from __future__ import annotations

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
