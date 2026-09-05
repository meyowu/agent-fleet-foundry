"""Trusted graph persistence: metadata CAS is never external-effect replay authority."""

from typing import Protocol

from agent_fleet.domain.errors import ErrorCode
from agent_fleet.domain.fleet_plan import FleetPlan
from agent_fleet.domain.graph import (
    GraphArtifactRef,
    GraphChildBinding,
    GraphChildSeed,
    GraphDriverClaim,
    GraphJoinCompletion,
    GraphJoinPreparation,
    GraphNodeRecord,
    GraphNodeStatus,
    GraphSnapshot,
    GraphStatus,
)


class GraphStore(Protocol):
    def initialize(
        self, parent_run_id: str, plan: FleetPlan, children: tuple[GraphChildSeed, ...]
    ) -> GraphSnapshot: ...

    def get(self, parent_run_id: str) -> GraphSnapshot | None: ...

    def child_binding(self, child_run_id: str) -> GraphChildBinding | None: ...

    def descendants(self, parent_run_id: str) -> tuple[GraphChildBinding, ...]: ...

    def claim_driver(self, parent_run_id: str, *, expected_revision: int) -> GraphDriverClaim: ...

    def claim_continuation(
        self, parent_run_id: str, *, expected_revision: int
    ) -> GraphDriverClaim: ...

    def transition_node(
        self,
        claim: GraphDriverClaim,
        node_id: str,
        iteration: int,
        *,
        expected_revision: int,
        target: GraphNodeStatus,
        input_artifacts: tuple[GraphArtifactRef, ...] = (),
        output_artifacts: tuple[GraphArtifactRef, ...] = (),
        error_code: ErrorCode | None = None,
    ) -> GraphNodeRecord: ...

    def release_driver(
        self, claim: GraphDriverClaim, *, expected_revision: int, status: GraphStatus
    ) -> GraphSnapshot: ...

    def mark_join_prepared(
        self,
        claim: GraphDriverClaim,
        receipt: GraphJoinPreparation,
        *,
        expected_revision: int,
    ) -> GraphSnapshot: ...

    def mark_join_complete(
        self,
        claim: GraphDriverClaim,
        result: GraphJoinCompletion,
        *,
        expected_revision: int,
    ) -> GraphSnapshot: ...

    def request_cancel(self, parent_run_id: str, *, expected_revision: int) -> GraphSnapshot: ...
