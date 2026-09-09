"""Actual pinned SDK Runner/HTTP contracts; every response is offline synthetic."""

from __future__ import annotations

import asyncio
import atexit
import json
import logging
import threading
import warnings
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any

import httpx2
import pytest
from action_tool_fixtures import make_action_tools, persist_action_tools
from agents import Agent, FunctionTool, RunState
from agents.exceptions import UserError
from agents.models.openai_responses import OpenAIResponsesModel
from agents.tool_context import ToolContext
from agents.tracing import processors as trace_processors
from agents.tracing import setup as trace_setup
from agents.tracing.provider import DefaultTraceProvider
from openai.types.responses import ResponseFunctionToolCall
from test_pydantic_ai_runtime import RecordingCatalog, StaticSecretStore
from test_runtime_budgets import _ledger
from test_runtime_conformance import expected_output, request

import agent_fleet.adapters.runtime.openai_agents_boundary as boundary
import agent_fleet.adapters.runtime.openai_client as transport_module
from agent_fleet.adapters.runtime.openai_agents import OpenAIAgentsRuntimeAdapter
from agent_fleet.application.proposal_tools import ProposalHashToolCatalog
from agent_fleet.domain.budgets import RunBudgetLimits, RuntimeAttemptStatus
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import (
    AgentRole,
    FleetPatch,
    RuntimeConfiguration,
    RuntimeCredentialCheck,
    RuntimeToolDefinition,
    ScopeDecision,
)
from agent_fleet.domain.security import Redactor, sha256_bytes
from agent_fleet.ports.runtime import (
    EMPTY_RUNTIME_TOOL_CATALOG,
    RuntimeInvocationServices,
    RuntimeToolCatalog,
)

_KEY = "offline-agents-selected-credential"
_MODEL = "gpt-test"
_CONFIG = RuntimeConfiguration(
    runtime_name="openai-agents",
    provider_model=f"openai:{_MODEL}",
    credential_ref="env:FLEET_AGENTS_OFFLINE",
    max_retries=0,
    max_requests=4,
    max_total_tokens=4096,
    timeout_seconds=3,
)


@pytest.fixture(autouse=True)
def safe_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "OPENAI_LOG",
        "OPENAI_CUSTOM_HEADERS",
        "OPENAI_AGENTS_DONT_LOG_MODEL_DATA",
        "OPENAI_AGENTS_DONT_LOG_TOOL_DATA",
    ):
        monkeypatch.delenv(name, raising=False)


def configure_transport(
    monkeypatch: pytest.MonkeyPatch, respond: Callable[[httpx2.Request], Any]
) -> list[httpx2.AsyncClient]:
    clients: list[httpx2.AsyncClient] = []

    def create(**kwargs: Any) -> httpx2.AsyncClient:
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        client = httpx2.AsyncClient(transport=httpx2.MockTransport(respond), **kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(transport_module, "DefaultAsyncHttpxClient", create)
    return clients


def call(name: str, arguments: object, call_id: str = "output-final") -> dict[str, object]:
    return {
        "type": "function_call",
        "id": "item-" + call_id,
        "call_id": call_id,
        "name": name,
        "arguments": json.dumps(arguments),
        "status": "completed",
    }


def output(
    received: httpx2.Request, calls: list[dict[str, object]], *, usage: object = None
) -> httpx2.Response:
    return httpx2.Response(
        200,
        request=received,
        json={
            "id": "response-offline",
            "object": "response",
            "created_at": 0,
            "status": "completed",
            "model": _MODEL,
            "output": calls,
            "usage": usage
            if usage is not None
            else {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        },
    )


def final_call(
    body: dict[str, Any], kind: AgentRole = AgentRole.COS, role: str = "cos"
) -> dict[str, object]:
    name = next(tool["name"] for tool in body["tools"] if tool["name"].startswith("submit_"))
    return call(name, expected_output(kind, role).model_dump(mode="json"))


def adapter() -> OpenAIAgentsRuntimeAdapter:
    return OpenAIAgentsRuntimeAdapter(StaticSecretStore(_KEY), Redactor([_KEY]))


@pytest.mark.parametrize(
    ("kind", "custom"),
    [(kind, False) for kind in AgentRole]
    + [(kind, True) for kind in AgentRole if kind is not AgentRole.COS],
)
async def test_actual_sdk_typed_output_and_explicit_transport(
    monkeypatch: pytest.MonkeyPatch,
    kind: AgentRole,
    custom: bool,
) -> None:
    role = "custom-" + kind.value if custom else kind.value
    sent: list[httpx2.Request] = []

    def respond(received: httpx2.Request) -> httpx2.Response:
        sent.append(received)
        body = json.loads(received.content)
        assert body["model"] == _MODEL and body["store"] is False
        assert body.get("stream", False) is False and body["parallel_tool_calls"] is False
        assert body["max_output_tokens"] == 4096
        assert all(
            tool["strict"] is (not tool["name"].startswith("submit_")) for tool in body["tools"]
        )
        assert all(tool["type"] == "function" for tool in body["tools"])
        assert not {"conversation", "previous_response_id", "prompt"} & body.keys()
        return output(received, [final_call(body, kind, role)])

    clients = configure_transport(monkeypatch, respond)
    for name in (
        "OPENAI_API_KEY",
        "OPENAI_ADMIN_API_KEY",
        "OPENAI_BASE_URL",
        "OPENAI_ORG_ID",
        "OPENAI_PROJECT_ID",
        "HTTP_PROXY",
        "HTTPS_PROXY",
    ):
        monkeypatch.setenv(name, "ambient-not-selected")
    result = await adapter().invoke(
        request(role),
        RuntimeInvocationServices(
            configuration=_CONFIG,
            tools=EMPTY_RUNTIME_TOOL_CATALOG,
            execution_kind=kind if custom else None,
        ),
    )
    assert result.output == expected_output(kind, role)
    assert result.usage is not None and result.usage.total_tokens == 15
    assert result.usage.tool_calls == 0 and result.checkpoint_ref is None
    assert (
        result.provider_metadata is not None
        and result.provider_metadata.model == f"openai:{_MODEL}"
    )
    assert len(sent) == len(clients) == 1 and clients[0].is_closed
    assert str(sent[0].url) == "https://api.openai.com/v1/responses"
    assert sent[0].headers["authorization"] == f"Bearer {_KEY}"
    assert "cookie" not in sent[0].headers
    assert _KEY not in sent[0].content.decode() and "ambient-not-selected" not in str(
        sent[0].headers
    )


async def test_real_loop_interrupts_all_actions_and_only_resumes_completed_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = RecordingCatalog(
        (
            RuntimeToolDefinition(
                name="repo_list_files",
                description="Bounded fixture.",
                parameters_json_schema={
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            ),
        )
    )
    bodies: list[dict[str, Any]] = []

    def respond(received: httpx2.Request) -> httpx2.Response:
        body = json.loads(received.content)
        bodies.append(body)
        if len(bodies) == 1:
            assert catalog.calls == []
            return output(
                received,
                [call("repo_list_files", {}, "list-one"), call("repo_list_files", {}, "list-two")],
            )
        assert len(catalog.calls) == 2
        returned = [item for item in body["input"] if item.get("type") == "function_call_output"]
        assert {item["call_id"] for item in returned} == {"list-one", "list-two"}
        assert all(json.loads(item["output"])["content"] == {"accepted": True} for item in returned)
        return output(received, [final_call(body, AgentRole.ENGINEER, "engineer")])

    clients = configure_transport(monkeypatch, respond)
    result = await adapter().invoke(
        request("engineer"), RuntimeInvocationServices(configuration=_CONFIG, tools=catalog)
    )
    assert result.usage is not None and result.usage.requests == result.usage.tool_calls == 2
    assert len(bodies) == 2 and all(item.is_closed for item in clients)


@pytest.mark.parametrize("fault", ["missing", "wrong", "extra", "oversized"])
async def test_invalid_second_action_rejects_full_batch_before_tool_reservation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    tools = make_action_tools(role=AgentRole.VERIFIER)
    budget = persist_action_tools(tmp_path, tools)
    accounting = budget.begin_attempt(tools.invocation)
    invalid: dict[str, object] = {"command_id": "python-test", "reason": "bounded"}
    if fault == "missing":
        del invalid["command_id"]
    elif fault == "wrong":
        invalid["command_id"] = "unadmitted"
    elif fault == "extra":
        invalid["authority"] = "allow"
    else:
        invalid["reason"] = "x" * 10_000
    original = tuple(item.model_dump_json() for item in tools.catalog.definitions)
    clients = configure_transport(
        monkeypatch,
        lambda received: output(
            received,
            [
                call(
                    "run_verification",
                    {"command_id": "python-test", "reason": "bounded"},
                    "valid-first",
                ),
                call("run_verification", invalid, "invalid-second"),
            ],
        ),
    )
    with pytest.raises(FleetError) as caught:
        await adapter().invoke(
            tools.invocation,
            RuntimeInvocationServices(
                configuration=_CONFIG, tools=tools.catalog, accounting=accounting
            ),
        )
    assert caught.value.code is (
        ErrorCode.COMMAND_NOT_REVIEWED if fault == "wrong" else ErrorCode.RUNTIME_OUTPUT_INVALID
    )
    if fault != "wrong":
        assert caught.value.details["runtime_diagnostic"]["category"] == "tool_arguments"
    accounting.finish(RuntimeAttemptStatus.FAILED)
    snapshot = budget.snapshot(tools.run.run_id)
    assert snapshot.model_requests == 1 and snapshot.reported_total_tokens == 15
    assert snapshot.tool_calls == snapshot.outstanding_requests == 0
    assert tools.gateway.calls == [] and tools.catalog.records == ()
    assert tuple(item.model_dump_json() for item in tools.catalog.definitions) == original
    assert all(item.is_closed for item in clients)


@pytest.mark.parametrize(
    "fault",
    [
        "duplicate",
        "duplicate-changed",
        "native",
        "unknown",
        "mixed",
        "two-outputs",
        "bad-json",
        "duplicate-key",
    ],
)
async def test_original_sdk_response_cannot_hide_invalid_batch(
    monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    catalog = RecordingCatalog(
        (
            RuntimeToolDefinition(
                name="repo_list_files",
                description="Bounded fixture.",
                parameters_json_schema={"type": "object", "properties": {}},
            ),
        )
    )
    sends = 0

    def respond(received: httpx2.Request) -> httpx2.Response:
        nonlocal sends
        sends += 1
        body = json.loads(received.content)
        first = call("repo_list_files", {}, "one")
        second = call("repo_list_files", {}, "two")
        if fault.startswith("duplicate"):
            second = dict(first)
            if fault == "duplicate-changed":
                second["arguments"] = '{"changed":true}'
        elif fault == "native":
            second = {"type": "web_search_call", "id": "native", "status": "completed"}
        elif fault == "unknown":
            second["name"] = "shell"
        elif fault == "mixed":
            second = final_call(body, AgentRole.ENGINEER, "engineer")
        elif fault == "two-outputs":
            first = final_call(body, AgentRole.ENGINEER, "engineer")
            second = {**first, "call_id": "other-output"}
        elif fault == "bad-json":
            second["arguments"] = "{"
        else:
            second["arguments"] = '{"reason":"first","reason":"second"}'
        return output(received, [first, second])

    clients = configure_transport(monkeypatch, respond)
    with pytest.raises(FleetError):
        await adapter().invoke(
            request("engineer"), RuntimeInvocationServices(configuration=_CONFIG, tools=catalog)
        )
    assert catalog.calls == [] and sends == 1 and all(item.is_closed for item in clients)


async def test_repeated_completed_call_id_is_not_silently_deduplicated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = RecordingCatalog(
        (
            RuntimeToolDefinition(
                name="repo_list_files",
                description="Bounded fixture.",
                parameters_json_schema={"type": "object", "properties": {}},
            ),
        )
    )
    sends = 0

    def respond(received: httpx2.Request) -> httpx2.Response:
        nonlocal sends
        sends += 1
        return output(received, [call("repo_list_files", {}, "same")])

    clients = configure_transport(monkeypatch, respond)
    with pytest.raises(FleetError):
        await adapter().invoke(
            request("engineer"), RuntimeInvocationServices(configuration=_CONFIG, tools=catalog)
        )
    assert sends == 2 and len(catalog.calls) == 1 and all(item.is_closed for item in clients)


@pytest.mark.parametrize("fault", ["arguments", "lookup", "name", "namespace", "agent"])
async def test_forged_interruption_has_no_gateway_effect(
    monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    tools = make_action_tools(role=AgentRole.VERIFIER)
    clients = configure_transport(
        monkeypatch,
        lambda received: output(
            received,
            [
                call(
                    "run_verification",
                    {"command_id": "python-test", "reason": "bounded"},
                    "original",
                )
            ],
        ),
    )
    original = RunState.get_interruptions

    def forged(self: RunState[Any]) -> Any:
        items = original(self)
        if items:
            if fault == "arguments":
                assert isinstance(items[0].raw_item, ResponseFunctionToolCall)
                items[0].raw_item = items[0].raw_item.model_copy(update={"arguments": "{}"})
            elif fault == "lookup":
                items[0].tool_lookup_key = ("bare", "different")
            elif fault == "name":
                items[0].tool_name = "different"
            elif fault == "namespace":
                items[0].tool_namespace = "unadmitted"
            else:
                items[0].agent = Agent(name="foreign")
        return items

    monkeypatch.setattr(RunState, "get_interruptions", forged)
    with pytest.raises(FleetError):
        await adapter().invoke(
            tools.invocation, RuntimeInvocationServices(configuration=_CONFIG, tools=tools.catalog)
        )
    assert tools.gateway.calls == [] and all(item.is_closed for item in clients)


@pytest.mark.parametrize(
    "fault",
    [
        "timeout",
        "cancel",
        "http429",
        "http500",
        "missing",
        "boolean",
        "numeric-string",
        "float",
        "missing-input",
        "secret-usage",
        "negative",
        "inconsistent",
        "secret",
        "schema",
        "success",
        "zero",
    ],
)
async def test_real_request_accounting_and_unknowns_are_durable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    ledger = _ledger(tmp_path, RunBudgetLimits(max_model_requests=4, max_total_tokens=8192))
    accounting = ledger.store.begin_attempt(ledger.request)
    sends = 0

    async def respond(received: httpx2.Request) -> httpx2.Response:
        nonlocal sends
        sends += 1
        snapshot = ledger.reopen().snapshot(ledger.run.run_id)
        assert snapshot.model_requests == snapshot.outstanding_requests == 1
        assert snapshot.reserved_tokens == 4096
        if fault == "timeout":
            raise httpx2.ReadTimeout("untrusted upstream details", request=received)
        if fault == "cancel":
            raise asyncio.CancelledError()
        if fault.startswith("http"):
            return httpx2.Response(
                int(fault[4:]), request=received, json={"error": {"message": _KEY}}
            )
        body = json.loads(received.content)
        terminal = final_call(body)
        if fault == "secret":
            terminal["arguments"] = json.dumps({"normalized_goal": _KEY})
        elif fault == "schema":
            terminal["arguments"] = "{}"
        usage: dict[str, object] = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
        if fault == "missing":
            usage = {}
        elif fault == "boolean":
            usage["input_tokens"] = True
        elif fault == "numeric-string":
            usage["input_tokens"] = "10"
        elif fault == "float":
            usage["input_tokens"] = 10.0
        elif fault == "missing-input":
            del usage["input_tokens"]
        elif fault == "secret-usage":
            usage["input_tokens"] = _KEY
        elif fault == "negative":
            usage["output_tokens"] = -1
        elif fault == "inconsistent":
            usage["total_tokens"] = 1
        elif fault == "zero":
            usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        return output(received, [terminal], usage=usage)

    clients = configure_transport(monkeypatch, respond)
    services = RuntimeInvocationServices(
        configuration=_CONFIG, tools=EMPTY_RUNTIME_TOOL_CATALOG, accounting=accounting
    )
    if fault in {"success", "zero"}:
        result = await adapter().invoke(ledger.request, services)
        assert result.usage is not None and result.usage.total_tokens == (
            0 if fault == "zero" else 15
        )
        accounting.finish(RuntimeAttemptStatus.COMPLETED)
    else:
        with warnings.catch_warnings(record=True) as captured_warnings:
            warnings.simplefilter("always", UserWarning)
            with pytest.raises(
                asyncio.CancelledError if fault == "cancel" else FleetError
            ) as caught:
                await adapter().invoke(ledger.request, services)
        assert not any(issubclass(item.category, UserWarning) for item in captured_warnings)
        assert all(_KEY not in str(item.message) for item in captured_warnings)
        assert (
            _KEY not in str(caught.value)
            and caught.value.__cause__ is caught.value.__context__ is None
        )
        if fault.startswith("http"):
            assert isinstance(caught.value, FleetError)
            assert caught.value.details["runtime_diagnostic"]["http_status"] == int(fault[4:])
        accounting.finish(
            RuntimeAttemptStatus.CANCELLED if fault == "cancel" else RuntimeAttemptStatus.FAILED
        )
    current = ledger.reopen().snapshot(ledger.run.run_id)
    unknown = fault in {
        "timeout",
        "cancel",
        "http429",
        "http500",
        "missing",
        "boolean",
        "numeric-string",
        "float",
        "missing-input",
        "secret-usage",
        "negative",
        "inconsistent",
    }
    assert current.unknown_requests == int(unknown)
    assert current.model_requests == sends == 1
    assert current.outstanding_requests == current.reserved_tokens == current.tool_calls == 0
    assert current.unknown_tokens == (4096 if unknown else 0)
    assert current.reported_costs == {} and all(item.is_closed for item in clients)


@pytest.mark.parametrize("limit", ["request", "steps", "tools", "tokens"])
async def test_resume_cannot_reset_any_invocation_budget(
    monkeypatch: pytest.MonkeyPatch, limit: str
) -> None:
    catalog = RecordingCatalog(
        (
            RuntimeToolDefinition(
                name="repo_list_files",
                description="Bounded fixture.",
                parameters_json_schema={"type": "object", "properties": {}},
            ),
        )
    )
    count = 0

    def respond(received: httpx2.Request) -> httpx2.Response:
        nonlocal count
        count += 1
        return output(received, [call("repo_list_files", {}, f"call-{count}")])

    clients = configure_transport(monkeypatch, respond)
    changes = {
        "request": {"max_requests": 2},
        "tools": {"max_tool_calls": 1},
        "tokens": {"max_total_tokens": 20},
        "steps": {},
    }[limit]
    configuration = RuntimeConfiguration.model_validate({**_CONFIG.model_dump(), **changes})
    invocation = request("engineer")
    if limit == "steps":
        invocation.max_steps = 2
    with pytest.raises(FleetError) as caught:
        await adapter().invoke(
            invocation, RuntimeInvocationServices(configuration=configuration, tools=catalog)
        )
    assert caught.value.code is ErrorCode.RUNTIME_BUDGET_EXCEEDED
    assert count == 2 and len(catalog.calls) == 1 and all(item.is_closed for item in clients)


@pytest.mark.parametrize(
    "fault",
    [
        "wrong-runtime",
        "checkpoint",
        "unbound-custom",
        "cos-impersonation",
        "chat",
        "other-provider",
        "logging",
        "debug-flag",
    ],
)
async def test_admission_precedes_credentials_and_dispatch(
    monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    secret = StaticSecretStore(_KEY)
    runtime = OpenAIAgentsRuntimeAdapter(secret, Redactor([_KEY]))
    invocation = request("cos")
    configuration = _CONFIG
    kind = None
    if fault == "wrong-runtime":
        configuration = _CONFIG.model_copy(update={"runtime_name": "pydantic-ai"})
    elif fault == "checkpoint":
        invocation.checkpoint_ref = "art_" + "a" * 32
    elif fault == "unbound-custom":
        invocation.role = "custom-reader"
    elif fault == "cos-impersonation":
        invocation.role, kind = "custom-reader", AgentRole.COS
    elif fault in {"chat", "other-provider"}:
        configuration = _CONFIG.model_copy(
            update={
                "provider_model": "openai-chat:gpt-test"
                if fault == "chat"
                else "anthropic:unadmitted"
            }
        )
    elif fault == "logging":
        pass
    else:
        monkeypatch.setenv("OPENAI_AGENTS_DONT_LOG_MODEL_DATA", "false")
    logger = logging.getLogger("openai.agents.hostile-child")
    original_level = logger.level
    try:
        if fault == "logging":
            logger.setLevel(logging.DEBUG)
        with pytest.raises(FleetError):
            await runtime.invoke(
                invocation,
                RuntimeInvocationServices(
                    configuration=configuration,
                    tools=EMPTY_RUNTIME_TOOL_CATALOG,
                    execution_kind=kind,
                ),
            )
    finally:
        logger.setLevel(original_level)
    assert secret.resolve_calls == secret.inspect_calls == 0


def test_preflight_none_does_not_read_secret_or_initialize_tracing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = StaticSecretStore(_KEY)
    runtime = OpenAIAgentsRuntimeAdapter(secret, Redactor())
    monkeypatch.setattr(trace_setup, "GLOBAL_TRACE_PROVIDER", None)
    result = runtime.preflight(_CONFIG, credential_check=RuntimeCredentialCheck.NONE)
    assert result.ready and secret.resolve_calls == secret.inspect_calls == 0
    assert trace_setup.GLOBAL_TRACE_PROVIDER is None


def test_no_export_policy_is_atomic_and_never_initializes_default_exporter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(boundary, "_TRACE_PROVIDER", None)
    monkeypatch.setattr(trace_setup, "GLOBAL_TRACE_PROVIDER", None)
    monkeypatch.setattr(trace_setup, "_SHUTDOWN_HANDLER_REGISTERED", False)
    registered: list[Callable[..., object]] = []

    def register(callback: Callable[..., object]) -> Callable[..., object]:
        registered.append(callback)
        return callback

    monkeypatch.setattr(atexit, "register", register)

    def forbidden() -> None:
        raise AssertionError("Default exporter must never be created")

    monkeypatch.setattr(trace_processors, "default_processor", forbidden)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: boundary.initialize_no_export_tracing(), range(32)))
    provider = trace_setup.GLOBAL_TRACE_PROVIDER
    assert provider is boundary._TRACE_PROVIDER and provider is not None
    assert provider._disabled is True
    assert provider._multi_processor._processors == ()
    assert registered == [trace_setup._shutdown_global_trace_provider]
    assert trace_setup._SHUTDOWN_HANDLER_REGISTERED is True


def test_foreign_sdk_installer_cannot_interleave_compare_and_install(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(boundary, "_TRACE_PROVIDER", None)
    monkeypatch.setattr(trace_setup, "GLOBAL_TRACE_PROVIDER", None)
    monkeypatch.setattr(trace_setup, "_SHUTDOWN_HANDLER_REGISTERED", True)
    constructor = DefaultTraceProvider
    foreign = constructor()
    foreign.set_disabled(True)
    setter_started = threading.Event()
    installation: Future[None] | None = None

    def install_foreign() -> None:
        setter_started.set()
        trace_setup.set_trace_provider(foreign)

    with ThreadPoolExecutor(max_workers=1) as pool:

        def construct() -> Any:
            nonlocal installation
            assert trace_setup._GLOBAL_TRACE_PROVIDER_LOCK.locked()
            installation = pool.submit(install_foreign)
            assert setter_started.wait(1)
            with pytest.raises(TimeoutError):
                installation.result(timeout=0.05)
            return constructor()

        monkeypatch.setattr(boundary, "DefaultTraceProvider", construct)
        boundary.initialize_no_export_tracing()
        assert installation is not None
        installation.result(timeout=1)
    # A later trusted process-global mutation is not prevented. It is detected
    # at the next admission and never silently overwritten by Fleet.
    assert trace_setup.GLOBAL_TRACE_PROVIDER is foreign
    with pytest.raises(FleetError):
        boundary.initialize_no_export_tracing()
    assert trace_setup.GLOBAL_TRACE_PROVIDER is foreign


async def test_passive_invoker_requires_exact_single_use_completed_receipt() -> None:
    passive = boundary.PassiveResults()
    raw = ResponseFunctionToolCall(
        type="function_call", name="repo_list_files", call_id="exact", arguments="{}"
    )
    context = ToolContext(
        context=None,
        tool_name="repo_list_files",
        tool_call_id="exact",
        tool_arguments="{}",
        tool_call=raw,
        agent=Agent(name="bounded"),
    )
    with pytest.raises(FleetError):
        await passive.invoke(context, "{}")
    passive.publish(
        (boundary.CompletedReceipt("exact", "repo_list_files", "{}", '{"complete":true}'),)
    )
    with pytest.raises(FleetError):
        await passive.invoke(context, '{"different":true}')
    assert await passive.invoke(context, "{}") == '{"complete":true}'
    with pytest.raises(FleetError):
        await passive.invoke(context, "{}")
    assert passive.empty and boundary.PassiveResults.__slots__ == ("_receipts",)


async def test_hostile_sdk_error_and_notes_never_cross_public_boundary(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    clients = configure_transport(monkeypatch, lambda _: pytest.fail("No request expected"))

    async def fail(*args: Any, **kwargs: Any) -> Any:
        try:
            raise ValueError(_KEY)
        except ValueError as cause:
            error = UserError(_KEY)
            error.add_note(_KEY)
            raise error from cause

    monkeypatch.setattr(OpenAIResponsesModel, "get_response", fail)
    with pytest.raises(FleetError) as caught:
        await adapter().invoke(
            request("cos"),
            RuntimeInvocationServices(configuration=_CONFIG, tools=EMPTY_RUNTIME_TOOL_CATALOG),
        )
    assert caught.value.__cause__ is caught.value.__context__ is None
    assert not hasattr(caught.value, "__notes__")
    assert _KEY not in str(caught.value) + str(caught.value.details) + caplog.text
    assert all(item.is_closed for item in clients)


@pytest.mark.parametrize(
    "fault", ["model-mismatch", "model-missing", "incomplete", "failed", "status-missing", "error"]
)
async def test_response_identity_and_terminal_status_are_checked_before_sdk_projection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    ledger = _ledger(tmp_path, RunBudgetLimits(max_total_tokens=8192))
    accounting = ledger.store.begin_attempt(ledger.request)
    sends = 0

    def respond(received: httpx2.Request) -> httpx2.Response:
        nonlocal sends
        sends += 1
        initial = output(received, [final_call(json.loads(received.content))])
        payload = json.loads(initial.content)
        if fault == "model-mismatch":
            payload["model"] = "not-selected"
        elif fault == "model-missing":
            del payload["model"]
        elif fault == "status-missing":
            del payload["status"]
        elif fault == "error":
            payload["error"] = {"code": "server_error", "message": _KEY}
        else:
            payload["status"] = fault
        return httpx2.Response(200, request=received, json=payload)

    clients = configure_transport(monkeypatch, respond)
    with pytest.raises(FleetError) as caught:
        await adapter().invoke(
            ledger.request,
            RuntimeInvocationServices(
                configuration=_CONFIG, tools=EMPTY_RUNTIME_TOOL_CATALOG, accounting=accounting
            ),
        )
    assert caught.value.code is ErrorCode.PROVIDER_FAILED
    assert _KEY not in str(caught.value) + str(caught.value.details)
    assert caught.value.__cause__ is caught.value.__context__ is None
    accounting.finish(RuntimeAttemptStatus.FAILED)
    snapshot = ledger.reopen().snapshot(ledger.run.run_id)
    assert snapshot.model_requests == snapshot.unknown_requests == sends == 1
    assert (
        snapshot.outstanding_requests == snapshot.tool_calls == snapshot.reported_total_tokens == 0
    )
    assert snapshot.unknown_tokens == 4096 and all(client.is_closed for client in clients)


async def test_secret_tool_result_never_reaches_sdk_continuation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agent_fleet.domain.models import RuntimeToolCall, RuntimeToolResult

    class SecretCatalog(RecordingCatalog):
        async def execute(self, call: RuntimeToolCall) -> RuntimeToolResult:
            await super().execute(call)
            return RuntimeToolResult(call_id=call.call_id, name=call.name, content={"value": _KEY})

    catalog = SecretCatalog(
        (
            RuntimeToolDefinition(
                name="repo_list_files",
                description="Bounded fixture.",
                parameters_json_schema={"type": "object", "properties": {}},
            ),
        )
    )
    sends = 0

    def respond(received: httpx2.Request) -> httpx2.Response:
        nonlocal sends
        sends += 1
        return output(received, [call("repo_list_files", {}, "one")])

    clients = configure_transport(monkeypatch, respond)
    with pytest.raises(FleetError) as caught:
        await adapter().invoke(
            request("engineer"), RuntimeInvocationServices(configuration=_CONFIG, tools=catalog)
        )
    assert caught.value.code is ErrorCode.COMMAND_DENIED and sends == len(catalog.calls) == 1
    assert _KEY not in str(caught.value) and all(client.is_closed for client in clients)


async def test_partial_tool_batch_failure_is_not_resumed_or_replayed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agent_fleet.domain.models import RuntimeToolCall, RuntimeToolResult

    class FailingCatalog(RecordingCatalog):
        async def execute(self, call: RuntimeToolCall) -> RuntimeToolResult:
            if self.calls:
                raise FleetError(ErrorCode.COMMAND_DENIED, "Bounded denial", "Inspect the run.")
            return await super().execute(call)

    catalog = FailingCatalog(
        (
            RuntimeToolDefinition(
                name="repo_list_files",
                description="Bounded fixture.",
                parameters_json_schema={"type": "object", "properties": {}},
            ),
        )
    )
    sends = 0

    def respond(received: httpx2.Request) -> httpx2.Response:
        nonlocal sends
        sends += 1
        return output(
            received, [call("repo_list_files", {}, "one"), call("repo_list_files", {}, "two")]
        )

    clients = configure_transport(monkeypatch, respond)
    with pytest.raises(FleetError) as caught:
        await adapter().invoke(
            request("engineer"), RuntimeInvocationServices(configuration=_CONFIG, tools=catalog)
        )
    assert caught.value.code is ErrorCode.COMMAND_DENIED and sends == len(catalog.calls) == 1
    assert all(client.is_closed for client in clients)


def test_terminal_compatibility_is_explicit_and_preserves_original_schema() -> None:
    schema = ScopeDecision.model_json_schema()
    original = json.dumps(schema, sort_keys=True)
    passive = boundary.PassiveResults()
    with pytest.raises(UserError):
        FunctionTool(
            name="submit_scope_decision",
            description="Bounded output.",
            params_json_schema=schema,
            on_invoke_tool=passive.invoke,
            needs_approval=True,
            strict_json_schema=True,
        )
    terminal = FunctionTool(
        name="submit_scope_decision",
        description="Bounded output.",
        params_json_schema=schema,
        on_invoke_tool=passive.invoke,
        needs_approval=True,
        strict_json_schema=False,
    )
    assert terminal.needs_approval is True and terminal.strict_json_schema is False
    assert json.dumps(terminal.params_json_schema, sort_keys=True) == original
    assert json.dumps(schema, sort_keys=True) == original


async def test_raw_usage_receipt_is_request_scoped_and_consumed_once() -> None:
    receipt = boundary.RawUsageReceipt()
    response = httpx2.Response(
        200, json={"usage": {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3}}
    )
    with pytest.raises(FleetError):
        await receipt.observe(response)
    with receipt.request():
        await receipt.observe(response)
        assert receipt.consume().total_tokens == 3
        with pytest.raises(FleetError):
            receipt.consume()
        with pytest.raises(FleetError):
            await receipt.observe(response)
    with receipt.request():
        with pytest.raises(FleetError):
            receipt.consume()
        with pytest.raises(FleetError):
            await receipt.observe(httpx2.Response(200, json={"usage": {"total_tokens": 0}}))
    with pytest.raises(FleetError):
        receipt.consume()


@pytest.mark.parametrize("kind", ["gateway", "proposal"])
async def test_real_sdk_strict_actions_preserve_all_shipped_schemas(
    monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    catalog: RuntimeToolCatalog = (
        make_action_tools().catalog if kind == "gateway" else ProposalHashToolCatalog(Redactor())
    )
    originals = {tool.name: tool.model_dump_json() for tool in catalog.definitions}
    sends = 0

    def respond(received: httpx2.Request) -> httpx2.Response:
        nonlocal sends
        sends += 1
        body = json.loads(received.content)
        wire = {
            tool["name"]: tool for tool in body["tools"] if not tool["name"].startswith("submit_")
        }
        assert set(wire) == set(originals)
        for definition in catalog.definitions:
            assert wire[definition.name]["strict"] is True
            assert wire[definition.name]["parameters"] == definition.parameters_json_schema
        return output(received, [final_call(body, AgentRole.ENGINEER, "engineer")])

    clients = configure_transport(monkeypatch, respond)
    result = await adapter().invoke(
        request("engineer"), RuntimeInvocationServices(configuration=_CONFIG, tools=catalog)
    )
    assert result.usage is not None and result.usage.tool_calls == 0
    assert {tool.name: tool.model_dump_json() for tool in catalog.definitions} == originals
    assert sends == 1 and catalog.records == () and all(client.is_closed for client in clients)


async def test_incompatible_strict_action_schema_never_reserves_or_dispatches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = _ledger(tmp_path, RunBudgetLimits(max_total_tokens=8192))
    accounting = ledger.store.begin_attempt(ledger.request)
    definition = RuntimeToolDefinition(
        name="unqualified-open-object",
        description="Unqualified shape",
        parameters_json_schema={"type": "object", "additionalProperties": True},
    )
    original = definition.model_dump_json()
    catalog = RecordingCatalog((definition,))
    clients = configure_transport(
        monkeypatch, lambda _: pytest.fail("No send before strict construction")
    )
    with pytest.raises(FleetError) as caught:
        await adapter().invoke(
            ledger.request,
            RuntimeInvocationServices(configuration=_CONFIG, tools=catalog, accounting=accounting),
        )
    assert caught.value.code is ErrorCode.PROVIDER_FAILED
    assert caught.value.details["runtime_diagnostic"]["category"] == "request_construction"
    assert caught.value.__context__ is caught.value.__cause__ is None
    accounting.finish(RuntimeAttemptStatus.FAILED)
    snapshot = ledger.reopen().snapshot(ledger.run.run_id)
    assert (
        snapshot.model_requests
        == snapshot.tool_calls
        == snapshot.unknown_requests
        == snapshot.outstanding_requests
        == 0
    )
    assert definition.model_dump_json() == original and catalog.calls == []
    assert len(clients) == 1 and clients[0].is_closed


async def test_real_sdk_organization_submission_is_typed_and_not_an_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = "Reviewed organization note.\n"
    patch = FleetPatch.model_validate(
        {
            "fleet_patch_id": "fpatch_" + "1" * 32,
            "project_id": "prj_" + "2" * 32,
            "base_fleet_spec_sha256": "3" * 64,
            "rationale": "A reviewable organization proposal.",
            "changes": [
                {
                    "operation": "replace",
                    "path": ".fleet/README.md",
                    "before_sha256": "4" * 64,
                    "after_sha256": sha256_bytes(content.encode()),
                    "content": content,
                }
            ],
        }
    )
    invocation = request("cos")
    invocation.input["organization_context"] = {
        "proposal_id": patch.fleet_patch_id,
        "project_id": patch.project_id,
        "base_fleet_spec_sha256": patch.base_fleet_spec_sha256,
    }

    def respond(received: httpx2.Request) -> httpx2.Response:
        body = json.loads(received.content)
        assert {tool["name"] for tool in body["tools"]} == {
            "submit_scope_decision",
            "submit_fleet_patch",
        }
        assert all(tool["strict"] is False for tool in body["tools"])
        return output(received, [call("submit_fleet_patch", patch.model_dump(mode="json"))])

    clients = configure_transport(monkeypatch, respond)
    result = await adapter().invoke(
        invocation,
        RuntimeInvocationServices(configuration=_CONFIG, tools=EMPTY_RUNTIME_TOOL_CATALOG),
    )
    assert result.output == patch and result.usage is not None and result.usage.tool_calls == 0
    assert len(clients) == 1 and clients[0].is_closed


@pytest.mark.parametrize("fault", ["missing", "http500"])
async def test_resumed_request_never_reuses_previous_usage_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    ledger = _ledger(tmp_path, RunBudgetLimits(max_model_requests=4, max_total_tokens=8192))
    accounting = ledger.store.begin_attempt(ledger.request)
    catalog = RecordingCatalog(
        (
            RuntimeToolDefinition(
                name="repo_list_files",
                description="Bounded listing",
                parameters_json_schema={"type": "object", "properties": {}},
            ),
        )
    )
    sends = 0

    def respond(received: httpx2.Request) -> httpx2.Response:
        nonlocal sends
        sends += 1
        if sends == 1:
            return output(received, [call("repo_list_files", {}, "first-action")])
        if fault == "http500":
            return httpx2.Response(
                500, request=received, json={"error": {"message": "synthetic unavailable"}}
            )
        return output(received, [final_call(json.loads(received.content))], usage={})

    clients = configure_transport(monkeypatch, respond)
    with pytest.raises(FleetError):
        await adapter().invoke(
            ledger.request,
            RuntimeInvocationServices(configuration=_CONFIG, tools=catalog, accounting=accounting),
        )
    accounting.finish(RuntimeAttemptStatus.FAILED)
    snapshot = ledger.reopen().snapshot(ledger.run.run_id)
    assert sends == snapshot.model_requests == 2
    assert snapshot.unknown_requests == snapshot.tool_calls == len(catalog.calls) == 1
    assert snapshot.reported_total_tokens == 15 and snapshot.unknown_tokens == 4081
    assert snapshot.outstanding_requests == snapshot.reserved_tokens == 0
    assert all(client.is_closed for client in clients)


@pytest.mark.parametrize(
    ("detail", "field"),
    [
        ("input_tokens_details", "cached_tokens"),
        ("input_tokens_details", "cache_write_tokens"),
        ("output_tokens_details", "reasoning_tokens"),
    ],
)
@pytest.mark.parametrize("value", [_KEY, "1", True, 1.0, -1, None])
async def test_nested_wire_usage_never_reaches_value_bearing_sdk_serializers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    detail: str,
    field: str,
    value: object,
) -> None:
    ledger = _ledger(tmp_path, RunBudgetLimits(max_total_tokens=8192))
    accounting = ledger.store.begin_attempt(ledger.request)
    sends = 0

    def respond(received: httpx2.Request) -> httpx2.Response:
        nonlocal sends
        sends += 1
        return output(
            received,
            [final_call(json.loads(received.content))],
            usage={
                "input_tokens": 10,
                "output_tokens": 5,
                "total_tokens": 15,
                detail: {field: value},
            },
        )

    clients = configure_transport(monkeypatch, respond)
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always", UserWarning)
        with pytest.raises(FleetError) as caught:
            await adapter().invoke(
                ledger.request,
                RuntimeInvocationServices(
                    configuration=_CONFIG, tools=EMPTY_RUNTIME_TOOL_CATALOG, accounting=accounting
                ),
            )
    assert not any(issubclass(item.category, UserWarning) for item in captured)
    assert all(_KEY not in str(item.message) for item in captured)
    assert _KEY not in str(caught.value) + str(caught.value.details) + caplog.text
    assert caught.value.__cause__ is caught.value.__context__ is None
    accounting.finish(RuntimeAttemptStatus.FAILED)
    snapshot = ledger.reopen().snapshot(ledger.run.run_id)
    assert sends == snapshot.model_requests == snapshot.unknown_requests == 1
    assert (
        snapshot.reported_total_tokens == snapshot.outstanding_requests == snapshot.tool_calls == 0
    )
    assert snapshot.unknown_tokens == 4096 and all(client.is_closed for client in clients)


async def test_valid_nested_usage_remains_exact_total_without_extra_cost_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clients = configure_transport(
        monkeypatch,
        lambda received: output(
            received,
            [final_call(json.loads(received.content))],
            usage={
                "input_tokens": 10,
                "output_tokens": 5,
                "total_tokens": 15,
                "input_tokens_details": {"cached_tokens": 3, "cache_write_tokens": 2},
                "output_tokens_details": {"reasoning_tokens": 1},
            },
        ),
    )
    result = await adapter().invoke(
        request("cos"),
        RuntimeInvocationServices(configuration=_CONFIG, tools=EMPTY_RUNTIME_TOOL_CATALOG),
    )
    assert result.usage is not None and result.usage.total_tokens == 15
    assert result.usage.provider_cost is None and result.usage.provider_currency is None
    assert len(clients) == 1 and clients[0].is_closed


@pytest.mark.parametrize(
    "fault",
    [
        "null-role-map",
        "unknown-role-key",
        "verifier-writer",
        "extra-field",
        "wrong-specialist",
        "boolean-integer",
    ],
)
async def test_nonstrict_terminal_wire_never_relaxes_local_role_schema(
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    role = "researcher" if fault == "wrong-specialist" else "cos"
    kind = AgentRole.RESEARCHER if role == "researcher" else AgentRole.COS
    value = expected_output(kind, role).model_dump(mode="json")
    if fault == "null-role-map":
        value["role_selections"] = None
    elif fault == "unknown-role-key":
        value["role_selections"] = {"cos": "other-chief"}
    elif fault == "verifier-writer":
        value["fleet_strategy"] = "engineer_verifier"
        value["writer_assignments"] = [{"node_id": "verifier", "role": "verifier"}]
    elif fault == "extra-field":
        value["permission"] = "allow"
    elif fault == "boolean-integer":
        value["max_parallel_agents"] = True
    else:
        value["role"] = "architect"
    sends = 0

    def respond(received: httpx2.Request) -> httpx2.Response:
        nonlocal sends
        sends += 1
        body = json.loads(received.content)
        name = next(tool["name"] for tool in body["tools"] if tool["name"].startswith("submit_"))
        return output(received, [call(name, value)])

    clients = configure_transport(monkeypatch, respond)
    with pytest.raises(FleetError) as caught:
        await adapter().invoke(
            request(role),
            RuntimeInvocationServices(configuration=_CONFIG, tools=EMPTY_RUNTIME_TOOL_CATALOG),
        )
    assert caught.value.code is ErrorCode.RUNTIME_OUTPUT_INVALID
    assert sends == 1 and all(client.is_closed for client in clients)
