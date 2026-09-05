"""Real local Git snapshots and bounded subprocess failure cleanup."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from agent_fleet.adapters.repository import git as git_adapter
from agent_fleet.adapters.repository.git import GitRepositoryAdapter
from agent_fleet.adapters.system import UuidIdGenerator
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.security import canonical_json_hash, sha256_bytes


def _git(root: Path, *arguments: str) -> None:
    subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", *arguments],
        cwd=root,
        check=True,
        capture_output=True,
        timeout=10,
        env={
            "PATH": os.environ["PATH"],
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_AUTHOR_NAME": "Boundary Test",
            "GIT_AUTHOR_EMAIL": "boundary@example.invalid",
            "GIT_COMMITTER_NAME": "Boundary Test",
            "GIT_COMMITTER_EMAIL": "boundary@example.invalid",
        },
    )


@pytest.fixture
def repository(tmp_path: Path) -> tuple[Path, GitRepositoryAdapter]:
    root = tmp_path / "repository"
    root.mkdir()
    _git(root, "init", "--quiet")
    (root / "source.py").write_text("value = 1\n")
    _git(root, "add", "--", "source.py")
    _git(root, "commit", "--quiet", "-m", "Initial fixture")
    return root, GitRepositoryAdapter(tmp_path / "state", UuidIdGenerator())


def test_boundary_matches_normal_repository_identity_without_index_write(
    repository: tuple[Path, GitRepositoryAdapter],
) -> None:
    root, adapter = repository
    index_before = (root / ".git/index").read_bytes()
    ordinary = adapter.inspect(root)
    first = adapter.inspect_organization_boundary(root)
    second = adapter.inspect_organization_boundary(root)
    assert first.repository == ordinary
    assert first == second
    assert first.non_organization_status_sha256 == canonical_json_hash([])
    assert (root / ".git/index").read_bytes() == index_before


def test_only_organization_working_tree_edits_preserve_external_boundary(
    repository: tuple[Path, GitRepositoryAdapter],
) -> None:
    root, adapter = repository
    before = adapter.inspect_organization_boundary(root)
    (root / ".fleet").mkdir()
    (root / ".fleet/README.md").write_text("Reviewed organization\n")
    after = adapter.inspect_organization_boundary(root)
    assert before.unchanged_outside_organization(after)
    assert before.repository.status_porcelain != after.repository.status_porcelain
    _git(root, "add", "--", ".fleet/README.md")
    staged = adapter.inspect_organization_boundary(root)
    assert staged.index_sha256 != after.index_sha256
    assert not after.unchanged_outside_organization(staged)


def test_source_changes_and_new_head_do_not_match_prior_boundary(
    repository: tuple[Path, GitRepositoryAdapter],
) -> None:
    root, adapter = repository
    before = adapter.inspect_organization_boundary(root)
    (root / "source.py").write_text("value = 2\n")
    dirty = adapter.inspect_organization_boundary(root)
    assert dirty.non_organization_status_sha256 != canonical_json_hash([])
    assert not before.unchanged_outside_organization(dirty)
    _git(root, "add", "--", "source.py")
    _git(root, "commit", "--quiet", "-m", "New source revision")
    committed = adapter.inspect_organization_boundary(root)
    assert committed.repository.head_revision != before.repository.head_revision
    assert not before.unchanged_outside_organization(committed)


def test_intent_to_add_flag_changes_are_bound_even_inside_organization(
    repository: tuple[Path, GitRepositoryAdapter],
) -> None:
    root, adapter = repository
    (root / ".fleet").mkdir()
    (root / ".fleet/empty.yaml").write_text("")
    _git(root, "add", "--intent-to-add", "--", ".fleet/empty.yaml")
    before = adapter.inspect_organization_boundary(root)
    _git(root, "add", "--", ".fleet/empty.yaml")
    after = adapter.inspect_organization_boundary(root)
    assert before.non_organization_status_sha256 == after.non_organization_status_sha256
    assert before.index_sha256 != after.index_sha256
    assert not before.unchanged_outside_organization(after)


def test_nul_framing_preserves_weird_filenames_and_never_hides_similar_prefixes(
    repository: tuple[Path, GitRepositoryAdapter],
) -> None:
    root, adapter = repository
    names = ["line\nbreak.txt", "tab\tname.txt", 'quote" name.txt', "验证.txt", ".fleet-other"]
    for name in names:
        (root / name).write_text("Unreviewed source\n")
    boundary = adapter.inspect_organization_boundary(root)
    assert boundary.repository.dirty_paths == sorted(names)
    outside = [entry for entry in boundary.repository.status_porcelain.split("\x00") if entry]
    assert boundary.non_organization_status_sha256 == canonical_json_hash(outside)
    assert boundary.non_organization_status_sha256 != canonical_json_hash([])


def test_flag_only_index_drift_between_complete_reads_is_rejected(
    repository: tuple[Path, GitRepositoryAdapter], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, adapter = repository
    original = git_adapter._bounded_organization_git
    changed = False

    def query(argv: list[str], **kwargs: Any) -> tuple[bytes, str, int, int]:
        nonlocal changed
        result = original(argv, **kwargs)
        if "ls-files" in argv and "-v" in argv and not changed:
            changed = True
            _git(root, "update-index", "--assume-unchanged", "--", "source.py")
        return result

    monkeypatch.setattr(git_adapter, "_bounded_organization_git", query)
    with pytest.raises(FleetError) as caught:
        adapter.inspect_organization_boundary(root)
    assert changed
    assert caught.value.code is ErrorCode.PATCH_TARGET_DIVERGED
    assert caught.value.__cause__ is None and caught.value.__context__ is None


def test_boundary_retains_secured_argv_environment_and_disables_hooks(
    repository: tuple[Path, GitRepositoryAdapter], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, adapter = repository
    sentinel = root.parent / "hook-ran"
    hook = root / ".git/hooks/post-index-change"
    hook.write_text(f"#!/bin/sh\ntouch '{sentinel}'\n")
    hook.chmod(0o700)
    monkeypatch.setenv("BOUNDARY_PRIVATE_SENTINEL", "must-never-reach-child")
    original = git_adapter._bounded_organization_git
    queries: list[list[str]] = []

    def query(argv: list[str], **kwargs: Any) -> tuple[bytes, str, int, int]:
        queries.append(argv)
        assert "BOUNDARY_PRIVATE_SENTINEL" not in kwargs["environment"]
        if "--version" not in argv:
            assert "--no-lazy-fetch" in argv
            assert "--no-optional-locks" in argv
            assert "core.hooksPath=/dev/null" in argv
            assert "core.fsmonitor=false" in argv
            assert "protocol.allow=never" in argv
        return original(argv, **kwargs)

    monkeypatch.setattr(git_adapter, "_bounded_organization_git", query)
    adapter.inspect_organization_boundary(root)
    assert len([argv for argv in queries if "ls-files" in argv]) == 4
    assert not sentinel.exists()


@pytest.mark.parametrize("failure", ["oversized", "timeout", "stderr", "status"])
def test_bad_git_output_is_bounded_and_child_is_killed_and_reaped(
    repository: tuple[Path, GitRepositoryAdapter], monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    root, adapter = repository
    original = subprocess.Popen
    children: list[subprocess.Popen[bytes]] = []
    monkeypatch.setattr(git_adapter, "_GIT_TIMEOUT_SECONDS", 2)
    monkeypatch.setattr(git_adapter, "_MAX_ORGANIZATION_INDEX_BYTES", 128)
    monkeypatch.setattr(git_adapter, "_MAX_ORGANIZATION_STATUS_BYTES", 128)

    def launch(argv: list[str], **kwargs: Any) -> subprocess.Popen[bytes]:
        if "ls-files" in argv or (failure == "status" and "status" in argv):
            code = {
                "oversized": "import os,time; os.write(1,b'x'*65536); time.sleep(20)",
                "timeout": "import time; time.sleep(20)",
                "stderr": "import os,time; os.write(2,b'x'*131072); time.sleep(20)",
                "status": "import os,time; os.write(1,b'x'*65536); time.sleep(20)",
            }[failure]
            child = original([sys.executable, "-c", code], **kwargs)
            children.append(child)
            return child
        return original(argv, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", launch)
    started = time.monotonic()
    with pytest.raises(FleetError) as caught:
        adapter.inspect_organization_boundary(root)
    assert children
    assert time.monotonic() - started < 5
    assert all(child.poll() is not None for child in children)
    assert all(child.stdout is not None and child.stdout.closed for child in children)
    assert all(child.stderr is not None and child.stderr.closed for child in children)
    assert caught.value.code is ErrorCode.PATCH_TARGET_DIVERGED
    assert caught.value.__cause__ is None and caught.value.__context__ is None


def test_hash_only_reader_returns_no_retained_stdout(tmp_path: Path) -> None:
    output, digest, count, code = git_adapter._bounded_organization_git(
        [sys.executable, "-c", "import os; os.write(1,b'x'*65536)"],
        cwd=tmp_path,
        environment={},
        deadline=time.monotonic() + 2,
        maximum=65_536,
        capture=False,
    )
    assert output == b""
    assert digest == sha256_bytes(b"x" * 65_536)
    assert count == 65_536 and code == 0


def test_non_utf8_status_fails_closed_without_echo_or_partial_boundary(
    repository: tuple[Path, GitRepositoryAdapter], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, adapter = repository
    original = git_adapter._bounded_organization_git

    def query(argv: list[str], **kwargs: Any) -> tuple[bytes, str, int, int]:
        result = original(argv, **kwargs)
        if "status" in argv:
            output = b"?? invalid-\xff\x00"
            return output, sha256_bytes(output), len(output), 0
        return result

    monkeypatch.setattr(git_adapter, "_bounded_organization_git", query)
    with pytest.raises(FleetError) as caught:
        adapter.inspect_organization_boundary(root)
    assert caught.value.code is ErrorCode.PATCH_TARGET_DIVERGED
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert "invalid-" not in str(caught.value)
