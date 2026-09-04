"""Fleet-owned resource lease creation, cleanup, cancellation, and recovery."""

from __future__ import annotations

from pathlib import Path

from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.ids import IdPrefix
from agent_fleet.domain.models import (
    LeaseKind,
    LeaseStatus,
    ResourceLease,
    Run,
    RunStatus,
    SandboxHandle,
    Workspace,
    WorkspaceKind,
)
from agent_fleet.domain.workflow import is_terminal
from agent_fleet.ports.clock import Clock
from agent_fleet.ports.id_generator import IdGenerator
from agent_fleet.ports.repository import RepositoryPort
from agent_fleet.ports.sandbox import SandboxProvider
from agent_fleet.ports.state_store import StateStore


class ResourceService:
    def __init__(
        self,
        state: StateStore,
        repository: RepositoryPort,
        sandbox: SandboxProvider,
        clock: Clock,
        ids: IdGenerator,
    ) -> None:
        self.state = state
        self.repository = repository
        self.sandbox = sandbox
        self.clock = clock
        self.ids = ids

    def lease_workspace(self, workspace: Workspace) -> ResourceLease:
        now = self.clock.now()
        lease = ResourceLease(
            lease_id=self.ids.new(IdPrefix.LEASE),
            run_id=workspace.run_id,
            kind=LeaseKind.WORKTREE,
            resource_id=workspace.workspace_id,
            path=workspace.path,
            status=LeaseStatus.ACTIVE,
            created_at=now,
            updated_at=now,
            metadata={
                "workspace_kind": workspace.kind.value,
                "base_revision": workspace.base_revision,
            },
        )
        self.state.save_lease(lease)
        return lease

    def lease_sandbox(self, handle: SandboxHandle) -> ResourceLease:
        now = self.clock.now()
        lease = ResourceLease(
            lease_id=self.ids.new(IdPrefix.LEASE),
            run_id=handle.run_id,
            kind=LeaseKind.SANDBOX,
            resource_id=handle.sandbox_id,
            status=LeaseStatus.ACTIVE,
            created_at=now,
            updated_at=now,
            metadata={"workspace_host_path": handle.workspace_host_path},
        )
        self.state.save_lease(lease)
        return lease

    def candidate_workspace(self, run_id: str) -> Workspace:
        for lease in self.state.active_leases(run_id):
            if (
                lease.kind is LeaseKind.WORKTREE
                and lease.metadata.get("workspace_kind") == WorkspaceKind.CANDIDATE.value
                and lease.path is not None
            ):
                return _workspace_from_lease(lease)
        raise FleetError(
            ErrorCode.RECOVERY_REQUIRED,
            f"Active candidate workspace is missing for run {run_id}.",
            "Inspect resource leases and start a new run if the workspace was lost.",
        )

    def engineer_sandbox(self, run_id: str) -> SandboxHandle:
        for lease in self.state.active_leases(run_id):
            if lease.kind is LeaseKind.SANDBOX:
                return SandboxHandle(
                    sandbox_id=lease.resource_id,
                    run_id=run_id,
                    workspace_host_path=str(lease.metadata["workspace_host_path"]),
                )
        raise FleetError(
            ErrorCode.RECOVERY_REQUIRED,
            f"Active fake sandbox lease is missing for run {run_id}.",
            "Inspect resource leases and resume from a valid checkpoint.",
        )

    async def cleanup_run(self, run: Run, *, recovered: bool = False) -> None:
        target_status = LeaseStatus.RECOVERED if recovered else LeaseStatus.RELEASED
        leases = list(self.state.active_leases(run.run_id))
        for lease in reversed(leases):
            await self.cleanup_lease(run, lease, status=target_status)

    async def cleanup_lease(
        self,
        run: Run,
        lease: ResourceLease,
        *,
        status: LeaseStatus = LeaseStatus.RELEASED,
    ) -> None:
        project = self.state.get_project(run.project_id)
        if lease.kind is LeaseKind.SANDBOX:
            handle = SandboxHandle(
                sandbox_id=lease.resource_id,
                run_id=run.run_id,
                workspace_host_path=str(lease.metadata["workspace_host_path"]),
            )
            await self.sandbox.terminate(handle)
        else:
            workspace = _workspace_from_lease(lease)
            self.repository.cleanup_workspace(Path(project.canonical_root), workspace)
        self.state.update_lease_status(lease.lease_id, status.value)


class RecoveryService:
    def __init__(self, state: StateStore, resources: ResourceService) -> None:
        self.state = state
        self.resources = resources

    async def recover_orphaned(self) -> list[str]:
        recovered: list[str] = []
        seen: set[str] = set()
        for lease in self.state.active_leases():
            if lease.run_id in seen:
                continue
            run = self.state.get_run(lease.run_id)
            if run.status in {RunStatus.RUNNING, RunStatus.APPLYING}:
                run = run.model_copy(
                    update={"status": RunStatus.FAILED, "updated_at": self.resources.clock.now()}
                )
                self.state.save_run(
                    run,
                    "run.failed",
                    {"reason": "orphaned_resources_recovered"},
                )
            if is_terminal(run.status):
                await self.resources.cleanup_run(run, recovered=True)
                recovered.append(run.run_id)
                seen.add(run.run_id)
        return recovered


class CancellationService:
    def __init__(self, state: StateStore, resources: ResourceService, clock: Clock) -> None:
        self.state = state
        self.resources = resources
        self.clock = clock

    async def cancel(self, run_id: str) -> Run:
        run = self.state.get_run(run_id)
        if is_terminal(run.status):
            return run
        if run.status is not RunStatus.CANCELLED:
            run = run.model_copy(
                update={"status": RunStatus.CANCELLED, "updated_at": self.clock.now()}
            )
            self.state.save_run(
                run, "run.cancelled", {"stage": run.stage.value if run.stage else None}
            )
        await self.resources.cleanup_run(run)
        return self.state.get_run(run_id)


def _workspace_from_lease(lease: ResourceLease) -> Workspace:
    if lease.path is None:
        raise FleetError(
            ErrorCode.RECOVERY_REQUIRED,
            f"Workspace lease {lease.lease_id} has no persisted path.",
            "Discard the invalid lease only after inspecting its audit events.",
        )
    return Workspace(
        workspace_id=lease.resource_id,
        run_id=lease.run_id,
        kind=WorkspaceKind(str(lease.metadata["workspace_kind"])),
        path=lease.path,
        base_revision=str(lease.metadata["base_revision"]),
    )
