"""Coordinator scheduling contracts, with typed in-memory boundary doubles.

SQLite transactions/content validation are exercised by graph-store tests;
these tests control concurrent hook completion without a provider or sandbox.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from pydantic import JsonValue

from agent_fleet.application.graph import GraphCoordinator
from agent_fleet.domain.errors import ErrorCode, FleetError, GraphOwnershipUnavailableError
from agent_fleet.domain.fleet_plan import FleetPlan, FleetPlanNode, FleetStrategy
from agent_fleet.domain.graph import (
    GraphArtifactRef,
    GraphChildBinding,
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
    CanonicalResource,
    IntentStatus,
    LeaseKind,
    LeaseStatus,
    ResourceLease,
    Run,
    RunStatus,
    StoredToolIntent,
    ToolIntent,
    WorkflowStage,
)
from agent_fleet.domain.security import canonical_json_hash
from agent_fleet.ports.graph import GraphStore
from agent_fleet.ports.state_store import StateStore

NOW = datetime(2026, 9, 5, tzinfo=UTC)
HASH = "a" * 64


def identifier(prefix: str, number: int) -> str:
    return f"{prefix}_{number:032x}"


def invalid() -> FleetError:
    return FleetError(ErrorCode.RECOVERY_REQUIRED, "Invalid test boundary.", "Inspect state.")


class FixedClock:
    def now(self) -> datetime:
        return NOW


class MemoryState:
    def __init__(self, runs: list[Run]) -> None:
        self.runs = {run.run_id: run for run in runs}
        self.artifacts: dict[str, ArtifactMetadata] = {}
        self.approvals: dict[str, ApprovalRequest] = {}
        self.intents: dict[str, StoredToolIntent] = {}
        self.leases: list[ResourceLease] = []
        self.events: list[str] = []

    def get_run(self, run_id: str) -> Run:
        return self.runs[run_id].model_copy(deep=True)

    def save_run(self, run: Run, event: str, payload: dict[str, JsonValue]) -> Run:
        del payload
        self.events.append(event)
        self.runs[run.run_id] = Run.model_validate(run.model_dump())
        return self.get_run(run.run_id)

    def update(self, run: Run, **changes: object) -> Run:
        return self.save_run(run.model_copy(update=changes), "test.changed", {})

    def get_artifact(self, artifact_id: str) -> ArtifactMetadata:
        return self.artifacts[artifact_id]

    def list_artifacts(self, run_id: str) -> list[ArtifactMetadata]:
        return [item for item in self.artifacts.values() if item.run_id == run_id]

    def get_approval(self, request_id: str) -> ApprovalRequest:
        return self.approvals[request_id]

    def get_intent(self, intent_id: str) -> StoredToolIntent:
        return self.intents[intent_id]

    def outstanding_leases(self, run_id: str) -> list[ResourceLease]:
        return [
            item
            for item in self.leases
            if item.run_id == run_id
            and item.status not in {LeaseStatus.RELEASED, LeaseStatus.RECOVERED}
        ]

    def active_leases(self, run_id: str) -> list[ResourceLease]:
        return [
            item for item in self.outstanding_leases(run_id) if item.status is LeaseStatus.ACTIVE
        ]

    def artifact(self, run: Run, kind: ArtifactKind) -> ArtifactMetadata:
        item = ArtifactMetadata(
            artifact_id=identifier("art", len(self.artifacts) + 100),
            kind=kind,
            project_id=run.project_id,
            run_id=run.run_id,
            task_id=run.task_id,
            mime_type="application/json",
            byte_size=2,
            sha256=HASH,
            content_ref="unit-test-memory",
            producer="unit-test",
            redacted=True,
            created_at=NOW,
        )
        self.artifacts[item.artifact_id] = item
        return item

    def lease(self, run: Run) -> ResourceLease:
        lease = ResourceLease(
            lease_id=identifier("lease", len(self.leases) + 100),
            run_id=run.run_id,
            kind=LeaseKind.WORKTREE,
            resource_id=identifier("ws", len(self.leases) + 100),
            status=LeaseStatus.ACTIVE,
            metadata={"workspace_kind": "candidate"},
            created_at=NOW,
            updated_at=NOW,
        )
        self.leases.append(lease)
        return lease

    def pause(self, child: Run) -> Run:
        number = len(self.approvals) + 100
        intent = ToolIntent(
            intent_id=identifier("intent", number),
            run_id=child.run_id,
            task_id=cast(str, child.task_id),
            agent_instance_id=identifier("agent", number),
            principal_role="engineer",
            workflow="code-change",
            stage=WorkflowStage.IMPLEMENTING,
            action="command.run",
            resource=CanonicalResource(kind="command", identifier="test"),
            parameters={},
            reason="Needs approval.",
            side_effect=True,
            idempotency_key=f"command-{number}",
        )
        request = ApprovalRequest(
            request_id=identifier("perm", number),
            intent_id=intent.intent_id,
            run_id=child.run_id,
            intent_hash=canonical_json_hash(intent.model_dump(mode="json")),
            principal_role=intent.principal_role,
            action=intent.action,
            resource=intent.resource,
            reason="Needs approval.",
            created_at=NOW,
            expires_at=NOW + timedelta(minutes=10),
        )
        self.approvals[request.request_id] = request
        self.intents[intent.intent_id] = StoredToolIntent(
            intent=intent,
            intent_hash=request.intent_hash,
            status=IntentStatus.PENDING_APPROVAL,
            approval_request_id=request.request_id,
        )
        return self.update(
            child,
            status=RunStatus.PAUSED_FOR_APPROVAL,
            stage=WorkflowStage.IMPLEMENTING,
            pending_approval_id=request.request_id,
        )


class MemoryGraph:
    """Typed CAS double; deliberately no persistence/content assurance claim."""

    def __init__(self, snapshot: GraphSnapshot, state: MemoryState) -> None:
        self.snapshot = snapshot
        self.state = state
        self.transitions: list[tuple[str, GraphNodeStatus]] = []
        self.preparations: list[GraphJoinPreparation] = []

    def replace(self, **changes: object) -> GraphSnapshot:
        self.snapshot = GraphSnapshot.model_validate(
            self.snapshot.model_copy(update=changes).model_dump()
        )
        return self.snapshot

    def get(self, parent_run_id: str) -> GraphSnapshot | None:
        return self.snapshot if parent_run_id == self.snapshot.parent_run_id else None

    def child_binding(self, child_run_id: str) -> GraphChildBinding | None:
        return next(
            (
                node.binding
                for node in self.snapshot.nodes
                if node.binding.child_run_id == child_run_id
            ),
            None,
        )

    def claim_driver(self, parent_run_id: str, *, expected_revision: int) -> GraphDriverClaim:
        if (
            parent_run_id != self.snapshot.parent_run_id
            or expected_revision != self.snapshot.revision
            or self.snapshot.driver_claim is not None
        ):
            raise invalid()
        claim = GraphDriverClaim(
            parent_run_id=parent_run_id,
            plan_sha256=self.snapshot.plan_sha256,
            claim_id=identifier("corr", self.snapshot.driver_generation + 100),
            generation=self.snapshot.driver_generation + 1,
            claimed_at=NOW,
        )
        self.replace(
            driver_claim=claim,
            driver_generation=claim.generation,
            status=GraphStatus.RUNNING,
            revision=self.snapshot.revision + 1,
        )
        return claim

    def owned(self, claim: GraphDriverClaim, revision: int | None = None) -> None:
        if self.snapshot.driver_claim != claim or (
            revision is not None and revision != self.snapshot.revision
        ):
            raise invalid()

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
    ) -> GraphNodeRecord:
        self.owned(claim)
        node = next(item for item in self.snapshot.nodes if item.binding.node_id == node_id)
        if node.revision != expected_revision or iteration != 0:
            raise invalid()
        if target is GraphNodeStatus.RUNNING:
            assert self.state.get_run(node.binding.child_run_id).task_spec_artifact_id is not None
            assert sum(item.status is target for item in self.snapshot.nodes) < (
                self.snapshot.plan.max_parallel_agents
            )
        updated = GraphNodeRecord.model_validate(
            node.model_copy(
                update={
                    "status": target,
                    "revision": node.revision + 1,
                    "input_artifacts": input_artifacts,
                    "output_artifacts": output_artifacts,
                    "error_code": error_code,
                    "started_at": node.started_at
                    or (NOW if target is GraphNodeStatus.RUNNING else None),
                    "finished_at": None
                    if target in {GraphNodeStatus.RUNNING, GraphNodeStatus.WAITING_APPROVAL}
                    else NOW,
                }
            ).model_dump()
        )
        self.replace(nodes=tuple(updated if item == node else item for item in self.snapshot.nodes))
        self.transitions.append((node_id, target))
        return updated

    def release_driver(
        self, claim: GraphDriverClaim, *, expected_revision: int, status: GraphStatus
    ) -> GraphSnapshot:
        self.owned(claim, expected_revision)
        assert all(node.status is not GraphNodeStatus.RUNNING for node in self.snapshot.nodes)
        assert self.snapshot.join_preparation is None or status is GraphStatus.JOINED
        return self.replace(status=status, driver_claim=None, revision=self.snapshot.revision + 1)

    def mark_join_prepared(
        self, claim: GraphDriverClaim, receipt: GraphJoinPreparation, *, expected_revision: int
    ) -> GraphSnapshot:
        self.owned(claim, expected_revision)
        assert all(node.status is GraphNodeStatus.SUCCEEDED for node in self.snapshot.nodes)
        self.preparations.append(receipt)
        return self.replace(join_preparation=receipt, revision=self.snapshot.revision + 1)

    def mark_join_complete(
        self, claim: GraphDriverClaim, result: GraphJoinCompletion, *, expected_revision: int
    ) -> GraphSnapshot:
        self.owned(claim, expected_revision)
        return self.replace(
            join_completion=result,
            status=GraphStatus.JOINED,
            revision=self.snapshot.revision + 1,
        )

    def request_cancel(self, parent_run_id: str, *, expected_revision: int) -> GraphSnapshot:
        assert parent_run_id == self.snapshot.parent_run_id
        assert expected_revision == self.snapshot.revision
        nodes = []
        for node in self.snapshot.nodes:
            if node.status in {
                GraphNodeStatus.PENDING,
                GraphNodeStatus.RUNNING,
                GraphNodeStatus.WAITING_APPROVAL,
            }:
                node = node.model_copy(
                    update={"status": GraphNodeStatus.CANCELLED, "finished_at": NOW}
                )
                self.state.update(
                    self.state.get_run(node.binding.child_run_id), status=RunStatus.CANCELLED
                )
            nodes.append(node)
        return self.replace(
            nodes=tuple(nodes),
            cancel_requested_at=NOW,
            status=GraphStatus.CANCELLED,
            driver_claim=None,
            revision=self.snapshot.revision + 1,
        )


class ControlledHooks:
    def __init__(self, state: MemoryState, graphs: MemoryGraph) -> None:
        self.state = state
        self.graphs = graphs
        self.prepared: list[str] = []
        self.dependency_refs: dict[str, tuple[GraphArtifactRef, ...]] = {}
        self.executions: Counter[str] = Counter()
        self.active: set[str] = set()
        self.started: asyncio.Queue[str] = asyncio.Queue()
        self.release = {node.binding.node_id: asyncio.Event() for node in graphs.snapshot.nodes}
        self.pause_once: set[str] = set()
        self.fail_nodes: set[str] = set()
        self.cancelled: set[str] = set()
        self.output_mutation: Callable[[Run], Run] | None = None
        self.join_mutation: Callable[[Run], Run] | None = None
        self.join_inputs: list[tuple[GraphJoinInput, ...]] = []
        self.cleanup_count = 0
        self.cleanup_started = asyncio.Event()
        self.cleanup_release = asyncio.Event()
        self.cleanup_release.set()
        self.cleanup_error = False
        self.allowance: Callable[[], float] = lambda: 100.0

    async def prepare_graph_child(
        self, parent: Run, node: GraphNodeRecord, dependency_refs: tuple[GraphArtifactRef, ...]
    ) -> Run:
        assert parent.run_id == node.binding.parent_run_id
        self.prepared.append(node.binding.node_id)
        self.dependency_refs[node.binding.node_id] = dependency_refs
        child = self.state.get_run(node.binding.child_run_id)
        artifact = self.state.artifact(child, ArtifactKind.TASK_SPEC)
        return self.state.update(
            child, task_spec_artifact_id=artifact.artifact_id, task_spec_hash=HASH
        )

    async def execute_graph_child(self, child: Run) -> Run:
        node_id = cast(str, child.parent_node_id)
        node = next(item for item in self.graphs.snapshot.nodes if item.binding.node_id == node_id)
        assert node.status is GraphNodeStatus.RUNNING
        self.executions[node_id] += 1
        self.active.add(node_id)
        self.started.put_nowait(node_id)
        try:
            await self.release[node_id].wait()
            if node_id in self.fail_nodes:
                raise RuntimeError("private-provider-sentinel")
            if node_id in self.pause_once and self.executions[node_id] == 1:
                return self.state.pause(child)
            report_kind = (
                ArtifactKind.IMPLEMENTATION_REPORT
                if node.node.can_write
                else ArtifactKind.SPECIALIST_REPORT
            )
            self.state.artifact(child, report_kind)
            cleanup = self.state.artifact(child, ArtifactKind.RESOURCE_CLEANUP)
            changes: dict[str, object] = {
                "status": RunStatus.COMPLETED,
                "stage": WorkflowStage.PRESENTING,
                "pending_approval_id": None,
                "cleanup_receipt_artifact_id": cleanup.artifact_id,
                "cleanup_receipt_sha256": cleanup.sha256,
            }
            if node.node.can_write:
                patch = self.state.artifact(child, ArtifactKind.PATCH)
                changes.update(patch_artifact_id=patch.artifact_id, patch_sha256=patch.sha256)
            completed = self.state.update(child, **changes)
            return self.output_mutation(completed) if self.output_mutation else completed
        except asyncio.CancelledError:
            self.cancelled.add(node_id)
            raise
        finally:
            self.active.remove(node_id)

    async def join_graph_candidates(
        self, parent: Run, ordered_inputs: tuple[GraphJoinInput, ...]
    ) -> Run:
        assert not self.active
        assert self.graphs.snapshot.join_preparation is not None
        self.join_inputs.append(ordered_inputs)
        patch = self.state.artifact(parent, ArtifactKind.PATCH)
        self.state.lease(parent)
        joined = self.state.update(
            parent,
            stage=WorkflowStage.VERIFYING,
            patch_artifact_id=patch.artifact_id,
            patch_sha256=patch.sha256,
        )
        return self.join_mutation(joined) if self.join_mutation else joined

    async def cleanup_graph_children(self, parent: Run) -> None:
        assert parent.run_id == self.graphs.snapshot.parent_run_id
        assert not self.active, "owned children must be awaited before cleanup"
        self.cleanup_count += 1
        self.cleanup_started.set()
        await self.cleanup_release.wait()
        if self.cleanup_error:
            raise RuntimeError("private-cleanup-sentinel")

    def remaining_graph_active_seconds(self, parent_run_id: str) -> float:
        assert parent_run_id == self.graphs.snapshot.parent_run_id
        return self.allowance()

    def release_all(self) -> None:
        for event in self.release.values():
            event.set()

    async def next_started(self) -> str:
        return await asyncio.wait_for(self.started.get(), timeout=2)


class Fixture:
    def __init__(self, count: int = 3, capacity: int = 2, *, specialists: bool = False) -> None:
        parent = Run(
            run_id=identifier("run", 1),
            project_id=identifier("prj", 1),
            correlation_id=identifier("corr", 1),
            goal="Complete all criteria.",
            base_revision="abc123",
            target_status_fingerprint=HASH,
            status=RunStatus.RUNNING,
            stage=WorkflowStage.IMPLEMENTING,
            task_id=identifier("task", 1),
            config_snapshot_hash=HASH,
            created_at=NOW,
            updated_at=NOW,
        )
        nodes = [
            FleetPlanNode(
                node_id=f"writer-{number}",
                role_id="engineer",
                can_write=True,
                requires_workspace=True,
                scope=[f"src/{number}"],
                criterion_ids=["criterion"],
            )
            for number in range(count)
        ]
        if specialists:
            nodes = [
                FleetPlanNode(node_id="research", role_id="researcher"),
                FleetPlanNode(node_id="design", role_id="architect", depends_on=["research"]),
                nodes[0].model_copy(update={"depends_on": ["design"]}),
            ]
        plan = FleetPlan(
            plan_id=identifier("plan", 1),
            run_id=parent.run_id,
            task_id=cast(str, parent.task_id),
            strategy=FleetStrategy.RESEARCH_ARCHITECT_ENGINEER_VERIFIER
            if specialists
            else FleetStrategy.PARALLEL_ENGINEERS,
            nodes=[
                *nodes,
                FleetPlanNode(
                    node_id="verifier",
                    role_id="verifier",
                    independent_verifier=True,
                    depends_on=[node.node_id for node in nodes if node.can_write],
                    requires_workspace=True,
                    scope=["src"],
                ),
            ],
            max_parallel_agents=capacity,
            required_evidence=["canonical_patch"],
            rationale="Unit test graph.",
            created_at=NOW,
        )
        plan_hash = canonical_json_hash(plan.model_dump(mode="json"))
        children = []
        records = []
        for number, node in enumerate(sorted(nodes, key=lambda item: item.node_id), 2):
            child = parent.model_copy(
                update={
                    "run_id": identifier("run", number),
                    "task_id": identifier("task", number),
                    "status": RunStatus.CREATED,
                    "parent_run_id": parent.run_id,
                    "parent_plan_sha256": plan_hash,
                    "parent_node_id": node.node_id,
                    "parent_iteration": 0,
                }
            )
            children.append(child)
            records.append(
                GraphNodeRecord(
                    binding=GraphChildBinding(
                        project_id=child.project_id,
                        parent_run_id=parent.run_id,
                        plan_sha256=plan_hash,
                        node_id=node.node_id,
                        child_run_id=child.run_id,
                        child_task_id=cast(str, child.task_id),
                        node_sha256=canonical_json_hash(node.model_dump(mode="json")),
                        task_sha256=HASH,
                        run_binding_sha256=HASH,
                        created_at=NOW,
                    ),
                    node=node,
                    updated_at=NOW,
                )
            )
        self.parent = parent
        self.state = MemoryState([parent, *children])
        self.graphs = MemoryGraph(
            GraphSnapshot(
                project_id=parent.project_id,
                parent_run_id=parent.run_id,
                parent_task_id=cast(str, parent.task_id),
                plan_id=plan.plan_id,
                plan_artifact_id=identifier("art", 1),
                plan_sha256=plan_hash,
                plan=plan,
                nodes=tuple(records),
                created_at=NOW,
                updated_at=NOW,
            ),
            self.state,
        )
        self.hooks = ControlledHooks(self.state, self.graphs)

    def driver(self) -> GraphCoordinator:
        return GraphCoordinator(
            cast(GraphStore, self.graphs), cast(StateStore, self.state), self.hooks, FixedClock()
        )

    def child(self, node_id: str) -> Run:
        node = next(item for item in self.graphs.snapshot.nodes if item.binding.node_id == node_id)
        return self.state.get_run(node.binding.child_run_id)

    def resolve(self, node_id: str, status: ApprovalStatus) -> None:
        request_id = cast(str, self.child(node_id).pending_approval_id)
        self.state.approvals[request_id] = self.state.approvals[request_id].model_copy(
            update={"status": status}
        )


@pytest.mark.parametrize("first", ["writer-0", "writer-1"])
async def test_bounded_stable_queue_and_deterministic_join(first: str) -> None:
    fixture = Fixture(count=5, capacity=2)
    task = asyncio.create_task(fixture.driver().drive(fixture.parent.run_id))
    assert await fixture.hooks.next_started() == "writer-0"
    assert await fixture.hooks.next_started() == "writer-1"
    assert fixture.hooks.active == {"writer-0", "writer-1"}
    assert fixture.hooks.prepared == ["writer-0", "writer-1"]
    fixture.hooks.release[first].set()
    assert await fixture.hooks.next_started() == "writer-2"
    assert len(fixture.hooks.active) == 2
    fixture.hooks.release_all()
    result = await asyncio.wait_for(task, timeout=2)
    assert result.stage is WorkflowStage.VERIFYING
    assert result.status is RunStatus.RUNNING
    assert not result.verified_complete
    assert fixture.hooks.executions == Counter({f"writer-{i}": 1 for i in range(5)})
    assert [item.node_id for item in fixture.hooks.join_inputs[0]] == [
        f"writer-{i}" for i in range(5)
    ]
    assert fixture.graphs.snapshot.status is GraphStatus.JOINED
    assert fixture.graphs.snapshot.driver_claim is None
    assert fixture.graphs.snapshot.join_completion is not None
    assert (
        fixture.graphs.snapshot.join_completion.parent_patch_artifact_id == result.patch_artifact_id
    )
    # A completed graph read never executes a child or repeats join.
    assert await fixture.driver().drive(fixture.parent.run_id) == result
    assert len(fixture.hooks.join_inputs) == 1


async def test_specialist_dependencies_pass_reports_only_and_freeze_all_refs() -> None:
    fixture = Fixture(count=1, specialists=True)
    fixture.hooks.release_all()
    await fixture.driver().drive(fixture.parent.run_id)
    assert fixture.hooks.prepared == ["research", "design", "writer-0"]
    for node_id in ["design", "writer-0"]:
        refs = fixture.hooks.dependency_refs[node_id]
        assert len(refs) == 1 and refs[0].kind is ArtifactKind.SPECIALIST_REPORT
        node = next(
            item for item in fixture.graphs.snapshot.nodes if item.binding.node_id == node_id
        )
        assert {ref.kind for ref in node.input_artifacts} == {
            ArtifactKind.SPECIALIST_REPORT,
            ArtifactKind.RESOURCE_CLEANUP,
        }
    assert len(fixture.hooks.join_inputs[0]) == 1
    assert "verifier" not in fixture.hooks.executions


async def test_pause_waits_for_active_children_then_restart_only_approved_child() -> None:
    fixture = Fixture(count=3)
    fixture.hooks.pause_once = {"writer-0", "writer-1"}
    fixture.hooks.release["writer-0"].set()
    fixture.hooks.release["writer-1"].set()
    task = asyncio.create_task(fixture.driver().drive(fixture.parent.run_id))
    assert await fixture.hooks.next_started() == "writer-0"
    assert await fixture.hooks.next_started() == "writer-1"
    assert await fixture.hooks.next_started() == "writer-2"
    assert not task.done()
    assert fixture.graphs.snapshot.driver_claim is not None
    fixture.hooks.release["writer-2"].set()
    paused = await asyncio.wait_for(task, timeout=2)
    assert paused.status is RunStatus.WAITING_FOR_CHILDREN
    assert paused.pending_approval_id is None
    assert fixture.graphs.snapshot.status is GraphStatus.PAUSED
    assert not fixture.hooks.active
    prepared = fixture.hooks.prepared.copy()
    fixture.resolve("writer-0", ApprovalStatus.APPROVED)
    paused_again = await fixture.driver().drive(paused.run_id)
    assert paused_again.status is RunStatus.WAITING_FOR_CHILDREN
    assert fixture.hooks.executions == Counter({"writer-0": 2, "writer-1": 1, "writer-2": 1})
    assert fixture.hooks.prepared == prepared
    fixture.resolve("writer-1", ApprovalStatus.APPROVED)
    result = await fixture.driver().drive(paused.run_id)
    assert result.stage is WorkflowStage.VERIFYING
    assert fixture.hooks.executions == Counter({"writer-0": 2, "writer-1": 2, "writer-2": 1})
    assert fixture.hooks.cleanup_count == 0


async def test_denied_approval_blocks_without_reexecuting() -> None:
    fixture = Fixture(count=1)
    fixture.hooks.pause_once.add("writer-0")
    fixture.hooks.release_all()
    await fixture.driver().drive(fixture.parent.run_id)
    fixture.resolve("writer-0", ApprovalStatus.DENIED)
    with pytest.raises(FleetError) as caught:
        await fixture.driver().drive(fixture.parent.run_id)
    assert caught.value.code is ErrorCode.COMMAND_DENIED
    assert fixture.hooks.executions == {"writer-0": 1}
    assert fixture.graphs.snapshot.nodes[0].status is GraphNodeStatus.FAILED
    assert fixture.graphs.snapshot.status is GraphStatus.FAILED
    assert not fixture.hooks.join_inputs


async def test_competing_driver_does_not_cancel_or_clean_winners_children() -> None:
    fixture = Fixture(count=2)
    winner = asyncio.create_task(fixture.driver().drive(fixture.parent.run_id))
    await fixture.hooks.next_started()
    await fixture.hooks.next_started()
    with pytest.raises(FleetError):
        await fixture.driver().drive(fixture.parent.run_id)
    assert len(fixture.hooks.active) == 2
    assert fixture.hooks.cleanup_count == 0
    fixture.hooks.release_all()
    await asyncio.wait_for(winner, timeout=2)


async def test_failed_child_awaits_others_before_cleanup_and_blocks_queue() -> None:
    fixture = Fixture(count=3)
    fixture.hooks.fail_nodes.add("writer-0")
    task = asyncio.create_task(fixture.driver().drive(fixture.parent.run_id))
    await fixture.hooks.next_started()
    await fixture.hooks.next_started()
    fixture.hooks.release["writer-0"].set()
    with pytest.raises(FleetError) as caught:
        await asyncio.wait_for(task, timeout=2)
    assert caught.value.code is ErrorCode.INTERNAL_ERROR
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert fixture.hooks.cancelled == {"writer-1"}
    assert fixture.hooks.cleanup_count == 1 and not fixture.hooks.active
    assert fixture.graphs.snapshot.status is GraphStatus.FAILED
    assert fixture.graphs.snapshot.nodes[-1].status is GraphNodeStatus.BLOCKED
    assert "writer-2" not in fixture.hooks.executions
    assert not fixture.hooks.join_inputs


async def test_repeated_cancellation_retains_cleanup_and_fences_before_it() -> None:
    fixture = Fixture(count=3)
    fixture.hooks.cleanup_release.clear()
    task = asyncio.create_task(fixture.driver().drive(fixture.parent.run_id))
    await fixture.hooks.next_started()
    await fixture.hooks.next_started()
    task.cancel()
    await asyncio.wait_for(fixture.hooks.cleanup_started.wait(), timeout=2)
    assert fixture.graphs.snapshot.status is GraphStatus.CANCELLED
    assert fixture.hooks.cancelled == {"writer-0", "writer-1"}
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    fixture.hooks.cleanup_release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert fixture.hooks.cleanup_count == 1 and not fixture.hooks.active
    assert not fixture.hooks.join_inputs


async def test_external_fence_stops_active_children_without_accepting_outputs() -> None:
    fixture = Fixture(count=2)
    task = asyncio.create_task(fixture.driver().drive(fixture.parent.run_id))
    await fixture.hooks.next_started()
    await fixture.hooks.next_started()
    fixture.graphs.request_cancel(
        fixture.parent.run_id, expected_revision=fixture.graphs.snapshot.revision
    )
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=2)
    assert not fixture.hooks.active
    assert fixture.hooks.cleanup_count == 1
    assert all(not node.output_artifacts for node in fixture.graphs.snapshot.nodes)


async def test_shared_live_budget_watch_cancels_parallel_children() -> None:
    fixture = Fixture(count=3)
    loop = asyncio.get_running_loop()
    start = loop.time()
    fixture.hooks.allowance = lambda: 0.08 - 2 * (loop.time() - start)
    with pytest.raises(FleetError) as caught:
        await asyncio.wait_for(fixture.driver().drive(fixture.parent.run_id), timeout=2)
    assert caught.value.code is ErrorCode.RUNTIME_BUDGET_EXCEEDED
    assert fixture.hooks.cancelled == {"writer-0", "writer-1"}
    assert not fixture.hooks.active and fixture.hooks.cleanup_count == 1
    assert "writer-2" not in fixture.hooks.executions


@pytest.mark.parametrize("remaining", [0.0, -1.0, float("inf"), float("nan")])
async def test_invalid_or_exhausted_budget_starts_no_child(remaining: float) -> None:
    fixture = Fixture()
    fixture.hooks.allowance = lambda: remaining
    with pytest.raises(FleetError) as caught:
        await fixture.driver().drive(fixture.parent.run_id)
    assert caught.value.code is ErrorCode.RUNTIME_BUDGET_EXCEEDED
    assert not fixture.hooks.executions and not fixture.hooks.prepared


@pytest.mark.parametrize(
    "mutation",
    [
        "verified",
        "wrong-stage",
        "no-cleanup",
        "duplicate-report",
        "lease",
        "wrong-hash",
        "foreign-task",
    ],
)
async def test_child_output_boundary_fails_closed(mutation: str) -> None:
    fixture = Fixture(count=1)
    fixture.hooks.release_all()

    def mutate(child: Run) -> Run:
        if mutation == "verified":
            return fixture.state.update(child, verified_complete=True)
        if mutation == "wrong-stage":
            return fixture.state.update(child, stage=WorkflowStage.IMPLEMENTING)
        if mutation == "no-cleanup":
            return fixture.state.update(
                child, cleanup_receipt_artifact_id=None, cleanup_receipt_sha256=None
            )
        if mutation == "duplicate-report":
            fixture.state.artifact(child, ArtifactKind.IMPLEMENTATION_REPORT)
        elif mutation == "lease":
            fixture.state.lease(child)
        elif mutation == "wrong-hash":
            return fixture.state.update(child, patch_sha256="b" * 64)
        else:
            metadata = fixture.state.get_artifact(cast(str, child.patch_artifact_id))
            fixture.state.artifacts[metadata.artifact_id] = metadata.model_copy(
                update={"task_id": identifier("task", 999)}
            )
        return child

    fixture.hooks.output_mutation = mutate
    with pytest.raises(FleetError) as caught:
        await fixture.driver().drive(fixture.parent.run_id)
    assert caught.value.code is ErrorCode.RECOVERY_REQUIRED
    assert fixture.graphs.snapshot.status is GraphStatus.FAILED
    assert not fixture.hooks.join_inputs


@pytest.mark.parametrize("mutation", ["task", "hash", "request"])
async def test_approval_requires_exact_stored_intent_binding(mutation: str) -> None:
    fixture = Fixture(count=1)
    fixture.hooks.pause_once.add("writer-0")
    fixture.hooks.release_all()
    await fixture.driver().drive(fixture.parent.run_id)
    fixture.resolve("writer-0", ApprovalStatus.APPROVED)
    request = fixture.state.get_approval(cast(str, fixture.child("writer-0").pending_approval_id))
    stored = fixture.state.get_intent(request.intent_id)
    changes: dict[str, object] = {}
    if mutation == "task":
        changes["intent"] = stored.intent.model_copy(update={"task_id": identifier("task", 999)})
    elif mutation == "hash":
        changes["intent_hash"] = "b" * 64
    else:
        changes["approval_request_id"] = identifier("perm", 999)
    fixture.state.intents[request.intent_id] = stored.model_copy(update=changes)
    with pytest.raises(FleetError) as caught:
        await fixture.driver().drive(fixture.parent.run_id)
    assert caught.value.code is ErrorCode.RECOVERY_REQUIRED
    assert fixture.hooks.executions == {"writer-0": 1}


@pytest.mark.parametrize(
    "mutation", ["missing-patch", "wrong-stage", "two-candidates", "raw-error"]
)
async def test_partial_join_is_never_replayed(mutation: str) -> None:
    fixture = Fixture(count=1)
    fixture.hooks.release_all()

    def mutate(parent: Run) -> Run:
        if mutation == "missing-patch":
            return fixture.state.update(parent, patch_artifact_id=None, patch_sha256=None)
        if mutation == "wrong-stage":
            return fixture.state.update(parent, stage=WorkflowStage.IMPLEMENTING)
        if mutation == "two-candidates":
            fixture.state.lease(parent)
            return parent
        raise RuntimeError("private-join-sentinel")

    fixture.hooks.join_mutation = mutate
    with pytest.raises(FleetError) as caught:
        await fixture.driver().drive(fixture.parent.run_id)
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert fixture.graphs.snapshot.join_preparation is not None
    assert fixture.graphs.snapshot.join_completion is None
    assert fixture.graphs.snapshot.driver_claim is not None
    with pytest.raises(FleetError):
        await fixture.driver().drive(fixture.parent.run_id)
    assert len(fixture.hooks.join_inputs) == 1


async def test_cleanup_exception_is_cause_free_and_keeps_unknown_claim() -> None:
    fixture = Fixture(count=1)
    fixture.hooks.release_all()
    fixture.hooks.fail_nodes.add("writer-0")
    fixture.hooks.cleanup_error = True
    with pytest.raises(FleetError) as caught:
        await fixture.driver().drive(fixture.parent.run_id)
    assert caught.value.code is ErrorCode.RECOVERY_REQUIRED
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert fixture.graphs.snapshot.driver_claim is not None
    assert fixture.hooks.cleanup_count == 1


async def test_stale_claim_cas_loser_has_no_parent_or_cleanup_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = Fixture()
    original = fixture.graphs.claim_driver

    def competing_claim(parent_run_id: str, *, expected_revision: int) -> GraphDriverClaim:
        original(parent_run_id, expected_revision=expected_revision)
        raise RuntimeError("private-claim-conflict-sentinel")

    monkeypatch.setattr(fixture.graphs, "claim_driver", competing_claim)
    with pytest.raises(GraphOwnershipUnavailableError) as caught:
        await fixture.driver().drive(fixture.parent.run_id)
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert fixture.state.get_run(fixture.parent.run_id) == fixture.parent
    assert fixture.graphs.snapshot.status is GraphStatus.RUNNING
    assert fixture.graphs.snapshot.driver_claim is not None
    assert not fixture.state.events and not fixture.hooks.prepared
    assert not fixture.hooks.executions and fixture.hooks.cleanup_count == 0


async def test_preclaim_raw_read_error_is_safe_and_does_not_touch_parent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = Fixture()

    def fail_read(parent_run_id: str) -> GraphSnapshot:
        del parent_run_id
        raise RuntimeError("private-graph-read-sentinel")

    monkeypatch.setattr(fixture.graphs, "get", fail_read)
    with pytest.raises(GraphOwnershipUnavailableError) as caught:
        await fixture.driver().drive(fixture.parent.run_id)
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert not fixture.state.events and fixture.hooks.cleanup_count == 0


async def test_foreign_returned_child_does_not_replace_frozen_binding() -> None:
    fixture = Fixture(count=1)
    fixture.hooks.release_all()
    fixture.hooks.output_mutation = lambda child: child.model_copy(
        update={"run_id": fixture.parent.run_id}
    )
    with pytest.raises(FleetError) as caught:
        await fixture.driver().drive(fixture.parent.run_id)
    assert caught.value.code is ErrorCode.RECOVERY_REQUIRED
    assert not fixture.hooks.join_inputs
    assert fixture.state.get_run(fixture.parent.run_id).patch_artifact_id is None


async def test_join_completion_with_unreleased_unknown_owner_cannot_continue() -> None:
    fixture = Fixture(count=1)
    fixture.hooks.release_all()
    await fixture.driver().drive(fixture.parent.run_id)
    fixture.graphs.claim_driver(
        fixture.parent.run_id, expected_revision=fixture.graphs.snapshot.revision
    )
    fixture.graphs.replace(status=GraphStatus.JOINED)
    with pytest.raises(GraphOwnershipUnavailableError):
        await fixture.driver().drive(fixture.parent.run_id)
    assert len(fixture.hooks.join_inputs) == 1
    assert fixture.hooks.cleanup_count == 0
