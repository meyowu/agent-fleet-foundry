from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from conftest import FleetHarness
from pydantic import ValidationError

from agent_fleet.domain.errors import FleetError
from agent_fleet.domain.evaluation_execution import CommittedSource, SourceEntry


@pytest.mark.parametrize(
    "path", ["/absolute", "a/../b", "a//b", "a\\b", ".git/config", "a\nsecret", "a/./b", "a/"]
)
def test_source_paths_are_canonical(path: str) -> None:
    with pytest.raises(ValidationError):
        SourceEntry(path=path, mode="100644", sha256="1" * 64)


def test_source_hash_is_content_not_commit_metadata_or_dependency_install_proof() -> None:
    entry = SourceEntry(
        path="pyproject.toml", mode="100644", sha256=hashlib.sha256(b"[project]").hexdigest()
    )
    first = CommittedSource(commit_sha="a" * 40, entries=(entry,))
    changed_commit = first.model_copy(update={"commit_sha": "b" * 40})
    assert first.source_sha256 == changed_commit.source_sha256
    assert first.dependencies_sha256 == changed_commit.dependencies_sha256
    executable = CommittedSource(
        commit_sha="a" * 40, entries=(entry.model_copy(update={"mode": "100755"}),)
    )
    assert executable.source_sha256 != first.source_sha256
    with pytest.raises(ValidationError):
        CommittedSource(commit_sha="a" * 40, entries=(entry, entry))


def test_git_source_reads_pinned_objects_not_dirty_worktree(harness: FleetHarness) -> None:
    repository = harness.container.repository
    info = repository.inspect(harness.repository_root)
    source = repository.committed_source(harness.repository_root, info.head_revision)
    original = harness.repository_root / "src/canary_calc/core.py"
    content = original.read_bytes()
    entry = next(item for item in source.entries if item.path == "src/canary_calc/core.py")
    assert entry.sha256 == hashlib.sha256(content).hexdigest()
    original.write_text("different local bytes\n")
    assert repository.committed_source(harness.repository_root, info.head_revision) == source
    with pytest.raises(FleetError) as rejected:
        repository.committed_source(harness.repository_root, "f" * 40)
    assert rejected.value.__context__ is None and rejected.value.__cause__ is None


def test_git_source_rejects_committed_symlink(harness: FleetHarness) -> None:
    target = harness.repository_root / "link"
    target.symlink_to(Path("src/canary_calc/core.py"))
    harness.git("add", "link")
    harness.git("commit", "-m", "synthetic symlink source")
    commit = harness.git("rev-parse", "HEAD").strip()
    with pytest.raises(FleetError):
        harness.container.repository.committed_source(harness.repository_root, commit)


def test_git_source_stops_at_blob_bound(harness: FleetHarness) -> None:
    path = harness.repository_root / "too-large.txt"
    path.write_bytes(b"x" * 2_000_001)
    harness.git("add", "too-large.txt")
    harness.git("commit", "-m", "synthetic bounded source")
    commit = harness.git("rev-parse", "HEAD").strip()
    with pytest.raises(FleetError):
        harness.container.repository.committed_source(harness.repository_root, commit)
