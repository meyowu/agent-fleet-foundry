"""Offline CLI preview never creates state, invokes a model, or adopts files."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import FleetHarness

pytestmark = pytest.mark.e2e


def invoke(state: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if key in {"PATH", "SYSTEMROOT", "TMPDIR", "TEMP", "TMP", "LANG", "LC_ALL"}
    }
    environment["AGENT_FLEET_HOME"] = str(state)
    return subprocess.run(
        [str(Path(sys.executable).parent / "fleet"), "role-bundles", *arguments],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_list_needs_neither_repository_nor_state(tmp_path: Path) -> None:
    state = tmp_path / "absent-state"
    result = invoke(state, "list", "--json")
    assert result.returncode == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)["data"]
    assert len(data["bundles"]) == 4
    assert not data["execution_authorized"] and not data["publication_authorized"]
    assert not state.exists()


@pytest.mark.parametrize(
    "bundle_id", ["general-change", "public-interface", "stateful-change", "design-guided"]
)
def test_preview_provides_full_diff_without_adopting(harness: FleetHarness, bundle_id: str) -> None:
    state = harness.root / "absent-cli-state"
    before = {
        str(path.relative_to(harness.repository_root)): path.read_bytes()
        for path in (harness.repository_root / ".fleet").rglob("*")
        if path.is_file()
    }
    result = invoke(
        state,
        "preview",
        bundle_id,
        "--path",
        str(harness.repository_root),
        "--workflow",
        "code-change",
        "--scope",
        "src/canary_calc",
        "--command",
        "python-test",
        "--json",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(result.stdout.encode()) <= 1_048_576
    data = json.loads(result.stdout)["data"]
    assert data["bundle"]["bundle_id"] == bundle_id
    assert data["execution_authorized"] is data["publication_authorized"] is False
    assert data["patch"].startswith("---") and "+++ b/.fleet/" in data["patch"]
    assert data["commands"][0]["command_id"] == "python-test"
    assert "NEW FleetPatch" in data["adoption_brief"]
    assert len(data["adoption_brief"].encode()) <= 16384
    assert not state.exists()
    after = {
        str(path.relative_to(harness.repository_root)): path.read_bytes()
        for path in (harness.repository_root / ".fleet").rglob("*")
        if path.is_file()
    }
    assert after == before


@pytest.mark.parametrize(
    "arguments",
    [
        ["PRIVATE_COMMAND", "--json"],
        ["--PRIVATE_OPTION", "--json"],
        ["preview", "PRIVATE_BAD_INPUT", "--json"],
        ["list", "--PRIVATE_BAD_OPTION", "--json"],
        [
            "preview",
            "general-change",
            "--workflow",
            "PRIVATE_WORKFLOW",
            "--scope",
            "..",
            "--command",
            "PRIVATE_COMMAND",
            "--json",
        ],
    ],
)
def test_argument_failures_are_safe_and_do_not_create_state(
    tmp_path: Path, arguments: list[str]
) -> None:
    state = tmp_path / "absent-state"
    result = invoke(state, *arguments)
    assert result.returncode == 2
    assert not json.loads(result.stdout)["ok"]
    assert "PRIVATE" not in result.stdout + result.stderr
    assert not state.exists()
