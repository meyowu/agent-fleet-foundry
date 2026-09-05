"""Admission and existing aggregate writes form one real SQLite rollback unit."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

import pytest

from agent_fleet.adapters.artifacts.local import LocalArtifactStore
from agent_fleet.adapters.config.yaml import YamlConfigurationAdapter
from agent_fleet.adapters.persistence import evolution
from agent_fleet.adapters.persistence.conversations import SqliteConversationStore
from agent_fleet.adapters.persistence.evolution import SqliteOrganizationStore
from agent_fleet.adapters.persistence.graphs import SqliteGraphStore
from agent_fleet.adapters.persistence.sqlite import SqliteStateStore
from agent_fleet.adapters.system import SystemClock, UuidIdGenerator
from agent_fleet.application.artifacts import ArtifactService
from agent_fleet.domain.budgets import RunBudgetLimits
from agent_fleet.domain.conversation import (
    Conversation,
    ConversationContext,
    ConversationRegistration,
    ConversationSubmission,
    ConversationSummary,
)
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.evolution import (
    FleetPatchProposalRecord,
    OrganizationAdmission,
    describe_fleet_patch,
    evolve_tree,
)
from agent_fleet.domain.fleet_plan import FleetPlan, FleetPlanNode, FleetStrategy
from agent_fleet.domain.graph import GraphChildSeed
from agent_fleet.domain.ids import IdPrefix
from agent_fleet.domain.models import (
    AcceptanceCriterion,
    ArtifactKind,
    FleetPatch,
    FleetPatchFileChange,
    FleetPatchOperation,
    Project,
    RepositoryInfo,
    Run,
    RunStatus,
    TaskSpec,
    WorkflowStage,
)
from agent_fleet.domain.organization_tree import (
    DirectoryIdentity,
    OrganizationDirectory,
    OrganizationFile,
    OrganizationTree,
    PreparedPublication,
)
from agent_fleet.domain.repository_boundary import OrganizationRepositoryBoundary
from agent_fleet.domain.security import Redactor, canonical_json_hash, sha256_bytes


@dataclass
class AdmissionHarness:
    state: SqliteStateStore
    organizations: SqliteOrganizationStore
    conversations: SqliteConversationStore
    project: Project
    tree: OrganizationTree
    conversation: Conversation

    def baseline(self) -> OrganizationAdmission:
        assert self.project.fleet_spec_hash is not None
        head = self.organizations.register_baseline(
            self.project, self.tree, self.project.fleet_spec_hash
        )
        return OrganizationAdmission(
            project_id=head.project_id,
            revision=head.revision,
            tree_sha256=head.tree_sha256,
            config_snapshot_sha256=head.config_snapshot_sha256,
        )

    def run(self) -> Run:
        now = self.state.clock.now()
        return Run(
            run_id=self.state.ids.new(IdPrefix.RUN),
            project_id=self.project.project_id,
            correlation_id=self.state.ids.new(IdPrefix.CORRELATION),
            goal="Explain the bounded repository",
            base_revision="a" * 40,
            target_status_fingerprint="b" * 64,
            config_snapshot_hash=self.project.fleet_spec_hash,
            created_at=now,
            updated_at=now,
        )

    def submission(self) -> ConversationSubmission:
        return ConversationSubmission(
            conversation_id=self.conversation.conversation_id,
            project_id=self.project.project_id,
            repository_identity=self.project.identity_hash,
            submission_key="exact-request",
            expected_revision=0,
            context=ConversationContext(
                conversation_id=self.conversation.conversation_id,
                project_id=self.project.project_id,
                through_sequence=0,
                entries=(),
            ),
            user_summary=ConversationSummary(text="Explain the bounded repository"),
        )

    def register_chat(
        self, run: Run, admission: OrganizationAdmission | None
    ) -> ConversationRegistration:
        assert self.project.fleet_spec_hash is not None
        return self.conversations.register_turn_run(
            self.submission(),
            run,
            config_snapshot_sha256=self.project.fleet_spec_hash,
            budget_limits=RunBudgetLimits(),
            organization_admission=admission,
        )

    def register(
        self, kind: Literal["ordinary", "chat"], run: Run, admission: OrganizationAdmission | None
    ) -> None:
        if kind == "ordinary":
            self.state.create_run(run, organization_admission=admission)
        else:
            self.register_chat(run, admission)


@pytest.fixture
def harness(tmp_path: Path) -> AdmissionHarness:
    state = SqliteStateStore(tmp_path / "state.db", SystemClock(), UuidIdGenerator(), Redactor())
    state.migrate()
    config = YamlConfigurationAdapter()
    files = config.default_files("admission-fixture")
    _, snapshot = config.snapshot_from_files(files)
    directories = {"."}
    for path in files:
        directories.update(str(parent) for parent in PurePosixPath(path).parents)
    tree = OrganizationTree(
        files=tuple(
            OrganizationFile(
                path=path, content=content, sha256=sha256_bytes(content.encode()), mode=0o600
            )
            for path, content in sorted(files.items())
        ),
        directories=tuple(
            OrganizationDirectory(path=path, mode=0o700) for path in sorted(directories)
        ),
    )
    now = state.clock.now()
    project = Project(
        project_id=state.ids.new(IdPrefix.PROJECT),
        canonical_root=str(tmp_path / "repository"),
        identity_hash="c" * 64,
        fleet_spec_hash=config.snapshot_hash(snapshot),
        created_at=now,
        updated_at=now,
    )
    state.save_project(project)
    organizations = SqliteOrganizationStore(
        state.database_path, state.clock, state.ids, state.redactor, state, config
    )
    conversations = SqliteConversationStore(
        state.database_path, state.clock, state.ids, state.redactor, state
    )
    conversation = conversations.create(project.project_id, project.identity_hash)
    return AdmissionHarness(state, organizations, conversations, project, tree, conversation)


def _rows(state: SqliteStateStore) -> dict[str, tuple[tuple[object, ...], ...]]:
    with state._connect() as connection:
        names = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
        ]
        return {
            name: tuple(tuple(row) for row in connection.execute(f'SELECT * FROM "{name}"'))
            for name in names
        }


def _reject_after_admission(monkeypatch: pytest.MonkeyPatch, *, fail_on_call: int = 1) -> list[str]:
    original = evolution.record_organization_admission
    admitted: list[str] = []

    def injected(
        connection: sqlite3.Connection,
        run: Run,
        admission: OrganizationAdmission | None,
        *,
        parent_run_id: str | None = None,
        redactor: Redactor | None = None,
    ) -> None:
        assert connection.in_transaction
        original(connection, run, admission, parent_run_id=parent_run_id, redactor=redactor)
        admitted.append(run.run_id)
        if len(admitted) == fail_on_call:
            raise FleetError(
                ErrorCode.RECOVERY_REQUIRED,
                "Injected admission persistence failure",
                "Exercise rollback only.",
            )

    monkeypatch.setattr(evolution, "record_organization_admission", injected)
    return admitted


@pytest.mark.parametrize("kind", ["ordinary", "chat"])
def test_legacy_registration_preserves_run_and_project_bytes(
    harness: AdmissionHarness, kind: Literal["ordinary", "chat"]
) -> None:
    h = harness
    run = h.run()
    h.register(kind, run, None)
    assert h.organizations.admission_for_run(run.run_id) is None
    assert h.state.get_run(run.run_id).model_dump_json() == run.model_dump_json()
    assert (
        h.state.get_project(h.project.project_id).model_dump_json() == h.project.model_dump_json()
    )
    assert h.state.list_events(run.run_id)[0].event_type == "run.created"


@pytest.mark.parametrize("kind", ["ordinary", "chat"])
def test_exact_admission_is_registered_with_run_without_changing_its_wire_identity(
    harness: AdmissionHarness, kind: Literal["ordinary", "chat"]
) -> None:
    h = harness
    admission = h.baseline()
    run = h.run()
    h.register(kind, run, admission)
    assert h.organizations.admission_for_run(run.run_id) == admission
    assert h.state.get_run(run.run_id).model_dump_json() == run.model_dump_json()
    assert h.state.list_events(run.run_id)[0].event_type == "run.created"


@pytest.mark.parametrize("kind", ["ordinary", "chat"])
@pytest.mark.parametrize("failure", ["missing", "revision", "tree", "config", "project"])
def test_missing_or_stale_admission_leaves_no_partial_aggregate(
    harness: AdmissionHarness,
    kind: Literal["ordinary", "chat"],
    failure: str,
) -> None:
    h = harness
    admission: OrganizationAdmission | None = h.baseline()
    if failure == "missing":
        admission = None
    else:
        assert admission is not None
        field, value = {
            "revision": ("revision", 1),
            "tree": ("tree_sha256", "d" * 64),
            "config": ("config_snapshot_sha256", "e" * 64),
            "project": ("project_id", "prj_" + "f" * 32),
        }[failure]
        admission = admission.model_copy(update={field: value})
    before = _rows(h.state)
    with pytest.raises(FleetError):
        h.register(kind, h.run(), admission)
    assert _rows(h.state) == before


@pytest.mark.parametrize("kind", ["ordinary", "chat"])
def test_failure_after_real_admission_insert_rolls_back_every_record(
    harness: AdmissionHarness,
    monkeypatch: pytest.MonkeyPatch,
    kind: Literal["ordinary", "chat"],
) -> None:
    h = harness
    admission = h.baseline()
    run = h.run()
    before = _rows(h.state)
    admitted = _reject_after_admission(monkeypatch)
    with pytest.raises(FleetError, match="Injected admission"):
        h.register(kind, run, admission)
    assert admitted == [run.run_id]
    assert _rows(h.state) == before


def test_chat_duplicate_keeps_original_admission_and_never_reacquires_owner(
    harness: AdmissionHarness,
) -> None:
    h = harness
    admission = h.baseline()
    original_run = h.run()
    first = h.register_chat(original_run, admission)
    before = _rows(h.state)
    for stale in (None, admission.model_copy(update={"revision": 100})):
        duplicate = h.register_chat(h.run(), stale)
        assert duplicate.turn == first.turn
        assert duplicate.claim is None
        assert _rows(h.state) == before
    assert h.organizations.admission_for_run(original_run.run_id) == admission


def test_late_chat_failure_rolls_back_admission_run_turn_claim_and_events(
    harness: AdmissionHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = harness
    admission = h.baseline()
    before = _rows(h.state)
    original = h.conversations._write_conversation

    def injected(connection: sqlite3.Connection, value: Conversation, *, new: bool = False) -> None:
        original(connection, value, new=new)
        assert connection.execute("SELECT COUNT(*) FROM conversation_turns").fetchone()[0] == 1
        assert (
            connection.execute("SELECT COUNT(*) FROM conversation_turn_claims").fetchone()[0] == 1
        )
        assert (
            connection.execute("SELECT COUNT(*) FROM organization_run_admissions").fetchone()[0]
            == 1
        )
        raise FleetError(
            ErrorCode.RECOVERY_REQUIRED, "Injected late chat failure", "Exercise rollback."
        )

    monkeypatch.setattr(h.conversations, "_write_conversation", injected)
    with pytest.raises(FleetError, match="Injected late chat"):
        h.register_chat(h.run(), admission)
    assert _rows(h.state) == before


def test_headed_project_only_accepts_identical_existing_project(harness: AdmissionHarness) -> None:
    h = harness
    h.baseline()
    before = _rows(h.state)
    h.state.save_project(h.project)
    assert _rows(h.state) == before
    for field, value in (
        ("fleet_spec_hash", "e" * 64),
        ("canonical_root", str(Path(h.project.canonical_root).with_name("other"))),
        ("updated_at", h.state.clock.now()),
    ):
        with pytest.raises(FleetError):
            h.state.save_project(h.project.model_copy(update={field: value}))
        assert _rows(h.state) == before


def _prepare_publication_fence(h: AdmissionHarness) -> OrganizationAdmission:
    """Journal fixture receipts prove a durable fence, not filesystem exchange."""
    admission = h.baseline()
    source = h.run()
    h.state.create_run(source, organization_admission=admission)
    for stage in (WorkflowStage.INTAKE, WorkflowStage.SCOPING, WorkflowStage.PRESENTING):
        source = h.state.save_run(
            source.model_copy(update={"status": RunStatus.RUNNING, "stage": stage}),
            "run.stage_changed",
            {},
        )
    h.state.save_run(source.model_copy(update={"status": RunStatus.COMPLETED}), "run.completed", {})
    old = next(file for file in h.tree.files if file.path == "README.md")
    content = old.content + "\nReviewed documentation update.\n"
    patch = FleetPatch(
        fleet_patch_id="fpatch_" + "1" * 32,
        project_id=h.project.project_id,
        base_fleet_spec_sha256=admission.config_snapshot_sha256,
        changes=[
            FleetPatchFileChange(
                operation=FleetPatchOperation.REPLACE,
                path=".fleet/README.md",
                before_sha256=old.sha256,
                after_sha256=sha256_bytes(content.encode()),
                content=content,
            )
        ],
        rationale="Update reviewable documentation only.",
    )
    after = evolve_tree(h.tree, patch)
    diff, semantics = describe_fleet_patch(h.tree, after, patch)
    h.organizations.save_proposal(
        FleetPatchProposalRecord(
            patch=patch,
            source_run_id=source.run_id,
            base=admission,
            before_tree_sha256=h.tree.sha256,
            after_tree_sha256=after.sha256,
            before_config_snapshot_sha256=admission.config_snapshot_sha256,
            after_config_snapshot_sha256=admission.config_snapshot_sha256,
            text_diff=diff,
            semantic_changes=semantics,
            created_at=h.state.clock.now(),
        ),
        h.tree,
        after,
    )
    identities = [
        DirectoryIdentity(device=1, inode=index, uid=0, mode=0o700) for index in range(1, 6)
    ]
    operation_id = "fop_" + "2" * 32
    publication = PreparedPublication(
        operation_id=operation_id,
        project_id=h.project.project_id,
        repository_identity=h.project.identity_hash,
        repository_basename=Path(h.project.canonical_root).name,
        parent_identity=identities[0],
        repository_directory_identity=identities[1],
        target_identity=identities[2],
        scratch_basename=".fleet-publication-" + operation_id,
        scratch_identity=identities[3],
        staged_identity=identities[4],
        before_sha256=h.tree.sha256,
        after_sha256=after.sha256,
        backend="linux-renameat2",
        durability="fsync",
    )
    operation = h.organizations.prepare_operation(
        h.project,
        patch.fleet_patch_id,
        publication,
        authorization="apply",
        repository_before=OrganizationRepositoryBoundary(
            repository=RepositoryInfo(
                root=h.project.canonical_root,
                head_revision="a" * 40,
                remote_fingerprint=None,
                identity_hash=h.project.identity_hash,
                status_porcelain="",
                status_fingerprint=sha256_bytes(b""),
                dirty_paths=[],
            ),
            index_sha256="0" * 64,
            non_organization_status_sha256=canonical_json_hash([]),
        ),
    )
    assert operation.status == "prepared"
    return admission


@pytest.mark.parametrize("kind", ["ordinary", "chat", "project"])
def test_real_pending_publication_fence_blocks_existing_registration_transactions(
    harness: AdmissionHarness, kind: str
) -> None:
    h = harness
    admission = _prepare_publication_fence(h)
    before = _rows(h.state)
    with pytest.raises(FleetError):
        if kind == "project":
            h.state.save_project(h.project)
        elif kind == "ordinary":
            h.state.create_run(h.run(), organization_admission=admission)
        else:
            h.register_chat(h.run(), admission)
    assert _rows(h.state) == before


def _graph(
    h: AdmissionHarness, *, admitted: bool
) -> tuple[SqliteGraphStore, Run, FleetPlan, tuple[GraphChildSeed, ...]]:
    admission = h.baseline() if admitted else None
    parent = h.run()
    h.state.create_run(parent, organization_admission=admission)
    for stage in (WorkflowStage.INTAKE, WorkflowStage.SCOPING):
        parent = h.state.save_run(
            parent.model_copy(update={"status": RunStatus.RUNNING, "stage": stage}),
            "run.stage_changed",
            {},
        )
    task = TaskSpec(
        task_id=h.state.ids.new(IdPrefix.TASK),
        run_id=parent.run_id,
        original_goal=parent.goal,
        normalized_goal=parent.goal,
        base_revision=parent.base_revision,
        allowed_paths=["src/left.py", "src/right.py"],
        forbidden_paths=[".git", ".fleet"],
        acceptance_criteria=[
            AcceptanceCriterion(criterion_id=f"criterion-{i}", description=f"Change {i}")
            for i in range(2)
        ],
        required_evidence=["canonical_patch", "command_evidence", "independent_verifier_verdict"],
        max_repair_iterations=parent.max_repair_iterations,
        config_snapshot_hash=parent.config_snapshot_hash,
        created_at=h.state.clock.now(),
    )
    h.state.save_task(task)
    writers = [
        FleetPlanNode(
            node_id=f"writer-{i}",
            role_id="engineer",
            goal=f"Change {i}",
            criterion_ids=[task.acceptance_criteria[i].criterion_id],
            scope=[task.allowed_paths[i]],
            can_write=True,
            requires_workspace=True,
        )
        for i in range(2)
    ]
    plan = FleetPlan(
        plan_id=h.state.ids.new(IdPrefix.FLEET_PLAN),
        run_id=parent.run_id,
        task_id=task.task_id,
        strategy=FleetStrategy.PARALLEL_ENGINEERS,
        nodes=[
            *writers,
            FleetPlanNode(
                node_id="verify",
                role_id="verifier",
                scope=task.allowed_paths,
                depends_on=[node.node_id for node in writers],
                requires_workspace=True,
                independent_verifier=True,
            ),
        ],
        max_parallel_agents=2,
        required_evidence=task.required_evidence,
        rationale="Two disjoint bounded changes",
        created_at=h.state.clock.now(),
    )
    artifacts = ArtifactService(
        LocalArtifactStore(h.state.database_path.parent / "artifacts"),
        h.state,
        h.state.clock,
        h.state.ids,
        h.state.redactor,
    )
    artifact = artifacts.create_text(
        kind=ArtifactKind.FLEET_PLAN,
        project_id=parent.project_id,
        run_id=parent.run_id,
        task_id=task.task_id,
        producer="test",
        content=plan.model_dump_json(indent=2),
    )
    parent = h.state.save_run(
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
    children = []
    for i, node in enumerate(writers):
        child_task = task.model_copy(
            update={
                "run_id": h.state.ids.new(IdPrefix.RUN),
                "task_id": h.state.ids.new(IdPrefix.TASK),
                "original_goal": node.goal,
                "normalized_goal": node.goal,
                "allowed_paths": node.scope,
                "acceptance_criteria": [task.acceptance_criteria[i]],
                "required_evidence": ["canonical_patch", "command_evidence"],
            }
        )
        child = h.run().model_copy(
            update={
                "run_id": child_task.run_id,
                "goal": node.goal,
                "task_id": child_task.task_id,
                "parent_run_id": parent.run_id,
                "parent_plan_sha256": artifact.sha256,
                "parent_node_id": node.node_id,
                "parent_iteration": 0,
            }
        )
        children.append(GraphChildSeed(node_id=node.node_id, run=child, task=child_task))
    graphs = SqliteGraphStore(
        h.state.database_path, h.state.clock, h.state.ids, h.state.redactor, artifacts.store
    )
    return graphs, parent, plan, tuple(children)


def test_graph_children_inherit_exact_parent_admission_without_wire_changes(
    harness: AdmissionHarness,
) -> None:
    h = harness
    graphs, parent, plan, children = _graph(h, admitted=True)
    admission = h.organizations.admission_for_run(parent.run_id)
    assert admission is not None
    snapshot = graphs.initialize(parent.run_id, plan, children)
    before = _rows(h.state)
    for child in children:
        assert h.organizations.admission_for_run(child.run.run_id) == admission
        assert h.state.get_run(child.run.run_id).model_dump_json() == child.run.model_dump_json()
    assert graphs.initialize(parent.run_id, plan, children) == snapshot
    assert _rows(h.state) == before


def test_graph_missing_parent_admission_rejects_all_children_after_baseline(
    harness: AdmissionHarness,
) -> None:
    h = harness
    graphs, parent, plan, children = _graph(h, admitted=False)
    h.baseline()
    before = _rows(h.state)
    with pytest.raises(FleetError):
        graphs.initialize(parent.run_id, plan, children)
    assert _rows(h.state) == before


def test_second_child_admission_failure_rolls_back_prior_child_task_events_and_graph(
    harness: AdmissionHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = harness
    graphs, parent, plan, children = _graph(h, admitted=True)
    before = _rows(h.state)
    admitted = _reject_after_admission(monkeypatch, fail_on_call=2)
    with pytest.raises(FleetError, match="Injected admission"):
        graphs.initialize(parent.run_id, plan, children)
    assert admitted == [child.run.run_id for child in children]
    assert _rows(h.state) == before


class ExplosiveAdmission(OrganizationAdmission):
    def __eq__(self, other: object) -> bool:
        raise AssertionError("Untrusted admission subclasses must not be compared")


@pytest.mark.parametrize("kind", ["ordinary", "chat"])
@pytest.mark.parametrize("malformation", ["subclass", "model_copy"])
def test_untrusted_admission_is_revalidated_before_equality_or_persistence(
    harness: AdmissionHarness,
    kind: Literal["ordinary", "chat"],
    malformation: str,
) -> None:
    h = harness
    admission = h.baseline()
    if malformation == "subclass":
        admission = ExplosiveAdmission.model_validate(admission.model_dump(mode="json"))
    else:
        admission = admission.model_copy(update={"revision": "not an integer"})
    before = _rows(h.state)
    with pytest.raises(FleetError) as caught:
        h.register(kind, h.run(), admission)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert _rows(h.state) == before
