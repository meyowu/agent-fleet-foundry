"""Real SQLite journal proofs; publication receipts here are explicit test fixtures."""

from __future__ import annotations

import base64
import sqlite3
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from threading import Barrier
from typing import Any

import pytest

from agent_fleet.adapters.artifacts.local import LocalArtifactStore
from agent_fleet.adapters.config.yaml import YamlConfigurationAdapter
from agent_fleet.adapters.persistence import evolution
from agent_fleet.adapters.persistence import sqlite as sqlite_adapter
from agent_fleet.adapters.persistence.conversations import SqliteConversationStore
from agent_fleet.adapters.persistence.evolution import SqliteOrganizationStore
from agent_fleet.adapters.persistence.graphs import SqliteGraphStore
from agent_fleet.adapters.persistence.sqlite import SqliteStateStore
from agent_fleet.adapters.system import UuidIdGenerator
from agent_fleet.application.artifacts import ArtifactService
from agent_fleet.domain.budgets import RunBudgetLimits
from agent_fleet.domain.conversation import (
    ConversationContext,
    ConversationSubmission,
    ConversationSummary,
)
from agent_fleet.domain.errors import FleetError
from agent_fleet.domain.evolution import (
    FleetPatchProposalRecord,
    OrganizationHead,
    describe_fleet_patch,
    evolve_tree,
)
from agent_fleet.domain.fleet_plan import FleetPlan, FleetPlanNode, FleetStrategy
from agent_fleet.domain.graph import GraphChildSeed, GraphStatus
from agent_fleet.domain.ids import IdPrefix
from agent_fleet.domain.models import (
    AcceptanceCriterion,
    ArtifactKind,
    ArtifactMetadata,
    FleetPatch,
    FleetPatchFileChange,
    FleetPatchOperation,
    LeaseKind,
    LeaseStatus,
    Project,
    RepositoryInfo,
    ResourceLease,
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
    OrganizationXattr,
    PreparedPublication,
    PublicationObservation,
)
from agent_fleet.domain.repository_boundary import OrganizationRepositoryBoundary
from agent_fleet.domain.security import Redactor, canonical_json_hash, sha256_bytes


@dataclass
class JournalClock:
    value: datetime

    def now(self) -> datetime:
        return self.value


@dataclass
class JournalHarness:
    state: SqliteStateStore
    journal: SqliteOrganizationStore
    config: YamlConfigurationAdapter
    project: Project
    tree: OrganizationTree
    head: OrganizationHead
    source: Run

    def reopen(self) -> SqliteOrganizationStore:
        return SqliteOrganizationStore(
            self.state.database_path,
            self.state.clock,
            self.state.ids,
            self.state.redactor,
            self.state,
            self.config,
        )

    def proposal(
        self,
        *,
        path: str = "README.md",
        content: str = "Reviewed documentation\n",
        operation: FleetPatchOperation = FleetPatchOperation.REPLACE,
        source: Run | None = None,
    ) -> tuple[FleetPatchProposalRecord, OrganizationTree]:
        head = self.journal.get_head(self.project.project_id)
        assert head is not None
        before = self.journal.get_tree(head.tree_sha256)
        old = next((item for item in before.files if item.path == path), None)
        patch = FleetPatch(
            fleet_patch_id=self.state.ids.new(IdPrefix.FLEET_PATCH),
            project_id=self.project.project_id,
            base_fleet_spec_sha256=head.config_snapshot_sha256,
            changes=[
                FleetPatchFileChange(
                    operation=operation,
                    path=".fleet/" + path,
                    before_sha256=old.sha256 if old else None,
                    after_sha256=None
                    if operation is FleetPatchOperation.REMOVE
                    else sha256_bytes(content.encode()),
                    content=None if operation is FleetPatchOperation.REMOVE else content,
                )
            ],
            rationale="User-requested reviewed organization update",
        )
        after = evolve_tree(before, patch)
        text, semantic = describe_fleet_patch(before, after, patch)
        _, snapshot = self.config.snapshot_from_files(
            {item.path: item.content for item in after.files}
        )
        proposal = FleetPatchProposalRecord(
            patch=patch,
            source_run_id=(source or self.source).run_id,
            base=head.admission,
            before_tree_sha256=before.sha256,
            after_tree_sha256=after.sha256,
            before_config_snapshot_sha256=head.config_snapshot_sha256,
            after_config_snapshot_sha256=self.config.snapshot_hash(snapshot),
            text_diff=text,
            semantic_changes=semantic,
            created_at=self.state.clock.now(),
        )
        return self.journal.save_proposal(proposal, before, after), after

    def publication(self, proposal: FleetPatchProposalRecord) -> PreparedPublication:
        operation_id = "fop_" + self.state.ids.new(IdPrefix.CORRELATION).removeprefix("corr_")

        def identity(inode: int) -> DirectoryIdentity:
            return DirectoryIdentity(device=1, inode=inode, uid=501, mode=0o700)

        return PreparedPublication(
            operation_id=operation_id,
            project_id=self.project.project_id,
            repository_identity=self.project.identity_hash,
            repository_basename="repository",
            parent_identity=identity(1),
            repository_directory_identity=identity(2),
            target_identity=identity(3),
            scratch_basename=".fleet-publication-" + operation_id,
            scratch_identity=identity(4),
            staged_identity=identity(5),
            before_sha256=proposal.before_tree_sha256,
            after_sha256=proposal.after_tree_sha256,
            backend="linux-renameat2",
            durability="fsync",
        )

    def boundary(self) -> OrganizationRepositoryBoundary:
        return OrganizationRepositoryBoundary(
            repository=RepositoryInfo(
                root=self.project.canonical_root,
                identity_hash=self.project.identity_hash,
                head_revision="a" * 40,
                remote_fingerprint=None,
                status_porcelain="",
                status_fingerprint=sha256_bytes(b""),
                dirty_paths=[],
            ),
            index_sha256="b" * 64,
            non_organization_status_sha256=canonical_json_hash([]),
        )

    def prepare(
        self, proposal: FleetPatchProposalRecord, publication: PreparedPublication | None = None
    ) -> PreparedPublication:
        publication = publication or self.publication(proposal)
        self.journal.prepare_operation(
            self.state.get_project(self.project.project_id),
            proposal.patch.fleet_patch_id,
            publication,
            authorization="rollback" if proposal.patch.rollback_of else "apply",
            repository_before=self.boundary(),
        )
        return publication

    def project_after(self, after: OrganizationTree) -> Project:
        _, snapshot = self.config.snapshot_from_files(
            {item.path: item.content for item in after.files}
        )
        digest = self.config.snapshot_hash(snapshot)
        artifact = ArtifactMetadata(
            artifact_id=self.state.ids.new(IdPrefix.ARTIFACT),
            kind=ArtifactKind.CONFIG_SNAPSHOT,
            project_id=self.project.project_id,
            mime_type="application/json",
            byte_size=len(snapshot.model_dump_json(indent=2).encode()),
            sha256=digest,
            content_ref="fixture-snapshot/" + digest,
            producer="journal-fixture",
            redacted=False,
            created_at=self.state.clock.now(),
        )
        self.state.save_artifact(artifact)
        return self.state.get_project(self.project.project_id).model_copy(
            update={
                "fleet_spec_hash": digest,
                "config_snapshot_artifact_id": artifact.artifact_id,
                "init_status_fingerprint": sha256_bytes(b"reviewed .fleet status"),
                "updated_at": self.state.clock.now(),
            }
        )


def observation(prepared: PreparedPublication, *, exchanged: bool) -> PublicationObservation:
    return PublicationObservation(
        prepared=prepared,
        state="exchanged" if exchanged else "prepared",
        target_identity=prepared.staged_identity if exchanged else prepared.target_identity,
        target_sha256=prepared.after_sha256 if exchanged else prepared.before_sha256,
        backup_identity=prepared.target_identity if exchanged else prepared.staged_identity,
        backup_sha256=prepared.before_sha256 if exchanged else prepared.after_sha256,
    )


@pytest.fixture
def harness(tmp_path: Path) -> JournalHarness:
    clock = JournalClock(datetime(2026, 9, 5, tzinfo=UTC))
    state = SqliteStateStore(tmp_path / "journal.db", clock, UuidIdGenerator(), Redactor())
    state.migrate()
    config = YamlConfigurationAdapter(state.redactor)
    files = config.default_files("journal-fixture")
    files["project/notes.md"] = "Unreferenced text survives\r\n"
    directories = {".", "empty"}
    for path in files:
        directories.update(str(item) for item in PurePosixPath(path).parents)
    tree = OrganizationTree(
        files=tuple(
            OrganizationFile(
                path=path, content=content, sha256=sha256_bytes(content.encode()), mode=0o644
            )
            for path, content in sorted(files.items())
        ),
        directories=tuple(
            OrganizationDirectory(path=path, mode=0o755) for path in sorted(directories)
        ),
    )
    _, snapshot = config.snapshot_from_files(files)
    project = Project(
        project_id=state.ids.new(IdPrefix.PROJECT),
        canonical_root=str(tmp_path / "repository"),
        identity_hash="c" * 64,
        fleet_spec_hash=config.snapshot_hash(snapshot),
        created_at=clock.now(),
        updated_at=clock.now(),
    )
    state.save_project(project)
    journal = SqliteOrganizationStore(
        state.database_path, clock, state.ids, state.redactor, state, config
    )
    head = journal.register_baseline(project, tree, config.snapshot_hash(snapshot))
    source = Run(
        run_id=state.ids.new(IdPrefix.RUN),
        project_id=project.project_id,
        correlation_id=state.ids.new(IdPrefix.CORRELATION),
        goal="Propose an organization update",
        base_revision="a" * 40,
        target_status_fingerprint=sha256_bytes(b""),
        config_snapshot_hash=project.fleet_spec_hash,
        status=RunStatus.COMPLETED,
        stage=WorkflowStage.PRESENTING,
        created_at=clock.now(),
        updated_at=clock.now(),
    )
    state.create_run(source, organization_admission=head.admission)
    return JournalHarness(state, journal, config, project, tree, head, source)


def rows(state: SqliteStateStore) -> dict[str, list[tuple[Any, ...]]]:
    with state._connect() as connection:
        names = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'organization_%' "
                "ORDER BY name"
            )
        ]
        return {
            name: [tuple(row) for row in connection.execute(f"SELECT * FROM {name}")]
            for name in names
        }


def test_baseline_proposal_tree_and_receipts_survive_reopen(harness: JournalHarness) -> None:
    h = harness
    before = rows(h.state)
    assert h.journal.register_baseline(h.project, h.tree, h.head.config_snapshot_sha256) == h.head
    assert rows(h.state) == before
    proposal, after = h.proposal()
    stored = rows(h.state)
    reopened = h.reopen()
    assert reopened.get_proposal(proposal.patch.fleet_patch_id) == proposal
    assert reopened.get_tree(after.sha256) == after
    assert reopened.get_tree(h.tree.sha256) == h.tree
    assert reopened.list_proposals(h.project.project_id) == (proposal,)
    assert reopened.save_proposal(proposal, h.tree, after) == proposal
    assert reopened.admission_for_run(h.source.run_id) == h.head.admission
    assert rows(h.state) == stored
    assert not Path(h.project.canonical_root).exists()


def test_new_entries_inherit_exact_root_metadata_and_replacements_keep_their_own(
    harness: JournalHarness,
) -> None:
    h = harness
    root_attribute = OrganizationXattr(
        name="com.apple.provenance", value_base64=base64.b64encode(b"root opaque bytes").decode()
    )
    own_attribute = OrganizationXattr(
        name="com.apple.provenance", value_base64=base64.b64encode(b"file opaque bytes").decode()
    )
    tree = h.tree.model_copy(
        update={
            "directories": tuple(
                item.model_copy(update={"xattrs": (root_attribute,)}) if item.path == "." else item
                for item in h.tree.directories
            ),
            "files": tuple(
                item.model_copy(update={"xattrs": (own_attribute,)})
                if item.path == "README.md"
                else item
                for item in h.tree.files
            ),
        }
    )
    old = next(item for item in tree.files if item.path == "README.md")
    patch = FleetPatch(
        fleet_patch_id=h.state.ids.new(IdPrefix.FLEET_PATCH),
        project_id=h.project.project_id,
        base_fleet_spec_sha256=h.head.config_snapshot_sha256,
        rationale="Exact metadata policy",
        changes=[
            FleetPatchFileChange(
                operation=FleetPatchOperation.ADD,
                path=".fleet/agents/new-team/guidance.md",
                content="new\n",
                after_sha256=sha256_bytes(b"new\n"),
            ),
            FleetPatchFileChange(
                operation=FleetPatchOperation.REPLACE,
                path=".fleet/README.md",
                before_sha256=old.sha256,
                content="updated\n",
                after_sha256=sha256_bytes(b"updated\n"),
            ),
        ],
    )
    after = evolve_tree(tree, patch)
    added = next(item for item in after.files if item.path == "agents/new-team/guidance.md")
    parent = next(item for item in after.directories if item.path == "agents/new-team")
    replaced = next(item for item in after.files if item.path == "README.md")
    assert added.mode == 0o600 and added.xattrs == (root_attribute,)
    assert parent.mode == 0o700 and parent.xattrs == (root_attribute,)
    assert replaced.mode == old.mode and replaced.xattrs == (own_attribute,)
    project = h.project.model_copy(
        update={
            "project_id": h.state.ids.new(IdPrefix.PROJECT),
            "canonical_root": h.project.canonical_root + "-metadata",
        }
    )
    h.state.save_project(project)
    head = h.journal.register_baseline(project, tree, h.head.config_snapshot_sha256)
    assert h.reopen().get_tree(head.tree_sha256) == tree


@pytest.mark.parametrize("register_before_secret", [False, True])
@pytest.mark.parametrize("prefix", [b"", b"\xff"])
def test_encoded_metadata_secret_is_rejected_on_write_and_read(
    harness: JournalHarness,
    register_before_secret: bool,
    prefix: bytes,
) -> None:
    h = harness
    secret = "REGISTERED-OPAQUE-METADATA-SECRET"
    attribute = OrganizationXattr(
        name="com.apple.provenance",
        value_base64=base64.b64encode(prefix + secret.encode()).decode(),
    )
    tree = h.tree.model_copy(
        update={
            "directories": tuple(
                item.model_copy(update={"xattrs": (attribute,)}) if item.path == "." else item
                for item in h.tree.directories
            )
        }
    )
    project = h.project.model_copy(
        update={
            "project_id": h.state.ids.new(IdPrefix.PROJECT),
            "canonical_root": h.project.canonical_root + "-encoded",
        }
    )
    h.state.save_project(project)
    if register_before_secret:
        h.journal.register_baseline(project, tree, h.head.config_snapshot_sha256)
    h.state.redactor.register_secret(secret)
    before = rows(h.state)
    with pytest.raises(FleetError) as caught:
        if register_before_secret:
            h.reopen().get_tree(tree.sha256)
        else:
            h.journal.register_baseline(project, tree, h.head.config_snapshot_sha256)
    assert rows(h.state) == before
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert secret not in "".join(traceback.format_exception(caught.value))


def test_apply_is_exact_atomic_and_idempotent(harness: JournalHarness) -> None:
    h = harness
    proposal, after = h.proposal()
    publication = h.prepare(proposal)
    operation = h.reopen().get_operation(publication.operation_id)
    assert operation.status == "prepared"
    assert h.journal.get_head(h.project.project_id).pending_operation_id == publication.operation_id  # type: ignore[union-attr]
    before = rows(h.state)
    assert h.prepare(proposal, publication) == publication
    assert rows(h.state) == before
    project = h.project_after(after)
    version = h.journal.commit_operation(
        publication.operation_id, project, observation(publication, exchanged=True)
    )
    assert version.version == 1 and version.predecessor_version == 0
    assert version.config_snapshot_sha256 == h.head.config_snapshot_sha256  # README-only update.
    assert version.tree_sha256 != h.head.tree_sha256
    head = h.reopen().get_head(h.project.project_id)
    assert (
        head is not None
        and head.pending_operation_id is None
        and head.admission == version.admission
    )
    assert h.state.get_project(h.project.project_id) == project
    stable = rows(h.state)
    assert (
        h.reopen().commit_operation(
            publication.operation_id, project, observation(publication, exchanged=True)
        )
        == version
    )
    assert rows(h.state) == stable
    with pytest.raises(FleetError):
        h.journal.assert_current(h.head.admission)
    assert h.journal.admission_for_run(h.source.run_id) == h.head.admission


@pytest.mark.parametrize("recover", [False, True])
def test_abort_preserves_project_and_cannot_replay(harness: JournalHarness, recover: bool) -> None:
    h = harness
    proposal, _ = h.proposal()
    publication = h.prepare(proposal)
    if recover:
        operation = h.journal.require_recovery(publication.operation_id)
        assert operation.status == "recovery_required"
        stable = rows(h.state)
        assert h.journal.require_recovery(publication.operation_id) == operation
        assert rows(h.state) == stable
    aborted = h.journal.abort_operation(
        publication.operation_id, observation(publication, exchanged=False)
    )
    stable = rows(h.state)
    assert (
        h.reopen().abort_operation(
            publication.operation_id, observation(publication, exchanged=False)
        )
        == aborted
    )
    assert rows(h.state) == stable
    assert h.state.get_project(h.project.project_id) == h.project
    assert h.journal.operation_for_proposal(proposal.patch.fleet_patch_id) == aborted
    with pytest.raises(FleetError):
        h.prepare(proposal)
    with pytest.raises(FleetError):
        h.journal.commit_operation(
            publication.operation_id, h.project, observation(publication, exchanged=True)
        )


@pytest.mark.parametrize("remove", [False, True])
def test_rollback_is_new_version_and_restores_exact_prior_modes_and_directories(
    harness: JournalHarness,
    remove: bool,
) -> None:
    h = harness
    # A new unreferenced organization file adds a directory; rollback must remove that directory.
    proposal, after = h.proposal(
        path="README.md" if remove else "agents/new-team/guidance.md",
        content="New guidance\n",
        operation=FleetPatchOperation.REMOVE if remove else FleetPatchOperation.ADD,
    )
    publication = h.prepare(proposal)
    h.journal.commit_operation(
        publication.operation_id, h.project_after(after), observation(publication, exchanged=True)
    )
    head = h.journal.get_head(h.project.project_id)
    assert head is not None
    changed = next(
        item
        for item in (h.tree.files if remove else after.files)
        if item.path == ("README.md" if remove else "agents/new-team/guidance.md")
    )
    inverse = FleetPatch(
        fleet_patch_id=h.state.ids.new(IdPrefix.FLEET_PATCH),
        project_id=h.project.project_id,
        base_fleet_spec_sha256=head.config_snapshot_sha256,
        changes=[
            FleetPatchFileChange(
                operation=FleetPatchOperation.ADD if remove else FleetPatchOperation.REMOVE,
                path=".fleet/" + changed.path,
                before_sha256=None if remove else changed.sha256,
                after_sha256=changed.sha256 if remove else None,
                content=changed.content if remove else None,
            )
        ],
        rationale="Explicit current-head rollback",
        rollback_of=proposal.patch.fleet_patch_id,
    )
    text, semantic = describe_fleet_patch(after, h.tree, inverse, rollback_target=h.tree)
    record = FleetPatchProposalRecord(
        patch=inverse,
        source_run_id=h.source.run_id,
        base=head.admission,
        before_tree_sha256=after.sha256,
        after_tree_sha256=h.tree.sha256,
        before_config_snapshot_sha256=head.config_snapshot_sha256,
        after_config_snapshot_sha256=h.head.config_snapshot_sha256,
        text_diff=text,
        semantic_changes=semantic,
        created_at=h.state.clock.now(),
    )
    record = h.journal.save_proposal(record, after, h.tree)
    inverse_publication = h.prepare(record)
    version = h.journal.commit_operation(
        inverse_publication.operation_id,
        h.project_after(h.tree),
        observation(inverse_publication, exchanged=True),
    )
    assert version.version == 2 and version.tree_sha256 == h.tree.sha256
    assert h.journal.get_version(h.project.project_id, 1).operation_id == publication.operation_id
    assert h.journal.get_tree(version.tree_sha256) == h.tree
    assert h.journal.get_proposal(proposal.patch.fleet_patch_id) == proposal
    with pytest.raises(FleetError):
        h.journal.assert_current(h.head.admission)


@pytest.mark.parametrize("field", ["text_diff", "after_tree_sha256", "source_run_id", "created_at"])
def test_immutable_proposal_id_cannot_be_rebound(harness: JournalHarness, field: str) -> None:
    h = harness
    proposal, after = h.proposal()
    changed = {
        "text_diff": "forged",
        "after_tree_sha256": "a" * 64,
        "source_run_id": h.state.ids.new(IdPrefix.RUN),
        "created_at": h.state.clock.now() + timedelta(seconds=1),
    }[field]
    before = rows(h.state)
    with pytest.raises(FleetError):
        h.journal.save_proposal(proposal.model_copy(update={field: changed}), h.tree, after)
    assert rows(h.state) == before


@pytest.mark.parametrize(
    "status",
    [
        RunStatus.CREATED,
        RunStatus.RUNNING,
        RunStatus.WAITING_FOR_CHILDREN,
        RunStatus.PAUSED_FOR_APPROVAL,
        RunStatus.APPLYING,
    ],
)
def test_every_active_run_status_blocks_publication(
    harness: JournalHarness, status: RunStatus
) -> None:
    h = harness
    proposal, _ = h.proposal()
    active = h.source.model_copy(
        update={
            "run_id": h.state.ids.new(IdPrefix.RUN),
            "correlation_id": h.state.ids.new(IdPrefix.CORRELATION),
            "status": status,
            "stage": None,
        }
    )
    h.state.create_run(active, organization_admission=h.head.admission)
    before = rows(h.state)
    with pytest.raises(FleetError):
        h.prepare(proposal)
    assert rows(h.state) == before


@pytest.mark.parametrize("status", [LeaseStatus.CREATING, LeaseStatus.ACTIVE, LeaseStatus.FAILED])
def test_outstanding_including_failed_lease_blocks_publication(
    harness: JournalHarness, status: LeaseStatus
) -> None:
    h = harness
    proposal, _ = h.proposal()
    lease = ResourceLease(
        lease_id=h.state.ids.new(IdPrefix.LEASE),
        run_id=h.source.run_id,
        kind=LeaseKind.WORKTREE,
        resource_id=h.state.ids.new(IdPrefix.WORKSPACE),
        path="/fixture/owned-worktree",
        status=status,
        created_at=h.state.clock.now(),
        updated_at=h.state.clock.now(),
    )
    h.state.save_lease(lease)
    with pytest.raises(FleetError):
        h.prepare(proposal)
    assert h.journal.get_head(h.project.project_id) == h.head


@pytest.mark.parametrize(
    "field", ["runtime_name", "identity_hash", "canonical_root", "fleet_spec_hash"]
)
def test_commit_cannot_rebind_protected_project_identity(
    harness: JournalHarness, field: str
) -> None:
    h = harness
    proposal, after = h.proposal()
    publication = h.prepare(proposal)
    new = h.project_after(after)
    changed = {
        "runtime_name": "pydantic-ai",
        "identity_hash": "d" * 64,
        "canonical_root": "/different/repository",
        "fleet_spec_hash": "d" * 64,
    }[field]
    before = rows(h.state)
    with pytest.raises(FleetError):
        h.journal.commit_operation(
            publication.operation_id,
            new.model_copy(update={field: changed}),
            observation(publication, exchanged=True),
        )
    assert rows(h.state) == before
    assert h.state.get_project(h.project.project_id) == h.project


def test_two_connections_have_one_publication_winner(harness: JournalHarness) -> None:
    h = harness
    proposal, _ = h.proposal()
    publications = [h.publication(proposal), h.publication(proposal)]
    barrier = Barrier(2)

    def prepare(publication: PreparedPublication) -> str | None:
        journal = h.reopen()
        barrier.wait(timeout=5)
        try:
            return journal.prepare_operation(
                h.project,
                proposal.patch.fleet_patch_id,
                publication,
                authorization="apply",
                repository_before=h.boundary(),
            ).operation_id
        except FleetError:
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(prepare, publications))
    assert len([result for result in results if result]) == 1
    operation = h.journal.operation_for_proposal(proposal.patch.fleet_patch_id)
    assert operation is not None and operation.operation_id in results
    assert h.reopen().get_operation(operation.operation_id) == operation


@pytest.mark.parametrize(
    "table",
    [
        "organization_trees",
        "organization_proposals",
        "organization_heads",
        "organization_versions",
        "organization_operations",
        "organization_events",
    ],
)
def test_corrupt_record_or_audit_is_not_reported_as_applicable(
    harness: JournalHarness, table: str
) -> None:
    h = harness
    proposal, _ = h.proposal()
    publication = h.prepare(proposal)
    with h.state._connect() as connection:
        connection.execute(f"UPDATE {table} SET data_json='{{}}'")
    with pytest.raises(FleetError):
        h.journal.get_operation(publication.operation_id)


def test_rewinding_head_to_old_valid_receipt_is_rejected(harness: JournalHarness) -> None:
    h = harness
    proposal, _ = h.proposal()
    h.prepare(proposal)
    with h.state._connect() as connection:
        connection.execute(
            "UPDATE organization_heads SET pending_operation_id=NULL,audit_event_id=?,data_json=?",
            (h.head.audit_event_id, h.head.model_dump_json()),
        )
    with pytest.raises(FleetError):
        h.journal.get_head(h.project.project_id)


def test_event_write_failure_rolls_back_operation_and_fence(
    harness: JournalHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = harness
    proposal, _ = h.proposal()
    before = rows(h.state)
    original = evolution._append

    def fail_head(*args: Any, **kwargs: Any) -> None:
        if kwargs["kind"] == "head":
            raise sqlite3.OperationalError("injected safe audit failure")
        original(*args, **kwargs)

    monkeypatch.setattr(evolution, "_append", fail_head)
    with pytest.raises(FleetError):
        h.prepare(proposal)
    assert rows(h.state) == before
    assert h.reopen().get_head(h.project.project_id) == h.head


@pytest.mark.parametrize("operation", ["prepare", "commit"])
@pytest.mark.parametrize("committed_before_error", [False, True])
def test_uncertain_commit_is_read_back_without_replaying_or_losing_fence(
    harness: JournalHarness,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    committed_before_error: bool,
) -> None:
    h = harness
    proposal, after = h.proposal()
    publication = h.publication(proposal)
    if operation == "commit":
        h.prepare(proposal, publication)
    project = h.project_after(after)
    real_connect = sqlite3.connect
    injected = False
    expected_status = "prepared" if operation == "prepare" else "committed"

    class UncertainConnection(sqlite3.Connection):
        def commit(self) -> None:
            nonlocal injected
            row = self.execute(
                "SELECT status FROM organization_operations WHERE operation_id=?",
                (publication.operation_id,),
            ).fetchone()
            if not injected and row is not None and row[0] == expected_status:
                injected = True
                if committed_before_error:
                    super().commit()
                raise sqlite3.OperationalError("injected uncertain commit")
            super().commit()

    def connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        return real_connect(*args, **kwargs, factory=UncertainConnection)

    def execute() -> object:
        if operation == "prepare":
            return h.journal.prepare_operation(
                h.project,
                proposal.patch.fleet_patch_id,
                publication,
                authorization="apply",
                repository_before=h.boundary(),
            )
        return h.journal.commit_operation(
            publication.operation_id, project, observation(publication, exchanged=True)
        )

    with monkeypatch.context() as patcher:
        patcher.setattr(sqlite3, "connect", connect)
        if committed_before_error:
            execute()
        else:
            with pytest.raises(FleetError) as caught:
                execute()
            assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert injected
    stored = h.reopen().operation_for_proposal(proposal.patch.fleet_patch_id)
    head = h.reopen().get_head(h.project.project_id)
    assert head is not None
    if operation == "prepare" and not committed_before_error:
        assert stored is None and head == h.head
    elif operation == "commit" and committed_before_error:
        assert stored is not None and stored.status == "committed"
        assert head.revision == 1 and head.pending_operation_id is None
        assert h.state.get_project(h.project.project_id) == project
    else:
        assert stored is not None and stored.status == "prepared"
        assert head.revision == 0 and head.pending_operation_id == publication.operation_id
        assert h.state.get_project(h.project.project_id) == h.project
    with h.state._connect() as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM organization_events WHERE record_id=? AND event_type=?",
            (publication.operation_id, "fleet_patch." + expected_status),
        ).fetchone()[0]
        assert count == int(committed_before_error)


@pytest.mark.parametrize("lifecycle", ["active", "fenced", "released", "reconciled"])
def test_retained_conversation_claim_blocks_but_exact_settlement_allows_publication(
    harness: JournalHarness,
    lifecycle: str,
) -> None:
    h = harness
    proposal, _ = h.proposal()
    chats = SqliteConversationStore(
        h.state.database_path, h.state.clock, h.state.ids, h.state.redactor, h.state
    )
    conversation = chats.create(h.project.project_id, h.project.identity_hash)
    run = h.source.model_copy(
        update={
            "run_id": h.state.ids.new(IdPrefix.RUN),
            "correlation_id": h.state.ids.new(IdPrefix.CORRELATION),
            "status": RunStatus.CREATED,
            "stage": None,
        }
    )
    submission = ConversationSubmission(
        conversation_id=conversation.conversation_id,
        project_id=h.project.project_id,
        repository_identity=h.project.identity_hash,
        submission_key="retained-claim",
        expected_revision=conversation.revision,
        context=ConversationContext(
            conversation_id=conversation.conversation_id,
            project_id=h.project.project_id,
            through_sequence=0,
            entries=(),
        ),
        user_summary=ConversationSummary(text=run.goal),
    )
    registered = chats.register_turn_run(
        submission,
        run,
        config_snapshot_sha256=h.head.config_snapshot_sha256,
        budget_limits=RunBudgetLimits(),
        organization_admission=h.head.admission,
    )
    assert registered.claim is not None
    h.state.save_run(run.model_copy(update={"status": RunStatus.FAILED}), "run.failed", {})
    if lifecycle in {"fenced", "reconciled"}:
        fenced = chats.fence(
            run.run_id,
            expected_revision=registered.turn.revision,
            reason="recovery",
            claim=registered.claim,
        )
        if lifecycle == "reconciled":
            chats.reconcile_fenced(run.run_id, expected_revision=fenced.revision)
    elif lifecycle == "released":
        chats.settle(registered.claim, expected_revision=registered.turn.revision)
    if lifecycle in {"active", "fenced"}:
        before = rows(h.state)
        with pytest.raises(FleetError):
            h.prepare(proposal)
        assert rows(h.state) == before
    else:
        publication = h.prepare(proposal)
        assert h.reopen().get_operation(publication.operation_id).status == "prepared"


def test_reconciled_conversation_does_not_hide_newer_active_claim(harness: JournalHarness) -> None:
    # A distinct active claim in the same project remains a blocker even after another settles.
    test_retained_conversation_claim_blocks_but_exact_settlement_allows_publication(
        harness, "fenced"
    )
    h = harness
    chats = SqliteConversationStore(
        h.state.database_path, h.state.clock, h.state.ids, h.state.redactor, h.state
    )
    conversation = chats.latest(h.project.project_id, h.project.identity_hash)
    assert conversation is not None
    turn = chats.list_turns(h.project.project_id, conversation.conversation_id)[0]
    chats.reconcile_fenced(turn.binding.run_id, expected_revision=turn.revision)
    # The helper uses a new conversation and a terminal Run with an intentionally retained owner.
    test_retained_conversation_claim_blocks_but_exact_settlement_allows_publication(h, "active")


@pytest.mark.parametrize("lifecycle", ["unclaimed", "active", "released", "rewound", "orphan"])
def test_exact_graph_driver_lifecycle_controls_publication(
    harness: JournalHarness,
    tmp_path: Path,
    lifecycle: str,
) -> None:
    h = harness
    proposal, _ = h.proposal()
    artifacts = ArtifactService(
        LocalArtifactStore(tmp_path / "graph-artifacts"),
        h.state,
        h.state.clock,
        h.state.ids,
        h.state.redactor,
    )
    graphs = SqliteGraphStore(
        h.state.database_path, h.state.clock, h.state.ids, h.state.redactor, artifacts.store
    )
    parent = h.source.model_copy(
        update={
            "run_id": h.state.ids.new(IdPrefix.RUN),
            "correlation_id": h.state.ids.new(IdPrefix.CORRELATION),
            "goal": "Two independent changes",
            "status": RunStatus.CREATED,
            "stage": None,
        }
    )
    h.state.create_run(parent, organization_admission=h.head.admission)
    for stage in (WorkflowStage.INTAKE, WorkflowStage.SCOPING):
        parent = h.state.save_run(
            parent.model_copy(update={"status": RunStatus.RUNNING, "stage": stage}),
            "run.stage_changed",
            {},
        )
    criteria = [
        AcceptanceCriterion(criterion_id=f"criterion-{index}", description=f"Change {index}")
        for index in range(2)
    ]
    task = TaskSpec(
        task_id=h.state.ids.new(IdPrefix.TASK),
        run_id=parent.run_id,
        original_goal=parent.goal,
        normalized_goal=parent.goal,
        base_revision=parent.base_revision,
        allowed_paths=["src/left.py", "src/right.py"],
        forbidden_paths=[".git", ".fleet"],
        acceptance_criteria=criteria,
        required_evidence=["canonical_patch", "command_evidence", "independent_verifier_verdict"],
        max_repair_iterations=1,
        config_snapshot_hash=h.head.config_snapshot_sha256,
        created_at=h.state.clock.now(),
    )
    h.state.save_task(task)
    writers = [
        FleetPlanNode(
            node_id=f"writer-{index}",
            role_id="engineer",
            goal=f"Change {index}",
            criterion_ids=[criteria[index].criterion_id],
            scope=[task.allowed_paths[index]],
            can_write=True,
            requires_workspace=True,
        )
        for index in range(2)
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
        rationale="Exact independent child ownership",
        created_at=h.state.clock.now(),
    )
    plan_artifact = artifacts.create_text(
        kind=ArtifactKind.FLEET_PLAN,
        project_id=parent.project_id,
        run_id=parent.run_id,
        task_id=task.task_id,
        producer="journal-test",
        content=plan.model_dump_json(indent=2),
    )
    parent = h.state.save_run(
        parent.model_copy(
            update={
                "task_id": task.task_id,
                "fleet_plan_artifact_id": plan_artifact.artifact_id,
                "fleet_plan_hash": plan_artifact.sha256,
                "fleet_strategy": plan.strategy.value,
            }
        ),
        "run.task_bound",
        {},
    )
    seeds: list[GraphChildSeed] = []
    for index, node in enumerate(writers):
        child_task = task.model_copy(
            update={
                "run_id": h.state.ids.new(IdPrefix.RUN),
                "task_id": h.state.ids.new(IdPrefix.TASK),
                "original_goal": node.goal,
                "normalized_goal": node.goal,
                "allowed_paths": node.scope,
                "acceptance_criteria": [criteria[index]],
                "required_evidence": ["canonical_patch", "command_evidence"],
            }
        )
        child = h.source.model_copy(
            update={
                "run_id": child_task.run_id,
                "correlation_id": h.state.ids.new(IdPrefix.CORRELATION),
                "goal": node.goal,
                "status": RunStatus.CREATED,
                "stage": None,
                "task_id": child_task.task_id,
                "parent_run_id": parent.run_id,
                "parent_plan_sha256": plan_artifact.sha256,
                "parent_node_id": node.node_id,
                "parent_iteration": 0,
            }
        )
        seeds.append(GraphChildSeed(node_id=node.node_id, run=child, task=child_task))
    initial = graphs.initialize(parent.run_id, plan, tuple(seeds))
    if lifecycle != "unclaimed":
        claim = graphs.claim_driver(parent.run_id, expected_revision=initial.revision)
        if lifecycle == "released":
            graphs.release_driver(claim, expected_revision=1, status=GraphStatus.FAILED)
        elif lifecycle == "rewound":
            with h.state._connect() as connection:
                connection.execute(
                    "UPDATE fleet_graphs SET revision=0,driver_generation=0,"
                    "driver_claim_id=NULL,status='ready',data_json=? WHERE parent_run_id=?",
                    (initial.model_dump_json(), parent.run_id),
                )
                connection.execute(
                    "DELETE FROM fleet_graph_driver_claims WHERE parent_run_id=?", (parent.run_id,)
                )
        elif lifecycle == "orphan":
            with h.state._connect() as connection:
                connection.execute("PRAGMA foreign_keys=OFF")
                connection.execute(
                    "DELETE FROM fleet_graphs WHERE parent_run_id=?", (parent.run_id,)
                )
    for run in [parent, *(seed.run for seed in seeds)]:
        h.state.save_run(run.model_copy(update={"status": RunStatus.FAILED}), "run.failed", {})
    before = rows(h.state)
    if lifecycle in {"active", "rewound", "orphan"}:
        with pytest.raises(FleetError):
            h.prepare(proposal)
        assert rows(h.state) == before
    else:
        publication = h.prepare(proposal)
        assert h.reopen().get_operation(publication.operation_id).status == "prepared"


def test_secret_and_malformed_json_reads_have_no_raw_exception_chain(
    harness: JournalHarness,
) -> None:
    h = harness
    proposal, after = h.proposal()
    secret = "REGISTERED-JOURNAL-SECRET"
    h.state.redactor.register_secret(secret)
    before = rows(h.state)
    with pytest.raises(FleetError) as caught:
        h.journal.save_proposal(proposal.model_copy(update={"text_diff": secret}), h.tree, after)
    assert rows(h.state) == before
    assert secret not in "".join(traceback.format_exception(caught.value))
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    with h.state._connect() as connection:
        connection.execute(
            "UPDATE organization_proposals SET data_json=?", ('{"unknown":"' + secret,)
        )
    with pytest.raises(FleetError) as caught:
        h.journal.get_proposal(proposal.patch.fleet_patch_id)
    assert secret not in "".join(traceback.format_exception(caught.value))
    assert caught.value.__cause__ is None and caught.value.__context__ is None


def test_schema7_upgrade_preserves_legacy_project_and_run_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = SqliteStateStore(
        tmp_path / "legacy.db",
        JournalClock(datetime(2026, 9, 5, tzinfo=UTC)),
        UuidIdGenerator(),
        Redactor(),
    )
    with monkeypatch.context() as patcher:
        patcher.setattr(sqlite_adapter, "SUPPORTED_SCHEMA_VERSION", 7)
        assert state.migrate() == 7
        project = Project(
            project_id=state.ids.new(IdPrefix.PROJECT),
            canonical_root="/fixture/legacy",
            identity_hash="a" * 64,
            created_at=state.clock.now(),
            updated_at=state.clock.now(),
        )
        state.save_project(project)
        run = Run(
            run_id=state.ids.new(IdPrefix.RUN),
            project_id=project.project_id,
            correlation_id=state.ids.new(IdPrefix.CORRELATION),
            goal="legacy",
            base_revision="b" * 40,
            target_status_fingerprint="c" * 64,
            created_at=state.clock.now(),
            updated_at=state.clock.now(),
        )
        state.create_run(run)
        with state._connect() as connection:
            before = [
                connection.execute(f"SELECT data_json FROM {table}").fetchone()[0]
                for table in ("projects", "runs")
            ]
    assert state.migrate() == sqlite_adapter.SUPPORTED_SCHEMA_VERSION
    with state._connect() as connection:
        after = [
            connection.execute(f"SELECT data_json FROM {table}").fetchone()[0]
            for table in ("projects", "runs")
        ]
        assert connection.execute("SELECT COUNT(*) FROM organization_heads").fetchone()[0] == 0
        assert (
            connection.execute("SELECT COUNT(*) FROM organization_run_admissions").fetchone()[0]
            == 0
        )
    assert after == before


def test_operation_observation_must_match_exact_staged_receipt(harness: JournalHarness) -> None:
    h = harness
    proposal, after = h.proposal()
    publication = h.prepare(proposal)
    project = h.project_after(after)
    with pytest.raises(FleetError):
        h.journal.commit_operation(
            publication.operation_id, project, observation(publication, exchanged=False)
        )
    with pytest.raises(FleetError):
        h.journal.abort_operation(
            publication.operation_id, observation(publication, exchanged=True)
        )
    other = h.publication(proposal)
    with pytest.raises(FleetError):
        h.journal.commit_operation(
            publication.operation_id, project, observation(other, exchanged=True)
        )
    assert h.reopen().get_operation(publication.operation_id).status == "prepared"


def test_transaction_durability_settings_are_verified(harness: JournalHarness) -> None:
    with harness.journal._transaction() as connection:
        assert connection.in_transaction
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("PRAGMA synchronous").fetchone()[0] == 2
