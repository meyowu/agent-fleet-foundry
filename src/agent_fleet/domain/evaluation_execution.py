"""Immutable reserved execution identities, not an execution-capable evaluator."""

from __future__ import annotations

from datetime import datetime
from pathlib import PurePosixPath
from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, field_validator, model_validator

from agent_fleet.domain.budgets import RunBudgetLimits
from agent_fleet.domain.evaluation import (
    CampaignId,
    CaseId,
    EvaluationCommand,
    EvaluationModel,
    require_utc,
)
from agent_fleet.domain.models import CorrelationId, ImageIdentity, ProjectId, Run, RunId, Sha256
from agent_fleet.domain.outcomes import AttemptId
from agent_fleet.domain.security import canonical_json_hash

SourcePath = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=4096)]
CommitId = Annotated[str, StringConstraints(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")]
DEPENDENCY_NAMES = frozenset(
    {
        "pyproject.toml",
        "uv.lock",
        "poetry.lock",
        "Pipfile",
        "Pipfile.lock",
        "requirements.txt",
        "requirements-dev.txt",
        "package.json",
        "package-lock.json",
        "npm-shrinkwrap.json",
        "pnpm-lock.yaml",
        "yarn.lock",
    }
)


class SourceEntry(EvaluationModel):
    path: SourcePath
    mode: Literal["100644", "100755"]
    sha256: Sha256

    @field_validator("path")
    @classmethod
    def canonical_path(cls, value: str) -> str:
        parts = value.split("/")
        if (
            value.startswith("/")
            or "\\" in value
            or any(part in {"", ".", ".."} or part.casefold() == ".git" for part in parts)
            or any(ord(char) < 32 or ord(char) == 127 for char in value)
        ):
            raise ValueError("source path is not canonical")
        value.encode("utf-8")
        return value


class CommittedSource(EvaluationModel):
    schema_version: Literal[1] = 1
    commit_sha: CommitId
    entries: tuple[SourceEntry, ...] = Field(max_length=4096)

    @model_validator(mode="after")
    def bounded_tree(self) -> Self:
        paths = [entry.path for entry in self.entries]
        if paths != sorted(paths) or len({path.casefold() for path in paths}) != len(paths):
            raise ValueError("source entries must be unique and sorted")
        if len(self.model_dump_json().encode()) > 1_048_576:
            raise ValueError("source descriptor exceeds its bound")
        return self

    @property
    def source_sha256(self) -> str:
        return canonical_json_hash(
            {
                "schema_version": 1,
                "entries": [entry.model_dump(mode="json") for entry in self.entries],
            }
        )

    @property
    def dependencies_sha256(self) -> str:
        return canonical_json_hash(
            {
                "schema_version": 1,
                "recipe": "committed-declarations-v1",
                "entries": [
                    entry.model_dump(mode="json")
                    for entry in self.entries
                    if PurePosixPath(entry.path).name in DEPENDENCY_NAMES
                ],
            }
        )


class EvaluationSubmission(EvaluationModel):
    campaign_id: CampaignId
    manifest_sha256: Sha256
    case_id: CaseId
    repetition: int = Field(strict=True, ge=0, le=2)
    attempt_id: AttemptId


class EvaluationAdmission(EvaluationModel):
    source: CommittedSource
    configuration_sha256: Sha256
    commands: tuple[EvaluationCommand, ...] = Field(max_length=32)


class EvaluationExecutionBinding(EvaluationModel):
    submission: EvaluationSubmission
    project_id: ProjectId
    repository_identity: Sha256
    root_run_id: RunId
    run_binding_sha256: Sha256
    case_sha256: Sha256
    source_sha256: Sha256
    commit_sha: CommitId
    configuration_sha256: Sha256
    model_bindings_sha256: Sha256
    image_identity: ImageIdentity | None
    dependencies_sha256: Sha256
    commands: tuple[EvaluationCommand, ...] = Field(max_length=32)
    limits: RunBudgetLimits
    admitted_at: datetime

    _utc = field_validator("admitted_at")(require_utc)

    @property
    def sha256(self) -> str:
        return canonical_json_hash(self.model_dump(mode="json"))


class EvaluationClaim(EvaluationModel):
    root_run_id: RunId
    binding_sha256: Sha256
    claim_id: CorrelationId


class EvaluationExecutionRecord(EvaluationModel):
    binding: EvaluationExecutionBinding
    claim: EvaluationClaim
    status: Literal["active", "settled", "fenced"] = "active"
    revision: int = Field(default=1, strict=True, ge=1, le=3)
    updated_at: datetime

    _utc = field_validator("updated_at")(require_utc)

    @model_validator(mode="after")
    def identity(self) -> Self:
        if (
            self.claim.root_run_id != self.binding.root_run_id
            or self.claim.binding_sha256 != self.binding.sha256
            or self.updated_at < self.binding.admitted_at
            or (self.status == "active") != (self.revision == 1)
        ):
            raise ValueError("execution claim identity is inconsistent")
        return self


class EvaluationRegistration(EvaluationModel):
    record: EvaluationExecutionRecord
    claim: EvaluationClaim | None = None


def run_execution_hash(run: Run) -> str:
    """Only admission-time identity: task/results/lifecycle legitimately evolve."""
    fields = {
        "run_id",
        "project_id",
        "correlation_id",
        "parent_run_id",
        "goal",
        "base_revision",
        "target_status_fingerprint",
        "runtime_name",
        "provider_model",
        "credential_ref",
        "model_bindings_sha256",
        "sandbox_name",
        "sandbox_configuration",
        "sandbox_configuration_hash",
        "sandbox_requirements",
        "sandbox_capabilities_snapshot",
        "sandbox_capabilities_hash",
        "sandbox_image_identity",
        "sandbox_daemon_identity",
        "unsafe_local_confirmed",
        "fake_scenario",
        "config_snapshot_hash",
        "max_repair_iterations",
        "plan_review_required",
        "created_at",
    }
    return canonical_json_hash(run.model_dump(mode="json", include=fields))
