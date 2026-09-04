"""A deterministic recorder, explicitly not an OS isolation boundary."""

from __future__ import annotations

from dataclasses import dataclass

from agent_fleet.domain.ids import IdPrefix
from agent_fleet.domain.models import (
    ExecRequest,
    ExecResult,
    SandboxHandle,
    SandboxSecurityLevel,
    SandboxSpec,
)
from agent_fleet.ports.clock import Clock
from agent_fleet.ports.id_generator import IdGenerator


@dataclass(frozen=True)
class FakeExecScript:
    exit_code: int = 0
    stdout: str = "deterministic fake command: PASS\n"
    stderr: str = ""
    timed_out: bool = False


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
        self.terminated: set[str] = set()

    @property
    def security_level(self) -> SandboxSecurityLevel:
        return SandboxSecurityLevel.FAKE

    async def create(self, run_id: str, spec: SandboxSpec) -> SandboxHandle:
        handle = SandboxHandle(
            sandbox_id=self.ids.new(IdPrefix.SANDBOX),
            run_id=run_id,
            workspace_host_path=spec.workspace_host_path,
        )
        self.handles[handle.sandbox_id] = handle
        return handle

    async def exec(self, handle: SandboxHandle, request: ExecRequest) -> ExecResult:
        self.handles.setdefault(handle.sandbox_id, handle)
        self.requests.append(request)
        script = self.scripts.pop(0) if self.scripts else FakeExecScript()
        start = self.clock.now()
        stdout = script.stdout[: request.max_output_bytes]
        stderr = script.stderr[: request.max_output_bytes]
        return ExecResult(
            exit_code=script.exit_code,
            stdout=stdout,
            stderr=stderr,
            started_at=start,
            completed_at=self.clock.now(),
            timed_out=script.timed_out,
        )

    async def terminate(self, handle: SandboxHandle) -> None:
        self.terminated.add(handle.sandbox_id)
        self.handles.pop(handle.sandbox_id, None)
