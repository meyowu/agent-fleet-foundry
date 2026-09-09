"""Pinned Gemini Developer API transport behind the real PydanticAI Google model."""

from __future__ import annotations

import json
import logging
import math
import os
import re
import ssl
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any, cast

import certifi
import httpx2
from httpx2 import AsyncClient as AsyncClient
from httpx2 import Client as Client
from pydantic import BaseModel
from pydantic_ai.exceptions import ModelAPIError, UserError
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    SystemPromptPart,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.settings import ModelSettings

from agent_fleet.adapters.runtime.google_response_policy import (
    MAX_BODY_BYTES,
    RawGoogleReceipt,
    bounded_json,
    policy_error,
)
from agent_fleet.adapters.runtime.openai_transport_policy import new_stateless_cookie_jar
from agent_fleet.adapters.runtime.provider_lifecycle import close_provider_clients
from agent_fleet.adapters.runtime.single_send import SingleSendGate, send_policy_error
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.security import Redactor

_HOST = "generativelanguage.googleapis.com"
_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_HEADERS = frozenset(
    {
        "host",
        "accept",
        "accept-encoding",
        "connection",
        "content-length",
        "content-type",
        "user-agent",
        "x-goog-api-key",
        "x-goog-api-client",
        "x-server-timeout",
    }
)
_ENV_DENIED = (
    "GOOGLE_GENAI_CLIENT_MODE",
    "GOOGLE_GENAI_REPLAYS_DIRECTORY",
    "GOOGLE_GENAI_REPLAY_ID",
    "GOOGLE_SDK_PYTHON_LOGGING_SCOPE",
    "GOOGLE_GENAI_LOG_LEVEL",
    "GOOGLE_GENAI_CUSTOM_HEADERS",
)


def require_google_policy() -> None:
    """Check names/log levels only, before SDK import or credential resolution."""
    # The qualified wheel names its loggers google_genai.*, not just google.*.
    namespaces = ("google", "google_genai", "httpx2", "httpcore2")
    names = set(namespaces) | {
        name
        for name in logging.Logger.manager.loggerDict
        if any(name.startswith(prefix + ".") for prefix in namespaces)
    }
    if any(name in os.environ for name in _ENV_DENIED) or any(
        logging.getLogger(name).isEnabledFor(logging.INFO) for name in names
    ):
        raise FleetError(
            ErrorCode.PROVIDER_FAILED,
            "Ambient Google replay or verbose transport logging is not permitted.",
            "Remove ambient customization; Fleet does not modify global settings.",
        )


def _parts(value: object, *, system: bool = False) -> bool:
    if type(value) is not dict or set(value) - {"parts", "role"}:
        return False
    if value.get("role") not in ({None, "user"} if system else {"user", "model"}):
        return False
    parts = value.get("parts")
    if type(parts) is not list or not 1 <= len(parts) <= 128:
        return False
    for part in parts:
        if type(part) is not dict or set(part) - {
            "text",
            "thought",
            "thoughtSignature",
            "functionCall",
            "functionResponse",
        }:
            return False
        kinds = set(part) & {"text", "functionCall", "functionResponse"}
        if len(kinds) != 1 or (system and kinds != {"text"}):
            return False
        if "thought" in part and type(part["thought"]) is not bool:
            return False
        if "thoughtSignature" in part and (
            type(part["thoughtSignature"]) is not str or len(part["thoughtSignature"]) > 16384
        ):
            return False
        if "text" in part:
            if type(part["text"]) is not str:
                return False
        else:
            key = next(iter(kinds))
            call = part[key]
            data_key = "args" if key == "functionCall" else "response"
            if (
                type(call) is not dict
                or set(call) - {"name", "id", data_key}
                or type(call.get("name")) is not str
                or not _MODEL.fullmatch(call["name"])
                or type(call.get(data_key)) is not dict
                or ("id" in call and (type(call["id"]) is not str or len(call["id"]) > 128))
            ):
                return False
    return True


def _declarations(tools: object, *, wire: bool) -> frozenset[str]:
    key = "functionDeclarations" if wire else "function_declarations"
    # google-genai 2.18.0 deliberately keeps this JSON-schema field in snake case
    # in the Developer API request, unlike functionDeclarations around it.
    schema_key = "parameters_json_schema"
    if type(tools) is not list or not 1 <= len(tools) <= 64:
        raise ValueError("Only bounded plain function tools are admitted")
    names: set[str] = set()
    for tool in tools:
        if type(tool) is not dict or set(tool) != {key} or type(tool[key]) is not list:
            raise ValueError("Native/callable/MCP tools are not admitted")
        for definition in tool[key]:
            if (
                type(definition) is not dict
                or set(definition) - {"name", "description", schema_key}
                or type(definition.get("name")) is not str
                or not _MODEL.fullmatch(definition["name"])
                or definition["name"] in names
                or type(definition.get(schema_key)) is not dict
                or type(definition.get("description", "")) is not str
            ):
                raise ValueError("Invalid local function declaration")
            names.add(definition["name"])
    if not 1 <= len(names) <= 64:
        raise ValueError("Invalid function count")
    return frozenset(names)


def _payload(body: dict[str, Any]) -> frozenset[str]:
    if set(body) - {"contents", "systemInstruction", "tools", "toolConfig", "generationConfig"}:
        raise ValueError("Unsupported request feature")
    contents = body.get("contents")
    if (
        type(contents) is not list
        or not 1 <= len(contents) <= 256
        or not all(_parts(item) for item in contents)
    ):
        raise ValueError("Invalid request content")
    if "systemInstruction" in body and not _parts(body["systemInstruction"], system=True):
        raise ValueError("Invalid system instruction")
    generation = body.get("generationConfig")
    if (
        type(generation) is not dict
        or set(generation) - {"maxOutputTokens", "responseModalities"}
        or type(generation.get("maxOutputTokens")) is not int
        or not 1 <= generation["maxOutputTokens"] <= 1_000_000
        or generation.get("responseModalities") != ["TEXT"]
    ):
        raise ValueError("Invalid generation bounds")
    names = _declarations(body.get("tools"), wire=True)
    config = body.get("toolConfig")
    if type(config) is not dict or set(config) != {"functionCallingConfig"}:
        raise ValueError("Unsupported tool configuration")
    calling = config["functionCallingConfig"]
    if (
        type(calling) is not dict
        or set(calling) - {"mode", "allowedFunctionNames"}
        or calling.get("mode") not in {"AUTO", "ANY", "VALIDATED", "NONE"}
        or (
            "allowedFunctionNames" in calling
            and (
                type(calling["allowedFunctionNames"]) is not list
                or any(
                    type(name) is not str or name not in names
                    for name in calling["allowedFunctionNames"]
                )
            )
        )
    ):
        raise ValueError("Invalid function selection")
    return names


def google_request_guard(
    credential: str, model: str, redactor: Redactor, gate: SingleSendGate, receipt: RawGoogleReceipt
) -> Callable[[httpx2.Request], Awaitable[None]]:
    async def guard(request: httpx2.Request) -> None:
        valid = False
        names: frozenset[str] = frozenset()
        try:
            headers = [key.lower() for key, _ in request.headers.multi_items()]
            valid = (
                request.method == "POST"
                and request.url.scheme == "https"
                and request.url.host == _HOST
                and request.url.port in {None, 443}
                and not request.url.username
                and not request.url.password
                and not request.url.query
                and not request.url.fragment
                and request.url.path == f"/v1beta/models/{model}:generateContent"
                and len(headers) == len(set(headers))
                and set(headers) <= _HEADERS
                and request.headers.get_list("host") == [_HOST]
                and request.headers.get_list("x-goog-api-key") == [credential]
                and request.headers.get_list("content-type") == ["application/json"]
                and request.headers.get_list("content-length") == [str(len(request.content))]
                and 1 <= len(request.content) <= MAX_BODY_BYTES
                and not redactor.contains_secret(request.content)
            )
            if valid:
                names = _payload(bounded_json(request.content))
        except (ValueError, TypeError, AttributeError, RecursionError):
            valid = False
        if not valid:
            raise send_policy_error()
        gate.consume()
        receipt.bind_tools(names)
        request.headers.clear()
        request.headers.update(
            {
                "Host": _HOST,
                "X-Goog-Api-Key": credential,
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Content-Length": str(len(request.content)),
                "User-Agent": "agent-fleet-pydantic-ai-runtime",
            }
        )

    return guard


def _deny_sync(request: httpx2.Request) -> None:
    raise send_policy_error()


def _require_local_messages(messages: list[ModelMessage]) -> None:
    """Reject media before PydanticAI's message mapper can fetch a URL/file."""
    invalid = False
    try:
        for message in messages:
            if type(message) not in {ModelRequest, ModelResponse}:
                raise ValueError("Unsupported message")
            for part in message.parts:
                if type(part) not in {
                    SystemPromptPart,
                    UserPromptPart,
                    TextPart,
                    ThinkingPart,
                    ToolReturnPart,
                    ToolCallPart,
                    RetryPromptPart,
                }:
                    raise ValueError("Native or unsupported message part")
                if isinstance(part, SystemPromptPart | UserPromptPart | TextPart | ThinkingPart):
                    if type(part.content) is not str:
                        raise ValueError("Only text content is admitted")
                elif isinstance(part, ToolReturnPart):
                    json.dumps(part.content, allow_nan=False)
                elif isinstance(part, ToolCallPart):
                    if part.args is not None:
                        json.dumps(part.args, allow_nan=False)
                elif isinstance(part, RetryPromptPart):
                    json.dumps(part.content, allow_nan=False)
                else:
                    raise ValueError("Native or unsupported message part")
    except (ValueError, TypeError, AttributeError, RecursionError):
        invalid = True
    if invalid:
        raise send_policy_error()


def _mapped_error(error: BaseException) -> FleetError:
    from google.genai import errors

    timeout = False
    status: int | None = None
    current: BaseException | None = error
    seen: set[int] = set()
    for _ in range(8):
        if current is None or id(current) in seen:
            break
        seen.add(id(current))
        candidate = (
            getattr(current, "code", None)
            if isinstance(current, errors.APIError)
            else getattr(current, "status_code", None)
            if isinstance(current, ModelAPIError)
            else None
        )
        if type(candidate) is int and 100 <= candidate <= 599:
            status = candidate
        timeout = timeout or isinstance(current, httpx2.TimeoutException)
        current = current.__cause__ or current.__context__
    cause = (
        "api_timeout"
        if timeout
        else {
            401: "api_authentication",
            403: "api_permission",
            429: "api_rate_limit",
        }.get(status if status is not None else 0, "api_status" if status else "unknown")
    )
    return FleetError(
        ErrorCode.RUNTIME_TIMEOUT if timeout else ErrorCode.PROVIDER_FAILED,
        "The configured Google model request failed.",
        "Inspect the retained request accounting before starting a new attempt.",
        details={
            "runtime_diagnostic": {
                "category": "provider_timeout" if timeout else "provider_sdk",
                "cause_category": cause,
                **({"http_status": status} if status is not None else {}),
            }
        },
    )


class _GoogleReceiptModel(WrapperModel):
    def __init__(self, model: Model, gate: SingleSendGate, receipt: RawGoogleReceipt) -> None:
        super().__init__(model)
        self._gate, self._receipt = gate, receipt

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        require_google_policy()
        from google.genai import errors

        mapped: FleetError
        try:
            return await self._request(messages, model_settings, model_request_parameters)
        except FleetError as error:
            mapped = error
        except (errors.APIError, ModelAPIError, httpx2.HTTPError, UserError, ValueError) as error:
            mapped = _mapped_error(error)
        # Mapping here precedes the factory's generator exception context and
        # the SDK's value-bearing exception can no longer escape to the harness.
        mapped.__cause__ = mapped.__context__ = None
        if hasattr(mapped, "__notes__"):
            del mapped.__notes__
        raise mapped from None

    async def _request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        _require_local_messages(messages)
        with self._gate.request(), self._receipt.request():
            response = await self.wrapped.request(
                messages, model_settings, model_request_parameters
            )
            input_tokens, output_tokens, total, cache = self._receipt.consume()
            actual = response.usage
            if (
                response.model_name != self._receipt.model
                or type(actual.input_tokens) is not int
                or actual.input_tokens != input_tokens
                or type(actual.output_tokens) is not int
                or actual.output_tokens != output_tokens
                or actual.total_tokens != total
                or actual.cache_read_tokens != cache
            ):
                raise policy_error()
            # Google can omit function-call IDs. PydanticAI's generated IDs are
            # local RAM continuation identifiers, never provider evidence IDs.
            return response


@asynccontextmanager
async def open_google_model(
    model: str,
    credential: str,
    redactor: Redactor,
    *,
    timeout_seconds: float,
    terminal_outputs: dict[str, type[BaseModel]],
) -> AsyncIterator[Model]:
    require_google_policy()
    if (
        not _MODEL.fullmatch(model)
        or not credential
        or credential != credential.strip()
        or not math.isfinite(timeout_seconds)
        or not 0 < timeout_seconds <= 3600
        or not terminal_outputs
        or len(terminal_outputs) > 2
        or any(
            not name.startswith("submit_") or not issubclass(output, BaseModel)
            for name, output in terminal_outputs.items()
        )
    ):
        raise send_policy_error()
    redactor.register_secret(credential)
    # These imports must remain after the ambient replay/logging policy.
    from google import genai
    from google.genai import errors, types
    from google.genai.client import DebugConfig
    from pydantic_ai.models.google import GoogleModel
    from pydantic_ai.providers.google import GoogleProvider

    class BoundedGoogleModel(GoogleModel):
        async def _build_content_and_config(
            self,
            messages: list[ModelMessage],
            model_settings: Any,
            model_request_parameters: ModelRequestParameters,
        ) -> Any:
            if (
                model_request_parameters.native_tools
                or set(model_settings) - {"max_tokens", "timeout", "parallel_tool_calls"}
                or model_settings.get("parallel_tool_calls", False) is not False
            ):
                raise send_policy_error()
            contents, config = await super()._build_content_and_config(
                messages, model_settings, model_request_parameters
            )
            invalid = False
            try:
                _declarations(config.get("tools"), wire=False)
            except (ValueError, TypeError):
                invalid = True
            if invalid:
                raise send_policy_error()
            config["automatic_function_calling"] = {"disable": True}
            config["response_modalities"] = ["TEXT"]
            # PydanticAI contributes `User-Agent`, while this SDK already has
            # `user-agent`. Drop the trusted model builder's redundant label;
            # the final transport still rejects every duplicate header.
            http_options = config.get("http_options")
            if http_options is None:
                raise send_policy_error()
            http_options["headers"] = {"Content-Type": "application/json"}
            return contents, config

    gate = SingleSendGate()
    receipt = RawGoogleReceipt(model, redactor, dict(terminal_outputs))
    context = ssl.create_default_context(cafile=certifi.where())
    sync: httpx2.Client | None = None
    asynchronous: httpx2.AsyncClient | None = None
    client: genai.Client | None = None
    mapped: FleetError | None = None
    try:
        sync = Client(
            verify=context,
            trust_env=False,
            follow_redirects=False,
            timeout=timeout_seconds,
            cookies=new_stateless_cookie_jar(),
            event_hooks={"request": [_deny_sync]},
        )
        asynchronous = AsyncClient(
            verify=context,
            trust_env=False,
            follow_redirects=False,
            timeout=timeout_seconds,
            cookies=new_stateless_cookie_jar(),
            event_hooks={
                "request": [google_request_guard(credential, model, redactor, gate, receipt)],
                "response": [receipt.observe],
            },
        )
        client = genai.Client(
            enterprise=False,
            vertexai=False,
            api_key=credential,
            debug_config=DebugConfig(client_mode=None, replays_directory=None, replay_id=None),
            http_options=types.HttpOptions(
                base_url=f"https://{_HOST}",
                api_version="v1beta",
                timeout=max(1, int(timeout_seconds * 1000)),
                retry_options=types.HttpRetryOptions(attempts=1),
                httpx_client=sync,
                httpx_async_client=asynchronous,
                client_args={"verify": context},
                async_client_args={"verify": context, "ssl": context},
            ),
        )
        yield _GoogleReceiptModel(
            BoundedGoogleModel(model, provider=GoogleProvider(client=client)), gate, receipt
        )
    except (errors.APIError, ModelAPIError, httpx2.HTTPError, UserError, ValueError) as error:
        mapped = _mapped_error(error)
    finally:
        closers: list[Callable[[], Awaitable[None]]] = []
        if client is not None:

            async def close_sdk_sync() -> None:
                cast(Any, client).close()

            closers.extend((close_sdk_sync, client.aio.aclose))
        if sync is not None:

            async def close_sync() -> None:
                cast(Any, sync).close()

            closers.append(close_sync)
        if asynchronous is not None:
            closers.append(asynchronous.aclose)
        if closers:
            await close_provider_clients(*closers)
    if mapped is not None:
        raise mapped from None
