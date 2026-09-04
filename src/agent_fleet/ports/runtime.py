from __future__ import annotations

from typing import Protocol

from agent_fleet.domain.models import AgentInvocation, AgentInvocationResult


class RuntimeAdapter(Protocol):
    @property
    def capabilities(self) -> frozenset[str]: ...

    async def invoke(self, request: AgentInvocation) -> AgentInvocationResult: ...
