from __future__ import annotations

import os
import socket
import tempfile
from pathlib import Path

import pytest

from agent_fleet.adapters.filesystem.workspace import BoundedWorkspaceFileSystem
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.security import sha256_bytes


def test_bounded_workspace_round_trip_edit_search_list_and_delete(tmp_path: Path) -> None:
    files = BoundedWorkspaceFileSystem()

    assert files.write_text(tmp_path, "src/example.py", "value = 1\n") == 10
    assert files.read_text(tmp_path, "src/example.py") == "value = 1\n"
    assert files.list_files(tmp_path) == ["src/example.py"]
    assert files.search_text(tmp_path, "value") == [
        {"path": "src/example.py", "line": 1, "text": "value = 1"}
    ]
    current_hash = sha256_bytes(b"value = 1\n")
    assert (
        files.apply_edit(
            tmp_path,
            "src/example.py",
            expected_sha256=current_hash,
            old="1",
            new="2",
            expected_matches=1,
        )
        == 10
    )
    assert files.read_text(tmp_path, "src/example.py") == "value = 2\n"
    files.delete_file(
        tmp_path,
        "src/example.py",
        expected_sha256=sha256_bytes(b"value = 2\n"),
    )
    assert files.list_files(tmp_path) == []


@pytest.mark.parametrize(
    "logical_path",
    [
        "../escape",
        "/absolute",
        "src\\alternate.py",
        "src//noncanonical.py",
        ".git/config",
        "src/.fleet/config",
        ".env",
        "secrets/id_rsa",
        "nul\x00path",
    ],
)
def test_bounded_workspace_rejects_unsafe_paths(tmp_path: Path, logical_path: str) -> None:
    files = BoundedWorkspaceFileSystem()

    with pytest.raises(FleetError) as captured:
        files.write_text(tmp_path, logical_path, "content")

    assert captured.value.code is ErrorCode.PATH_OUTSIDE_SCOPE


def test_bounded_workspace_never_follows_parent_or_leaf_symlinks(tmp_path: Path) -> None:
    files = BoundedWorkspaceFileSystem()
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (outside / "secret").write_text("outside", encoding="utf-8")
    (tmp_path / "parent-link").symlink_to(outside, target_is_directory=True)
    (tmp_path / "leaf-link").symlink_to(outside / "secret")

    with pytest.raises(FleetError):
        files.write_text(tmp_path, "parent-link/new", "escape")
    with pytest.raises(FleetError):
        files.read_text(tmp_path, "leaf-link")
    with pytest.raises(FleetError):
        files.write_text(tmp_path, "leaf-link", "replacement")

    assert (outside / "secret").read_text(encoding="utf-8") == "outside"
    assert not (outside / "new").exists()


def test_bounded_workspace_rejects_case_fold_alias(tmp_path: Path) -> None:
    files = BoundedWorkspaceFileSystem()
    (tmp_path / "Source").mkdir()

    with pytest.raises(FleetError, match="case-folded alias"):
        files.write_text(tmp_path, "source/example.py", "content")


def test_bounded_workspace_rejects_special_files_and_does_not_block(tmp_path: Path) -> None:
    del tmp_path
    files = BoundedWorkspaceFileSystem()
    with tempfile.TemporaryDirectory(prefix="af-sock-", dir="/tmp") as directory:
        root = Path(directory)
        fifo = root / "events.fifo"
        os.mkfifo(fifo)
        with pytest.raises(FleetError, match="special file"):
            files.list_files(root)
        with pytest.raises(FleetError, match="bounded regular file"):
            files.read_text(root, "events.fifo")
        fifo.unlink()

        socket_path = root / "agent.sock"
        server = socket.socket(socket.AF_UNIX)
        try:
            try:
                server.bind(str(socket_path))
            except PermissionError:
                # Some parent sandboxes prohibit creating Unix sockets. FIFO coverage above
                # still proves that special files are rejected without blocking.
                return
            with pytest.raises(FleetError, match="special file"):
                files.list_files(root)
        finally:
            server.close()


def test_bounded_workspace_enforces_read_write_and_edit_limits(tmp_path: Path) -> None:
    files = BoundedWorkspaceFileSystem()
    with pytest.raises(FleetError, match="exceeds"):
        files.write_text(tmp_path, "large.txt", "x" * 200_001)
    (tmp_path / "large.txt").write_text("x" * 20, encoding="utf-8")
    with pytest.raises(FleetError, match="bounded regular file"):
        files.read_text(tmp_path, "large.txt", max_bytes=10)
    with pytest.raises(FleetError) as captured:
        files.apply_edit(
            tmp_path,
            "large.txt",
            expected_sha256="0" * 64,
            old="x",
            new="y",
            expected_matches=20,
        )
    assert captured.value.code is ErrorCode.PATCH_TARGET_DIVERGED

    with pytest.raises(FleetError) as delete_captured:
        files.delete_file(tmp_path, "large.txt", expected_sha256="0" * 64)
    assert delete_captured.value.code is ErrorCode.PATCH_TARGET_DIVERGED
    assert (tmp_path / "large.txt").exists()


def test_bounded_workspace_ignores_symlinks_during_list_and_search(tmp_path: Path) -> None:
    files = BoundedWorkspaceFileSystem()
    (tmp_path / "safe.txt").write_text("needle\n", encoding="utf-8")
    outside = tmp_path.parent / f"{tmp_path.name}-secret"
    outside.write_text("needle secret\n", encoding="utf-8")
    (tmp_path / "outside-link").symlink_to(outside)

    assert files.list_files(tmp_path) == ["safe.txt"]
    assert files.search_text(tmp_path, "needle") == [
        {"path": "safe.txt", "line": 1, "text": "needle"}
    ]


def test_bounded_workspace_search_reads_only_explicit_logical_paths(tmp_path: Path) -> None:
    files = BoundedWorkspaceFileSystem()
    (tmp_path / "allowed.txt").write_text("needle allowed\n", encoding="utf-8")
    (tmp_path / "outside.txt").write_text("needle outside\n", encoding="utf-8")

    assert files.search_text(
        tmp_path,
        "needle",
        logical_paths=["allowed.txt"],
    ) == [{"path": "allowed.txt", "line": 1, "text": "needle allowed"}]


def test_parent_swap_during_descriptor_traversal_cannot_escape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    files = BoundedWorkspaceFileSystem()
    root = tmp_path / "workspace"
    root.mkdir()
    parent = root / "src"
    parent.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    real_open = os.open
    swapped = False

    def swap_before_parent_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal swapped
        if path == "src" and dir_fd is not None and flags & os.O_DIRECTORY and not swapped:
            swapped = True
            parent.rename(root / "src-detached")
            parent.symlink_to(outside, target_is_directory=True)
        if dir_fd is None:
            return real_open(path, flags, mode)
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", swap_before_parent_open)

    with pytest.raises(FleetError) as captured:
        files.write_text(root, "src/escape.txt", "blocked")

    assert captured.value.code is ErrorCode.PATH_OUTSIDE_SCOPE
    assert not (outside / "escape.txt").exists()
    assert not (root / "src-detached" / "escape.txt").exists()


def test_leaf_swap_during_descriptor_read_cannot_follow_outside_symlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    files = BoundedWorkspaceFileSystem()
    root = tmp_path / "workspace"
    root.mkdir()
    leaf = root / "value.txt"
    leaf.write_text("inside", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("outside-secret", encoding="utf-8")
    real_open = os.open
    real_unlink = os.unlink
    swapped = False

    def swap_before_leaf_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal swapped
        if path == "value.txt" and dir_fd is not None and flags & os.O_NONBLOCK and not swapped:
            swapped = True
            real_unlink(path, dir_fd=dir_fd)
            os.symlink(outside, path, dir_fd=dir_fd)
        if dir_fd is None:
            return real_open(path, flags, mode)
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", swap_before_leaf_open)

    with pytest.raises(FleetError) as captured:
        files.read_text(root, "value.txt")

    assert captured.value.code is ErrorCode.PATH_OUTSIDE_SCOPE
    assert outside.read_text(encoding="utf-8") == "outside-secret"


def test_parent_swap_during_atomic_replace_updates_only_pinned_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    files = BoundedWorkspaceFileSystem()
    root = tmp_path / "workspace"
    parent = root / "src"
    parent.mkdir(parents=True)
    (parent / "value.txt").write_text("old", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "value.txt").write_text("outside", encoding="utf-8")
    real_replace = os.replace
    swapped = False

    def swap_before_replace(
        source: str | bytes,
        destination: str | bytes,
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
    ) -> None:
        nonlocal swapped
        if destination == "value.txt" and not swapped:
            swapped = True
            parent.rename(root / "src-detached")
            parent.symlink_to(outside, target_is_directory=True)
        real_replace(
            source,
            destination,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
        )

    monkeypatch.setattr(os, "replace", swap_before_replace)

    assert files.write_text(root, "src/value.txt", "new") == 3
    assert (outside / "value.txt").read_text(encoding="utf-8") == "outside"
    assert (root / "src-detached" / "value.txt").read_text(encoding="utf-8") == "new"


def test_leaf_swap_during_delete_unlinks_symlink_not_outside_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    files = BoundedWorkspaceFileSystem()
    root = tmp_path / "workspace"
    root.mkdir()
    leaf = root / "value.txt"
    leaf.write_text("inside", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    real_unlink = os.unlink
    swapped = False

    def swap_before_unlink(
        path: str | bytes,
        *,
        dir_fd: int | None = None,
    ) -> None:
        nonlocal swapped
        if path == "value.txt" and dir_fd is not None and not swapped:
            swapped = True
            real_unlink(path, dir_fd=dir_fd)
            os.symlink(outside, path, dir_fd=dir_fd)
        if dir_fd is None:
            real_unlink(path)
        else:
            real_unlink(path, dir_fd=dir_fd)

    monkeypatch.setattr(os, "unlink", swap_before_unlink)

    files.delete_file(root, "value.txt", expected_sha256=sha256_bytes(b"inside"))

    assert outside.read_text(encoding="utf-8") == "outside"
    assert not leaf.exists()
