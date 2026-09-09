"""Pinned API-key Anthropic Messages transport; no native tool or credential chain."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any, cast

import httpx2
from httpx2 import AsyncClient
from pydantic_ai.exceptions import ModelAPIError
from pydantic_ai.models import Model

from agent_fleet.adapters.runtime.openai_transport_policy import new_stateless_cookie_jar
from agent_fleet.adapters.runtime.provider_lifecycle import close_provider_clients
from agent_fleet.adapters.runtime.provider_selection import provider_policy_issue
from agent_fleet.adapters.runtime.single_send import (
    SingleSendGate,
    SingleSendModel,
    send_policy_error,
)
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.security import Redactor

_HOST = "api.anthropic.com"
_HEADERS = frozenset(
    {
        "accept",
        "accept-encoding",
        "connection",
        "content-length",
        "content-type",
        "host",
        "user-agent",
        "x-api-key",
        "anthropic-version",
        "x-stainless-arch",
        "x-stainless-async",
        "x-stainless-lang",
        "x-stainless-os",
        "x-stainless-package-version",
        "x-stainless-read-timeout",
        "x-stainless-retry-count",
        "x-stainless-runtime",
        "x-stainless-runtime-version",
        "x-stainless-timeout",
    }
)
_BODY_KEYS = frozenset(
    {
        "model",
        "max_tokens",
        "messages",
        "system",
        "tools",
        "tool_choice",
        "stream",
        "stop_sequences",
        "thinking",
        "service_tier",
    }
)


def require_anthropic_policy() -> None:
    issue = provider_policy_issue("anthropic")
    if issue is not None:
        raise FleetError(
            ErrorCode.PROVIDER_FAILED,
            issue,
            "Remove ambient header/logging customization; Fleet does not alter global settings.",
        )


def _local_content(content: object, *, results: bool = True) -> bool:
    if isinstance(content, str):
        return True
    if not isinstance(content, list):
        return False
    for block in content:
        if not isinstance(block, dict):
            return False
        kind = block.get("type")
        if kind == "text":
            if set(block) != {"type", "text"} or not isinstance(block["text"], str):
                return False
        elif kind == "tool_use" and results:
            if (
                set(block) != {"type", "id", "name", "input"}
                or not isinstance(block["input"], dict)
                or not isinstance(block["id"], str)
                or not isinstance(block["name"], str)
            ):
                return False
        elif kind == "tool_result" and results:
            if (
                set(block) - {"type", "tool_use_id", "content", "is_error"}
                or not isinstance(block.get("tool_use_id"), str)
                or not _local_content(block.get("content"), results=False)
                or ("is_error" in block and type(block["is_error"]) is not bool)
            ):
                return False
        else:
            return False
    return True


def _local_payload(body: object, model: str) -> bool:
    if not isinstance(body, dict) or set(body) - _BODY_KEYS:
        return False
    if (
        body.get("model") != model
        or body.get("stream", False) is not False
        or type(body.get("max_tokens")) is not int
        or not 1 <= body["max_tokens"] <= 1_000_000
        or body.get("thinking", {"type": "disabled"}) != {"type": "disabled"}
        or body.get("service_tier", "standard_only") != "standard_only"
        or not _local_content(body.get("system", ""), results=False)
    ):
        return False
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        return False
    for message in messages:
        if (
            not isinstance(message, dict)
            or set(message) != {"role", "content"}
            or message["role"] not in {"user", "assistant"}
            or not _local_content(message["content"])
        ):
            return False
    tools = body.get("tools", [])
    if not isinstance(tools, list):
        return False
    for tool in tools:
        if (
            not isinstance(tool, dict)
            or set(tool) - {"type", "name", "description", "input_schema", "strict"}
            or tool.get("type", "custom") != "custom"
            or not isinstance(tool.get("name"), str)
            or not isinstance(tool.get("input_schema"), dict)
        ):
            return False
    return True


def anthropic_request_guard(
    credential: str, model: str, redactor: Redactor, gate: SingleSendGate
) -> Callable[[httpx2.Request], Awaitable[None]]:
    async def guard(request: httpx2.Request) -> None:
        valid = False
        try:
            names = [name.lower() for name, _ in request.headers.multi_items()]
            valid = (
                request.method == "POST"
                and request.url.scheme == "https"
                and request.url.host == _HOST
                and request.url.port in {None, 443}
                and not request.url.username
                and not request.url.password
                and not request.url.fragment
                and request.url.path == "/v1/messages"
                and request.url.query in {b"", b"beta=true"}
                and len(names) == len(set(names))
                and set(names) <= _HEADERS
                and request.headers.get_list("host") == [_HOST]
                and request.headers.get_list("x-api-key") == [credential]
                and request.headers.get_list("anthropic-version") == ["2023-06-01"]
                and request.headers.get_list("content-length") == [str(len(request.content))]
                and not redactor.contains_secret(request.content)
                and _local_payload(json.loads(request.content), model)
            )
        except (AttributeError, TypeError, ValueError):
            pass
        if not valid:
            raise send_policy_error()
        gate.consume()
        request.headers.clear()
        request.headers.update(
            {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Host": _HOST,
                "X-Api-Key": credential,
                "anthropic-version": "2023-06-01",
                "User-Agent": "agent-fleet-pydantic-ai-runtime",
                "Content-Length": str(len(request.content)),
            }
        )

    return guard


def anthropic_response_guard(redactor: Redactor) -> Callable[[httpx2.Response], Awaitable[None]]:
    async def guard(response: httpx2.Response) -> None:
        invalid = False
        try:
            invalid = redactor.contains_secret_data(list(response.headers.multi_items()))
            response.headers.clear()
            response.headers["Content-Type"] = "application/json"
        except (AttributeError, TypeError, ValueError):
            invalid = True
        if invalid:
            raise FleetError(
                ErrorCode.PROVIDER_FAILED,
                "The provider response violated the pinned transport policy.",
                "Inspect the retained request accounting without replaying an unknown request.",
                details={
                    "runtime_diagnostic": {
                        "category": "provider_sdk",
                        "cause_category": "response_policy",
                    }
                },
            )

    return guard


@asynccontextmanager
async def open_anthropic_model(
    model: str, credential: str, redactor: Redactor, *, timeout_seconds: float
) -> AsyncIterator[Model]:
    require_anthropic_policy()
    # Import only after the logging/environment policy: importing the SDK itself
    # can configure global logging from ANTHROPIC_LOG.
    import anthropic
    from pydantic_ai.models.anthropic import AnthropicModel, AnthropicModelSettings
    from pydantic_ai.providers.anthropic import AnthropicProvider

    class ExplicitKeyClient(anthropic.AsyncAnthropic):
        """Pinned SDK subclass skips base-client profile-warning discovery probes."""

    gate = SingleSendGate()
    transport = AsyncClient(
        trust_env=False,
        follow_redirects=False,
        timeout=timeout_seconds,
        cookies=new_stateless_cookie_jar(),
        event_hooks={
            "request": [anthropic_request_guard(credential, model, redactor, gate)],
            "response": [anthropic_response_guard(redactor)],
        },
    )
    mapped: FleetError | None = None
    client: anthropic.AsyncAnthropic | None = None
    try:
        client = ExplicitKeyClient(
            api_key=credential,
            webhook_key="",
            base_url=f"https://{_HOST}",
            max_retries=0,
            timeout=timeout_seconds,
            http_client=transport,
            default_headers={"X-Api-Key": credential, "Host": _HOST},
        )
        yield SingleSendModel(
            AnthropicModel(
                cast(Any, model),
                provider=AnthropicProvider(anthropic_client=client),
                settings=AnthropicModelSettings(
                    anthropic_thinking={"type": "disabled"},
                    anthropic_service_tier="standard_only",
                ),
            ),
            gate,
            expected_model=model,
        )
    except (anthropic.AnthropicError, ModelAPIError) as error:
        timeout = False
        cause = "unknown"
        status: int | None = None
        current: BaseException | None = error
        seen: set[int] = set()
        for _ in range(8):
            if current is None or id(current) in seen:
                break
            seen.add(id(current))
            for kind, label in (
                (anthropic.APITimeoutError, "api_timeout"),
                (anthropic.APIConnectionError, "api_connection"),
                (anthropic.APIResponseValidationError, "api_response_validation"),
                (anthropic.AuthenticationError, "api_authentication"),
                (anthropic.PermissionDeniedError, "api_permission"),
                (anthropic.RateLimitError, "api_rate_limit"),
                (anthropic.APIStatusError, "api_status"),
            ):
                if isinstance(current, kind):
                    cause = label
                    timeout = label == "api_timeout"
                    break
            if isinstance(current, anthropic.APIStatusError):
                candidate = current.status_code
                if type(candidate) is int and 100 <= candidate <= 599:
                    status = candidate
            if isinstance(current, FleetError):
                detail = current.details.get("runtime_diagnostic")
                if type(detail) is dict and detail.get("cause_category") in {
                    "request_policy",
                    "response_policy",
                }:
                    cause = detail["cause_category"]
            current = current.__cause__ if current.__cause__ is not None else current.__context__
        mapped = FleetError(
            ErrorCode.RUNTIME_TIMEOUT if timeout else ErrorCode.PROVIDER_FAILED,
            "The configured Anthropic model request failed.",
            "Review the selected model and retained request accounting before a new attempt.",
            details={
                "runtime_diagnostic": {
                    "category": "provider_timeout" if timeout else "provider_sdk",
                    "cause_category": cause,
                    **({"http_status": status} if status is not None else {}),
                }
            },
        )
    finally:
        if client is None:
            await close_provider_clients(transport.aclose)
        else:
            await close_provider_clients(client.close, transport.aclose)
    if mapped is not None:
        raise mapped from None
