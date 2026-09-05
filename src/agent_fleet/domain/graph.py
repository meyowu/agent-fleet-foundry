"""Immutable identities and bounded durable adaptive-graph receipts."""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from typing import Literal

from pydantic import Field, field_validator, model_validator

from agent_fleet.domain.errors import ErrorCode
from agent_fleet.domain.fleet_plan import FleetPlan, FleetPlanNode, NodeId
from agent_fleet.domain.models import (
    ArtifactId,
    ArtifactKind,
    CorrelationId,
    FleetPlanId,
    FrozenStrictModel,
    ProjectId,
    Run,
    RunId,
    Sha256,
    TaskId,
    TaskSpec,
    WorkspaceId,
)
from agent_fleet.domain.security import canonical_json_hash


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("graph timestamps must be timezone-aware UTC")
    return value


class GraphStatus(StrEnum):
    READY = "ready"
    RUNNING = "running"
    PAUSED = "paused"
    JOINED = "joined"
    FAILED = "failed"
    CANCELLED = "cancelled"


class GraphNodeStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class GraphChildSeed(FrozenStrictModel):
    node_id: NodeId
    iteration: Literal[0] = 0
    run: Run
    task: TaskSpec


class GraphChildBinding(FrozenStrictModel):
    project_id: ProjectId
    parent_run_id: RunId
    plan_sha256: Sha256
    node_id: NodeId
    iteration: Literal[0] = 0
    child_run_id: RunId
    child_task_id: TaskId
    node_sha256: Sha256
    task_sha256: Sha256
    run_binding_sha256: Sha256
    created_at: datetime

    _created_utc = field_validator("created_at")(_utc)

    @model_validator(mode="after")
    def validate_identity(self) -> GraphChildBinding:
        if self.parent_run_id == self.child_run_id:
            raise ValueError("a graph child cannot be its parent")
        return self


class GraphDriverClaim(FrozenStrictModel):
    parent_run_id: RunId
    plan_sha256: Sha256
    claim_id: CorrelationId
    generation: int = Field(ge=1, strict=True)
    claimed_at: datetime

    _claimed_utc = field_validator("claimed_at")(_utc)


class GraphArtifactRef(FrozenStrictModel):
    artifact_id: ArtifactId
    sha256: Sha256
    run_id: RunId
    kind: ArtifactKind


class GraphNodeRecord(FrozenStrictModel):
    binding: GraphChildBinding
    node: FleetPlanNode
    status: GraphNodeStatus = GraphNodeStatus.PENDING
    revision: int = Field(default=0, ge=0, strict=True)
    input_artifacts: tuple[GraphArtifactRef, ...] = Field(default=(), max_length=64)
    output_artifacts: tuple[GraphArtifactRef, ...] = Field(default=(), max_length=64)
    error_code: ErrorCode | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    updated_at: datetime

    _updated_utc = field_validator("updated_at")(_utc)
    _optional_utc = field_validator("started_at", "finished_at")(
        lambda value: _utc(value) if value is not None else None
    )

    @model_validator(mode="after")
    def validate_record(self) -> GraphNodeRecord:
        if self.node.node_id != self.binding.node_id or self.node.independent_verifier:
            raise ValueError("graph child node identity is inconsistent")
        if canonical_json_hash(self.node.model_dump(mode="json")) != self.binding.node_sha256:
            raise ValueError("graph child node hash is inconsistent")
        for refs in (self.input_artifacts, self.output_artifacts):
            if len({item.artifact_id for item in refs}) != len(refs):
                raise ValueError("graph artifact references must be unique")
        if self.status is GraphNodeStatus.PENDING and self.started_at is not None:
            raise ValueError("pending node cannot have dispatched")
        if self.status in {GraphNodeStatus.RUNNING, GraphNodeStatus.WAITING_APPROVAL} and (
            self.started_at is None or self.finished_at is not None
        ):
            raise ValueError("active node lifecycle is inconsistent")
        if self.status is GraphNodeStatus.SUCCEEDED and (
            not self.output_artifacts or self.started_at is None or self.finished_at is None
        ):
            raise ValueError("successful node requires frozen output and lifecycle evidence")
        if (
            self.finished_at is not None
            and self.started_at is not None
            and self.finished_at < self.started_at
        ):
            raise ValueError("node completion precedes dispatch")
        return self


class GraphJoinInput(FrozenStrictModel):
    node_id: NodeId
    child_run_id: RunId
    child_task_id: TaskId
    patch_artifact_id: ArtifactId
    patch_sha256: Sha256
    report_artifact_id: ArtifactId
    report_sha256: Sha256


class GraphJoinPreparation(FrozenStrictModel):
    parent_run_id: RunId
    parent_task_id: TaskId
    config_snapshot_sha256: Sha256
    plan_sha256: Sha256
    iteration: Literal[0] = 0
    base_revision: str = Field(min_length=1, max_length=256)
    ordered_inputs: tuple[GraphJoinInput, ...] = Field(min_length=1, max_length=16)
    created_at: datetime

    _created_utc = field_validator("created_at")(_utc)

    @model_validator(mode="after")
    def validate_order(self) -> GraphJoinPreparation:
        ids = [item.node_id for item in self.ordered_inputs]
        if ids != sorted(set(ids)):
            raise ValueError("join inputs must be unique and sorted by node ID")
        if len({item.child_run_id for item in self.ordered_inputs}) != len(ids):
            raise ValueError("join child identities must be unique")
        return self

    @property
    def preparation_sha256(self) -> str:
        return canonical_json_hash(self.model_dump(mode="json"))


class GraphJoinCompletion(FrozenStrictModel):
    preparation_sha256: Sha256
    parent_patch_artifact_id: ArtifactId
    parent_patch_sha256: Sha256
    workspace_id: WorkspaceId
    created_at: datetime

    _created_utc = field_validator("created_at")(_utc)


class GraphSnapshot(FrozenStrictModel):
    api_version: Literal["agentfleet.dev/v1alpha1"] = "agentfleet.dev/v1alpha1"
    kind: Literal["GraphSnapshot"] = "GraphSnapshot"
    project_id: ProjectId
    parent_run_id: RunId
    parent_task_id: TaskId
    plan_id: FleetPlanId
    plan_artifact_id: ArtifactId
    plan_sha256: Sha256
    plan: FleetPlan
    status: GraphStatus = GraphStatus.READY
    revision: int = Field(default=0, ge=0, strict=True)
    driver_generation: int = Field(default=0, ge=0, strict=True)
    driver_claim: GraphDriverClaim | None = None
    nodes: tuple[GraphNodeRecord, ...] = Field(min_length=1, max_length=16)
    join_preparation: GraphJoinPreparation | None = None
    join_completion: GraphJoinCompletion | None = None
    cancel_requested_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    _dates_utc = field_validator("created_at", "updated_at")(_utc)
    _cancel_utc = field_validator("cancel_requested_at")(
        lambda value: _utc(value) if value is not None else None
    )

    @model_validator(mode="after")
    def validate_snapshot(self) -> GraphSnapshot:
        if (self.plan.plan_id, self.plan.run_id, self.plan.task_id) != (
            self.plan_id,
            self.parent_run_id,
            self.parent_task_id,
        ):
            raise ValueError("graph plan identity is inconsistent")
        expected = {node.node_id: node for node in self.plan.nodes if not node.independent_verifier}
        if set(expected) != {item.binding.node_id for item in self.nodes} or len(expected) != len(
            self.nodes
        ):
            raise ValueError("graph must bind every non-verifier node exactly once")
        for item in self.nodes:
            if item.node != expected[item.binding.node_id]:
                raise ValueError("graph child node must exactly match its frozen plan node")
            if (item.binding.parent_run_id, item.binding.project_id, item.binding.plan_sha256) != (
                self.parent_run_id,
                self.project_id,
                self.plan_sha256,
            ):
                raise ValueError("graph child parent identity is inconsistent")
        if self.driver_claim is not None and (
            self.driver_claim.parent_run_id != self.parent_run_id
            or self.driver_claim.plan_sha256 != self.plan_sha256
            or self.driver_claim.generation != self.driver_generation
        ):
            raise ValueError("graph driver identity is inconsistent")
        if self.status is GraphStatus.RUNNING and self.driver_claim is None:
            raise ValueError("running graph requires a durable driver")
        if self.join_completion is not None and (
            self.join_preparation is None
            or self.join_completion.preparation_sha256 != self.join_preparation.preparation_sha256
        ):
            raise ValueError("join completion requires its exact preparation")
        if self.status is GraphStatus.JOINED and self.join_completion is None:
            raise ValueError("joined graph requires a completion receipt")
        if self.status is GraphStatus.CANCELLED and self.cancel_requested_at is None:
            raise ValueError("cancelled graph requires its durable fence")
        return self
