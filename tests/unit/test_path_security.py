from __future__ import annotations

from pathlib import Path

import pytest

from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.security import resolve_logical_path


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
