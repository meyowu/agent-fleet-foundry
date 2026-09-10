from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from agent_fleet.adapters.repository.git import GitRepositoryAdapter
from agent_fleet.adapters.system import UuidIdGenerator


@pytest.mark.e2e
@pytest.mark.parametrize("ecosystem", ["python", "node"])
def test_subprocess_readiness_inspects_but_never_runs(tmp_path: Path, ecosystem: str) -> None:
    repository = GitRepositoryAdapter(tmp_path, UuidIdGenerator()).create_canary_fixture(
        tmp_path / "repo"
    )
    marker = repository / "MUST_NOT_EXIST"
    if ecosystem == "python":
        (repository / "pyproject.toml").write_text(
            '[project]\nrequires-python=">=3.12"\ndependencies=["pytest"]\n'
        )
        (repository / "conftest.py").write_text(
            "from pathlib import Path\nPath('MUST_NOT_EXIST').touch()\n"
        )
    else:
        (repository / "pyproject.toml").unlink()
        (repository / "package.json").write_text(
            json.dumps(
                {
                    "packageManager": "npm@10.0.0",
                    "engines": {"node": ">=20"},
                    "scripts": {
                        "test": "touch MUST_NOT_EXIST",
                        "postinstall": "touch MUST_NOT_EXIST",
                    },
                }
            )
        )
    state_root = tmp_path / "state"
    environment = {
        key: value
        for key, value in os.environ.items()
        if key in {"PATH", "SYSTEMROOT", "TMPDIR", "TEMP", "TMP", "LANG", "LC_ALL"}
    }
    environment["AGENT_FLEET_HOME"] = str(state_root)
    result = subprocess.run(
        [str(Path(sys.executable).parent / "fleet"), "readiness", str(repository), "--json"],
        capture_output=True,
        text=True,
        env=environment,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)["data"]
    assert report["environment_status"] == "unverified"
    assert report["baseline_status"] == "not_checked"
    assert report["commands_executed"] == 0
    assert report["execution_authorized"] is False
    assert not marker.exists()
    assert not state_root.exists()
    assert not (repository / ".fleet").exists()


@pytest.mark.e2e
def test_subprocess_static_issues_are_non_success_without_state(tmp_path: Path) -> None:
    repository = GitRepositoryAdapter(tmp_path, UuidIdGenerator()).create_canary_fixture(
        tmp_path / "repo"
    )
    (repository / "pyproject.toml").write_text("PRIVATE malformed content")
    environment = {
        key: value
        for key, value in os.environ.items()
        if key in {"PATH", "SYSTEMROOT", "TMPDIR", "TEMP", "TMP", "LANG", "LC_ALL"}
    }
    environment["AGENT_FLEET_HOME"] = str(tmp_path / "state")
    result = subprocess.run(
        [str(Path(sys.executable).parent / "fleet"), "readiness", str(repository), "--json"],
        capture_output=True,
        text=True,
        env=environment,
        timeout=30,
        check=False,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    report = json.loads(result.stdout)["data"]
    assert report["inspection_complete"] is False
    assert report["baseline_status"] == "not_checked"
    assert "PRIVATE" not in result.stdout + result.stderr
    assert not (tmp_path / "state").exists()
