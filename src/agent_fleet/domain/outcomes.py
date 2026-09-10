"""Immutable observations, not external-evidence authenticity or spending authority."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator, model_validator

from agent_fleet.domain.evaluation import (
    CampaignId,
    CaseId,
    EvaluationModel,
    EvidenceCategory,
    require_utc,
)
from agent_fleet.domain.models import ArtifactId, RunId, RunStatus, Sha256, TaskId, Verdict

OutcomeKind = Literal[
    "verified_success",
    "functional_failure",
    "environment_failure",
    "provider_failure",
    "budget_exhausted",
    "timeout",
    "cancelled",
    "inconclusive",
    "not_run",
    "dispatch_unknown",
]
OutcomeId = Annotated[str, StringConstraints(pattern=r"^outcome_[0-9a-f]{32}$")]
AttemptId = Annotated[str, StringConstraints(pattern=r"^attempt_[0-9a-f]{32}$")]
Currency = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
Count = Annotated[int, Field(strict=True, ge=0, le=2**63 - 1)]


class OutcomeArtifactRef(EvaluationModel):
    artifact_id: ArtifactId
    category: EvidenceCategory
    run_id: RunId | None
    sha256: Sha256


class OutcomeUsage(EvaluationModel):
    """One disjoint usage segment; None remains unreported, never zero."""

    segment_id: Annotated[
        str, StringConstraints(min_length=1, max_length=100, pattern=r"^[a-z][a-z0-9_-]*$")
    ]
    model_requests: Count | None = None
    tool_calls: Count | None = None
    input_tokens: Count | None = None
    output_tokens: Count | None = None
    active_milliseconds: Count | None = None
    unknown_requests: Count = 0


class OutcomeRecord(EvaluationModel):
    schema_version: int = Field(default=1, strict=True, ge=1, le=1)
    outcome_id: OutcomeId
    campaign_id: CampaignId
    manifest_sha256: Sha256
    case_id: CaseId
    repetition: int = Field(strict=True, ge=0, le=2)
    attempt_id: AttemptId
    root_run_id: RunId | None = None
    task_id: TaskId | None = None
    recorded_at: datetime
    configuration_sha256: Sha256
    oracle_sha256: Sha256
    scoring_sha256: Sha256
    product_status: RunStatus | None = None
    product_verdict: Verdict | None = None
    product_verified_complete: bool | None = None
    external_result: OutcomeKind
    user_acceptance: Literal["accepted", "rejected", "not_observed"] = "not_observed"
    apply_status: Literal["applied", "not_applied", "failed", "not_applicable", "unknown"]
    artifacts: tuple[OutcomeArtifactRef, ...] = Field(default=(), max_length=64)
    usage: tuple[OutcomeUsage, ...] = Field(default=(), max_length=64)
    reported_cost_microunits: Count | None = None
    currency: Currency | None = None

    _utc = field_validator("recorded_at")(require_utc)

    @model_validator(mode="after")
    def coherent(self) -> OutcomeRecord:
        # A CoS failure can leave a persisted Run before any TaskSpec is bound.
        # Never manufacture a provisional Task identity merely to record it.
        if self.task_id is not None and self.root_run_id is None:
            raise ValueError("an outcome Task identity requires its actual root Run")
        if self.root_run_id is None and any(
            value is not None
            for value in (self.product_status, self.product_verdict, self.product_verified_complete)
        ):
            raise ValueError("preflight outcomes cannot invent product Run observations")
        if self.external_result == "verified_success" and (
            self.root_run_id is None or self.task_id is None
        ):
            raise ValueError("successful outcome needs its actual root Run and Task identities")
        if self.external_result == "not_run" and (
            self.root_run_id is not None or self.apply_status == "applied"
        ):
            raise ValueError("not_run cannot contain an executed Run or applied patch")
        if self.external_result == "not_run":
            executed_fields = (
                "model_requests",
                "tool_calls",
                "input_tokens",
                "output_tokens",
                "unknown_requests",
            )
            if any(
                any((getattr(segment, name) or 0) > 0 for name in executed_fields)
                for segment in self.usage
            ):
                raise ValueError("not_run cannot contain executed or unknown model/tool usage")
            if (self.reported_cost_microunits or 0) > 0 or any(
                ref.category != "diagnostic" for ref in self.artifacts
            ):
                raise ValueError("not_run cannot contain positive cost or execution receipts")
        if len({ref.artifact_id for ref in self.artifacts}) != len(self.artifacts):
            raise ValueError("outcome artifact identities must be unique")
        if any(ref.run_id != self.root_run_id for ref in self.artifacts):
            raise ValueError("outcome artifacts must bind the exact root Run")
        if len({item.segment_id for item in self.usage}) != len(self.usage):
            raise ValueError("usage segments must be unique and disjoint")
        if (self.reported_cost_microunits is None) != (self.currency is None):
            raise ValueError("reported cost and currency must occur together")
        if self.external_result == "verified_success" and not {"oracle", "cleanup"}.issubset(
            {ref.category for ref in self.artifacts}
        ):
            raise ValueError("success needs structurally linked oracle and cleanup evidence")
        return self
