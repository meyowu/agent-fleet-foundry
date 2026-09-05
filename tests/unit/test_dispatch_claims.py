"""Durable dispatch fencing is independent of process-local gateway state."""

from __future__ import annotations

import base64
import multiprocessing
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from importlib.resources import files
from multiprocessing.connection import Connection
from multiprocessing.synchronize import Barrier as ProcessBarrier
from pathlib import Path
from threading import Barrier

import pytest

from agent_fleet.adapters.persistence.sqlite import SUPPORTED_SCHEMA_VERSION, SqliteStateStore
from agent_fleet.adapters.system import SystemClock, UuidIdGenerator
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.ids import IdPrefix
from agent_fleet.domain.models import (
    AcceptanceCriterion,
    AgentInstance,
    AgentStatus,
    CanonicalResource,
    FleetEvent,
    IntentStatus,
    Project,
    Run,
    RunStatus,
    TaskSpec,
    ToolIntent,
    WorkflowStage,
)
from agent_fleet.domain.security import Redactor, canonical_json_hash


@dataclass
class DispatchFixture:
    state: SqliteStateStore
    run: Run
    task: TaskSpec
    agent: AgentInstance
    intent: ToolIntent
    intent_hash: str

    def reopen(self) -> SqliteStateStore:
        return _open(self.state.database_path)


def _open(path: Path) -> SqliteStateStore:
    return SqliteStateStore(path, SystemClock(), UuidIdGenerator(), Redactor())


def _fixture(
    tmp_path: Path, *, legacy: bool = False, parameter: str = "reviewed"
) -> DispatchFixture:
    state = _open(tmp_path / "dispatch.db")
    if legacy:
        with state._connect() as connection:
            connection.execute(
                "CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT)"
            )
            for version in range(1, 4):
                script = (
                    files("agent_fleet.adapters.persistence.migrations")
                    .joinpath(f"{version:04d}.sql")
                    .read_text(encoding="utf-8")
                )
                connection.executescript(script)
                connection.execute(
                    "INSERT INTO schema_migrations VALUES (?, ?)",
                    (version, state.clock.now().isoformat()),
                )
    else:
        state.migrate()
    now = state.clock.now()
    project = Project(
        project_id=state.ids.new(IdPrefix.PROJECT),
        canonical_root=str(tmp_path / "repository"),
        identity_hash="1" * 64,
        created_at=now,
        updated_at=now,
    )
    state.save_project(project)
    task_id = state.ids.new(IdPrefix.TASK)
    run = Run(
        run_id=state.ids.new(IdPrefix.RUN),
        project_id=project.project_id,
        correlation_id=state.ids.new(IdPrefix.CORRELATION),
        goal="Prove one durable dispatch",
        base_revision="a" * 40,
        target_status_fingerprint="2" * 64,
        status=RunStatus.RUNNING,
        stage=WorkflowStage.IMPLEMENTING,
        task_id=task_id,
        created_at=now,
        updated_at=now,
    )
    state.create_run(run)
    task = TaskSpec(
        task_id=task_id,
        run_id=run.run_id,
        original_goal=run.goal,
        normalized_goal=run.goal,
        base_revision=run.base_revision,
        allowed_paths=["src"],
        forbidden_paths=[],
        acceptance_criteria=[AcceptanceCriterion(criterion_id="ac-1", description="Runs once")],
        required_evidence=["canonical_patch", "command_evidence"],
        max_repair_iterations=1,
        config_snapshot_hash="3" * 64,
        created_at=now,
    )
    state.save_task(task)
    agent = AgentInstance(
        agent_instance_id=state.ids.new(IdPrefix.AGENT),
        run_id=run.run_id,
        task_id=task_id,
        role="engineer",
        status=AgentStatus.RUNNING,
        iteration=0,
        created_at=now,
    )
    state.save_agent_instance(agent)
    intent = ToolIntent(
        intent_id=state.ids.new(IdPrefix.INTENT),
        run_id=run.run_id,
        task_id=task_id,
        agent_instance_id=agent.agent_instance_id,
        principal_role="engineer",
        workflow=task.workflow,
        stage=WorkflowStage.IMPLEMENTING,
        action="command.run",
        resource=CanonicalResource(kind="project_command", identifier="pytest"),
        parameters={"command_spec_sha256": "4" * 64, "argument": parameter},
        reason="Run the exact reviewed command",
        side_effect=True,
        idempotency_key="one-command",
    )
    intent_hash = canonical_json_hash(intent.model_dump(mode="json"))
    state.reserve_intent(intent, intent_hash)
    return DispatchFixture(state, run, task, agent, intent, intent_hash)


def _claims(state: SqliteStateStore) -> list[tuple[str, str, str]]:
    with state._connect() as connection:
        return [
            (row["intent_id"], row["intent_hash"], row["claimed_at"])
            for row in connection.execute("SELECT * FROM tool_dispatch_claims ORDER BY intent_id")
        ]


def _claim_events(fixture: DispatchFixture) -> list[FleetEvent]:
    return [
        event
        for event in fixture.state.list_events(fixture.run.run_id)
        if event.event_type == "intent.dispatch_claimed"
    ]


def test_claim_is_permanent_across_reopen_and_completion(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    assert (
        fixture.state.claim_reserved_intent_for_dispatch(
            fixture.intent.intent_id, fixture.intent_hash
        )
        is True
    )
    claim = _claims(fixture.state)
    assert len(claim) == 1
    assert claim[0][:2] == (fixture.intent.intent_id, fixture.intent_hash)
    assert datetime.fromisoformat(claim[0][2]).utcoffset() is not None
    events = _claim_events(fixture)
    assert len(events) == 1
    assert events[0].agent_instance_id == fixture.agent.agent_instance_id
    assert events[0].payload == {
        "intent_id": fixture.intent.intent_id,
        "intent_hash": fixture.intent_hash,
    }
    reserved = fixture.state.get_intent(fixture.intent.intent_id)
    assert reserved.status is IntentStatus.RESERVED
    assert reserved.result is None
    for _ in range(2):
        assert (
            fixture.reopen().claim_reserved_intent_for_dispatch(
                fixture.intent.intent_id, fixture.intent_hash
            )
            is False
        )
    completed = fixture.state.complete_intent(fixture.intent.intent_id, {"exit_code": 0})
    assert completed.status is IntentStatus.EXECUTED
    assert (
        fixture.reopen().claim_reserved_intent_for_dispatch(
            fixture.intent.intent_id, fixture.intent_hash
        )
        is False
    )
    assert _claims(fixture.state) == claim
    assert _claim_events(fixture) == events
    assert fixture.state.get_intent(fixture.intent.intent_id) == completed


def test_parallel_thread_claims_have_one_winner_and_one_event(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    barrier = Barrier(8, timeout=10)

    def claim(_: int) -> bool:
        reopened = fixture.reopen()
        barrier.wait()
        return reopened.claim_reserved_intent_for_dispatch(
            fixture.intent.intent_id, fixture.intent_hash
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(claim, range(8)))
    assert results.count(True) == 1
    assert results.count(False) == 7
    assert len(_claims(fixture.state)) == len(_claim_events(fixture)) == 1


def _claim_from_process(
    path: Path,
    intent_id: str,
    intent_hash: str,
    barrier: ProcessBarrier,
    result: Connection,
) -> None:
    try:
        state = _open(path)
        barrier.wait(timeout=20)
        result.send(state.claim_reserved_intent_for_dispatch(intent_id, intent_hash))
    finally:
        result.close()


def test_parallel_spawned_processes_share_one_durable_claim(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(4)
    pipes = [context.Pipe(duplex=False) for _ in range(4)]
    processes = [
        context.Process(
            target=_claim_from_process,
            args=(
                fixture.state.database_path,
                fixture.intent.intent_id,
                fixture.intent_hash,
                barrier,
                child,
            ),
        )
        for _, child in pipes
    ]
    try:
        for process in processes:
            process.start()
        for _, child in pipes:
            child.close()
        results: list[bool] = []
        for parent, _ in pipes:
            assert parent.poll(30), "A dispatch contender did not return"
            result = parent.recv()
            assert isinstance(result, bool)
            results.append(result)
        for process in processes:
            process.join(timeout=10)
            assert process.exitcode == 0
        assert results.count(True) == 1
        assert results.count(False) == 3
        assert len(_claims(fixture.state)) == len(_claim_events(fixture)) == 1
        assert (
            fixture.reopen().claim_reserved_intent_for_dispatch(
                fixture.intent.intent_id, fixture.intent_hash
            )
            is False
        )
    finally:
        for parent, child in pipes:
            parent.close()
            child.close()
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)


def test_failed_claim_event_rolls_back_receipt_and_event_before_reopen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    events = fixture.state.list_events(fixture.run.run_id)
    original_insert = fixture.state._insert_event

    def fail_after_event_insert(connection: sqlite3.Connection, event: FleetEvent) -> FleetEvent:
        persisted = original_insert(connection, event)
        if event.event_type == "intent.dispatch_claimed":
            raise RuntimeError("simulated event persistence failure")
        return persisted

    monkeypatch.setattr(fixture.state, "_insert_event", fail_after_event_insert)
    with pytest.raises(RuntimeError, match="simulated event persistence failure"):
        fixture.state.claim_reserved_intent_for_dispatch(
            fixture.intent.intent_id, fixture.intent_hash
        )
    assert _claims(fixture.state) == []
    assert fixture.state.list_events(fixture.run.run_id) == events
    assert fixture.state.get_intent(fixture.intent.intent_id).status is IntentStatus.RESERVED
    assert (
        fixture.reopen().claim_reserved_intent_for_dispatch(
            fixture.intent.intent_id, fixture.intent_hash
        )
        is True
    )
    assert len(_claims(fixture.state)) == len(_claim_events(fixture)) == 1


@pytest.mark.parametrize(
    "invalid_context",
    [
        "missing_intent",
        "changed_hash",
        "denied",
        "pending_approval",
        "executed",
        "run_paused",
        "run_failed",
        "run_stage",
        "run_pending",
        "run_task",
        "task_workflow",
        "agent_created",
        "agent_paused",
        "agent_failed",
        "agent_completed",
        "agent_completed_at",
        "agent_role",
        "agent_task",
        "agent_run",
        "intent_json_parameters",
        "intent_column_hash",
        "intent_column_status",
        "run_column_status",
    ],
)
def test_invalid_current_dispatch_context_cannot_claim(
    tmp_path: Path, invalid_context: str
) -> None:
    fixture = _fixture(tmp_path)
    state = fixture.state
    intent_id = fixture.intent.intent_id
    intent_hash = fixture.intent_hash
    with state._connect() as connection:
        if invalid_context == "missing_intent":
            intent_id = state.ids.new(IdPrefix.INTENT)
        elif invalid_context == "changed_hash":
            intent_hash = "f" * 64
        elif invalid_context in {"denied", "pending_approval", "executed"}:
            stored = state.get_intent(intent_id).model_copy(
                update={"status": IntentStatus(invalid_context)}
            )
            state._update_intent(connection, stored)
        elif invalid_context.startswith("run_") and invalid_context != "run_column_status":
            updates: dict[str, object]
            if invalid_context == "run_paused":
                updates = {"status": RunStatus.PAUSED_FOR_APPROVAL}
            elif invalid_context == "run_failed":
                updates = {"status": RunStatus.FAILED}
            elif invalid_context == "run_stage":
                updates = {"stage": WorkflowStage.VERIFYING}
            elif invalid_context == "run_pending":
                updates = {"pending_approval_id": state.ids.new(IdPrefix.APPROVAL)}
            else:
                updates = {"task_id": state.ids.new(IdPrefix.TASK)}
            state._update_run(connection, fixture.run.model_copy(update=updates))
        elif invalid_context == "task_workflow":
            changed_task = fixture.task.model_copy(update={"workflow": "other-workflow"})
            connection.execute(
                "UPDATE tasks SET data_json = ? WHERE task_id = ?",
                (changed_task.model_dump_json(), fixture.task.task_id),
            )
        elif invalid_context.startswith("agent_"):
            if invalid_context in {
                "agent_created",
                "agent_paused",
                "agent_failed",
                "agent_completed",
            }:
                updates = {"status": AgentStatus(invalid_context.removeprefix("agent_"))}
            elif invalid_context == "agent_completed_at":
                updates = {"completed_at": state.clock.now()}
            elif invalid_context == "agent_role":
                updates = {"role": "verifier"}
            elif invalid_context == "agent_task":
                updates = {"task_id": state.ids.new(IdPrefix.TASK)}
            else:
                updates = {"run_id": state.ids.new(IdPrefix.RUN)}
            changed_agent = fixture.agent.model_copy(update=updates)
            connection.execute(
                "UPDATE agent_instances SET data_json = ? WHERE agent_instance_id = ?",
                (changed_agent.model_dump_json(), fixture.agent.agent_instance_id),
            )
        elif invalid_context == "intent_json_parameters":
            stored = state.get_intent(intent_id).model_copy(
                update={
                    "intent": fixture.intent.model_copy(update={"parameters": {"changed": True}})
                }
            )
            state._update_intent(connection, stored)
        elif invalid_context == "intent_column_hash":
            connection.execute(
                "UPDATE tool_intents SET intent_hash = ? WHERE intent_id = ?", ("f" * 64, intent_id)
            )
        elif invalid_context == "intent_column_status":
            connection.execute(
                "UPDATE tool_intents SET status = 'executed' WHERE intent_id = ?", (intent_id,)
            )
        elif invalid_context == "run_column_status":
            connection.execute(
                "UPDATE runs SET status = 'failed' WHERE run_id = ?", (fixture.run.run_id,)
            )
        else:
            raise AssertionError(invalid_context)
    events = state.list_events(fixture.run.run_id)
    with pytest.raises(FleetError) as failure:
        state.claim_reserved_intent_for_dispatch(intent_id, intent_hash)
    assert failure.value.code is ErrorCode.RECOVERY_REQUIRED
    assert _claims(state) == []
    assert state.list_events(fixture.run.run_id) == events


@pytest.mark.parametrize("encoded", [False, True])
def test_registered_secret_parameters_never_receive_claim_or_echo(
    tmp_path: Path, encoded: bool
) -> None:
    secret = "dispatch-secret-not-for-events-90742"
    representation = base64.b64encode(secret.encode()).decode() if encoded else secret
    fixture = _fixture(tmp_path, parameter=representation)
    fixture.state.redactor.register_secret(secret)
    before = fixture.state.list_events(fixture.run.run_id)
    with pytest.raises(FleetError) as failure:
        fixture.state.claim_reserved_intent_for_dispatch(
            fixture.intent.intent_id, fixture.intent_hash
        )
    assert failure.value.code is ErrorCode.RECOVERY_REQUIRED
    assert secret not in str(failure.value)
    assert representation not in str(failure.value)
    assert _claims(fixture.state) == []
    assert fixture.state.list_events(fixture.run.run_id) == before
    assert all(representation not in event.model_dump_json() for event in before)


def test_existing_claim_cannot_be_rebound_to_changed_hash(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    assert fixture.state.claim_reserved_intent_for_dispatch(
        fixture.intent.intent_id, fixture.intent_hash
    )
    claims = _claims(fixture.state)
    events = fixture.state.list_events(fixture.run.run_id)
    with pytest.raises(FleetError) as failure:
        fixture.reopen().claim_reserved_intent_for_dispatch(fixture.intent.intent_id, "f" * 64)
    assert failure.value.code is ErrorCode.RECOVERY_REQUIRED
    assert _claims(fixture.state) == claims
    assert fixture.state.list_events(fixture.run.run_id) == events


def test_v3_upgrade_adds_claim_table_without_rewriting_existing_intent(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path, legacy=True)
    before = fixture.state.get_intent(fixture.intent.intent_id)
    assert fixture.state.migrate() == SUPPORTED_SCHEMA_VERSION
    assert fixture.state.get_intent(fixture.intent.intent_id) == before
    assert _claims(fixture.state) == []
    assert fixture.state.claim_reserved_intent_for_dispatch(
        fixture.intent.intent_id, fixture.intent_hash
    )
    assert fixture.reopen().migrate() == SUPPORTED_SCHEMA_VERSION
    assert (
        fixture.reopen().claim_reserved_intent_for_dispatch(
            fixture.intent.intent_id, fixture.intent_hash
        )
        is False
    )


def test_public_agent_getter_reopens_exact_identity_and_rejects_unknown(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    assert fixture.reopen().get_agent_instance(fixture.agent.agent_instance_id) == fixture.agent
    with pytest.raises(FleetError) as failure:
        fixture.state.get_agent_instance("agent_unknown")
    assert failure.value.code is ErrorCode.RESOURCE_NOT_FOUND


@pytest.mark.parametrize("corruption", ["json", "agent_instance_id", "run_id", "task_id", "role"])
def test_public_agent_getter_rejects_malformed_or_mismatched_rows(
    tmp_path: Path, corruption: str
) -> None:
    fixture = _fixture(tmp_path)
    secret = "malformed-agent-private-value-58290"
    if corruption == "json":
        content = "{" + secret
    else:
        replacement = {
            "agent_instance_id": "agent_other",
            "run_id": "run_other",
            "task_id": "task_other",
            "role": "verifier",
        }[corruption]
        content = fixture.agent.model_copy(update={corruption: replacement}).model_dump_json()
    with fixture.state._connect() as connection:
        connection.execute(
            "UPDATE agent_instances SET data_json = ? WHERE agent_instance_id = ?",
            (content, fixture.agent.agent_instance_id),
        )
    with pytest.raises(FleetError) as failure:
        fixture.reopen().get_agent_instance(fixture.agent.agent_instance_id)
    assert failure.value.code is ErrorCode.RECOVERY_REQUIRED
    assert secret not in str(failure.value)
