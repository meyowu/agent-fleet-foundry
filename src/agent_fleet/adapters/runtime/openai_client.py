"""Shared pinned OpenAI client construction, never a Harness execution boundary."""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from openai import AsyncOpenAI, DefaultAsyncHttpxClient

from agent_fleet.adapters.runtime.openai_transport_policy import (
    OpenAIRequestPolicyError,
    OpenAIResponsePolicyError,
    new_stateless_cookie_jar,
)
from agent_fleet.adapters.runtime.provider_lifecycle import close_provider_clients
from agent_fleet.adapters.runtime.single_send import SingleSendGate
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.security import Redactor

_OPENAI_API_BASE_URL = "https://api.openai.com/v1"
_OPENAI_API_HOST = "api.openai.com"
_OPENAI_API_PATHS = frozenset({"/v1/chat/completions", "/v1/responses"})
_OPENAI_SDK_REQUEST_HEADERS = frozenset(
    {
        "accept",
        "accept-encoding",
        "authorization",
        "connection",
        "content-length",
        "content-type",
        "host",
        "openai-organization",
        "openai-project",
        "user-agent",
        "x-stainless-arch",
        "x-stainless-async",
        "x-stainless-lang",
        "x-stainless-os",
        "x-stainless-package-version",
        "x-stainless-read-timeout",
        "x-stainless-retry-count",
        "x-stainless-runtime",
        "x-stainless-runtime-version",
    }
)


def reject_ambient_openai_custom_headers() -> None:
    if "OPENAI_CUSTOM_HEADERS" in os.environ:
        raise FleetError(
            ErrorCode.PROVIDER_FAILED,
            "Ambient OpenAI custom headers are not permitted for the BYOK runtime.",
            "Unset OPENAI_CUSTOM_HEADERS for the Fleet process and retry; Fleet does not "
            "mutate global environment state.",
        )


def reject_unsafe_openai_environment() -> None:
    """Stricter precredential admission for the new Agents SDK loop."""
    reject_ambient_openai_custom_headers()
    namespaces = ("openai", "httpx2", "httpcore2")
    names = set(namespaces) | {
        name
        for name in logging.Logger.manager.loggerDict
        if any(name.startswith(prefix + ".") for prefix in namespaces)
    }
    if "OPENAI_LOG" in os.environ or any(
        logging.getLogger(name).isEnabledFor(logging.INFO) for name in names
    ):
        raise FleetError(
            ErrorCode.PROVIDER_FAILED,
            "Verbose provider transport logging is not permitted for the Agents SDK runtime.",
            "Remove ambient logging customization; Fleet does not alter global settings.",
        )


@asynccontextmanager
async def open_openai_client(
    *,
    raw_credential: str,
    redactor: Redactor,
    timeout_seconds: float,
    gate: SingleSendGate | None = None,
    raw_responses: bool = False,
    response_observer: Callable[[Any], Awaitable[None]] | None = None,
    client_factory: Callable[..., Any] | None = None,
    transport_factory: Callable[..., Any] | None = None,
) -> AsyncIterator[AsyncOpenAI]:
    """Construct explicit clients and retain ownership through actual cleanup.

    Factories are trusted in-process adapter/test seams, not user configuration.
    PydanticAI retains its existing admission policy; the new ticketed SDK path
    repeats its stricter logging check before constructing any SDK request.
    """
    if type(raw_responses) is not bool or (raw_responses and gate is None):
        raise OpenAIRequestPolicyError()
    reject_ambient_openai_custom_headers()
    if gate is not None:
        reject_unsafe_openai_environment()
    proven_guard = _openai_request_guard(raw_credential, redactor, raw_responses=raw_responses)
    proven_response_guard = _openai_response_guard(redactor)

    async def guarded_request(request: Any) -> None:
        await proven_guard(request)
        if gate is not None:
            if (
                request.url.path != "/v1/responses"
                or request.url.query
                or request.url.fragment
                or request.url.username
                or request.url.password
            ):
                raise OpenAIRequestPolicyError()
            gate.consume()

    async def guarded_response(response: Any) -> None:
        await proven_response_guard(response)
        if response_observer is not None:
            await response_observer(response)

    http_client = (transport_factory or DefaultAsyncHttpxClient)(
        trust_env=False,
        follow_redirects=False,
        cookies=new_stateless_cookie_jar(),
        event_hooks={
            "request": [guarded_request],
            "response": [guarded_response],
        },
    )
    client: Any = None
    try:
        client = (client_factory or AsyncOpenAI)(
            api_key=raw_credential,
            admin_api_key="",
            organization="",
            project="",
            webhook_secret="",
            base_url=_OPENAI_API_BASE_URL,
            default_headers={
                "Authorization": f"Bearer {raw_credential}",
                "Host": _OPENAI_API_HOST,
            },
            http_client=http_client,
            max_retries=0,
            timeout=timeout_seconds,
        )
        yield client
    finally:
        if client is None:
            await close_provider_clients(http_client.aclose)
        else:

            async def close_sdk() -> None:
                await client.__aexit__(None, None, None)

            await close_provider_clients(close_sdk, http_client.aclose)


def _openai_request_guard(
    raw_credential: str, redactor: Redactor, *, raw_responses: bool = False
) -> Any:
    """Validate and minimize the SDK's fully merged request before transmission."""

    async def guard(request: Any) -> None:
        try:
            url_is_allowed = (
                request.method == "POST"
                and request.url.scheme == "https"
                and request.url.host == _OPENAI_API_HOST
                and request.url.port in {None, 443}
                and request.url.path in _OPENAI_API_PATHS
            )
            header_items = list(request.headers.multi_items())
            header_names = [name.casefold() for name, _ in header_items]
            host_values = request.headers.get_list("host")
            authorization_values = request.headers.get_list("authorization")
            organization_values = request.headers.get_list("openai-organization")
            project_values = request.headers.get_list("openai-project")
            content_length_values = request.headers.get_list("content-length")
            request_content_length = str(len(request.content))
            raw_values = request.headers.get_list("x-stainless-raw-response")
            allowed_headers = _OPENAI_SDK_REQUEST_HEADERS | (
                {"x-stainless-raw-response"} if raw_responses else set()
            )
            headers_are_allowed = (
                len(header_names) == len(set(header_names))
                and set(header_names) <= allowed_headers
                and raw_values == (["true"] if raw_responses else [])
                and organization_values in ([], [""])
                and project_values in ([], [""])
                and content_length_values == [request_content_length]
            )
            body_is_allowed = not redactor.contains_secret(request.content)
        except (AttributeError, TypeError, ValueError):
            url_is_allowed = False
            headers_are_allowed = False
            body_is_allowed = False
            host_values = []
            authorization_values = []
            content_length_values = []
        if (
            not url_is_allowed
            or not headers_are_allowed
            or not body_is_allowed
            or host_values != [_OPENAI_API_HOST]
            or authorization_values != [f"Bearer {raw_credential}"]
        ):
            # Preserve SDK-family propagation while exposing only a fixed policy cause
            # to the outer adapter, never untrusted request details.
            raise OpenAIRequestPolicyError()

        safe_headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {raw_credential}",
            "Content-Type": "application/json",
            "Host": _OPENAI_API_HOST,
            "User-Agent": "agent-fleet-pydantic-ai-runtime",
        }
        safe_headers["Content-Length"] = content_length_values[0]
        if raw_responses:
            safe_headers["x-stainless-raw-response"] = "true"
        request.headers.clear()
        request.headers.update(safe_headers)

    return guard


def _openai_response_guard(redactor: Redactor) -> Any:
    """Remove untrusted response headers before provider SDK logging or parsing."""

    async def guard(response: Any) -> None:
        policy_failed = False
        header_items: list[tuple[str, str]] = []
        try:
            header_items = list(response.headers.multi_items())
            policy_failed = redactor.contains_secret_data(header_items)
            response.headers.clear()
            # Phase 2 uses non-streaming JSON endpoints only. Supplying a constant
            # content type preserves SDK parsing without retaining provider-controlled
            # values such as x-request-id, Location, Set-Cookie, or tracing headers.
            response.headers["Content-Type"] = "application/json"
        except (AttributeError, TypeError, ValueError):
            policy_failed = True
        if policy_failed:
            raise OpenAIResponsePolicyError()

    return guard
