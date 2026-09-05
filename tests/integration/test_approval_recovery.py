from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from conftest import FleetHarness

from agent_fleet.bootstrap import build_container
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.ids import IdPrefix
from agent_fleet.domain.models import (
    FakeScenario,
    LeaseKind,
    LeaseStatus,
    ResourceLease,
    Run,
    RunStatus,
    SandboxCleanupResult,
    SandboxExecutionHandle,
    SandboxHandle,
)
from agent_fleet.domain.security import canonical_json_hash


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
    assert rejected.evidence_bundle_artifact_id is not None
    assert rejected.verified_complete is False
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
    assert harness.container.state.outstanding_leases(paused.run_id) == []
    assert not list((harness.state_root / "workspaces" / paused.run_id).glob("*"))


@pytest.mark.integration
@pytest.mark.asyncio
async def test_concurrent_cancel_joins_full_cleanup_despite_repeated_task_cancellation(
    harness: FleetHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paused = await harness.start(FakeScenario.APPROVAL)
    state = harness.container.state
    resources = harness.container.recovery.resources
    provider = harness.container.sandbox
    sandbox = resources.engineer_sandbox(paused.run_id)
    execution_id = state.ids.new(IdPrefix.EXECUTION)
    execution_labels = {
        "agent-fleet.execution": execution_id,
        "agent-fleet.run": paused.run_id,
        "agent-fleet.sandbox": sandbox.sandbox_id,
    }
    execution_handle = SandboxExecutionHandle(
        execution_id=execution_id,
        sandbox_id=sandbox.sandbox_id,
        run_id=paused.run_id,
        provider="fake",
        native_resource_id=f"fake:{execution_id}",
        labels=execution_labels,
        labels_sha256=canonical_json_hash(execution_labels),
    )
    now = state.clock.now()
    execution_lease = ResourceLease(
        lease_id=state.ids.new(IdPrefix.LEASE),
        run_id=paused.run_id,
        kind=LeaseKind.EXECUTION,
        resource_id=execution_id,
        status=LeaseStatus.ACTIVE,
        created_at=now,
        updated_at=now,
        metadata={
            "provider": "fake",
            "sandbox_handle": sandbox.model_dump(mode="json"),
            "execution_handle": execution_handle.model_dump(mode="json"),
        },
    )
    provider.executions.add(execution_id)
    state.save_lease(execution_lease)
    leases = list(state.outstanding_leases(paused.run_id))
    sandbox_lease = next(lease for lease in leases if lease.kind is LeaseKind.SANDBOX)
    workspace_lease = next(lease for lease in leases if lease.kind is LeaseKind.WORKTREE)
    assert workspace_lease.path is not None
    workspace_path = Path(workspace_lease.path)
    original_terminate = provider.terminate
    cleanup_entered = asyncio.Event()
    cleanup_release = asyncio.Event()
    cleanup_finished = asyncio.Event()
    terminate_calls = 0

    async def blocked_terminate(handle: SandboxHandle) -> SandboxCleanupResult:
        nonlocal terminate_calls
        terminate_calls += 1
        assert execution_id not in provider.executions
        assert state.get_lease(execution_lease.lease_id).status is LeaseStatus.RELEASED
        cleanup_entered.set()
        await cleanup_release.wait()
        result = await original_terminate(handle)
        cleanup_finished.set()
        return result

    monkeypatch.setattr(provider, "terminate", blocked_terminate)
    first = asyncio.create_task(harness.container.cancellation.cancel(paused.run_id))
    second: asyncio.Task[Run] | None = None
    cancelled: Run | None = None
    try:
        await asyncio.wait_for(cleanup_entered.wait(), timeout=5)
        second = asyncio.create_task(harness.container.cancellation.cancel(paused.run_id))
        await asyncio.sleep(0)
        assert not second.done()

        first.cancel()
        await asyncio.sleep(0)
        first.cancel()
        await asyncio.sleep(0)

        assert not first.done()
        assert not second.done()
        assert terminate_calls == 1
        assert cleanup_finished.is_set() is False
        assert state.get_lease(sandbox_lease.lease_id).status is LeaseStatus.RELEASING
        assert state.get_lease(workspace_lease.lease_id).status is LeaseStatus.ACTIVE
        assert await asyncio.to_thread(workspace_path.exists)

        cleanup_release.set()
        with pytest.raises(asyncio.CancelledError):
            await first
        cancelled = await second
    finally:
        cleanup_release.set()
        pending = [task for task in (first, second) if task is not None and not task.done()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    assert cancelled is not None
    assert cancelled.status is RunStatus.CANCELLED
    assert cleanup_finished.is_set() is True
    assert terminate_calls == 1
    assert state.outstanding_leases(paused.run_id) == []
    assert {
        state.get_lease(execution_lease.lease_id).status,
        state.get_lease(sandbox_lease.lease_id).status,
        state.get_lease(workspace_lease.lease_id).status,
    } == {LeaseStatus.RELEASED}
    assert execution_id not in provider.executions
    assert sandbox_lease.resource_id not in provider.handles
    assert await asyncio.to_thread(workspace_path.exists) is False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_recovery_finishes_full_cleanup_before_propagating_repeated_cancellation(
    harness: FleetHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paused = await harness.start(FakeScenario.APPROVAL)
    state = harness.container.state
    provider = harness.container.sandbox
    interrupted = paused.model_copy(
        update={
            "status": RunStatus.RUNNING,
            "pending_approval_id": None,
            "updated_at": state.clock.now(),
        }
    )
    state.save_run(interrupted, "run.resumed", {"reason": "simulated process loss"})
    leases = list(state.outstanding_leases(paused.run_id))
    sandbox_lease = next(lease for lease in leases if lease.kind is LeaseKind.SANDBOX)
    workspace_lease = next(lease for lease in leases if lease.kind is LeaseKind.WORKTREE)
    assert workspace_lease.path is not None
    workspace_path = Path(workspace_lease.path)
    original_terminate = provider.terminate
    cleanup_entered = asyncio.Event()
    cleanup_release = asyncio.Event()
    cleanup_finished = asyncio.Event()
    terminate_calls = 0

    async def blocked_terminate(handle: SandboxHandle) -> SandboxCleanupResult:
        nonlocal terminate_calls
        terminate_calls += 1
        cleanup_entered.set()
        await cleanup_release.wait()
        result = await original_terminate(handle)
        cleanup_finished.set()
        return result

    monkeypatch.setattr(provider, "terminate", blocked_terminate)
    recovery = asyncio.create_task(harness.container.recovery.recover_run(paused.run_id))
    joined_recovery: asyncio.Task[Run] | None = None
    recovered: Run | None = None
    try:
        await asyncio.wait_for(cleanup_entered.wait(), timeout=5)
        joined_recovery = asyncio.create_task(harness.container.recovery.recover_run(paused.run_id))
        await asyncio.sleep(0)
        assert not joined_recovery.done()
        recovery.cancel()
        await asyncio.sleep(0)
        recovery.cancel()
        await asyncio.sleep(0)

        assert not recovery.done()
        assert not joined_recovery.done()
        assert cleanup_finished.is_set() is False
        assert terminate_calls == 1
        assert state.get_lease(sandbox_lease.lease_id).status is LeaseStatus.RELEASING
        assert state.get_lease(workspace_lease.lease_id).status is LeaseStatus.ACTIVE
        assert await asyncio.to_thread(workspace_path.exists)

        cleanup_release.set()
        with pytest.raises(asyncio.CancelledError):
            await recovery
        recovered = await joined_recovery
    finally:
        cleanup_release.set()
        pending = [
            task for task in (recovery, joined_recovery) if task is not None and not task.done()
        ]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    assert recovered is not None
    assert recovered.status is RunStatus.FAILED
    assert cleanup_finished.is_set() is True
    assert terminate_calls == 1
    assert state.get_run(paused.run_id).status is RunStatus.FAILED
    assert state.outstanding_leases(paused.run_id) == []
    assert {
        state.get_lease(sandbox_lease.lease_id).status,
        state.get_lease(workspace_lease.lease_id).status,
    } == {LeaseStatus.RECOVERED}
    assert sandbox_lease.resource_id not in provider.handles
    assert await asyncio.to_thread(workspace_path.exists) is False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_direct_lease_cleanup_finishes_before_propagating_repeated_cancellation(
    harness: FleetHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paused = await harness.start(FakeScenario.APPROVAL)
    state = harness.container.state
    resources = harness.container.recovery.resources
    provider = harness.container.sandbox
    leases = list(state.outstanding_leases(paused.run_id))
    sandbox_lease = next(lease for lease in leases if lease.kind is LeaseKind.SANDBOX)
    workspace_lease = next(lease for lease in leases if lease.kind is LeaseKind.WORKTREE)
    original_terminate = provider.terminate
    cleanup_entered = asyncio.Event()
    cleanup_release = asyncio.Event()

    async def blocked_terminate(handle: SandboxHandle) -> SandboxCleanupResult:
        cleanup_entered.set()
        await cleanup_release.wait()
        return await original_terminate(handle)

    monkeypatch.setattr(provider, "terminate", blocked_terminate)
    cleanup = asyncio.create_task(resources.cleanup_lease(paused, sandbox_lease))
    try:
        await asyncio.wait_for(cleanup_entered.wait(), timeout=5)
        with pytest.raises(FleetError) as conflict:
            await resources.cleanup_lease(
                paused,
                sandbox_lease,
                status=LeaseStatus.RECOVERED,
            )
        assert conflict.value.code is ErrorCode.RECOVERY_REQUIRED
        cleanup.cancel()
        await asyncio.sleep(0)
        cleanup.cancel()
        await asyncio.sleep(0)

        assert not cleanup.done()
        assert state.get_lease(sandbox_lease.lease_id).status is LeaseStatus.RELEASING
        cleanup_release.set()
        with pytest.raises(asyncio.CancelledError):
            await cleanup
    finally:
        cleanup_release.set()
        if not cleanup.done():
            cleanup.cancel()
            await asyncio.gather(cleanup, return_exceptions=True)

    assert state.get_lease(sandbox_lease.lease_id).status is LeaseStatus.RELEASED
    assert state.get_lease(workspace_lease.lease_id).status is LeaseStatus.ACTIVE
    assert sandbox_lease.resource_id not in provider.handles
    await resources.cleanup_run(paused)
    assert state.outstanding_leases(paused.run_id) == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_conflicting_public_cleanup_modes_fail_closed_without_duplicate_cleanup(
    harness: FleetHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paused = await harness.start(FakeScenario.APPROVAL)
    state = harness.container.state
    provider = harness.container.sandbox
    sandbox_lease = next(
        lease
        for lease in state.outstanding_leases(paused.run_id)
        if lease.kind is LeaseKind.SANDBOX
    )
    original_terminate = provider.terminate
    cleanup_entered = asyncio.Event()
    cleanup_release = asyncio.Event()
    terminate_calls = 0

    async def blocked_terminate(handle: SandboxHandle) -> SandboxCleanupResult:
        nonlocal terminate_calls
        terminate_calls += 1
        cleanup_entered.set()
        await cleanup_release.wait()
        return await original_terminate(handle)

    monkeypatch.setattr(provider, "terminate", blocked_terminate)
    cancellation = asyncio.create_task(harness.container.cancellation.cancel(paused.run_id))
    cancelled: Run | None = None
    try:
        await asyncio.wait_for(cleanup_entered.wait(), timeout=5)
        with pytest.raises(FleetError) as conflict:
            await harness.container.recovery.recover_run(paused.run_id)

        assert conflict.value.code is ErrorCode.RECOVERY_REQUIRED
        assert conflict.value.details == {
            "run_id": paused.run_id,
            "active_status": LeaseStatus.RELEASED.value,
            "requested_status": LeaseStatus.RECOVERED.value,
        }
        assert not cancellation.done()
        assert terminate_calls == 1
        assert state.get_lease(sandbox_lease.lease_id).status is LeaseStatus.RELEASING
        cleanup_release.set()
        cancelled = await cancellation
    finally:
        cleanup_release.set()
        if not cancellation.done():
            cancellation.cancel()
        await asyncio.gather(cancellation, return_exceptions=True)

    assert cancelled is not None
    assert cancelled.status is RunStatus.CANCELLED
    assert terminate_calls == 1
    assert state.outstanding_leases(paused.run_id) == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_completed_cleanup_registry_window_rejects_conflicting_modes(
    harness: FleetHarness,
) -> None:
    paused = await harness.start(FakeScenario.APPROVAL)
    state = harness.container.state
    resources = harness.container.recovery.resources
    sandbox_lease = next(
        lease
        for lease in state.outstanding_leases(paused.run_id)
        if lease.kind is LeaseKind.SANDBOX
    )

    completed_lease_cleanup = asyncio.create_task(asyncio.sleep(0))
    await completed_lease_cleanup
    resources._lease_cleanup_tasks[sandbox_lease.lease_id] = (
        LeaseStatus.RELEASED,
        completed_lease_cleanup,
    )
    try:
        with pytest.raises(FleetError) as lease_conflict:
            await resources.cleanup_lease(
                paused,
                sandbox_lease,
                status=LeaseStatus.RECOVERED,
            )
    finally:
        resources._lease_cleanup_tasks.pop(sandbox_lease.lease_id, None)

    assert lease_conflict.value.code is ErrorCode.RECOVERY_REQUIRED
    assert lease_conflict.value.details == {
        "lease_id": sandbox_lease.lease_id,
        "active_status": LeaseStatus.RELEASED.value,
        "requested_status": LeaseStatus.RECOVERED.value,
    }

    completed_run_cleanup = asyncio.create_task(asyncio.sleep(0))
    await completed_run_cleanup
    resources._run_cleanup_tasks[paused.run_id] = (
        LeaseStatus.RELEASED,
        completed_run_cleanup,
    )
    try:
        with pytest.raises(FleetError) as run_conflict:
            await resources.cleanup_run(paused, recovered=True)
    finally:
        resources._run_cleanup_tasks.pop(paused.run_id, None)

    assert run_conflict.value.code is ErrorCode.RECOVERY_REQUIRED
    assert run_conflict.value.details == {
        "run_id": paused.run_id,
        "active_status": LeaseStatus.RELEASED.value,
        "requested_status": LeaseStatus.RECOVERED.value,
    }
    await resources.cleanup_run(paused)
    assert state.outstanding_leases(paused.run_id) == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cleanup_failure_wins_over_caller_cancellation(
    harness: FleetHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paused = await harness.start(FakeScenario.APPROVAL)
    state = harness.container.state
    provider = harness.container.sandbox
    leases = list(state.outstanding_leases(paused.run_id))
    sandbox_lease = next(lease for lease in leases if lease.kind is LeaseKind.SANDBOX)
    workspace_lease = next(lease for lease in leases if lease.kind is LeaseKind.WORKTREE)
    cleanup_entered = asyncio.Event()
    cleanup_release = asyncio.Event()
    original_terminate = provider.terminate

    async def failed_terminate(_handle: SandboxHandle) -> SandboxCleanupResult:
        cleanup_entered.set()
        await cleanup_release.wait()
        raise FleetError(
            ErrorCode.SANDBOX_CLEANUP_FAILED,
            "Injected sandbox cleanup failure.",
            "Keep the parent workspace intact.",
        )

    monkeypatch.setattr(provider, "terminate", failed_terminate)
    cancellation = asyncio.create_task(harness.container.cancellation.cancel(paused.run_id))
    try:
        await asyncio.wait_for(cleanup_entered.wait(), timeout=5)
        cancellation.cancel()
        cleanup_release.set()
        with pytest.raises(FleetError) as captured:
            await cancellation
    finally:
        cleanup_release.set()
        if not cancellation.done():
            cancellation.cancel()
            await asyncio.gather(cancellation, return_exceptions=True)

    assert captured.value.code is ErrorCode.SANDBOX_CLEANUP_FAILED
    assert state.get_lease(sandbox_lease.lease_id).status is LeaseStatus.FAILED
    assert state.get_lease(workspace_lease.lease_id).status is LeaseStatus.ACTIVE
    monkeypatch.setattr(provider, "terminate", original_terminate)
    retried = await harness.container.cancellation.cancel(paused.run_id)
    assert retried.status is RunStatus.CANCELLED
    assert state.outstanding_leases(paused.run_id) == []


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
    recovered = await reconstructed.recovery.recover_run(paused.run_id)
    assert recovered.status is RunStatus.FAILED
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
async def test_exact_recovery_fails_interrupted_run_even_without_a_lease(
    harness: FleetHarness,
) -> None:
    paused = await harness.start(FakeScenario.APPROVAL)
    await harness.container.recovery.resources.cleanup_run(paused)
    assert harness.container.state.outstanding_leases(paused.run_id) == []
    interrupted = paused.model_copy(
        update={
            "status": RunStatus.RUNNING,
            "pending_approval_id": None,
            "updated_at": harness.container.state.clock.now(),
        }
    )
    harness.container.state.save_run(
        interrupted, "run.resumed", {"reason": "simulated lease-free process loss"}
    )

    recovered = await build_container(harness.state_root).recovery.recover_run(paused.run_id)

    assert recovered.status is RunStatus.FAILED
    assert recovered.run_id == paused.run_id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_exact_recovery_refuses_durable_approval_pause(
    harness: FleetHarness,
) -> None:
    paused = await harness.start(FakeScenario.APPROVAL)
    before = list(harness.container.state.outstanding_leases(paused.run_id))

    with pytest.raises(FleetError) as captured:
        await build_container(harness.state_root).recovery.recover_run(paused.run_id)

    assert captured.value.code is ErrorCode.RECOVERY_REQUIRED
    assert list(harness.container.state.outstanding_leases(paused.run_id)) == before
    assert harness.container.state.get_run(paused.run_id).status is RunStatus.PAUSED_FOR_APPROVAL


@pytest.mark.integration
@pytest.mark.asyncio
async def test_exact_recovery_does_not_touch_another_runs_leases(
    harness: FleetHarness,
) -> None:
    interrupted = await harness.start(FakeScenario.APPROVAL)
    unrelated = await harness.start(FakeScenario.APPROVAL)
    unrelated_before = list(harness.container.state.outstanding_leases(unrelated.run_id))
    assert unrelated_before
    resumed = interrupted.model_copy(
        update={
            "status": RunStatus.RUNNING,
            "pending_approval_id": None,
            "updated_at": harness.container.state.clock.now(),
        }
    )
    harness.container.state.save_run(
        resumed, "run.resumed", {"reason": "simulated scoped process loss"}
    )

    recovered = await build_container(harness.state_root).recovery.recover_run(interrupted.run_id)

    assert recovered.status is RunStatus.FAILED
    assert harness.container.state.outstanding_leases(interrupted.run_id) == []
    assert list(harness.container.state.outstanding_leases(unrelated.run_id)) == unrelated_before
    assert harness.container.state.get_run(unrelated.run_id).status is RunStatus.PAUSED_FOR_APPROVAL


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
