from __future__ import annotations

from pathlib import Path

import pytest
from conftest import FleetHarness

from agent_fleet.bootstrap import build_container
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import FakeScenario, RunStatus


@pytest.mark.integration
@pytest.mark.asyncio
async def test_approval_survives_reconstruction_and_side_effect_executes_once(
    harness: FleetHarness,
) -> None:
    paused = await harness.start(FakeScenario.APPROVAL)
    assert paused.status is RunStatus.PAUSED_FOR_APPROVAL
    assert paused.pending_approval_id is not None
    assert harness.container.state.active_leases(paused.run_id)

    reconstructed = build_container(harness.state_root)
    with pytest.raises(FleetError) as self_approval:
        reconstructed.approvals.approve_once(paused.pending_approval_id, actor="cos")
    assert self_approval.value.code is ErrorCode.APPROVAL_INVALID

    grant = reconstructed.approvals.approve_once(paused.pending_approval_id)
    assert grant.remaining_uses == 1
    ready = await reconstructed.workflow.resume(paused.run_id)
    assert ready.status is RunStatus.READY_FOR_REVIEW
    assert (
        reconstructed.state.count_executed_intents(ready.run_id, "fixture.record_side_effect") == 1
    )

    repeated = build_container(harness.state_root)
    unchanged = await repeated.workflow.resume(ready.run_id)
    assert unchanged.status is RunStatus.READY_FOR_REVIEW
    assert repeated.state.count_executed_intents(ready.run_id, "fixture.record_side_effect") == 1
    consumed_events = [
        event
        for event in repeated.state.list_events(ready.run_id)
        if event.event_type == "capability.consumed"
    ]
    assert len(consumed_events) == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_denial_rejects_without_executing_side_effect(harness: FleetHarness) -> None:
    paused = await harness.start(FakeScenario.APPROVAL)
    assert paused.pending_approval_id is not None
    reconstructed = build_container(harness.state_root)
    reconstructed.approvals.deny(paused.pending_approval_id, "Use no side effect")
    rejected = await reconstructed.workflow.resume(paused.run_id)
    assert rejected.status is RunStatus.REJECTED
    assert (
        reconstructed.state.count_executed_intents(paused.run_id, "fixture.record_side_effect") == 0
    )
    assert reconstructed.state.active_leases(paused.run_id) == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cancellation_cleans_paused_resources(harness: FleetHarness) -> None:
    paused = await harness.start(FakeScenario.APPROVAL)
    assert paused.status is RunStatus.PAUSED_FOR_APPROVAL
    cancelled = await harness.container.cancellation.cancel(paused.run_id)
    assert cancelled.status is RunStatus.CANCELLED
    assert harness.container.state.active_leases(paused.run_id) == []
    assert not list((harness.state_root / "workspaces" / paused.run_id).glob("*"))


@pytest.mark.integration
@pytest.mark.asyncio
async def test_recovery_fails_interrupted_run_and_cleans_orphaned_resource_leases(
    harness: FleetHarness,
) -> None:
    paused = await harness.start(FakeScenario.APPROVAL)
    assert paused.pending_approval_id is not None
    harness.container.approvals.approve_once(paused.pending_approval_id)
    interrupted = paused.model_copy(
        update={
            "status": RunStatus.RUNNING,
            "pending_approval_id": None,
            "updated_at": harness.container.state.clock.now(),
        }
    )
    harness.container.state.save_run(
        interrupted, "run.resumed", {"reason": "simulated process loss after resume"}
    )
    assert harness.container.state.active_leases(paused.run_id)

    reconstructed = build_container(harness.state_root)
    recovered = await reconstructed.recovery.recover_orphaned()
    assert recovered == [paused.run_id]
    assert reconstructed.state.get_run(paused.run_id).status is RunStatus.FAILED
    assert reconstructed.state.active_leases(paused.run_id) == []
    with reconstructed.state._connect() as connection:
        statuses = {
            row[0]
            for row in connection.execute(
                "SELECT status FROM resource_leases WHERE run_id = ?", (paused.run_id,)
            )
        }
    assert statuses == {"recovered"}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_approval_resume_from_another_state_path_fails_closed(
    harness: FleetHarness, tmp_path: Path
) -> None:
    paused = await harness.start(FakeScenario.APPROVAL)
    assert paused.pending_approval_id is not None
    other = build_container(tmp_path / "unrelated-state")
    with pytest.raises(FleetError) as captured:
        other.approvals.approve_once(paused.pending_approval_id)
    assert captured.value.code is ErrorCode.RESOURCE_NOT_FOUND
