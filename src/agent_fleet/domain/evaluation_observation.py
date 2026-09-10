"""Safe immutable observations; neither execution nor external-success authority."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator, model_validator

from agent_fleet.domain.errors import ErrorCode
from agent_fleet.domain.evaluation import CampaignId, CaseId, EvaluationModel
from agent_fleet.domain.models import RunId, RunStatus, Sha256, TaskId, Verdict
from agent_fleet.domain.outcomes import AttemptId, OutcomeArtifactRef, OutcomeUsage
from agent_fleet.domain.security import canonical_json_hash

TerminalObservationResult = Literal[
    "environment_failure",
    "provider_failure",
    "budget_exhausted",
    "timeout",
    "cancelled",
    "inconclusive",
    "dispatch_unknown",
]


class EvaluationObservation(EvaluationModel):
    campaign_id: CampaignId
    attempt_id: AttemptId
    state: Literal[
        "reserved",
        "active",
        "awaiting_apply",
        "awaiting_oracle",
        "failed",
        "cancelled",
        "dispatch_unknown",
        "corrupt",
    ]
    manifest_sha256: Sha256 | None = None
    case_id: CaseId | None = None
    repetition: int | None = Field(default=None, strict=True, ge=0, le=2)
    root_run_id: RunId | None = None
    task_id: TaskId | None = None
    configuration_sha256: Sha256 | None = None
    oracle_sha256: Sha256 | None = None
    scoring_sha256: Sha256 | None = None
    persisted_sha256: Sha256 | None = None
    product_status: RunStatus | None = None
    product_verdict: Verdict | None = None
    product_verified_complete: bool | None = None
    failure_code: ErrorCode | None = None
    terminal_result: TerminalObservationResult | None = None
    apply_status: Literal["not_applied", "not_applicable", "unknown"] = "unknown"
    artifacts: tuple[OutcomeArtifactRef, ...] = Field(default=(), max_length=64)
    verified_artifact_count: int = Field(default=0, strict=True, ge=0, le=256)
    usage: tuple[OutcomeUsage, ...] = Field(default=(), max_length=1)
    durable_released_leases: int = Field(default=0, strict=True, ge=0, le=4096)
    durable_outstanding_leases: int = Field(default=0, strict=True, ge=0, le=4096)
    physical_cleanup: Literal["not_checked"] = "not_checked"
    evidence_issue: Literal["evidence_invalid"] | None = None
    execution_authorized: Literal[False] = False

    @field_validator("execution_authorized", mode="before")
    @classmethod
    def exact_false(cls, value: object) -> object:
        if type(value) is not bool:
            raise ValueError("execution authorization must be an exact boolean")
        return value

    @property
    def sha256(self) -> str:
        return canonical_json_hash(self.model_dump(mode="json"))

    @model_validator(mode="after")
    def coherent(self) -> EvaluationObservation:
        if len(self.model_dump_json().encode("utf-8")) > 1_048_576:
            raise ValueError("observation exceeds its fixed bound")
        if (self.state == "corrupt") != (self.evidence_issue is not None):
            raise ValueError("corrupt observations require a fixed issue category")
        if self.terminal_result is not None and (
            self.state not in {"failed", "cancelled", "dispatch_unknown"}
            or self.root_run_id is None
            or self.persisted_sha256 is None
        ):
            raise ValueError("only a bound ended execution can be finalized")
        if self.task_id is not None and self.root_run_id is None:
            raise ValueError("a Task requires its actual Run")
        if any(ref.run_id != self.root_run_id for ref in self.artifacts):
            raise ValueError("artifact references must belong to the observed root")
        return self
