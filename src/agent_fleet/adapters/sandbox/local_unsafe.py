"""Explicit host-process sandbox adapter with no isolation claims."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

from agent_fleet.adapters.executable_resolution import (
    resolve_trusted_executable,
    trusted_search_path,
)
from agent_fleet.adapters.sandbox.process import (
    ProcessInvocationError,
    ProcessRunner,
    ProcessTerminationError,
)
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.ids import IdPrefix
from agent_fleet.domain.models import (
    ExecRequest,
    ExecResult,
    SandboxCapabilities,
    SandboxCleanupResult,
    SandboxConfiguration,
    SandboxExecutionHandle,
    SandboxExecutionMetadata,
    SandboxExecutionRecoveryRequest,
    SandboxHandle,
    SandboxInspection,
    SandboxPreflight,
    SandboxRequirements,
    SandboxSecurityLevel,
    SandboxSpec,
)
from agent_fleet.domain.security import (
    Redactor,
    canonical_json_hash,
    resolve_logical_path,
    sha256_bytes,
)
from agent_fleet.ports.clock import Clock
from agent_fleet.ports.id_generator import IdGenerator


class LocalUnsafeSandboxProvider:
    def __init__(
        self,
        *,
        runner: ProcessRunner,
        clock: Clock,
        ids: IdGenerator,
        state_root: Path,
        redactor: Redactor,
    ) -> None:
        self.runner = runner
        self.clock = clock
        self.ids = ids
        self.state_root = state_root
        self.redactor = redactor
        self._handles: dict[str, SandboxHandle] = {}
        self._specs: dict[str, SandboxSpec] = {}
        self._executions: set[str] = set()

    @property
    def capabilities(self) -> SandboxCapabilities:
        return SandboxCapabilities(
            provider="local-unsafe",
            security_level=SandboxSecurityLevel.UNSAFE_HOST,
            isolation_enforced=False,
            executes_code=True,
            supported_network_modes=("approved-unrestricted",),
            supports_resource_limits=False,
            supports_recovery=False,
        )

    @property
    def security_level(self) -> SandboxSecurityLevel:
        return self.capabilities.security_level

    @property
    def recovery_scope_id(self) -> None:
        return None

    async def preflight(
        self,
        configuration: SandboxConfiguration,
        requirements: SandboxRequirements,
    ) -> SandboxPreflight:
        if configuration.provider != "local-unsafe":
            raise ValueError("LocalUnsafeSandboxProvider requires provider='local-unsafe'")
        return SandboxPreflight(
            provider="local-unsafe",
            ready=True,
            capabilities=self.capabilities,
            configuration_hash=canonical_json_hash(configuration.model_dump(mode="json")),
            requirements_hash=canonical_json_hash(requirements.model_dump(mode="json")),
            endpoint_kind="host",
            diagnostic=(
                "Host execution is available but provides no isolation, bounded recovery, "
                "or network restriction."
            ),
            checked_at=self.clock.now(),
        )

    async def create(
        self,
        run_id: str,
        spec: SandboxSpec,
        *,
        sandbox_id: str | None = None,
    ) -> SandboxHandle:
        spec_snapshot = SandboxSpec.model_validate(spec.model_dump(mode="json"))
        handle = await self._validate_preparation(
            run_id,
            spec_snapshot,
            sandbox_id=sandbox_id,
        )
        return self._publish_new(handle, spec_snapshot)

    async def _validate_preparation(
        self,
        run_id: str,
        spec: SandboxSpec,
        *,
        sandbox_id: str | None,
    ) -> SandboxHandle:
        if spec.configuration.provider != "local-unsafe":
            raise ValueError("LocalUnsafeSandboxProvider requires provider='local-unsafe'")
        if not spec.unsafe_local_confirmed:
            raise FleetError(
                ErrorCode.UNSAFE_LOCAL_CONFIRMATION_REQUIRED,
                "Local host execution requires a separate explicit high-risk confirmation.",
                "Pass `--allow-unsafe-local` deliberately; `--yes` is not sufficient.",
            )
        if spec.configuration.network_mode != "approved-unrestricted":
            raise FleetError(
                ErrorCode.SANDBOX_CAPABILITY_MISSING,
                "Local-unsafe cannot enforce network isolation on the host.",
                "Use the explicit unrestricted local-unsafe configuration or select Docker.",
            )
        workspace = await asyncio.to_thread(
            Path(spec.workspace_host_path).resolve,
            strict=True,
        )
        identity = sandbox_id or self.ids.new(IdPrefix.SANDBOX)
        handle = SandboxHandle(
            sandbox_id=identity,
            run_id=run_id,
            project_id=spec.project_id,
            workspace_host_path=str(workspace),
            provider="local-unsafe",
            capabilities=self.capabilities,
            configuration_hash=canonical_json_hash(spec.configuration.model_dump(mode="json")),
        )
        return SandboxHandle.model_validate(handle.model_dump(mode="json"))

    def _publish_new(self, handle: SandboxHandle, spec: SandboxSpec) -> SandboxHandle:
        identity = handle.sandbox_id
        if identity in self._handles or identity in self._specs:
            raise FleetError(
                ErrorCode.SANDBOX_CREATION_FAILED,
                "Local-unsafe sandbox preparation is already active for this identity.",
                "Terminate the existing logical sandbox before preparing it again.",
            )
        self._handles[identity] = handle
        self._specs[identity] = spec
        return SandboxHandle.model_validate(handle.model_dump(mode="json"))

    async def restore(self, handle: SandboxHandle, spec: SandboxSpec) -> SandboxHandle:
        handle_snapshot = SandboxHandle.model_validate(handle.model_dump(mode="json"))
        spec_snapshot = SandboxSpec.model_validate(spec.model_dump(mode="json"))
        initial_handle = self._handles.get(handle_snapshot.sandbox_id)
        initial_spec = self._specs.get(handle_snapshot.sandbox_id)
        if (
            handle.provider != "local-unsafe"
            or spec.configuration.provider != "local-unsafe"
            or (initial_handle is None) is not (initial_spec is None)
            or (initial_handle is not None and initial_handle != handle_snapshot)
            or (initial_spec is not None and initial_spec != spec_snapshot)
        ):
            raise FleetError(
                ErrorCode.SANDBOX_INSPECTION_FAILED,
                "The local-unsafe sandbox restoration binding is invalid.",
                "Resume through the exact explicitly confirmed local-unsafe checkpoint.",
            )
        expected = await self._validate_preparation(
            handle_snapshot.run_id,
            spec_snapshot,
            sandbox_id=handle_snapshot.sandbox_id,
        )
        if handle_snapshot != expected:
            raise FleetError(
                ErrorCode.SANDBOX_INSPECTION_FAILED,
                "The local-unsafe sandbox restoration binding is invalid.",
                "Resume through the exact explicitly confirmed local-unsafe checkpoint.",
            )
        current = self._handles.get(handle.sandbox_id)
        current_spec = self._specs.get(handle.sandbox_id)
        if initial_handle is None and initial_spec is None:
            if current is not None or current_spec is not None:
                raise FleetError(
                    ErrorCode.SANDBOX_INSPECTION_FAILED,
                    "The local-unsafe sandbox restoration binding changed during validation.",
                    "Cancel this run; Fleet preserved the concurrent host execution boundary.",
                )
            return self._publish_new(expected, spec_snapshot)
        if (
            current is None
            or current_spec is None
            or current is not initial_handle
            or current_spec is not initial_spec
            or current != handle_snapshot
            or current_spec != spec_snapshot
        ):
            raise FleetError(
                ErrorCode.SANDBOX_INSPECTION_FAILED,
                "The local-unsafe sandbox restoration binding does not match its checkpoint.",
                "Cancel this run; Fleet did not substitute another host execution boundary.",
            )
        return SandboxHandle.model_validate(current.model_dump(mode="json"))

    async def inspect(self, handle: SandboxHandle) -> SandboxInspection:
        if handle.sandbox_id not in self._handles:
            raise FleetError(
                ErrorCode.SANDBOX_INSPECTION_FAILED,
                "Local-unsafe sandbox handle is unavailable.",
                "Start a new explicitly confirmed local-unsafe execution.",
            )
        return SandboxInspection(
            sandbox_id=handle.sandbox_id,
            provider="local-unsafe",
            ready=True,
            capabilities=self.capabilities,
            configuration_hash=handle.configuration_hash or "0" * 64,
            effective_network_mode="approved-unrestricted",
            non_root=False,
            read_only_root=False,
            no_new_privileges=False,
            capabilities_dropped=False,
            resource_limits_enforced=False,
            exact_mounts=False,
            inspected_at=self.clock.now(),
        )

    async def exec(
        self,
        handle: SandboxHandle,
        request: ExecRequest,
        *,
        on_creation_dispatched: Callable[[], None] | None = None,
        on_resource_created: Callable[[SandboxExecutionHandle], None] | None = None,
    ) -> ExecResult:
        if handle.sandbox_id not in self._handles:
            raise FleetError(
                ErrorCode.SANDBOX_EXECUTION_FAILED,
                "Local-unsafe sandbox handle is unavailable.",
                "Start a new explicitly confirmed local-unsafe execution.",
            )
        if request.network_mode != "approved-unrestricted":
            raise FleetError(
                ErrorCode.SANDBOX_CAPABILITY_MISSING,
                "Local-unsafe cannot satisfy a network-none execution request.",
                "Use Docker for network isolation or explicitly accept unrestricted host mode.",
            )
        if self.redactor.contains_secret_data(request.environment):
            raise FleetError(
                ErrorCode.COMMAND_DENIED,
                "A registered secret reached the local-unsafe environment boundary.",
                "Use only reviewed non-secret command environment values.",
            )
        if request.execution_id is None:
            raise FleetError(
                ErrorCode.SANDBOX_EXECUTION_FAILED,
                "Local-unsafe execution requires a control-plane execution identity.",
                "Retry through ToolGateway; direct execution is unsupported.",
            )
        labels = {
            "agent-fleet.run": handle.run_id,
            "agent-fleet.sandbox": handle.sandbox_id,
            "agent-fleet.execution": request.execution_id,
        }
        resource_handle = SandboxExecutionHandle(
            execution_id=request.execution_id,
            sandbox_id=handle.sandbox_id,
            run_id=handle.run_id,
            provider="local-unsafe",
            native_resource_id=f"local-process:{request.execution_id}",
            labels=labels,
            labels_sha256=canonical_json_hash(labels),
        )
        workspace = Path(handle.workspace_host_path)
        cwd = resolve_logical_path(workspace, request.cwd, allow_missing=False)
        executable = resolve_trusted_executable(
            request.executable,
            cwd,
            workspace,
            self.state_root,
            expected_name=Path(request.executable).name,
        )
        if executable is None:
            raise FleetError(
                ErrorCode.COMMAND_DENIED,
                "The local-unsafe command executable is not trusted or available.",
                "Use an exact reviewed executable outside the repository and Fleet state.",
            )
        if on_creation_dispatched is not None:
            on_creation_dispatched()
        self._executions.add(request.execution_id)
        if on_resource_created is not None:
            on_resource_created(resource_handle)
        environment = dict(request.environment)
        environment["PATH"] = trusted_search_path(cwd, workspace, self.state_root)
        started = self.clock.now()
        try:
            result = await self.runner.run(
                (executable, *request.argv),
                environment=environment,
                cwd=str(cwd),
                timeout_seconds=request.timeout_seconds,
                max_output_bytes=request.max_output_bytes,
            )
        except ProcessTerminationError as error:
            raise FleetError(
                ErrorCode.SANDBOX_CLEANUP_FAILED,
                "The local-unsafe host process could not be proven fully terminated.",
                "Inspect local child processes before starting a fresh run.",
            ) from error
        except ProcessInvocationError as error:
            raise FleetError(
                ErrorCode.SANDBOX_EXECUTION_FAILED,
                "The local-unsafe host process could not be started.",
                "Inspect the trusted executable and start a fresh run.",
            ) from error
        inspection = await self.inspect(handle)
        cleanup = await self.cleanup_execution(resource_handle)
        return ExecResult(
            exit_code=result.returncode,
            stdout=result.stdout.decode("utf-8", errors="replace"),
            stderr=result.stderr.decode("utf-8", errors="replace"),
            started_at=started,
            completed_at=self.clock.now(),
            timed_out=result.timed_out,
            output_truncated=result.output_truncated,
            execution=(
                SandboxExecutionMetadata(
                    execution_id=request.execution_id,
                    provider="local-unsafe",
                    resource_id_sha256=sha256_bytes(
                        f"local-process:{request.execution_id}".encode()
                    ),
                    configuration_hash=handle.configuration_hash or "0" * 64,
                    capabilities_hash=canonical_json_hash(
                        self.capabilities.model_dump(mode="json")
                    ),
                    inspection_hash=canonical_json_hash(inspection.model_dump(mode="json")),
                    inspection=inspection,
                    resource_handle=resource_handle,
                    cleanup_result=cleanup,
                )
                if request.execution_id is not None
                else None
            ),
        )

    async def cleanup_execution(self, handle: SandboxExecutionHandle) -> SandboxCleanupResult:
        found = int(handle.execution_id in self._executions)
        self._executions.discard(handle.execution_id)
        return SandboxCleanupResult(
            provider="local-unsafe",
            resource_id=handle.native_resource_id,
            resources_found=found,
            resources_removed=found,
            reconciled=True,
            complete=True,
            completed_at=self.clock.now(),
        )

    async def reconcile_execution(
        self,
        sandbox: SandboxHandle,
        request: SandboxExecutionRecoveryRequest,
    ) -> SandboxCleanupResult:
        del sandbox
        execution_id = request.execution_id
        found = int(execution_id in self._executions)
        self._executions.discard(execution_id)
        return SandboxCleanupResult(
            provider="local-unsafe",
            resource_id=execution_id,
            resources_found=found,
            resources_removed=found,
            reconciled=True,
            complete=True,
            completed_at=self.clock.now(),
        )

    async def terminate(self, handle: SandboxHandle) -> SandboxCleanupResult:
        found = int(handle.sandbox_id in self._handles)
        self._handles.pop(handle.sandbox_id, None)
        self._specs.pop(handle.sandbox_id, None)
        return SandboxCleanupResult(
            provider="local-unsafe",
            resource_id=handle.sandbox_id,
            resources_found=found,
            resources_removed=found,
            reconciled=True,
            complete=True,
            completed_at=self.clock.now(),
        )
