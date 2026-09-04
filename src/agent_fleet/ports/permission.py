from __future__ import annotations

from typing import Protocol

from agent_fleet.domain.models import (
    PermissionDecision,
    SandboxCapabilities,
    TaskSpec,
    ToolIntent,
)


class PermissionBroker(Protocol):
    """Project-owned authorization boundary for every runtime-requested action."""

    def evaluate(
        self,
        intent: ToolIntent,
        task: TaskSpec,
        sandbox: SandboxCapabilities,
    ) -> PermissionDecision: ...
