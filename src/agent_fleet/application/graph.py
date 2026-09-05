"""Bounded adaptive scheduling; models never own graph or join authority."""

from __future__ import annotations

import asyncio
import math
from contextlib import suppress
from typing import Protocol

from agent_fleet.domain.errors import ErrorCode, FleetError, GraphOwnershipUnavailableError
from agent_fleet.domain.graph import (
    GraphArtifactRef,
    GraphDriverClaim,
    GraphJoinCompletion,
    GraphJoinInput,
    GraphJoinPreparation,
    GraphNodeRecord,
    GraphNodeStatus,
    GraphSnapshot,
    GraphStatus,
)
from agent_fleet.domain.models import (
    ApprovalRequest,
    ApprovalStatus,
    ArtifactKind,
    ArtifactMetadata,
    LeaseKind,
    LeaseStatus,
    Run,
    RunStatus,
    WorkflowStage,
    WorkspaceKind,
)
from agent_fleet.ports.clock import Clock
from agent_fleet.ports.graph import GraphStore
from agent_fleet.ports.state_store import StateStore

_WATCH_INTERVAL_SECONDS = 0.25
_REPORT_KINDS = {ArtifactKind.IMPLEMENTATION_REPORT, ArtifactKind.SPECIALIST_REPORT}
_FAILED_NODES = {GraphNodeStatus.FAILED, GraphNodeStatus.BLOCKED, GraphNodeStatus.CANCELLED}


class GraphExecutionHooks(Protocol):
    """Trusted workflow operations; none may recursively call public start/resume."""

    async def prepare_graph_child(
        self, parent: Run, node: GraphNodeRecord, dependency_refs: tuple[GraphArtifactRef, ...]
    ) -> Run:
        """Bind artifacts/budget only; no resource creation, tool, or model effects."""
        ...

    async def execute_graph_child(self, child: Run) -> Run: ...

    async def join_graph_candidates(
        self, parent: Run, ordered_inputs: tuple[GraphJoinInput, ...]
    ) -> Run: ...

    async def cleanup_graph_children(self, parent: Run) -> None: ...

    def remaining_graph_active_seconds(self, parent_run_id: str) -> float:
        """Live aggregate allowance, including elapsed time of active attempts."""
        ...


class GraphCoordinator:
    def __init__(
        self, graphs: GraphStore, state: StateStore, hooks: GraphExecutionHooks, clock: Clock
    ) -> None:
        self.graphs = graphs
        self.state = state
        self.hooks = hooks
        self.clock = clock

    async def drive(self, parent_run_id: str) -> Run:
        acquired: tuple[Run, GraphDriverClaim | None] | None = None
        with suppress(Exception):
            acquired = self._acquire(parent_run_id)
        if acquired is None:
            # The workflow must distinguish this from an owner's failure: a
            # losing caller cannot fail the parent or clean another driver's work.
            raise GraphOwnershipUnavailableError
        parent, claim = acquired
        if claim is None:
            return parent
        tasks: dict[str, asyncio.Task[Run]] = {}
        failure_code: ErrorCode | None = None
        cancelled = False
        try:
            if parent.status is RunStatus.WAITING_FOR_CHILDREN:
                self._parent_status(parent, RunStatus.RUNNING, "graph.resumed")
            return await self._drive_claimed(claim, tasks)
        except asyncio.CancelledError:
            cancelled = True
        except FleetError as error:
            failure_code = error.code
        except Exception:
            failure_code = ErrorCode.INTERNAL_ERROR

        # Keep both raw harness exceptions and their inspectable context outside
        # the public boundary. Retain cleanup across repeated cancellation.
        cleanup = asyncio.create_task(self._abort(claim, tasks, failure_code, cancelled))
        while not cleanup.done():
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                cancelled = True
            except Exception:
                failure_code = ErrorCode.RECOVERY_REQUIRED
        if not cleanup.cancelled() and cleanup.exception() is not None:
            failure_code = ErrorCode.RECOVERY_REQUIRED
        if cancelled:
            raise asyncio.CancelledError
        raise _failure(failure_code or ErrorCode.INTERNAL_ERROR)

    def _acquire(self, parent_run_id: str) -> tuple[Run, GraphDriverClaim | None]:
        parent = self.state.get_run(parent_run_id)
        graph = self._snapshot(parent_run_id)
        if self.graphs.child_binding(parent_run_id) is not None:
            raise _failure(ErrorCode.RECOVERY_REQUIRED)
        if graph.status is GraphStatus.JOINED:
            if graph.driver_claim is not None:
                raise _failure(ErrorCode.RECOVERY_REQUIRED)
            return parent, None
        if (
            graph.status not in {GraphStatus.READY, GraphStatus.PAUSED}
            or parent.status not in {RunStatus.RUNNING, RunStatus.WAITING_FOR_CHILDREN}
            or parent.stage is not WorkflowStage.IMPLEMENTING
            or parent.pending_approval_id is not None
        ):
            raise _failure(ErrorCode.RECOVERY_REQUIRED)
        claim = self.graphs.claim_driver(parent_run_id, expected_revision=graph.revision)
        return parent, claim

    async def _drive_claimed(
        self, claim: GraphDriverClaim, tasks: dict[str, asyncio.Task[Run]]
    ) -> Run:
        while True:
            graph = self._owned_snapshot(claim)
            parent = self.state.get_run(claim.parent_run_id)
            if parent.status is not RunStatus.RUNNING:
                raise asyncio.CancelledError
            if (
                parent.stage is not WorkflowStage.IMPLEMENTING
                or parent.pending_approval_id is not None
            ):
                raise _failure(ErrorCode.RECOVERY_REQUIRED)
            if any(node.status in _FAILED_NODES for node in graph.nodes):
                raise _failure(ErrorCode.COMMAND_DENIED)
            capacity = graph.plan.max_parallel_agents
            nodes = {node.binding.node_id: node for node in graph.nodes}
            for node in sorted(graph.nodes, key=lambda item: item.binding.node_id):
                if len(tasks) >= capacity:
                    break
                if not self._ready(node, nodes):
                    continue
                self._remaining(claim.parent_run_id)
                inputs = self._dependency_inputs(node, nodes)
                if node.status is GraphNodeStatus.PENDING:
                    # This hook is metadata-only: task/config artifacts and the
                    # shared budget binding precede the durable execution claim.
                    prepared = await self.hooks.prepare_graph_child(
                        parent, node, tuple(ref for ref in inputs if ref.kind in _REPORT_KINDS)
                    )
                    if prepared.run_id != self._child(node).run_id:
                        raise _failure(ErrorCode.RECOVERY_REQUIRED)
                    self._owned_snapshot(claim)
                running = self.graphs.transition_node(
                    claim,
                    node.binding.node_id,
                    node.binding.iteration,
                    expected_revision=node.revision,
                    target=GraphNodeStatus.RUNNING,
                    input_artifacts=inputs,
                )
                tasks[node.binding.node_id] = asyncio.create_task(
                    self.hooks.execute_graph_child(self._child(running))
                )
            if not tasks:
                graph = self._owned_snapshot(claim)
                if all(node.status is GraphNodeStatus.SUCCEEDED for node in graph.nodes):
                    return await self._join(claim, graph)
                if any(node.status is GraphNodeStatus.WAITING_APPROVAL for node in graph.nodes):
                    parent = self.state.get_run(claim.parent_run_id)
                    parent = self._parent_status(
                        parent, RunStatus.WAITING_FOR_CHILDREN, "graph.waiting_for_children"
                    )
                    self.graphs.release_driver(
                        claim, expected_revision=graph.revision, status=GraphStatus.PAUSED
                    )
                    return parent
                raise _failure(ErrorCode.RECOVERY_REQUIRED)

            remaining = self._remaining(claim.parent_run_id)
            done, _ = await asyncio.wait(
                tasks.values(),
                timeout=min(_WATCH_INTERVAL_SECONDS, remaining / len(tasks)),
                return_when=asyncio.FIRST_COMPLETED,
            )
            # Re-read the fence before accepting a result or launching a successor.
            self._owned_snapshot(claim)
            for node_id in sorted(key for key, task in tasks.items() if task in done):
                task = tasks[node_id]
                node = self._node(self._owned_snapshot(claim), node_id)
                error_code: ErrorCode | None = None
                result: Run | None = None
                try:
                    result = task.result()
                except asyncio.CancelledError:
                    raise
                except FleetError as error:
                    error_code = error.code
                except Exception:
                    error_code = ErrorCode.INTERNAL_ERROR
                del tasks[node_id]
                if error_code is not None:
                    self._transition(claim, node, GraphNodeStatus.FAILED, error_code=error_code)
                    raise _failure(error_code)
                if result is None or result.run_id != node.binding.child_run_id:
                    raise _failure(ErrorCode.RECOVERY_REQUIRED)
                self._settle(claim, node)

    def _ready(self, node: GraphNodeRecord, nodes: dict[str, GraphNodeRecord]) -> bool:
        if node.status is GraphNodeStatus.PENDING:
            if any(identifier not in nodes for identifier in node.node.depends_on):
                raise _failure(ErrorCode.RECOVERY_REQUIRED)
            return all(
                nodes[identifier].status is GraphNodeStatus.SUCCEEDED
                for identifier in node.node.depends_on
            )
        if node.status is GraphNodeStatus.WAITING_APPROVAL:
            child = self._child(node)
            if (
                child.status is not RunStatus.PAUSED_FOR_APPROVAL
                or child.pending_approval_id is None
            ):
                raise _failure(ErrorCode.RECOVERY_REQUIRED)
            request = self._approval(child)
            if request.status is ApprovalStatus.DENIED:
                raise _failure(ErrorCode.COMMAND_DENIED)
            return request.status is ApprovalStatus.APPROVED
        return False

    def _dependency_inputs(
        self, node: GraphNodeRecord, nodes: dict[str, GraphNodeRecord]
    ) -> tuple[GraphArtifactRef, ...]:
        if node.status is GraphNodeStatus.WAITING_APPROVAL:
            return node.input_artifacts
        refs: list[GraphArtifactRef] = []
        for identifier in sorted(node.node.depends_on):
            dependency = nodes[identifier]
            for ref in dependency.output_artifacts:
                self._validate_ref(ref, dependency)
                refs.append(ref)
        return tuple(refs)

    def _settle(self, claim: GraphDriverClaim, node: GraphNodeRecord) -> None:
        child = self._child(node)
        if child.status is RunStatus.PAUSED_FOR_APPROVAL:
            if child.pending_approval_id is None:
                raise _failure(ErrorCode.RECOVERY_REQUIRED)
            self._approval(child)
            self._transition(claim, node, GraphNodeStatus.WAITING_APPROVAL)
        elif child.status is RunStatus.COMPLETED:
            outputs = self._outputs(node, child)
            self._transition(claim, node, GraphNodeStatus.SUCCEEDED, output_artifacts=outputs)
        else:
            self._transition(
                claim, node, GraphNodeStatus.FAILED, error_code=ErrorCode.COMMAND_DENIED
            )
            raise _failure(ErrorCode.COMMAND_DENIED)

    def _outputs(self, node: GraphNodeRecord, child: Run) -> tuple[GraphArtifactRef, ...]:
        if (
            child.stage is not WorkflowStage.PRESENTING
            or child.verified_complete
            or child.evidence_bundle_artifact_id is not None
            or self.state.outstanding_leases(child.run_id)
        ):
            raise _failure(ErrorCode.RECOVERY_REQUIRED)
        if child.cleanup_receipt_artifact_id is None or child.cleanup_receipt_sha256 is None:
            raise _failure(ErrorCode.RECOVERY_REQUIRED)
        report_kind = (
            ArtifactKind.IMPLEMENTATION_REPORT
            if node.node.can_write
            else ArtifactKind.SPECIALIST_REPORT
        )
        reports = [
            item for item in self.state.list_artifacts(child.run_id) if item.kind is report_kind
        ]
        if len(reports) != 1:
            raise _failure(ErrorCode.RECOVERY_REQUIRED)
        cleanup = self.state.get_artifact(child.cleanup_receipt_artifact_id)
        if (
            cleanup.kind is not ArtifactKind.RESOURCE_CLEANUP
            or cleanup.sha256 != child.cleanup_receipt_sha256
        ):
            raise _failure(ErrorCode.RECOVERY_REQUIRED)
        outputs = [reports[0], cleanup]
        if node.node.can_write:
            if child.patch_artifact_id is None or child.patch_sha256 is None:
                raise _failure(ErrorCode.RECOVERY_REQUIRED)
            patch = self.state.get_artifact(child.patch_artifact_id)
            if patch.kind is not ArtifactKind.PATCH or patch.sha256 != child.patch_sha256:
                raise _failure(ErrorCode.RECOVERY_REQUIRED)
            outputs.insert(0, patch)
        elif child.patch_artifact_id is not None:
            raise _failure(ErrorCode.RECOVERY_REQUIRED)
        refs = tuple(self._ref(item) for item in outputs)
        for ref in refs:
            self._validate_ref(ref, node)
        return refs

    async def _join(self, claim: GraphDriverClaim, graph: GraphSnapshot) -> Run:
        self._remaining(claim.parent_run_id)
        if graph.join_preparation is not None:
            # A preparation without completion after lost ownership is uncertain.
            raise _failure(ErrorCode.RECOVERY_REQUIRED)
        parent = self.state.get_run(claim.parent_run_id)
        if parent.task_id is None or parent.config_snapshot_hash is None:
            raise _failure(ErrorCode.RECOVERY_REQUIRED)
        inputs: list[GraphJoinInput] = []
        for node in sorted(graph.nodes, key=lambda item: item.binding.node_id):
            child = self._child(node)
            if (
                child.status is not RunStatus.COMPLETED
                or self._outputs(node, child) != node.output_artifacts
            ):
                raise _failure(ErrorCode.RECOVERY_REQUIRED)
            if node.node.can_write:
                patch = next(ref for ref in node.output_artifacts if ref.kind is ArtifactKind.PATCH)
                report = next(
                    ref
                    for ref in node.output_artifacts
                    if ref.kind is ArtifactKind.IMPLEMENTATION_REPORT
                )
                inputs.append(
                    GraphJoinInput(
                        node_id=node.binding.node_id,
                        child_run_id=child.run_id,
                        child_task_id=node.binding.child_task_id,
                        patch_artifact_id=patch.artifact_id,
                        patch_sha256=patch.sha256,
                        report_artifact_id=report.artifact_id,
                        report_sha256=report.sha256,
                    )
                )
        preparation = GraphJoinPreparation(
            parent_run_id=parent.run_id,
            parent_task_id=parent.task_id,
            config_snapshot_sha256=parent.config_snapshot_hash,
            plan_sha256=claim.plan_sha256,
            base_revision=parent.base_revision,
            ordered_inputs=tuple(inputs),
            created_at=self.clock.now(),
        )
        self.graphs.mark_join_prepared(claim, preparation, expected_revision=graph.revision)
        joined = await self.hooks.join_graph_candidates(parent, preparation.ordered_inputs)
        current = self.state.get_run(parent.run_id)
        if (
            joined.run_id != parent.run_id
            or current.status is not RunStatus.RUNNING
            or current.stage is not WorkflowStage.VERIFYING
            or current.patch_artifact_id is None
            or current.patch_sha256 is None
        ):
            raise _failure(ErrorCode.RECOVERY_REQUIRED)
        candidates = [
            lease
            for lease in self.state.active_leases(parent.run_id)
            if lease.kind is LeaseKind.WORKTREE
            and lease.status is LeaseStatus.ACTIVE
            and lease.metadata.get("workspace_kind") == WorkspaceKind.CANDIDATE.value
        ]
        if len(candidates) != 1:
            raise _failure(ErrorCode.RECOVERY_REQUIRED)
        latest = self._owned_snapshot(claim)
        completed = self.graphs.mark_join_complete(
            claim,
            GraphJoinCompletion(
                preparation_sha256=preparation.preparation_sha256,
                parent_patch_artifact_id=current.patch_artifact_id,
                parent_patch_sha256=current.patch_sha256,
                workspace_id=candidates[0].resource_id,
                created_at=self.clock.now(),
            ),
            expected_revision=latest.revision,
        )
        self.graphs.release_driver(
            claim, expected_revision=completed.revision, status=GraphStatus.JOINED
        )
        return current

    async def _abort(
        self,
        claim: GraphDriverClaim,
        tasks: dict[str, asyncio.Task[Run]],
        error_code: ErrorCode | None,
        cancelled: bool,
    ) -> None:
        for task in tasks.values():
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks.values(), return_exceptions=True)
        graph = self._snapshot(claim.parent_run_id)
        if graph.driver_claim == claim and graph.status is GraphStatus.RUNNING:
            if cancelled:
                self.graphs.request_cancel(claim.parent_run_id, expected_revision=graph.revision)
            else:
                for node in graph.nodes:
                    if node.status in {
                        GraphNodeStatus.PENDING,
                        GraphNodeStatus.RUNNING,
                        GraphNodeStatus.WAITING_APPROVAL,
                    }:
                        target = (
                            GraphNodeStatus.BLOCKED
                            if node.status is GraphNodeStatus.PENDING
                            else GraphNodeStatus.FAILED
                        )
                        self._transition(claim, node, target, error_code=error_code)
        parent = self.state.get_run(claim.parent_run_id)
        await self.hooks.cleanup_graph_children(parent)
        graph = self._snapshot(claim.parent_run_id)
        if (
            graph.driver_claim == claim
            and graph.status is GraphStatus.RUNNING
            and graph.join_preparation is None
        ):
            self.graphs.release_driver(
                claim, expected_revision=graph.revision, status=GraphStatus.FAILED
            )

    def _approval(self, child: Run) -> ApprovalRequest:
        if child.pending_approval_id is None:
            raise _failure(ErrorCode.RECOVERY_REQUIRED)
        request = self.state.get_approval(child.pending_approval_id)
        stored = self.state.get_intent(request.intent_id)
        if (
            request.request_id != child.pending_approval_id
            or request.run_id != child.run_id
            or stored.intent.run_id != child.run_id
            or stored.intent.task_id != child.task_id
            or stored.intent_hash != request.intent_hash
            or stored.approval_request_id != request.request_id
            or stored.intent.principal_role != request.principal_role
            or stored.intent.action != request.action
            or stored.intent.resource != request.resource
        ):
            raise _failure(ErrorCode.RECOVERY_REQUIRED)
        return request

    def _remaining(self, parent_run_id: str) -> float:
        remaining = self.hooks.remaining_graph_active_seconds(parent_run_id)
        if not math.isfinite(remaining) or remaining <= 0:
            raise _failure(ErrorCode.RUNTIME_BUDGET_EXCEEDED)
        return remaining

    def _snapshot(self, parent_run_id: str) -> GraphSnapshot:
        result = self.graphs.get(parent_run_id)
        if result is None:
            raise _failure(ErrorCode.RECOVERY_REQUIRED)
        return result

    def _owned_snapshot(self, claim: GraphDriverClaim) -> GraphSnapshot:
        graph = self._snapshot(claim.parent_run_id)
        if graph.cancel_requested_at is not None:
            raise asyncio.CancelledError
        if graph.driver_claim != claim or graph.status is not GraphStatus.RUNNING:
            raise _failure(ErrorCode.RECOVERY_REQUIRED)
        return graph

    def _child(self, node: GraphNodeRecord) -> Run:
        child = self.state.get_run(node.binding.child_run_id)
        if (
            self.graphs.child_binding(child.run_id) != node.binding
            or child.task_id != node.binding.child_task_id
            or child.project_id != node.binding.project_id
            or child.parent_run_id != node.binding.parent_run_id
            or child.parent_plan_sha256 != node.binding.plan_sha256
            or child.parent_node_id != node.binding.node_id
            or child.parent_iteration != node.binding.iteration
        ):
            raise _failure(ErrorCode.RECOVERY_REQUIRED)
        return child

    def _validate_ref(self, ref: GraphArtifactRef, node: GraphNodeRecord) -> None:
        metadata = self.state.get_artifact(ref.artifact_id)
        if (
            ref != self._ref(metadata)
            or metadata.run_id != node.binding.child_run_id
            or metadata.task_id != node.binding.child_task_id
            or metadata.project_id != node.binding.project_id
        ):
            raise _failure(ErrorCode.RECOVERY_REQUIRED)

    @staticmethod
    def _ref(metadata: ArtifactMetadata) -> GraphArtifactRef:
        if metadata.run_id is None:
            raise _failure(ErrorCode.RECOVERY_REQUIRED)
        return GraphArtifactRef(
            artifact_id=metadata.artifact_id,
            sha256=metadata.sha256,
            run_id=metadata.run_id,
            kind=metadata.kind,
        )

    @staticmethod
    def _node(graph: GraphSnapshot, node_id: str) -> GraphNodeRecord:
        return next(node for node in graph.nodes if node.binding.node_id == node_id)

    def _transition(
        self,
        claim: GraphDriverClaim,
        node: GraphNodeRecord,
        target: GraphNodeStatus,
        *,
        output_artifacts: tuple[GraphArtifactRef, ...] = (),
        error_code: ErrorCode | None = None,
    ) -> GraphNodeRecord:
        return self.graphs.transition_node(
            claim,
            node.binding.node_id,
            node.binding.iteration,
            expected_revision=node.revision,
            target=target,
            input_artifacts=node.input_artifacts,
            output_artifacts=output_artifacts,
            error_code=error_code,
        )

    def _parent_status(self, parent: Run, status: RunStatus, event: str) -> Run:
        return self.state.save_run(
            parent.model_copy(
                update={
                    "status": status,
                    "stage": WorkflowStage.IMPLEMENTING,
                    "pending_approval_id": None,
                    "updated_at": self.clock.now(),
                }
            ),
            event,
            {"status": status.value},
        )


def _failure(code: ErrorCode) -> FleetError:
    return FleetError(
        code,
        "Adaptive graph execution could not safely continue.",
        "Inspect the parent graph and exact child records; uncertain work must not be replayed.",
    )
