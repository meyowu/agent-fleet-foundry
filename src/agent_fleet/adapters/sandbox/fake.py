"""A deterministic recorder, explicitly not an OS isolation boundary."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

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
from agent_fleet.domain.security import canonical_json_hash, sha256_bytes
from agent_fleet.ports.clock import Clock
from agent_fleet.ports.id_generator import IdGenerator


@dataclass(frozen=True)
class FakeExecScript:
    exit_code: int = 0
    stdout: str = "deterministic fake command: PASS\n"
    stderr: str = ""
    timed_out: bool = False


def _truncate_utf8(value: str, max_bytes: int) -> tuple[str, bool]:
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value, False
    return encoded[:max_bytes].decode("utf-8", errors="ignore"), True


class FakeSandboxProvider:
    def __init__(
        self,
        clock: Clock,
        ids: IdGenerator,
        scripts: list[FakeExecScript] | None = None,
    ) -> None:
        self.clock = clock
        self.ids = ids
        self.scripts = list(scripts or [])
        self.requests: list[ExecRequest] = []
        self.handles: dict[str, SandboxHandle] = {}
        self._specs: dict[str, SandboxSpec] = {}
        self.terminated: set[str] = set()
        self.executions: set[str] = set()

    @property
    def capabilities(self) -> SandboxCapabilities:
        return SandboxCapabilities.phase1_fake()

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
        if configuration.provider != "fake":
            raise ValueError("FakeSandboxProvider requires provider='fake'")
        return SandboxPreflight(
            provider="fake",
            ready=True,
            capabilities=self.capabilities,
            configuration_hash=canonical_json_hash(configuration.model_dump(mode="json")),
            requirements_hash=canonical_json_hash(requirements.model_dump(mode="json")),
            endpoint_kind="none",
            diagnostic="Deterministic simulation is ready; no project code will execute.",
            checked_at=self.clock.now(),
        )

    async def create(
        self,
        run_id: str,
        spec: SandboxSpec,
        *,
        sandbox_id: str | None = None,
    ) -> SandboxHandle:
        if spec.configuration.provider != "fake":
            raise ValueError("FakeSandboxProvider requires provider='fake'")
        handle = SandboxHandle(
            sandbox_id=sandbox_id or self.ids.new(IdPrefix.SANDBOX),
            run_id=run_id,
            project_id=spec.project_id,
            workspace_host_path=spec.workspace_host_path,
            provider="fake",
            capabilities=self.capabilities,
            configuration_hash=canonical_json_hash(spec.configuration.model_dump(mode="json")),
        )
        handle_snapshot = SandboxHandle.model_validate(handle.model_dump(mode="json"))
        self.handles[handle.sandbox_id] = handle_snapshot
        self._specs[handle.sandbox_id] = SandboxSpec.model_validate(spec.model_dump(mode="json"))
        return SandboxHandle.model_validate(handle_snapshot.model_dump(mode="json"))

    async def restore(self, handle: SandboxHandle, spec: SandboxSpec) -> SandboxHandle:
        handle_snapshot = SandboxHandle.model_validate(handle.model_dump(mode="json"))
        spec_snapshot = SandboxSpec.model_validate(spec.model_dump(mode="json"))
        expected = SandboxHandle(
            sandbox_id=handle_snapshot.sandbox_id,
            run_id=handle_snapshot.run_id,
            project_id=spec_snapshot.project_id,
            workspace_host_path=spec_snapshot.workspace_host_path,
            provider="fake",
            capabilities=self.capabilities,
            configuration_hash=canonical_json_hash(
                spec_snapshot.configuration.model_dump(mode="json")
            ),
        )
        if (
            handle.provider != "fake"
            or spec.configuration.provider != "fake"
            or handle_snapshot != expected
        ):
            raise FleetError(
                ErrorCode.SANDBOX_INSPECTION_FAILED,
                "The fake sandbox restoration binding is invalid.",
                "Resume through the exact recorded fake sandbox checkpoint.",
            )
        current = self.handles.get(handle.sandbox_id)
        if current is None:
            restored = await self.create(
                handle.run_id,
                spec_snapshot,
                sandbox_id=handle.sandbox_id,
            )
            current = self.handles.get(handle.sandbox_id)
        else:
            restored = SandboxHandle.model_validate(current.model_dump(mode="json"))
        if (
            current is None
            or current != handle_snapshot
            or restored != handle_snapshot
            or self._specs.get(handle.sandbox_id) != spec_snapshot
        ):
            raise FleetError(
                ErrorCode.SANDBOX_INSPECTION_FAILED,
                "The fake sandbox restoration binding does not match its checkpoint.",
                "Cancel this run; Fleet did not substitute another sandbox.",
            )
        return SandboxHandle.model_validate(current.model_dump(mode="json"))

    async def inspect(self, handle: SandboxHandle) -> SandboxInspection:
        if handle.provider != "fake" or handle.sandbox_id not in self.handles:
            raise ValueError("unknown fake sandbox handle")
        return SandboxInspection(
            sandbox_id=handle.sandbox_id,
            provider="fake",
            ready=True,
            capabilities=self.capabilities,
            configuration_hash=handle.configuration_hash
            or canonical_json_hash({"provider": "fake", "network_mode": "none"}),
            effective_network_mode="none",
            non_root=False,
            read_only_root=False,
            no_new_privileges=False,
            capabilities_dropped=False,
            resource_limits_enforced=False,
            exact_mounts=True,
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
        self.handles.setdefault(handle.sandbox_id, handle)
        self.requests.append(request)
        if request.execution_id is None:
            raise ValueError("fake gateway execution requires an execution identity")
        labels = {
            "agent-fleet.run": handle.run_id,
            "agent-fleet.sandbox": handle.sandbox_id,
            "agent-fleet.execution": request.execution_id,
        }
        resource_handle = SandboxExecutionHandle(
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
        self.executions.add(request.execution_id)
        if on_resource_created is not None:
            on_resource_created(resource_handle)
        script = self.scripts.pop(0) if self.scripts else FakeExecScript()
        start = self.clock.now()
        stdout, stdout_truncated = _truncate_utf8(
            script.stdout,
            request.max_output_bytes,
        )
        stderr, stderr_truncated = _truncate_utf8(
            script.stderr,
            max(0, request.max_output_bytes - len(stdout.encode("utf-8"))),
        )
        inspection = await self.inspect(handle)
        cleanup = await self.cleanup_execution(resource_handle)
        return ExecResult(
            exit_code=script.exit_code,
            stdout=stdout,
            stderr=stderr,
            started_at=start,
            completed_at=self.clock.now(),
            timed_out=script.timed_out,
            output_truncated=stdout_truncated or stderr_truncated,
            execution=SandboxExecutionMetadata(
                execution_id=request.execution_id,
                provider="fake",
                resource_id_sha256=sha256_bytes(f"fake-execution:{request.execution_id}".encode()),
                configuration_hash=inspection.configuration_hash,
                capabilities_hash=canonical_json_hash(self.capabilities.model_dump(mode="json")),
                inspection_hash=canonical_json_hash(inspection.model_dump(mode="json")),
                inspection=inspection,
                resource_handle=resource_handle,
                cleanup_result=cleanup,
            ),
        )

    async def cleanup_execution(self, handle: SandboxExecutionHandle) -> SandboxCleanupResult:
        found = int(handle.execution_id in self.executions)
        self.executions.discard(handle.execution_id)
        return SandboxCleanupResult(
            provider="fake",
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
        found = int(execution_id in self.executions)
        self.executions.discard(execution_id)
        return SandboxCleanupResult(
            provider="fake",
            resource_id=execution_id,
            resources_found=found,
            resources_removed=found,
            reconciled=True,
            complete=True,
            completed_at=self.clock.now(),
        )

    async def terminate(self, handle: SandboxHandle) -> SandboxCleanupResult:
        found = int(handle.sandbox_id in self.handles)
        self.terminated.add(handle.sandbox_id)
        self.handles.pop(handle.sandbox_id, None)
        self._specs.pop(handle.sandbox_id, None)
        return SandboxCleanupResult(
            provider="fake",
            resource_id=handle.sandbox_id,
            resources_found=found,
            resources_removed=found,
            reconciled=True,
            complete=True,
            completed_at=self.clock.now(),
        )
