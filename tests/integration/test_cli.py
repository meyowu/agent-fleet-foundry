from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agent_fleet.adapters.repository.git import GitRepositoryAdapter
from agent_fleet.adapters.system import UuidIdGenerator
from agent_fleet.bootstrap import build_container
from agent_fleet.cli.app import app
from agent_fleet.domain.security import canonical_json_hash


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
    assert version_data["data"]["phase"] == "0/1.5"

    doctor = runner.invoke(app, ["doctor", "--json", "--path", str(tmp_path)], env=environment)
    assert doctor.exit_code == 0, doctor.output
    report = json.loads(doctor.stdout)
    assert report["ok"] is True
    assert report["data"]["healthy"] is True
    assert any("fake" in warning.lower() for warning in report["warnings"])


def test_doctor_does_not_resolve_git_from_the_inspected_repository(tmp_path: Path) -> None:
    runner = CliRunner()
    repository = _repository(tmp_path)
    subdirectory = repository / "subdirectory"
    subdirectory.mkdir()
    controlled_alias = tmp_path / "controlled-alias"
    (controlled_alias / ".git").mkdir(parents=True)
    linked_repository = controlled_alias / "linked-repository"
    linked_repository.symlink_to(repository, target_is_directory=True)
    repository_bin = controlled_alias / "bin"
    repository_bin.mkdir()
    sentinel = tmp_path / "doctor-git-executed"
    docker_sentinel = tmp_path / "doctor-docker-executed"
    real_git = shutil.which("git")
    assert real_git is not None
    fake_git = repository_bin / "git"
    fake_git.write_text(
        f"#!/bin/sh\ntouch '{sentinel}'\nexec '{real_git}' \"$@\"\n",
        encoding="utf-8",
    )
    fake_git.chmod(0o755)
    fake_docker = repository_bin / "docker"
    fake_docker.write_text(
        f"#!/bin/sh\ntouch '{docker_sentinel}'\necho 'Docker version repository-controlled'\n",
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)
    environment = {
        "AGENT_FLEET_HOME": str(tmp_path / "state"),
        "PATH": f"{repository_bin}{os.pathsep}{os.environ['PATH']}",
    }

    doctor = runner.invoke(
        app,
        ["doctor", "--json", "--path", str(linked_repository / subdirectory.name)],
        env=environment,
    )

    assert doctor.exit_code == 0, doctor.output
    assert json.loads(doctor.stdout)["data"]["healthy"] is True
    assert not sentinel.exists()
    assert not docker_sentinel.exists()


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
    initialized_data = json.loads(initialized.stdout)["data"]
    assert initialized_data["security_level"] == "fake"
    assert initialized_data["repository_profile_artifact_id"].startswith("art_")
    assert initialized_data["project_knowledge_artifact_id"].startswith("art_")
    state = build_container(Path(environment["AGENT_FLEET_HOME"])).state
    profile_artifact = state.get_artifact(initialized_data["repository_profile_artifact_id"])
    knowledge_artifact = state.get_artifact(initialized_data["project_knowledge_artifact_id"])
    assert initialized_data["repository_profile_artifact_sha256"] == profile_artifact.sha256
    assert initialized_data["project_knowledge_artifact_sha256"] == knowledge_artifact.sha256
    assert (
        initialized_data["repository_profile_semantic_sha256"]
        == initialized_data["project_knowledge"]["source_profile_sha256"]
        == canonical_json_hash(initialized_data["repository_profile"])
    )
    assert initialized_data["project_knowledge_semantic_sha256"] == canonical_json_hash(
        initialized_data["project_knowledge"]
    )
    assert "repository_profile_sha256" not in initialized_data
    assert "project_knowledge_sha256" not in initialized_data
    assert initialized_data["sandbox_capabilities"]["executes_code"] is False

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
    assert result["data"]["fleet_strategy"] == "engineer_verifier"
    assert result["data"]["verified_complete"] is False
    assert result["data"]["assurance_verdict"] == "inconclusive"
    assert "OS isolation" in result["warnings"][0]
    evidence = result["data"]["evidence"]
    assert evidence["changed_paths"] == ["src/canary_calc/core.py"]
    assert {item["code"] for item in evidence["proof_gaps"]} >= {"SIMULATED_EXECUTION"}
    assert {"PROOF_GAPS_PRESENT", "SIMULATED_EVIDENCE_ONLY"} <= set(
        evidence["completion_reason_codes"]
    )
    assert evidence["command_results"]
    assert {item["strength"] for item in evidence["command_results"]} == {"simulated"}
    assert all(
        item["transcript_artifact_id"].startswith("art_") for item in evidence["command_results"]
    )
    assert result["data"]["config_snapshot_artifact_id"].startswith("art_")
    assert result["data"]["task_spec_artifact_id"].startswith("art_")

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


def test_cli_init_preview_profiles_and_writes_nothing(tmp_path: Path) -> None:
    runner = CliRunner()
    repository = _repository(tmp_path)
    state_root = tmp_path / "preview-state"
    result = runner.invoke(
        app,
        ["init", str(repository), "--preview", "--json"],
        env={"AGENT_FLEET_HOME": str(state_root)},
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)["data"]
    assert data["repository_profile"]["ecosystems"] == ["python"]
    assert (
        data["repository_profile_semantic_sha256"]
        == data["project_knowledge"]["source_profile_sha256"]
        == canonical_json_hash(data["repository_profile"])
    )
    assert data["project_knowledge_semantic_sha256"] == canonical_json_hash(
        data["project_knowledge"]
    )
    assert "repository_profile_sha256" not in data
    assert "python -m pytest" in data["project_knowledge"]["verification_commands"]
    assert "--- a/.fleet/fleet.yaml" in data["proposal_patch"]
    assert ".fleet/project/verification.yaml" in data["proposed_files"]
    assert not (repository / ".fleet").exists()
    assert not state_root.exists()


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


def test_init_rejects_repository_inside_state_directory(tmp_path: Path) -> None:
    state_root = tmp_path / "fleet-state"
    repository = GitRepositoryAdapter(state_root, UuidIdGenerator()).create_canary_fixture(
        state_root / "target-repository"
    )
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["init", str(repository), "--yes", "--json"],
        env={"AGENT_FLEET_HOME": str(state_root)},
    )

    assert result.exit_code == 2
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "PATH_OUTSIDE_SCOPE"
    assert not (repository / ".fleet").exists()


def test_init_rejects_differently_cased_state_path_inside_repository(tmp_path: Path) -> None:
    actual_parent = tmp_path / "CaseSensitiveProbe"
    actual_parent.mkdir()
    alternate_parent = tmp_path / "casesensitiveprobe"
    if not alternate_parent.exists() or not os.path.samefile(actual_parent, alternate_parent):
        pytest.skip("filesystem is case-sensitive")
    repository = _repository(actual_parent)
    alternate_repository = alternate_parent / repository.name.swapcase()
    assert alternate_repository.exists()
    assert os.path.samefile(repository, alternate_repository)
    state_root = alternate_repository / "AgentFleetState"
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["init", str(repository), "--yes", "--json"],
        env={"AGENT_FLEET_HOME": str(state_root)},
    )

    assert result.exit_code == 2
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "PATH_OUTSIDE_SCOPE"
    assert not state_root.exists()
