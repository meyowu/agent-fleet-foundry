from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import AcceptanceCriterion, TaskSpec
from agent_fleet.domain.security import (
    Redactor,
    git_version_is_supported,
    path_is_within,
    resolve_logical_path,
)


@pytest.mark.parametrize("value", ["../../.ssh/id_rsa", "/etc/passwd", "..\\outside"])
def test_traversal_and_absolute_paths_are_rejected(tmp_path: Path, value: str) -> None:
    root = tmp_path / "repo-safe"
    root.mkdir()
    with pytest.raises(FleetError) as captured:
        resolve_logical_path(root, value)
    assert captured.value.code is ErrorCode.PATH_OUTSIDE_SCOPE


def test_symlink_escape_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "repo-safe"
    outside = tmp_path / "repo-safe-evil"
    root.mkdir()
    outside.mkdir()
    (root / "escape").symlink_to(outside, target_is_directory=True)
    with pytest.raises(FleetError) as captured:
        resolve_logical_path(root, "escape/secret.txt")
    assert captured.value.code is ErrorCode.PATH_OUTSIDE_SCOPE


def test_prefix_collision_is_not_containment(tmp_path: Path) -> None:
    root = tmp_path / "repo-safe"
    other = tmp_path / "repo-safe-evil"
    root.mkdir()
    other.mkdir()
    (root / "escape").symlink_to(other, target_is_directory=True)
    with pytest.raises(FleetError):
        resolve_logical_path(root, "escape/value")


def test_filesystem_identity_containment_handles_symlinked_spelling(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    alias = tmp_path / "repository-alias"
    alias.symlink_to(root, target_is_directory=True)

    assert path_is_within(alias / "missing-state", root) is True
    assert path_is_within(tmp_path / "repository-elsewhere", root) is False


def test_registered_secret_detection_and_redaction_cover_mapping_keys() -> None:
    secret = "REGISTERED-SECRET-KEY"
    redactor = Redactor([secret])
    value = {f"prefix-{secret}": {"safe": f"value-{secret}"}}

    assert redactor.contains_secret_data(value) is True
    cleaned, summary = redactor.redact_data(value)

    assert secret not in repr(cleaned)
    assert summary == ["registered_secret_1"]


@pytest.mark.parametrize(
    ("output", "supported"),
    [
        ("git version 2.45.0", True),
        ("git version 2.50.1 (Apple Git-155)", True),
        ("git version 2.44.9", False),
        ("unknown", False),
    ],
)
def test_hardened_git_version_floor(output: str, supported: bool) -> None:
    assert git_version_is_supported(output) is supported


@pytest.mark.parametrize(
    "allowed_paths",
    [
        [".fleet/project/charter.md"],
        [".git/config"],
        ["src", "src/module.py"],
        ["../outside.py"],
        ["/tmp/outside.py"],
        ["src\\outside.py"],
    ],
    ids=[
        "fleet-protected",
        "git-protected",
        "forbidden-child",
        "traversal",
        "absolute",
        "backslash",
    ],
)
def test_task_spec_rejects_protected_or_conflicting_write_scope(
    allowed_paths: list[str],
) -> None:
    with pytest.raises(ValidationError):
        TaskSpec(
            task_id="task_" + "1" * 32,
            run_id="run_" + "2" * 32,
            original_goal="Make a bounded change.",
            normalized_goal="Make a bounded change.",
            base_revision="base-revision",
            allowed_paths=allowed_paths,
            forbidden_paths=[".git", ".fleet", "src"],
            acceptance_criteria=[
                AcceptanceCriterion(criterion_id="bounded", description="Stay in scope.")
            ],
            required_evidence=["canonical patch", "command evidence"],
            max_repair_iterations=1,
            config_snapshot_hash="a" * 64,
            created_at=datetime(2026, 9, 4, tzinfo=UTC),
        )
