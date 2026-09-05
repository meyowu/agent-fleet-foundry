from __future__ import annotations

import asyncio
from collections.abc import Callable

import pytest
from conftest import FleetHarness

from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import (
    ArtifactKind,
    ExecRequest,
    LeaseKind,
    LeaseStatus,
    SandboxExecutionHandle,
    SandboxExecutionRecoveryRequest,
    SandboxHandle,
)
from agent_fleet.domain.security import canonical_json_hash


@pytest.mark.asyncio
async def test_commit_success_return_failure_does_not_replay_released_execution(
    harness: FleetHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = harness.container.state
    original_finalize = state.finalize_lease
    injected = False

    def commit_then_fail(
        lease_id: str,
        status: str,
        metadata: dict[str, object],
    ) -> object:
        nonlocal injected
        finalized = original_finalize(lease_id, status, metadata)
        if not injected and status == LeaseStatus.RELEASED.value:
            injected = True
            raise FleetError(
                ErrorCode.STATE_UNAVAILABLE,
                "Injected lost acknowledgement after commit.",
                "Do not replay the command.",
            )
        return finalized

    monkeypatch.setattr(state, "finalize_lease", commit_then_fail)

    with pytest.raises(FleetError) as captured:
        await harness.start()

    assert captured.value.code is ErrorCode.STATE_UNAVAILABLE
    run_id = captured.value.details["run_id"]
    assert isinstance(run_id, str)
    execution_leases = [
        lease for lease in state.list_leases(run_id) if lease.kind is LeaseKind.EXECUTION
    ]
    assert len(execution_leases) == 1
    assert execution_leases[0].status is LeaseStatus.RELEASED
    terminal_result = execution_leases[0].metadata["terminal_result"]
    assert isinstance(terminal_result, dict)
    assert terminal_result["exit_code"] == 0
    assert len(harness.container.sandbox.requests) == 1

    resumed = await harness.container.workflow.resume(run_id)

    assert resumed.status.value == "failed"
    assert len(harness.container.sandbox.requests) == 1


@pytest.mark.asyncio
async def test_artifact_failure_after_execution_finalization_keeps_terminal_lease(
    harness: FleetHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts = harness.container.artifacts
    original_create = artifacts.create_text

    def fail_first_execution_artifact(*args: object, **kwargs: object) -> object:
        if kwargs.get("kind") is ArtifactKind.SANDBOX_INSPECTION:
            raise FleetError(
                ErrorCode.ARTIFACT_INTEGRITY_FAILED,
                "Injected artifact persistence failure.",
                "Do not replay the already terminal command.",
            )
        return original_create(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(artifacts, "create_text", fail_first_execution_artifact)

    with pytest.raises(FleetError) as captured:
        await harness.start()

    assert captured.value.code is ErrorCode.ARTIFACT_INTEGRITY_FAILED
    run_id = captured.value.details["run_id"]
    assert isinstance(run_id, str)
    execution_leases = [
        lease
        for lease in harness.container.state.list_leases(run_id)
        if lease.kind is LeaseKind.EXECUTION
    ]
    assert len(execution_leases) == 1
    assert execution_leases[0].status is LeaseStatus.RELEASED
    cleanup_result = execution_leases[0].metadata["cleanup_result"]
    assert isinstance(cleanup_result, dict)
    assert cleanup_result["complete"] is True
    assert len(harness.container.sandbox.requests) == 1

    await harness.container.workflow.resume(run_id)

    assert len(harness.container.sandbox.requests) == 1


@pytest.mark.asyncio
async def test_failed_active_execution_is_cleaned_and_finalized_with_recovery_metadata(
    harness: FleetHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = harness.container.sandbox
    calls = 0

    async def fail_after_resource_creation(
        handle: SandboxHandle,
        request: ExecRequest,
        *,
        on_creation_dispatched: Callable[[], None] | None = None,
        on_resource_created: Callable[[SandboxExecutionHandle], None] | None = None,
    ) -> object:
        nonlocal calls
        calls += 1
        assert request.execution_id is not None
        labels = {
            "agent-fleet.execution": request.execution_id,
            "agent-fleet.run": handle.run_id,
            "agent-fleet.sandbox": handle.sandbox_id,
        }
        resource = SandboxExecutionHandle(
            execution_id=request.execution_id,
            sandbox_id=handle.sandbox_id,
            run_id=handle.run_id,
            provider="fake",
            native_resource_id=f"fake:{request.execution_id}",
            labels=labels,
            labels_sha256=canonical_json_hash(labels),
        )
        if on_creation_dispatched is not None:
            on_creation_dispatched()
        provider.executions.add(request.execution_id)
        if on_resource_created is not None:
            on_resource_created(resource)
        raise FleetError(
            ErrorCode.SANDBOX_EXECUTION_FAILED,
            "Injected failure after exact resource activation.",
            "Recover the execution without replay.",
        )

    monkeypatch.setattr(provider, "exec", fail_after_resource_creation)

    with pytest.raises(FleetError) as captured:
        await harness.start()

    assert captured.value.code is ErrorCode.SANDBOX_EXECUTION_FAILED
    run_id = captured.value.details["run_id"]
    assert isinstance(run_id, str)
    execution_leases = [
        lease
        for lease in harness.container.state.list_leases(run_id)
        if lease.kind is LeaseKind.EXECUTION
    ]
    assert len(execution_leases) == 1
    lease = execution_leases[0]
    assert lease.status is LeaseStatus.RECOVERED
    recovery = lease.metadata["recovery"]
    assert isinstance(recovery, dict)
    assert recovery["original_error_code"] == ErrorCode.SANDBOX_EXECUTION_FAILED.value
    cleanup_result = recovery["cleanup_result"]
    assert isinstance(cleanup_result, dict)
    assert cleanup_result["complete"] is True
    assert calls == 1
    assert provider.executions == set()


@pytest.mark.asyncio
async def test_creation_callback_rejects_resource_outside_full_lease_binding(
    harness: FleetHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = harness.container.sandbox
    monkeypatch.setattr(
        "agent_fleet.application.gateway.execution_lease_binding_is_valid",
        lambda lease, execution, sandbox: False,
    )

    with pytest.raises(FleetError) as captured:
        await harness.start()

    assert captured.value.code is ErrorCode.SANDBOX_CREATION_FAILED
    run_id = captured.value.details["run_id"]
    assert isinstance(run_id, str)
    execution_leases = [
        lease
        for lease in harness.container.state.list_leases(run_id)
        if lease.kind is LeaseKind.EXECUTION
    ]
    assert len(execution_leases) == 1
    assert execution_leases[0].status is LeaseStatus.RECOVERED
    assert provider.executions == set()


@pytest.mark.asyncio
@pytest.mark.parametrize("activate_resource", [True, False])
async def test_repeated_cancellation_waits_for_durable_execution_recovery(
    harness: FleetHarness,
    monkeypatch: pytest.MonkeyPatch,
    activate_resource: bool,
) -> None:
    provider = harness.container.sandbox
    execution_entered = asyncio.Event()
    recovery_entered = asyncio.Event()
    recovery_release = asyncio.Event()
    recovery_finished = asyncio.Event()
    never_release_execution = asyncio.Event()
    original_cleanup = provider.cleanup_execution
    original_reconcile = provider.reconcile_execution
    cleanup_calls = 0
    reconcile_calls = 0

    async def block_after_resource_creation(
        handle: SandboxHandle,
        request: ExecRequest,
        *,
        on_creation_dispatched: Callable[[], None] | None = None,
        on_resource_created: Callable[[SandboxExecutionHandle], None] | None = None,
    ) -> object:
        assert request.execution_id is not None
        labels = {
            "agent-fleet.execution": request.execution_id,
            "agent-fleet.run": handle.run_id,
            "agent-fleet.sandbox": handle.sandbox_id,
        }
        resource = SandboxExecutionHandle(
            execution_id=request.execution_id,
            sandbox_id=handle.sandbox_id,
            run_id=handle.run_id,
            provider="fake",
            native_resource_id=f"fake:{request.execution_id}",
            labels=labels,
            labels_sha256=canonical_json_hash(labels),
        )
        if on_creation_dispatched is not None:
            on_creation_dispatched()
        provider.executions.add(request.execution_id)
        if activate_resource and on_resource_created is not None:
            on_resource_created(resource)
        execution_entered.set()
        await never_release_execution.wait()
        raise AssertionError("cancelled execution unexpectedly resumed")

    async def blocked_cleanup(handle: SandboxExecutionHandle) -> object:
        nonlocal cleanup_calls
        cleanup_calls += 1
        recovery_entered.set()
        await recovery_release.wait()
        result = await original_cleanup(handle)
        recovery_finished.set()
        return result

    async def blocked_reconcile(
        sandbox: SandboxHandle,
        request: SandboxExecutionRecoveryRequest,
    ) -> object:
        nonlocal reconcile_calls
        reconcile_calls += 1
        recovery_entered.set()
        await recovery_release.wait()
        result = await original_reconcile(sandbox, request)
        recovery_finished.set()
        return result

    monkeypatch.setattr(provider, "exec", block_after_resource_creation)
    monkeypatch.setattr(provider, "cleanup_execution", blocked_cleanup)
    monkeypatch.setattr(provider, "reconcile_execution", blocked_reconcile)
    execution = asyncio.create_task(harness.start())
    await execution_entered.wait()

    execution.cancel()
    await recovery_entered.wait()
    execution.cancel()
    await asyncio.sleep(0)
    assert not execution.done()
    with harness.container.state._connect() as connection:
        run_row = connection.execute("SELECT run_id FROM runs").fetchone()
    assert run_row is not None
    run_id = str(run_row["run_id"])
    execution_leases = [
        lease
        for lease in harness.container.state.list_leases(run_id)
        if lease.kind is LeaseKind.EXECUTION
    ]
    assert len(execution_leases) == 1
    expected_status = LeaseStatus.ACTIVE if activate_resource else LeaseStatus.CREATING
    assert execution_leases[0].status is expected_status
    assert recovery_finished.is_set() is False

    recovery_release.set()
    with pytest.raises(asyncio.CancelledError):
        await execution

    assert recovery_finished.is_set() is True
    assert cleanup_calls == int(activate_resource)
    assert reconcile_calls == int(not activate_resource)
    recovered = harness.container.state.get_lease(execution_leases[0].lease_id)
    assert recovered.status is LeaseStatus.RECOVERED
    recovery = recovered.metadata["recovery"]
    assert isinstance(recovery, dict)
    cleanup_result = recovery["cleanup_result"]
    assert isinstance(cleanup_result, dict)
    assert cleanup_result["complete"] is True
    assert cleanup_result["reconciled"] is True
    assert provider.executions == set()
