from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from agent_fleet.domain.models import (
    AgentInvocation,
    AgentInvocationResult,
    AgentRole,
    RuntimeCapability,
    RuntimeConfiguration,
    RuntimeCredentialCheck,
    RuntimePreflight,
    RuntimeToolCall,
    RuntimeToolDefinition,
    RuntimeToolExecutionRecord,
    RuntimeToolResult,
)
from agent_fleet.ports.runtime_accounting import RuntimeAccounting


class RuntimeToolCatalog(Protocol):
    """The sole runtime-visible execution boundary, bound by the control plane."""

    @property
    def definitions(self) -> tuple[RuntimeToolDefinition, ...]: ...

    @property
    def records(self) -> tuple[RuntimeToolExecutionRecord, ...]: ...

    def validate(self, call: RuntimeToolCall) -> None: ...

    async def execute(self, call: RuntimeToolCall) -> RuntimeToolResult: ...


class EmptyRuntimeToolCatalog:
    """Explicit fail-closed catalog for roles that receive no tools."""

    @property
    def definitions(self) -> tuple[RuntimeToolDefinition, ...]:
        return ()

    @property
    def records(self) -> tuple[RuntimeToolExecutionRecord, ...]:
        return ()

    def validate(self, call: RuntimeToolCall) -> None:
        raise LookupError(f"runtime tool {call.name!r} is not registered")

    async def execute(self, call: RuntimeToolCall) -> RuntimeToolResult:
        raise LookupError(f"runtime tool {call.name!r} is not registered")


EMPTY_RUNTIME_TOOL_CATALOG = EmptyRuntimeToolCatalog()


@dataclass(frozen=True, slots=True)
class RuntimeInvocationServices:
    """Trusted sideband assembled by the application, never by model output."""

    configuration: RuntimeConfiguration
    tools: RuntimeToolCatalog
    accounting: RuntimeAccounting | None = None
    execution_kind: AgentRole | None = None


class RuntimeAdapter(Protocol):
    @property
    def capabilities(self) -> frozenset[RuntimeCapability]: ...

    def preflight(
        self,
        configuration: RuntimeConfiguration,
        *,
        credential_check: RuntimeCredentialCheck,
    ) -> RuntimePreflight: ...

    async def invoke(
        self,
        request: AgentInvocation,
        services: RuntimeInvocationServices,
    ) -> AgentInvocationResult: ...
