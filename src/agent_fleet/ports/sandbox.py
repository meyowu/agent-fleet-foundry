from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from agent_fleet.domain.models import (
    ExecRequest,
    ExecResult,
    SandboxCapabilities,
    SandboxCleanupResult,
    SandboxConfiguration,
    SandboxExecutionHandle,
    SandboxExecutionRecoveryRequest,
    SandboxHandle,
    SandboxInspection,
    SandboxPreflight,
    SandboxRequirements,
    SandboxSecurityLevel,
    SandboxSpec,
)


class SandboxProvider(Protocol):
    @property
    def capabilities(self) -> SandboxCapabilities: ...

    @property
    def security_level(self) -> SandboxSecurityLevel: ...

    @property
    def recovery_scope_id(self) -> str | None: ...

    async def preflight(
        self,
        configuration: SandboxConfiguration,
        requirements: SandboxRequirements,
    ) -> SandboxPreflight: ...

    async def create(
        self,
        run_id: str,
        spec: SandboxSpec,
        *,
        sandbox_id: str | None = None,
    ) -> SandboxHandle: ...

    async def inspect(self, handle: SandboxHandle) -> SandboxInspection: ...

    async def exec(
        self,
        handle: SandboxHandle,
        request: ExecRequest,
        *,
        on_creation_dispatched: Callable[[], None] | None = None,
        on_resource_created: Callable[[SandboxExecutionHandle], None] | None = None,
    ) -> ExecResult: ...

    async def cleanup_execution(self, handle: SandboxExecutionHandle) -> SandboxCleanupResult: ...

    async def reconcile_execution(
        self,
        sandbox: SandboxHandle,
        request: SandboxExecutionRecoveryRequest,
    ) -> SandboxCleanupResult: ...

    async def terminate(self, handle: SandboxHandle) -> SandboxCleanupResult: ...
