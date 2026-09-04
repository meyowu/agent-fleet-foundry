from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from agent_fleet.adapters.repository.git import GitRepositoryAdapter
from agent_fleet.adapters.system import UuidIdGenerator
from agent_fleet.cli.app import app


def _repository(tmp_path: Path) -> Path:
    return GitRepositoryAdapter(tmp_path, UuidIdGenerator()).create_canary_fixture(
        tmp_path / "cli-repository"
    )


def test_version_and_doctor_json_envelopes(tmp_path: Path) -> None:
    runner = CliRunner()
    environment = {"AGENT_FLEET_HOME": str(tmp_path / "state")}
    version = runner.invoke(app, ["version", "--json"], env=environment)
    assert version.exit_code == 0, version.output
    version_data = json.loads(version.stdout)
    assert version_data["api_version"] == "agentfleet.dev/v1alpha1"
    assert version_data["data"]["phase"] == "0/1"

    doctor = runner.invoke(app, ["doctor", "--json", "--path", str(tmp_path)], env=environment)
    assert doctor.exit_code == 0, doctor.output
    report = json.loads(doctor.stdout)
    assert report["ok"] is True
    assert report["data"]["healthy"] is True
    assert any("fake" in warning.lower() for warning in report["warnings"])


def test_cli_init_run_inspect_and_human_warning(tmp_path: Path) -> None:
    runner = CliRunner()
    repository = _repository(tmp_path)
    environment = {"AGENT_FLEET_HOME": str(tmp_path / "state")}
    initialized = runner.invoke(
        app,
        [
            "init",
            str(repository),
            "--runtime",
            "fake",
            "--sandbox",
            "fake",
            "--yes",
            "--json",
        ],
        env=environment,
    )
    assert initialized.exit_code == 0, initialized.output
    assert json.loads(initialized.stdout)["data"]["security_level"] == "fake"

    executed = runner.invoke(
        app,
        [
            "run",
            "Fix the canary behavior",
            "--project",
            str(repository),
            "--runtime",
            "fake",
            "--sandbox",
            "fake",
            "--json",
        ],
        env=environment,
    )
    assert executed.exit_code == 0, executed.output
    result = json.loads(executed.stdout)
    run_id = result["data"]["run_id"]
    assert result["data"]["status"] == "ready_for_review"
    assert "OS isolation" in result["warnings"][0]

    for command in (["status", run_id], ["logs", run_id], ["artifacts", run_id]):
        inspected = runner.invoke(app, [*command, "--json"], env=environment)
        assert inspected.exit_code == 0, inspected.output
        assert json.loads(inspected.stdout)["ok"] is True

    shown = runner.invoke(app, ["patch", "show", run_id, "--json"], env=environment)
    assert shown.exit_code == 0, shown.output
    assert "division by zero is not allowed" in json.loads(shown.stdout)["data"]["patch"]

    human = runner.invoke(app, ["status", run_id], env=environment)
    assert human.exit_code == 0
    assert "ready_for_review" in human.stdout


def test_cli_json_error_is_stable(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["status", "run_00000000000000000000000000000000", "--json"],
        env={"AGENT_FLEET_HOME": str(tmp_path / "state")},
    )
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "RESOURCE_NOT_FOUND"


def test_cli_json_init_requires_noninteractive_confirmation(tmp_path: Path) -> None:
    runner = CliRunner()
    repository = _repository(tmp_path)
    result = runner.invoke(
        app,
        ["init", str(repository), "--json"],
        env={"AGENT_FLEET_HOME": str(tmp_path / "state")},
    )
    assert result.exit_code == 2
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "CONFIG_INVALID"
    assert not (repository / ".fleet").exists()


def test_init_rejects_state_directory_inside_target_repository(tmp_path: Path) -> None:
    runner = CliRunner()
    repository = _repository(tmp_path)
    result = runner.invoke(
        app,
        ["init", str(repository), "--yes", "--json"],
        env={"AGENT_FLEET_HOME": str(repository / ".fleet-state")},
    )
    assert result.exit_code == 2
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "PATH_OUTSIDE_SCOPE"
    assert not (repository / ".fleet-state").exists()
