"""User-owned Phase 1 approval resolution."""

from __future__ import annotations

from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import ApprovalStatus, CapabilityGrant
from agent_fleet.ports.state_store import StateStore


class ApprovalService:
    def __init__(self, state: StateStore) -> None:
        self.state = state

    def approve_once(self, request_id: str, *, actor: str = "user") -> CapabilityGrant:
        if actor != "user":
            raise FleetError(
                ErrorCode.APPROVAL_INVALID,
                "Agents and workflow roles cannot approve permission requests.",
                "A user must issue the explicit approval command.",
                details={"actor": actor},
            )
        request = self.state.get_approval(request_id)
        if request.status is ApprovalStatus.DENIED:
            raise FleetError(
                ErrorCode.APPROVAL_INVALID,
                "A denied approval request cannot later be approved.",
                "Start a new run if the action is still wanted.",
            )
        grant = self.state.resolve_approval(request_id, approve=True, denial_reason=None)
        if grant is None:
            raise FleetError(
                ErrorCode.APPROVAL_INVALID,
                "Approval resolution did not issue a one-use grant.",
                "Inspect the approval event history.",
            )
        return grant

    def deny(self, request_id: str, reason: str | None = None) -> None:
        request = self.state.get_approval(request_id)
        if request.status is ApprovalStatus.APPROVED:
            raise FleetError(
                ErrorCode.APPROVAL_INVALID,
                "An approved request cannot be changed to denied.",
                "Cancel the run before resuming if the action is no longer wanted.",
            )
        self.state.resolve_approval(request_id, approve=False, denial_reason=reason)
