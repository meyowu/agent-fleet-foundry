"""Immutable preregistration contracts; parser limits are not execution authority."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from agent_fleet.domain.models import ActionId, ImageIdentity, Sha256
from agent_fleet.domain.security import canonical_json_hash

EvaluationId = Annotated[str, StringConstraints(pattern=r"^eval_[0-9a-f]{32}$")]
CampaignId = Annotated[str, StringConstraints(pattern=r"^campaign_[0-9a-f]{32}$")]
CaseId = Annotated[
    str, StringConstraints(min_length=1, max_length=100, pattern=r"^[a-z][a-z0-9_-]*$")
]
RepositoryId = Annotated[
    str, StringConstraints(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_-]*$")
]
EvidenceCategory = Literal[
    "source_baseline",
    "patch",
    "verification",
    "apply",
    "post_apply",
    "oracle",
    "cleanup",
    "answer",
    "diagnostic",
]
Cohort = Literal["development", "sealed_holdout", "auxiliary"]
MAX_MANIFEST_BYTES = 1_048_576
_CODE_EVIDENCE = frozenset(
    {"source_baseline", "patch", "verification", "apply", "post_apply", "oracle", "cleanup"}
)
_READ_EVIDENCE = frozenset({"source_baseline", "answer", "oracle", "cleanup"})


class EvaluationModel(BaseModel):
    """All descendants contain only immutable scalars, tuples and frozen models."""

    model_config = ConfigDict(
        extra="forbid", frozen=True, strict=True, revalidate_instances="always"
    )


def require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("evaluation timestamps must use UTC")
    # Never retain a caller-owned mutable tzinfo (or datetime subclass).
    return datetime(
        value.year,
        value.month,
        value.day,
        value.hour,
        value.minute,
        value.second,
        value.microsecond,
        tzinfo=UTC,
    )


class EvaluationRunBudget(EvaluationModel):
    max_agent_invocations: int = Field(strict=True, ge=1, le=10_000)
    max_model_requests: int = Field(strict=True, ge=1, le=100_000)
    max_tool_calls: int = Field(strict=True, ge=0, le=100_000)
    max_total_tokens: int = Field(strict=True, ge=1, le=100_000_000)
    max_active_seconds: int = Field(strict=True, ge=1, le=86_400)


class EvaluationCampaignBudget(EvaluationRunBudget):
    max_attempts: int = Field(strict=True, ge=1, le=256)


class EvaluationRepository(EvaluationModel):
    repository_id: RepositoryId
    source_sha256: Sha256
    commit_sha: Annotated[str, StringConstraints(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")]
    cohort: Cohort


class EvaluationCommand(EvaluationModel):
    command_id: ActionId
    sha256: Sha256


class EvaluationCase(EvaluationModel):
    case_id: CaseId
    repository_id: RepositoryId
    task_kind: Literal["code_change", "read_only"]
    requirement: str = Field(min_length=1, max_length=8192)
    allowed_paths: tuple[Annotated[str, StringConstraints(min_length=1, max_length=4096)], ...] = (
        Field(max_length=128)
    )
    required_evidence: tuple[EvidenceCategory, ...] = Field(min_length=1, max_length=9)
    oracle_sha256: Sha256
    scoring_sha256: Sha256
    commands: tuple[EvaluationCommand, ...] = Field(max_length=32)
    image_identity: ImageIdentity | None
    dependencies_sha256: Sha256
    profile_id: ActionId
    profile_revision: int = Field(strict=True, ge=0, le=2**63 - 1)
    profile_sha256: Sha256
    configuration_sha256: Sha256
    run_budget: EvaluationRunBudget
    auxiliary_purpose: Literal["provider_canary", "cold_start", "safety"] | None = None

    @model_validator(mode="after")
    def coherent(self) -> EvaluationCase:
        if not self.requirement.strip():
            raise ValueError("evaluation requirement cannot be blank")
        for value in self.allowed_paths:
            path = PurePosixPath(value)
            if (
                path.is_absolute()
                or path.as_posix() != value
                or ".." in path.parts
                or not path.parts
                or "\\" in value
                or any(ord(char) < 32 or ord(char) == 127 for char in value)
            ):
                raise ValueError("evaluation paths must be canonical repository-relative paths")
        if len({path.casefold() for path in self.allowed_paths}) != len(self.allowed_paths):
            raise ValueError("evaluation paths must be case-insensitively unique")
        if len(set(self.required_evidence)) != len(self.required_evidence):
            raise ValueError("evaluation evidence categories must be unique")
        if len({command.command_id for command in self.commands}) != len(self.commands):
            raise ValueError("evaluation command IDs must be unique")
        required = _CODE_EVIDENCE if self.task_kind == "code_change" else _READ_EVIDENCE
        if not required.issubset(self.required_evidence):
            raise ValueError("evaluation success contract lacks required evidence categories")
        if self.task_kind == "code_change" and (not self.commands or not self.allowed_paths):
            raise ValueError("code-change evaluation needs command and path contracts")
        if self.task_kind == "read_only" and {"patch", "apply", "post_apply"}.intersection(
            self.required_evidence
        ):
            raise ValueError("read-only evaluation cannot require patch application")
        return self


class EvaluationSlot(EvaluationModel):
    case_id: CaseId
    repetition: int = Field(strict=True, ge=0, le=2)


class EvaluationManifest(EvaluationModel):
    schema_version: int = Field(default=1, strict=True, ge=1, le=1)
    manifest_id: EvaluationId
    campaign_id: CampaignId
    revision: int = Field(strict=True, ge=0, le=2**63 - 1)
    previous_sha256: Sha256 | None = None
    frozen_at: datetime
    repositories: tuple[EvaluationRepository, ...] = Field(min_length=1, max_length=16)
    cases: tuple[EvaluationCase, ...] = Field(min_length=1, max_length=64)
    slots: tuple[EvaluationSlot, ...] = Field(min_length=1, max_length=256)
    budget: EvaluationCampaignBudget

    _utc = field_validator("frozen_at")(require_utc)

    @property
    def sha256(self) -> str:
        return canonical_json_hash(self.model_dump(mode="json"))

    @model_validator(mode="after")
    def frozen_contract(self) -> EvaluationManifest:
        if (self.revision == 0) != (self.previous_sha256 is None):
            raise ValueError("manifest revision must bind its predecessor")
        repos = {repo.repository_id: repo for repo in self.repositories}
        cases = {case.case_id: case for case in self.cases}
        if len(repos) != len(self.repositories) or len(cases) != len(self.cases):
            raise ValueError("manifest repository and case IDs must be unique")
        source_splits: dict[str, set[str]] = {}
        for repo in self.repositories:
            source_splits.setdefault(repo.source_sha256, set()).add(repo.cohort)
        if any(
            {"development", "sealed_holdout"}.issubset(splits) for splits in source_splits.values()
        ):
            raise ValueError("the same source cannot appear in development and sealed holdout")
        if len(
            {(repo.source_sha256, repo.commit_sha, repo.cohort) for repo in self.repositories}
        ) != len(repos):
            raise ValueError("repository aliases cannot duplicate a source revision and cohort")
        for case in self.cases:
            if case.repository_id not in repos:
                raise ValueError("evaluation case refers to an undeclared repository")
            if repos[case.repository_id].cohort == "auxiliary" and case.auxiliary_purpose is None:
                raise ValueError("auxiliary repositories cannot contribute cohort tasks")
            for name, value in case.run_budget.model_dump().items():
                if value > getattr(self.budget, name):
                    raise ValueError("case budget exceeds the frozen campaign ceiling")
        registered: dict[str, list[int]] = {case_id: [] for case_id in cases}
        for slot in self.slots:
            if slot.case_id not in cases:
                raise ValueError("evaluation slot refers to an undeclared case")
            registered[slot.case_id].append(slot.repetition)
        for case_id, repetitions in registered.items():
            if sorted(repetitions) != list(range(len(repetitions))) or not repetitions:
                raise ValueError("case attempts must be unique contiguous slots beginning at zero")
            if cases[case_id].auxiliary_purpose is not None and repetitions != [0]:
                raise ValueError("auxiliary attempts must have their own case and single slot")
        if self.budget.max_attempts != len(self.slots):
            raise ValueError("campaign attempt ceiling must match preregistered slots")
        encoded = json.dumps(
            self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
        if len(encoded) > MAX_MANIFEST_BYTES:
            raise ValueError("evaluation manifest exceeds its encoded byte limit")
        return self
