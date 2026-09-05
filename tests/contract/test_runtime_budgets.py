from __future__ import annotations

import asyncio
import json
import multiprocessing
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic_ai import ModelMessage, ModelResponse, ModelSettings, TextPart, ToolCallPart
from pydantic_ai.exceptions import ModelAPIError
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.usage import RequestUsage

from agent_fleet.adapters.persistence.runtime_budgets import (
    SqliteRuntimeAccounting,
    SqliteRuntimeBudgetStore,
)
from agent_fleet.adapters.persistence.sqlite import SqliteStateStore
from agent_fleet.adapters.runtime.pydantic_ai import PydanticAIRuntimeAdapter
from agent_fleet.adapters.system import UuidIdGenerator
from agent_fleet.domain.budgets import RunBudgetLimits, RuntimeAttemptStatus
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.ids import IdPrefix
from agent_fleet.domain.models import (
    AgentInstance,
    AgentInvocation,
    AgentStatus,
    Project,
    Run,
    RunStatus,
    RuntimeConfiguration,
    UsageRecord,
    WorkflowStage,
)
from agent_fleet.domain.security import Redactor
from agent_fleet.ports.runtime import EMPTY_RUNTIME_TOOL_CATALOG, RuntimeInvocationServices


@dataclass
class _Clock:
    current: datetime

    def now(self) -> datetime:
        return self.current


@dataclass
class _Ledger:
    state: SqliteStateStore
    store: SqliteRuntimeBudgetStore
    clock: _Clock
    run: Run
    request: AgentInvocation

    def reopen(self) -> SqliteRuntimeBudgetStore:
        return SqliteRuntimeBudgetStore(
            self.state.database_path, self.clock, self.state.ids, self.state.redactor, self.state
        )


def _new_agent(ledger: _Ledger, *, max_steps: int = 6) -> AgentInvocation:
    ids = ledger.state.ids
    agent = AgentInstance(
        agent_instance_id=ids.new(IdPrefix.AGENT),
        run_id=ledger.run.run_id,
        task_id=None,
        role="cos",
        status=AgentStatus.RUNNING,
        iteration=0,
        created_at=ledger.clock.now(),
    )
    ledger.state.save_agent_instance(agent)
    return AgentInvocation(
        run_id=ledger.run.run_id,
        task_id=ids.new(IdPrefix.TASK),
        agent_instance_id=agent.agent_instance_id,
        role="cos",
        stage=WorkflowStage.SCOPING,
        iteration=0,
        max_steps=max_steps,
        input={"goal": "Read-only test"},
    )


def _ledger(tmp_path: Path, limits: RunBudgetLimits | None = None) -> _Ledger:
    clock = _Clock(datetime.now(UTC))
    ids = UuidIdGenerator()
    state = SqliteStateStore(tmp_path / "state.db", clock, ids, Redactor())
    state.migrate()
    project = Project(
        project_id=ids.new(IdPrefix.PROJECT),
        canonical_root=str(tmp_path / "project"),
        identity_hash="a" * 64,
        created_at=clock.now(),
        updated_at=clock.now(),
    )
    state.save_project(project)
    run = Run(
        run_id=ids.new(IdPrefix.RUN),
        project_id=project.project_id,
        correlation_id=ids.new(IdPrefix.CORRELATION),
        goal="Read-only test",
        base_revision="b" * 40,
        target_status_fingerprint="c" * 64,
        runtime_name="pydantic-ai",
        provider_model="openai:offline-test",
        credential_ref="env:FLEET_TEST_KEY",
        created_at=clock.now(),
        updated_at=clock.now(),
    )
    state.create_run(run)
    store = SqliteRuntimeBudgetStore(state.database_path, clock, ids, state.redactor, state)
    if limits is not None:
        store.initialize_run(run.run_id, limits)
    run = state.save_run(
        run.model_copy(update={"status": RunStatus.RUNNING, "stage": WorkflowStage.INTAKE}),
        "run.started",
        {},
    )
    run = state.save_run(run.model_copy(update={"stage": WorkflowStage.SCOPING}), "run.scoping", {})
    ledger = _Ledger(
        state,
        store,
        clock,
        run,
        AgentInvocation(
            run_id=run.run_id,
            task_id=ids.new(IdPrefix.TASK),
            agent_instance_id=ids.new(IdPrefix.AGENT),
            role="cos",
            stage=WorkflowStage.SCOPING,
            iteration=0,
            max_steps=6,
            input={},
        ),
    )
    ledger.request = _new_agent(ledger)
    return ledger


def _usage(tokens: int = 10) -> UsageRecord:
    return UsageRecord(requests=1, input_tokens=tokens, output_tokens=0, total_tokens=tokens)


def test_missing_legacy_budget_is_unknown_and_cannot_be_backfilled(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    assert ledger.store.snapshot(ledger.run.run_id).completeness == "legacy_unknown"
    for operation in (
        lambda: ledger.store.begin_attempt(ledger.request),
        lambda: ledger.store.initialize_run(ledger.run.run_id, RunBudgetLimits()),
    ):
        with pytest.raises(FleetError) as captured:
            operation()
        assert captured.value.code is ErrorCode.RECOVERY_REQUIRED


def test_limits_are_immutable_and_initialization_is_idempotent(tmp_path: Path) -> None:
    limits = RunBudgetLimits(max_total_tokens=100)
    ledger = _ledger(tmp_path, limits)
    before = ledger.store.snapshot(ledger.run.run_id)
    assert ledger.reopen().initialize_run(ledger.run.run_id, limits) == before
    with pytest.raises(FleetError) as captured:
        ledger.store.initialize_run(ledger.run.run_id, RunBudgetLimits(max_total_tokens=101))
    assert captured.value.code is ErrorCode.RECOVERY_REQUIRED
    assert ledger.store.snapshot(ledger.run.run_id) == before


def test_settlement_and_finish_retries_do_not_double_charge(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path, RunBudgetLimits())
    attempt = ledger.store.begin_attempt(ledger.request)
    reservation = attempt.reserve_request(1, requested_tokens=100)
    first = attempt.record_response(reservation, _usage())
    assert attempt.record_response(reservation, _usage()) == first
    attempt.reserve_tool_batch(1, ("tool-one", "tool-two"))
    ledger.clock.current += timedelta(seconds=2)
    finished = attempt.finish(RuntimeAttemptStatus.COMPLETED)
    assert attempt.finish(RuntimeAttemptStatus.COMPLETED) == finished
    assert ledger.reopen().snapshot(ledger.run.run_id) == finished
    assert finished.model_requests == 1 and finished.tool_calls == 2
    assert finished.reported_total_tokens == 10 and finished.active_seconds == 2
    assert finished.reserved_tokens == 0 and finished.unknown_requests == 0
    types = [event.event_type for event in ledger.state.list_events(ledger.run.run_id)]
    assert types.count("runtime.response_recorded") == types.count("runtime.attempt_finished") == 1
    with pytest.raises(FleetError):
        attempt.record_response(reservation, _usage(11))
    with pytest.raises(FleetError):
        attempt.finish(RuntimeAttemptStatus.FAILED)


def test_repeated_reservation_is_not_dispatch_authority_or_extra_charge(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path, RunBudgetLimits())
    attempt = ledger.store.begin_attempt(ledger.request)
    attempt.reserve_request(1, requested_tokens=100)
    before = ledger.store.snapshot(ledger.run.run_id)
    with pytest.raises(FleetError) as captured:
        attempt.reserve_request(1, requested_tokens=100)
    assert captured.value.code is ErrorCode.RECOVERY_REQUIRED
    assert ledger.store.snapshot(ledger.run.run_id) == before


@pytest.mark.parametrize(
    "status",
    [RuntimeAttemptStatus.PAUSED, RuntimeAttemptStatus.FAILED, RuntimeAttemptStatus.CANCELLED],
)
def test_unknown_request_stays_charged_across_failure_and_restart(
    tmp_path: Path, status: RuntimeAttemptStatus
) -> None:
    ledger = _ledger(tmp_path, RunBudgetLimits())
    attempt = ledger.store.begin_attempt(ledger.request)
    attempt.reserve_request(1, requested_tokens=100)
    snapshot = attempt.finish(status)
    assert snapshot.completeness == "unknown_requests"
    assert snapshot.unknown_tokens == 100 and snapshot.unknown_requests == 1
    assert snapshot.reserved_tokens == 0
    assert ledger.reopen().snapshot(ledger.run.run_id) == snapshot
    with pytest.raises(FleetError) as captured:
        ledger.reopen().begin_attempt(ledger.request)
    assert captured.value.code is ErrorCode.RECOVERY_REQUIRED


def test_missing_total_preserves_partial_usage_and_does_not_become_zero(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path, RunBudgetLimits())
    attempt = ledger.store.begin_attempt(ledger.request)
    reservation = attempt.reserve_request(1, requested_tokens=100)
    with pytest.raises(FleetError) as captured:
        attempt.record_response(reservation, UsageRecord(requests=1, input_tokens=17))
    assert captured.value.code is ErrorCode.RECOVERY_REQUIRED
    snapshot = ledger.store.snapshot(ledger.run.run_id)
    assert snapshot.completeness == "unknown_requests"
    assert snapshot.reported_input_tokens == 17 and snapshot.reported_total_tokens == 0
    assert snapshot.unknown_tokens == 100
    with pytest.raises(FleetError):
        attempt.reserve_tool_batch(1, ("no-effect",))


def test_explicit_reported_zero_is_distinct_from_unavailable_usage(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path, RunBudgetLimits())
    attempt = ledger.store.begin_attempt(ledger.request)
    snapshot = attempt.record_response(attempt.reserve_request(1, requested_tokens=100), _usage(0))
    assert snapshot.completeness == "complete" and snapshot.unknown_tokens == 0
    assert snapshot.reported_total_tokens == 0 and snapshot.model_requests == 1


def test_logical_agent_step_limit_survives_approval_attempt_reconstruction(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path, RunBudgetLimits())
    request = ledger.request.model_copy(update={"max_steps": 2})
    first = ledger.store.begin_attempt(request)
    first.record_response(first.reserve_request(1, requested_tokens=100), _usage())
    first.finish(RuntimeAttemptStatus.PAUSED)
    second = ledger.reopen().begin_attempt(request)
    second.record_response(second.reserve_request(1, requested_tokens=100), _usage())
    second.finish(RuntimeAttemptStatus.PAUSED)
    with pytest.raises(FleetError) as captured:
        ledger.reopen().begin_attempt(request)
    assert captured.value.code is ErrorCode.RUNTIME_BUDGET_EXCEEDED
    with pytest.raises(FleetError) as changed:
        ledger.reopen().begin_attempt(request.model_copy(update={"max_steps": 3}))
    assert changed.value.code is ErrorCode.RECOVERY_REQUIRED
    assert ledger.store.snapshot(ledger.run.run_id).model_requests == 2


def test_whole_tool_batch_is_rejected_before_any_budget_mutation(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path, RunBudgetLimits(max_tool_calls=1))
    attempt = ledger.store.begin_attempt(ledger.request)
    with pytest.raises(FleetError) as captured:
        attempt.reserve_tool_batch(1, ("one", "two"))
    assert captured.value.code is ErrorCode.RUNTIME_BUDGET_EXCEEDED
    assert ledger.store.snapshot(ledger.run.run_id).tool_calls == 0
    attempt.reserve_tool_batch(1, ("one",))
    with pytest.raises(FleetError):
        attempt.reserve_tool_batch(1, ("one",))
    assert ledger.store.snapshot(ledger.run.run_id).tool_calls == 1


def test_observed_token_overshoot_is_saved_before_continuation_is_denied(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path, RunBudgetLimits(max_total_tokens=10))
    attempt = ledger.store.begin_attempt(ledger.request)
    reservation = attempt.reserve_request(1, requested_tokens=100)
    assert reservation.token_allowance == 10
    with pytest.raises(FleetError) as captured:
        attempt.record_response(reservation, _usage(12))
    assert captured.value.code is ErrorCode.RUNTIME_BUDGET_EXCEEDED
    snapshot = ledger.store.snapshot(ledger.run.run_id)
    assert snapshot.reported_total_tokens == 12 and snapshot.exhausted
    with pytest.raises(FleetError):
        attempt.reserve_tool_batch(1, ("blocked",))


def test_clock_allowance_excludes_time_waiting_after_finished_approval(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path, RunBudgetLimits(max_active_seconds=10))
    attempt = ledger.store.begin_attempt(ledger.request)
    ledger.clock.current += timedelta(seconds=3)
    assert attempt.remaining_active_seconds() == 7
    attempt.finish(RuntimeAttemptStatus.PAUSED)
    ledger.clock.current += timedelta(days=1)
    resumed = ledger.reopen().begin_attempt(ledger.request)
    assert resumed.remaining_active_seconds() == 7


def test_active_attempt_cannot_be_recreated_with_a_fresh_id(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path, RunBudgetLimits())
    first = ledger.store.begin_attempt(ledger.request)
    same = ledger.reopen().begin_attempt(ledger.request, attempt_id=first.attempt_id)
    assert same.attempt_id == first.attempt_id
    with pytest.raises(FleetError) as captured:
        ledger.reopen().begin_attempt(ledger.request)
    assert captured.value.code is ErrorCode.RECOVERY_REQUIRED
    assert ledger.store.snapshot(ledger.run.run_id).agent_invocations == 1


def test_secret_call_ids_and_corrupt_usage_fail_without_exposure(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path, RunBudgetLimits())
    sentinel = "BUDGET-REGISTERED-SECRET"
    ledger.state.redactor.register_secret(sentinel)
    attempt = ledger.store.begin_attempt(ledger.request)
    with pytest.raises(FleetError) as captured:
        attempt.reserve_tool_batch(1, (sentinel,))
    assert sentinel not in str(captured.value) and captured.value.__cause__ is None
    assert ledger.store.snapshot(ledger.run.run_id).tool_calls == 0
    reservation = attempt.reserve_request(1, requested_tokens=100)
    with sqlite3.connect(ledger.state.database_path) as connection:
        connection.execute("UPDATE runtime_model_requests SET data_json = ?", (sentinel,))
    with pytest.raises(FleetError) as corrupt:
        attempt.record_response(reservation, _usage())
    assert sentinel not in str(corrupt.value) and corrupt.value.__cause__ is None
    assert sentinel not in repr(ledger.state.list_events(ledger.run.run_id))


def _race_request(path: str, timestamp: str, attempt_id: str, barrier: Any, queue: Any) -> None:
    clock = _Clock(datetime.fromisoformat(timestamp))
    ids = UuidIdGenerator()
    state = SqliteStateStore(Path(path), clock, ids, Redactor())
    store = SqliteRuntimeBudgetStore(Path(path), clock, ids, state.redactor, state)
    barrier.wait(timeout=10)
    try:
        reservation = SqliteRuntimeAccounting(store, attempt_id).reserve_request(
            1, requested_tokens=100
        )
        queue.put(("reserved", reservation.token_allowance))
    except FleetError as error:
        queue.put((error.code.value, 0))


def test_two_processes_cannot_reserve_the_same_remaining_budget(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path, RunBudgetLimits(max_model_requests=1, max_total_tokens=100))
    attempts = [
        ledger.store.begin_attempt(ledger.request),
        ledger.store.begin_attempt(_new_agent(ledger)),
    ]
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(2)
    queue = context.Queue()
    processes = [
        context.Process(
            target=_race_request,
            args=(
                str(ledger.state.database_path),
                ledger.clock.now().isoformat(),
                item.attempt_id,
                barrier,
                queue,
            ),
        )
        for item in attempts
    ]
    try:
        for process in processes:
            process.start()
        results = [queue.get(timeout=15) for _ in processes]
        for process in processes:
            process.join(timeout=15)
            assert process.exitcode == 0
        assert sorted(results) == [(ErrorCode.RUNTIME_BUDGET_EXCEEDED.value, 0), ("reserved", 100)]
        snapshot = ledger.store.snapshot(ledger.run.run_id)
        assert snapshot.model_requests == 1 and snapshot.reserved_tokens == 100
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        queue.close()


def _related_run(ledger: _Ledger, *, parent: bool) -> Run:
    run = ledger.run.model_copy(
        update={
            "run_id": ledger.state.ids.new(IdPrefix.RUN),
            "correlation_id": ledger.state.ids.new(IdPrefix.CORRELATION),
            "status": RunStatus.CREATED,
            "stage": None,
        }
    )
    ledger.state.create_run(run)
    limits = ledger.store.snapshot(ledger.run.run_id).limits
    assert limits is not None
    ledger.store.initialize_run(
        run.run_id, limits, parent_run_id=ledger.run.run_id if parent else None
    )
    return run


@pytest.mark.parametrize("spent", [False, True])
def test_root_owner_mapping_cannot_redirect_to_another_same_project_budget(
    tmp_path: Path, spent: bool
) -> None:
    ledger = _ledger(tmp_path, RunBudgetLimits())
    other = _related_run(ledger, parent=False)
    if spent:
        attempt = ledger.store.begin_attempt(ledger.request)
        attempt.reserve_tool_batch(1, ("charged",))
        attempt.finish(RuntimeAttemptStatus.PAUSED)
    with sqlite3.connect(ledger.state.database_path) as connection:
        connection.execute(
            "UPDATE runtime_budget_runs SET owner_run_id = ? WHERE run_id = ?",
            (other.run_id, ledger.run.run_id),
        )
    with pytest.raises(FleetError) as captured:
        ledger.reopen().snapshot(ledger.run.run_id)
    assert captured.value.code is ErrorCode.RECOVERY_REQUIRED


def test_declared_child_shares_exact_root_limits_and_usage_without_remapping(
    tmp_path: Path,
) -> None:
    ledger = _ledger(tmp_path, RunBudgetLimits())
    child = _related_run(ledger, parent=True)
    attempt = ledger.store.begin_attempt(ledger.request)
    attempt.reserve_tool_batch(1, ("parent-charge",))
    parent = ledger.store.snapshot(ledger.run.run_id)
    shared = ledger.reopen().snapshot(child.run_id)
    assert shared.owner_run_id == ledger.run.run_id
    assert shared.tool_calls == parent.tool_calls == 1
    assert shared.limits == parent.limits
    other = _related_run(ledger, parent=False)
    with sqlite3.connect(ledger.state.database_path) as connection:
        connection.execute(
            "UPDATE runtime_budget_runs SET owner_run_id = ? WHERE run_id = ?",
            (other.run_id, child.run_id),
        )
    with pytest.raises(FleetError):
        ledger.reopen().snapshot(child.run_id)


@pytest.mark.parametrize("timing", ["before_attempt", "after_attempt"])
@pytest.mark.parametrize("mutation", ["sql_run", "json_id", "json_task"])
def test_agent_sql_and_json_identities_are_revalidated_before_accounting_dispatch(
    tmp_path: Path, timing: str, mutation: str
) -> None:
    ledger = _ledger(tmp_path, RunBudgetLimits())
    other = _related_run(ledger, parent=False)
    attempt = ledger.store.begin_attempt(ledger.request) if timing == "after_attempt" else None
    with sqlite3.connect(ledger.state.database_path) as connection:
        if mutation == "sql_run":
            connection.execute(
                "UPDATE agent_instances SET run_id = ? WHERE agent_instance_id = ?",
                (other.run_id, ledger.request.agent_instance_id),
            )
        else:
            row = connection.execute(
                "SELECT data_json FROM agent_instances WHERE agent_instance_id = ?",
                (ledger.request.agent_instance_id,),
            ).fetchone()
            payload = json.loads(row[0])
            payload["agent_instance_id" if mutation == "json_id" else "task_id"] = (
                ledger.state.ids.new(IdPrefix.AGENT if mutation == "json_id" else IdPrefix.TASK)
            )
            connection.execute(
                "UPDATE agent_instances SET data_json = ? WHERE agent_instance_id = ?",
                (json.dumps(payload), ledger.request.agent_instance_id),
            )
    with pytest.raises(FleetError) as captured:
        if attempt is None:
            ledger.reopen().begin_attempt(ledger.request)
        else:
            attempt.reserve_request(1, requested_tokens=100)
    assert captured.value.code is ErrorCode.RECOVERY_REQUIRED
    assert ledger.store.snapshot(ledger.run.run_id).model_requests == 0


def test_malformed_persisted_run_has_no_raw_exception_context_or_secret(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path, RunBudgetLimits())
    sentinel = "BUDGET-PERSISTED-SECRET"
    ledger.state.redactor.register_secret(sentinel)
    with sqlite3.connect(ledger.state.database_path) as connection:
        payload = ledger.run.model_dump(mode="json")
        payload["unknown"] = sentinel
        connection.execute(
            "UPDATE runs SET data_json = ? WHERE run_id = ?",
            (json.dumps(payload), ledger.run.run_id),
        )
    with pytest.raises(FleetError) as captured:
        ledger.reopen().snapshot(ledger.run.run_id)
    assert captured.value.code is ErrorCode.RECOVERY_REQUIRED
    assert captured.value.__cause__ is None and captured.value.__context__ is None
    assert sentinel not in repr(captured.value)
    with sqlite3.connect(ledger.state.database_path) as connection:
        payload["unknown"] = "ordinary-invalid-value"
        connection.execute(
            "UPDATE runs SET data_json = ? WHERE run_id = ?",
            (json.dumps(payload), ledger.run.run_id),
        )
    with pytest.raises(FleetError) as invalid:
        ledger.reopen().snapshot(ledger.run.run_id)
    assert invalid.value.__cause__ is None and invalid.value.__context__ is None


def test_accounting_audit_failure_rolls_back_request_reservation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = _ledger(tmp_path, RunBudgetLimits())
    attempt = ledger.store.begin_attempt(ledger.request)
    before = ledger.store.snapshot(ledger.run.run_id)

    def fail_event(*args: object, **kwargs: object) -> None:
        raise sqlite3.OperationalError("injected audit write failure")

    monkeypatch.setattr(ledger.store, "_event", fail_event)
    with pytest.raises(FleetError) as captured:
        attempt.reserve_request(1, requested_tokens=100)
    assert captured.value.code is ErrorCode.STATE_UNAVAILABLE
    assert captured.value.__cause__ is None and captured.value.__context__ is None
    assert ledger.store.snapshot(ledger.run.run_id) == before


def _scope_output(info: AgentInfo) -> ToolCallPart:
    return ToolCallPart(
        info.output_tools[0].name,
        {
            "normalized_goal": "A bounded read-only answer.",
            "response": "A bounded answer.",
            "workflow": "code-change",
            "change_kind": "read_only",
            "fleet_strategy": "direct",
            "allowed_paths": [],
            "forbidden_paths": [".git", ".fleet"],
            "acceptance_criteria": [
                {"criterion_id": "answer", "description": "Answer the question."}
            ],
            "required_evidence": ["control_plane_plan"],
        },
        tool_call_id="scope-output",
    )


def _services(attempt: SqliteRuntimeAccounting) -> RuntimeInvocationServices:
    return RuntimeInvocationServices(
        configuration=RuntimeConfiguration(
            runtime_name="pydantic-ai",
            provider_model="openai:offline-test",
            credential_ref="env:FLEET_TEST_KEY",
            max_total_tokens=1000,
            max_requests=8,
            max_retries=1,
            timeout_seconds=120,
        ),
        tools=EMPTY_RUNTIME_TOOL_CATALOG,
        accounting=attempt,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("max_steps", [1, 2])
async def test_physical_structured_output_retries_are_charged_and_role_bounded(
    tmp_path: Path, max_steps: int
) -> None:
    ledger = _ledger(tmp_path, RunBudgetLimits())
    request = ledger.request.model_copy(update={"max_steps": max_steps})
    attempt = ledger.store.begin_attempt(request)
    calls = 0

    async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal calls
        calls += 1
        output = (
            ToolCallPart(info.output_tools[0].name, {"invalid": "schema"}, tool_call_id="bad")
            if calls == 1
            else _scope_output(info)
        )
        return ModelResponse(parts=[output], usage=RequestUsage(input_tokens=3, output_tokens=2))

    adapter = PydanticAIRuntimeAdapter.for_test_model(FunctionModel(respond))
    if max_steps == 1:
        with pytest.raises(FleetError) as captured:
            await adapter.invoke(request, _services(attempt))
        assert captured.value.code is ErrorCode.RUNTIME_BUDGET_EXCEEDED
        attempt.finish(RuntimeAttemptStatus.FAILED, error_code=captured.value.code)
    else:
        await adapter.invoke(request, _services(attempt))
        attempt.finish(RuntimeAttemptStatus.COMPLETED)
    snapshot = ledger.reopen().snapshot(ledger.run.run_id)
    assert calls == snapshot.model_requests == max_steps
    assert snapshot.reported_total_tokens == 5 * max_steps
    assert snapshot.unknown_requests == snapshot.outstanding_requests == 0


@pytest.mark.asyncio
async def test_response_usage_persists_before_rejecting_secret_companion_text(
    tmp_path: Path,
) -> None:
    ledger = _ledger(tmp_path, RunBudgetLimits())
    sentinel = "PROVIDER-RESPONSE-SECRET"
    ledger.state.redactor.register_secret(sentinel)
    attempt = ledger.store.begin_attempt(ledger.request)

    async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(
            parts=[TextPart(sentinel), _scope_output(info)],
            usage=RequestUsage(input_tokens=3, output_tokens=2),
        )

    adapter = PydanticAIRuntimeAdapter.for_test_model(
        FunctionModel(respond), redactor=ledger.state.redactor
    )
    with pytest.raises(FleetError) as captured:
        await adapter.invoke(ledger.request, _services(attempt))
    assert captured.value.code is ErrorCode.COMMAND_DENIED
    snapshot = attempt.finish(RuntimeAttemptStatus.FAILED, error_code=captured.value.code)
    assert snapshot.reported_total_tokens == 5 and snapshot.model_requests == 1
    assert sentinel not in repr(ledger.state.list_events(ledger.run.run_id))


@pytest.mark.asyncio
async def test_unavailable_sdk_zero_usage_is_conservatively_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = _ledger(tmp_path, RunBudgetLimits())
    attempt = ledger.store.begin_attempt(ledger.request)

    async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[_scope_output(info)], usage=RequestUsage())

    model = FunctionModel(respond)
    request_model = model.request

    async def without_usage(
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        response = await request_model(messages, model_settings, model_request_parameters)
        # FunctionModel estimates omitted usage itself. Remove that test-only
        # estimate to exercise an actual model boundary with unavailable counters.
        response.usage = RequestUsage()
        return response

    monkeypatch.setattr(model, "request", without_usage)
    adapter = PydanticAIRuntimeAdapter.for_test_model(model)
    with pytest.raises(FleetError) as captured:
        await adapter.invoke(ledger.request, _services(attempt))
    assert captured.value.code is ErrorCode.RECOVERY_REQUIRED
    snapshot = attempt.finish(RuntimeAttemptStatus.FAILED, error_code=captured.value.code)
    assert snapshot.completeness == "unknown_requests" and snapshot.unknown_tokens == 1000


@pytest.mark.asyncio
async def test_provider_error_charges_unknown_without_persisting_exception_text(
    tmp_path: Path,
) -> None:
    ledger = _ledger(tmp_path, RunBudgetLimits())
    sentinel = "UNTRUSTED-PROVIDER-ERROR-DETAIL"
    attempt = ledger.store.begin_attempt(ledger.request)

    async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        raise ModelAPIError("offline:test", sentinel)

    adapter = PydanticAIRuntimeAdapter.for_test_model(FunctionModel(respond))
    with pytest.raises(FleetError) as captured:
        await adapter.invoke(ledger.request, _services(attempt))
    assert captured.value.code is ErrorCode.PROVIDER_FAILED
    assert captured.value.__cause__ is None and captured.value.__context__ is None
    snapshot = attempt.finish(RuntimeAttemptStatus.FAILED, error_code=captured.value.code)
    assert snapshot.unknown_requests == 1 and snapshot.unknown_tokens == 1000
    assert sentinel not in repr(ledger.state.list_events(ledger.run.run_id))


@pytest.mark.asyncio
@pytest.mark.parametrize("terminate", ["cancel", "budget_timeout"])
async def test_blocked_provider_is_bounded_and_unknown_charge_survives_termination(
    tmp_path: Path, terminate: str
) -> None:
    ledger = _ledger(tmp_path, RunBudgetLimits(max_active_seconds=1))
    attempt = ledger.store.begin_attempt(ledger.request)
    if terminate == "budget_timeout":
        ledger.clock.current += timedelta(seconds=0.95)
    entered = asyncio.Event()

    async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        entered.set()
        await asyncio.Event().wait()
        raise AssertionError("blocked provider should not complete")

    adapter = PydanticAIRuntimeAdapter.for_test_model(FunctionModel(respond))
    execution = asyncio.create_task(adapter.invoke(ledger.request, _services(attempt)))
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        if terminate == "cancel":
            execution.cancel()
            with pytest.raises(asyncio.CancelledError):
                await execution
            status = RuntimeAttemptStatus.CANCELLED
        else:
            with pytest.raises(FleetError) as captured:
                await asyncio.wait_for(execution, timeout=2)
            assert captured.value.code is ErrorCode.RUNTIME_BUDGET_EXCEEDED
            status = RuntimeAttemptStatus.FAILED
        snapshot = attempt.finish(status)
        assert snapshot.model_requests == snapshot.unknown_requests == 1
        assert snapshot.unknown_tokens == 1000 and snapshot.tool_calls == 0
        assert ledger.reopen().snapshot(ledger.run.run_id) == snapshot
    finally:
        if not execution.done():
            execution.cancel()
            await asyncio.gather(execution, return_exceptions=True)
