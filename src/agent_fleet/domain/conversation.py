"""Bounded conversation context and durable, non-authorizing Run ownership."""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator, model_validator

from agent_fleet.domain.budgets import RunBudgetLimits
from agent_fleet.domain.models import (
    ArtifactId,
    ArtifactKind,
    CorrelationId,
    FrozenStrictModel,
    ProjectId,
    RunId,
    RunStatus,
    Sha256,
)
from agent_fleet.domain.security import canonical_json_hash

ConversationId = Annotated[str, StringConstraints(pattern=r"^conv_[0-9a-f]{32}$")]
ConversationTurnId = Annotated[str, StringConstraints(pattern=r"^turn_[0-9a-f]{32}$")]
SubmissionKey = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")]


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("conversation timestamps must be timezone-aware UTC")
    return value


class _ConversationModel(FrozenStrictModel):
    @model_validator(mode="after")
    def bounded_document(self) -> _ConversationModel:
        if len(self.model_dump_json().encode("utf-8")) > 131_072:
            raise ValueError("conversation document exceeds its byte limit")
        return self


class ConversationSummary(_ConversationModel):
    text: Annotated[str, StringConstraints(min_length=1, max_length=4096)]
    truncated: bool = Field(default=False, strict=True)

    @field_validator("text")
    @classmethod
    def bounded_text(cls, value: str) -> str:
        if not value.strip() or "\x00" in value or len(value.encode("utf-8")) > 4096:
            raise ValueError("conversation summary must be nonempty and at most 4096 UTF-8 bytes")
        return value


def _user_summary(value: ConversationSummary) -> ConversationSummary:
    if len(value.text.encode("utf-8")) > 2048:
        raise ValueError("user summary exceeds 2048 UTF-8 bytes")
    return value


class ConversationArtifactRef(_ConversationModel):
    artifact_id: ArtifactId
    sha256: Sha256
    run_id: RunId
    kind: ArtifactKind

    @field_validator("kind")
    @classmethod
    def bounded_kind(cls, value: ArtifactKind) -> ArtifactKind:
        if value not in {
            ArtifactKind.COS_RESPONSE,
            ArtifactKind.RUN_SUMMARY,
            ArtifactKind.EVIDENCE_BUNDLE,
            ArtifactKind.PATCH,
            ArtifactKind.FLEET_PATCH,
            ArtifactKind.FLEET_PATCH_DIFF,
            ArtifactKind.RESOURCE_CLEANUP,
            ArtifactKind.RUNTIME_USAGE,
        }:
            raise ValueError("artifact kind is not a conversation summary reference")
        return value


def _refs(values: tuple[ConversationArtifactRef, ...]) -> tuple[ConversationArtifactRef, ...]:
    if len({value.artifact_id for value in values}) != len(values):
        raise ValueError("conversation artifact references must be unique")
    return values


class ConversationContextEntry(_ConversationModel):
    turn_id: ConversationTurnId
    sequence: int = Field(ge=1, le=1000, strict=True)
    run_id: RunId
    run_status: RunStatus
    user_summary: ConversationSummary
    result_summary: ConversationSummary | None = None
    artifact_refs: tuple[ConversationArtifactRef, ...] = Field(default=(), max_length=8)

    _bounded_user = field_validator("user_summary")(_user_summary)
    _unique_refs = field_validator("artifact_refs")(_refs)

    @model_validator(mode="after")
    def settled_root(self) -> ConversationContextEntry:
        if self.run_status not in {
            RunStatus.READY_FOR_REVIEW,
            RunStatus.COMPLETED,
            RunStatus.REJECTED,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
            RunStatus.ABANDONED,
        } or any(ref.run_id != self.run_id for ref in self.artifact_refs):
            raise ValueError("context must refer to one settled root Run")
        return self


class ConversationContext(_ConversationModel):
    conversation_id: ConversationId
    project_id: ProjectId
    through_sequence: int = Field(ge=0, le=1000, strict=True)
    entries: tuple[ConversationContextEntry, ...] = Field(default=(), max_length=8)

    @property
    def context_sha256(self) -> str:
        return canonical_json_hash(self.model_dump(mode="json"))

    @property
    def omitted_turn_count(self) -> int:
        return self.through_sequence - len(self.entries)

    @model_validator(mode="after")
    def ordered_bounded_history(self) -> ConversationContext:
        sequences = [entry.sequence for entry in self.entries]
        if sequences != sorted(set(sequences)) or any(
            value > self.through_sequence for value in sequences
        ):
            raise ValueError("context sequences must be ordered unique covered turns")
        if len({entry.turn_id for entry in self.entries}) != len(self.entries) or len(
            {entry.run_id for entry in self.entries}
        ) != len(self.entries):
            raise ValueError("context turn and Run identities must be unique")
        if len(self.model_dump_json().encode("utf-8")) > 32768:
            raise ValueError("conversation context exceeds 32768 UTF-8 bytes")
        return self


class Conversation(_ConversationModel):
    api_version: Literal["agentfleet.dev/v1alpha1"] = "agentfleet.dev/v1alpha1"
    kind: Literal["Conversation"] = "Conversation"
    conversation_id: ConversationId
    project_id: ProjectId
    repository_identity: Sha256
    revision: int = Field(default=0, ge=0, strict=True)
    next_turn_sequence: int = Field(default=1, ge=1, le=1001, strict=True)
    active_turn_id: ConversationTurnId | None = None
    created_at: datetime
    updated_at: datetime

    _timestamps = field_validator("created_at", "updated_at")(_utc)

    @model_validator(mode="after")
    def ordered_times(self) -> Conversation:
        if self.updated_at < self.created_at:
            raise ValueError("conversation update precedes creation")
        return self


class ConversationSubmission(_ConversationModel):
    conversation_id: ConversationId
    project_id: ProjectId
    repository_identity: Sha256
    submission_key: SubmissionKey
    expected_revision: int = Field(ge=0, strict=True)
    context: ConversationContext
    user_summary: ConversationSummary

    _bounded_user = field_validator("user_summary")(_user_summary)

    @model_validator(mode="after")
    def matching_context(self) -> ConversationSubmission:
        if (self.context.conversation_id, self.context.project_id) != (
            self.conversation_id,
            self.project_id,
        ):
            raise ValueError("submission context identity does not match")
        return self


class ConversationRunBinding(_ConversationModel):
    conversation_id: ConversationId
    turn_id: ConversationTurnId
    project_id: ProjectId
    repository_identity: Sha256
    sequence: int = Field(ge=1, le=1000, strict=True)
    submission_key: SubmissionKey
    submission_sha256: Sha256
    user_goal_sha256: Sha256
    run_id: RunId
    run_binding_sha256: Sha256
    config_snapshot_sha256: Sha256
    budget_limits: RunBudgetLimits
    context_sha256: Sha256
    created_at: datetime

    _created_utc = field_validator("created_at")(_utc)


class ConversationClaim(_ConversationModel):
    claim_id: CorrelationId
    conversation_id: ConversationId
    turn_id: ConversationTurnId
    project_id: ProjectId
    run_id: RunId
    generation: int = Field(ge=1, strict=True)
    claimed_at: datetime

    _claimed_utc = field_validator("claimed_at")(_utc)


class ConversationTurnStatus(StrEnum):
    RUNNING = "running"
    WAITING = "waiting"
    DELIVERED = "delivered"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RECOVERY_REQUIRED = "recovery_required"


class ConversationTurn(_ConversationModel):
    api_version: Literal["agentfleet.dev/v1alpha1"] = "agentfleet.dev/v1alpha1"
    kind: Literal["ConversationTurn"] = "ConversationTurn"
    binding: ConversationRunBinding
    revision: int = Field(default=0, ge=0, strict=True)
    status: ConversationTurnStatus
    owner_generation: int = Field(ge=1, strict=True)
    active_claim_id: CorrelationId | None = None
    context: ConversationContext
    user_summary: ConversationSummary
    result_summary: ConversationSummary | None = None
    artifact_refs: tuple[ConversationArtifactRef, ...] = Field(default=(), max_length=8)
    observed_run_status: RunStatus
    created_at: datetime
    updated_at: datetime
    settled_at: datetime | None = None
    fenced_at: datetime | None = None

    _bounded_user = field_validator("user_summary")(_user_summary)
    _unique_refs = field_validator("artifact_refs")(_refs)
    _timestamps = field_validator("created_at", "updated_at")(_utc)
    _optional_timestamps = field_validator("settled_at", "fenced_at")(
        lambda value: _utc(value) if value is not None else value
    )

    @model_validator(mode="after")
    def consistent_turn(self) -> ConversationTurn:
        binding = self.binding
        if (
            self.context.conversation_id != binding.conversation_id
            or self.context.project_id != binding.project_id
            or self.context.context_sha256 != binding.context_sha256
            or self.context.through_sequence + 1 != binding.sequence
            or self.created_at != binding.created_at
            or any(ref.run_id != binding.run_id for ref in self.artifact_refs)
            or self.updated_at < self.created_at
            or any(
                value is not None and not self.created_at <= value <= self.updated_at
                for value in (self.settled_at, self.fenced_at)
            )
        ):
            raise ValueError("conversation turn binding is inconsistent")
        terminal = self.status in {
            ConversationTurnStatus.DELIVERED,
            ConversationTurnStatus.FAILED,
            ConversationTurnStatus.CANCELLED,
        }
        if terminal != (self.settled_at is not None) or (
            (self.status is ConversationTurnStatus.RUNNING) != (self.active_claim_id is not None)
        ):
            raise ValueError("conversation turn owner or settlement is inconsistent")
        if self.status is ConversationTurnStatus.RECOVERY_REQUIRED and self.fenced_at is None:
            raise ValueError("conversation recovery requires a durable fence")
        return self


class ConversationRegistration(_ConversationModel):
    turn: ConversationTurn
    claim: ConversationClaim | None = None

    @model_validator(mode="after")
    def matching_owner(self) -> ConversationRegistration:
        if self.claim is not None:
            binding = self.turn.binding
            if (
                self.claim.claim_id != self.turn.active_claim_id
                or self.claim.generation != self.turn.owner_generation
                or any(
                    getattr(self.claim, key) != getattr(binding, key)
                    for key in ("conversation_id", "turn_id", "project_id", "run_id")
                )
            ):
                raise ValueError("registration claim does not match its exact turn")
        return self
