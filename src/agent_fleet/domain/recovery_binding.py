"""Internal, immutable stopped-owner review and exact cleanup receipts.

Serialized snapshots are deliberately retained as strings: frozen outer models
do not make a nested Run or a lease's metadata dictionary immutable.
"""

from __future__ import annotations

from pydantic import Field, model_validator

from agent_fleet.domain.conversation import Conversation, ConversationClaim, ConversationTurn
from agent_fleet.domain.graph import GraphSnapshot
from agent_fleet.domain.models import (
    CorrelationId,
    FrozenStrictModel,
    Project,
    ResourceLease,
    Run,
    StrictModel,
)
from agent_fleet.domain.security import canonical_json_hash
from agent_fleet.domain.session_review import SessionSelection


class RecoverySnapshot(StrictModel):
    """A transaction-local decoded value, never the retained authority object."""

    selection: SessionSelection
    project: Project
    conversation: Conversation
    turn: ConversationTurn
    claim: ConversationClaim
    claim_status: str = Field(pattern=r"^(active|released|fenced)$")
    claim_released_at: str | None
    runs: tuple[Run, ...] = Field(min_length=1, max_length=129)
    graphs: tuple[GraphSnapshot, ...] = Field(default=(), max_length=129)
    leases: tuple[ResourceLease, ...] = Field(default=(), max_length=256)


class RecoveryBinding(FrozenStrictModel):
    snapshot_json: str = Field(max_length=16_777_216)

    @model_validator(mode="after")
    def validate_snapshot(self) -> RecoveryBinding:
        if len(self.snapshot_json.encode("utf-8")) > 16_777_216:
            raise ValueError("recovery snapshot exceeds its byte limit")
        RecoverySnapshot.model_validate_json(self.snapshot_json)
        return self

    def snapshot(self) -> RecoverySnapshot:
        return RecoverySnapshot.model_validate_json(self.snapshot_json)

    @property
    def sha256(self) -> str:
        return canonical_json_hash(self.snapshot().model_dump(mode="json"))


class ReviewedRecoveryPlan(FrozenStrictModel):
    plan_id: CorrelationId
    binding: RecoveryBinding

    @property
    def sha256(self) -> str:
        return canonical_json_hash(self.model_dump(mode="json"))


class RecoveryLeaseClaim(FrozenStrictModel):
    claim_id: CorrelationId
    plan: ReviewedRecoveryPlan
    lease_json: str = Field(max_length=1_048_576)

    def lease(self) -> ResourceLease:
        return ResourceLease.model_validate_json(self.lease_json)
