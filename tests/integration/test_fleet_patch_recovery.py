"""Joint native filesystem and SQLite cut points, not synthetic publication receipts."""

from __future__ import annotations

import asyncio
import os
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from evolution_fixtures import deliver_proposal

from agent_fleet.adapters.config import publication
from agent_fleet.bootstrap import build_container
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.ids import IdPrefix
from agent_fleet.domain.models import Project
from agent_fleet.domain.organization_tree import (
    OrganizationTree,
    PreparedPublication,
    PublicationObservation,
)
from agent_fleet.ports.organization_filesystem import (
    OrganizationFileSystem,
    OrganizationPublicationSession,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


class CutPointFiles:
    def __init__(
        self,
        original: OrganizationFileSystem,
        cut: str,
        *,
        on_stage: Callable[[], None] | None = None,
        on_exchange: Callable[[], None] | None = None,
    ) -> None:
        self.original, self.cut = original, cut
        self.receipt: PreparedPublication | None = None
        self.on_stage, self.on_exchange = on_stage, on_exchange

    @contextmanager
    def session(
        self, project: Project, operation_id: str
    ) -> Iterator[OrganizationPublicationSession]:
        with self.original.session(project, operation_id) as session:
            yield CutPointSession(session, self)


class CutPointSession:
    def __init__(self, session: OrganizationPublicationSession, owner: CutPointFiles) -> None:
        self.session, self.owner = session, owner

    def capture_target(self) -> OrganizationTree:
        return self.session.capture_target()

    def stage(self, after: OrganizationTree) -> PreparedPublication:
        result = self.session.stage(after)
        self.owner.receipt = result
        if self.owner.on_stage is not None:
            self.owner.on_stage()
        if self.owner.cut == "stage-receipt-lost":
            raise OSError("injected stage return failure")
        return result

    def observe(self, prepared: PreparedPublication) -> PublicationObservation:
        return self.session.observe(prepared)

    def exchange(self, prepared: PreparedPublication) -> PublicationObservation:
        if self.owner.cut == "before-exchange":
            raise OSError("injected pre-exchange failure")
        result = self.session.exchange(prepared)
        if self.owner.on_exchange is not None:
            self.owner.on_exchange()
        if self.owner.cut == "after-exchange":
            raise OSError("injected exchange response failure")
        return result

    def sync_exchanged(self, prepared: PreparedPublication) -> PublicationObservation:
        return self.session.sync_exchanged(prepared)

    def cleanup_owned(
        self,
        prepared: PreparedPublication,
        *,
        expected_target_sha256: str,
        expected_backup_sha256: str | None,
        expected_backup_tree: OrganizationTree | None = None,
    ) -> None:
        if self.owner.cut == "cleanup":
            raise OSError("injected cleanup failure")
        self.session.cleanup_owned(
            prepared,
            expected_target_sha256=expected_target_sha256,
            expected_backup_sha256=expected_backup_sha256,
            expected_backup_tree=expected_backup_tree,
        )


@pytest.mark.parametrize(
    "cut",
    [
        "before-prepare",
        "after-prepare",
        "before-exchange",
        "after-exchange",
        "before-commit",
        "after-commit",
    ],
)
async def test_publication_cut_points_reconcile_without_second_exchange(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cut: str
) -> None:
    container, repository, run, _, before = await deliver_proposal(tmp_path)
    service = container.organization
    proposal = service.list_proposals(repository)[0]
    original_project = container.state.get_project(run.project_id)
    original_boundary = container.repository.inspect_organization_boundary(repository)
    files = CutPointFiles(service.files, cut)
    service.files = files
    store = service.store
    if "prepare" in cut:
        original_prepare = store.prepare_operation

        def interrupted_prepare(*args: Any, **kwargs: Any) -> Any:
            if cut == "before-prepare":
                raise OSError("injected preparation failure")
            original_prepare(*args, **kwargs)
            raise OSError("injected prepared return failure")

        monkeypatch.setattr(store, "prepare_operation", interrupted_prepare)
    elif "commit" in cut:
        original_commit = store.commit_operation

        def interrupted_commit(*args: Any, **kwargs: Any) -> Any:
            if cut == "before-commit":
                raise OSError("injected commit failure")
            original_commit(*args, **kwargs)
            raise OSError("injected committed return failure")

        monkeypatch.setattr(store, "commit_operation", interrupted_commit)
    with pytest.raises(FleetError) as caught:
        service.apply(proposal.patch.fleet_patch_id)
    assert caught.value.__context__ is None and caught.value.__cause__ is None
    assert files.receipt is not None
    receipt = files.receipt
    scratch = repository.parent / receipt.scratch_basename
    rebuilt = build_container(container.state_root)
    head = rebuilt.organization.store.get_head(run.project_id)
    assert head is not None
    if cut == "before-prepare":
        assert caught.value.code is ErrorCode.CONFIG_INVALID
        assert head.revision == 0 and head.pending_operation_id is None
        assert (
            rebuilt.organization.store.operation_for_proposal(proposal.patch.fleet_patch_id) is None
        )
        assert not scratch.exists()
        assert rebuilt.state.get_project(run.project_id) == original_project
        return
    assert caught.value.code is ErrorCode.RECOVERY_REQUIRED
    assert caught.value.details["operation_id"] == receipt.operation_id
    assert scratch.is_dir()
    operation = rebuilt.organization.get_operation(receipt.operation_id)
    if cut == "after-commit":
        assert operation.status == "committed" and head.revision == 1
        assert head.pending_operation_id is None
    else:
        assert operation.status == "recovery_required" and head.revision == 0
        assert head.pending_operation_id == receipt.operation_id
        assert rebuilt.state.get_project(run.project_id) == original_project
        with pytest.raises(FleetError), rebuilt.organization.admission(original_project):
            pytest.fail("pending publication admitted execution")
    with pytest.raises(FleetError) as missing_confirmation:
        rebuilt.organization.recover(receipt.operation_id)
    assert missing_confirmation.value.code is ErrorCode.APPROVAL_REQUIRED

    # If recovery tried to exchange again this wrapper would fail. Real sync/cleanup remain enabled.
    rebuilt.organization.files = CutPointFiles(rebuilt.organization.files, "before-exchange")
    recovered = rebuilt.organization.recover(receipt.operation_id, owner_stopped=True)
    pre_exchange = cut in {"after-prepare", "before-exchange"}
    assert recovered.status == ("aborted" if pre_exchange else "committed")
    assert recovered.cleanup_complete is True and not scratch.exists()
    assert recovered.changed is (not pre_exchange and cut != "after-commit")
    head = rebuilt.organization.store.get_head(run.project_id)
    assert head is not None and head.pending_operation_id is None
    assert head.revision == (0 if pre_exchange else 1)
    project = rebuilt.state.get_project(run.project_id)
    with rebuilt.organization.files.session(
        project, service.ids.new(IdPrefix.ORGANIZATION_OPERATION)
    ) as session:
        assert session.capture_target().sha256 == (
            before if pre_exchange else proposal.after_tree_sha256
        )
    assert original_boundary.unchanged_outside_organization(
        rebuilt.repository.inspect_organization_boundary(repository)
    )
    if pre_exchange:
        with pytest.raises(FleetError):
            rebuilt.organization.apply(proposal.patch.fleet_patch_id)
    repeated = rebuilt.organization.recover(receipt.operation_id, owner_stopped=True)
    assert repeated.cleanup_complete is True and not repeated.changed


@pytest.mark.parametrize(
    "point,drift",
    [
        ("stage", "source"),
        ("stage", "index"),
        ("exchange", "source"),
        ("exchange", "index"),
        ("exchange", "organization"),
    ],
)
async def test_unrelated_drift_is_preserved_and_post_exchange_recovery_stays_fenced(
    tmp_path: Path,
    point: str,
    drift: str,
) -> None:
    container, repository, run, _, before = await deliver_proposal(tmp_path)
    proposal = container.organization.list_proposals(repository)[0]
    original_project = container.state.get_project(run.project_id)
    source = repository / "src/canary_calc/core.py"
    original_source = source.read_text()
    unknown = repository / ".fleet/unreviewed-user-note.md"

    def alter() -> None:
        if drift == "source":
            source.write_text(original_source + "\n# Concurrent user work: do not overwrite.\n")
        elif drift == "index":
            container.repository._run(
                ["git", "update-index", "--assume-unchanged", "--", "src/canary_calc/core.py"],
                cwd=repository,
            )
        else:
            unknown.write_text("Concurrent user organization note.\n")
            unknown.chmod(0o600)

    files = CutPointFiles(
        container.organization.files,
        "none",
        on_stage=alter if point == "stage" else None,
        on_exchange=alter if point == "exchange" else None,
    )
    container.organization.files = files
    with pytest.raises(FleetError) as rejected:
        container.organization.apply(proposal.patch.fleet_patch_id)
    assert files.receipt is not None
    scratch = repository.parent / files.receipt.scratch_basename
    changed_boundary = container.repository.inspect_organization_boundary(repository)
    changed_source = source.read_bytes()
    changed_organization = {
        path.relative_to(repository): path.read_bytes()
        for path in (repository / ".fleet").rglob("*")
        if path.is_file()
    }
    rebuilt = build_container(container.state_root)
    head = rebuilt.organization.store.get_head(run.project_id)
    assert head is not None and head.revision == 0
    assert rebuilt.state.get_project(run.project_id) == original_project
    if point == "stage":
        assert rejected.value.code is ErrorCode.CONFIG_INVALID
        assert not scratch.exists() and head.pending_operation_id is None
        assert head.tree_sha256 == before
        assert (
            rebuilt.organization.store.operation_for_proposal(proposal.patch.fleet_patch_id) is None
        )
    else:
        assert rejected.value.code is ErrorCode.RECOVERY_REQUIRED
        assert head.pending_operation_id == files.receipt.operation_id and scratch.is_dir()
        with pytest.raises(FleetError):
            rebuilt.organization.recover(files.receipt.operation_id, owner_stopped=True)
        assert rebuilt.organization.store.get_head(run.project_id) == head
        assert scratch.is_dir()
    assert source.read_bytes() == changed_source
    assert changed_boundary == rebuilt.repository.inspect_organization_boundary(repository)
    assert changed_organization == {
        path.relative_to(repository): path.read_bytes()
        for path in (repository / ".fleet").rglob("*")
        if path.is_file()
    }
    # Test-owned repair of the exact deliberate edit, not automatic product recovery.
    if drift == "source":
        source.write_text(original_source)
    elif drift == "index":
        container.repository._run(
            ["git", "update-index", "--no-assume-unchanged", "--", "src/canary_calc/core.py"],
            cwd=repository,
        )
    else:
        unknown.unlink()
    if point == "exchange":
        recovered = rebuilt.organization.recover(files.receipt.operation_id, owner_stopped=True)
        assert recovered.status == "committed" and recovered.cleanup_complete is True
        assert recovered.version is not None and recovered.version.version == 1
        assert not scratch.exists()


async def test_committed_cleanup_gap_is_distinct_and_recoverable(tmp_path: Path) -> None:
    container, repository, run, _, _ = await deliver_proposal(tmp_path)
    proposal = container.organization.list_proposals(repository)[0]
    files = CutPointFiles(container.organization.files, "cleanup")
    container.organization.files = files
    result = container.organization.apply(proposal.patch.fleet_patch_id)
    assert result.status == "committed" and result.version is not None
    assert result.cleanup_complete is False and result.warnings
    rebuilt = build_container(container.state_root)
    recovered = rebuilt.organization.recover(result.operation_id, owner_stopped=True)
    assert recovered.version == result.version and recovered.cleanup_complete is True
    head = rebuilt.organization.store.get_head(run.project_id)
    assert head is not None and head.revision == 1 and head.pending_operation_id is None


async def test_lost_stage_receipt_never_invents_journal_recovery(tmp_path: Path) -> None:
    container, repository, run, _, before = await deliver_proposal(tmp_path)
    proposal = container.organization.list_proposals(repository)[0]
    files = CutPointFiles(container.organization.files, "stage-receipt-lost")
    container.organization.files = files
    with pytest.raises(FleetError) as caught:
        container.organization.apply(proposal.patch.fleet_patch_id)
    assert caught.value.code is ErrorCode.RECOVERY_REQUIRED
    assert caught.value.details["journaled"] is False
    assert files.receipt is not None
    assert caught.value.details["operation_id"] == files.receipt.operation_id
    assert (repository.parent / files.receipt.scratch_basename).is_dir()
    assert (
        container.organization.store.operation_for_proposal(proposal.patch.fleet_patch_id) is None
    )
    head = container.organization.store.get_head(run.project_id)
    assert head is not None and head.tree_sha256 == before and head.pending_operation_id is None
    # Test teardown has the actual trusted local receipt; production did not receive one.
    with files.original.session(
        container.state.get_project(run.project_id), files.receipt.operation_id
    ) as session:
        session.cleanup_owned(
            files.receipt,
            expected_target_sha256=before,
            expected_backup_sha256=proposal.after_tree_sha256,
            expected_backup_tree=container.organization.store.get_tree(proposal.after_tree_sha256),
        )


async def test_actual_post_exchange_flush_failure_recovers_without_a_second_rename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    container, repository, run, _, _ = await deliver_proposal(tmp_path)
    proposal = container.organization.list_proposals(repository)[0]
    original_exchange, original_flush = publication._exchange_at, publication._flush_file
    exchanged = False

    def exchange(from_fd: int, from_name: str, to_fd: int, to_name: str) -> None:
        nonlocal exchanged
        original_exchange(from_fd, from_name, to_fd, to_name)
        if from_name == ".fleet":
            exchanged = True

    def flush(descriptor: int) -> None:
        if exchanged:
            raise OSError("injected post-exchange flush failure")
        original_flush(descriptor)

    with monkeypatch.context() as patch:
        patch.setattr(publication, "_exchange_at", exchange)
        patch.setattr(publication, "_flush_file", flush)
        with pytest.raises(FleetError) as caught:
            container.organization.apply(proposal.patch.fleet_patch_id)
    assert exchanged
    operation_id = caught.value.details["operation_id"]
    rebuilt = build_container(container.state_root)
    operation = rebuilt.organization.get_operation(operation_id)
    assert operation.status == "recovery_required"
    assert (
        rebuilt.state.get_project(run.project_id).fleet_spec_hash
        == proposal.before_config_snapshot_sha256
    )

    def never_exchange(*args: Any) -> None:
        pytest.fail("recovery attempted another directory exchange")

    with monkeypatch.context() as patch:
        patch.setattr(publication, "_exchange_at", never_exchange)
        recovered = rebuilt.organization.recover(operation_id, owner_stopped=True)
    assert recovered.status == "committed" and recovered.cleanup_complete is True
    assert (
        recovered.version is not None
        and recovered.version.tree_sha256 == proposal.after_tree_sha256
    )


@pytest.mark.parametrize("unexpected_remainder", [False, True])
async def test_actual_partial_cleanup_uses_durable_manifest_and_preserves_unknown_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, unexpected_remainder: bool
) -> None:
    container, repository, _, _, _ = await deliver_proposal(tmp_path)
    proposal = container.organization.list_proposals(repository)[0]
    original_remove = publication._Session._remove_contents
    original_unlink = os.unlink

    def partial_remove(session: Any, root: int, tree: OrganizationTree) -> None:
        count = 0

        def stop_after_first(path: Any, *, dir_fd: int | None = None) -> None:
            nonlocal count
            count += 1
            if count == 2:
                raise OSError("injected partial cleanup failure")
            original_unlink(path, dir_fd=dir_fd)

        with monkeypatch.context() as patch:
            patch.setattr(os, "unlink", stop_after_first)
            original_remove(session, root, tree)

    with monkeypatch.context() as patch:
        patch.setattr(publication._Session, "_remove_contents", partial_remove)
        result = container.organization.apply(proposal.patch.fleet_patch_id)
    assert result.status == "committed" and result.cleanup_complete is False
    receipt = container.organization.get_operation(result.operation_id).publication
    scratch = repository.parent / receipt.scratch_basename
    before_tree = container.organization.store.get_tree(proposal.before_tree_sha256)
    assert (
        len([item for item in (scratch / "tree").rglob("*") if item.is_file()])
        == len(before_tree.files) - 1
    )
    rebuilt = build_container(container.state_root)
    if unexpected_remainder:
        foreign = scratch / "tree/foreign-note.txt"
        foreign.write_text("Preserve unexpected bytes.\n", encoding="utf-8")
        retained = rebuilt.organization.recover(result.operation_id, owner_stopped=True)
        assert retained.status == "committed" and retained.cleanup_complete is False
        assert foreign.read_text() == "Preserve unexpected bytes.\n"
        foreign.unlink()  # Remove only this test's exact injected entry, not the retained backup.
    recovered = rebuilt.organization.recover(result.operation_id, owner_stopped=True)
    assert recovered.cleanup_complete is True and recovered.version == result.version
    assert not scratch.exists()


async def test_a_second_state_client_cannot_take_over_an_active_publisher(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    container, repository, run, _, _ = await deliver_proposal(tmp_path)
    proposal = container.organization.list_proposals(repository)[0]
    second = build_container(container.state_root)
    prepared = threading.Event()
    release = threading.Event()
    original = container.organization.store.prepare_operation

    def held_prepare(*args: Any, **kwargs: Any) -> Any:
        operation = original(*args, **kwargs)
        prepared.set()
        if not release.wait(10):
            raise AssertionError("publisher test barrier timed out")
        return operation

    monkeypatch.setattr(container.organization.store, "prepare_operation", held_prepare)
    publisher = asyncio.create_task(
        asyncio.to_thread(container.organization.apply, proposal.patch.fleet_patch_id)
    )
    try:
        assert await asyncio.to_thread(prepared.wait, 10)
        operation = second.organization.store.operation_for_proposal(proposal.patch.fleet_patch_id)
        assert operation is not None and operation.status == "prepared"
        with pytest.raises(FleetError):
            second.organization.apply(proposal.patch.fleet_patch_id)
        with pytest.raises(FleetError):
            second.organization.recover(operation.operation_id, owner_stopped=True)
        assert second.organization.get_operation(operation.operation_id) == operation
    finally:
        release.set()
        result = await publisher
    assert result.status == "committed" and result.cleanup_complete is True
    head = second.organization.store.get_head(run.project_id)
    assert head is not None and head.revision == 1 and head.pending_operation_id is None
    repeated = second.organization.apply(proposal.patch.fleet_patch_id)
    assert not repeated.changed and repeated.version == result.version
