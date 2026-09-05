"""Fleet-owned resource lease creation, cleanup, cancellation, and recovery."""

from __future__ import annotations

import asyncio
from pathlib import Path

from agent_fleet.application.sandboxes import SandboxRegistry
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.ids import IdPrefix
from agent_fleet.domain.models import (
    LeaseKind,
    LeaseStatus,
    ResourceLease,
    Run,
    RunStatus,
    SandboxCleanupResult,
    SandboxExecutionHandle,
    SandboxExecutionRecoveryRequest,
    SandboxHandle,
    SandboxSpec,
    Workspace,
    WorkspaceKind,
)
from agent_fleet.domain.security import canonical_json_hash
from agent_fleet.domain.workflow import is_terminal
from agent_fleet.ports.clock import Clock
from agent_fleet.ports.id_generator import IdGenerator
from agent_fleet.ports.repository import RepositoryPort
from agent_fleet.ports.state_store import StateStore


class ResourceService:
    def __init__(
        self,
        state: StateStore,
        repository: RepositoryPort,
        sandboxes: SandboxRegistry,
        clock: Clock,
        ids: IdGenerator,
    ) -> None:
        self.state = state
        self.repository = repository
        self.sandboxes = sandboxes
        self.clock = clock
        self.ids = ids
        self._run_cleanup_tasks: dict[str, tuple[LeaseStatus, asyncio.Task[None]]] = {}
        self._lease_cleanup_tasks: dict[str, tuple[LeaseStatus, asyncio.Task[None]]] = {}

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
            metadata=_sandbox_lease_metadata(handle),
        )
        self.state.save_lease(lease)
        return lease

    async def create_sandbox(self, run_id: str, spec: SandboxSpec) -> SandboxHandle:
        provider = self.sandboxes.require(spec.configuration, spec.requirements)
        sandbox_id = self.ids.new(IdPrefix.SANDBOX)
        configuration_hash = canonical_json_hash(spec.configuration.model_dump(mode="json"))
        expected = SandboxHandle(
            sandbox_id=sandbox_id,
            run_id=run_id,
            project_id=spec.project_id,
            workspace_host_path=spec.workspace_host_path,
            provider=spec.configuration.provider,
            capabilities=provider.capabilities,
            configuration_hash=configuration_hash,
            image_identity=spec.image_identity,
            daemon_identity=spec.daemon_identity,
            recovery_scope_id=provider.recovery_scope_id,
        )
        now = self.clock.now()
        lease = ResourceLease(
            lease_id=self.ids.new(IdPrefix.LEASE),
            run_id=run_id,
            kind=LeaseKind.SANDBOX,
            resource_id=sandbox_id,
            status=LeaseStatus.CREATING,
            created_at=now,
            updated_at=now,
            metadata=_sandbox_lease_metadata(expected),
        )
        self.state.save_lease(lease)
        try:
            handle = await provider.create(run_id, spec, sandbox_id=sandbox_id)
            if handle != expected:
                raise FleetError(
                    ErrorCode.SANDBOX_CREATION_FAILED,
                    "The sandbox provider returned an identity that did not match the lease.",
                    "Inspect the provider configuration and recover the recorded lease.",
                    details={"sandbox": spec.configuration.provider},
                )
            inspection = await provider.inspect(handle)
            if (
                not inspection.ready
                or inspection.provider != handle.provider
                or inspection.configuration_hash != configuration_hash
                or inspection.capabilities != handle.capabilities
                or inspection.image_identity != handle.image_identity
                or inspection.daemon_identity != handle.daemon_identity
                or inspection.effective_network_mode != spec.configuration.network_mode
                or inspection.missing_requirements(spec.requirements)
            ):
                raise FleetError(
                    ErrorCode.SANDBOX_INSPECTION_FAILED,
                    "The sandbox failed its effective-configuration inspection.",
                    "Inspect the sandbox provider and image configuration; "
                    "Fleet did not execute code.",
                    details={"sandbox": spec.configuration.provider},
                )
            self.state.update_lease_status(lease.lease_id, LeaseStatus.ACTIVE.value)
            return handle
        except BaseException as creation_error:
            cleanup_task = asyncio.create_task(provider.terminate(expected))
            try:
                result = await _await_sandbox_cleanup_task(cleanup_task)
                if not result.complete:
                    raise FleetError(
                        ErrorCode.SANDBOX_CLEANUP_FAILED,
                        "Sandbox creation failed and cleanup could not prove absence.",
                        "Run Fleet recovery before continuing.",
                    )
            except BaseException as cleanup_error:
                self.state.update_lease_status(lease.lease_id, LeaseStatus.FAILED.value)
                if (
                    isinstance(cleanup_error, FleetError)
                    and cleanup_error.code is ErrorCode.SANDBOX_CLEANUP_FAILED
                ):
                    raise
                raise FleetError(
                    ErrorCode.SANDBOX_CLEANUP_FAILED,
                    "Sandbox creation failed and cleanup could not prove absence.",
                    "Run Fleet recovery before continuing.",
                ) from cleanup_error
            else:
                self.state.update_lease_status(lease.lease_id, LeaseStatus.RECOVERED.value)
            raise creation_error

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
                    **_sandbox_handle_from_lease(lease).model_dump(),
                )
        raise FleetError(
            ErrorCode.RECOVERY_REQUIRED,
            f"Active engineer sandbox lease is missing for run {run_id}.",
            "Inspect resource leases and resume from a valid checkpoint.",
        )

    async def cleanup_run(self, run: Run, *, recovered: bool = False) -> None:
        target_status = LeaseStatus.RECOVERED if recovered else LeaseStatus.RELEASED
        active_cleanup = self._run_cleanup_tasks.get(run.run_id)
        if active_cleanup is None:
            cleanup_task = asyncio.create_task(
                self._cleanup_run_ordered(run, target_status=target_status)
            )
            self._run_cleanup_tasks[run.run_id] = (target_status, cleanup_task)
        else:
            active_status, cleanup_task = active_cleanup
            if active_status is not target_status:
                raise FleetError(
                    ErrorCode.RECOVERY_REQUIRED,
                    "A conflicting resource cleanup mode is already active for this run.",
                    "Wait for the active cancellation or recovery cleanup to finish, then retry.",
                    details={
                        "run_id": run.run_id,
                        "active_status": active_status.value,
                        "requested_status": target_status.value,
                    },
                )
        try:
            await _await_resource_cleanup_task(cleanup_task)
        finally:
            current = self._run_cleanup_tasks.get(run.run_id)
            if cleanup_task.done() and current is not None and current[1] is cleanup_task:
                self._run_cleanup_tasks.pop(run.run_id, None)

    async def _cleanup_run_ordered(
        self,
        run: Run,
        *,
        target_status: LeaseStatus,
    ) -> None:
        leases = list(self.state.outstanding_leases(run.run_id))
        for kind in (LeaseKind.EXECUTION, LeaseKind.SANDBOX, LeaseKind.WORKTREE):
            failures: list[BaseException] = []
            for lease in (item for item in leases if item.kind is kind):
                try:
                    await self._join_lease_cleanup(run, lease, status=target_status)
                except BaseException as error:
                    failures.append(error)
            if failures:
                # A surviving command container may still hold the workspace mount. Never
                # destroy a parent sandbox or worktree until every dependent child resource
                # in the preceding tier has been proven absent.
                raise failures[0]

    async def cleanup_lease(
        self,
        run: Run,
        lease: ResourceLease,
        *,
        status: LeaseStatus = LeaseStatus.RELEASED,
    ) -> None:
        cleanup_task = self._lease_cleanup_task(run, lease, status=status)
        try:
            await _await_resource_cleanup_task(cleanup_task)
        finally:
            self._forget_lease_cleanup_task(lease.lease_id, cleanup_task)

    async def _join_lease_cleanup(
        self,
        run: Run,
        lease: ResourceLease,
        *,
        status: LeaseStatus,
    ) -> None:
        cleanup_task = self._lease_cleanup_task(run, lease, status=status)
        try:
            await cleanup_task
        finally:
            self._forget_lease_cleanup_task(lease.lease_id, cleanup_task)

    def _lease_cleanup_task(
        self,
        run: Run,
        lease: ResourceLease,
        *,
        status: LeaseStatus,
    ) -> asyncio.Task[None]:
        active_cleanup = self._lease_cleanup_tasks.get(lease.lease_id)
        if active_cleanup is None:
            current = self.state.get_lease(lease.lease_id)
            cleanup_task = asyncio.create_task(
                self._cleanup_lease_once(run, current, status=status)
            )
            self._lease_cleanup_tasks[lease.lease_id] = (status, cleanup_task)
        else:
            active_status, cleanup_task = active_cleanup
            if active_status is not status:
                raise FleetError(
                    ErrorCode.RECOVERY_REQUIRED,
                    "A conflicting resource cleanup mode is already active for this lease.",
                    "Wait for the active cleanup to finish, then retry the exact lease.",
                    details={
                        "lease_id": lease.lease_id,
                        "active_status": active_status.value,
                        "requested_status": status.value,
                    },
                )
        return cleanup_task

    def _forget_lease_cleanup_task(
        self,
        lease_id: str,
        cleanup_task: asyncio.Task[None],
    ) -> None:
        active_cleanup = self._lease_cleanup_tasks.get(lease_id)
        if cleanup_task.done() and active_cleanup is not None and active_cleanup[1] is cleanup_task:
            self._lease_cleanup_tasks.pop(lease_id, None)

    async def _cleanup_lease_once(
        self,
        run: Run,
        lease: ResourceLease,
        *,
        status: LeaseStatus,
    ) -> None:
        project = self.state.get_project(run.project_id)
        if lease.status in {LeaseStatus.RELEASED, LeaseStatus.RECOVERED}:
            return
        if lease.status is not LeaseStatus.RELEASING:
            self.state.update_lease_status(lease.lease_id, LeaseStatus.RELEASING.value)
        if lease.kind is LeaseKind.SANDBOX:
            handle = _sandbox_handle_from_lease(lease)
            provider = self.sandboxes.get(handle.provider)
            try:
                result = await provider.terminate(handle)
                if not result.complete:
                    raise FleetError(
                        ErrorCode.SANDBOX_CLEANUP_FAILED,
                        "Sandbox cleanup could not prove every managed resource absent.",
                        "Inspect the persisted lease before continuing.",
                    )
            except BaseException:
                self.state.update_lease_status(lease.lease_id, LeaseStatus.FAILED.value)
                raise
        elif lease.kind is LeaseKind.EXECUTION:
            raw_handle = lease.metadata.get("execution_handle")
            try:
                if isinstance(raw_handle, dict):
                    execution_handle = SandboxExecutionHandle.model_validate(raw_handle)
                    raw_sandbox = lease.metadata.get("sandbox_handle")
                    if not isinstance(raw_sandbox, dict):
                        raise FleetError(
                            ErrorCode.RECOVERY_REQUIRED,
                            f"Execution lease {lease.lease_id} has no parent sandbox identity.",
                            "Inspect the lease before attempting manual cleanup.",
                        )
                    sandbox_handle = SandboxHandle.model_validate(raw_sandbox)
                    if not execution_lease_binding_is_valid(
                        lease,
                        execution_handle,
                        sandbox_handle,
                    ):
                        raise FleetError(
                            ErrorCode.RECOVERY_REQUIRED,
                            f"Execution lease {lease.lease_id} identity binding is invalid.",
                            "Inspect the lease manually; Fleet did not delete any resource.",
                        )
                    provider = self.sandboxes.get(execution_handle.provider)
                    result = await provider.cleanup_execution(execution_handle)
                else:
                    raw_sandbox = lease.metadata.get("sandbox_handle")
                    if not isinstance(raw_sandbox, dict):
                        raise FleetError(
                            ErrorCode.RECOVERY_REQUIRED,
                            f"Execution lease {lease.lease_id} has no sandbox identity.",
                            "Inspect the lease before attempting manual cleanup.",
                        )
                    sandbox_handle = SandboxHandle.model_validate(raw_sandbox)
                    provider = self.sandboxes.get(sandbox_handle.provider)
                    result = await provider.reconcile_execution(
                        sandbox_handle,
                        execution_recovery_request_from_lease(lease, sandbox_handle),
                    )
                if not result.complete:
                    raise FleetError(
                        ErrorCode.SANDBOX_CLEANUP_FAILED,
                        "Execution cleanup could not prove the exact resource absent.",
                        "Inspect the persisted execution lease before continuing.",
                    )
            except BaseException:
                self.state.update_lease_status(lease.lease_id, LeaseStatus.FAILED.value)
                raise
        else:
            workspace = _workspace_from_lease(lease)
            try:
                self.repository.cleanup_workspace(Path(project.canonical_root), workspace)
            except BaseException:
                self.state.update_lease_status(lease.lease_id, LeaseStatus.FAILED.value)
                raise
        self.state.update_lease_status(lease.lease_id, status.value)


class RecoveryService:
    def __init__(self, state: StateStore, resources: ResourceService) -> None:
        self.state = state
        self.resources = resources

    async def recover_run(self, run_id: str) -> Run:
        """Recover one explicitly selected run after its prior owner has stopped.

        A blanket startup sweep cannot distinguish an orphan from a concurrently
        running Fleet process.  The public CLI therefore requires an operator
        confirmation and calls this exact-run primitive instead.
        """

        run = self.state.get_run(run_id)
        if run.status in {RunStatus.RUNNING, RunStatus.APPLYING}:
            run = run.model_copy(
                update={"status": RunStatus.FAILED, "updated_at": self.resources.clock.now()}
            )
            run = self.state.save_run(
                run,
                "run.failed",
                {"reason": "operator_confirmed_owner_stopped"},
            )
        elif not is_terminal(run.status):
            raise FleetError(
                ErrorCode.RECOVERY_REQUIRED,
                f"Run {run_id} is {run.status.value}, not an interrupted execution state.",
                "Use the normal resume, cancel, review, or apply command for this run.",
                details={"run_id": run_id, "status": run.status.value},
            )

        if self.state.outstanding_leases(run_id):
            await self.resources.cleanup_run(run, recovered=True)
        return self.state.get_run(run_id)


class CancellationService:
    def __init__(self, state: StateStore, resources: ResourceService, clock: Clock) -> None:
        self.state = state
        self.resources = resources
        self.clock = clock

    async def cancel(self, run_id: str) -> Run:
        run = self.state.get_run(run_id)
        outstanding = bool(self.state.outstanding_leases(run_id))
        if is_terminal(run.status) and (run.status is not RunStatus.CANCELLED or not outstanding):
            return run
        if run.status is not RunStatus.CANCELLED:
            run = run.model_copy(
                update={"status": RunStatus.CANCELLED, "updated_at": self.clock.now()}
            )
            self.state.save_run(
                run, "run.cancelled", {"stage": run.stage.value if run.stage else None}
            )
        if outstanding:
            await self.resources.cleanup_run(run)
        return self.state.get_run(run_id)


async def _await_sandbox_cleanup_task(
    cleanup_task: asyncio.Task[SandboxCleanupResult],
) -> SandboxCleanupResult:
    """Finish bounded sandbox-creation cleanup despite repeated cancellation."""

    while not cleanup_task.done():
        try:
            await asyncio.wait({cleanup_task})
        except asyncio.CancelledError:
            continue
    return cleanup_task.result()


async def _await_resource_cleanup_task(cleanup_task: asyncio.Task[None]) -> None:
    """Finish a retained cleanup operation before propagating caller cancellation."""

    cancellation: asyncio.CancelledError | None = None
    while not cleanup_task.done():
        try:
            await asyncio.wait({cleanup_task})
        except asyncio.CancelledError as error:
            if cancellation is None:
                cancellation = error
    cleanup_task.result()
    if cancellation is not None:
        raise cancellation


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


def _sandbox_lease_metadata(handle: SandboxHandle) -> dict[str, object]:
    return {
        "schema_version": 2,
        "provider": handle.provider,
        "handle": handle.model_dump(mode="json"),
        "capabilities_hash": canonical_json_hash(handle.capabilities.model_dump(mode="json")),
    }


def execution_lease_binding_is_valid(
    lease: ResourceLease,
    execution_handle: SandboxExecutionHandle,
    sandbox_handle: SandboxHandle,
) -> bool:
    if (
        execution_handle.execution_id != lease.resource_id
        or execution_handle.run_id != lease.run_id
        or sandbox_handle.run_id != lease.run_id
        or execution_handle.sandbox_id != sandbox_handle.sandbox_id
        or execution_handle.provider != sandbox_handle.provider
        or lease.metadata.get("provider") != execution_handle.provider
    ):
        return False
    if execution_handle.provider != "docker":
        return True
    intent_id = lease.metadata.get("intent_id")
    project_id = lease.metadata.get("project_id")
    task_id = lease.metadata.get("task_id")
    agent_instance_id = lease.metadata.get("agent_instance_id")
    stage = lease.metadata.get("stage")
    if (
        not all(
            isinstance(value, str)
            for value in (intent_id, project_id, task_id, agent_instance_id, stage)
        )
        or sandbox_handle.project_id != project_id
        or lease.metadata.get("creation_dispatched") is not True
    ):
        return False
    expected_labels = {
        "agent-fleet.agent": agent_instance_id,
        "agent-fleet.daemon": sandbox_handle.daemon_identity,
        "agent-fleet.execution": execution_handle.execution_id,
        "agent-fleet.installation": sandbox_handle.recovery_scope_id,
        "agent-fleet.intent": intent_id,
        "agent-fleet.managed": "true",
        "agent-fleet.project": project_id,
        "agent-fleet.run": lease.run_id,
        "agent-fleet.sandbox": sandbox_handle.sandbox_id,
        "agent-fleet.stage": stage,
        "agent-fleet.task": task_id,
    }
    return execution_handle.labels == expected_labels


def execution_recovery_request_from_lease(
    lease: ResourceLease,
    sandbox_handle: SandboxHandle,
) -> SandboxExecutionRecoveryRequest:
    try:
        request = SandboxExecutionRecoveryRequest.model_validate(
            {
                "execution_id": lease.resource_id,
                "sandbox_id": sandbox_handle.sandbox_id,
                "run_id": lease.run_id,
                "project_id": lease.metadata.get("project_id"),
                "provider": lease.metadata.get("provider"),
                "intent_id": lease.metadata.get("intent_id"),
                "task_id": lease.metadata.get("task_id"),
                "agent_instance_id": lease.metadata.get("agent_instance_id"),
                "stage": lease.metadata.get("stage"),
                "creation_dispatched": lease.metadata.get("creation_dispatched"),
            }
        )
    except ValueError as error:
        raise FleetError(
            ErrorCode.RECOVERY_REQUIRED,
            f"Execution lease {lease.lease_id} has incomplete recovery identities.",
            "Inspect the lease manually; Fleet did not delete any resource.",
        ) from error
    if (
        lease.kind is not LeaseKind.EXECUTION
        or request.sandbox_id != sandbox_handle.sandbox_id
        or request.run_id != sandbox_handle.run_id
        or request.project_id != sandbox_handle.project_id
        or request.provider != sandbox_handle.provider
    ):
        raise FleetError(
            ErrorCode.RECOVERY_REQUIRED,
            f"Execution lease {lease.lease_id} recovery binding is invalid.",
            "Inspect the lease manually; Fleet did not delete any resource.",
        )
    return request


def _sandbox_handle_from_lease(lease: ResourceLease) -> SandboxHandle:
    raw_handle = lease.metadata.get("handle")
    if isinstance(raw_handle, dict):
        handle = SandboxHandle.model_validate(raw_handle)
        if handle.sandbox_id != lease.resource_id or handle.run_id != lease.run_id:
            raise FleetError(
                ErrorCode.RECOVERY_REQUIRED,
                f"Sandbox lease {lease.lease_id} identity does not match its handle.",
                "Inspect the lease before attempting cleanup.",
            )
        expected_hash = lease.metadata.get("capabilities_hash")
        actual_hash = canonical_json_hash(handle.capabilities.model_dump(mode="json"))
        if expected_hash != actual_hash:
            raise FleetError(
                ErrorCode.RECOVERY_REQUIRED,
                f"Sandbox lease {lease.lease_id} capability binding is invalid.",
                "Inspect the lease before attempting cleanup.",
            )
        return handle
    workspace_host_path = lease.metadata.get("workspace_host_path")
    if isinstance(workspace_host_path, str):
        return SandboxHandle(
            sandbox_id=lease.resource_id,
            run_id=lease.run_id,
            project_id=None,
            workspace_host_path=workspace_host_path,
        )
    raise FleetError(
        ErrorCode.RECOVERY_REQUIRED,
        f"Sandbox lease {lease.lease_id} has no valid persisted handle.",
        "Inspect the lease before attempting cleanup.",
    )
