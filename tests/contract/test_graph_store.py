from __future__ import annotations

import asyncio
import json
import multiprocessing
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from typing import Any

import pytest
from pydantic import ValidationError

from agent_fleet.adapters.artifacts.local import LocalArtifactStore
from agent_fleet.adapters.persistence import sqlite as sqlite_adapter
from agent_fleet.adapters.persistence.graphs import SqliteGraphStore
from agent_fleet.adapters.persistence.runtime_budgets import SqliteRuntimeBudgetStore
from agent_fleet.adapters.persistence.sqlite import SqliteStateStore
from agent_fleet.adapters.system import UuidIdGenerator
from agent_fleet.application.artifacts import ArtifactService
from agent_fleet.application.graph import GraphCoordinator
from agent_fleet.domain.budgets import RunBudgetLimits
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.evidence import ResourceCleanupReceipt
from agent_fleet.domain.fleet_plan import FleetPlan, FleetPlanNode, FleetStrategy
from agent_fleet.domain.graph import (
    GraphArtifactRef,
    GraphChildSeed,
    GraphDriverClaim,
    GraphJoinCompletion,
    GraphJoinInput,
    GraphJoinPreparation,
    GraphNodeRecord,
    GraphNodeStatus,
    GraphSnapshot,
    GraphStatus,
)
from agent_fleet.domain.ids import IdPrefix
from agent_fleet.domain.models import (
    AcceptanceCriterion,
    AgentInstance,
    AgentStatus,
    ApprovalRequest,
    ArtifactKind,
    CanonicalResource,
    ImplementationReport,
    LeaseKind,
    LeaseStatus,
    Project,
    ResourceLease,
    Run,
    RunStatus,
    SpecialistReport,
    TaskSpec,
    ToolIntent,
    WorkflowStage,
)
from agent_fleet.domain.security import Redactor, canonical_json_hash, sha256_bytes


@dataclass
class GraphClock:
    current: datetime

    def now(self) -> datetime:
        return self.current


@dataclass
class GraphHarness:
    state: SqliteStateStore
    graphs: SqliteGraphStore
    budgets: SqliteRuntimeBudgetStore
    artifacts: ArtifactService
    parent: Run
    plan: FleetPlan
    children: tuple[GraphChildSeed, ...]
    clock: GraphClock

    def initialize(self) -> GraphSnapshot:
        return self.graphs.initialize(self.parent.run_id, self.plan, self.children)

    def reopen(self) -> SqliteGraphStore:
        return SqliteGraphStore(
            self.state.database_path,
            self.clock,
            self.state.ids,
            self.state.redactor,
            self.artifacts.store,
        )

    def prepare(self, index: int) -> Run:
        seed = self.children[index]
        child = self.state.get_run(seed.run.run_id)
        self.budgets.initialize_run(
            child.run_id, RunBudgetLimits(), parent_run_id=self.parent.run_id
        )
        task_artifact = self.artifacts.create_text(
            kind=ArtifactKind.TASK_SPEC,
            project_id=child.project_id,
            run_id=child.run_id,
            task_id=seed.task.task_id,
            producer="test",
            content=seed.task.model_dump_json(indent=2),
        )
        config = self.artifacts.create_text(
            kind=ArtifactKind.CONFIG_SNAPSHOT,
            project_id=child.project_id,
            run_id=child.run_id,
            task_id=seed.task.task_id,
            producer="test",
            content="{}",
        )
        child = self.state.save_run(
            child.model_copy(
                update={
                    "task_spec_artifact_id": task_artifact.artifact_id,
                    "task_spec_hash": task_artifact.sha256,
                    "config_snapshot_artifact_id": config.artifact_id,
                }
            ),
            "child.prepared",
            {},
        )
        return child

    def run_child(self, index: int) -> Run:
        child = self.state.get_run(self.children[index].run.run_id)
        for stage in (
            WorkflowStage.INTAKE,
            WorkflowStage.SCOPING,
            WorkflowStage.WORKSPACE_PREPARATION,
            WorkflowStage.IMPLEMENTING,
        ):
            child = self.state.save_run(
                child.model_copy(
                    update={
                        "status": RunStatus.RUNNING,
                        "stage": stage,
                    }
                ),
                "run.stage_changed",
                {},
            )
        return child

    def outputs(self, index: int) -> tuple[GraphArtifactRef, ...]:
        child = self.run_child(index)
        refs = []
        for kind, content in (
            (ArtifactKind.PATCH, f"bounded patch {index}"),
            (
                ArtifactKind.IMPLEMENTATION_REPORT,
                ImplementationReport(
                    summary=f"report {index}",
                    intended_changed_paths=[self.children[index].task.allowed_paths[0]],
                    tests_added_or_changed=[],
                    criterion_results=[],
                    evidence_artifact_ids=[],
                    unresolved_limitations=[],
                    verifier_focus=[],
                ).model_dump_json(indent=2),
            ),
            (
                ArtifactKind.RESOURCE_CLEANUP,
                ResourceCleanupReceipt(
                    run_id=child.run_id, leases=[], complete=True, completed_at=self.clock.now()
                ).model_dump_json(indent=2),
            ),
        ):
            artifact = self.artifacts.create_text(
                kind=kind,
                project_id=child.project_id,
                run_id=child.run_id,
                task_id=child.task_id,
                producer="test",
                content=content,
            )
            refs.append(
                GraphArtifactRef(
                    artifact_id=artifact.artifact_id,
                    sha256=artifact.sha256,
                    run_id=child.run_id,
                    kind=kind,
                )
            )
        child = self.state.save_run(
            child.model_copy(
                update={
                    "patch_artifact_id": refs[0].artifact_id,
                    "patch_sha256": refs[0].sha256,
                    "cleanup_receipt_artifact_id": refs[2].artifact_id,
                    "cleanup_receipt_sha256": refs[2].sha256,
                    "stage": WorkflowStage.PRESENTING,
                }
            ),
            "run.stage_changed",
            {},
        )
        self.state.save_run(
            child.model_copy(update={"status": RunStatus.COMPLETED}), "run.completed", {}
        )
        return tuple(refs)


def graph_harness(tmp_path: Path) -> GraphHarness:
    clock = GraphClock(datetime.now(UTC))
    ids = UuidIdGenerator()
    state = SqliteStateStore(tmp_path / "state.db", clock, ids, Redactor())
    state.migrate()
    artifacts = ArtifactService(
        LocalArtifactStore(tmp_path / "artifacts"), state, clock, ids, state.redactor
    )
    graphs = SqliteGraphStore(state.database_path, clock, ids, state.redactor, artifacts.store)
    budgets = SqliteRuntimeBudgetStore(state.database_path, clock, ids, state.redactor, state)
    project = Project(
        project_id=ids.new(IdPrefix.PROJECT),
        canonical_root=str(tmp_path / "project"),
        identity_hash="a" * 64,
        created_at=clock.now(),
        updated_at=clock.now(),
    )
    state.save_project(project)
    parent = Run(
        run_id=ids.new(IdPrefix.RUN),
        project_id=project.project_id,
        correlation_id=ids.new(IdPrefix.CORRELATION),
        goal="Two bounded changes",
        base_revision="b" * 40,
        target_status_fingerprint="c" * 64,
        config_snapshot_hash=sha256_bytes(b"{}"),
        created_at=clock.now(),
        updated_at=clock.now(),
    )
    state.create_run(parent)
    budgets.initialize_run(parent.run_id, RunBudgetLimits())
    for stage in (WorkflowStage.INTAKE, WorkflowStage.SCOPING):
        parent = state.save_run(
            parent.model_copy(update={"status": RunStatus.RUNNING, "stage": stage}),
            "run.stage_changed",
            {},
        )
    criteria = [
        AcceptanceCriterion(criterion_id=f"criterion-{i}", description=f"Change {i}")
        for i in range(2)
    ]
    task = TaskSpec(
        task_id=ids.new(IdPrefix.TASK),
        run_id=parent.run_id,
        original_goal=parent.goal,
        normalized_goal=parent.goal,
        base_revision=parent.base_revision,
        allowed_paths=["src/left.py", "src/right.py"],
        forbidden_paths=[".git", ".fleet"],
        acceptance_criteria=criteria,
        required_evidence=["canonical_patch", "command_evidence", "independent_verifier_verdict"],
        max_repair_iterations=1,
        config_snapshot_hash=sha256_bytes(b"{}"),
        created_at=clock.now(),
    )
    state.save_task(task)
    writers = [
        FleetPlanNode(
            node_id=f"writer-{i}",
            role_id="engineer",
            goal=f"Change {i}",
            criterion_ids=[criteria[i].criterion_id],
            scope=[task.allowed_paths[i]],
            can_write=True,
            requires_workspace=True,
        )
        for i in range(2)
    ]
    plan = FleetPlan(
        plan_id=ids.new(IdPrefix.FLEET_PLAN),
        run_id=parent.run_id,
        task_id=task.task_id,
        strategy=FleetStrategy.PARALLEL_ENGINEERS,
        nodes=[
            *writers,
            FleetPlanNode(
                node_id="verify",
                role_id="verifier",
                scope=task.allowed_paths,
                depends_on=[item.node_id for item in writers],
                requires_workspace=True,
                independent_verifier=True,
            ),
        ],
        max_parallel_agents=2,
        required_evidence=task.required_evidence,
        rationale="Disjoint bounded changes",
        created_at=clock.now(),
    )
    artifact = artifacts.create_text(
        kind=ArtifactKind.FLEET_PLAN,
        project_id=parent.project_id,
        run_id=parent.run_id,
        task_id=task.task_id,
        producer="test",
        content=plan.model_dump_json(indent=2),
    )
    parent = state.save_run(
        parent.model_copy(
            update={
                "task_id": task.task_id,
                "fleet_plan_artifact_id": artifact.artifact_id,
                "fleet_plan_hash": artifact.sha256,
                "fleet_strategy": plan.strategy.value,
            }
        ),
        "run.task_bound",
        {},
    )
    children: list[GraphChildSeed] = []
    for i, node in enumerate(writers):
        child_task = task.model_copy(
            update={
                "run_id": ids.new(IdPrefix.RUN),
                "task_id": ids.new(IdPrefix.TASK),
                "original_goal": node.goal,
                "normalized_goal": node.goal,
                "allowed_paths": node.scope,
                "acceptance_criteria": [criteria[i]],
                "required_evidence": ["canonical_patch", "command_evidence"],
            }
        )
        child = Run(
            run_id=child_task.run_id,
            project_id=parent.project_id,
            correlation_id=ids.new(IdPrefix.CORRELATION),
            goal=node.goal,
            base_revision=parent.base_revision,
            target_status_fingerprint=parent.target_status_fingerprint,
            task_id=child_task.task_id,
            config_snapshot_hash=task.config_snapshot_hash,
            parent_run_id=parent.run_id,
            parent_plan_sha256=artifact.sha256,
            parent_node_id=node.node_id,
            parent_iteration=0,
            created_at=clock.now(),
            updated_at=clock.now(),
        )
        children.append(GraphChildSeed(node_id=node.node_id, run=child, task=child_task))
    return GraphHarness(state, graphs, budgets, artifacts, parent, plan, tuple(children), clock)


def test_atomic_initialize_reopen_and_frozen_preallocated_identities(tmp_path: Path) -> None:
    h = graph_harness(tmp_path)
    assert h.graphs.get(h.parent.run_id) is None
    graph = h.initialize()
    assert h.reopen().get(h.parent.run_id) == graph
    assert len(graph.nodes) == 2
    assert len(graph.plan.nodes) == 3
    assert h.graphs.descendants(h.parent.run_id) == tuple(node.binding for node in graph.nodes)
    other = h.children[0].model_copy(
        update={
            "run": h.children[0].run.model_copy(update={"run_id": h.state.ids.new(IdPrefix.RUN)})
        }
    )
    assert h.graphs.initialize(h.parent.run_id, h.plan, (other, h.children[1])) == graph
    for seed in h.children:
        assert h.state.get_run(seed.run.run_id) == seed.run
        assert h.state.get_task(seed.task.task_id) == seed.task
        assert h.graphs.child_binding(seed.run.run_id) is not None
    assert h.graphs.child_binding(h.parent.run_id) is None
    assert (
        sum(
            event.event_type == "graph.initialized"
            for event in h.state.list_events(h.parent.run_id)
        )
        == 1
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("goal", "Unreviewed replacement goal"),
        ("scope", ["src/other.py"]),
        ("max_steps", 99),
        ("criterion_ids", ["criterion-1"]),
    ],
)
def test_snapshot_rejects_self_hashed_child_not_matching_frozen_plan(
    tmp_path: Path, field: str, value: Any
) -> None:
    h = graph_harness(tmp_path)
    graph = h.initialize()
    data = graph.model_dump(mode="json")
    node = data["nodes"][0]
    node["node"][field] = value
    node["binding"]["node_sha256"] = canonical_json_hash(node["node"])
    GraphNodeRecord.model_validate(node)  # self-hash alone is not the parent plan boundary.
    with pytest.raises(ValidationError, match="frozen plan node"):
        GraphSnapshot.model_validate(data)


def test_initialization_failure_rolls_back_every_child_and_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = graph_harness(tmp_path)
    original = h.graphs._event

    def fail(
        connection: sqlite3.Connection, run: Run, kind: str, payload: dict[str, object]
    ) -> None:
        if kind == "graph.initialized":
            raise sqlite3.OperationalError("injected")
        original(connection, run, kind, payload)

    monkeypatch.setattr(h.graphs, "_event", fail)
    with pytest.raises(FleetError) as captured:
        h.initialize()
    assert captured.value.__context__ is None
    with sqlite3.connect(h.state.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM fleet_graphs").fetchone()[0] == 0
    assert h.graphs.get(h.parent.run_id) is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("project_id", "prj_" + "e" * 32),
        ("base_revision", "e" * 40),
        ("target_status_fingerprint", "e" * 64),
        ("parent_plan_sha256", "e" * 64),
        ("parent_node_id", "another"),
        ("parent_iteration", 1),
    ],
)
def test_foreign_or_widened_seed_has_no_partial_state(
    tmp_path: Path, field: str, value: Any
) -> None:
    h = graph_harness(tmp_path)
    bad = h.children[1].model_copy(
        update={"run": h.children[1].run.model_copy(update={field: value})}
    )
    with pytest.raises(FleetError):
        h.graphs.initialize(h.parent.run_id, h.plan, (h.children[0], bad))
    assert h.graphs.get(h.parent.run_id) is None
    with sqlite3.connect(h.state.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1


def test_driver_claim_is_permanent_until_quiescent_release_and_stale_token_rejects(
    tmp_path: Path,
) -> None:
    h = graph_harness(tmp_path)
    h.initialize()
    claim = h.graphs.claim_driver(h.parent.run_id, expected_revision=0)
    with pytest.raises(FleetError):
        h.reopen().claim_driver(h.parent.run_id, expected_revision=1)
    graph = h.graphs.release_driver(claim, expected_revision=1, status=GraphStatus.READY)
    next_claim = h.graphs.claim_driver(h.parent.run_id, expected_revision=graph.revision)
    assert next_claim.generation == 2
    with pytest.raises(FleetError):
        h.graphs.release_driver(claim, expected_revision=3, status=GraphStatus.READY)


def test_node_requires_complete_metadata_and_shared_budget_then_cas_before_dispatch(
    tmp_path: Path,
) -> None:
    h = graph_harness(tmp_path)
    h.initialize()
    claim = h.graphs.claim_driver(h.parent.run_id, expected_revision=0)
    with pytest.raises(FleetError):
        h.graphs.transition_node(
            claim, "writer-0", 0, expected_revision=0, target=GraphNodeStatus.RUNNING
        )
    h.prepare(0)
    node = h.graphs.transition_node(
        claim, "writer-0", 0, expected_revision=0, target=GraphNodeStatus.RUNNING
    )
    assert node.revision == 1
    with pytest.raises(FleetError):
        h.graphs.transition_node(
            claim, "writer-0", 0, expected_revision=0, target=GraphNodeStatus.RUNNING
        )
    with pytest.raises(FleetError):
        h.graphs.release_driver(claim, expected_revision=1, status=GraphStatus.PAUSED)
    reopened = h.reopen().get(h.parent.run_id)
    assert reopened is not None and reopened.nodes[0].status is GraphNodeStatus.RUNNING


def test_success_freezes_exact_artifacts_and_join_receipts_without_replaying_nodes(
    tmp_path: Path,
) -> None:
    h = graph_harness(tmp_path)
    h.initialize()
    claim = h.graphs.claim_driver(h.parent.run_id, expected_revision=0)
    finished: list[GraphNodeRecord] = []
    for i in range(2):
        h.prepare(i)
        h.graphs.transition_node(
            claim, f"writer-{i}", 0, expected_revision=0, target=GraphNodeStatus.RUNNING
        )
        outputs = h.outputs(i)
        finished.append(
            h.graphs.transition_node(
                claim,
                f"writer-{i}",
                0,
                expected_revision=1,
                target=GraphNodeStatus.SUCCEEDED,
                output_artifacts=outputs,
            )
        )
    graph = h.graphs.get(h.parent.run_id)
    assert graph is not None and graph.revision == 1
    receipt = GraphJoinPreparation(
        parent_run_id=h.parent.run_id,
        parent_task_id=h.parent.task_id,
        config_snapshot_sha256=h.parent.config_snapshot_hash,
        plan_sha256=graph.plan_sha256,
        base_revision=h.parent.base_revision,
        created_at=h.clock.now(),
        ordered_inputs=tuple(
            GraphJoinInput(
                node_id=node.binding.node_id,
                child_run_id=node.binding.child_run_id,
                child_task_id=node.binding.child_task_id,
                patch_artifact_id=node.output_artifacts[0].artifact_id,
                patch_sha256=node.output_artifacts[0].sha256,
                report_artifact_id=node.output_artifacts[1].artifact_id,
                report_sha256=node.output_artifacts[1].sha256,
            )
            for node in finished
        ),
    )
    graph = h.graphs.mark_join_prepared(claim, receipt, expected_revision=graph.revision)
    with pytest.raises(FleetError):
        h.graphs.release_driver(claim, expected_revision=graph.revision, status=GraphStatus.READY)
    patch = h.artifacts.create_text(
        kind=ArtifactKind.PATCH,
        project_id=h.parent.project_id,
        run_id=h.parent.run_id,
        task_id=h.parent.task_id,
        producer="test",
        content="joined",
    )
    parent = h.state.get_run(h.parent.run_id)
    h.state.save_run(
        parent.model_copy(
            update={"patch_artifact_id": patch.artifact_id, "patch_sha256": patch.sha256}
        ),
        "patch.joined",
        {},
    )
    workspace_id = h.state.ids.new(IdPrefix.WORKSPACE)
    h.state.save_lease(
        ResourceLease(
            lease_id=h.state.ids.new(IdPrefix.LEASE),
            run_id=parent.run_id,
            kind=LeaseKind.WORKTREE,
            resource_id=workspace_id,
            status=LeaseStatus.ACTIVE,
            created_at=h.clock.now(),
            updated_at=h.clock.now(),
            metadata={"workspace_kind": "candidate", "base_revision": parent.base_revision},
        )
    )
    completion = GraphJoinCompletion(
        preparation_sha256=receipt.preparation_sha256,
        parent_patch_artifact_id=patch.artifact_id,
        parent_patch_sha256=patch.sha256,
        workspace_id=workspace_id,
        created_at=h.clock.now(),
    )
    graph = h.graphs.mark_join_complete(claim, completion, expected_revision=graph.revision)
    assert graph.status is GraphStatus.JOINED
    graph = h.graphs.release_driver(
        claim, expected_revision=graph.revision, status=GraphStatus.JOINED
    )
    assert h.reopen().get(parent.run_id) == graph
    assert all(node.status is GraphNodeStatus.SUCCEEDED for node in graph.nodes)


@pytest.mark.parametrize(
    "mutation", ["flags", "sql-run", "task", "node", "manifest", "missing-binding"]
)
def test_mutable_or_corrupt_child_identity_never_becomes_public_run(
    tmp_path: Path, mutation: str
) -> None:
    h = graph_harness(tmp_path)
    h.initialize()
    child = h.children[0].run
    with sqlite3.connect(h.state.database_path) as connection:
        if mutation == "flags":
            data = child.model_dump(mode="json")
            for key in (
                "parent_run_id",
                "parent_plan_sha256",
                "parent_node_id",
                "parent_iteration",
            ):
                data[key] = None
            connection.execute(
                "UPDATE runs SET data_json=? WHERE run_id=?", (json.dumps(data), child.run_id)
            )
        elif mutation == "sql-run":
            connection.execute(
                "UPDATE runs SET project_id=? WHERE run_id=?", ("prj_" + "e" * 32, child.run_id)
            )
        elif mutation == "task":
            connection.execute(
                "UPDATE tasks SET run_id=? WHERE task_id=?",
                ("run_" + "e" * 32, h.children[0].task.task_id),
            )
        elif mutation == "node":
            connection.execute(
                "UPDATE fleet_graph_nodes SET status='succeeded' WHERE child_run_id=?",
                (child.run_id,),
            )
        elif mutation == "manifest":
            connection.execute("UPDATE fleet_graphs SET immutable_manifest_json='{}'")
        else:
            connection.execute(
                "DELETE FROM fleet_graph_nodes WHERE child_run_id=?", (child.run_id,)
            )
    with pytest.raises(FleetError) as captured:
        h.graphs.child_binding(child.run_id)
    assert captured.value.code is ErrorCode.RECOVERY_REQUIRED
    assert captured.value.__context__ is None


def test_registered_secret_corruption_has_no_raw_exception_context(tmp_path: Path) -> None:
    h = graph_harness(tmp_path)
    h.initialize()
    secret = "graph-private-sentinel-67213"
    h.state.redactor.register_secret(secret)
    with sqlite3.connect(h.state.database_path) as connection:
        connection.execute(
            "UPDATE fleet_graphs SET data_json=?", (json.dumps({"unknown": secret}),)
        )
    with pytest.raises(FleetError) as captured:
        h.graphs.get(h.parent.run_id)
    assert secret not in str(captured.value)
    assert captured.value.__context__ is None and captured.value.__cause__ is None


def test_cancel_fence_atomically_stops_exact_children_and_invalidates_owner(tmp_path: Path) -> None:
    h = graph_harness(tmp_path)
    h.initialize()
    claim = h.graphs.claim_driver(h.parent.run_id, expected_revision=0)
    h.prepare(0)
    h.graphs.transition_node(
        claim, "writer-0", 0, expected_revision=0, target=GraphNodeStatus.RUNNING
    )
    graph = h.graphs.request_cancel(h.parent.run_id, expected_revision=1)
    assert graph.status is GraphStatus.CANCELLED
    assert all(node.status is GraphNodeStatus.CANCELLED for node in graph.nodes)
    assert all(
        h.state.get_run(seed.run.run_id).status is RunStatus.CANCELLED for seed in h.children
    )
    assert h.state.get_run(h.parent.run_id).status is RunStatus.RUNNING
    assert h.graphs.request_cancel(h.parent.run_id, expected_revision=graph.revision) == graph
    with pytest.raises(FleetError):
        h.graphs.claim_driver(h.parent.run_id, expected_revision=graph.revision)
    with pytest.raises(FleetError):
        h.graphs.transition_node(
            claim, "writer-1", 0, expected_revision=1, target=GraphNodeStatus.RUNNING
        )


def test_cancel_audit_failure_rolls_back_all_child_statuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = graph_harness(tmp_path)
    h.initialize()
    original = h.graphs._event

    def fail(
        connection: sqlite3.Connection, run: Run, kind: str, payload: dict[str, object]
    ) -> None:
        if kind == "graph.cancel_requested":
            raise sqlite3.OperationalError("injected")
        original(connection, run, kind, payload)

    monkeypatch.setattr(h.graphs, "_event", fail)
    with pytest.raises(FleetError):
        h.graphs.request_cancel(h.parent.run_id, expected_revision=0)
    assert all(h.state.get_run(seed.run.run_id).status is RunStatus.CREATED for seed in h.children)
    graph = h.graphs.get(h.parent.run_id)
    assert graph is not None and graph.status is GraphStatus.READY


def _claim_process(
    database: str, artifacts: str, parent_id: str, now: str, barrier: Any, results: Any
) -> None:
    store = SqliteGraphStore(
        Path(database),
        GraphClock(datetime.fromisoformat(now)),
        UuidIdGenerator(),
        Redactor(),
        LocalArtifactStore(Path(artifacts)),
    )
    barrier.wait()
    try:
        claim = store.claim_driver(parent_id, expected_revision=0)
        results.put(claim.claim_id)
    except FleetError as error:
        results.put(error.code.value)


def test_multiprocess_driver_claim_has_exactly_one_winner(tmp_path: Path) -> None:
    h = graph_harness(tmp_path)
    h.initialize()
    context = multiprocessing.get_context("spawn")
    barrier, results = context.Barrier(2), context.Queue()
    processes = [
        context.Process(
            target=_claim_process,
            args=(
                str(h.state.database_path),
                str(tmp_path / "artifacts"),
                h.parent.run_id,
                h.clock.now().isoformat(),
                barrier,
                results,
            ),
        )
        for _ in range(2)
    ]
    for process in processes:
        process.start()
    outcomes = [results.get(timeout=20) for _ in processes]
    for process in processes:
        process.join(timeout=20)
        assert process.exitcode == 0
    assert sum(value.startswith("corr_") for value in outcomes) == 1
    assert outcomes.count(ErrorCode.RECOVERY_REQUIRED.value) == 1
    assert (
        sum(
            event.event_type == "graph.driver_claimed"
            for event in h.state.list_events(h.parent.run_id)
        )
        == 1
    )


def test_approval_pause_reopen_resumes_only_the_exact_approved_child(tmp_path: Path) -> None:
    h = graph_harness(tmp_path)
    h.initialize()
    claim = h.graphs.claim_driver(h.parent.run_id, expected_revision=0)
    h.prepare(0)
    h.graphs.transition_node(
        claim, "writer-0", 0, expected_revision=0, target=GraphNodeStatus.RUNNING
    )
    child = h.run_child(0)
    assert child.task_id is not None
    agent = AgentInstance(
        agent_instance_id=h.state.ids.new(IdPrefix.AGENT),
        run_id=child.run_id,
        task_id=child.task_id,
        role="engineer",
        status=AgentStatus.RUNNING,
        iteration=0,
        created_at=h.clock.now(),
    )
    h.state.save_agent_instance(agent)
    intent = ToolIntent(
        intent_id=h.state.ids.new(IdPrefix.INTENT),
        run_id=child.run_id,
        task_id=child.task_id,
        agent_instance_id=agent.agent_instance_id,
        principal_role="engineer",
        workflow="code-change",
        stage=WorkflowStage.IMPLEMENTING,
        action="fixture.record_side_effect",
        resource=CanonicalResource(kind="fake_side_effect", identifier="fixture://approval-proof"),
        parameters={},
        reason="Exact node approval",
        side_effect=True,
        idempotency_key="node-approval",
    )
    digest = canonical_json_hash(intent.model_dump(mode="json"))
    request = ApprovalRequest(
        request_id=h.state.ids.new(IdPrefix.APPROVAL),
        intent_id=intent.intent_id,
        run_id=child.run_id,
        intent_hash=digest,
        principal_role="engineer",
        action=intent.action,
        resource=intent.resource,
        reason=intent.reason,
        created_at=h.clock.now(),
        expires_at=h.clock.now() + timedelta(minutes=5),
    )
    h.state.create_approval_and_pause(intent, digest, request)
    node = h.graphs.transition_node(
        claim, "writer-0", 0, expected_revision=1, target=GraphNodeStatus.WAITING_APPROVAL
    )
    graph = h.graphs.release_driver(claim, expected_revision=1, status=GraphStatus.PAUSED)
    next_claim = h.reopen().claim_driver(h.parent.run_id, expected_revision=graph.revision)
    with pytest.raises(FleetError):
        h.graphs.transition_node(
            next_claim,
            "writer-0",
            0,
            expected_revision=node.revision,
            target=GraphNodeStatus.RUNNING,
        )
    h.state.resolve_approval(request.request_id, approve=True, denial_reason=None)
    resumed = h.graphs.transition_node(
        next_claim, "writer-0", 0, expected_revision=node.revision, target=GraphNodeStatus.RUNNING
    )
    assert resumed.binding == node.binding
    assert resumed.started_at == node.started_at
    assert resumed.input_artifacts == node.input_artifacts
    assert h.state.get_run(h.children[1].run.run_id).status is RunStatus.CREATED


@pytest.mark.parametrize("mutation", ["clear-driver", "node-state", "parent-task"])
def test_sql_and_json_edits_cannot_reforge_journaled_ownership(
    tmp_path: Path, mutation: str
) -> None:
    h = graph_harness(tmp_path)
    h.initialize()
    h.graphs.claim_driver(h.parent.run_id, expected_revision=0)
    with sqlite3.connect(h.state.database_path) as connection:
        if mutation == "clear-driver":
            raw = connection.execute("SELECT data_json FROM fleet_graphs").fetchone()[0]
            data = json.loads(raw)
            data.update(driver_claim=None, status="ready")
            connection.execute(
                "UPDATE fleet_graphs SET driver_claim_id=NULL,status='ready',data_json=?",
                (json.dumps(data),),
            )
        elif mutation == "node-state":
            raw = connection.execute(
                "SELECT data_json FROM fleet_graph_nodes WHERE node_id='writer-0'"
            ).fetchone()[0]
            data = json.loads(raw)
            data.update(status="running", started_at=h.clock.now().isoformat(), revision=1)
            connection.execute(
                "UPDATE fleet_graph_nodes SET status='running',revision=1,data_json=? "
                "WHERE node_id='writer-0'",
                (json.dumps(data),),
            )
        else:
            raw = connection.execute(
                "SELECT data_json FROM tasks WHERE task_id=?", (h.parent.task_id,)
            ).fetchone()[0]
            data = json.loads(raw)
            data["acceptance_criteria"][0]["description"] = "Changed criterion"
            connection.execute(
                "UPDATE tasks SET data_json=? WHERE task_id=?", (json.dumps(data), h.parent.task_id)
            )
    with pytest.raises(FleetError) as captured:
        h.reopen().get(h.parent.run_id)
    assert captured.value.code is ErrorCode.RECOVERY_REQUIRED


def test_foreign_outputs_and_missing_cleanup_do_not_settle_node(tmp_path: Path) -> None:
    h = graph_harness(tmp_path)
    h.initialize()
    claim = h.graphs.claim_driver(h.parent.run_id, expected_revision=0)
    for i in range(2):
        h.prepare(i)
        h.graphs.transition_node(
            claim, f"writer-{i}", 0, expected_revision=0, target=GraphNodeStatus.RUNNING
        )
    own = h.outputs(0)
    foreign = h.outputs(1)
    for invalid in (own[:-1], foreign, (own[0], own[1], foreign[2])):
        with pytest.raises(FleetError):
            h.graphs.transition_node(
                claim,
                "writer-0",
                0,
                expected_revision=1,
                target=GraphNodeStatus.SUCCEEDED,
                output_artifacts=invalid,
            )
    result = h.graphs.transition_node(
        claim,
        "writer-0",
        0,
        expected_revision=1,
        target=GraphNodeStatus.SUCCEEDED,
        output_artifacts=own,
    )
    assert result.output_artifacts == own


def test_cancel_preserves_succeeded_child_provenance_and_unrelated_run(tmp_path: Path) -> None:
    h = graph_harness(tmp_path)
    h.initialize()
    claim = h.graphs.claim_driver(h.parent.run_id, expected_revision=0)
    h.prepare(0)
    h.graphs.transition_node(
        claim, "writer-0", 0, expected_revision=0, target=GraphNodeStatus.RUNNING
    )
    outputs = h.outputs(0)
    h.graphs.transition_node(
        claim,
        "writer-0",
        0,
        expected_revision=1,
        target=GraphNodeStatus.SUCCEEDED,
        output_artifacts=outputs,
    )
    other = h.parent.model_copy(
        update={
            "run_id": h.state.ids.new(IdPrefix.RUN),
            "task_id": None,
            "fleet_plan_artifact_id": None,
            "fleet_plan_hash": None,
            "fleet_strategy": None,
        }
    )
    h.state.create_run(other)
    graph = h.graphs.request_cancel(h.parent.run_id, expected_revision=1)
    assert graph.nodes[0].status is GraphNodeStatus.SUCCEEDED
    assert graph.nodes[0].output_artifacts == outputs
    assert h.state.get_run(h.children[0].run.run_id).status is RunStatus.COMPLETED
    assert h.state.get_run(other.run_id) == other


def test_absent_database_is_not_created_and_old_schema_requires_explicit_migration(
    tmp_path: Path,
) -> None:
    absent = tmp_path / "absent.db"
    store = SqliteGraphStore(
        absent,
        GraphClock(datetime.now(UTC)),
        UuidIdGenerator(),
        Redactor(),
        LocalArtifactStore(tmp_path / "artifacts"),
    )
    with pytest.raises(FleetError):
        store.get("run_" + "a" * 32)
    assert not absent.exists()
    h = graph_harness(tmp_path)
    with sqlite3.connect(h.state.database_path) as connection:
        connection.execute("DELETE FROM schema_migrations WHERE version >= 6")
    with pytest.raises(FleetError):
        h.graphs.get(h.parent.run_id)


@pytest.mark.asyncio
async def test_real_store_coordinator_overlaps_children_and_reopen_does_not_rejoin(
    tmp_path: Path,
) -> None:
    h = graph_harness(tmp_path)
    h.initialize()
    parent = h.state.get_run(h.parent.run_id)
    for stage in (WorkflowStage.WORKSPACE_PREPARATION, WorkflowStage.IMPLEMENTING):
        parent = h.state.save_run(
            parent.model_copy(update={"stage": stage}), "run.stage_changed", {}
        )

    class Hooks:
        def __init__(self) -> None:
            self.entered = 0
            self.both = asyncio.Event()
            self.joins = 0

        async def prepare_graph_child(
            self, parent: Run, node: GraphNodeRecord, dependency_refs: tuple[GraphArtifactRef, ...]
        ) -> Run:
            assert not dependency_refs
            return h.prepare(int(node.binding.node_id[-1]))

        async def execute_graph_child(self, child: Run) -> Run:
            self.entered += 1
            if self.entered == 2:
                self.both.set()
            await asyncio.wait_for(self.both.wait(), timeout=5)
            assert child.parent_node_id is not None
            h.outputs(int(child.parent_node_id[-1]))
            return h.state.get_run(child.run_id)

        async def join_graph_candidates(
            self, parent: Run, ordered_inputs: tuple[GraphJoinInput, ...]
        ) -> Run:
            self.joins += 1
            assert [item.node_id for item in ordered_inputs] == ["writer-0", "writer-1"]
            patch = h.artifacts.create_text(
                kind=ArtifactKind.PATCH,
                project_id=parent.project_id,
                run_id=parent.run_id,
                task_id=parent.task_id,
                producer="test",
                content="joined once",
            )
            h.state.save_lease(
                ResourceLease(
                    lease_id=h.state.ids.new(IdPrefix.LEASE),
                    run_id=parent.run_id,
                    kind=LeaseKind.WORKTREE,
                    resource_id=h.state.ids.new(IdPrefix.WORKSPACE),
                    status=LeaseStatus.ACTIVE,
                    created_at=h.clock.now(),
                    updated_at=h.clock.now(),
                    metadata={"workspace_kind": "candidate", "base_revision": parent.base_revision},
                )
            )
            return h.state.save_run(
                parent.model_copy(
                    update={
                        "stage": WorkflowStage.VERIFYING,
                        "patch_artifact_id": patch.artifact_id,
                        "patch_sha256": patch.sha256,
                    }
                ),
                "patch.joined",
                {},
            )

        async def cleanup_graph_children(self, parent: Run) -> None:
            assert all(not h.state.outstanding_leases(seed.run.run_id) for seed in h.children)

        def remaining_graph_active_seconds(self, parent_run_id: str) -> float:
            return 60.0

    hooks = Hooks()
    result = await GraphCoordinator(h.graphs, h.state, hooks, h.clock).drive(parent.run_id)
    assert result.stage is WorkflowStage.VERIFYING
    graph = h.graphs.get(parent.run_id)
    assert graph is not None and graph.status is GraphStatus.JOINED
    assert graph.driver_claim is None and hooks.joins == 1 and hooks.entered == 2
    assert all(
        node.status is GraphNodeStatus.SUCCEEDED and len(node.output_artifacts) == 3
        for node in graph.nodes
    )
    repeated = await GraphCoordinator(h.reopen(), h.state, hooks, h.clock).drive(parent.run_id)
    assert repeated == result and hooks.joins == 1 and hooks.entered == 2

    # Two reconstructed approved-parent drivers cannot both begin verification/repair.
    barrier = Barrier(2)

    def continuation() -> GraphDriverClaim | ErrorCode:
        barrier.wait()
        try:
            return h.reopen().claim_continuation(parent.run_id, expected_revision=graph.revision)
        except FleetError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(continuation) for _ in range(2)]
        outcomes = [future.result(timeout=10) for future in futures]
    winners = [item for item in outcomes if isinstance(item, GraphDriverClaim)]
    assert len(winners) == 1 and outcomes.count(ErrorCode.RECOVERY_REQUIRED) == 1
    owned = h.reopen().get(parent.run_id)
    assert owned is not None and owned.status is GraphStatus.RUNNING
    assert owned.driver_claim == winners[0] and owned.join_completion == graph.join_completion
    with pytest.raises(FleetError):
        h.reopen().claim_continuation(parent.run_id, expected_revision=owned.revision)
    released = h.graphs.release_driver(
        winners[0], expected_revision=owned.revision, status=GraphStatus.JOINED
    )
    assert released.join_completion == graph.join_completion
    with pytest.raises(FleetError):
        h.graphs.claim_driver(parent.run_id, expected_revision=released.revision)

    # A metadata-compatible but unauthorized parent stage/status cannot acquire continuation.
    original = h.state.get_run(parent.run_id)
    assert original.stage is WorkflowStage.VERIFYING
    for status, stage in (
        (RunStatus.RUNNING, WorkflowStage.IMPLEMENTING),
        (RunStatus.READY_FOR_REVIEW, WorkflowStage.PRESENTING),
        (RunStatus.FAILED, WorkflowStage.VERIFYING),
    ):
        altered = original.model_copy(update={"status": status, "stage": stage})
        with sqlite3.connect(h.state.database_path) as connection:
            connection.execute(
                "UPDATE runs SET status=?,stage=?,data_json=? WHERE run_id=?",
                (status.value, stage.value, altered.model_dump_json(), parent.run_id),
            )
        with pytest.raises(FleetError):
            h.graphs.claim_continuation(parent.run_id, expected_revision=released.revision)
    with sqlite3.connect(h.state.database_path) as connection:
        connection.execute(
            "UPDATE runs SET status=?,stage=?,data_json=? WHERE run_id=?",
            (
                original.status.value,
                original.stage.value,
                original.model_dump_json(),
                parent.run_id,
            ),
        )

    assert original.task_id is not None
    agent = AgentInstance(
        agent_instance_id=h.state.ids.new(IdPrefix.AGENT),
        run_id=original.run_id,
        task_id=original.task_id,
        role="verifier",
        status=AgentStatus.RUNNING,
        iteration=0,
        created_at=h.clock.now(),
    )
    h.state.save_agent_instance(agent)
    intent = ToolIntent(
        intent_id=h.state.ids.new(IdPrefix.INTENT),
        run_id=original.run_id,
        task_id=original.task_id,
        agent_instance_id=agent.agent_instance_id,
        principal_role="verifier",
        workflow="code-change",
        stage=WorkflowStage.VERIFYING,
        action="command.run",
        resource=CanonicalResource(kind="project_command", identifier="python-test"),
        parameters={},
        reason="Exact parent verification",
        side_effect=True,
        idempotency_key="parent-verification",
    )
    digest = canonical_json_hash(intent.model_dump(mode="json"))
    approval = ApprovalRequest(
        request_id=h.state.ids.new(IdPrefix.APPROVAL),
        intent_id=intent.intent_id,
        run_id=parent.run_id,
        intent_hash=digest,
        principal_role="verifier",
        action=intent.action,
        resource=intent.resource,
        reason=intent.reason,
        created_at=h.clock.now(),
        expires_at=h.clock.now() + timedelta(minutes=5),
    )
    h.state.create_approval_and_pause(intent, digest, approval)
    with pytest.raises(FleetError):
        h.graphs.claim_continuation(parent.run_id, expected_revision=released.revision)
    h.state.resolve_approval(approval.request_id, approve=True, denial_reason=None)
    claim = h.graphs.claim_continuation(parent.run_id, expected_revision=released.revision)
    latest = h.graphs.get(parent.run_id)
    assert latest is not None and latest.driver_claim == claim
    final = h.graphs.release_driver(
        claim, expected_revision=latest.revision, status=GraphStatus.JOINED
    )
    assert final.join_completion == graph.join_completion and hooks.joins == 1


def test_read_only_specialist_dependencies_require_exact_typed_report_and_cleanup(
    tmp_path: Path,
) -> None:
    h = graph_harness(tmp_path)
    parent_task = h.state.get_task(h.plan.task_id)
    roles = ["researcher", "architect", "engineer", "verifier"]
    nodes = [
        FleetPlanNode(
            node_id=role,
            role_id=role,
            goal=f"Bounded {role}",
            criterion_ids=[item.criterion_id for item in parent_task.acceptance_criteria],
            scope=parent_task.allowed_paths,
            depends_on=[] if i == 0 else [roles[i - 1]],
            can_write=role == "engineer",
            requires_workspace=True,
            independent_verifier=role == "verifier",
        )
        for i, role in enumerate(roles)
    ]
    plan = h.plan.model_copy(
        update={
            "strategy": FleetStrategy.RESEARCH_ARCHITECT_ENGINEER_VERIFIER,
            "nodes": nodes,
            "max_parallel_agents": 1,
        }
    )
    artifact = h.artifacts.create_text(
        kind=ArtifactKind.FLEET_PLAN,
        project_id=h.parent.project_id,
        run_id=h.parent.run_id,
        task_id=parent_task.task_id,
        producer="test",
        content=plan.model_dump_json(indent=2),
    )
    parent = h.state.save_run(
        h.parent.model_copy(
            update={
                "fleet_plan_artifact_id": artifact.artifact_id,
                "fleet_plan_hash": artifact.sha256,
                "fleet_strategy": plan.strategy.value,
            }
        ),
        "plan.bound",
        {},
    )
    seeds = []
    for node in nodes[:-1]:
        task = parent_task.model_copy(
            update={
                "run_id": h.state.ids.new(IdPrefix.RUN),
                "task_id": h.state.ids.new(IdPrefix.TASK),
                "original_goal": node.goal,
                "normalized_goal": node.goal,
                "change_kind": "code_change" if node.can_write else "read_only",
                "required_evidence": ["canonical_patch", "command_evidence"]
                if node.can_write
                else ["control_plane_plan"],
            }
        )
        child = h.children[0].run.model_copy(
            update={
                "run_id": task.run_id,
                "task_id": task.task_id,
                "correlation_id": h.state.ids.new(IdPrefix.CORRELATION),
                "goal": node.goal,
                "parent_node_id": node.node_id,
                "parent_plan_sha256": artifact.sha256,
            }
        )
        seeds.append(GraphChildSeed(node_id=node.node_id, run=child, task=task))
    h.parent, h.plan, h.children = parent, plan, tuple(seeds)
    h.initialize()
    claim = h.graphs.claim_driver(parent.run_id, expected_revision=0)
    for i in range(3):
        h.prepare(i)
    with pytest.raises(FleetError):
        h.graphs.transition_node(
            claim, "architect", 0, expected_revision=0, target=GraphNodeStatus.RUNNING
        )
    h.graphs.transition_node(
        claim, "researcher", 0, expected_revision=0, target=GraphNodeStatus.RUNNING
    )
    child = h.run_child(0)
    refs = []
    report = SpecialistReport(
        role="researcher",
        summary="Bounded repository findings",
        findings=["Observed a module"],
        recommendations=[],
        proof_gaps=[],
    )
    cleanup = ResourceCleanupReceipt(
        run_id=child.run_id, leases=[], complete=True, completed_at=h.clock.now()
    )
    for kind, content in (
        (ArtifactKind.SPECIALIST_REPORT, report.model_dump_json(indent=2)),
        (ArtifactKind.RESOURCE_CLEANUP, cleanup.model_dump_json(indent=2)),
    ):
        metadata = h.artifacts.create_text(
            kind=kind,
            project_id=child.project_id,
            run_id=child.run_id,
            task_id=child.task_id,
            producer="test",
            content=content,
        )
        refs.append(
            GraphArtifactRef(
                artifact_id=metadata.artifact_id,
                sha256=metadata.sha256,
                run_id=child.run_id,
                kind=kind,
            )
        )
    child = h.state.save_run(
        child.model_copy(
            update={
                "stage": WorkflowStage.PRESENTING,
                "cleanup_receipt_artifact_id": refs[1].artifact_id,
                "cleanup_receipt_sha256": refs[1].sha256,
            }
        ),
        "presenting",
        {},
    )
    h.state.save_run(child.model_copy(update={"status": RunStatus.COMPLETED}), "completed", {})
    finished = h.graphs.transition_node(
        claim,
        "researcher",
        0,
        expected_revision=1,
        target=GraphNodeStatus.SUCCEEDED,
        output_artifacts=tuple(refs),
    )
    with pytest.raises(FleetError):
        h.graphs.transition_node(
            claim,
            "architect",
            0,
            expected_revision=0,
            target=GraphNodeStatus.RUNNING,
            input_artifacts=(refs[0],),
        )
    architect = h.graphs.transition_node(
        claim,
        "architect",
        0,
        expected_revision=0,
        target=GraphNodeStatus.RUNNING,
        input_artifacts=finished.output_artifacts,
    )
    assert architect.input_artifacts == tuple(refs)
    assert h.state.get_run(seeds[2].run.run_id).status is RunStatus.CREATED


def test_migration_six_is_atomic_and_preserves_existing_version_five_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with monkeypatch.context() as scoped:
        scoped.setattr(sqlite_adapter, "SUPPORTED_SCHEMA_VERSION", 5)
        h = graph_harness(tmp_path)
    original = h.state.get_run(h.parent.run_id)
    split = sqlite_adapter._split_sql

    def broken(script: str) -> list[str]:
        statements = split(script)
        return (
            [*statements, "SELECT deliberately_missing FROM no_such_table"]
            if "CREATE TABLE fleet_graphs" in script
            else statements
        )

    with monkeypatch.context() as scoped:
        scoped.setattr(sqlite_adapter, "_split_sql", broken)
        with pytest.raises(FleetError):
            h.state.migrate()
    with sqlite3.connect(h.state.database_path) as connection:
        assert connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 5
        assert (
            connection.execute(
                "SELECT name FROM sqlite_master WHERE name='fleet_graphs'"
            ).fetchone()
            is None
        )
    assert h.state.get_run(original.run_id) == original
    assert h.state.migrate() == 8
    assert h.state.get_run(original.run_id) == original
    assert h.initialize() == h.reopen().get(original.run_id)
