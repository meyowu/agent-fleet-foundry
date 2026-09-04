from __future__ import annotations

from typing import Protocol

from agent_fleet.domain.models import (
    ExecRequest,
    ExecResult,
    SandboxCapabilities,
    SandboxHandle,
    SandboxSecurityLevel,
    SandboxSpec,
)


class SandboxProvider(Protocol):
    @property
    def capabilities(self) -> SandboxCapabilities: ...

    @property
    def security_level(self) -> SandboxSecurityLevel: ...

    async def create(self, run_id: str, spec: SandboxSpec) -> SandboxHandle: ...

    async def exec(self, handle: SandboxHandle, request: ExecRequest) -> ExecResult: ...

    async def terminate(self, handle: SandboxHandle) -> None: ...
