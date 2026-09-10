"""Atomic root-Run registration and conversation execution ownership."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Protocol

from agent_fleet.domain.budgets import RunBudgetLimits
from agent_fleet.domain.conversation import (
    Conversation,
    ConversationArtifactRef,
    ConversationClaim,
    ConversationRegistration,
    ConversationRunBinding,
    ConversationSubmission,
    ConversationSummary,
    ConversationTurn,
)
from agent_fleet.domain.models import LeaseStatus, Run
from agent_fleet.domain.recovery_binding import (
    RecoveryBinding,
    RecoveryLeaseClaim,
    ReviewedRecoveryPlan,
)
from agent_fleet.domain.session_review import SessionSelection

if TYPE_CHECKING:
    from agent_fleet.domain.evolution import OrganizationAdmission


class ConversationStore(Protocol):
    def capture_recovery(self, selection: SessionSelection) -> RecoveryBinding: ...

    def prepare_reviewed_recovery(self, binding: RecoveryBinding) -> ReviewedRecoveryPlan:
        """Compare original review and fence its complete ownership in one transaction."""
        ...

    def claim_recovery_lease(
        self, plan: ReviewedRecoveryPlan, lease_id: str
    ) -> RecoveryLeaseClaim: ...

    def finish_recovery_lease(self, claim: RecoveryLeaseClaim, status: LeaseStatus) -> None: ...

    def reconcile_reviewed_recovery(self, plan: ReviewedRecoveryPlan) -> Run: ...

    def create(self, project_id: str, repository_identity: str) -> Conversation: ...

    def latest(self, project_id: str, repository_identity: str) -> Conversation | None: ...

    def get(self, project_id: str, conversation_id: str) -> Conversation: ...

    def list_turns(
        self,
        project_id: str,
        conversation_id: str,
        *,
        before_sequence: int | None = None,
        limit: int = 50,
    ) -> tuple[ConversationTurn, ...]: ...

    def get_submission(
        self, project_id: str, conversation_id: str, submission_key: str
    ) -> ConversationTurn | None: ...

    def get_turn(self, project_id: str, turn_id: str) -> ConversationTurn: ...

    def binding_for_run(self, run_id: str) -> ConversationRunBinding | None: ...

    def register_turn_run(
        self,
        submission: ConversationSubmission,
        run: Run,
        *,
        config_snapshot_sha256: str,
        budget_limits: RunBudgetLimits,
        organization_admission: OrganizationAdmission | None = None,
    ) -> ConversationRegistration: ...

    def assert_claim(self, claim: ConversationClaim) -> ConversationTurn: ...

    def claim_resume(self, run_id: str, *, expected_revision: int) -> ConversationClaim: ...

    def settle(
        self,
        claim: ConversationClaim,
        *,
        expected_revision: int,
        summary: ConversationSummary | None = None,
        artifact_refs: tuple[ConversationArtifactRef, ...] = (),
    ) -> ConversationTurn: ...

    def fence(
        self,
        run_id: str,
        *,
        expected_revision: int,
        reason: Literal["cancel", "recovery"],
        claim: ConversationClaim | None = None,
    ) -> ConversationTurn:
        """Recovery without a claim requires explicit stopped-owner user authority."""
        ...

    def reconcile_fenced(
        self,
        run_id: str,
        *,
        expected_revision: int,
        summary: ConversationSummary | None = None,
        artifact_refs: tuple[ConversationArtifactRef, ...] = (),
    ) -> ConversationTurn: ...
