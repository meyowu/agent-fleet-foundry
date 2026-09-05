from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from conftest import FleetHarness

from agent_fleet.application.resources import execution_lease_binding_is_valid
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.ids import IdPrefix
from agent_fleet.domain.models import (
    LeaseKind,
    LeaseStatus,
    ResourceLease,
    Run,
    SandboxCapabilities,
    SandboxExecutionHandle,
    SandboxHandle,
    SandboxSecurityLevel,
    SandboxSpec,
    WorkspaceKind,
)
from agent_fleet.domain.security import canonical_json_hash


@pytest.mark.asyncio
async def test_execution_cleanup_failure_preserves_parent_sandbox_and_worktree(
    harness: FleetHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = harness.container.state
    repository = harness.container.repository
    resources = harness.container.recovery.resources
    project = state.get_project_by_root(str(harness.repository_root.resolve()))
    assert project is not None
    info = repository.inspect(harness.repository_root)
    now = datetime.now(UTC)
    run = Run(
        run_id=state.ids.new(IdPrefix.RUN),
        project_id=project.project_id,
        correlation_id=state.ids.new(IdPrefix.CORRELATION),
        goal="cleanup dependency ordering",
        base_revision=info.head_revision,
        target_status_fingerprint=info.status_fingerprint,
        created_at=now,
        updated_at=now,
    )
    state.create_run(run)
    workspace = repository.create_workspace(
        harness.repository_root,
        run.run_id,
        run.base_revision,
        WorkspaceKind.CANDIDATE,
    )
    workspace_lease = resources.lease_workspace(workspace)
    sandbox = await resources.create_sandbox(
        run.run_id,
        SandboxSpec(
            workspace_host_path=workspace.path,
            project_id=project.project_id,
        ),
    )
    sandbox_lease = next(
        item for item in state.outstanding_leases(run.run_id) if item.kind is LeaseKind.SANDBOX
    )
    execution_id = state.ids.new(IdPrefix.EXECUTION)
    labels = {
        "agent-fleet.execution": execution_id,
        "agent-fleet.run": run.run_id,
        "agent-fleet.sandbox": sandbox.sandbox_id,
    }
    execution_handle = SandboxExecutionHandle(
        execution_id=execution_id,
        sandbox_id=sandbox.sandbox_id,
        run_id=run.run_id,
        provider="fake",
        native_resource_id=f"fake:{execution_id}",
        labels=labels,
        labels_sha256=canonical_json_hash(labels),
    )
    execution_lease = ResourceLease(
        lease_id=state.ids.new(IdPrefix.LEASE),
        run_id=run.run_id,
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
    state.save_lease(execution_lease)
    cleanup_workspace_called = False

    async def fail_execution_cleanup(_handle: SandboxExecutionHandle) -> object:
        raise FleetError(
            ErrorCode.SANDBOX_CLEANUP_FAILED,
            "Injected execution cleanup failure.",
            "Keep parent resources intact.",
        )

    def record_workspace_cleanup(_root: Path, _workspace: object) -> None:
        nonlocal cleanup_workspace_called
        cleanup_workspace_called = True

    monkeypatch.setattr(harness.container.sandbox, "cleanup_execution", fail_execution_cleanup)
    monkeypatch.setattr(repository, "cleanup_workspace", record_workspace_cleanup)

    with pytest.raises(FleetError) as captured:
        await resources.cleanup_run(run)

    assert captured.value.code is ErrorCode.SANDBOX_CLEANUP_FAILED
    assert cleanup_workspace_called is False
    assert sandbox.sandbox_id in harness.container.sandbox.handles
    assert state.get_lease(execution_lease.lease_id).status is LeaseStatus.FAILED
    assert state.get_lease(sandbox_lease.lease_id).status is LeaseStatus.ACTIVE
    assert state.get_lease(workspace_lease.lease_id).status is LeaseStatus.ACTIVE


def test_docker_execution_lease_rejects_optional_control_plane_label_drift() -> None:
    now = datetime.now(UTC)
    run_id = "run_" + "1" * 32
    sandbox_id = "sandbox_" + "2" * 32
    execution_id = "exec_" + "3" * 32
    project_id = "prj_" + "4" * 32
    intent_id = "intent_" + "5" * 32
    task_id = "task_" + "6" * 32
    agent_id = "agent_" + "7" * 32
    daemon_id = "8" * 64
    installation_id = "9" * 32
    capabilities = SandboxCapabilities(
        provider="docker",
        security_level=SandboxSecurityLevel.ISOLATED,
        isolation_enforced=True,
        executes_code=True,
        supported_network_modes=("none",),
        supports_resource_limits=True,
        supports_recovery=True,
        supports_non_root=True,
        supports_read_only_root=True,
        supports_no_new_privileges=True,
        supports_capability_drop=True,
    )
    sandbox = SandboxHandle(
        sandbox_id=sandbox_id,
        run_id=run_id,
        project_id=project_id,
        workspace_host_path="/fleet/workspace",
        provider="docker",
        capabilities=capabilities,
        configuration_hash="a" * 64,
        image_identity="sha256:" + "b" * 64,
        daemon_identity=daemon_id,
        recovery_scope_id=installation_id,
    )
    labels = {
        "agent-fleet.agent": "agent_" + "f" * 32,
        "agent-fleet.daemon": daemon_id,
        "agent-fleet.execution": execution_id,
        "agent-fleet.installation": installation_id,
        "agent-fleet.intent": intent_id,
        "agent-fleet.managed": "true",
        "agent-fleet.project": project_id,
        "agent-fleet.run": run_id,
        "agent-fleet.sandbox": sandbox_id,
        "agent-fleet.stage": "verifying",
        "agent-fleet.task": task_id,
    }
    execution = SandboxExecutionHandle(
        execution_id=execution_id,
        sandbox_id=sandbox_id,
        run_id=run_id,
        provider="docker",
        native_resource_id="c" * 64,
        labels=labels,
        labels_sha256=canonical_json_hash(labels),
    )
    lease = ResourceLease(
        lease_id="lease_" + "d" * 32,
        run_id=run_id,
        kind=LeaseKind.EXECUTION,
        resource_id=execution_id,
        status=LeaseStatus.ACTIVE,
        created_at=now,
        updated_at=now,
        metadata={
            "provider": "docker",
            "intent_id": intent_id,
            "project_id": project_id,
            "task_id": task_id,
            "agent_instance_id": agent_id,
            "stage": "verifying",
        },
    )

    assert execution_lease_binding_is_valid(lease, execution, sandbox) is False
