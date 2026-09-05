"""User-owned Phase 1 approval resolution."""

from __future__ import annotations

from agent_fleet.application.permission_policy import (
    PermissionPolicyService,
    PolicyPermissionBroker,
)
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import (
    ApprovalChoice,
    ApprovalStatus,
    CapabilityGrant,
    PermissionOutcome,
)
from agent_fleet.domain.security import canonical_json_hash
from agent_fleet.domain.trust import ExactPermissionScope
from agent_fleet.ports.state_store import StateStore


class ApprovalService:
    def __init__(self, state: StateStore, policy: PermissionPolicyService | None = None) -> None:
        self.state = state
        self.policy = policy

    def approve_once(self, request_id: str, *, actor: str = "user") -> CapabilityGrant:
        return self.approve(request_id, choice=ApprovalChoice.ALLOW_ONCE, actor=actor)

    def approve(
        self, request_id: str, *, choice: ApprovalChoice, actor: str = "user"
    ) -> CapabilityGrant:
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
        if choice is ApprovalChoice.DENY:
            raise FleetError(
                ErrorCode.APPROVAL_INVALID,
                "Deny is not an approval choice.",
                "Use the explicit deny command.",
            )
        scope_hash = (
            canonical_json_hash(request.authorization_scope)
            if request.authorization_scope is not None
            else None
        )
        source_rule_id = request.source_rule_id
        if request.status is ApprovalStatus.PENDING and self.policy is not None:
            run = self.state.get_run(request.run_id)
            self.policy.validate_run_target(run)
            if run.task_id is None or run.sandbox_capabilities_snapshot is None:
                raise FleetError(
                    ErrorCode.APPROVAL_INVALID,
                    "Approval context is incomplete.",
                    "Inspect the run before retrying.",
                )
            stored = self.state.get_intent(request.intent_id)
            if canonical_json_hash(stored.intent.model_dump(mode="json")) != request.intent_hash:
                raise FleetError(
                    ErrorCode.APPROVAL_INVALID,
                    "The approved intent has changed.",
                    "Start a fresh run with the intended action.",
                )
            decision = PolicyPermissionBroker(self.policy).evaluate(
                stored.intent, self.state.get_task(run.task_id), run.sandbox_capabilities_snapshot
            )
            if decision.outcome is PermissionOutcome.DENY or decision.effective_scope is None:
                raise FleetError(
                    ErrorCode.COMMAND_DENIED,
                    decision.explanation,
                    "A user approval cannot override a policy ceiling.",
                )
            scope = ExactPermissionScope.model_validate(decision.effective_scope)
            if request.authorization_scope is not None:
                if scope.model_dump(mode="json") != request.authorization_scope:
                    raise FleetError(
                        ErrorCode.APPROVAL_INVALID,
                        "The approval scope changed.",
                        "Start a new run after reviewing the changed conditions.",
                    )
                scope_hash = scope.scope_sha256
            elif choice is not ApprovalChoice.ALLOW_ONCE:
                raise FleetError(
                    ErrorCode.APPROVAL_INVALID,
                    "A legacy request permits once only.",
                    "Start a new run to obtain a fully scoped request.",
                )
            if choice not in request.available_choices:
                raise FleetError(
                    ErrorCode.APPROVAL_INVALID,
                    "This approval duration is unavailable.",
                    "Choose an option present on the exact request.",
                )
            if choice is ApprovalChoice.ALLOW_ALWAYS:
                source_rule_id = self.policy.stage_always_rule(request_id, scope).rule_id
        elif request.status is ApprovalStatus.PENDING and choice is not ApprovalChoice.ALLOW_ONCE:
            raise FleetError(
                ErrorCode.APPROVAL_INVALID,
                "Persistent policy is not configured.",
                "Use the complete Fleet application to grant a wider duration.",
            )
        grant = self.state.resolve_approval(
            request_id,
            approve=True,
            denial_reason=None,
            choice=choice,
            scope_sha256=scope_hash,
            source_rule_id=source_rule_id,
        )
        if grant is None:
            raise FleetError(
                ErrorCode.APPROVAL_INVALID,
                "Approval resolution did not issue a one-use grant.",
                "Inspect the approval event history.",
            )
        return grant

    def deny(self, request_id: str, reason: str | None = None, *, actor: str = "user") -> None:
        if actor != "user":
            raise FleetError(
                ErrorCode.APPROVAL_INVALID,
                "Only the user may resolve approvals.",
                "Request a decision from the user.",
            )
        request = self.state.get_approval(request_id)
        if request.status is ApprovalStatus.APPROVED:
            raise FleetError(
                ErrorCode.APPROVAL_INVALID,
                "An approved request cannot be changed to denied.",
                "Cancel the run before resuming if the action is no longer wanted.",
            )
        self.state.resolve_approval(request_id, approve=False, denial_reason=reason)
