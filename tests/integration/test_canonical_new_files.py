from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from agent_fleet.adapters.repository import git as git_module
from agent_fleet.adapters.repository.git import GitRepositoryAdapter
from agent_fleet.adapters.system import UuidIdGenerator
from agent_fleet.domain.errors import FleetError
from agent_fleet.domain.models import Workspace, WorkspaceKind
from agent_fleet.domain.paths import path_is_within


@pytest.fixture
def candidate(tmp_path: Path) -> tuple[GitRepositoryAdapter, Path, Workspace]:
    adapter = GitRepositoryAdapter(tmp_path / "state", UuidIdGenerator())
    repository = adapter.create_canary_fixture(tmp_path / "state" / "source")
    info = adapter.inspect(repository)
    workspace = adapter.create_workspace(
        repository, "run_" + "1" * 32, info.head_revision, WorkspaceKind.CANDIDATE
    )
    return adapter, repository, workspace


def _git(root: Path, *args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True).stdout


def test_new_files_reconstruct_exactly_without_mutating_git_index_or_object_store(
    candidate: tuple[GitRepositoryAdapter, Path, Workspace],
) -> None:
    adapter, repository, workspace = candidate
    root = Path(workspace.path)
    inputs = {
        "src/new.py": b"value = 7\n",
        "src/empty.py": b"",
        "src/space name.py": b"# spaces\n",
        "src/-leading.py": b"# leading dash\n",
        "src/comma,name.py": b"# comma\n",
    }
    for path, content in inputs.items():
        (root / path).write_bytes(content)
    (root / "src/new.py").chmod(0o755)
    (root / "src/canary_calc/core.py").write_text("# changed existing\n", encoding="utf-8")
    index_path = Path(_git(root, "rev-parse", "--git-path", "index").decode().strip())
    before_index = index_path.read_bytes()
    objects = {
        str(path.relative_to(repository)): path.read_bytes()
        for path in (repository / ".git/objects").rglob("*")
        if path.is_file()
    }
    patch = adapter.compute_patch(workspace)
    assert index_path.read_bytes() == before_index
    assert patch == adapter.compute_patch(workspace)
    assert patch.changed_paths == sorted([*inputs, "src/canary_calc/core.py"])
    assert "new file mode 100755" in patch.content
    assert "GIT binary patch" not in patch.content
    verifier = adapter.create_workspace(
        repository, workspace.run_id, workspace.base_revision, WorkspaceKind.VERIFICATION
    )
    adapter.apply_patch_to_workspace(verifier, patch.content.encode())
    assert adapter.compute_patch(verifier) == patch
    for path, content in inputs.items():
        assert (Path(verifier.path) / path).read_bytes() == content
    assert (Path(verifier.path) / "src/new.py").stat().st_mode & 0o100
    assert index_path.read_bytes() == before_index
    assert {
        str(path.relative_to(repository)): path.read_bytes()
        for path in (repository / ".git/objects").rglob("*")
        if path.is_file()
    } == objects
    assert not list(adapter.state_root.glob("patch-*"))


@pytest.mark.parametrize(
    "unsafe",
    [
        "symlink",
        "parent_symlink",
        "fifo",
        "hardlink",
        "protected",
        "control",
        "nested_git",
        "special_mode",
    ],
)
def test_unsafe_new_files_fail_closed(
    candidate: tuple[GitRepositoryAdapter, Path, Workspace], unsafe: str, tmp_path: Path
) -> None:
    adapter, _, workspace = candidate
    root = Path(workspace.path)
    outside = tmp_path / "private.txt"
    outside.write_text("must not be copied", encoding="utf-8")
    if unsafe == "symlink":
        (root / "src/new.py").symlink_to(outside)
    elif unsafe == "parent_symlink":
        (root / "src/link").symlink_to(tmp_path, target_is_directory=True)
    elif unsafe == "fifo":
        os.mkfifo(root / "src/fifo")
    elif unsafe == "hardlink":
        os.link(outside, root / "src/new.py")
    elif unsafe == "protected":
        (root / "src/.env").write_text("secret", encoding="utf-8")
    elif unsafe == "control":
        (root / "src/new\nfile").write_text("bad path", encoding="utf-8")
    elif unsafe == "nested_git":
        nested = root / "src/nested"
        nested.mkdir()
        _git(nested, "init", "--template=", "--initial-branch=main")
        (nested / "file").write_text("nested", encoding="utf-8")
    else:
        (root / "src/new.py").write_text("unsafe mode", encoding="utf-8")
        (root / "src/new.py").chmod(0o4755)
    with pytest.raises(FleetError):
        adapter.compute_patch(workspace)
    assert outside.read_text() == "must not be copied"


@pytest.mark.parametrize("bound", ["file", "total", "count", "patch"])
def test_new_file_size_and_count_bounds(
    candidate: tuple[GitRepositoryAdapter, Path, Workspace],
    monkeypatch: pytest.MonkeyPatch,
    bound: str,
) -> None:
    adapter, _, workspace = candidate
    (Path(workspace.path) / "src/new.py").write_bytes(b"0123456789")
    constants = {
        "file": "_MAX_NEW_FILE_BYTES",
        "total": "_MAX_NEW_FILES_BYTES",
        "count": "_MAX_NEW_FILES",
        "patch": "_MAX_PATCH_BYTES",
    }
    monkeypatch.setattr(git_module, constants[bound], 0 if bound == "count" else 5)
    with pytest.raises(FleetError):
        adapter.compute_patch(workspace)


def test_ordinary_repository_untracked_caches_are_not_silently_hidden(
    candidate: tuple[GitRepositoryAdapter, Path, Workspace],
) -> None:
    adapter, _, workspace = candidate
    root = Path(workspace.path)
    (root / ".gitignore").write_text("", encoding="utf-8")
    (root / "__pycache__").mkdir()
    (root / "__pycache__/unreviewed.pyc").write_text("unreviewed text\n", encoding="utf-8")
    patch = adapter.compute_patch(workspace)
    assert "__pycache__/unreviewed.pyc" in patch.changed_paths
    assert not all(path_is_within(path, ["src"]) for path in patch.changed_paths)


def test_fixture_only_ignores_generated_caches(
    candidate: tuple[GitRepositoryAdapter, Path, Workspace],
) -> None:
    adapter, _, workspace = candidate
    root = Path(workspace.path)
    (root / "__pycache__").mkdir()
    (root / "__pycache__/ignored.pyc").write_bytes(b"generated\x00bytes")
    assert adapter.compute_patch(workspace).changed_paths == []


def test_staged_new_file_is_rejected_without_index_changes(
    candidate: tuple[GitRepositoryAdapter, Path, Workspace],
) -> None:
    adapter, _, workspace = candidate
    root = Path(workspace.path)
    (root / "src/new.py").write_text("new", encoding="utf-8")
    _git(root, "add", "--", "src/new.py")
    index_path = Path(_git(root, "rev-parse", "--git-path", "index").decode().strip())
    before = index_path.read_bytes()
    with pytest.raises(FleetError):
        adapter.compute_patch(workspace)
    assert index_path.read_bytes() == before


@pytest.mark.parametrize("content", [b"secret-sentinel\x00binary", b"\xffsecret-sentinel"])
def test_new_binary_content_is_unsupported_without_emitting_encoded_patch_or_bytes(
    candidate: tuple[GitRepositoryAdapter, Path, Workspace],
    content: bytes,
) -> None:
    adapter, repository, workspace = candidate
    root = Path(workspace.path)
    (root / "src/new.dat").write_bytes(content)
    index_path = Path(_git(root, "rev-parse", "--git-path", "index").decode().strip())
    before = index_path.read_bytes()
    objects = sorted(
        path.relative_to(repository) for path in (repository / ".git/objects").rglob("*")
    )
    with pytest.raises(FleetError) as caught:
        adapter.compute_patch(workspace)
    assert "binary" in str(caught.value)
    assert "secret-sentinel" not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert index_path.read_bytes() == before
    assert (
        sorted(path.relative_to(repository) for path in (repository / ".git/objects").rglob("*"))
        == objects
    )
    assert not list(adapter.state_root.glob("patch-*"))


@pytest.mark.parametrize("change", ["modified", "deleted", "unchanged"])
def test_tracked_binary_is_rejected_only_when_changed(
    candidate: tuple[GitRepositoryAdapter, Path, Workspace],
    change: str,
) -> None:
    adapter, repository, original = candidate
    (repository / "binary.dat").write_bytes(b"secret-sentinel\x00original")
    # Force text attributes too: deleted binary content must still be rejected.
    (repository / ".gitattributes").write_text("binary.dat diff\n", encoding="utf-8")
    _git(repository, "add", "--", "binary.dat", ".gitattributes")
    _git(
        repository,
        "-c",
        "user.name=Fleet Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-m",
        "binary baseline",
    )
    workspace = adapter.create_workspace(
        repository,
        original.run_id,
        adapter.inspect(repository).head_revision,
        WorkspaceKind.VERIFICATION,
    )
    root = Path(workspace.path)
    if change == "modified":
        (root / "binary.dat").write_bytes(b"secret-sentinel\x00changed")
    elif change == "deleted":
        (root / "binary.dat").unlink()
    if change == "unchanged":
        (root / "src/new.py").write_text("new text", encoding="utf-8")
        assert adapter.compute_patch(workspace).changed_paths == ["src/new.py"]
    else:
        with pytest.raises(FleetError) as caught:
            adapter.compute_patch(workspace)
        assert "secret-sentinel" not in str(caught.value)


def test_file_mutation_during_patch_generation_is_rejected(
    candidate: tuple[GitRepositoryAdapter, Path, Workspace],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, _, workspace = candidate
    leaf = Path(workspace.path) / "src/new.py"
    leaf.write_text("before", encoding="utf-8")
    original = adapter._new_file_patch

    def changing(snapshots: list[tuple[str, str, bytes]]) -> bytes:
        patch = original(snapshots)
        leaf.write_text("after!", encoding="utf-8")
        return patch

    monkeypatch.setattr(adapter, "_new_file_patch", changing)
    with pytest.raises(FleetError):
        adapter.compute_patch(workspace)


def test_new_attributes_cannot_encode_text_as_a_binary_delivery_patch(
    candidate: tuple[GitRepositoryAdapter, Path, Workspace],
) -> None:
    adapter, _, workspace = candidate
    root = Path(workspace.path)
    (root / ".gitattributes").write_text("*.dat -diff\n", encoding="utf-8")
    (root / "src/new.dat").write_text("secret-sentinel plain text\n", encoding="utf-8")
    with pytest.raises(FleetError) as caught:
        adapter.compute_patch(workspace)
    assert "secret-sentinel" not in str(caught.value)


def test_changed_tracked_file_cannot_become_a_symlink(
    candidate: tuple[GitRepositoryAdapter, Path, Workspace],
    tmp_path: Path,
) -> None:
    adapter, _, workspace = candidate
    leaf = Path(workspace.path) / "src/canary_calc/core.py"
    leaf.unlink()
    outside = tmp_path / "outside.py"
    outside.write_text("private text\n", encoding="utf-8")
    leaf.symlink_to(outside)
    with pytest.raises(FleetError):
        adapter.compute_patch(workspace)


def test_gitlink_contents_cannot_disappear_from_patch_and_mutation_checks(
    candidate: tuple[GitRepositoryAdapter, Path, Workspace],
) -> None:
    adapter, repository, original = candidate
    _git(
        repository,
        "update-index",
        "--add",
        "--cacheinfo",
        f"160000,{original.base_revision},vendor",
    )
    _git(
        repository,
        "-c",
        "user.name=Fleet Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-m",
        "gitlink baseline",
    )
    workspace = adapter.create_workspace(
        repository,
        original.run_id,
        adapter.inspect(repository).head_revision,
        WorkspaceKind.VERIFICATION,
    )
    (Path(workspace.path) / "vendor/untracked.py").write_text("hidden\n", encoding="utf-8")
    with pytest.raises(FleetError):
        adapter.compute_patch(workspace)


def test_invalid_path_encoding_does_not_leave_secret_bytes_in_exception_context(
    candidate: tuple[GitRepositoryAdapter, Path, Workspace],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, _, workspace = candidate
    original = adapter._run_bytes

    def malformed_listing(
        argv: list[str],
        *,
        cwd: Path,
        input_bytes: bytes | None = None,
        extra_untrusted_roots: tuple[Path, ...] = (),
    ) -> bytes:
        # macOS cannot create invalid UTF-8 filenames; exercise Git's raw-byte
        # boundary directly so this Linux-relevant rejection remains portable.
        if "--others" in argv:
            return b"src/\xffsecret-sentinel\x00"
        return original(
            argv, cwd=cwd, input_bytes=input_bytes, extra_untrusted_roots=extra_untrusted_roots
        )

    monkeypatch.setattr(adapter, "_run_bytes", malformed_listing)
    with pytest.raises(FleetError) as caught:
        adapter.compute_patch(workspace)
    assert "secret-sentinel" not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_scratch_git_failure_does_not_leave_secret_output_in_exception_context(
    candidate: tuple[GitRepositoryAdapter, Path, Workspace],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, _, workspace = candidate
    (Path(workspace.path) / "src/new.py").write_text("text\n", encoding="utf-8")

    def failure(snapshots: list[tuple[str, str, bytes]]) -> bytes:
        raise subprocess.CalledProcessError(
            1, ["git"], output=b"secret-sentinel", stderr=b"secret-sentinel"
        )

    monkeypatch.setattr(adapter, "_new_file_patch", failure)
    with pytest.raises(FleetError) as caught:
        adapter.compute_patch(workspace)
    assert "secret-sentinel" not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


@pytest.mark.parametrize("race", ["additional_path", "symlink_mode"])
def test_actual_emitted_patch_cannot_escape_prevalidated_paths_or_file_modes(
    candidate: tuple[GitRepositoryAdapter, Path, Workspace],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    race: str,
) -> None:
    adapter, _, workspace = candidate
    root = Path(workspace.path)
    leaf = root / "src/canary_calc/core.py"
    leaf.write_text("changed text\n", encoding="utf-8")
    outside = tmp_path / "private.txt"
    outside.write_text("private\n", encoding="utf-8")
    original = adapter._run_bytes

    def racing_git(
        argv: list[str],
        *,
        cwd: Path,
        input_bytes: bytes | None = None,
        extra_untrusted_roots: tuple[Path, ...] = (),
    ) -> bytes:
        if argv[:2] == ["git", "diff"] and "--binary" in argv and "--cached" not in argv:
            if race == "additional_path":
                (root / "pyproject.toml").write_text("outside scope\n", encoding="utf-8")
            else:
                leaf.unlink()
                leaf.symlink_to(outside)
            result = original(
                argv, cwd=cwd, input_bytes=input_bytes, extra_untrusted_roots=extra_untrusted_roots
            )
            if race == "symlink_mode":
                leaf.unlink()
                leaf.write_text("changed text\n", encoding="utf-8")
            return result
        return original(
            argv, cwd=cwd, input_bytes=input_bytes, extra_untrusted_roots=extra_untrusted_roots
        )

    monkeypatch.setattr(adapter, "_run_bytes", racing_git)
    with pytest.raises(FleetError):
        adapter.compute_patch(workspace)


def test_deleted_content_aggregate_is_bounded_before_blob_reads_or_diff_emission(
    candidate: tuple[GitRepositoryAdapter, Path, Workspace],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, _, workspace = candidate
    root = Path(workspace.path)
    deleted = [root / "src/canary_calc/core.py", root / "tests/test_core.py"]
    limit = max(leaf.stat().st_size for leaf in deleted)
    for leaf in deleted:
        leaf.unlink()
    monkeypatch.setattr(git_module, "_MAX_NEW_FILES_BYTES", limit)
    original = adapter._run_bytes

    def bounded_git(
        argv: list[str],
        *,
        cwd: Path,
        input_bytes: bytes | None = None,
        extra_untrusted_roots: tuple[Path, ...] = (),
    ) -> bytes:
        assert argv[:3] != ["git", "cat-file", "blob"]
        assert "--binary" not in argv
        return original(
            argv, cwd=cwd, input_bytes=input_bytes, extra_untrusted_roots=extra_untrusted_roots
        )

    monkeypatch.setattr(adapter, "_run_bytes", bounded_git)
    with pytest.raises(FleetError):
        adapter.compute_patch(workspace)
