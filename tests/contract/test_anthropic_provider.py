"""Actual Anthropic/PydanticAI serialization over a non-network test transport."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import socket
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx2
import pytest
from action_tool_fixtures import make_action_tools
from pydantic_ai.models import override_allow_model_requests
from test_pydantic_ai_runtime import RecordingCatalog, StaticSecretStore
from test_runtime_budgets import _ledger
from test_runtime_conformance import expected_output, request

import agent_fleet.adapters.runtime.anthropic_provider as provider_module
from agent_fleet.adapters.runtime.pydantic_ai import PydanticAIRuntimeAdapter
from agent_fleet.adapters.runtime.single_send import SingleSendGate
from agent_fleet.domain.budgets import RunBudgetLimits, RuntimeAttemptStatus
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import (
    AgentRole,
    RuntimeConfiguration,
    RuntimeCredentialCheck,
    RuntimeToolDefinition,
)
from agent_fleet.domain.security import Redactor
from agent_fleet.ports.runtime import EMPTY_RUNTIME_TOOL_CATALOG, RuntimeInvocationServices

_KEY = "fleet-anthropic-offline-selected-credential"
_MODEL = "claude-haiku-4-5-20251001"
_CONFIG = RuntimeConfiguration(
    runtime_name="pydantic-ai",
    provider_model=f"anthropic:{_MODEL}",
    credential_ref="env:FLEET_ANTHROPIC_OFFLINE",
    max_retries=0,
    max_requests=4,
    max_total_tokens=4096,
    timeout_seconds=2,
)


@pytest.fixture(autouse=True)
def clean_transport_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_CUSTOM_HEADERS", raising=False)
    monkeypatch.delenv("ANTHROPIC_LOG", raising=False)

    def denied(*args: object, **kwargs: object) -> None:
        raise AssertionError("Offline Anthropic contracts cannot open sockets")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket, "create_connection", denied)


def configure_transport(
    monkeypatch: pytest.MonkeyPatch,
    response: Callable[[httpx2.Request], httpx2.Response] | Callable[[httpx2.Request], Any],
) -> list[httpx2.AsyncClient]:
    clients: list[httpx2.AsyncClient] = []

    def create(**arguments: Any) -> httpx2.AsyncClient:
        assert arguments["trust_env"] is False
        assert arguments["follow_redirects"] is False
        client = httpx2.AsyncClient(transport=httpx2.MockTransport(response), **arguments)
        clients.append(client)
        return client

    monkeypatch.setattr(provider_module, "AsyncClient", create)
    return clients


def output_response(
    received: httpx2.Request, content: list[dict[str, object]], *, usage: object = None
) -> httpx2.Response:
    return httpx2.Response(
        200,
        request=received,
        json={
            "id": "msg_offline",
            "type": "message",
            "role": "assistant",
            "model": _MODEL,
            "content": content,
            "stop_reason": "tool_use",
            "stop_sequence": None,
            "usage": usage if usage is not None else {"input_tokens": 10, "output_tokens": 5},
        },
    )


def output_block(body: dict[str, Any], kind: AgentRole, role: str) -> dict[str, object]:
    output = next(tool["name"] for tool in body["tools"] if tool["name"].startswith("submit_"))
    return {
        "type": "tool_use",
        "id": "result_final",
        "name": output,
        "input": expected_output(kind, role).model_dump(mode="json"),
    }


@pytest.mark.parametrize(
    ("kind", "custom"),
    [(kind, False) for kind in AgentRole]
    + [(kind, True) for kind in AgentRole if kind is not AgentRole.COS],
)
async def test_actual_sdk_exact_model_key_and_typed_role_output(
    monkeypatch: pytest.MonkeyPatch, kind: AgentRole, custom: bool
) -> None:
    role = "custom-" + kind.value if custom else kind.value
    sent: list[httpx2.Request] = []

    def respond(received: httpx2.Request) -> httpx2.Response:
        sent.append(received)
        body = json.loads(received.content)
        assert body["model"] == _MODEL
        assert body["stream"] is False
        assert body["thinking"] == {"type": "disabled"}
        assert body["service_tier"] == "standard_only"
        return output_response(received, [output_block(body, kind, role)])

    clients = configure_transport(monkeypatch, respond)
    for name in (
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_PROFILE",
        "ANTHROPIC_CONFIG_DIR",
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_WEBHOOK_SIGNING_KEY",
        "HTTP_PROXY",
        "HTTPS_PROXY",
    ):
        monkeypatch.setenv(name, "ambient-must-not-be-used")
    secret_store = StaticSecretStore(_KEY)
    runtime = PydanticAIRuntimeAdapter(secret_store, Redactor([_KEY]))
    with override_allow_model_requests(True):
        result = await runtime.invoke(
            request(role),
            RuntimeInvocationServices(
                configuration=_CONFIG,
                tools=EMPTY_RUNTIME_TOOL_CATALOG,
                execution_kind=kind if custom else None,
            ),
        )
    assert result.output == expected_output(kind, role)
    assert result.usage is not None and result.usage.total_tokens == 15
    assert result.provider_metadata is not None
    assert result.provider_metadata.model == _CONFIG.provider_model
    assert len(sent) == secret_store.resolve_calls == len(clients) == 1
    assert all(client.is_closed for client in clients)
    received = sent[0]
    assert str(received.url) == "https://api.anthropic.com/v1/messages?beta=true"
    assert received.headers["x-api-key"] == _KEY
    assert "authorization" not in received.headers and "cookie" not in received.headers
    assert _KEY not in received.content.decode()
    assert "ambient-must-not-be-used" not in str(received.headers)
    assert "ambient-must-not-be-used" not in received.content.decode()


async def test_actual_sdk_projects_read_pattern_into_description_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tools = make_action_tools()
    seen: list[dict[str, Any]] = []

    def respond(received: httpx2.Request) -> httpx2.Response:
        body = json.loads(received.content)
        seen.append(body)
        read = next(tool for tool in body["tools"] if tool["name"] == "repo_read_file")
        schema = read["input_schema"]
        path = schema["properties"]["path"]
        original = next(d for d in tools.catalog.definitions if d.name == "repo_read_file")
        properties = original.parameters_json_schema["properties"]
        assert isinstance(properties, dict) and isinstance(properties["path"], dict)
        pattern = properties["path"]["pattern"]
        assert isinstance(pattern, str)
        assert read["strict"] is True
        # Pinned Anthropic strict transformation moves pattern to description.
        # Preserve this existing provider limitation; no regex enforcement claim.
        assert "pattern" not in path and f"pattern: {pattern}" in path["description"]
        assert re.search(pattern, "SRC/CANARY_CALC/CORE.PY")
        assert re.search(pattern, "README.md") is None
        assert re.search(pattern, "\u212a/\u017f")
        assert schema["additionalProperties"] is False and set(schema["required"]) == {
            "path",
            "reason",
        }
        assert "minLength" not in path and "maxLength" not in path
        assert "minLength: 1" in path["description"] and "maxLength: 4096" in path["description"]
        return output_response(received, [output_block(body, AgentRole.ENGINEER, "engineer")])

    clients = configure_transport(monkeypatch, respond)
    runtime = PydanticAIRuntimeAdapter(StaticSecretStore(_KEY), Redactor([_KEY]))
    with override_allow_model_requests(True):
        await runtime.invoke(
            tools.invocation, RuntimeInvocationServices(configuration=_CONFIG, tools=tools.catalog)
        )
    assert len(seen) == 1 and tools.gateway.calls == [] and tools.catalog.records == ()
    assert all(client.is_closed for client in clients)


async def test_actual_sdk_local_tool_loop_retains_headers_and_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[dict[str, Any]] = []
    catalog = RecordingCatalog(
        (
            RuntimeToolDefinition(
                name="repo_list_files",
                description="Bounded non-executing fixture.",
                parameters_json_schema={
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            ),
        )
    )

    def respond(received: httpx2.Request) -> httpx2.Response:
        body = json.loads(received.content)
        sent.append(body)
        if len(sent) == 1:
            assert catalog.calls == []
            response = output_response(
                received,
                [{"type": "tool_use", "id": "list_once", "name": "repo_list_files", "input": {}}],
            )
            response.headers["set-cookie"] = "provider-session=untrusted; Path=/"
            return response
        assert len(catalog.calls) == 1
        assert "cookie" not in received.headers
        assert "tool_result" in received.content.decode()
        return output_response(received, [output_block(body, AgentRole.ENGINEER, "engineer")])

    clients = configure_transport(monkeypatch, respond)
    runtime = PydanticAIRuntimeAdapter(StaticSecretStore(_KEY), Redactor([_KEY]))
    with override_allow_model_requests(True):
        result = await runtime.invoke(
            request("engineer"),
            RuntimeInvocationServices(
                configuration=_CONFIG,
                tools=catalog,
            ),
        )
    assert len(sent) == 2 and len(catalog.calls) == 1
    assert result.usage is not None and result.usage.requests == 2
    assert result.usage.total_tokens == 30
    assert all(client.is_closed and not list(client.cookies.jar) for client in clients)


@pytest.mark.parametrize("status", [302, 401, 403, 429, 500, 503])
async def test_actual_sdk_http_failure_never_retries_or_leaks(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    sends: list[httpx2.Request] = []

    def respond(received: httpx2.Request) -> httpx2.Response:
        sends.append(received)
        return httpx2.Response(
            status,
            request=received,
            headers={"location": "https://untrusted.invalid/"},
            json={"type": "error", "error": {"type": "api_error", "message": _KEY}},
        )

    clients = configure_transport(monkeypatch, respond)
    runtime = PydanticAIRuntimeAdapter(StaticSecretStore(_KEY), Redactor([_KEY]))
    with override_allow_model_requests(True), pytest.raises(FleetError) as captured:
        await runtime.invoke(
            request("engineer"),
            RuntimeInvocationServices(
                configuration=_CONFIG,
                tools=EMPTY_RUNTIME_TOOL_CATALOG,
            ),
        )
    assert len(sends) == 1 and all(client.is_closed for client in clients)
    assert captured.value.code is ErrorCode.PROVIDER_FAILED
    assert captured.value.__cause__ is None and captured.value.__context__ is None
    assert _KEY not in str(captured.value) and _KEY not in str(captured.value.details)


@pytest.mark.parametrize("name", ["ANTHROPIC_CUSTOM_HEADERS", "ANTHROPIC_LOG"])
async def test_ambient_customization_fails_before_credentials(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    monkeypatch.setenv(name, _KEY)
    store = StaticSecretStore(_KEY)
    runtime = PydanticAIRuntimeAdapter(store, Redactor([_KEY]))
    assert not runtime.preflight(_CONFIG, credential_check=RuntimeCredentialCheck.INSPECT).ready
    with pytest.raises(FleetError):
        await runtime.invoke(
            request("engineer"),
            RuntimeInvocationServices(
                configuration=_CONFIG,
                tools=EMPTY_RUNTIME_TOOL_CATALOG,
            ),
        )
    assert store.resolve_calls == store.inspect_calls == 0


@pytest.mark.parametrize(
    "name",
    [
        "anthropic._base_client",
        "httpx2",
        "httpcore2.http11",
        "httpcore2.http2",
        "httpx2.future_child",
    ],
)
@pytest.mark.parametrize("level", [logging.DEBUG, logging.INFO])
async def test_verbose_logging_fails_before_credentials(name: str, level: int) -> None:
    logger = logging.getLogger(name)
    original_level = logger.level
    logger.setLevel(level)
    try:
        store = StaticSecretStore(_KEY)
        runtime = PydanticAIRuntimeAdapter(store, Redactor([_KEY]))
        with pytest.raises(FleetError):
            await runtime.invoke(
                request("engineer"),
                RuntimeInvocationServices(
                    configuration=_CONFIG,
                    tools=EMPTY_RUNTIME_TOOL_CATALOG,
                ),
            )
        assert store.resolve_calls == 0
    finally:
        logger.setLevel(original_level)


async def test_actual_sdk_cancel_closes_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    entered = asyncio.Event()
    sends = 0

    async def respond(received: httpx2.Request) -> httpx2.Response:
        nonlocal sends
        sends += 1
        entered.set()
        await asyncio.Event().wait()
        raise AssertionError("cancelled transport cannot finish")

    clients = configure_transport(monkeypatch, respond)
    runtime = PydanticAIRuntimeAdapter(StaticSecretStore(_KEY), Redactor([_KEY]))
    with override_allow_model_requests(True):
        execution = asyncio.create_task(
            runtime.invoke(
                request("engineer"),
                RuntimeInvocationServices(
                    configuration=_CONFIG,
                    tools=EMPTY_RUNTIME_TOOL_CATALOG,
                ),
            )
        )
        try:
            await asyncio.wait_for(entered.wait(), timeout=2)
            execution.cancel()
            with pytest.raises(asyncio.CancelledError):
                await execution
        finally:
            if not execution.done():
                execution.cancel()
            await asyncio.gather(execution, return_exceptions=True)
    assert sends == 1 and all(client.is_closed for client in clients)


@pytest.mark.parametrize("extra_cancels", [1, 3])
async def test_repeated_cancel_waits_for_actual_sdk_transport_close_and_settles_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, extra_cancels: int
) -> None:
    entered = asyncio.Event()
    closing = asyncio.Event()
    release = asyncio.Event()
    closed = asyncio.Event()
    close_starts = 0
    ledger = _ledger(tmp_path, RunBudgetLimits(max_model_requests=2, max_total_tokens=8192))
    accounting = ledger.store.begin_attempt(ledger.request)

    async def respond(received: httpx2.Request) -> httpx2.Response:
        entered.set()
        await asyncio.Event().wait()
        raise AssertionError("cancelled request cannot complete")

    class HeldCloseTransport(httpx2.MockTransport):
        async def aclose(self) -> None:
            nonlocal close_starts
            close_starts += 1
            closing.set()
            await release.wait()
            await super().aclose()
            closed.set()

    physical = HeldCloseTransport(respond)
    clients: list[httpx2.AsyncClient] = []

    def create(**arguments: Any) -> httpx2.AsyncClient:
        client = httpx2.AsyncClient(transport=physical, **arguments)
        clients.append(client)
        return client

    monkeypatch.setattr(provider_module, "AsyncClient", create)
    runtime = PydanticAIRuntimeAdapter(StaticSecretStore(_KEY), Redactor([_KEY]))
    with override_allow_model_requests(True):
        execution = asyncio.create_task(
            runtime.invoke(
                ledger.request,
                RuntimeInvocationServices(
                    configuration=_CONFIG, tools=EMPTY_RUNTIME_TOOL_CATALOG, accounting=accounting
                ),
            )
        )
        try:
            await asyncio.wait_for(entered.wait(), timeout=2)
            execution.cancel()
            await asyncio.wait_for(closing.wait(), timeout=2)
            assert clients[0].is_closed  # This flag alone did not prove physical closure.
            for _ in range(extra_cancels):
                execution.cancel()
                await asyncio.sleep(0)
                assert not execution.done()
                assert not closed.is_set()
        finally:
            release.set()
            await asyncio.gather(execution, return_exceptions=True)
            accounting.finish(RuntimeAttemptStatus.CANCELLED)
    assert execution.cancelled()
    assert closed.is_set() and close_starts == 1
    snapshot = ledger.reopen().snapshot(ledger.run.run_id)
    assert snapshot.model_requests == snapshot.unknown_requests == 1
    assert snapshot.outstanding_requests == snapshot.reserved_tokens == 0
    assert snapshot.unknown_tokens == 4096


@pytest.mark.parametrize(
    "fault",
    [
        "timeout",
        "cancel",
        "model-mismatch",
        "missing-usage",
        "secret-output",
        "invalid-output",
        "success",
    ],
)
async def test_actual_sdk_durable_request_accounting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    ledger = _ledger(tmp_path, RunBudgetLimits(max_model_requests=2, max_total_tokens=8192))
    accounting = ledger.store.begin_attempt(ledger.request)
    sent = 0

    async def respond(received: httpx2.Request) -> httpx2.Response:
        nonlocal sent
        sent += 1
        # The actual SQLite reservation precedes this physical SDK send.
        current = ledger.reopen().snapshot(ledger.run.run_id)
        assert current.model_requests == current.outstanding_requests == 1
        assert current.reserved_tokens == 4096
        if fault == "timeout":
            raise httpx2.ReadTimeout("fixture-only timeout", request=received)
        if fault == "cancel":
            raise asyncio.CancelledError()
        body = json.loads(received.content)
        block = output_block(body, AgentRole.COS, "cos")
        if fault == "invalid-output":
            block["input"] = {"not_a_valid_scope": "fixture"}
        if fault == "secret-output":
            block["input"] = {"normalized_goal": _KEY}
        response = output_response(
            received, [block], usage={} if fault == "missing-usage" else None
        )
        if fault == "model-mismatch":
            content = json.loads(response.content)
            content["model"] = "unrequested-model"
            response = httpx2.Response(200, request=received, json=content)
        return response

    clients = configure_transport(monkeypatch, respond)
    runtime = PydanticAIRuntimeAdapter(StaticSecretStore(_KEY), Redactor([_KEY]))
    services = RuntimeInvocationServices(
        configuration=_CONFIG,
        tools=EMPTY_RUNTIME_TOOL_CATALOG,
        accounting=accounting,
    )
    with override_allow_model_requests(True):
        if fault == "cancel":
            with pytest.raises(asyncio.CancelledError):
                await runtime.invoke(ledger.request, services)
        elif fault == "success":
            await runtime.invoke(ledger.request, services)
        else:
            with pytest.raises(FleetError) as captured:
                await runtime.invoke(ledger.request, services)
            if fault == "timeout":
                assert captured.value.code is ErrorCode.RUNTIME_TIMEOUT
                assert (
                    captured.value.details["runtime_diagnostic"]["cause_category"] == "api_timeout"
                )
            assert captured.value.__cause__ is None and captured.value.__context__ is None
            assert _KEY not in str(captured.value) + str(captured.value.details)
    accounting.finish(
        RuntimeAttemptStatus.COMPLETED if fault == "success" else RuntimeAttemptStatus.FAILED
    )
    snapshot = ledger.reopen().snapshot(ledger.run.run_id)
    assert snapshot.model_requests == sent == 1
    assert snapshot.outstanding_requests == snapshot.reserved_tokens == 0
    assert snapshot.reported_costs == {}
    if fault in {"timeout", "cancel", "model-mismatch", "missing-usage"}:
        assert snapshot.unknown_requests == 1
        assert snapshot.unknown_tokens == 4096
    else:
        assert snapshot.unknown_requests == 0
        assert snapshot.reported_total_tokens == 15
    assert all(client.is_closed for client in clients)


async def test_actual_sdk_profile_discovery_is_never_reached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import anthropic._client as sdk_client

    def rejected(*args: object, **kwargs: object) -> None:
        raise AssertionError("SDK must not inspect unrelated credential profiles")

    for symbol in ("default_credentials", "_warn_env_shadow", "CredentialsFile", "InMemoryConfig"):
        monkeypatch.setattr(sdk_client, symbol, rejected)
    configure_transport(
        monkeypatch,
        lambda received: output_response(
            received, [output_block(json.loads(received.content), AgentRole.COS, "cos")]
        ),
    )
    runtime = PydanticAIRuntimeAdapter(StaticSecretStore(_KEY), Redactor([_KEY]))
    with override_allow_model_requests(True):
        result = await runtime.invoke(
            request("cos"),
            RuntimeInvocationServices(
                configuration=_CONFIG,
                tools=EMPTY_RUNTIME_TOOL_CATALOG,
            ),
        )
    assert result.output == expected_output(AgentRole.COS, "cos")


@pytest.mark.parametrize(
    "fault",
    [
        "wrong-host",
        "userinfo",
        "query",
        "fragment",
        "method",
        "path",
        "port",
        "wrong-key",
        "cookie",
        "duplicate-key",
        "extra-header",
        "wrong-model",
        "stream",
        "native-tool",
        "hosted-content",
        "fallback",
        "secret-body",
    ],
)
async def test_request_guard_rejects_unsupported_wire_before_consuming_ticket(fault: str) -> None:
    body: dict[str, Any] = {
        "model": _MODEL,
        "max_tokens": 256,
        "messages": [{"role": "user", "content": "Offline fixture"}],
    }
    url = "https://api.anthropic.com/v1/messages?beta=true"
    method = "POST"
    headers = [
        ("host", "api.anthropic.com"),
        ("x-api-key", _KEY),
        ("anthropic-version", "2023-06-01"),
    ]
    if fault == "wrong-host":
        url = "https://untrusted.invalid/v1/messages?beta=true"
    elif fault == "userinfo":
        url = "https://user:password@api.anthropic.com/v1/messages"
    elif fault == "query":
        url = "https://api.anthropic.com/v1/messages?credential=unexpected"
    elif fault == "fragment":
        url += "#fragment"
    elif fault == "method":
        method = "GET"
    elif fault == "path":
        url = "https://api.anthropic.com/v1/models"
    elif fault == "port":
        url = "https://api.anthropic.com:8443/v1/messages"
    elif fault == "wrong-key":
        headers[1] = ("x-api-key", "wrong")
    elif fault == "cookie":
        headers.append(("cookie", "prior=untrusted"))
    elif fault == "duplicate-key":
        headers.append(("x-api-key", _KEY))
    elif fault == "extra-header":
        headers.append(("authorization", "Bearer wrong"))
    elif fault == "wrong-model":
        body["model"] = "other-model"
    elif fault == "stream":
        body["stream"] = True
    elif fault == "native-tool":
        body["tools"] = [{"type": "code_execution_20250825", "name": "code_execution"}]
    elif fault == "hosted-content":
        body["messages"][0]["content"] = [
            {"type": "image", "source": {"type": "url", "url": "https://untrusted.invalid/image"}}
        ]
    elif fault == "fallback":
        body["fallbacks"] = [{"model": "unrequested-model"}]
    else:
        body["messages"][0]["content"] = _KEY
    received = httpx2.Request(method, url, headers=headers, json=body)
    gate = SingleSendGate()
    guard = provider_module.anthropic_request_guard(_KEY, _MODEL, Redactor([_KEY]), gate)
    with gate.request():
        with pytest.raises(FleetError) as captured:
            await guard(received)
        assert captured.value.__context__ is None and captured.value.__cause__ is None
        assert _KEY not in str(captured.value)
        gate.consume()  # Denial did not transmit or consume the physical-send ticket.


async def test_injected_sdk_model_second_send_is_denied_with_one_durable_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pydantic_ai.models.anthropic import AnthropicModel

    original = AnthropicModel.request

    async def twice(self: Any, *args: Any, **kwargs: Any) -> Any:
        await original(self, *args, **kwargs)
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(AnthropicModel, "request", twice)
    sends: list[httpx2.Request] = []

    def respond(received: httpx2.Request) -> httpx2.Response:
        sends.append(received)
        return output_response(
            received, [output_block(json.loads(received.content), AgentRole.COS, "cos")]
        )

    clients = configure_transport(monkeypatch, respond)
    ledger = _ledger(tmp_path, RunBudgetLimits(max_total_tokens=8192))
    accounting = ledger.store.begin_attempt(ledger.request)
    runtime = PydanticAIRuntimeAdapter(StaticSecretStore(_KEY), Redactor([_KEY]))
    with override_allow_model_requests(True), pytest.raises(FleetError):
        await runtime.invoke(
            ledger.request,
            RuntimeInvocationServices(
                configuration=_CONFIG,
                tools=EMPTY_RUNTIME_TOOL_CATALOG,
                accounting=accounting,
            ),
        )
    accounting.finish(RuntimeAttemptStatus.FAILED)
    current = ledger.reopen().snapshot(ledger.run.run_id)
    assert len(sends) == current.model_requests == current.unknown_requests == 1
    assert current.unknown_tokens == 4096 and current.outstanding_requests == 0
    assert all(client.is_closed for client in clients)


async def test_invalid_second_tool_denies_entire_actual_sdk_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = RecordingCatalog(
        (
            RuntimeToolDefinition(
                name="repo_list_files",
                description="Only this tool is admitted.",
                parameters_json_schema={"type": "object", "properties": {}},
            ),
        )
    )
    configure_transport(
        monkeypatch,
        lambda received: output_response(
            received,
            [
                {"type": "tool_use", "id": "valid_first", "name": "repo_list_files", "input": {}},
                {"type": "tool_use", "id": "invalid_second", "name": "unbound_tool", "input": {}},
            ],
        ),
    )
    runtime = PydanticAIRuntimeAdapter(StaticSecretStore(_KEY), Redactor([_KEY]))
    with override_allow_model_requests(True), pytest.raises(FleetError):
        await runtime.invoke(
            request("engineer"),
            RuntimeInvocationServices(
                configuration=_CONFIG,
                tools=catalog,
            ),
        )
    assert catalog.calls == []
