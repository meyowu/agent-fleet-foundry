"""Public Workflow-backed observations, never live provider execution."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sqlite3
import subprocess
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from conftest import FleetHarness
from evaluation_execution_fixtures import execution_fixture

from agent_fleet.adapters.artifacts.local import LocalArtifactStore
from agent_fleet.adapters.persistence import evaluation_capture as capture
from agent_fleet.adapters.persistence.evaluation_evidence import SqliteEvaluationEvidence
from agent_fleet.adapters.runtime.fake import FakeRuntimeAdapter
from agent_fleet.application.evaluation_outcomes import EvaluationOutcomeService
from agent_fleet.application.runtime import RuntimeRegistry
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import (
    AgentInvocation,
    AgentInvocationResult,
    FakeScenario,
    RunStatus,
)
from agent_fleet.ports.runtime import RuntimeInvocationServices

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture(autouse=True)
def observation_children_are_reaped(
    monkeypatch: pytest.MonkeyPatch, record_property: Callable[[str, object], None]
) -> Iterator[None]:
    original = capture._spawn_capture
    children: list[tuple[subprocess.Popen[bytes], Path]] = []

    def spawn(stage: Path) -> subprocess.Popen[bytes]:
        child = original(stage)
        children.append((child, stage))
        return child

    monkeypatch.setattr(capture, "_spawn_capture", spawn)
    yield
    records = []
    for child, stage in children:
        assert child.poll() is not None and not stage.exists()
        with pytest.raises(ProcessLookupError):
            os.kill(child.pid, 0)
        records.append(
            {"pid": child.pid, "stage": str(stage), "reaped": True, "stage_absent": True}
        )
    record_property("clean_capture_children", json.dumps(records, sort_keys=True))


def service(harness: FleetHarness) -> EvaluationOutcomeService:
    state = harness.container.state
    root = harness.state_root / "artifacts"
    return EvaluationOutcomeService(
        SqliteEvaluationEvidence(state, LocalArtifactStore(root), root),
        state.clock,
        state.ids,
    )


def attempt_id(harness: FleetHarness) -> str:
    with sqlite3.connect(harness.container.state.database_path) as connection:
        return str(
            connection.execute(
                "SELECT attempt_id FROM evaluation_reservations ORDER BY repetition LIMIT 1"
            ).fetchone()[0]
        )


def dump(harness: FleetHarness) -> tuple[str, ...]:
    with sqlite3.connect(harness.container.state.database_path) as connection:
        return tuple(connection.iterdump())


class FailedCoS(FakeRuntimeAdapter):
    def __init__(
        self, code: ErrorCode = ErrorCode.PROVIDER_FAILED, *, unknown: bool = False
    ) -> None:
        super().__init__()
        self.code, self.unknown = code, unknown

    async def invoke(
        self, request: AgentInvocation, services: RuntimeInvocationServices
    ) -> AgentInvocationResult:
        assert services is not None and services.accounting is not None
        if self.unknown:
            reservation = services.accounting.reserve_request(1, requested_tokens=64)
            services.accounting.record_unknown(reservation)
        raise FleetError(self.code, "Fixed test failure.", "Inspect the retained attempt.")


async def failed(
    harness: FleetHarness, code: ErrorCode = ErrorCode.PROVIDER_FAILED, *, unknown: bool = False
) -> tuple[Any, Any]:
    fixture = execution_fixture(harness)
    harness.container.workflow.runtimes = RuntimeRegistry(
        {"fake": FailedCoS(code, unknown=unknown)}
    )
    with pytest.raises(FleetError) as caught:
        await fixture.execute()
    return fixture, harness.container.state.get_run(str(caught.value.details["run_id"]))


async def test_public_cos_before_task_failure_observed_without_terminal_recording(
    harness: FleetHarness,
) -> None:
    fixture, run = await failed(harness)
    assert run.task_id is None and run.status is RunStatus.FAILED
    observer = service(harness)
    before = dump(harness)
    observation = observer.inspect_attempt(fixture.manifest.campaign_id, attempt_id(harness))
    assert observation.state == "failed", observation
    assert observation.terminal_result == "provider_failure"
    assert observation.root_run_id == run.run_id and observation.task_id is None
    assert observation.verified_artifact_count == 0
    assert (
        service(harness).inspect_attempt(fixture.manifest.campaign_id, attempt_id(harness))
        == observation
    )
    assert dump(harness) == before
    for _ in range(2):
        with pytest.raises(FleetError) as caught:
            observer.record_final_outcome(
                fixture.manifest.campaign_id, attempt_id(harness), observation.sha256
            )
        assert caught.value.code is ErrorCode.STATE_UNAVAILABLE
    assert dump(harness) == before
    assert (await fixture.execute()).run_id == run.run_id
    assert fixture.store.for_run(run.run_id) is not None
    with pytest.raises(FleetError):
        await harness.container.workflow.resume(run.run_id)
    with sqlite3.connect(harness.container.state.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM evaluation_outcomes").fetchone()[0] == 0


@pytest.mark.parametrize(
    "code,result",
    [
        (ErrorCode.RUNTIME_TIMEOUT, "timeout"),
        (ErrorCode.RUNTIME_BUDGET_EXCEEDED, "budget_exhausted"),
        (ErrorCode.SANDBOX_UNAVAILABLE, "environment_failure"),
        (ErrorCode.RUNTIME_OUTPUT_INVALID, "inconclusive"),
    ],
)
async def test_terminal_result_comes_from_retained_error(
    harness: FleetHarness, code: ErrorCode, result: str
) -> None:
    fixture, _ = await failed(harness, code)
    observer = service(harness)
    observation = observer.inspect_attempt(fixture.manifest.campaign_id, attempt_id(harness))
    assert observation.terminal_result == result, observation
    with pytest.raises(FleetError) as caught:
        observer.record_final_outcome(
            fixture.manifest.campaign_id, attempt_id(harness), observation.sha256
        )
    assert caught.value.code is ErrorCode.STATE_UNAVAILABLE


async def test_unknown_is_not_zero_or_automatic_replay(harness: FleetHarness) -> None:
    fixture, run = await failed(harness, unknown=True)
    observer = service(harness)
    observation = observer.inspect_attempt(fixture.manifest.campaign_id, attempt_id(harness))
    assert observation.state == "dispatch_unknown", observation
    assert observation.usage[0].unknown_requests == 1
    assert observation.usage[0].model_requests == 1
    with pytest.raises(FleetError) as caught:
        observer.record_final_outcome(
            fixture.manifest.campaign_id, attempt_id(harness), observation.sha256
        )
    assert caught.value.code is ErrorCode.STATE_UNAVAILABLE
    assert (await fixture.execute()).run_id == run.run_id


async def test_fake_candidate_waits_for_apply_and_does_not_finalize(harness: FleetHarness) -> None:
    fixture = execution_fixture(harness)
    run = await fixture.execute()
    observer = service(harness)
    observation = observer.inspect_attempt(fixture.manifest.campaign_id, attempt_id(harness))
    assert observation.state == "awaiting_apply", observation
    assert not observation.product_verified_complete and observation.terminal_result is None
    assert observation.durable_outstanding_leases == 0
    assert observation.physical_cleanup == "not_checked"
    assert observation.root_run_id == run.run_id
    with pytest.raises(FleetError):
        observer.record_final_outcome(
            fixture.manifest.campaign_id, attempt_id(harness), observation.sha256
        )


@pytest.mark.parametrize(
    "damage", ["missing", "bytes", "kind", "foreign_run", "oversized", "symlink"]
)
async def test_physical_or_metadata_corruption_cannot_become_outcome(
    harness: FleetHarness, damage: str
) -> None:
    fixture = execution_fixture(harness)
    run = await fixture.execute()
    assert run.config_snapshot_artifact_id is not None
    artifact = harness.container.state.get_artifact(run.config_snapshot_artifact_id)
    path = harness.state_root / "artifacts" / artifact.content_ref
    if damage == "missing":
        path.rename(path.with_suffix(".retained"))
    elif damage == "bytes":
        path.write_bytes(b"corrupt fixture")
    elif damage == "symlink":
        original = path.with_suffix(".retained")
        path.rename(original)
        path.symlink_to(original)
    else:
        with sqlite3.connect(harness.container.state.database_path) as connection:
            payload = artifact.model_dump(mode="json")
            if damage == "kind":
                payload["kind"] = "patch"
            elif damage == "foreign_run":
                payload["run_id"] = "run_" + "f" * 32
            else:
                payload["metadata"] = {"huge": "x" * 2_100_000}
            connection.execute(
                "UPDATE artifacts SET data_json=? WHERE artifact_id=?",
                (json.dumps(payload), artifact.artifact_id),
            )
    observer = service(harness)
    observation = observer.inspect_attempt(fixture.manifest.campaign_id, attempt_id(harness))
    assert observation.state == "corrupt" and observation.terminal_result is None
    with pytest.raises(FleetError):
        observer.record_final_outcome(
            fixture.manifest.campaign_id, attempt_id(harness), observation.sha256
        )


async def test_stale_observation_does_not_record(harness: FleetHarness) -> None:
    fixture, run = await failed(harness)
    observer = service(harness)
    observation = observer.inspect_attempt(fixture.manifest.campaign_id, attempt_id(harness))
    harness.container.workflow._emit(run, "evaluation.test.changed", {})
    with pytest.raises(FleetError):
        observer.record_final_outcome(
            fixture.manifest.campaign_id, attempt_id(harness), observation.sha256
        )
    with sqlite3.connect(harness.container.state.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM evaluation_outcomes").fetchone()[0] == 0


class ScenarioFake(FakeRuntimeAdapter):
    def __init__(
        self, scenario: FakeScenario = FakeScenario.SUCCESS, *, block: bool = False
    ) -> None:
        self.scenario, self.block = scenario, block
        self.entered = asyncio.Event()

    async def invoke(
        self, request: AgentInvocation, services: RuntimeInvocationServices
    ) -> AgentInvocationResult:
        self.entered.set()
        if self.block:
            await asyncio.Event().wait()
        return await super().invoke(
            request.model_copy(
                update={
                    "input": {**request.input, "fake_scenario": self.scenario.value},
                }
            ),
            services,
        )


async def test_readonly_and_parallel_observations_do_not_duplicate_root_usage(
    harness: FleetHarness,
) -> None:
    fixture = execution_fixture(harness, parallel=True)
    harness.container.workflow.runtimes = RuntimeRegistry(
        {"fake": ScenarioFake(FakeScenario.PARALLEL_ENGINEERS)}
    )
    run = await fixture.execute()
    observation = service(harness).inspect_attempt(
        fixture.manifest.campaign_id, attempt_id(harness)
    )
    assert observation.state == "awaiting_apply", observation
    budget = harness.container.budgets.snapshot(run.run_id)
    assert len(observation.usage) == 1
    assert observation.usage[0].tool_calls == budget.tool_calls
    assert observation.usage[0].model_requests == budget.model_requests
    assert observation.durable_outstanding_leases == 0


async def test_readonly_completion_awaits_oracle(harness: FleetHarness) -> None:
    fixture = execution_fixture(harness, read_only=True)
    harness.container.workflow.runtimes = RuntimeRegistry(
        {"fake": ScenarioFake(FakeScenario.DIRECT)}
    )
    await fixture.execute()
    observer = service(harness)
    observation = observer.inspect_attempt(fixture.manifest.campaign_id, attempt_id(harness))
    assert observation.state == "awaiting_oracle", observation
    assert observation.apply_status == "not_applicable"
    assert not {"patch", "apply", "post_apply"}.intersection(
        ref.category for ref in observation.artifacts
    )
    with pytest.raises(FleetError):
        observer.record_final_outcome(
            fixture.manifest.campaign_id, attempt_id(harness), observation.sha256
        )


async def test_active_read_is_repeatable_and_cancellation_is_final(harness: FleetHarness) -> None:
    fixture = execution_fixture(harness)
    runtime = ScenarioFake(block=True)
    harness.container.workflow.runtimes = RuntimeRegistry({"fake": runtime})
    running = asyncio.create_task(fixture.execute())
    await asyncio.wait_for(runtime.entered.wait(), timeout=10)
    observer = service(harness)
    try:
        first = observer.inspect_attempt(fixture.manifest.campaign_id, attempt_id(harness))
        assert first.state == "active", first
        assert first.usage[0].active_milliseconds is None
        assert observer.inspect_attempt(fixture.manifest.campaign_id, attempt_id(harness)) == first
        with pytest.raises(FleetError):
            observer.record_final_outcome(
                fixture.manifest.campaign_id, attempt_id(harness), first.sha256
            )
    finally:
        running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await running
    ended = observer.inspect_attempt(fixture.manifest.campaign_id, attempt_id(harness))
    assert ended.state == "cancelled", ended
    assert ended.terminal_result == "cancelled" and ended.task_id is None
    with pytest.raises(FleetError) as caught:
        observer.record_final_outcome(
            fixture.manifest.campaign_id, attempt_id(harness), ended.sha256
        )
    assert caught.value.code is ErrorCode.STATE_UNAVAILABLE


async def test_inspection_never_uses_generic_connection_or_changes_state_files(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture, _ = await failed(harness)
    observer = service(harness)
    selected = attempt_id(harness)

    def files() -> dict[str, str]:
        return {
            str(path.relative_to(harness.state_root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in harness.state_root.rglob("*")
            if path.is_file()
        }

    def forbidden(*args: object, **kwargs: object) -> Any:
        raise AssertionError("generic state connection is forbidden")

    monkeypatch.setattr(harness.container.state, "_connect", forbidden)
    before = files()
    first = observer.inspect_attempt(fixture.manifest.campaign_id, selected)
    assert first.state == "failed", first
    assert files() == before


async def test_missing_database_and_symlink_have_no_creation(
    harness: FleetHarness, tmp_path: Path
) -> None:
    state = harness.container.state
    original = state.database_path
    state.database_path = tmp_path / "absent" / "state.db"
    try:
        observation = service(harness).inspect_attempt(
            "campaign_" + "a" * 32, "attempt_" + "b" * 32
        )
        assert observation.state == "corrupt"
        assert not state.database_path.parent.exists()
        link = tmp_path / "state-link.db"
        link.symlink_to(original)
        state.database_path = link
        assert (
            service(harness).inspect_attempt("campaign_" + "a" * 32, "attempt_" + "b" * 32).state
            == "corrupt"
        )
    finally:
        state.database_path = original


async def test_disabled_recording_never_enters_the_old_database_cas_path(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture, _ = await failed(harness)
    observer = service(harness)
    selected = attempt_id(harness)
    before = observer.inspect_attempt(fixture.manifest.campaign_id, selected)

    def race(observation: Any, record: Any) -> Any:
        raise AssertionError("Disabled terminal recording must not enter the old CAS path")

    monkeypatch.setattr(observer.evidence, "record_terminal", race)
    with pytest.raises(FleetError):
        observer.record_final_outcome(fixture.manifest.campaign_id, selected, before.sha256)
    with sqlite3.connect(harness.container.state.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM evaluation_outcomes").fetchone()[0] == 0


async def test_concurrent_finalizations_are_contained_without_receipts(
    harness: FleetHarness,
) -> None:
    fixture, _ = await failed(harness)
    selected = attempt_id(harness)
    observer = service(harness)
    before = observer.inspect_attempt(fixture.manifest.campaign_id, selected)
    outcomes = await asyncio.gather(
        *(
            asyncio.to_thread(
                service(harness).record_final_outcome,
                fixture.manifest.campaign_id,
                selected,
                before.sha256,
            )
            for _ in range(2)
        ),
        return_exceptions=True,
    )
    assert all(
        isinstance(value, FleetError) and value.code is ErrorCode.STATE_UNAVAILABLE
        for value in outcomes
    )
    with sqlite3.connect(harness.container.state.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM evaluation_outcomes").fetchone()[0] == 0


class FailedEngineer(FailedCoS):
    async def invoke(
        self, request: AgentInvocation, services: RuntimeInvocationServices
    ) -> AgentInvocationResult:
        if request.role == "cos":
            return await FakeRuntimeAdapter().invoke(request, services)
        return await super().invoke(request, services)


async def test_post_task_failure_validates_physical_evidence_and_safe_read_failure(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = execution_fixture(harness)
    harness.container.workflow.runtimes = RuntimeRegistry({"fake": FailedEngineer()})
    with pytest.raises(FleetError) as caught:
        await fixture.execute()
    run = harness.container.state.get_run(str(caught.value.details["run_id"]))
    assert run.task_id is not None
    observer = service(harness)
    selected = attempt_id(harness)
    observation = observer.inspect_attempt(fixture.manifest.campaign_id, selected)
    assert observation.state == "failed", observation
    assert observation.verified_artifact_count > 0
    evidence = observer.evidence
    assert isinstance(evidence, SqliteEvaluationEvidence)

    def fault(*args: object, **kwargs: object) -> bytes:
        raise OSError("SYNTHETIC_SECRET must not escape")

    monkeypatch.setattr(evidence.artifacts, "get", fault)
    # The original pathname ArtifactStore is never consulted, even when faulting.
    repeated = observer.inspect_attempt(fixture.manifest.campaign_id, selected)
    assert repeated == observation and "SYNTHETIC_SECRET" not in repeated.model_dump_json()
    with pytest.raises(FleetError) as rejected:
        observer.record_final_outcome(fixture.manifest.campaign_id, selected, observation.sha256)
    assert rejected.value.__context__ is None and rejected.value.__cause__ is None


async def test_registered_secret_in_persisted_event_is_not_returned(harness: FleetHarness) -> None:
    fixture, run = await failed(harness)
    secret = "SYNTHETIC_REGISTERED_SECRET_FOR_OBSERVER"
    harness.container.redactor.register_secrets([secret])
    with sqlite3.connect(harness.container.state.database_path) as connection:
        raw = connection.execute(
            "SELECT data_json FROM run_events WHERE run_id=? AND event_type='run.failed'",
            (run.run_id,),
        ).fetchone()[0]
        event = json.loads(raw)
        event["payload"]["message"] = secret
        connection.execute(
            "UPDATE run_events SET data_json=? WHERE run_id=? AND event_type='run.failed'",
            (json.dumps(event), run.run_id),
        )
    observation = service(harness).inspect_attempt(
        fixture.manifest.campaign_id, attempt_id(harness)
    )
    assert observation.state == "corrupt" and secret not in observation.model_dump_json()


async def test_disabled_recording_never_enters_the_old_database_swap_path(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture, _ = await failed(harness)
    observer = service(harness)
    selected = attempt_id(harness)
    observation = observer.inspect_attempt(fixture.manifest.campaign_id, selected)

    def swap(observed: Any, record: Any) -> Any:
        raise AssertionError("Disabled terminal recording must not access a database pathname")

    monkeypatch.setattr(observer.evidence, "record_terminal", swap)
    with pytest.raises(FleetError):
        observer.record_final_outcome(fixture.manifest.campaign_id, selected, observation.sha256)


async def test_preflight_and_caller_supplied_success_remain_rejected(harness: FleetHarness) -> None:
    from typing import cast

    from evaluation_ledger_fixtures import preflight_record

    from agent_fleet.adapters.persistence.evaluations import SqliteEvaluationStore
    from agent_fleet.domain.outcomes import OutcomeRecord

    fixture, _ = await failed(harness)
    observer = service(harness)
    selected = attempt_id(harness)
    observation = observer.inspect_attempt(fixture.manifest.campaign_id, selected)
    ledger = SqliteEvaluationStore(harness.container.state)
    snapshot = ledger.snapshot(fixture.manifest.campaign_id)
    reservation = next(item for item in snapshot.reservations if item.attempt_id == selected)
    with pytest.raises(FleetError):
        ledger.record_preflight_outcome(preflight_record(fixture.manifest, reservation))
    with pytest.raises(FleetError) as caught:
        observer.record_final_outcome(fixture.manifest.campaign_id, selected, observation.sha256)
    assert caught.value.code is ErrorCode.STATE_UNAVAILABLE
    with pytest.raises(FleetError) as direct:
        observer.evidence.record_terminal(
            observation, cast(OutcomeRecord, {"external_result": "functional_failure"})
        )
    assert direct.value.code is ErrorCode.STATE_UNAVAILABLE
