"""Exact pre-execution plan decisions, independent of command permissions."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from agent_fleet.domain.evolution import OrganizationAdmission
from agent_fleet.domain.models import (
    ArtifactId,
    FrozenStrictModel,
    ProjectId,
    Run,
    RunId,
    Sha256,
    TaskId,
)
from agent_fleet.domain.security import canonical_json_hash


def plan_review_run_sha256(run: Run) -> str:
    """Hash immutable execution authority, not later lifecycle/evidence updates."""
    fields = {
        "run_id",
        "project_id",
        "correlation_id",
        "parent_run_id",
        "parent_plan_sha256",
        "parent_node_id",
        "parent_iteration",
        "goal",
        "plan_review_required",
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
        "task_id",
        "task_spec_artifact_id",
        "task_spec_hash",
        "config_snapshot_artifact_id",
        "config_snapshot_hash",
        "fleet_plan_artifact_id",
        "fleet_plan_hash",
        "fleet_strategy",
        "max_repair_iterations",
        "created_at",
    }
    return canonical_json_hash(run.model_dump(mode="json", include=fields))


class PlanReviewBinding(FrozenStrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    root_run_id: RunId
    project_id: ProjectId
    task_id: TaskId
    run_sha256: Sha256
    task_spec_artifact_id: ArtifactId
    task_spec_sha256: Sha256
    fleet_plan_artifact_id: ArtifactId
    fleet_plan_sha256: Sha256
    config_snapshot_artifact_id: ArtifactId
    config_snapshot_sha256: Sha256
    repository_root: str = Field(min_length=1, max_length=4096)
    repository_identity: Sha256
    base_revision: str = Field(min_length=1, max_length=256)
    target_status_fingerprint: Sha256
    organization_admission: OrganizationAdmission
    model_bindings_sha256: Sha256 | None = None

    @model_validator(mode="after")
    def admitted_configuration(self) -> PlanReviewBinding:
        if (
            self.organization_admission.project_id != self.project_id
            or self.organization_admission.config_snapshot_sha256 != self.config_snapshot_sha256
        ):
            raise ValueError("plan review requires its exact organization admission")
        return self


class PlanReviewCheckpoint(FrozenStrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    schema_version: Literal[1] = 1
    binding: PlanReviewBinding
    revision: int = Field(ge=1, le=3, strict=True)
    status: Literal["pending", "approved", "consumed"]
    previous_sha256: Sha256 | None = None
    actor: Literal["user"] | None = None
    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at")
    @classmethod
    def utc_timestamp(cls, value: datetime) -> datetime:
        if value.utcoffset() != timedelta(0):
            raise ValueError("plan review timestamps require UTC")
        return value

    @model_validator(mode="after")
    def monotonic_decision(self) -> PlanReviewCheckpoint:
        if (
            self.revision != {"pending": 1, "approved": 2, "consumed": 3}[self.status]
            or (self.previous_sha256 is None) != (self.revision == 1)
            or (self.actor is None) != (self.revision == 1)
            or self.updated_at < self.created_at
            or (self.revision == 1 and self.updated_at != self.created_at)
        ):
            raise ValueError("plan review requires exact monotonic decision history")
        return self

    @property
    def binding_sha256(self) -> str:
        return canonical_json_hash(self.binding.model_dump(mode="json"))

    @property
    def checkpoint_sha256(self) -> str:
        return canonical_json_hash(self.model_dump(mode="json"))

    def safe_projection(self) -> dict[str, object]:
        """No repository content, model references or credential values in public output."""
        return {
            "root_run_id": self.binding.root_run_id,
            "project_id": self.binding.project_id,
            "task_id": self.binding.task_id,
            "revision": self.revision,
            "status": self.status,
            "checkpoint_sha256": self.checkpoint_sha256,
            "binding_sha256": self.binding_sha256,
            "task_spec_sha256": self.binding.task_spec_sha256,
            "fleet_plan_sha256": self.binding.fleet_plan_sha256,
            "config_snapshot_sha256": self.binding.config_snapshot_sha256,
            "model_bindings_sha256": self.binding.model_bindings_sha256,
            "organization_revision": self.binding.organization_admission.revision,
            "actor": self.actor,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
