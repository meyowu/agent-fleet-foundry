from __future__ import annotations

import base64
import errno
import multiprocessing
import os
import stat
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from agent_fleet.adapters.config import publication
from agent_fleet.adapters.config.publication import NativeOrganizationFileSystem
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import Project
from agent_fleet.domain.organization_tree import (
    OrganizationDirectory,
    OrganizationFile,
    OrganizationTree,
    OrganizationXattr,
)
from agent_fleet.domain.security import Redactor, sha256_bytes
from agent_fleet.ports.organization_filesystem import OrganizationFileSystem

OPERATION = "fop_" + "1" * 32


@pytest.fixture
def project(tmp_path: Path) -> Project:
    root = tmp_path.resolve() / "repository"
    root.mkdir(mode=0o755)
    fleet = root / ".fleet"
    fleet.mkdir(mode=0o755)
    (fleet / "empty").mkdir(mode=0o700)
    (fleet / "README.md").write_text("unreferenced original\n", encoding="utf-8")
    (fleet / "README.md").chmod(0o600)
    (fleet / "fleet.yaml").write_text("name: original\n", encoding="utf-8")
    (fleet / "fleet.yaml").chmod(0o644)
    now = datetime(2026, 9, 5, tzinfo=UTC)
    return Project(
        project_id="prj_" + "1" * 32,
        canonical_root=str(root),
        identity_hash="a" * 64,
        created_at=now,
        updated_at=now,
    )


def after_tree(before: OrganizationTree) -> OrganizationTree:
    files = [item for item in before.files if item.path != "fleet.yaml"]
    metadata = {item.path: item.xattrs for item in before.files}
    root_metadata = next(item.xattrs for item in before.directories if item.path == ".")
    for path, value in (("fleet.yaml", "name: changed\n"), ("nested/new.txt", "new text ü\n")):
        files.append(
            OrganizationFile(
                path=path,
                content=value,
                sha256=sha256_bytes(value.encode()),
                mode=0o644,
                xattrs=metadata.get(path, root_metadata),
            )
        )
    return OrganizationTree(
        files=tuple(sorted(files, key=lambda item: item.path)),
        directories=(
            *before.directories,
            OrganizationDirectory(path="nested", mode=0o755, xattrs=root_metadata),
        ),
    )


def factory() -> OrganizationFileSystem:
    return NativeOrganizationFileSystem(Redactor())


def assert_closed(error: FleetError) -> None:
    assert error.code is ErrorCode.RECOVERY_REQUIRED
    assert error.__context__ is None and error.__cause__ is None


def test_real_native_capture_stage_exchange_reopen_and_exact_cleanup(project: Project) -> None:
    root = Path(project.canonical_root)
    with factory().session(project, OPERATION) as session:
        before = session.capture_target()
        after = after_tree(before)
        prepared = session.stage(after)
        scratch = root.parent / prepared.scratch_basename
        assert scratch.parent == root.parent and scratch.parent != root
        assert stat.S_IMODE(scratch.stat().st_mode) == 0o700
        assert sorted(item.name for item in scratch.iterdir()) == ["tree"]
        assert session.capture_target() == before
        assert session.observe(prepared).state == "prepared"
    assert scratch.is_dir()  # context exit does not clean or exchange.
    with factory().session(project, OPERATION) as session:
        exchanged = session.exchange(prepared)
        assert exchanged.state == "exchanged"
        assert exchanged.target_identity == prepared.staged_identity
        assert exchanged.backup_identity == prepared.target_identity
        assert session.capture_target() == after
        with pytest.raises(FleetError) as replay:
            session.exchange(prepared)
        assert_closed(replay.value)
        assert session.capture_target() == after
    assert (root / ".fleet" / "README.md").read_text() == "unreferenced original\n"
    assert (root / ".fleet" / "empty").is_dir()
    assert stat.S_IMODE((root / ".fleet" / "README.md").stat().st_mode) == 0o600
    with factory().session(project, OPERATION) as session:
        assert session.observe(prepared) == exchanged
        session.cleanup_owned(
            prepared, expected_target_sha256=after.sha256, expected_backup_sha256=before.sha256
        )
        assert session.observe(prepared).state == "cleaned"
        session.cleanup_owned(
            prepared, expected_target_sha256=after.sha256, expected_backup_sha256=None
        )
        assert session.capture_target() == after
    assert not scratch.exists()
    locks = list(root.parent.glob(".fleet-publish-*.lock"))
    assert len(locks) == 1 and stat.S_IMODE(locks[0].stat().st_mode) == 0o600
    assert not list(root.glob(".fleet-publication-*"))


def test_abort_cleanup_only_removes_exact_prepared_stage(project: Project) -> None:
    with factory().session(project, OPERATION) as session:
        before = session.capture_target()
        after = after_tree(before)
        prepared = session.stage(after)
        session.cleanup_owned(
            prepared, expected_target_sha256=before.sha256, expected_backup_sha256=after.sha256
        )
        assert session.capture_target() == before
        assert session.observe(prepared).state == "cleaned"


@pytest.mark.parametrize(
    "unsafe",
    [
        "file-symlink",
        "directory-symlink",
        "hardlink",
        "fifo",
        "file-mode",
        "directory-mode",
        "utf8",
        "secret",
        "credential",
        "vcs",
        "file-size",
        "file-count",
        "tree-size",
    ],
)
def test_capture_rejects_unsafe_tree_without_staging(project: Project, unsafe: str) -> None:
    root = Path(project.canonical_root)
    fleet, entry = root / ".fleet", root / ".fleet" / "fleet.yaml"
    secret = "PUBLISH-REGISTERED-SECRET-392323"
    if unsafe == "file-symlink":
        entry.unlink()
        entry.symlink_to(root / "outside")
    elif unsafe == "directory-symlink":
        (fleet / "empty").rmdir()
        (fleet / "empty").symlink_to(root)
    elif unsafe == "hardlink":
        os.link(entry, root / "outside")
    elif unsafe == "fifo":
        entry.unlink()
        os.mkfifo(entry, 0o600)
    elif unsafe == "file-mode":
        entry.chmod(0o755)
    elif unsafe == "directory-mode":
        fleet.chmod(0o777)
    elif unsafe == "utf8":
        entry.write_bytes(b"\xff")
    elif unsafe == "secret":
        entry.write_text(secret)
    elif unsafe in {"credential", "vcs"}:
        (fleet / (".env" if unsafe == "credential" else ".git")).write_text("unsafe")
    elif unsafe == "file-size":
        entry.write_bytes(b"x" * 512_001)
    elif unsafe == "file-count":
        for index in range(256):
            (fleet / f"file{index:03}").write_text("x")
    else:
        for index in range(8):
            (fleet / f"large{index}").write_bytes(b"x" * 500_000)
    with NativeOrganizationFileSystem(Redactor([secret])).session(project, OPERATION) as session:
        with pytest.raises(FleetError) as error:
            session.capture_target()
        assert_closed(error.value)
        assert secret not in str(error.value)
    assert not list(root.parent.glob(".fleet-publication-*"))


@pytest.mark.parametrize(
    "drift",
    [
        "target-content",
        "stage-content",
        "target-inode",
        "stage-inode",
        "scratch-inode",
        "scratch-extra",
        "lock-inode",
        "repository-inode",
        "scratch-mode",
    ],
)
def test_prepared_drift_fails_before_exchange_and_never_deletes_unexpected_content(
    project: Project, drift: str
) -> None:
    root = Path(project.canonical_root)
    with factory().session(project, OPERATION) as session:
        before = session.capture_target()
        prepared = session.stage(after_tree(before))
        scratch = root.parent / prepared.scratch_basename
        if drift in {"target-content", "stage-content"}:
            selected = root / ".fleet" if drift == "target-content" else scratch / "tree"
            (selected / "fleet.yaml").write_text("foreign change")
        elif drift == "scratch-extra":
            (scratch / "foreign").write_text("preserve")
        elif drift == "scratch-mode":
            scratch.chmod(0o755)
        elif drift == "lock-inode":
            lock = next(root.parent.glob(".fleet-publish-*.lock"))
            lock.rename(root.parent / "retained-lock")
            lock.touch(mode=0o600)
        else:
            selected = {
                "target-inode": root / ".fleet",
                "stage-inode": scratch / "tree",
                "scratch-inode": scratch,
                "repository-inode": root,
            }[drift]
            selected.rename(selected.with_name(selected.name + "-retained"))
            selected.mkdir(mode=0o700)
        with pytest.raises(FleetError) as exchange:
            session.exchange(prepared)
        assert_closed(exchange.value)
        with pytest.raises(FleetError):
            session.cleanup_owned(
                prepared,
                expected_target_sha256=before.sha256,
                expected_backup_sha256=prepared.after_sha256,
            )
    if drift == "scratch-extra":
        assert (scratch / "foreign").read_text() == "preserve"


def _other_process(project_json: str, connection: Any) -> None:
    try:
        with factory().session(Project.model_validate_json(project_json), "fop_" + "2" * 32):
            connection.send("acquired")
    except FleetError:
        connection.send("locked")
    finally:
        connection.close()


def test_lock_serializes_distinct_instances_and_processes_without_waiting(project: Project) -> None:
    with factory().session(project, OPERATION):
        with pytest.raises(FleetError), factory().session(project, "fop_" + "2" * 32):
            pytest.fail("second owner acquired publication lock")
        different_registration = project.model_copy(
            update={"project_id": "prj_" + "2" * 32, "identity_hash": "b" * 64}
        )
        with (
            pytest.raises(FleetError),
            factory().session(different_registration, "fop_" + "3" * 32),
        ):
            pytest.fail("different state registration bypassed the canonical-root lock")
        context = multiprocessing.get_context("spawn")
        parent, child = context.Pipe(duplex=False)
        process = context.Process(target=_other_process, args=(project.model_dump_json(), child))
        process.start()
        child.close()
        try:
            assert parent.poll(15), "publication lock must not block a competing process"
            assert parent.recv() == "locked"
            process.join(15)
            assert process.exitcode == 0
        finally:
            parent.close()
            if process.is_alive():
                process.terminate()
                process.join(5)
    with factory().session(project, OPERATION) as session:
        assert session.capture_target()


def test_unsupported_exchange_probe_never_touches_target(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unsupported(*args: object) -> None:
        raise OSError(errno.ENOTSUP, "unsupported")

    with factory().session(project, OPERATION) as session:
        before = session.capture_target()
        monkeypatch.setattr(publication, "_exchange_at", unsupported)
        with pytest.raises(FleetError) as error:
            session.stage(after_tree(before))
        assert_closed(error.value)
        assert session.capture_target() == before


@pytest.mark.parametrize(
    "cut", ["stage-flush", "before-exchange", "after-exchange", "post-exchange-flush"]
)
def test_cutpoints_reopen_exact_old_or_new_tree_without_automatic_reversal(
    project: Project, monkeypatch: pytest.MonkeyPatch, cut: str
) -> None:
    prepared = None
    exchanged = False
    real_exchange, real_flush = publication._exchange_at, publication._flush_file

    def exchange(from_fd: int, from_name: str, to_fd: int, to_name: str) -> None:
        nonlocal exchanged
        if from_name == ".fleet" and cut == "before-exchange":
            raise OSError(errno.EIO, "before")
        real_exchange(from_fd, from_name, to_fd, to_name)
        if from_name == ".fleet":
            exchanged = True
            if cut == "after-exchange":
                raise OSError(errno.EIO, "after")

    def flush(descriptor: int) -> None:
        if cut == "stage-flush" or (exchanged and cut == "post-exchange-flush"):
            raise OSError(errno.EIO, "flush")
        real_flush(descriptor)

    with factory().session(project, OPERATION) as session:
        before = session.capture_target()
        after = after_tree(before)
        with monkeypatch.context() as patch:
            patch.setattr(publication, "_exchange_at", exchange)
            patch.setattr(publication, "_flush_file", flush)
            with pytest.raises(FleetError) as error:
                prepared = session.stage(after)
                session.exchange(prepared)
            assert_closed(error.value)
        assert session.capture_target() == (after if exchanged else before)
    assert (Path(project.canonical_root).parent / (".fleet-publication-" + OPERATION)).exists()
    if prepared is not None:
        with factory().session(project, OPERATION) as session:
            observation = session.observe(prepared)
            assert observation.state == ("exchanged" if exchanged else "prepared")
            assert observation.target_sha256 == (after.sha256 if exchanged else before.sha256)
            if exchanged:
                with pytest.raises(FleetError):
                    session.exchange(prepared)

                def never_rename(*args: object) -> None:
                    pytest.fail("explicit durability recovery must never exchange again")

                with monkeypatch.context() as patch:
                    patch.setattr(publication, "_exchange_at", never_rename)
                    assert session.sync_exchanged(prepared) == observation
            session.cleanup_owned(
                prepared,
                expected_target_sha256=observation.target_sha256,
                expected_backup_sha256=observation.backup_sha256,
            )


def test_registered_secret_candidate_rejected_before_scratch_creation(project: Project) -> None:
    secret = "PUBLISH-REGISTERED-SECRET-392323"
    with NativeOrganizationFileSystem(Redactor([secret])).session(project, OPERATION) as session:
        before = session.capture_target()
        after = OrganizationTree(
            files=(
                OrganizationFile(
                    path="fleet.yaml",
                    content=secret,
                    sha256=sha256_bytes(secret.encode()),
                    mode=0o644,
                ),
            ),
            directories=before.directories,
        )
        with pytest.raises(FleetError) as error:
            session.stage(after)
        assert_closed(error.value)
        assert secret not in str(error.value)
        assert session.capture_target() == before
    assert not list(Path(project.canonical_root).parent.glob(".fleet-publication-*"))


@pytest.mark.parametrize("platform", ["darwin", "linux"])
def test_platform_exchange_uses_descriptor_relative_native_symbol_and_only_exchange_flag(
    monkeypatch: pytest.MonkeyPatch, platform: str
) -> None:
    calls: list[tuple[Any, ...]] = []

    class Function:
        argtypes: Any = None
        restype: Any = None

        def __call__(self, *args: Any) -> int:
            calls.append(args)
            return 0

    class Library:
        renameatx_np = Function()
        renameat2 = Function()

    monkeypatch.setattr("agent_fleet.adapters.config.publication.sys.platform", platform)
    monkeypatch.setattr(
        "agent_fleet.adapters.config.publication.ctypes.CDLL", lambda *args, **kwargs: Library()
    )
    publication._exchange_at(10, ".fleet", 20, "tree")
    assert calls == [(10, b".fleet", 20, b"tree", 0x2)]


def test_unknown_platform_fails_before_lock_or_scratch_creation(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("agent_fleet.adapters.config.publication.sys.platform", "unsupported")
    with pytest.raises(FleetError), factory().session(project, OPERATION):
        pytest.fail("unsupported backend accepted")
    assert not list(Path(project.canonical_root).parent.glob(".fleet-*"))


def test_sync_exchanged_rejects_unexchanged_and_wrong_cleanup_hash(project: Project) -> None:
    with factory().session(project, OPERATION) as session:
        before = session.capture_target()
        prepared = session.stage(after_tree(before))
        with pytest.raises(FleetError):
            session.sync_exchanged(prepared)
        with pytest.raises(FleetError):
            session.cleanup_owned(
                prepared,
                expected_target_sha256="b" * 64,
                expected_backup_sha256=prepared.after_sha256,
            )
        with pytest.raises(FleetError):
            session.cleanup_owned(
                prepared, expected_target_sha256=before.sha256, expected_backup_sha256="b" * 64
            )
        assert session.capture_target() == before
        assert session.observe(prepared).state == "prepared"


@pytest.mark.parametrize(
    "drift",
    ["uid", "gid", "parent-mode", "target-symlink", "root-symlink", "lock-hardlink", "lock-mode"],
)
def test_owner_parent_and_lock_boundaries_are_checked(
    project: Project, monkeypatch: pytest.MonkeyPatch, drift: str
) -> None:
    root = Path(project.canonical_root)
    with factory().session(project, OPERATION) as session:
        before = session.capture_target()
    if drift in {"uid", "gid"}:
        function = "getuid" if drift == "uid" else "getgid"
        actual = getattr(os, function)()
        monkeypatch.setattr(os, function, lambda: actual + 1)
    elif drift == "parent-mode":
        root.parent.chmod(0o777)
    elif drift in {"target-symlink", "root-symlink"}:
        selected = root / ".fleet" if drift == "target-symlink" else root
        retained = selected.with_name(selected.name + "-retained")
        selected.rename(retained)
        selected.symlink_to(retained, target_is_directory=True)
    else:
        lock = next(root.parent.glob(".fleet-publish-*.lock"))
        if drift == "lock-hardlink":
            os.link(lock, root.parent / "other-lock-link")
        else:
            lock.chmod(0o644)
    with pytest.raises(FleetError) as error, factory().session(project, OPERATION) as session:
        session.capture_target()
    assert_closed(error.value)
    assert not list(root.parent.glob(".fleet-publication-*"))
    assert before.files


def test_candidate_and_receipt_model_copy_bypasses_are_revalidated(project: Project) -> None:
    with factory().session(project, OPERATION) as session:
        before = session.capture_target()
        bad_file = before.files[0].model_copy(update={"mode": 0o777})
        bad_tree = before.model_copy(update={"files": (bad_file, *before.files[1:])})
        with pytest.raises(FleetError):
            session.stage(bad_tree)
        prepared = session.stage(after_tree(before))
        for update in (
            {"before_sha256": "b" * 64},
            {"project_id": "prj_" + "2" * 32},
            {"scratch_basename": "../unsafe"},
        ):
            with pytest.raises(FleetError):
                session.exchange(prepared.model_copy(update=update))
        assert session.capture_target() == before


@pytest.mark.parametrize(
    "location", ["file-content", "file-name", "directory-name", "encoded-metadata", "raw-metadata"]
)
def test_secret_channels_rejected_without_raw_cause(project: Project, location: str) -> None:
    secret = "PUBLISH-REGISTERED-SECRET-392323"
    attribute = OrganizationXattr(
        name="com.apple.provenance", value_base64=base64.b64encode(secret.encode()).decode()
    )
    redactor = Redactor([attribute.value_base64 if location == "encoded-metadata" else secret])
    with NativeOrganizationFileSystem(redactor).session(project, OPERATION) as session:
        before = session.capture_target()
        if location == "file-name":
            (Path(project.canonical_root) / ".fleet" / secret).write_text("plain")
        elif location == "directory-name":
            (Path(project.canonical_root) / ".fleet" / secret).mkdir(mode=0o700)
        elif location == "file-content":
            (Path(project.canonical_root) / ".fleet" / "fleet.yaml").write_text(secret)
        else:
            changed = before.files[0].model_copy(update={"xattrs": (attribute,)})
            after = before.model_copy(update={"files": (changed, *before.files[1:])})
        with pytest.raises(FleetError) as error:
            if location.endswith("metadata"):
                session.stage(after)
            else:
                session.capture_target()
        assert_closed(error.value)
        assert secret not in str(error.value) and attribute.value_base64 not in str(error.value)
    assert not list(Path(project.canonical_root).parent.glob(".fleet-publication-*"))


@pytest.mark.skipif(sys.platform != "darwin", reason="Darwin native metadata acceptance")
@pytest.mark.parametrize("metadata", ["xattr", "acl", "flag"])
def test_real_host_unsupported_metadata_is_retained_and_rejected(
    project: Project, metadata: str
) -> None:
    entry = Path(project.canonical_root) / ".fleet" / "fleet.yaml"
    if metadata == "xattr":
        subprocess.run(
            ["/usr/bin/xattr", "-w", "com.agentfleet.fixture", "retained", str(entry)], check=True
        )
    elif metadata == "acl":
        subprocess.run(["/bin/chmod", "+a", "everyone allow read", str(entry)], check=True)
    else:
        set_flags = getattr(os, "chflags", None)
        assert callable(set_flags), "Darwin metadata fixture requires the native flag setter"
        set_flags(entry, stat.UF_NODUMP)
    with factory().session(project, OPERATION) as session, pytest.raises(FleetError) as error:
        session.capture_target()
    assert_closed(error.value)
    assert entry.read_text() == "name: original\n"
    if metadata == "xattr":
        assert (
            subprocess.run(
                ["/usr/bin/xattr", "-p", "com.agentfleet.fixture", str(entry)],
                check=True,
                capture_output=True,
            ).stdout.strip()
            == b"retained"
        )


@pytest.mark.skipif(sys.platform != "darwin", reason="Darwin native metadata acceptance")
def test_unreproducible_requested_metadata_fails_before_exchange(project: Project) -> None:
    with factory().session(project, OPERATION) as session:
        before = session.capture_target()
        file = before.files[0]
        # This host's OS enforces the provenance value even when removal reports
        # success. On hosts where removal is possible the exact empty value must
        # instead be reproduced; neither outcome may silently adopt other bytes.
        changed = file.model_copy(update={"xattrs": ()})
        after = before.model_copy(update={"files": (changed, *before.files[1:])})
        try:
            prepared = session.stage(after)
        except FleetError as error:
            assert_closed(error)
            assert "metadata" in str(error).lower()
        else:
            assert session.observe(prepared).backup_sha256 == after.sha256
        assert session.capture_target() == before


@pytest.mark.parametrize(
    "mutation", ["none", "unknown", "changed-content", "changed-mode", "wrong-manifest"]
)
def test_cleanup_failure_replays_only_exact_known_remainder(
    project: Project, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    root = Path(project.canonical_root)
    with factory().session(project, OPERATION) as session:
        before = session.capture_target()
        prepared = session.stage(after_tree(before))
        observation = session.exchange(prepared)
        real_unlink = os.unlink
        count = 0

        def fail_after_first(path: Any, *, dir_fd: int | None = None) -> None:
            nonlocal count
            count += 1
            if count == 2:
                raise OSError(errno.EIO, "cleanup interrupted")
            real_unlink(path, dir_fd=dir_fd)

        with monkeypatch.context() as patch:
            patch.setattr(os, "unlink", fail_after_first)
            with pytest.raises(FleetError):
                session.cleanup_owned(
                    prepared,
                    expected_target_sha256=observation.target_sha256,
                    expected_backup_sha256=observation.backup_sha256,
                )
        scratch = root.parent / prepared.scratch_basename
        assert scratch.exists()
        if mutation == "unknown":
            (scratch / "tree" / "foreign").write_text("must survive")
        elif mutation == "changed-content":
            (scratch / "tree" / "fleet.yaml").write_text("must survive")
        elif mutation == "changed-mode":
            (scratch / "tree" / "fleet.yaml").chmod(0o600)
        elif mutation == "wrong-manifest":
            before = before.model_copy(update={"files": ()})
        if mutation == "none":
            with pytest.raises(FleetError):
                session.observe(prepared)
            session.cleanup_owned(
                prepared,
                expected_target_sha256=observation.target_sha256,
                expected_backup_sha256=observation.backup_sha256,
                expected_backup_tree=before,
            )
            assert session.observe(prepared).state == "cleaned"
            assert not scratch.exists()
        else:
            with pytest.raises(FleetError):
                session.cleanup_owned(
                    prepared,
                    expected_target_sha256=observation.target_sha256,
                    expected_backup_sha256=observation.backup_sha256,
                    expected_backup_tree=before,
                )
            assert scratch.exists()
        if mutation == "unknown":
            assert (scratch / "tree" / "foreign").read_text() == "must survive"
        assert session.capture_target().sha256 == prepared.after_sha256


def test_cleanup_reopens_exact_empty_scratch_after_tree_was_removed(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = Path(project.canonical_root)
    with factory().session(project, OPERATION) as session:
        before = session.capture_target()
        prepared = session.stage(after_tree(before))
        observation = session.exchange(prepared)
        real_rmdir = os.rmdir

        def fail_scratch(path: Any, *, dir_fd: int | None = None) -> None:
            if path == prepared.scratch_basename:
                raise OSError(errno.EIO, "after tree removal")
            real_rmdir(path, dir_fd=dir_fd)

        with monkeypatch.context() as patch:
            patch.setattr(os, "rmdir", fail_scratch)
            with pytest.raises(FleetError):
                session.cleanup_owned(
                    prepared,
                    expected_target_sha256=observation.target_sha256,
                    expected_backup_sha256=observation.backup_sha256,
                    expected_backup_tree=before,
                )
        assert not list((root.parent / prepared.scratch_basename).iterdir())
    with factory().session(project, OPERATION) as session:
        session.cleanup_owned(
            prepared,
            expected_target_sha256=observation.target_sha256,
            expected_backup_sha256=observation.backup_sha256,
            expected_backup_tree=before,
        )
        assert session.observe(prepared).state == "cleaned"


@pytest.mark.parametrize("flag", [0, 0x80000, 0x1000, 0x20, 0x40, 0x20000000])
def test_linux_inode_flag_adapter_rejects_unpreserved_flags(
    project: Project, monkeypatch: pytest.MonkeyPatch, flag: int
) -> None:
    entry = Path(project.canonical_root) / ".fleet" / "fleet.yaml"
    descriptor = os.open(entry, os.O_RDONLY)
    calls = []

    def ioctl(fd: int, request: int, value: Any, mutate: bool) -> int:
        calls.append((fd, request, mutate))
        value[0] = flag
        return 0

    try:
        monkeypatch.setattr("agent_fleet.adapters.config.publication.sys.platform", "linux")
        monkeypatch.setattr(publication, "_xattrs", lambda fd: ())
        monkeypatch.setattr("agent_fleet.adapters.config.publication.fcntl.ioctl", ioctl)
        if flag in {0, 0x80000, 0x1000}:
            assert publication._metadata(descriptor, directory=False)
        else:
            with pytest.raises(FleetError):
                publication._metadata(descriptor, directory=False)
        assert calls == [(descriptor, 0x80086601, True)]
    finally:
        os.close(descriptor)


@pytest.mark.parametrize("cut", ["before", "after"])
def test_body_exception_only_releases_lock_without_cleanup_or_exchange(
    project: Project, cut: str
) -> None:
    prepared = None
    with (
        pytest.raises(RuntimeError, match="caller stopped"),
        factory().session(project, OPERATION) as session,
    ):
        before = session.capture_target()
        prepared = session.stage(after_tree(before))
        if cut == "after":
            session.exchange(prepared)
        raise RuntimeError("caller stopped")
    assert prepared is not None
    with factory().session(project, OPERATION) as session:
        observation = session.observe(prepared)
        assert observation.state == ("prepared" if cut == "before" else "exchanged")
        assert (Path(project.canonical_root).parent / prepared.scratch_basename).exists()


@pytest.mark.parametrize("drift", ["target", "backup", "scratch"])
def test_partial_cleanup_still_requires_all_pinned_directory_identities(
    project: Project, monkeypatch: pytest.MonkeyPatch, drift: str
) -> None:
    root = Path(project.canonical_root)
    with factory().session(project, OPERATION) as session:
        before = session.capture_target()
        prepared = session.stage(after_tree(before))
        observation = session.exchange(prepared)
        scratch = root.parent / prepared.scratch_basename
        selected = {"target": root / ".fleet", "backup": scratch / "tree", "scratch": scratch}[
            drift
        ]
        selected.rename(selected.with_name(selected.name + "-retained"))
        selected.mkdir(mode=0o700)
        with pytest.raises(FleetError):
            session.cleanup_owned(
                prepared,
                expected_target_sha256=observation.target_sha256,
                expected_backup_sha256=observation.backup_sha256,
                expected_backup_tree=before,
            )
        assert selected.is_dir()


@pytest.mark.skipif(sys.platform != "darwin", reason="Darwin native metadata acceptance")
def test_changed_backup_xattr_is_not_normalized_or_deleted_during_cleanup(project: Project) -> None:
    root = Path(project.canonical_root)
    with factory().session(project, OPERATION) as session:
        before = session.capture_target()
        prepared = session.stage(after_tree(before))
        observation = session.exchange(prepared)
        path = root.parent / prepared.scratch_basename / "tree" / "fleet.yaml"
        subprocess.run(
            ["/usr/bin/xattr", "-w", "com.agentfleet.fixture", "retained", str(path)], check=True
        )
        with pytest.raises(FleetError):
            session.cleanup_owned(
                prepared,
                expected_target_sha256=observation.target_sha256,
                expected_backup_sha256=observation.backup_sha256,
                expected_backup_tree=before,
            )
        assert path.read_text() == "name: original\n"
        assert (
            subprocess.run(
                ["/usr/bin/xattr", "-p", "com.agentfleet.fixture", str(path)],
                check=True,
                capture_output=True,
            ).stdout.strip()
            == b"retained"
        )


@pytest.mark.parametrize("platform", ["darwin", "linux"])
def test_native_symbol_absence_has_no_rename_fallback(
    monkeypatch: pytest.MonkeyPatch, platform: str
) -> None:
    monkeypatch.setattr("agent_fleet.adapters.config.publication.sys.platform", platform)
    monkeypatch.setattr(
        "agent_fleet.adapters.config.publication.ctypes.CDLL", lambda *args, **kwargs: object()
    )
    with pytest.raises(FleetError):
        publication._native_backend()


@pytest.mark.parametrize("platform", ["darwin", "linux"])
def test_platform_flush_is_file_fsync_then_supported_darwin_device_flush(
    monkeypatch: pytest.MonkeyPatch, platform: str
) -> None:
    calls: list[tuple[str, int, int | None]] = []
    monkeypatch.setattr("agent_fleet.adapters.config.publication.sys.platform", platform)
    monkeypatch.setattr(os, "fsync", lambda descriptor: calls.append(("fsync", descriptor, None)))
    monkeypatch.setattr(
        "agent_fleet.adapters.config.publication.fcntl.fcntl",
        lambda descriptor, operation: calls.append(("fcntl", descriptor, operation)),
    )
    publication._flush_file(10)
    expected: list[tuple[str, int, int | None]] = [("fsync", 10, None)]
    if platform == "darwin":
        expected.append(("fcntl", 10, 51))
    assert calls == expected


def test_cleanup_rechecks_each_exact_entry_after_initial_manifest_read(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = Path(project.canonical_root)
    with factory().session(project, OPERATION) as session:
        before = session.capture_target()
        prepared = session.stage(after_tree(before))
        observation = session.exchange(prepared)
        path = root.parent / prepared.scratch_basename / "tree" / "README.md"
        remove = publication._Session._remove_contents

        def change_mode(current: Any, descriptor: int, tree: OrganizationTree) -> None:
            path.chmod(0o644)  # Still supported, but no longer the reviewed 0600.
            remove(current, descriptor, tree)

        monkeypatch.setattr(publication._Session, "_remove_contents", change_mode)
        with pytest.raises(FleetError):
            session.cleanup_owned(
                prepared,
                expected_target_sha256=observation.target_sha256,
                expected_backup_sha256=observation.backup_sha256,
                expected_backup_tree=before,
            )
        assert path.read_text() == "unreferenced original\n"
