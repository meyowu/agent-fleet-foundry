from __future__ import annotations

import tomllib
from importlib import resources
from pathlib import Path

import pytest
from live_provider_support import assert_live_canary_verification, prepare_live_canary_fixture

from agent_fleet.adapters.config.yaml import YamlConfigurationAdapter
from agent_fleet.adapters.repository.git import GitRepositoryAdapter
from agent_fleet.adapters.repository.profile import StaticRepositoryProfiler
from agent_fleet.adapters.system import UuidIdGenerator
from agent_fleet.domain.offline_canary import BROKEN_CANARY


def test_live_fixture_reuses_packaged_manifest_and_requires_only_real_pytest(
    tmp_path: Path,
) -> None:
    target = prepare_live_canary_fixture(tmp_path / "live-module")
    packaged = resources.files("agent_fleet").joinpath("assets/canary/pyproject.toml")
    manifest = (target / "pyproject.toml").read_bytes()
    assert manifest == packaged.read_bytes()
    data = tomllib.loads(manifest.decode("utf-8"))
    assert "build-system" not in data
    assert data["tool"]["pytest"]["ini_options"]["pythonpath"] == ["src"]
    assert (target / "src/canary_calc/core.py").read_text() == BROKEN_CANARY
    assert "division by zero is not allowed" in (target / "tests/test_core.py").read_text()
    assert not (target / ".fleet").exists()
    git = GitRepositoryAdapter(tmp_path, UuidIdGenerator())
    assert git._run(["git", "status", "--porcelain"], cwd=target) == ""

    profile = StaticRepositoryProfiler().profile(target).profile
    assert [(item.name, item.executable, item.argv) for item in profile.commands] == [
        ("python-test", "python", ["-m", "pytest"])
    ]
    assert all(not item.execution_authorized for item in profile.commands)
    config = YamlConfigurationAdapter()
    files = config.default_files(target.name, profile)
    for relative, content in files.items():
        path = target / ".fleet" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    assert_live_canary_verification(target)
    assert (target / "src/canary_calc/core.py").read_text() == BROKEN_CANARY


@pytest.mark.parametrize("symlink", [False, True])
def test_live_fixture_refuses_existing_destination_without_overwrite(
    tmp_path: Path, symlink: bool
) -> None:
    existing = tmp_path / "existing"
    existing.mkdir()
    sentinel = existing / "keep.txt"
    sentinel.write_text("preserve this content", encoding="utf-8")
    destination = tmp_path / "linked" if symlink else existing
    if symlink:
        destination.symlink_to(existing, target_is_directory=True)
    with pytest.raises(ValueError, match="new disposable destination"):
        prepare_live_canary_fixture(destination)
    assert sentinel.read_text() == "preserve this content"
    assert sorted(path.name for path in existing.iterdir()) == ["keep.txt"]


def test_live_preparation_does_not_change_shared_synthetic_fixture(tmp_path: Path) -> None:
    git = GitRepositoryAdapter(tmp_path, UuidIdGenerator())
    shared = git.create_canary_fixture(tmp_path / "shared-offline-fixture")
    original_manifest = (shared / "pyproject.toml").read_bytes()
    original_test = (shared / "tests/test_core.py").read_bytes()
    live = prepare_live_canary_fixture(tmp_path / "live-module")
    assert (shared / "pyproject.toml").read_bytes() == original_manifest
    assert tomllib.loads(original_manifest.decode("utf-8"))["build-system"] == {
        "requires": [],
        "build-backend": "builtins",
    }
    assert (live / "tests/test_core.py").read_bytes() == original_test
    assert (live / "src/canary_calc/core.py").read_bytes() == (
        shared / "src/canary_calc/core.py"
    ).read_bytes()
