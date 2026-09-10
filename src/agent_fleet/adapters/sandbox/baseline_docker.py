"""Separate baseline state around the existing Docker control primitives."""

from __future__ import annotations

import asyncio
import os
import re
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from io import FileIO
from typing import TYPE_CHECKING

from agent_fleet.domain.baseline import (
    canonical,
    freeze_snapshot,
    reconstruct_command,
    reconstruct_sandbox,
    sandbox_policy,
)
from agent_fleet.domain.baseline_resources import (
    BaselineControlInspection,
    BaselineExecRequest,
    BaselineExecResult,
    BaselineExecutionHandle,
    BaselineExecutionMetadata,
    BaselineExecutionRecoveryRequest,
    BaselineSandboxHandle,
    BaselineSandboxInspection,
    BaselineSandboxSpec,
    baseline_labels,
)
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import SandboxCleanupResult
from agent_fleet.domain.security import sha256_bytes

if TYPE_CHECKING:
    from agent_fleet.adapters.sandbox.docker import DockerSandboxProvider


@dataclass(frozen=True)
class _BaselineLimits:
    cpu_limit: float
    memory_mb: int
    pids_limit: int
    shm_mb: int
    tmpfs_mb: int


@dataclass(frozen=True)
class _BaselineSpecView:
    configuration: _BaselineLimits
    daemon_identity: str


@dataclass(frozen=True)
class BaselinePreparedView:
    """Scalar-only view consumed by shared private Docker argv/inspection code."""

    spec: _BaselineSpecView
    workspace: str
    image_identity: str
    image_environment: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class BaselineRequestView:
    execution_id: str
    executable: str
    argv: tuple[str, ...]
    cwd: str
    environment: tuple[tuple[str, str], ...]
    timeout_seconds: int
    max_output_bytes: int


@dataclass(frozen=True)
class _PreparedBaseline:
    binding: BaselineSandboxSpec
    handle: BaselineSandboxHandle
    view: BaselinePreparedView
    workspace_identity: tuple[int, int]
    shadow_identity: tuple[int, int, int, int]
    shadow_file: FileIO


def _error(code: ErrorCode = ErrorCode.SANDBOX_EXECUTION_FAILED) -> FleetError:
    return FleetError(
        code,
        "The exact read-only baseline Docker operation is unavailable.",
        "Preserve its one-shot dispatch and inspect the exact recovery scope; do not replay it.",
    )


async def _drain(task: asyncio.Task[SandboxCleanupResult]) -> SandboxCleanupResult:
    while not task.done():
        try:
            await asyncio.wait({task})
        except asyncio.CancelledError:
            continue
    return task.result()


class BaselineDockerTransport:
    def __init__(self, provider: DockerSandboxProvider) -> None:
        self.provider = provider
        self._prepared: dict[str, _PreparedBaseline] = {}
        self._spent: set[str] = set()
        self._inspections: dict[str, BaselineSandboxInspection] = {}
        self._cleanup_tasks: dict[str, tuple[str, asyncio.Task[SandboxCleanupResult]]] = {}

    async def create(self, spec: BaselineSandboxSpec, *, sandbox_id: str) -> BaselineSandboxHandle:
        from agent_fleet.adapters.sandbox.docker import (
            _path_identity,
            _reject_mount_delimiters,
            _shadow_identity,
            _validated_workspace,
        )

        p = self.provider
        binding = BaselineSandboxSpec.from_canonical(spec.canonical_bytes())
        local = reconstruct_sandbox(binding.sandbox)
        configuration_sha256 = sha256_bytes(canonical(local.configuration.model_dump(mode="json")))
        config = _BaselineLimits(
            local.configuration.cpu_limit,
            local.configuration.memory_mb,
            local.configuration.pids_limit,
            local.configuration.shm_mb,
            local.configuration.tmpfs_mb,
        )
        image = local.image_identity
        daemon_id = local.daemon_identity
        del local
        if image is None or daemon_id is None or sandbox_id in self._prepared:
            raise _error(ErrorCode.SANDBOX_CREATION_FAILED)
        p._require_worker_identity()
        installation = p._require_recovery_scope_id()
        executable = p._require_executable()
        workspace = _validated_workspace(binding.workspace.path)
        if str(workspace) != binding.workspace.path:
            raise _error(ErrorCode.SANDBOX_CREATION_FAILED)
        _reject_mount_delimiters(workspace)
        _reject_mount_delimiters(p.git_shadow_path)
        daemon = await p._require_local_linux_daemon(executable, expected_identity=daemon_id)
        resolved_image, image_environment = await p._inspect_image(
            executable, image, expected_architecture=daemon.architecture
        )
        await p._require_local_linux_daemon(executable, expected_identity=daemon_id)
        if resolved_image != image:
            raise _error(ErrorCode.SANDBOX_IMAGE_UNAVAILABLE)
        handle = BaselineSandboxHandle(
            owner=binding.owner,
            sandbox_id=sandbox_id,
            workspace_id=binding.workspace.workspace_id,
            workspace_host_path=binding.workspace.path,
            capabilities=freeze_snapshot("capabilities-v1", p.capabilities.model_dump(mode="json")),
            configuration_sha256=configuration_sha256,
            sandbox_policy_sha256=sandbox_policy(binding.sandbox).sha256,
            sandbox_spec_sha256=binding.sandbox.sha256,
            approved_source_sha256=binding.workspace.approved_source_sha256,
            materialized_source_sha256=binding.workspace.approved_source_sha256,
            image_identity=image,
            daemon_identity=daemon_id,
            recovery_scope_id=installation,
        )
        shadow = p._open_git_shadow()
        try:
            prepared = _PreparedBaseline(
                binding,
                handle,
                BaselinePreparedView(
                    _BaselineSpecView(config, daemon_id), str(workspace), image, image_environment
                ),
                _path_identity(workspace),
                _shadow_identity(os.fstat(shadow.fileno())),
                shadow,
            )
            self._paths(prepared)
            self._prepared[sandbox_id] = prepared
        except BaseException:
            shadow.close()
            raise
        return BaselineSandboxHandle.from_canonical(handle.canonical_bytes())

    def _paths(self, prepared: _PreparedBaseline) -> None:
        from agent_fleet.adapters.sandbox.docker import (
            _path_identity,
            _shadow_identity,
            _validated_workspace,
        )

        p = self.provider
        workspace = _validated_workspace(prepared.handle.workspace_host_path)
        if (
            str(workspace) != prepared.view.workspace
            or _path_identity(workspace) != prepared.workspace_identity
            or prepared.shadow_file.closed
            or _shadow_identity(os.fstat(prepared.shadow_file.fileno())) != prepared.shadow_identity
            or _shadow_identity(p.git_shadow_path.lstat()) != prepared.shadow_identity
        ):
            raise _error(ErrorCode.SANDBOX_CREATION_FAILED)
        with p._open_git_shadow() as current:
            if _shadow_identity(os.fstat(current.fileno())) != prepared.shadow_identity:
                raise _error(ErrorCode.SANDBOX_CREATION_FAILED)

    def _prepared_for(self, handle: BaselineSandboxHandle) -> _PreparedBaseline:
        handle = BaselineSandboxHandle.from_canonical(handle.canonical_bytes())
        prepared = self._prepared.get(handle.sandbox_id)
        if prepared is None or prepared.handle != handle:
            raise _error()
        self.provider._require_current_recovery_scope(handle.recovery_scope_id)
        self._paths(prepared)
        return prepared

    def _launch(
        self, prepared: _PreparedBaseline, request: BaselineExecRequest, executable: str
    ) -> tuple[BaselineRequestView, tuple[str, ...], str]:
        request = BaselineExecRequest.from_canonical(request.canonical_bytes())
        labels = baseline_labels(prepared.handle, request)
        local = reconstruct_command(request.command)
        view = BaselineRequestView(
            request.execution_id,
            local.executable,
            local.argv,
            local.logical_cwd,
            (),
            local.timeout_seconds,
            local.max_output_bytes,
        )
        del local
        argv = self.provider._container_create_argv(
            executable,
            prepared.view,
            view,
            f"agent-fleet-baseline-{request.execution_id}",
            dict(labels),
            owner_kind="baseline",
        )
        digest = sha256_bytes(
            canonical(
                {
                    "version": "baseline-readonly-v1",
                    "request": request.digest,
                    "sandbox_spec": prepared.binding.sandbox.sha256,
                    "policy": prepared.handle.sandbox_policy_sha256,
                    "approved_source": prepared.handle.approved_source_sha256,
                    "materialized_source": prepared.handle.materialized_source_sha256,
                    "workspace_inode": list(prepared.workspace_identity),
                    "shadow_inode": list(prepared.shadow_identity),
                    "argv": list(argv),
                    "image_environment": [list(item) for item in prepared.view.image_environment],
                }
            )
        )
        return view, argv, digest

    async def inspect(self, handle: BaselineSandboxHandle) -> BaselineSandboxInspection:
        self._prepared_for(handle)
        inspection = self._inspections.get(handle.sandbox_id)
        if inspection is None:
            # Logical preparation is not evidence of an actual read-only container mount.
            raise _error(ErrorCode.SANDBOX_INSPECTION_FAILED)
        return BaselineSandboxInspection.from_canonical(inspection.canonical_bytes())

    async def execute(
        self,
        handle: BaselineSandboxHandle,
        request: BaselineExecRequest,
        *,
        on_creation_dispatched: Callable[[], None],
        on_resource_created: Callable[[BaselineExecutionHandle], None],
    ) -> BaselineExecResult:
        from agent_fleet.adapters.sandbox.docker import _validated_terminal_exit_code

        p = self.provider
        prepared = self._prepared_for(handle)
        request = BaselineExecRequest.from_canonical(request.canonical_bytes())
        labels = baseline_labels(handle, request)
        if request.execution_id in self._spent:
            raise _error()
        executable = p._require_executable()
        view, argv, launch_sha256 = self._launch(prepared, request, executable)
        self._spent.add(request.execution_id)
        native: BaselineExecutionHandle | None = None
        native_callback_complete = False
        started_at = p.clock.now()
        try:
            await p._require_local_linux_daemon(
                executable, expected_identity=handle.daemon_identity
            )
            self._paths(prepared)
            if self._launch(prepared, request, executable)[2] != launch_sha256:
                raise _error()
            on_creation_dispatched()
            self._paths(prepared)
            if self._launch(prepared, request, executable)[2] != launch_sha256:
                raise _error()
            created = await p._call(argv, timeout_seconds=30, max_output_bytes=1_000_000)
            if created.returncode or created.timed_out or created.output_truncated:
                raise _error(ErrorCode.SANDBOX_CREATION_FAILED)
            native_id = created.stdout.decode("ascii", errors="strict").strip()
            if re.fullmatch(r"[0-9a-f]{64}", native_id) is None:
                raise _error(ErrorCode.SANDBOX_CREATION_FAILED)
            native = BaselineExecutionHandle(
                owner=request.owner,
                claim_id=request.claim_id,
                execution_id=request.execution_id,
                sandbox_id=handle.sandbox_id,
                native_resource_id=native_id,
                labels=labels,
                labels_sha256=sha256_bytes(canonical(dict(labels))),
            )
            await p._require_local_linux_daemon(
                executable, expected_identity=handle.daemon_identity
            )
            raw = await p._inspect_container(executable, native_id)
            p._validate_effective_container(
                raw,
                created_id=native_id,
                prepared=prepared.view,
                request=view,
                labels=dict(labels),
                owner_kind="baseline",
            )
            controls = BaselineControlInspection(
                ready=True,
                capabilities=handle.capabilities,
                configuration_sha256=handle.configuration_sha256,
                image_identity=handle.image_identity,
                daemon_identity=handle.daemon_identity,
                non_root=True,
                read_only_root=True,
                no_new_privileges=True,
                capabilities_dropped=True,
                resource_limits_enforced=True,
                exact_mounts=True,
                inspected_at=p.clock.now(),
            )
            limits = prepared.view.spec.configuration
            inspection = BaselineSandboxInspection(
                owner=handle.owner,
                sandbox_id=handle.sandbox_id,
                execution_id=request.execution_id,
                native_resource_id=native_id,
                legacy_control_inspection=freeze_snapshot(
                    "sandbox-inspection-v1", controls.model_dump(mode="json", by_alias=True)
                ),
                workspace_read_only=True,
                tmp_scratch_mb=limits.tmpfs_mb,
                cache_scratch_mb=limits.tmpfs_mb,
                shm_scratch_mb=limits.shm_mb,
                mount_inspection_sha256=sha256_bytes(
                    canonical(
                        {
                            "mounts": raw["Mounts"],
                            "tmpfs": raw["HostConfig"]["Tmpfs"],
                            "shm_size": raw["HostConfig"]["ShmSize"],
                        }
                    )
                ),
            )
            self._inspections[handle.sandbox_id] = inspection
            del raw
            await p._require_local_linux_daemon(
                executable, expected_identity=handle.daemon_identity
            )
            self._paths(prepared)
            if self._launch(prepared, request, executable)[2] != launch_sha256:
                raise _error()
            # The trusted Gateway callback revalidates source/config/policy and
            # durably records this exact native handle directly before start.
            on_resource_created(native)
            native_callback_complete = True
            self._paths(prepared)
            if self._launch(prepared, request, executable)[2] != launch_sha256:
                raise _error()
            started_at = p.clock.now()
            result = await p._call(
                (executable, "container", "start", "--attach", native_id),
                timeout_seconds=view.timeout_seconds,
                max_output_bytes=view.max_output_bytes,
            )
            if result.timed_out or result.output_truncated:
                await self._kill(native)
                exit_code = None
            else:
                await self._assert_native(native)
                state = await p._inspect_container_state(executable, native_id)
                exit_code = _validated_terminal_exit_code(state)
                if result.returncode != exit_code:
                    raise _error()
            return BaselineExecResult(
                metadata=BaselineExecutionMetadata(
                    handle=native,
                    inspection=inspection,
                    request_sha256=request.digest,
                    sandbox_spec_sha256=handle.sandbox_spec_sha256,
                    launch_sha256=launch_sha256,
                ),
                started_at=started_at,
                completed_at=p.clock.now(),
                exit_code=exit_code,
                timed_out=result.timed_out,
                cancelled=False,
                output_truncated=result.output_truncated,
                stdout=result.stdout,
                stderr=result.stderr,
            )
        except BaseException:
            if native is not None and not native_callback_complete:
                # The native identity is locally known even if its durable callback failed.
                # Retain/drain exact removal; missing durable evidence remains unknown later.
                cleanup = asyncio.create_task(self.cleanup_execution(native))
                with suppress(FleetError, OSError):
                    await _drain(cleanup)
            raise

    async def _assert_native(self, handle: BaselineExecutionHandle) -> None:
        p = self.provider
        handle = BaselineExecutionHandle.from_canonical(handle.canonical_bytes())
        labels = dict(handle.labels)
        p._require_current_recovery_scope(labels["agent-fleet.installation"])
        executable = p._require_executable()
        await p._require_labels_daemon(executable, labels)
        inspected = await p._inspect_container(executable, handle.native_resource_id)
        config = inspected.get("Config")
        if (
            inspected.get("Id") != handle.native_resource_id
            or inspected.get("Name") != f"/{handle.native_name}"
            or type(config) is not dict
            or config.get("Labels") != labels
        ):
            raise _error(ErrorCode.SANDBOX_CLEANUP_FAILED)
        await p._require_labels_daemon(executable, labels)

    async def _kill(self, handle: BaselineExecutionHandle) -> None:
        p = self.provider
        await self._assert_native(handle)
        # Shared primitive rechecks daemon/identity directly before the bounded effect.
        await p._kill_exact(
            p._require_executable(),
            handle.native_resource_id,
            dict(handle.labels),
            owner_kind="baseline",
        )

    async def _remove(self, handle: BaselineExecutionHandle) -> None:
        p = self.provider
        await self._assert_native(handle)
        await p._remove_exact(
            p._require_executable(),
            handle.native_resource_id,
            dict(handle.labels),
            force=True,
            owner_kind="baseline",
        )

    async def cleanup_execution(self, handle: BaselineExecutionHandle) -> SandboxCleanupResult:
        handle = BaselineExecutionHandle.from_canonical(handle.canonical_bytes())
        existing = self._cleanup_tasks.get(handle.execution_id)
        if existing is not None:
            if existing[0] != handle.digest:
                raise _error(ErrorCode.SANDBOX_CLEANUP_FAILED)
            return await _drain(existing[1])
        task = asyncio.create_task(self._cleanup_execution(handle))
        self._cleanup_tasks[handle.execution_id] = (handle.digest, task)
        return await _drain(task)

    async def _cleanup_execution(self, handle: BaselineExecutionHandle) -> SandboxCleanupResult:
        p = self.provider
        labels = dict(handle.labels)
        p._require_current_recovery_scope(labels["agent-fleet.installation"])
        executable = p._require_executable()
        await p._require_labels_daemon(executable, labels)
        matches = await p._list_exact(executable, labels)
        await p._require_labels_daemon(executable, labels)
        present = await p._exact_id_present(executable, handle.native_resource_id)
        await p._require_labels_daemon(executable, labels)
        if not matches and not present:
            return self._result(handle.native_resource_id, 0, complete=True)
        if matches != [handle.native_resource_id] or not present:
            raise _error(ErrorCode.SANDBOX_CLEANUP_FAILED)
        await self._remove(handle)
        return self._result(handle.native_resource_id, 1, complete=True)

    def _result(self, identity: str, count: int, *, complete: bool) -> SandboxCleanupResult:
        return SandboxCleanupResult(
            provider="docker",
            resource_id=identity,
            resources_found=count,
            resources_removed=count if complete else 0,
            reconciled=complete,
            complete=complete,
            completed_at=self.provider.clock.now(),
        )

    async def reconcile(
        self, sandbox: BaselineSandboxHandle, request: BaselineExecutionRecoveryRequest
    ) -> SandboxCleanupResult:
        request = BaselineExecutionRecoveryRequest.from_canonical(request.canonical_bytes())
        if request.sandbox != sandbox:
            raise _error(ErrorCode.SANDBOX_CLEANUP_FAILED)
        p = self.provider
        p._require_current_recovery_scope(sandbox.recovery_scope_id)
        labels = dict(request.expected_labels)
        executable = p._require_executable()
        await p._require_labels_daemon(executable, labels)
        matches = await p._list_exact(executable, labels)
        await p._require_labels_daemon(executable, labels)
        if not matches:
            return self._result(
                request.request.execution_id, 0, complete=not request.creation_dispatched
            )
        if len(matches) != 1:
            raise _error(ErrorCode.SANDBOX_CLEANUP_FAILED)
        handle = BaselineExecutionHandle(
            owner=sandbox.owner,
            claim_id=request.request.claim_id,
            execution_id=request.request.execution_id,
            sandbox_id=sandbox.sandbox_id,
            native_resource_id=matches[0],
            labels=request.expected_labels,
            labels_sha256=sha256_bytes(canonical(labels)),
        )
        return await self.cleanup_execution(handle)

    async def terminate(self, handle: BaselineSandboxHandle) -> SandboxCleanupResult:
        handle = BaselineSandboxHandle.from_canonical(handle.canonical_bytes())
        p = self.provider
        p._require_current_recovery_scope(handle.recovery_scope_id)
        executable = p._require_executable()
        await p._require_local_linux_daemon(executable, expected_identity=handle.daemon_identity)
        # Logical termination never sweeps children; an unexpected child blocks release.
        matches = await p._list_exact(
            executable,
            {
                "agent-fleet.installation": handle.recovery_scope_id,
                "agent-fleet.owner-kind": "baseline",
                "agent-fleet.baseline": handle.owner.baseline_id,
                "agent-fleet.sandbox": handle.sandbox_id,
            },
        )
        await p._require_local_linux_daemon(executable, expected_identity=handle.daemon_identity)
        if matches:
            raise _error(ErrorCode.SANDBOX_CLEANUP_FAILED)
        prepared = self._prepared.get(handle.sandbox_id)
        if prepared is not None:
            if prepared.handle != handle:
                raise _error(ErrorCode.SANDBOX_CLEANUP_FAILED)
            prepared.shadow_file.close()
            del self._prepared[handle.sandbox_id]
        self._inspections.pop(handle.sandbox_id, None)
        return self._result(handle.sandbox_id, 0, complete=True)
