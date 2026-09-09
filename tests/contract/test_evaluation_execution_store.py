from __future__ import annotations

import json
import multiprocessing
import sqlite3
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from conftest import FleetHarness
from evaluation_execution_fixtures import capture_registration, execution_fixture
from evaluation_ledger_fixtures import preflight_record

from agent_fleet.adapters.persistence.evaluation_execution import SqliteEvaluationExecutionStore
from agent_fleet.adapters.persistence.evaluations import SqliteEvaluationStore
from agent_fleet.adapters.persistence.model_profiles import SqliteModelProfileStore
from agent_fleet.adapters.persistence.runtime_budgets import SqliteRuntimeBudgetStore
from agent_fleet.adapters.persistence.sqlite import SqliteStateStore
from agent_fleet.adapters.system import SystemClock, UuidIdGenerator
from agent_fleet.domain.budgets import RunBudgetLimits
from agent_fleet.domain.errors import FleetError
from agent_fleet.domain.ids import IdPrefix
from agent_fleet.domain.models import (
    AgentInstance,
    AgentInvocation,
    AgentStatus,
    RunStatus,
    UsageRecord,
    WorkflowStage,
)
from agent_fleet.domain.security import Redactor, sha256_bytes

pytestmark = pytest.mark.asyncio


def _dump(harness: FleetHarness) -> list[str]:
    with sqlite3.connect(harness.container.state.database_path) as connection:
        return list(connection.iterdump())


@pytest.mark.parametrize("phase", ["run", "bindings", "budget", "claim"])
async def test_every_registration_step_rolls_back_without_refunding_reservation(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    fixture = execution_fixture(harness)
    seed = await capture_registration(fixture, monkeypatch)
    before = _dump(harness)
    owner, name = {
        "run": (SqliteStateStore, "_insert_run_in_transaction"),
        "bindings": (SqliteModelProfileStore, "_save_bindings_in_transaction"),
        "budget": (SqliteRuntimeBudgetStore, "_initialize_run_in_transaction"),
        "claim": (SqliteEvaluationExecutionStore, "_write"),
    }[phase]
    original = getattr(owner, name)

    def fail(*args: Any, **kwargs: Any) -> Any:
        original(*args, **kwargs)
        raise sqlite3.OperationalError("synthetic-private-rollback-message")

    with monkeypatch.context() as context:
        context.setattr(owner, name, fail)
        with pytest.raises(FleetError) as rejected:
            fixture.store.register(**seed)
    assert "synthetic-private" not in str(rejected.value)
    assert rejected.value.__context__ is None and rejected.value.__cause__ is None
    assert _dump(harness) == before
    assert fixture.store.register(**seed).claim is not None


def _register_process(
    database_path: str, seed: dict[str, Any], queue: Any, preflight: Any = None
) -> None:
    state = SqliteStateStore(Path(database_path), SystemClock(), UuidIdGenerator(), Redactor())
    try:
        if preflight is not None:
            SqliteEvaluationStore(state).record_preflight_outcome(preflight)
            queue.put(("preflight", None))
        else:
            registration = SqliteEvaluationExecutionStore(state).register(**seed)
            queue.put(
                (
                    "claimed" if registration.claim else "existing",
                    registration.record.binding.root_run_id,
                )
            )
    except FleetError as error:
        queue.put((error.code.value, None))


@pytest.mark.parametrize("race", ["same_slot", "preflight"])
async def test_two_process_atomic_slot_and_preflight_exclusion(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch, race: str
) -> None:
    fixture = execution_fixture(harness)
    seed = await capture_registration(fixture, monkeypatch)
    ledger = SqliteEvaluationStore(harness.container.state)
    reservation = ledger.snapshot(fixture.manifest.campaign_id).reservations[0]
    record = preflight_record(fixture.manifest, reservation)
    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    processes = [
        context.Process(
            target=_register_process,
            args=(
                str(harness.container.state.database_path),
                seed,
                queue,
                record if race == "preflight" and index == 1 else None,
            ),
        )
        for index in range(2)
    ]
    try:
        for process in processes:
            process.start()
        results = [queue.get(timeout=20) for _ in processes]
        for process in processes:
            process.join(timeout=20)
            assert process.exitcode == 0
        if race == "same_slot":
            assert sorted(result[0] for result in results) == ["claimed", "existing"]
            assert {result[1] for result in results} == {seed["run"].run_id}
        else:
            assert sum(result[0] in {"claimed", "preflight"} for result in results) == 1
        with sqlite3.connect(harness.container.state.database_path) as connection:
            roots = connection.execute("SELECT COUNT(*) FROM evaluation_executions").fetchone()[0]
            outcomes = connection.execute("SELECT COUNT(*) FROM evaluation_outcomes").fetchone()[0]
            assert roots + outcomes == 1
            assert connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == roots
            assert (
                connection.execute("SELECT COUNT(*) FROM runtime_budget_owners").fetchone()[0]
                == roots
            )
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        queue.close()


def _request(harness: FleetHarness, run_id: str) -> AgentInvocation:
    state = harness.container.state
    run = state.get_run(run_id)
    run = state.save_run(
        run.model_copy(update={"status": RunStatus.RUNNING, "stage": WorkflowStage.INTAKE}),
        "test.intake",
        {},
    )
    state.save_run(
        run.model_copy(update={"status": RunStatus.RUNNING, "stage": WorkflowStage.SCOPING}),
        "test.scoping",
        {},
    )
    agent = AgentInstance(
        agent_instance_id=state.ids.new(IdPrefix.AGENT),
        run_id=run_id,
        role="cos",
        task_id=None,
        status=AgentStatus.RUNNING,
        iteration=0,
        created_at=state.clock.now(),
    )
    state.save_agent_instance(agent)
    return AgentInvocation(
        run_id=run_id,
        task_id=state.ids.new(IdPrefix.TASK),
        agent_instance_id=agent.agent_instance_id,
        role="cos",
        stage=WorkflowStage.SCOPING,
        iteration=0,
        max_steps=8,
        input={"goal": "synthetic accounting"},
    )


@pytest.mark.parametrize("failure", ["unknown", "token_overrun", "active_overrun", "fenced"])
async def test_cross_root_uncertainty_or_overrun_denies_whole_future_batch(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    fixture = execution_fixture(
        harness, attempts=2, limits=RunBudgetLimits(max_total_tokens=10, max_active_seconds=10)
    )
    seeds = [await capture_registration(fixture, monkeypatch, index) for index in range(2)]
    roots = [fixture.store.register(**seed).record.binding.root_run_id for seed in seeds]
    requests = [_request(harness, root) for root in roots]
    budgets = harness.container.budgets
    attempts = [budgets.begin_attempt(request) for request in requests]
    reservation = attempts[0].reserve_request(1, requested_tokens=10)
    # Already-outstanding work is charged, not a reason to serialize the whole campaign.
    attempts[1].reserve_request(1, requested_tokens=10)
    if failure == "unknown":
        attempts[0].record_unknown(reservation)
    elif failure == "token_overrun":
        with pytest.raises(FleetError):
            attempts[0].record_response(
                reservation,
                UsageRecord(requests=1, input_tokens=12, output_tokens=0, total_tokens=12),
            )
        assert budgets.snapshot(roots[0]).reported_total_tokens == 12
    elif failure == "active_overrun":
        now = budgets.clock.now() + timedelta(seconds=11)

        class AdvancedClock:
            def now(self) -> Any:
                return now

        monkeypatch.setattr(budgets, "clock", AdvancedClock())
    else:
        fixture.store.fence(roots[1])
    with pytest.raises(FleetError):
        attempts[1].reserve_tool_batch(1, ("first-tool", "second-tool"))
    with pytest.raises(FleetError):
        attempts[1].reserve_request(2, requested_tokens=1)
    with pytest.raises(FleetError):
        budgets.begin_attempt(requests[1])
    assert budgets.snapshot(roots[1]).tool_calls == 0
    with sqlite3.connect(harness.container.state.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM runtime_tool_batches").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM tool_intents").fetchone()[0] == 0


@pytest.mark.parametrize(
    "corruption", ["hash", "self_hashed_claim", "limits", "missing_row", "secret", "oversized"]
)
async def test_corrupted_execution_never_becomes_ordinary_run(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch, corruption: str
) -> None:
    fixture = execution_fixture(harness)
    seed = await capture_registration(fixture, monkeypatch)
    registered = fixture.store.register(**seed)
    root = registered.record.binding.root_run_id
    sentinel = "execution-private-sentinel"
    harness.container.redactor.register_secret(sentinel)
    with sqlite3.connect(harness.container.state.database_path) as connection:
        if corruption == "missing_row":
            connection.execute("DELETE FROM evaluation_executions WHERE root_run_id=?", (root,))
        else:
            raw = connection.execute(
                "SELECT data_json FROM evaluation_executions WHERE root_run_id=?", (root,)
            ).fetchone()[0]
            data = json.loads(raw)
            if corruption == "self_hashed_claim":
                data["claim"]["claim_id"] = "corr_" + "f" * 32
            elif corruption == "limits":
                data["binding"]["limits"]["max_total_tokens"] += 1
            elif corruption == "secret":
                data["unexpected"] = sentinel
            elif corruption == "oversized":
                data["unexpected"] = "x" * 65_536
            raw = json.dumps(data)
            digest = "f" * 64 if corruption == "hash" else sha256_bytes(raw.encode())
            connection.execute(
                "UPDATE evaluation_executions SET data_json=?,record_sha256=? WHERE root_run_id=?",
                (raw, digest, root),
            )
    with pytest.raises(FleetError) as rejected:
        fixture.store.for_run(root)
    assert sentinel not in str(rejected.value)
    assert rejected.value.__context__ is None and rejected.value.__cause__ is None
    with pytest.raises(FleetError):
        await fixture.execute()


@pytest.mark.parametrize("failure", ["unknown", "overrun"])
async def test_campaign_denies_new_root_after_observed_failure(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    fixture = execution_fixture(harness, attempts=2, limits=RunBudgetLimits(max_total_tokens=10))
    seeds = [await capture_registration(fixture, monkeypatch, index) for index in range(2)]
    root = fixture.store.register(**seeds[0]).record.binding.root_run_id
    accounting = harness.container.budgets.begin_attempt(_request(harness, root))
    reservation = accounting.reserve_request(1, requested_tokens=10)
    if failure == "unknown":
        accounting.record_unknown(reservation)
    else:
        with pytest.raises(FleetError):
            accounting.record_response(
                reservation,
                UsageRecord(requests=1, input_tokens=12, output_tokens=0, total_tokens=12),
            )
    before = _dump(harness)
    with pytest.raises(FleetError):
        fixture.store.register(**seeds[1])
    assert _dump(harness) == before
    assert (
        len(
            SqliteEvaluationStore(harness.container.state)
            .snapshot(fixture.manifest.campaign_id)
            .reservations
        )
        == 2
    )


async def test_migration12_preserves_reservations_and_rolls_back_ddl(harness: FleetHarness) -> None:
    fixture = execution_fixture(harness)
    state = harness.container.state
    with sqlite3.connect(state.database_path) as connection:
        connection.execute("DROP TABLE evaluation_executions")
        connection.execute("DELETE FROM schema_migrations WHERE version=12")
        tables = [
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            if row[0] != "schema_migrations"
        ]
        before = {name: connection.execute(f'SELECT * FROM "{name}"').fetchall() for name in tables}
        connection.execute("CREATE TABLE evaluation_executions (fixture INTEGER)")
    with pytest.raises(FleetError):
        state.migrate()
    with sqlite3.connect(state.database_path) as connection:
        assert connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 11
        connection.execute("DROP TABLE evaluation_executions")
    assert state.migrate() == 12
    with sqlite3.connect(state.database_path) as connection:
        assert {
            name: connection.execute(f'SELECT * FROM "{name}"').fetchall() for name in tables
        } == before
    assert (
        len(SqliteEvaluationStore(state).snapshot(fixture.manifest.campaign_id).reservations) == 1
    )


async def test_absent_execution_database_is_not_created(tmp_path: Path) -> None:
    path = tmp_path / "absent" / "state.db"
    store = SqliteEvaluationExecutionStore(
        SqliteStateStore(path, SystemClock(), UuidIdGenerator(), Redactor())
    )
    with pytest.raises(FleetError):
        store.for_run("run_" + "a" * 32)
    assert not path.parent.exists()
