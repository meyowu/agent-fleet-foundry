"""Actual pinned StateGraph and raw SDK Responses, with no external requests."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from contextvars import ContextVar
from pathlib import Path
from typing import Any, cast

import httpx2
import pytest
from action_tool_fixtures import make_action_tools, persist_action_tools
from langgraph_fixtures import (
    CONFIG,
    KEY,
    MODEL,
    adapter,
    call,
    configure_transport,
    final_call,
    output,
    payload,
)
from test_pydantic_ai_runtime import RecordingCatalog, StaticSecretStore
from test_runtime_budgets import _ledger
from test_runtime_conformance import expected_output, request

from agent_fleet.adapters.runtime.langgraph import LangGraphRuntimeAdapter
from agent_fleet.adapters.runtime.langgraph_boundary import action_wire_schema
from agent_fleet.application.proposal_tools import ProposalHashToolCatalog
from agent_fleet.domain.budgets import RunBudgetLimits, RuntimeAttemptStatus
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import (
    AgentRole,
    FleetPatch,
    RuntimeCredentialCheck,
    RuntimeToolDefinition,
)
from agent_fleet.domain.security import Redactor
from agent_fleet.ports.runtime import EMPTY_RUNTIME_TOOL_CATALOG, RuntimeInvocationServices


async def test_cancelled_native_exit_still_drains_independently_owned_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from langgraph.pregel._executor import AsyncBackgroundExecutor

    import agent_fleet.adapters.runtime.langgraph as module

    owners: list[Any] = []
    children: list[asyncio.Task[Any]] = []
    exits: list[asyncio.Task[Any]] = []
    worker_entered, worker_release, worker_closed, exit_entered = (
        asyncio.Event(),
        asyncio.Event(),
        asyncio.Event(),
        asyncio.Event(),
    )
    original_run = module._Invocation.run
    original_enter = AsyncBackgroundExecutor.__aenter__
    original_exit = AsyncBackgroundExecutor.__aexit__

    async def run(invocation: Any, credential: str) -> Any:
        owners.append(invocation.owner)
        return await original_run(invocation, credential)

    async def enter(executor: Any) -> Any:
        submit = await original_enter(executor)

        async def child() -> None:
            task = asyncio.current_task()
            owners[0].nodes.add(task)
            worker_entered.set()
            try:
                await worker_release.wait()
            finally:
                worker_closed.set()

        # The pinned async executor returns an asyncio.Task despite its shared
        # Submit protocol's concurrent.futures.Future annotation.
        child_task = submit(child, __cancel_on_exit__=False, __reraise_on_exit__=True)
        assert isinstance(child_task, asyncio.Task)
        children.append(child_task)
        return submit

    async def leave(executor: Any, *args: Any) -> Any:
        task = asyncio.current_task()
        assert task is not None
        exits.append(task)
        exit_entered.set()
        return await original_exit(executor, *args)

    monkeypatch.setattr(module._Invocation, "run", run)
    monkeypatch.setattr(AsyncBackgroundExecutor, "__aenter__", enter)
    monkeypatch.setattr(AsyncBackgroundExecutor, "__aexit__", leave)
    clients = configure_transport(
        monkeypatch, lambda received: output(received, [final_call(json.loads(received.content))])
    )
    baseline = set(asyncio.all_tasks())
    service = asyncio.create_task(
        adapter().invoke(
            request("cos"),
            RuntimeInvocationServices(configuration=CONFIG, tools=EMPTY_RUNTIME_TOOL_CATALOG),
        )
    )
    await asyncio.wait_for(worker_entered.wait(), 2)
    await asyncio.wait_for(exit_entered.wait(), 2)
    service.cancel()
    for _ in range(5):
        await asyncio.sleep(0)
        service.cancel()
    assert any(task.cancelled() for task in exits)
    assert not worker_closed.is_set() and not service.done()
    assert len(clients) == 1 and not clients[0].is_closed
    worker_release.set()
    with pytest.raises(asyncio.CancelledError) as observed:
        await asyncio.wait_for(service, 2)
    assert observed.value.args == () and worker_closed.is_set()
    assert all(task.done() for task in children + exits)
    assert clients[0].is_closed
    await asyncio.sleep(0)
    assert not [task for task in asyncio.all_tasks() - baseline if not task.done()]


async def test_physical_close_failure_cannot_become_terminal_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import agent_fleet.adapters.runtime.openai_client as transport_module

    class BrokenClose(httpx2.MockTransport):
        close_attempts = 0

        async def aclose(self) -> None:
            self.close_attempts += 1
            raise RuntimeError(KEY)

    transport = BrokenClose(
        lambda received: output(received, [final_call(json.loads(received.content))])
    )
    monkeypatch.setattr(
        transport_module,
        "DefaultAsyncHttpxClient",
        lambda **kwargs: httpx2.AsyncClient(transport=transport, **kwargs),
    )
    with pytest.raises(FleetError) as observed:
        await adapter().invoke(
            request("cos"),
            RuntimeInvocationServices(configuration=CONFIG, tools=EMPTY_RUNTIME_TOOL_CATALOG),
        )
    assert observed.value.details["runtime_diagnostic"]["cause_category"] == "client_cleanup"
    assert transport.close_attempts == 1
    assert observed.value.__cause__ is observed.value.__context__ is None
    assert KEY not in str(observed.value)


async def test_timeout_drains_request_and_retains_unknown_usage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = _ledger(tmp_path, RunBudgetLimits())
    accounting = ledger.store.begin_attempt(ledger.request)
    physical_closed = asyncio.Event()

    async def respond(received: httpx2.Request) -> httpx2.Response:
        try:
            await asyncio.Event().wait()
        finally:
            physical_closed.set()
        raise AssertionError("unreachable")

    clients = configure_transport(monkeypatch, respond)
    with pytest.raises(FleetError) as observed:
        await adapter().invoke(
            ledger.request,
            RuntimeInvocationServices(
                configuration=CONFIG.model_copy(update={"timeout_seconds": 1}),
                tools=EMPTY_RUNTIME_TOOL_CATALOG,
                accounting=accounting,
            ),
        )
    assert observed.value.code is ErrorCode.RUNTIME_TIMEOUT
    accounting.finish(RuntimeAttemptStatus.FAILED, error_code=observed.value.code)
    snapshot = ledger.reopen().snapshot(ledger.run.run_id)
    assert snapshot.model_requests == snapshot.unknown_requests == 1
    assert snapshot.outstanding_requests == snapshot.reserved_tokens == 0
    assert physical_closed.is_set() and all(client.is_closed for client in clients)


@pytest.mark.parametrize("with_context", [True, False])
async def test_fleet_patch_output_requires_actual_cos_organization_context(
    monkeypatch: pytest.MonkeyPatch,
    with_context: bool,
) -> None:
    from hashlib import sha256

    content = "Reviewed organization note.\n"
    patch = FleetPatch.model_validate(
        {
            "fleet_patch_id": "fpatch_" + "1" * 32,
            "project_id": "prj_" + "2" * 32,
            "base_fleet_spec_sha256": "3" * 64,
            "rationale": "A reviewable proposal only.",
            "changes": [
                {
                    "operation": "replace",
                    "path": ".fleet/README.md",
                    "before_sha256": "4" * 64,
                    "after_sha256": sha256(content.encode()).hexdigest(),
                    "content": content,
                }
            ],
        }
    )
    invocation = request("cos")
    if with_context:
        invocation.input["organization_context"] = {"proposal_id": patch.fleet_patch_id}
    catalog = ProposalHashToolCatalog(Redactor())
    originals = tuple(tool.model_dump_json() for tool in catalog.definitions)

    def respond(received: httpx2.Request) -> httpx2.Response:
        body = json.loads(received.content)
        wire = {tool["name"]: tool for tool in body["tools"]}
        assert ("submit_fleet_patch" in wire) is with_context
        assert wire["fleet_content_sha256"]["strict"] is True
        assert wire["submit_scope_decision"]["strict"] is False
        return output(received, [call("submit_fleet_patch", patch.model_dump(mode="json"))])

    clients = configure_transport(monkeypatch, respond)
    services = RuntimeInvocationServices(configuration=CONFIG, tools=catalog)
    if with_context:
        result = await adapter().invoke(invocation, services)
        assert result.output == patch and result.usage is not None and result.usage.tool_calls == 0
    else:
        with pytest.raises(FleetError):
            await adapter().invoke(invocation, services)
    assert originals == tuple(tool.model_dump_json() for tool in catalog.definitions)
    assert catalog.records == () and all(client.is_closed for client in clients)


@pytest.mark.parametrize("fault", ["wrong-specialist", "bad-terminal"])
async def test_terminal_output_remains_strictly_role_validated(
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    kind = AgentRole.RESEARCHER if fault == "wrong-specialist" else AgentRole.COS

    def respond(received: httpx2.Request) -> httpx2.Response:
        body = json.loads(received.content)
        terminal = final_call(body, kind, kind.value)
        arguments = json.loads(terminal["arguments"])
        arguments["role" if fault == "wrong-specialist" else "role_selections"] = "invalid-value"
        terminal["arguments"] = json.dumps(arguments)
        return output(received, [terminal])

    clients = configure_transport(monkeypatch, respond)
    with pytest.raises(FleetError) as observed:
        await adapter().invoke(
            request(kind.value),
            RuntimeInvocationServices(configuration=CONFIG, tools=EMPTY_RUNTIME_TOOL_CATALOG),
        )
    assert observed.value.code is ErrorCode.RUNTIME_OUTPUT_INVALID
    assert all(client.is_closed for client in clients)


@pytest.mark.parametrize("location", ["input", "response", "tool-result"])
async def test_registered_secret_never_reaches_next_request_or_error(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    location: str,
) -> None:
    from agent_fleet.domain.models import RuntimeToolResult

    class Catalog(RecordingCatalog):
        async def execute(self, item: Any) -> Any:
            self.calls.append(item)
            return RuntimeToolResult(call_id=item.call_id, name=item.name, content={"value": KEY})

    catalog = Catalog(
        (
            RuntimeToolDefinition(
                name="repo_list_files",
                description="Bounded.",
                parameters_json_schema={
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            ),
        )
    )
    invocation = request("engineer")
    if location == "input":
        invocation.input["private"] = KEY
    sends = 0

    def respond(received: httpx2.Request) -> httpx2.Response:
        nonlocal sends
        sends += 1
        assert KEY not in received.content.decode()
        if location == "response":
            data = payload([call("repo_list_files", {})])
            data["private"] = KEY
            return httpx2.Response(200, json=data)
        return output(received, [call("repo_list_files", {})])

    clients = configure_transport(monkeypatch, respond)
    with pytest.raises(FleetError) as observed:
        await adapter().invoke(
            invocation, RuntimeInvocationServices(configuration=CONFIG, tools=catalog)
        )
    assert observed.value.code is ErrorCode.COMMAND_DENIED
    assert sends == (0 if location == "input" else 1)
    assert len(catalog.calls) == (1 if location == "tool-result" else 0)
    assert KEY not in str(observed.value) + caplog.text
    assert observed.value.__context__ is observed.value.__cause__ is None
    assert all(client.is_closed for client in clients)


@pytest.mark.parametrize("case", ["checkpoint", "wrong-runtime", "unbound", "rebound", "cos-alias"])
async def test_shared_admission_rejects_before_secret_or_graph(case: str) -> None:
    invocation = request("engineer")
    selected, kind = CONFIG, None
    if case == "checkpoint":
        invocation.checkpoint_ref = "art_" + "4" * 32
    elif case == "wrong-runtime":
        selected = CONFIG.model_copy(update={"runtime_name": "fake"})
    elif case == "unbound":
        invocation.role = "unbound-specialist"
    elif case == "rebound":
        kind = AgentRole.VERIFIER
    else:
        invocation.role, kind = "cos-alias", AgentRole.COS
    secrets = StaticSecretStore(KEY)
    with pytest.raises(FleetError):
        await LangGraphRuntimeAdapter(secrets, Redactor()).invoke(
            invocation,
            RuntimeInvocationServices(
                configuration=selected, tools=EMPTY_RUNTIME_TOOL_CATALOG, execution_kind=kind
            ),
        )
    assert secrets.inspect_calls == secrets.resolve_calls == 0


@pytest.mark.parametrize("fault", ["missing-usage", "http500", "reused-call-id"])
async def test_second_request_does_not_reuse_old_usage_or_action_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    ledger = _ledger(tmp_path, RunBudgetLimits(max_model_requests=4, max_total_tokens=8192))
    accounting = ledger.store.begin_attempt(ledger.request)
    catalog = RecordingCatalog(
        (
            RuntimeToolDefinition(
                name="repo_list_files",
                description="Bounded.",
                parameters_json_schema={
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            ),
        )
    )
    sends = 0

    def respond(received: httpx2.Request) -> httpx2.Response:
        nonlocal sends
        sends += 1
        if sends == 1 or fault == "reused-call-id":
            return output(received, [call("repo_list_files", {}, "same-action")])
        if fault == "http500":
            return httpx2.Response(
                500, request=received, json={"error": {"message": "unavailable"}}
            )
        data = payload([final_call(json.loads(received.content))])
        data["usage"] = {}
        return httpx2.Response(200, request=received, json=data)

    clients = configure_transport(monkeypatch, respond)
    with pytest.raises(FleetError):
        await adapter().invoke(
            ledger.request,
            RuntimeInvocationServices(configuration=CONFIG, tools=catalog, accounting=accounting),
        )
    accounting.finish(RuntimeAttemptStatus.FAILED)
    snapshot = ledger.reopen().snapshot(ledger.run.run_id)
    assert sends == snapshot.model_requests == 2
    assert snapshot.tool_calls == len(catalog.calls) == 1
    assert snapshot.unknown_requests == (0 if fault == "reused-call-id" else 1)
    assert snapshot.reported_total_tokens == (30 if fault == "reused-call-id" else 15)
    assert snapshot.unknown_tokens == (0 if fault == "reused-call-id" else 4081)
    assert snapshot.outstanding_requests == snapshot.reserved_tokens == 0
    assert all(client.is_closed for client in clients)


async def test_hostile_sdk_exception_is_detached_before_graph_error_callbacks(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from openai import OpenAIError

    def respond(received: httpx2.Request) -> httpx2.Response:
        del received
        error = OpenAIError(KEY)
        error.add_note(KEY)
        raise error from ValueError(KEY)

    clients = configure_transport(monkeypatch, respond)
    with pytest.raises(FleetError) as observed:
        await adapter().invoke(
            request("cos"),
            RuntimeInvocationServices(configuration=CONFIG, tools=EMPTY_RUNTIME_TOOL_CATALOG),
        )
    assert observed.value.code is ErrorCode.PROVIDER_FAILED
    assert observed.value.__cause__ is observed.value.__context__ is None
    assert not getattr(observed.value, "__notes__", None)
    assert KEY not in str(observed.value) + caplog.text
    assert all(client.is_closed for client in clients)


@pytest.mark.parametrize("status", [401, 403, 429, 500, 503])
async def test_actual_http_failures_are_single_send_unknown_and_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    ledger = _ledger(tmp_path, RunBudgetLimits())
    accounting = ledger.store.begin_attempt(ledger.request)
    sends = 0

    def respond(received: httpx2.Request) -> httpx2.Response:
        nonlocal sends
        sends += 1
        return httpx2.Response(
            status, request=received, json={"error": {"message": "synthetic-provider-error"}}
        )

    clients = configure_transport(monkeypatch, respond)
    with pytest.raises(FleetError) as observed:
        await adapter().invoke(
            ledger.request,
            RuntimeInvocationServices(
                configuration=CONFIG.model_copy(update={"max_retries": 3}),
                tools=EMPTY_RUNTIME_TOOL_CATALOG,
                accounting=accounting,
            ),
        )
    accounting.finish(RuntimeAttemptStatus.FAILED, error_code=observed.value.code)
    snapshot = ledger.reopen().snapshot(ledger.run.run_id)
    assert sends == snapshot.model_requests == snapshot.unknown_requests == 1
    assert snapshot.outstanding_requests == 0 and snapshot.unknown_tokens > 0
    assert observed.value.code is ErrorCode.PROVIDER_FAILED
    assert observed.value.details["runtime_diagnostic"]["http_status"] == status
    assert "synthetic-provider-error" not in str(observed.value)
    assert all(client.is_closed for client in clients)


@pytest.mark.parametrize("limit", ["requests", "steps", "tools", "tokens"])
async def test_budget_stops_before_any_tool_effect(
    monkeypatch: pytest.MonkeyPatch, limit: str
) -> None:
    definition = RuntimeToolDefinition(
        name="repo_list_files",
        description="Bounded.",
        parameters_json_schema={"type": "object", "properties": {}, "additionalProperties": False},
    )
    catalog = RecordingCatalog((definition,))
    config = CONFIG
    invocation = request("engineer")
    if limit == "requests":
        config = config.model_copy(update={"max_requests": 1})
    elif limit == "steps":
        invocation.max_steps = 1
    elif limit == "tools":
        config = config.model_copy(update={"max_tool_calls": 1})
    else:
        config = config.model_copy(update={"max_total_tokens": 10})
    sends: list[httpx2.Request] = []

    def respond(received: httpx2.Request) -> httpx2.Response:
        sends.append(received)
        return output(
            received, [call("repo_list_files", {}, "one"), call("repo_list_files", {}, "two")]
        )

    configure_transport(monkeypatch, respond)
    with pytest.raises(FleetError) as observed:
        await adapter().invoke(
            invocation, RuntimeInvocationServices(configuration=config, tools=catalog)
        )
    assert observed.value.code is ErrorCode.RUNTIME_BUDGET_EXCEEDED
    assert len(sends) == 1 and catalog.calls == []


async def test_raw_path_never_calls_sdk_parser_or_diagnostic_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from openai._legacy_response import LegacyAPIResponse

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("SDK typed parser or implicit thread must not run")

    monkeypatch.setattr(LegacyAPIResponse, "parse", forbidden)
    monkeypatch.setattr(asyncio, "to_thread", forbidden)
    configure_transport(
        monkeypatch, lambda received: output(received, [final_call(json.loads(received.content))])
    )
    result = await adapter().invoke(
        request("cos"),
        RuntimeInvocationServices(configuration=CONFIG, tools=EMPTY_RUNTIME_TOOL_CATALOG),
    )
    assert result.usage is not None and result.usage.requests == 1


@pytest.mark.parametrize(
    "fault", ["global-tracing", "client", "hook", "debug", "logging", "context"]
)
async def test_telemetry_policy_denies_before_secret_or_exporter(
    monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    import langsmith.client
    from langchain_core import globals as lc_globals
    from langchain_core.tracers import context as trace_context
    from langsmith._internal import _context as ls_context

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("exporter construction must not run")

    monkeypatch.setattr(langsmith.client.Client, "__init__", forbidden)
    reset = None
    if fault == "global-tracing":
        monkeypatch.setattr(ls_context, "_GLOBAL_TRACING_ENABLED", True)
    elif fault == "client":
        monkeypatch.setattr(ls_context, "_GLOBAL_CLIENT", object())
    elif fault == "hook":
        monkeypatch.setattr(trace_context, "_configure_hooks", [])
    elif fault == "debug":
        monkeypatch.setattr(lc_globals, "_debug", True)
    elif fault == "logging":
        logger = logging.getLogger("langgraph.untrusted")
        previous = logger.level
        logger.setLevel(logging.DEBUG)
    else:
        reset = ls_context._TRACING_ENABLED.set(True)
    secrets = StaticSecretStore(KEY)
    try:
        with pytest.raises(FleetError):
            await LangGraphRuntimeAdapter(secrets, Redactor()).invoke(
                request("cos"),
                RuntimeInvocationServices(configuration=CONFIG, tools=EMPTY_RUNTIME_TOOL_CATALOG),
            )
        assert secrets.resolve_calls == 0
    finally:
        if fault == "logging":
            logger.setLevel(previous)
        if reset is not None:
            ls_context._TRACING_ENABLED.reset(reset)


async def test_fresh_graph_context_excludes_parent_runtime_and_callbacks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from langchain_core.callbacks.base import BaseCallbackHandler
    from langchain_core.runnables.config import var_child_runnable_config
    from langgraph.runtime import Runtime, get_runtime

    import agent_fleet.adapters.runtime.langgraph as module

    foreign: ContextVar[str | None] = ContextVar("foreign", default=None)

    class Forbidden(BaseCallbackHandler):
        raise_error = True

        def on_chain_start(self, *args: Any, **kwargs: Any) -> Any:
            raise AssertionError("foreign callback")

    original = module._Invocation._request

    async def checked(invocation: Any, client: Any) -> None:
        assert foreign.get() is None and get_runtime().store is None
        await original(invocation, client)

    monkeypatch.setattr(module._Invocation, "_request", checked)
    token = foreign.set("private-parent")
    config_token = var_child_runnable_config.set(
        cast(
            Any,
            {
                "callbacks": [Forbidden()],
                "configurable": {
                    "__pregel_runtime": Runtime(store=cast(Any, object())),
                    "__pregel_cache": object(),
                    "__pregel_checkpointer": object(),
                    "thread_id": "private-parent",
                },
            },
        )
    )
    configure_transport(
        monkeypatch, lambda received: output(received, [final_call(json.loads(received.content))])
    )
    try:
        await adapter().invoke(
            request("cos"),
            RuntimeInvocationServices(configuration=CONFIG, tools=EMPTY_RUNTIME_TOOL_CATALOG),
        )
        assert foreign.get() == "private-parent"
    finally:
        foreign.reset(token)
        var_child_runnable_config.reset(config_token)


@pytest.mark.parametrize("phase", ["request", "gateway", "graph-exit", "client-close"])
async def test_repeated_cancellation_drains_actual_nodes_graph_and_transport(
    monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    from langgraph.pregel._loop import AsyncPregelLoop

    import agent_fleet.adapters.runtime.langgraph as module
    import agent_fleet.adapters.runtime.openai_client as transport_module

    hit, release = asyncio.Event(), asyncio.Event()
    owners: list[Any] = []
    original_run = module._Invocation.run

    async def run(invocation: Any, credential: str) -> Any:
        owners.append(invocation.owner)
        return await original_run(invocation, credential)

    monkeypatch.setattr(module._Invocation, "run", run)
    effects: list[str] = []

    class Transport(httpx2.AsyncBaseTransport):
        active = 0
        closed = False

        async def handle_async_request(self, received: httpx2.Request) -> httpx2.Response:
            self.active += 1
            try:
                if phase == "request":
                    hit.set()
                    await release.wait()
                body = json.loads(received.content)
                if phase == "gateway":
                    return output(received, [call("repo_list_files", {})])
                return output(received, [final_call(body, AgentRole.ENGINEER, "engineer")])
            finally:
                self.active -= 1

        async def aclose(self) -> None:
            if phase == "client-close":
                hit.set()
                await release.wait()
            assert self.active == 0
            self.closed = True

    transport = Transport()
    monkeypatch.setattr(
        transport_module,
        "DefaultAsyncHttpxClient",
        lambda **kwargs: httpx2.AsyncClient(transport=transport, **kwargs),
    )

    class Catalog(RecordingCatalog):
        async def execute(self, call: Any) -> Any:
            hit.set()
            await release.wait()
            effects.append("effect")
            return await super().execute(call)

    definition = RuntimeToolDefinition(
        name="repo_list_files",
        description="Bounded.",
        parameters_json_schema={"type": "object", "properties": {}, "additionalProperties": False},
    )
    catalog = Catalog((definition,))
    if phase == "graph-exit":
        original_enter = AsyncPregelLoop.__aenter__

        async def enter(loop: Any) -> Any:
            result = await original_enter(loop)

            async def barrier() -> None:
                hit.set()
                await release.wait()

            loop.stack.push_async_callback(barrier)
            return result

        monkeypatch.setattr(AsyncPregelLoop, "__aenter__", enter)
    baseline = set(asyncio.all_tasks())
    task = asyncio.create_task(
        adapter().invoke(
            request("engineer"), RuntimeInvocationServices(configuration=CONFIG, tools=catalog)
        )
    )
    await asyncio.wait_for(hit.wait(), 2)
    task.cancel()
    for _ in range(5):
        await asyncio.sleep(0)
        task.cancel()
    if phase == "client-close":
        assert not task.done() and not transport.closed
    release.set()
    with pytest.raises(asyncio.CancelledError) as observed:
        await asyncio.wait_for(task, 2)
    assert observed.value.args == ()
    assert transport.closed and transport.active == 0 and effects == []
    assert len(owners) == 1
    assert all(node.done() for node in owners[0].nodes | owners[0].exits)
    await asyncio.sleep(0)
    assert not [pending for pending in asyncio.all_tasks() - baseline if not pending.done()]


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in tuple(os.environ):
        if name.startswith(("LANGGRAPH_", "LANGCHAIN_", "LANGSMITH_")) or name in {
            "OPENAI_LOG",
            "OPENAI_CUSTOM_HEADERS",
        }:
            monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize(
    ("kind", "custom"),
    [(kind, False) for kind in AgentRole]
    + [(kind, True) for kind in AgentRole if kind is not AgentRole.COS],
)
async def test_real_graph_role_outputs_and_explicit_raw_transport(
    monkeypatch: pytest.MonkeyPatch, kind: AgentRole, custom: bool
) -> None:
    role = "custom-" + kind.value if custom else kind.value
    sent: list[httpx2.Request] = []

    def respond(received: httpx2.Request) -> httpx2.Response:
        sent.append(received)
        body = json.loads(received.content)
        assert body["model"] == MODEL and body["store"] is False and body["stream"] is False
        assert body["max_output_tokens"] == 4096 and body["parallel_tool_calls"] is False
        assert not {"conversation", "previous_response_id", "prompt"} & body.keys()
        assert received.headers["authorization"] == f"Bearer {KEY}"
        assert "cookie" not in received.headers
        assert all(
            tool["strict"] is (not tool["name"].startswith("submit_")) for tool in body["tools"]
        )
        return output(received, [final_call(body, kind, role)])

    clients = configure_transport(monkeypatch, respond)
    for name in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "HTTP_PROXY"):
        monkeypatch.setenv(name, "unselected-ambient")
    result = await adapter().invoke(
        request(role),
        RuntimeInvocationServices(
            configuration=CONFIG,
            tools=EMPTY_RUNTIME_TOOL_CATALOG,
            execution_kind=kind if custom else None,
        ),
    )
    assert result.output == expected_output(kind, role)
    assert result.usage is not None and result.usage.total_tokens == 15
    assert result.checkpoint_ref is None and result.provider_metadata is not None
    assert len(sent) == 1 and all(client.is_closed for client in clients)
    assert KEY not in sent[0].content.decode()


async def test_actual_graph_two_requests_and_complete_gateway_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from langgraph.graph.state import StateGraph

    captured: list[StateGraph[Any, Any, Any, Any]] = []
    original = StateGraph.compile

    def compile_graph(graph: Any, *args: Any, **kwargs: Any) -> Any:
        captured.append(graph)
        assert kwargs["checkpointer"] is False and kwargs["store"] is kwargs["cache"] is None
        return original(graph, *args, **kwargs)

    monkeypatch.setattr(StateGraph, "compile", compile_graph)
    definition = RuntimeToolDefinition(
        name="repo_list_files",
        description="Bounded.",
        parameters_json_schema={"type": "object", "properties": {}, "additionalProperties": False},
    )
    catalog = RecordingCatalog((definition,))
    bodies: list[dict[str, Any]] = []

    def respond(received: httpx2.Request) -> httpx2.Response:
        body = json.loads(received.content)
        bodies.append(body)
        if len(bodies) == 1:
            return output(
                received, [call("repo_list_files", {}, "one"), call("repo_list_files", {}, "two")]
            )
        assert len(catalog.calls) == 2
        returned = [item for item in body["input"] if item.get("type") == "function_call_output"]
        assert {item["call_id"] for item in returned} == {"one", "two"}
        assert all(json.loads(item["output"])["content"] == {"accepted": True} for item in returned)
        return output(received, [final_call(body, AgentRole.ENGINEER, "engineer")])

    configure_transport(monkeypatch, respond)
    result = await adapter().invoke(
        request("engineer"), RuntimeInvocationServices(configuration=CONFIG, tools=catalog)
    )
    assert result.usage is not None and result.usage.requests == result.usage.tool_calls == 2
    assert len(captured) == 1 and set(captured[0].nodes) == {"request", "validate", "gateway_batch"}


@pytest.mark.parametrize("fault", ["missing", "wrong", "extra", "oversized"])
async def test_whole_batch_invalid_second_call_has_no_reservation_or_effect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    tools = make_action_tools(role=AgentRole.VERIFIER)
    budget = persist_action_tools(tmp_path, tools)
    accounting = budget.begin_attempt(tools.invocation)
    invalid: dict[str, Any] = {"command_id": "python-test", "reason": "bounded"}
    if fault == "missing":
        del invalid["command_id"]
    elif fault == "wrong":
        invalid["command_id"] = "not-admitted"
    elif fault == "extra":
        invalid["grant"] = "allow"
    else:
        invalid["reason"] = "x" * 10000
    configure_transport(
        monkeypatch,
        lambda received: output(
            received,
            [
                call("run_verification", {"command_id": "python-test", "reason": "valid"}, "one"),
                call("run_verification", invalid, "two"),
            ],
        ),
    )
    with pytest.raises(FleetError) as observed:
        await adapter().invoke(
            tools.invocation,
            RuntimeInvocationServices(
                configuration=CONFIG,
                tools=tools.catalog,
                accounting=accounting,
                execution_kind=AgentRole.VERIFIER,
            ),
        )
    assert observed.value.code is ErrorCode.RUNTIME_OUTPUT_INVALID
    assert observed.value.details["runtime_diagnostic"] == {
        "category": "tool_arguments",
        "cause_category": "schema_validation",
    }
    accounting.finish(RuntimeAttemptStatus.FAILED, error_code=observed.value.code)
    snapshot = budget.snapshot(tools.invocation.run_id)
    assert snapshot.tool_calls == 0 and snapshot.model_requests == 1
    assert snapshot.unknown_requests == snapshot.outstanding_requests == 0
    assert tools.catalog.records == ()


@pytest.mark.parametrize(
    "fault",
    [
        "missing-model",
        "wrong-model",
        "incomplete",
        "error",
        "bool-input",
        "missing-output",
        "small-total",
        "detail-string",
        "detail-bool",
        "native",
        "duplicate-call",
        "duplicate-json",
        "nonfinite-json",
        "mixed-terminal",
        "unknown-tool",
        "stored",
        "background",
        "parallel",
        "continuation",
        "oversized-response",
    ],
)
async def test_untrusted_raw_response_fails_without_effect_or_implicit_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    ledger = _ledger(tmp_path, RunBudgetLimits())
    accounting = ledger.store.begin_attempt(ledger.request)
    sends = 0

    def respond(received: httpx2.Request) -> httpx2.Response:
        nonlocal sends
        sends += 1
        body = json.loads(received.content)
        terminal = final_call(body)
        data = payload([terminal])
        if fault == "missing-model":
            del data["model"]
        elif fault == "wrong-model":
            data["model"] = "different"
        elif fault == "incomplete":
            data["status"] = "incomplete"
        elif fault == "error":
            data["error"] = {"message": "synthetic-hostile"}
        elif fault == "bool-input":
            data["usage"]["input_tokens"] = True
        elif fault == "missing-output":
            del data["usage"]["output_tokens"]
        elif fault == "small-total":
            data["usage"]["total_tokens"] = 1
        elif fault.startswith("detail-"):
            data["usage"]["output_tokens_details"] = {
                "reasoning_tokens": True if fault.endswith("bool") else "synthetic-hostile"
            }
        elif fault == "native":
            data["output"] = [{"type": "web_search_call"}]
        elif fault == "duplicate-call":
            data["output"] = [terminal, terminal]
        elif fault == "mixed-terminal":
            data["output"] = [terminal, call("repo_list_files", {}, "other")]
        elif fault == "unknown-tool":
            data["output"] = [call("unregistered", {})]
        elif fault == "stored":
            data["store"] = True
        elif fault == "background":
            data["background"] = True
        elif fault == "parallel":
            data["parallel_tool_calls"] = True
        elif fault == "continuation":
            data["previous_response_id"] = "previous-response"
        elif fault == "oversized-response":
            return httpx2.Response(200, content=b" " * (2 * 1024 * 1024 + 1))
        elif fault == "duplicate-json":
            return httpx2.Response(200, content=b'{"model":"a","model":"b"}')
        elif fault == "nonfinite-json":
            return httpx2.Response(200, content=b'{"usage":NaN}')
        return httpx2.Response(200, json=data)

    clients = configure_transport(monkeypatch, respond)
    with pytest.raises(FleetError) as observed:
        await adapter().invoke(
            ledger.request,
            RuntimeInvocationServices(
                configuration=CONFIG, tools=EMPTY_RUNTIME_TOOL_CATALOG, accounting=accounting
            ),
        )
    accounting.finish(RuntimeAttemptStatus.FAILED, error_code=observed.value.code)
    snapshot = ledger.reopen().snapshot(ledger.run.run_id)
    assert sends == snapshot.model_requests == 1 and snapshot.tool_calls == 0
    assert snapshot.outstanding_requests == snapshot.reserved_tokens == 0
    assert all(client.is_closed for client in clients)
    assert observed.value.__context__ is observed.value.__cause__ is None
    assert not getattr(observed.value, "__notes__", None)


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "object", "properties": {}},
        {
            "type": "object",
            "properties": {"items": {"type": "array"}},
            "required": ["items"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {"value": {"type": "string", "enum": []}},
            "required": ["value"],
            "additionalProperties": False,
        },
    ],
)
async def test_incompatible_tool_schema_fails_before_secret_access(
    schema: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    clients = configure_transport(monkeypatch, lambda _: pytest.fail("No provider dispatch"))
    secrets = StaticSecretStore(KEY)
    catalog = RecordingCatalog(
        (
            RuntimeToolDefinition(
                name="unsupported", description="Unsupported.", parameters_json_schema=schema
            ),
        )
    )
    with pytest.raises(FleetError):
        await LangGraphRuntimeAdapter(secrets, Redactor()).invoke(
            request("engineer"), RuntimeInvocationServices(configuration=CONFIG, tools=catalog)
        )
    assert secrets.resolve_calls == 0 and catalog.calls == []
    assert clients == []


def test_original_action_schema_is_not_mutated() -> None:
    for kind in (AgentRole.ENGINEER, AgentRole.VERIFIER):
        tools = make_action_tools(role=kind)
        originals = [item.model_dump_json() for item in tools.catalog.definitions]
        for item in tools.catalog.definitions:
            wire = action_wire_schema(item.parameters_json_schema, Redactor())
            assert wire["additionalProperties"] is False
            assert set(wire["required"]) == set(wire["properties"])
        assert originals == [item.model_dump_json() for item in tools.catalog.definitions]


@pytest.mark.parametrize("mode", list(RuntimeCredentialCheck))
def test_preflight_has_no_provider_call(mode: RuntimeCredentialCheck) -> None:
    secrets = StaticSecretStore(KEY)
    result = LangGraphRuntimeAdapter(secrets, Redactor()).preflight(CONFIG, credential_check=mode)
    assert result.ready
    assert secrets.resolve_calls == (mode is RuntimeCredentialCheck.RESOLVE)


@pytest.mark.parametrize(
    "name", ["LANGGRAPH_DEFAULT_RECURSION_LIMIT", "LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2"]
)
async def test_ambient_policy_is_rejected_before_secret(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(name, "unsafe")
    secrets = StaticSecretStore(KEY)
    with pytest.raises(FleetError):
        await LangGraphRuntimeAdapter(secrets, Redactor()).invoke(
            request("cos"),
            RuntimeInvocationServices(configuration=CONFIG, tools=EMPTY_RUNTIME_TOOL_CATALOG),
        )
    assert secrets.resolve_calls == secrets.inspect_calls == 0
