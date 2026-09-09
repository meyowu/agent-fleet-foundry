from __future__ import annotations

import base64
import json
import os
import shutil
import sqlite3
from collections.abc import Mapping
from pathlib import Path
from types import TracebackType
from typing import Any, cast
from unittest.mock import patch

import httpx2
import pytest
import typer
from action_tool_fixtures import SENTINEL, sdk_adapter, tool_response
from openai import OpenAIError, RateLimitError
from pydantic_ai import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models import Model, override_allow_model_requests
from pydantic_ai.models.function import AgentInfo, FunctionModel
from typer.testing import CliRunner

import agent_fleet.adapters.runtime.pydantic_ai as runtime_module
import agent_fleet.cli.app as cli_module
from agent_fleet.adapters.repository.git import GitRepositoryAdapter
from agent_fleet.adapters.runtime.fake import FakeRuntimeAdapter
from agent_fleet.adapters.runtime.openai_transport_policy import (
    OpenAIRequestPolicyError,
    OpenAIResponsePolicyError,
)
from agent_fleet.adapters.system import UuidIdGenerator
from agent_fleet.application.runtime import RuntimeRegistry
from agent_fleet.bootstrap import build_container
from agent_fleet.cli.app import app
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import RuntimeCapability
from agent_fleet.domain.offline_canary import FIXED_CANARY
from agent_fleet.domain.security import Redactor, canonical_json_hash


def _repository(tmp_path: Path) -> Path:
    return GitRepositoryAdapter(tmp_path, UuidIdGenerator()).create_canary_fixture(
        tmp_path / "cli-repository"
    )


def _register_test_project(
    repository: Path,
    state_root: Path,
    *,
    runtime_name: str = "fake",
    provider_model: str | None = None,
    credential_ref: str | None = None,
    environment: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Seed a registered project without exercising production bootstrap publication.

    Production ``fleet init`` now fails closed unless a real Docker canary produces
    independently verified evidence.  CLI tests whose subject is a later command use
    this explicit test-only boundary instead of weakening that publication policy.
    """

    with patch.dict(os.environ, dict(environment or {}), clear=False):
        return cast(
            dict[str, Any],
            build_container(state_root).projects._initialize_without_canary(
                repository,
                runtime_name=runtime_name,
                provider_model=provider_model,
                credential_ref=credential_ref,
                sandbox_name="fake",
                create_canary_fixture=False,
            ),
        )


class MissingToolCallingRuntime(FakeRuntimeAdapter):
    @property
    def capabilities(self) -> frozenset[RuntimeCapability]:
        return frozenset({RuntimeCapability.STRUCTURED_OUTPUT})


def test_version_and_doctor_json_envelopes(tmp_path: Path) -> None:
    runner = CliRunner()
    environment = {"AGENT_FLEET_HOME": str(tmp_path / "state")}
    version = runner.invoke(app, ["version", "--json"], env=environment)
    assert version.exit_code == 0, version.output
    version_data = json.loads(version.stdout)
    assert version_data["api_version"] == "agentfleet.dev/v1alpha1"
    assert version_data["data"]["phase"] == "6"
    assert version_data["data"]["sandboxes"] == ["docker", "fake", "local-unsafe"]
    assert version_data["data"]["runtime"] == "fake"
    assert version_data["data"]["runtimes"] == ["fake", "pydantic-ai", "openai-agents", "langgraph"]
    assert version_data["data"]["sandbox"] == "fake"

    resume_help = runner.invoke(app, ["resume", "--help"], env=environment)
    assert resume_help.exit_code == 0, resume_help.output
    assert "Resume an approved workflow" in " ".join(resume_help.stdout.split())
    assert "fake workflow" not in resume_help.stdout
    assert not (tmp_path / "state").exists()

    doctor = runner.invoke(app, ["doctor", "--json", "--path", str(tmp_path)], env=environment)
    assert doctor.exit_code == 0, doctor.output
    report = json.loads(doctor.stdout)
    assert report["ok"] is True
    assert report["data"]["healthy"] is True
    assert any("fake" in warning.lower() for warning in report["warnings"])


def test_success_presenters_redact_registered_raw_and_encoded_forms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "successful-presenter-secret"
    encoded = base64.b64encode(secret.encode()).decode()
    redactor = Redactor([secret])
    envelopes: list[Any] = []
    human_values: list[object] = []
    monkeypatch.setattr(cli_module, "_print_json", envelopes.append)

    cli_module._present_with_warnings(
        "fleet test",
        True,
        lambda: ({"raw": secret, "encoded": encoded}, [f"warning={secret}"]),
        redactor=redactor,
    )

    assert len(envelopes) == 1
    rendered_json = envelopes[0].model_dump_json()
    assert secret not in rendered_json
    assert encoded not in rendered_json
    assert "<redacted:1>" in rendered_json

    monkeypatch.setattr(cli_module, "_print_human", human_values.append)
    cli_module._present(
        "fleet test",
        False,
        lambda: {"raw": secret, "encoded": encoded},
        redactor=redactor,
    )

    assert len(human_values) == 1
    rendered_human = json.dumps(human_values[0], sort_keys=True)
    assert secret not in rendered_human
    assert encoded not in rendered_human
    assert "<redacted:1>" in rendered_human

    raw_values: list[object] = []

    def record_raw(value: object, **_: object) -> None:
        raw_values.append(value)

    monkeypatch.setattr(cli_module.console, "print", record_raw)
    cli_module._present(
        "fleet patch show",
        False,
        lambda: {"patch": "patch content"},
        raw_key="patch",
        redactor=Redactor(["patch"]),
    )

    assert raw_values == ["<redacted:1> content"]


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


def test_docker_preflight_never_resolves_cli_from_target_repository(tmp_path: Path) -> None:
    runner = CliRunner()
    repository = _repository(tmp_path)
    repository_bin = repository / "bin"
    repository_bin.mkdir()
    sentinel = tmp_path / "repository-docker-executed"
    fake_docker = repository_bin / "docker"
    fake_docker.write_text(
        f"#!/bin/sh\ntouch '{sentinel}'\nexit 0\n",
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)
    environment = {
        "AGENT_FLEET_HOME": str(tmp_path / "state"),
        "PATH": f"{repository_bin}{os.pathsep}{os.environ['PATH']}",
    }

    result = runner.invoke(
        app,
        [
            "doctor",
            "--path",
            str(repository),
            "--sandbox",
            "docker",
            "--docker-image",
            "definitely-missing-agent-fleet-image:test",
            "--json",
        ],
        env=environment,
    )

    assert result.exit_code == 0, result.output
    report = json.loads(result.stdout)["data"]
    assert report["healthy"] is False
    preflight = next(item for item in report["checks"] if item["name"] == "sandbox_preflight")
    assert preflight["ok"] is False
    assert "no container was created" in preflight["detail"]
    assert not sentinel.exists()


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
    assert initialized.exit_code == 1, initialized.output
    diagnostic = json.loads(initialized.stdout)
    assert diagnostic["error"]["code"] == "BOOTSTRAP_CANARY_FAILED"
    assert diagnostic["error"]["details"]["report_artifact_id"].startswith("art_")
    assert diagnostic["error"]["details"]["proof_gaps"]
    assert not (repository / ".fleet").exists()
    assert (
        build_container(Path(environment["AGENT_FLEET_HOME"])).state.get_project_by_root(
            str(repository)
        )
        is None
    )

    initialized_data = _register_test_project(
        repository,
        Path(environment["AGENT_FLEET_HOME"]),
    )
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


def test_cli_init_rejects_preview_with_yes_as_ambiguous(tmp_path: Path) -> None:
    runner = CliRunner()
    repository = _repository(tmp_path)
    state_root = tmp_path / "ambiguous-init-state"

    result = runner.invoke(
        app,
        ["init", str(repository), "--preview", "--yes", "--json"],
        env={"AGENT_FLEET_HOME": str(state_root)},
    )

    assert result.exit_code == 2
    assert json.loads(result.stdout)["error"]["code"] == "CONFIG_INVALID"
    assert not state_root.exists()
    assert not (repository / ".fleet").exists()


def test_cli_human_init_shows_exact_patch_and_execution_boundary_before_confirmation(
    tmp_path: Path,
) -> None:
    runner = CliRunner()
    repository = _repository(tmp_path)
    state_root = tmp_path / "human-preview-state"

    result = runner.invoke(
        app,
        ["init", str(repository)],
        input="n\n",
        env={"AGENT_FLEET_HOME": str(state_root)},
    )

    assert result.exit_code == 1
    assert "Execution and access boundary" in result.stdout
    assert "Runtime: fake" in result.stdout
    assert "security_level=fake" in result.stdout
    assert "Exact .fleet proposal patch" in result.stdout
    assert "--- a/.fleet/fleet.yaml" in result.stdout
    assert "workspace.write_file" in result.stdout
    assert "Apply exactly this validated .fleet proposal?" in result.stdout
    assert not state_root.exists()
    assert not (repository / ".fleet").exists()


def test_cli_human_init_rejects_proposal_drift_after_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = CliRunner()
    repository = _repository(tmp_path)
    state_root = tmp_path / "proposal-race-state"

    def mutate_then_confirm(_prompt: str) -> bool:
        (repository / "package.json").write_text(
            '{"packageManager":"npm@11","scripts":{"test":"vitest run"}}\n',
            encoding="utf-8",
        )
        (repository / "package-lock.json").write_text("{}\n", encoding="utf-8")
        return True

    monkeypatch.setattr(typer, "confirm", mutate_then_confirm)

    result = runner.invoke(
        app,
        ["init", str(repository)],
        env={"AGENT_FLEET_HOME": str(state_root)},
    )

    assert result.exit_code == 2
    assert "proposal changed after it was reviewed" in result.output
    assert not state_root.exists()
    assert not (repository / ".fleet").exists()


def test_cli_fake_init_diagnostic_uses_the_standard_error_envelope(tmp_path: Path) -> None:
    runner = CliRunner()
    repository = _repository(tmp_path)

    result = runner.invoke(
        app,
        ["init", str(repository), "--yes", "--json"],
        env={"AGENT_FLEET_HOME": str(tmp_path / "warning-state")},
    )

    assert result.exit_code == 1, result.output
    envelope = json.loads(result.stdout)
    assert envelope["ok"] is False
    assert envelope["data"] is None
    assert envelope["error"]["code"] == "BOOTSTRAP_CANARY_FAILED"
    assert envelope["error"]["details"]["policy_mode"] == "degraded_simulation"
    assert envelope["error"]["details"]["proof_gaps"]
    assert envelope["warnings"] == []
    assert not (repository / ".fleet").exists()


def test_cli_preview_maps_invalid_existing_utf8_to_stable_json(tmp_path: Path) -> None:
    runner = CliRunner()
    repository = _repository(tmp_path)
    fleet_root = repository / ".fleet"
    fleet_root.mkdir()
    (fleet_root / "fleet.yaml").write_bytes(b"\xff\xfe\x00")

    result = runner.invoke(
        app,
        ["init", str(repository), "--preview", "--json"],
        env={"AGENT_FLEET_HOME": str(tmp_path / "invalid-utf8-state")},
    )

    assert result.exit_code == 2
    envelope = json.loads(result.stdout)
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "CONFIG_INVALID"
    assert "Traceback" not in result.output
    assert not (tmp_path / "invalid-utf8-state").exists()


def test_cli_provider_preview_does_not_read_credential_or_write_state(tmp_path: Path) -> None:
    runner = CliRunner()
    repository = _repository(tmp_path)
    state_root = tmp_path / "provider-preview-state"
    credential_ref = "env:PHASE2_PREVIEW_KEY"

    result = runner.invoke(
        app,
        [
            "init",
            str(repository),
            "--runtime",
            "pydantic-ai",
            "--provider-model",
            "openai:gpt-5-mini",
            "--credential-ref",
            credential_ref,
            "--preview",
            "--json",
        ],
        env={"AGENT_FLEET_HOME": str(state_root)},
    )

    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)["data"]
    serialized = json.dumps(data, sort_keys=True)
    assert data["runtime"] == "pydantic-ai"
    assert data["provider_model"] == "openai:gpt-5-mini"
    assert credential_ref not in serialized
    assert "credential" not in data["proposed_files"][".fleet/fleet.yaml"].casefold()
    assert not state_root.exists()
    assert not (repository / ".fleet").exists()


def test_cli_preview_requires_explicit_docker_image_before_writes(tmp_path: Path) -> None:
    runner = CliRunner()
    repository = _repository(tmp_path)
    state_root = tmp_path / "sandbox-preview-state"

    result = runner.invoke(
        app,
        [
            "init",
            str(repository),
            "--sandbox",
            "docker",
            "--preview",
            "--json",
        ],
        env={"AGENT_FLEET_HOME": str(state_root)},
    )

    assert result.exit_code == 2
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "CONFIG_INVALID"
    assert not state_root.exists()
    assert not (repository / ".fleet").exists()


def test_cli_docker_preview_is_static_and_writes_nothing(tmp_path: Path) -> None:
    runner = CliRunner()
    repository = _repository(tmp_path)
    state_root = tmp_path / "docker-preview-state"

    result = runner.invoke(
        app,
        [
            "init",
            str(repository),
            "--sandbox",
            "docker",
            "--docker-image",
            "agent-fleet-runner:test",
            "--preview",
            "--json",
        ],
        env={"AGENT_FLEET_HOME": str(state_root)},
    )

    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)["data"]
    assert data["sandbox"] == "docker"
    assert data["sandbox_configuration"]["image"] == "agent-fleet-runner:test"
    assert data["sandbox_capabilities"]["isolation_enforced"] is True
    assert not state_root.exists()
    assert not (repository / ".fleet").exists()


def test_cli_provider_init_missing_credential_is_stable_and_writes_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = CliRunner()
    repository = _repository(tmp_path)
    state_root = tmp_path / "missing-provider-state"
    variable_name = "PHASE2_DEFINITELY_MISSING_PROVIDER_KEY"
    credential_ref = f"env:{variable_name}"
    monkeypatch.delenv(variable_name, raising=False)

    result = runner.invoke(
        app,
        [
            "init",
            str(repository),
            "--runtime",
            "pydantic-ai",
            "--provider-model",
            "openai:gpt-5-mini",
            "--credential-ref",
            credential_ref,
            "--sandbox",
            "fake",
            "--yes",
            "--json",
        ],
        env={"AGENT_FLEET_HOME": str(state_root)},
    )

    assert result.exit_code == 2
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "CREDENTIAL_MISSING"
    assert credential_ref not in result.stdout
    assert variable_name not in result.stdout
    assert not state_root.exists()
    assert not (repository / ".fleet").exists()


def test_cli_malformed_credential_reference_is_rejected_without_echo(tmp_path: Path) -> None:
    runner = CliRunner()
    repository = _repository(tmp_path)
    state_root = tmp_path / "malformed-reference-state"
    malformed = "raw-provider-secret"

    result = runner.invoke(
        app,
        [
            "init",
            str(repository),
            "--runtime",
            "pydantic-ai",
            "--provider-model",
            "openai:gpt-5-mini",
            "--credential-ref",
            malformed,
            "--preview",
            "--json",
        ],
        env={"AGENT_FLEET_HOME": str(state_root)},
    )

    assert result.exit_code == 2
    assert json.loads(result.stdout)["error"]["code"] == "CONFIG_INVALID"
    assert malformed not in result.stdout
    assert not state_root.exists()
    assert not (repository / ".fleet").exists()


def test_cli_unsupported_provider_fails_before_credential_read_or_state_write(
    tmp_path: Path,
) -> None:
    runner = CliRunner()
    repository = _repository(tmp_path)
    state_root = tmp_path / "unsupported-provider-state"
    credential_ref = "env:PHASE2_UNREAD_PROVIDER_KEY"

    result = runner.invoke(
        app,
        [
            "init",
            str(repository),
            "--runtime",
            "pydantic-ai",
            "--provider-model",
            "unsupported-provider:offline",
            "--credential-ref",
            credential_ref,
            "--yes",
            "--json",
        ],
        env={"AGENT_FLEET_HOME": str(state_root)},
    )

    assert result.exit_code == 2
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "PROVIDER_UNSUPPORTED"
    assert credential_ref not in result.stdout
    assert not state_root.exists()
    assert not (repository / ".fleet").exists()


def test_cli_runtime_capability_mismatch_fails_before_state_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = CliRunner()
    repository = _repository(tmp_path)
    state_root = tmp_path / "capability-mismatch-state"
    container = build_container(state_root, migrate=False)
    container.projects.runtime_registry = RuntimeRegistry(
        {"pydantic-ai": MissingToolCallingRuntime()}
    )
    monkeypatch.setattr(cli_module, "build_container", lambda *args, **kwargs: container)

    result = runner.invoke(
        app,
        [
            "init",
            str(repository),
            "--runtime",
            "pydantic-ai",
            "--provider-model",
            "openai:gpt-5-mini",
            "--credential-ref",
            "env:CAPABILITY_MISMATCH_KEY",
            "--preview",
            "--json",
        ],
        env={"AGENT_FLEET_HOME": str(state_root)},
    )

    assert result.exit_code == 2
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "RUNTIME_CAPABILITY_MISSING"
    assert payload["error"]["details"]["missing_capabilities"] == ["tool_calling"]
    assert not state_root.exists()
    assert not (repository / ".fleet").exists()


def test_cli_provider_run_rechecks_missing_credential_before_run_creation(
    tmp_path: Path,
) -> None:
    runner = CliRunner()
    repository = _repository(tmp_path)
    state_root = tmp_path / "provider-run-state"
    variable_name = "PHASE2_TEMPORARY_PROVIDER_KEY"
    credential_ref = f"env:{variable_name}"
    sentinel = "phase2-temporary-provider-secret"
    base_environment = {"AGENT_FLEET_HOME": str(state_root)}

    _register_test_project(
        repository,
        state_root,
        runtime_name="pydantic-ai",
        provider_model="openai:gpt-5-mini",
        credential_ref=credential_ref,
        environment={variable_name: sentinel},
    )

    executed = runner.invoke(
        app,
        ["run", "Fix the canary behavior", "--project", str(repository), "--json"],
        env=base_environment,
    )

    assert executed.exit_code == 2
    payload = json.loads(executed.stdout)
    assert payload["error"]["code"] == "CREDENTIAL_MISSING"
    assert credential_ref not in executed.stdout
    assert variable_name not in executed.stdout
    assert sentinel not in executed.stdout
    with sqlite3.connect(state_root / "state.db") as connection:
        assert connection.execute("SELECT COUNT(*) FROM runs").fetchone() == (0,)

    doctor = runner.invoke(
        app,
        ["doctor", "--path", str(repository), "--json"],
        env=base_environment,
    )
    assert doctor.exit_code == 0, doctor.output
    report = json.loads(doctor.stdout)
    assert report["data"]["healthy"] is False
    credential_check = next(
        item for item in report["data"]["checks"] if item["name"] == "provider_credential"
    )
    assert credential_check["required"] is True
    assert credential_check["ok"] is False
    assert "status=missing" in credential_check["detail"]
    assert credential_ref not in doctor.stdout
    assert variable_name not in doctor.stdout
    assert sentinel not in doctor.stdout


def test_cli_real_runtime_rejects_explicit_fake_scenario_before_run_creation(
    tmp_path: Path,
) -> None:
    runner = CliRunner()
    repository = _repository(tmp_path)
    state_root = tmp_path / "provider-fake-scenario-state"
    variable_name = "PHASE2_FAKE_SCENARIO_PROVIDER_KEY"
    environment = {
        "AGENT_FLEET_HOME": str(state_root),
        variable_name: "phase2-fake-scenario-provider-secret",
    }
    _register_test_project(
        repository,
        state_root,
        runtime_name="pydantic-ai",
        provider_model="openai:gpt-5-mini",
        credential_ref=f"env:{variable_name}",
        environment={variable_name: environment[variable_name]},
    )

    result = runner.invoke(
        app,
        [
            "run",
            "Fix the canary behavior",
            "--project",
            str(repository),
            "--fake-scenario",
            "success",
            "--json",
        ],
        env=environment,
    )

    assert result.exit_code == 2
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "CONFIG_INVALID"
    with sqlite3.connect(state_root / "state.db") as connection:
        assert connection.execute("SELECT COUNT(*) FROM runs").fetchone() == (0,)


@pytest.mark.parametrize("option", ["--runtime", "--provider-model", "--credential-ref"])
def test_cli_empty_provider_override_is_not_silently_ignored(
    tmp_path: Path,
    option: str,
) -> None:
    runner = CliRunner()
    repository = _repository(tmp_path)
    state_root = tmp_path / f"empty-{option.removeprefix('--')}-state"
    variable_name = "PHASE2_EMPTY_OVERRIDE_PROVIDER_KEY"
    environment = {
        "AGENT_FLEET_HOME": str(state_root),
        variable_name: "phase2-empty-override-provider-secret",
    }
    _register_test_project(
        repository,
        state_root,
        runtime_name="pydantic-ai",
        provider_model="openai:gpt-5-mini",
        credential_ref=f"env:{variable_name}",
        environment={variable_name: environment[variable_name]},
    )

    result = runner.invoke(
        app,
        [
            "run",
            "Fix the canary behavior",
            "--project",
            str(repository),
            option,
            "",
            "--json",
        ],
        env=environment,
    )

    assert result.exit_code == 2
    assert json.loads(result.stdout)["error"]["code"] == "CONFIG_INVALID"
    with sqlite3.connect(state_root / "state.db") as connection:
        assert connection.execute("SELECT COUNT(*) FROM runs").fetchone() == (0,)


def test_cli_provider_failure_redacts_registered_secret_before_goal_and_error_persistence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = CliRunner()
    repository = _repository(tmp_path)
    state_root = tmp_path / "provider-redaction-state"
    variable_name = "PHASE2_DYNAMIC_REDACTION_KEY"
    credential_ref = f"env:{variable_name}"
    sentinel = "phase2-provider-secret+/="
    encoded = base64.b64encode(sentinel.encode()).decode()
    environment = {
        "AGENT_FLEET_HOME": str(state_root),
        variable_name: sentinel,
    }
    _register_test_project(
        repository,
        state_root,
        runtime_name="pydantic-ai",
        provider_model="openai:gpt-5-mini",
        credential_ref=credential_ref,
        environment={variable_name: sentinel},
    )

    def reject_client(**arguments: object) -> object:
        assert arguments["api_key"] == sentinel
        raise FleetError(
            ErrorCode.PROVIDER_FAILED,
            f"provider echoed {sentinel}",
            f"upstream diagnostic contained {encoded}",
            details={"raw": sentinel, "encoded": encoded},
        )

    monkeypatch.setattr(runtime_module, "AsyncOpenAI", reject_client)
    result = runner.invoke(
        app,
        [
            "run",
            f"Do not persist {sentinel} or {encoded}",
            "--project",
            str(repository),
            "--json",
        ],
        env=environment,
    )

    assert result.exit_code == 5
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "PROVIDER_FAILED"
    assert payload["error"]["details"]["run_id"].startswith("run_")
    assert sentinel not in result.stdout
    assert encoded not in result.stdout
    with sqlite3.connect(state_root / "state.db") as connection:
        [(stored_goal,)] = connection.execute("SELECT json_extract(data_json, '$.goal') FROM runs")
    assert "<redacted:" in stored_goal
    for path in state_root.rglob("*"):
        if path.is_file():
            content = path.read_bytes()
            assert sentinel.encode() not in content, path
            assert encoded.encode() not in content, path


@pytest.mark.parametrize("cause", ["api_rate_limit", "request_policy", "response_policy"])
def test_cli_runtime_diagnostic_survives_reopened_logs_without_provider_contents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cause: str,
) -> None:
    runner = CliRunner()
    repository = _repository(tmp_path)
    state_root = tmp_path / "safe-runtime-diagnostic-state"
    variable_name = "FLEET_OFFLINE_DIAGNOSTIC_KEY"
    sentinel = "safe-diagnostic-secret+/="
    encoded = base64.b64encode(sentinel.encode()).decode()
    environment = {"AGENT_FLEET_HOME": str(state_root), variable_name: sentinel}
    _register_test_project(
        repository,
        state_root,
        runtime_name="pydantic-ai",
        provider_model="openai:offline-test",
        credential_ref=f"env:{variable_name}",
        environment={variable_name: sentinel},
    )

    def reject_client(**arguments: object) -> object:
        assert arguments["api_key"] == sentinel
        if cause != "api_rate_limit":
            policy_error = (
                OpenAIRequestPolicyError()
                if cause == "request_policy"
                else OpenAIResponsePolicyError()
            )
            policy_error.__context__ = OpenAIError(sentinel)
            policy_error.add_note(encoded)
            raise policy_error
        response = httpx2.Response(
            429,
            request=httpx2.Request("POST", f"https://example.invalid/{sentinel}"),
            headers={"x-request-id": encoded},
        )
        raise RateLimitError(sentinel, response=response, body={"error": encoded})

    monkeypatch.setattr(runtime_module, "AsyncOpenAI", reject_client)
    result = runner.invoke(
        app,
        ["run", "Fix the bounded fixture", "--project", str(repository), "--json"],
        env=environment,
    )
    assert result.exit_code == 5
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "PROVIDER_FAILED"
    expected: dict[str, Any] = {"category": "provider_sdk", "cause_category": cause}
    if cause == "api_rate_limit":
        expected["http_status"] = 429
    assert payload["error"]["details"]["runtime_diagnostic"] == expected
    run_id = payload["error"]["details"]["run_id"]
    logs = runner.invoke(app, ["logs", run_id, "--json"], env=environment)
    assert logs.exit_code == 0
    assert expected == next(
        event["payload"]["runtime_diagnostic"]
        for event in json.loads(logs.stdout)["data"]
        if event["event_type"] == "agent.failed"
    )
    for output in (result.stdout, logs.stdout):
        assert sentinel not in output and encoded not in output
    for path in state_root.rglob("*"):
        if path.is_file():
            content = path.read_bytes()
            assert sentinel.encode() not in content and encoded.encode() not in content


def test_cli_tool_argument_diagnostic_survives_reopened_logs_and_settled_accounting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = CliRunner()
    repository = _repository(tmp_path)
    state_root = tmp_path / "tool-argument-diagnostic-state"
    variable_name = "FLEET_ACTION_TEST_KEY"
    untrusted_reason = "offline-untrusted-validation-input+/="
    environment = {"AGENT_FLEET_HOME": str(state_root), variable_name: SENTINEL}
    _register_test_project(
        repository,
        state_root,
        runtime_name="pydantic-ai",
        provider_model="openai:gpt-test",
        credential_ref=f"env:{variable_name}",
        environment={variable_name: SENTINEL},
    )
    sends: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        sends.append(request)
        if len(sends) == 1:
            return tool_response(
                request,
                [
                    (
                        "submit_scope_decision",
                        {
                            "normalized_goal": "Fix the canary behavior.",
                            "workflow": "code-change",
                            "change_kind": "code_change",
                            "fleet_strategy": "engineer_verifier",
                            "allowed_paths": ["src/canary_calc/core.py"],
                            "forbidden_paths": [".git", ".fleet"],
                            "acceptance_criteria": [
                                {
                                    "criterion_id": "canary-zero-division",
                                    "description": "divide by zero raises the stable ValueError",
                                }
                            ],
                            "required_evidence": [
                                "canonical_patch",
                                "command_evidence",
                                "independent_verifier_verdict",
                            ],
                        },
                    )
                ],
            )
        assert len(sends) == 2, "malformed tool arguments must not trigger a model retry"
        return tool_response(request, [("run_verification", {"reason": untrusted_reason})], 2)

    _, clients = sdk_adapter(monkeypatch, handler)
    with override_allow_model_requests(True):
        result = runner.invoke(
            app,
            ["run", "Fix the bounded fixture", "--project", str(repository), "--json"],
            env=environment,
        )
    assert result.exit_code == 5
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "RUNTIME_OUTPUT_INVALID"
    expected = {"category": "tool_arguments", "cause_category": "schema_validation"}
    assert payload["error"]["details"]["runtime_diagnostic"] == expected
    run_id = payload["error"]["details"]["run_id"]
    logs = runner.invoke(app, ["logs", run_id, "--json"], env=environment)
    assert logs.exit_code == 0
    assert expected == next(
        event["payload"]["runtime_diagnostic"]
        for event in json.loads(logs.stdout)["data"]
        if event["event_type"] == "agent.failed"
    )
    reopened = build_container(state_root)
    snapshot = reopened.budgets.snapshot(run_id)
    assert snapshot.model_requests == 2 and snapshot.reported_total_tokens == 30
    assert snapshot.tool_calls == snapshot.outstanding_requests == snapshot.unknown_requests == 0
    assert snapshot.reserved_tokens == 0 and snapshot.completeness == "complete"
    assert reopened.state.outstanding_leases(run_id) == []
    assert len(sends) == 2 and clients and all(client.is_closed for client in clients)
    forbidden = (
        SENTINEL.encode(),
        base64.b64encode(SENTINEL.encode()),
        untrusted_reason.encode(),
        base64.b64encode(untrusted_reason.encode()),
    )
    for output in (result.stdout.encode(), logs.stdout.encode()):
        assert not any(value in output for value in forbidden)
    for path in state_root.rglob("*"):
        if path.is_file():
            content = path.read_bytes()
            assert not any(value in content for value in forbidden)


def test_cli_offline_pydantic_ai_run_reports_usage_and_fake_sandbox_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = CliRunner()
    repository = _repository(tmp_path)
    state_root = tmp_path / "offline-provider-state"
    variable_name = "PHASE2_OFFLINE_PROVIDER_KEY"
    sentinel = "phase2-offline-provider-secret"
    environment = {
        "AGENT_FLEET_HOME": str(state_root),
        variable_name: sentinel,
    }
    calls: dict[str, int] = {}

    async def model_function(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> ModelResponse:
        assert messages
        assert "fake_scenario" not in repr(messages)
        output_name = info.output_tools[0].name
        calls[output_name] = calls.get(output_name, 0) + 1
        if output_name == "submit_scope_decision":
            payload = {
                "normalized_goal": "Fix the canary behavior.",
                "workflow": "code-change",
                "change_kind": "code_change",
                "fleet_strategy": "engineer_verifier",
                "allowed_paths": ["src/canary_calc/core.py"],
                "forbidden_paths": [".git", ".fleet"],
                "acceptance_criteria": [
                    {
                        "criterion_id": "canary-zero-division",
                        "description": "divide by zero raises the stable ValueError",
                    }
                ],
                "required_evidence": [
                    "canonical_patch",
                    "command_evidence",
                    "independent_verifier_verdict",
                ],
            }
        elif output_name == "submit_implementation_report" and calls[output_name] == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "workspace_write_file",
                        {
                            "path": "src/canary_calc/core.py",
                            "content": FIXED_CANARY,
                            "reason": "Apply the bounded canary repair.",
                        },
                        tool_call_id="cli-engineer-write",
                    ),
                    ToolCallPart(
                        "run_verification",
                        {
                            "command_id": "python-test",
                            "reason": "Record declared simulated evidence.",
                        },
                        tool_call_id="cli-engineer-check",
                    ),
                ]
            )
        elif output_name == "submit_implementation_report":
            payload = {
                "summary": "Applied the bounded canary repair.",
                "intended_changed_paths": ["src/canary_calc/core.py"],
                "tests_added_or_changed": [],
                "criterion_results": ["canary-zero-division: candidate updated"],
                "evidence_artifact_ids": [],
                "unresolved_limitations": ["FakeSandbox did not execute project code."],
                "verifier_focus": ["Check the exact ValueError behavior."],
            }
        elif output_name == "submit_verifier_verdict" and calls[output_name] == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "run_verification",
                        {
                            "command_id": "python-test",
                            "reason": "Record independent simulated evidence.",
                        },
                        tool_call_id="cli-verifier-check",
                    )
                ]
            )
        else:
            assert output_name == "submit_verifier_verdict"
            payload = {
                "verdict": "pass",
                "criterion_results": ["canary-zero-division: passed review"],
                "evidence_artifact_ids": [],
                "regressions": [],
                "required_repairs": [],
                "proof_gaps": ["FakeSandbox did not execute project code."],
                "rationale": "Review passed, but execution remains simulated.",
            }
        return ModelResponse(
            parts=[ToolCallPart(output_name, payload, tool_call_id=f"cli-{output_name}")]
        )

    class OfflineClient:
        async def __aenter__(self) -> OfflineClient:
            return self

        async def __aexit__(
            self,
            exception_type: type[BaseException] | None,
            exception: BaseException | None,
            traceback: TracebackType | None,
        ) -> None:
            del exception_type, exception, traceback

    def client_factory(**arguments: object) -> OfflineClient:
        assert arguments["api_key"] == sentinel
        assert arguments["max_retries"] == 0
        return OfflineClient()

    def provider_factory(*, openai_client: object) -> object:
        assert isinstance(openai_client, OfflineClient)
        return object()

    def model_factory(model_name: object, *, provider: object) -> Model:
        assert model_name == "gpt-5-mini"
        assert provider is not None
        return FunctionModel(model_function)

    monkeypatch.setattr(runtime_module, "AsyncOpenAI", client_factory)
    monkeypatch.setattr(runtime_module, "OpenAIProvider", provider_factory)
    monkeypatch.setattr(runtime_module, "OpenAIResponsesModel", model_factory)

    _register_test_project(
        repository,
        state_root,
        runtime_name="pydantic-ai",
        provider_model="openai:gpt-5-mini",
        credential_ref=f"env:{variable_name}",
        environment={variable_name: sentinel},
    )

    executed = runner.invoke(
        app,
        ["run", "Fix the canary behavior", "--project", str(repository), "--json"],
        env=environment,
    )

    assert executed.exit_code == 0, executed.output
    envelope = json.loads(executed.stdout)
    data = envelope["data"]
    run_id = data["run_id"]
    assert data["status"] == "ready_for_review"
    assert data["runtime"] == "pydantic-ai"
    assert data["provider_model"] == "openai:gpt-5-mini"
    assert len(data["runtime_usage_artifact_ids"]) == 3
    assert data["verified_complete"] is False
    assert "SIMULATED_EVIDENCE_ONLY" in data["evidence"]["completion_reason_codes"]
    assert "model provider was contacted" in envelope["warnings"][0]
    assert "FakeSandbox" in envelope["warnings"][0]
    assert calls == {
        "submit_scope_decision": 1,
        "submit_implementation_report": 2,
        "submit_verifier_verdict": 2,
    }
    assert sentinel not in executed.stdout
    assert variable_name not in executed.stdout

    human = runner.invoke(app, ["resume", run_id], env=environment)
    assert human.exit_code == 0, human.output
    assert "model provider was contacted" in human.stdout
    assert "FakeSandbox" in human.stdout
    assert sentinel not in human.stdout


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
