"""Read back exact graph provenance before admitting a parent delivery."""

from __future__ import annotations

from agent_fleet.application.artifacts import ArtifactService
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.evidence import (
    CleanupLeaseRecord,
    GraphDeliveryEvidence,
    ResourceCleanupReceipt,
)
from agent_fleet.domain.fleet_plan import FleetPlan
from agent_fleet.domain.graph import (
    GraphArtifactRef,
    GraphJoinPreparation,
    GraphNodeStatus,
    GraphStatus,
)
from agent_fleet.domain.models import ArtifactKind, Run, RunStatus, TaskSpec, WorkflowStage
from agent_fleet.ports.graph import GraphStore
from agent_fleet.ports.state_store import StateStore


def assemble_graph_delivery(
    state: StateStore,
    artifacts: ArtifactService,
    graphs: GraphStore,
    run: Run,
    task: TaskSpec,
    plan: FleetPlan,
) -> tuple[GraphDeliveryEvidence, set[str]]:
    graph = graphs.get(run.run_id)
    if (
        graph is None
        or graph.status is not GraphStatus.JOINED
        or graph.driver_claim is not None
        or graph.cancel_requested_at is not None
        or graph.plan != plan
        or graph.plan_sha256 != run.fleet_plan_hash
        or graph.parent_task_id != task.task_id
        or graph.join_preparation is None
        or graph.join_completion is None
    ):
        raise _invalid()
    prepared = graph.join_preparation
    completed = graph.join_completion
    if (
        prepared.config_snapshot_sha256 != task.config_snapshot_hash
        or prepared.base_revision != run.base_revision
        or prepared.parent_run_id != run.run_id
        or prepared.parent_task_id != task.task_id
    ):
        raise _invalid()
    joins = [
        item for item in state.list_artifacts(run.run_id) if item.kind is ArtifactKind.GRAPH_JOIN
    ]
    if len(joins) != 1:
        raise _invalid()
    join = joins[0]
    if join.task_id != task.task_id or join.project_id != run.project_id:
        raise _invalid()
    try:
        parsed = GraphJoinPreparation.model_validate_json(artifacts.read_text(join.artifact_id))
    except ValueError:
        raise _invalid() from None
    if parsed != prepared:
        raise _invalid()
    patch = state.get_artifact(completed.parent_patch_artifact_id)
    if (
        patch.kind is not ArtifactKind.PATCH
        or patch.run_id != run.run_id
        or patch.task_id != task.task_id
        or patch.project_id != run.project_id
        or patch.sha256 != completed.parent_patch_sha256
    ):
        raise _invalid()
    artifacts.read_text(patch.artifact_id)
    if not run.repair_iterations and (
        run.patch_artifact_id != patch.artifact_id or run.patch_sha256 != patch.sha256
    ):
        raise _invalid()
    repairs = [
        event
        for event in state.list_events(run.run_id)
        if event.event_type == "graph.repair_fallback"
    ]
    if [event.payload.get("iteration") for event in repairs] != list(
        range(1, run.repair_iterations + 1)
    ) or any(event.payload.get("mode") != "sequential_parent_engineer" for event in repairs):
        raise _invalid()
    authoritative_ids = {join.artifact_id, patch.artifact_id}
    receipts: list[ResourceCleanupReceipt] = []
    for node in graph.nodes:
        binding = node.binding
        child = state.get_run(binding.child_run_id)
        if (
            graphs.child_binding(child.run_id) != binding
            or node.status is not GraphNodeStatus.SUCCEEDED
            or child.status is not RunStatus.COMPLETED
            or child.stage is not WorkflowStage.PRESENTING
            or child.task_id != binding.child_task_id
            or child.verified_complete
            or child.evidence_bundle_artifact_id is not None
            or state.outstanding_leases(child.run_id)
        ):
            raise _invalid()
        cleanup = [
            ref for ref in node.output_artifacts if ref.kind is ArtifactKind.RESOURCE_CLEANUP
        ]
        if len(cleanup) != 1 or (
            cleanup[0].artifact_id != child.cleanup_receipt_artifact_id
            or cleanup[0].sha256 != child.cleanup_receipt_sha256
        ):
            raise _invalid()
        for ref in node.output_artifacts:
            metadata = state.get_artifact(ref.artifact_id)
            if (
                metadata.run_id != child.run_id
                or ref.run_id != child.run_id
                or metadata.project_id != run.project_id
                or metadata.task_id != child.task_id
                or metadata.kind is not ref.kind
                or metadata.sha256 != ref.sha256
            ):
                raise _invalid()
            artifacts.read_text(ref.artifact_id)
            authoritative_ids.add(ref.artifact_id)
        try:
            receipt = ResourceCleanupReceipt.model_validate_json(
                artifacts.read_text(cleanup[0].artifact_id)
            )
        except ValueError:
            raise _invalid() from None
        records = [
            CleanupLeaseRecord(
                lease_id=item.lease_id,
                kind=item.kind,
                resource_id=item.resource_id,
                status=item.status,
            )
            for item in state.list_leases(child.run_id)
        ]
        if receipt.run_id != child.run_id or not receipt.complete or receipt.leases != records:
            raise _invalid()
        receipts.append(receipt)
    return GraphDeliveryEvidence(
        snapshot=graph,
        join_artifact=GraphArtifactRef(
            artifact_id=join.artifact_id, sha256=join.sha256, run_id=run.run_id, kind=join.kind
        ),
        child_cleanup_receipts=tuple(receipts),
        sequential_repair_iterations=run.repair_iterations,
    ), authoritative_ids


def _invalid() -> FleetError:
    return FleetError(
        ErrorCode.ARTIFACT_INTEGRITY_FAILED,
        "Adaptive graph delivery does not match its exact persisted provenance.",
        "Inspect parent and child artifacts; incomplete graph evidence cannot authorize delivery.",
    )
