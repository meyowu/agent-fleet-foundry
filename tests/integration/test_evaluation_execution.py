from __future__ import annotations

import asyncio
import sqlite3
from typing import Any

import pytest
from conftest import FleetHarness
from evaluation_execution_fixtures import capture_registration, execution_fixture

from agent_fleet.adapters.persistence.evaluations import SqliteEvaluationStore
from agent_fleet.adapters.runtime.fake import FakeRuntimeAdapter
from agent_fleet.application.runtime import RuntimeRegistry
from agent_fleet.bootstrap import build_container
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import (
    AgentInvocation,
    AgentInvocationResult,
    ArtifactKind,
    FakeScenario,
    RunStatus,
)
from agent_fleet.ports.runtime import RuntimeInvocationServices

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_public_reserved_execution_produces_real_workflow_patch_and_cleanup(
    harness: FleetHarness,
) -> None:
    fixture = execution_fixture(harness)
    before = harness.git("status", "--porcelain")
    run = await fixture.execute()
    assert run.status is RunStatus.READY_FOR_REVIEW
    assert run.patch_sha256 and run.patch_artifact_id and run.evidence_bundle_artifact_id
    assert "ValueError" in harness.container.artifacts.read_text(run.patch_artifact_id)
    kinds = {item.kind for item in harness.container.state.list_artifacts(run.run_id)}
    assert ArtifactKind.COMMAND_EVIDENCE in kinds
    assert not harness.container.state.outstanding_leases(run.run_id)
    assert harness.git("status", "--porcelain") == before
    record = fixture.store.for_run(run.run_id)
    assert record is not None and record.status == "settled"
    assert harness.container.budgets.snapshot(run.run_id).limits == record.binding.limits
    restarted = build_container(harness.state_root)
    replay = await restarted.evaluation_execution.execute_reserved(
        fixture.manifest.campaign_id,
        fixture.manifest.sha256,
        "repair",
        0,
        "reserved-0",
        harness.repository_root,
    )
    assert replay == run
    with sqlite3.connect(harness.container.state.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM evaluation_executions").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM evaluation_outcomes").fetchone()[0] == 0
    with pytest.raises(FleetError):
        await restarted.workflow.resume(run.run_id)


async def test_committed_claim_without_dispatch_is_never_replayed(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = execution_fixture(harness)
    seed = await capture_registration(fixture, monkeypatch)
    first = fixture.store.register(**seed)
    assert first.claim is not None
    repeated = fixture.store.register(**seed)
    assert repeated.claim is None
    run = await fixture.execute()
    assert run.status is RunStatus.CREATED
    assert harness.container.budgets.snapshot(run.run_id).agent_invocations == 0
    with pytest.raises(FleetError):
        await harness.container.workflow.resume(run.run_id)
    fixture.store.fence(run.run_id)
    with pytest.raises(FleetError):
        fixture.store.assert_claim(first.claim)
    assert (await fixture.execute()).run_id == run.run_id


@pytest.mark.parametrize(
    "target", ["source", "profile", "configuration", "image", "command", "dependencies"]
)
async def test_admission_drift_has_zero_run_or_runtime_dispatch(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch, target: str
) -> None:
    fixture = execution_fixture(harness)
    seed = await capture_registration(fixture, monkeypatch)
    if target == "source":
        source = seed["admission"].source
        entries = (source.entries[0].model_copy(update={"sha256": "f" * 64}), *source.entries[1:])
        seed["admission"] = seed["admission"].model_copy(
            update={"source": source.model_copy(update={"entries": entries})}
        )
    elif target == "profile":
        harness.container.model_profiles.set(
            "evaluation",
            configuration=seed["bindings"].roles["cos"].configuration,
            expected_revision=1,
        )
    elif target == "configuration":
        seed["admission"] = seed["admission"].model_copy(update={"configuration_sha256": "f" * 64})
    elif target == "image":
        seed["run"] = seed["run"].model_copy(
            update={"sandbox_image_identity": "sha256:" + "f" * 64}
        )
    elif target == "command":
        seed["admission"] = seed["admission"].model_copy(update={"commands": ()})
    else:
        source = seed["admission"].source
        entries = tuple(
            item.model_copy(update={"sha256": "f" * 64}) if item.path == "pyproject.toml" else item
            for item in source.entries
        )
        seed["admission"] = seed["admission"].model_copy(
            update={"source": source.model_copy(update={"entries": entries})}
        )
    with pytest.raises(FleetError) as rejected:
        fixture.store.register(**seed)
    assert rejected.value.code is ErrorCode.RECOVERY_REQUIRED
    with sqlite3.connect(harness.container.state.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM runtime_attempts").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM evaluation_reservations").fetchone()[0] == 1


async def test_observational_report_does_not_mutate_execution(harness: FleetHarness) -> None:
    fixture = execution_fixture(harness)
    await fixture.execute()

    def snapshot() -> list[str]:
        with sqlite3.connect(harness.container.state.database_path) as connection:
            return list(connection.iterdump())

    before = snapshot()
    ledger = SqliteEvaluationStore(harness.container.state)
    assert not ledger.snapshot(fixture.manifest.campaign_id).execution_authorized
    fixture.store.for_attempt(
        fixture.store.submission(
            fixture.manifest.campaign_id, fixture.manifest.sha256, "repair", 0, "reserved-0"
        )
    )
    assert snapshot() == before


class ScopedFake(FakeRuntimeAdapter):
    def __init__(
        self,
        *,
        read_only: bool = False,
        widen: bool = False,
        block: bool = False,
        parallel: bool = False,
    ) -> None:
        self.read_only, self.widen, self.block = read_only, widen, block
        self.parallel = parallel
        self.entered = asyncio.Event()

    async def invoke(
        self, request: AgentInvocation, services: RuntimeInvocationServices
    ) -> AgentInvocationResult:
        self.entered.set()
        if self.block:
            await asyncio.Event().wait()
        if self.read_only:
            request = request.model_copy(
                update={"input": {**request.input, "fake_scenario": FakeScenario.DIRECT.value}}
            )
        if self.parallel:
            request = request.model_copy(
                update={
                    "input": {
                        **request.input,
                        "fake_scenario": FakeScenario.PARALLEL_ENGINEERS.value,
                    }
                }
            )
        result = await super().invoke(request, services)
        if self.widen and request.role == "cos":
            result = result.model_copy(
                update={"output": result.output.model_copy(update={"allowed_paths": ["tests"]})}
            )
        return result


async def test_read_only_campaign_has_zero_required_commands_and_no_worker(
    harness: FleetHarness,
) -> None:
    fixture = execution_fixture(harness, read_only=True)
    harness.container.workflow.runtimes = RuntimeRegistry({"fake": ScopedFake(read_only=True)})
    run = await fixture.execute()
    assert run.status is RunStatus.COMPLETED
    assert not run.verified_complete
    assert run.task_id is not None
    task = harness.container.state.get_task(run.task_id)
    assert task.required_verification_command_ids == []
    assert task.verification_commands  # Available configuration is not automatic authority.
    budget = harness.container.budgets.snapshot(run.run_id)
    assert budget.agent_invocations == 1 and budget.tool_calls == 0
    assert not harness.container.state.outstanding_leases(run.run_id)


async def test_campaign_graph_children_share_atomic_root_owner_and_claim(
    harness: FleetHarness,
) -> None:
    fixture = execution_fixture(harness, parallel=True)
    harness.container.workflow.runtimes = RuntimeRegistry({"fake": ScopedFake(parallel=True)})
    run = await fixture.execute()
    assert run.status is RunStatus.READY_FOR_REVIEW
    graph = harness.container.graphs.get(run.run_id)
    assert graph is not None and len(graph.nodes) == 2
    budget = harness.container.budgets.snapshot(run.run_id)
    for node in graph.nodes:
        child_id = node.binding.child_run_id
        child = harness.container.budgets.snapshot(child_id)
        assert child.limits is not None
        assert child.owner_run_id == run.run_id and child.limits == budget.limits
        assert child.agent_invocations == budget.agent_invocations
        with pytest.raises(FleetError):
            harness.container.budgets.initialize_run(child_id, child.limits)
        with pytest.raises(FleetError):
            await harness.container.workflow.resume(child_id)
        assert not harness.container.state.outstanding_leases(child_id)
    with sqlite3.connect(harness.container.state.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM runtime_budget_owners").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM evaluation_executions").fetchone()[0] == 1


async def test_cos_scope_cannot_widen_the_frozen_case(harness: FleetHarness) -> None:
    fixture = execution_fixture(harness)
    harness.container.workflow.runtimes = RuntimeRegistry({"fake": ScopedFake(widen=True)})
    with pytest.raises(FleetError) as rejected:
        await fixture.execute()
    run_id = str(rejected.value.details["run_id"])
    assert harness.container.budgets.snapshot(run_id).agent_invocations == 1
    assert harness.container.budgets.snapshot(run_id).tool_calls == 0
    assert not harness.container.state.outstanding_leases(run_id)


async def test_cancelled_campaign_retains_one_claim_and_cannot_restart(
    harness: FleetHarness,
) -> None:
    fixture = execution_fixture(harness)
    runtime = ScopedFake(block=True)
    harness.container.workflow.runtimes = RuntimeRegistry({"fake": runtime})
    invocation = asyncio.create_task(fixture.execute())
    await asyncio.wait_for(runtime.entered.wait(), timeout=10)
    invocation.cancel()
    with pytest.raises(asyncio.CancelledError):
        await invocation
    run = await fixture.execute()
    assert run.status is RunStatus.CANCELLED
    assert not harness.container.state.outstanding_leases(run.run_id)
    assert harness.container.budgets.snapshot(run.run_id).agent_invocations == 1
    record = fixture.store.for_run(run.run_id)
    assert record is not None and record.status == "settled"


@pytest.mark.parametrize("surface", ["docker_null", "unsafe", "fake_sha"])
async def test_unsafe_or_false_image_identity_has_zero_dispatch(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch, surface: str
) -> None:
    fixture = execution_fixture(harness)
    seed = await capture_registration(fixture, monkeypatch)
    update: dict[str, Any] = {
        "sandbox_name": "docker" if surface == "docker_null" else "local-unsafe"
    }
    if surface == "fake_sha":
        update = {"sandbox_image_identity": "sha256:" + "a" * 64}
    seed["run"] = seed["run"].model_copy(update=update)
    with pytest.raises(FleetError):
        fixture.store.register(**seed)
    with sqlite3.connect(harness.container.state.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0
