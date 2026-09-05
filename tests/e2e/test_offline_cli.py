from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import cast

import pytest

from agent_fleet.adapters.repository.git import GitRepositoryAdapter
from agent_fleet.adapters.system import UuidIdGenerator
from agent_fleet.bootstrap import build_container
from agent_fleet.domain.models import FakeScenario, RunStatus


def _invoke(
    executable: Path, arguments: list[str], environment: dict[str, str]
) -> dict[str, object]:
    result = subprocess.run(
        [str(executable), *arguments, "--json"],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    parsed = json.loads(result.stdout)
    if not isinstance(parsed, dict):
        raise TypeError("fleet JSON output must be an object")
    return cast(dict[str, object], parsed)


def _invoke_failure(
    executable: Path,
    arguments: list[str],
    environment: dict[str, str],
) -> dict[str, object]:
    result = subprocess.run(
        [str(executable), *arguments, "--json"],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert result.returncode == 1, result.stderr
    parsed = json.loads(result.stdout)
    assert isinstance(parsed, dict)
    return cast(dict[str, object], parsed)


def _seed_legacy_fake_project(repository: Path, state_root: Path) -> dict[str, object]:
    """Seed an already-trusted legacy Project so offline E2E can test later commands."""

    return build_container(state_root).projects._initialize_without_canary(
        repository,
        runtime_name="fake",
        sandbox_name="fake",
    )


@pytest.mark.e2e
def test_subprocess_offline_flow_applies_behavioral_fix(tmp_path: Path) -> None:
    repository = GitRepositoryAdapter(tmp_path, UuidIdGenerator()).create_canary_fixture(
        tmp_path / "e2e-repository"
    )
    fleet_executable = Path(sys.executable).parent / "fleet"
    assert fleet_executable.exists()
    environment = {
        key: value
        for key, value in os.environ.items()
        if key in {"PATH", "SYSTEMROOT", "TMPDIR", "TEMP", "TMP", "LANG", "LC_ALL"}
    }
    state_root = tmp_path / "e2e-state"
    environment["AGENT_FLEET_HOME"] = str(state_root)

    rejected = _invoke_failure(
        fleet_executable,
        ["init", str(repository), "--runtime", "fake", "--sandbox", "fake", "--yes"],
        environment,
    )
    assert rejected["ok"] is False
    error = rejected["error"]
    assert isinstance(error, dict)
    assert error["code"] == "BOOTSTRAP_CANARY_FAILED"
    assert not (repository / ".fleet").exists()

    initialized_data = _seed_legacy_fake_project(repository, state_root)
    repository_profile = initialized_data["repository_profile"]
    sandbox_capabilities = initialized_data["sandbox_capabilities"]
    assert isinstance(repository_profile, dict)
    assert isinstance(sandbox_capabilities, dict)
    assert repository_profile["ecosystems"] == ["python"]
    assert sandbox_capabilities["executes_code"] is False
    executed = _invoke(
        fleet_executable,
        [
            "run",
            "Fix the canary behavior",
            "--project",
            str(repository),
            "--runtime",
            "fake",
            "--sandbox",
            "fake",
        ],
        environment,
    )
    data = executed["data"]
    assert isinstance(data, dict)
    run_id = str(data["run_id"])
    assert data["status"] == "ready_for_review"
    assert data["fleet_strategy"] == "engineer_verifier"
    assert data["assurance_verdict"] == "inconclusive"
    assert data["verified_complete"] is False
    evidence = data["evidence"]
    assert isinstance(evidence, dict)
    assert evidence["changed_paths"] == ["src/canary_calc/core.py"]
    assert {"PROOF_GAPS_PRESENT", "SIMULATED_EVIDENCE_ONLY"} <= set(
        evidence["completion_reason_codes"]
    )
    assert any(
        isinstance(gap, dict) and gap.get("code") == "SIMULATED_EXECUTION"
        for gap in evidence["proof_gaps"]
    )
    assert all(
        isinstance(result, dict) and result.get("strength") == "simulated"
        for result in evidence["command_results"]
    )

    for arguments in (
        ["status", run_id],
        ["logs", run_id],
        ["artifacts", run_id],
        ["patch", "show", run_id],
    ):
        inspected = _invoke(fleet_executable, arguments, environment)
        assert inspected["ok"] is True

    applied = _invoke(fleet_executable, ["patch", "apply", run_id], environment)
    applied_data = applied["data"]
    assert isinstance(applied_data, dict)
    assert applied_data["status"] == "completed"
    assert applied_data["changed_paths"] == ["src/canary_calc/core.py"]

    behavior_environment = dict(environment)
    behavior_environment["PYTHONPATH"] = str(repository / "src")
    subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from canary_calc import divide; "
                "\ntry: divide(1, 0)"
                "\nexcept ValueError as error: "
                "assert str(error) == 'division by zero is not allowed'"
                "\nelse: raise AssertionError('ValueError not raised')"
            ),
        ],
        check=True,
        capture_output=True,
        text=True,
        env=behavior_environment,
    )


@pytest.mark.e2e
def test_subprocess_approval_pause_approve_resume_is_exactly_once(tmp_path: Path) -> None:
    repository = GitRepositoryAdapter(tmp_path, UuidIdGenerator()).create_canary_fixture(
        tmp_path / "approval-repository"
    )
    fleet_executable = Path(sys.executable).parent / "fleet"
    environment = {
        key: value
        for key, value in os.environ.items()
        if key in {"PATH", "SYSTEMROOT", "TMPDIR", "TEMP", "TMP", "LANG", "LC_ALL"}
    }
    state_root = tmp_path / "approval-state"
    environment["AGENT_FLEET_HOME"] = str(state_root)
    _seed_legacy_fake_project(repository, state_root)
    paused = _invoke(
        fleet_executable,
        [
            "run",
            "Fix the canary behavior",
            "--project",
            str(repository),
            "--fake-scenario",
            "approval",
        ],
        environment,
    )
    paused_data = paused["data"]
    assert isinstance(paused_data, dict)
    assert paused_data["status"] == "paused_for_approval"
    run_id = str(paused_data["run_id"])
    request_id = str(paused_data["pending_approval_id"])

    approved = _invoke(fleet_executable, ["approve", request_id, "--once"], environment)
    assert approved["ok"] is True
    resumed = _invoke(fleet_executable, ["resume", run_id], environment)
    resumed_data = resumed["data"]
    assert isinstance(resumed_data, dict)
    assert resumed_data["status"] == "ready_for_review"
    repeated = _invoke(fleet_executable, ["resume", run_id], environment)
    assert repeated["ok"] is True
    logs = _invoke(fleet_executable, ["logs", run_id], environment)
    log_data = logs["data"]
    assert isinstance(log_data, list)
    assert (
        sum(
            isinstance(event, dict) and event.get("event_type") == "capability.consumed"
            for event in log_data
        )
        == 1
    )
    assert (
        sum(
            isinstance(event, dict)
            and event.get("event_type") == "tool.intent_executed"
            and event.get("payload", {}).get("action") == "fixture.record_side_effect"
            for event in log_data
        )
        == 1
    )


@pytest.mark.e2e
def test_subprocess_exact_recovery_requires_owner_confirmation_and_never_replays(
    tmp_path: Path,
) -> None:
    repository = GitRepositoryAdapter(tmp_path, UuidIdGenerator()).create_canary_fixture(
        tmp_path / "recovery-repository"
    )
    fleet_executable = Path(sys.executable).parent / "fleet"
    state_root = tmp_path / "recovery-state"
    environment = {
        key: value
        for key, value in os.environ.items()
        if key in {"PATH", "SYSTEMROOT", "TMPDIR", "TEMP", "TMP", "LANG", "LC_ALL"}
    }
    environment["AGENT_FLEET_HOME"] = str(state_root)
    _seed_legacy_fake_project(repository, state_root)
    container = build_container(state_root)
    paused = asyncio.run(
        container.workflow.start(
            project_path=repository,
            goal="Create a recoverable interrupted run",
            runtime_name="fake",
            sandbox_name="fake",
            fake_scenario=FakeScenario.APPROVAL,
        )
    )
    interrupted = paused.model_copy(
        update={
            "status": RunStatus.RUNNING,
            "pending_approval_id": None,
            "updated_at": container.state.clock.now(),
        }
    )
    container.state.save_run(
        interrupted,
        "run.resumed",
        {"reason": "simulated process loss before CLI reconstruction"},
    )
    before = list(container.state.outstanding_leases(paused.run_id))
    assert before

    refused = _invoke_failure(fleet_executable, ["recover", paused.run_id], environment)
    refused_error = refused["error"]
    assert isinstance(refused_error, dict)
    assert refused_error["code"] == "RECOVERY_REQUIRED"
    assert build_container(state_root).state.outstanding_leases(paused.run_id)

    recovered = _invoke(
        fleet_executable,
        ["recover", paused.run_id, "--confirm-owner-stopped"],
        environment,
    )
    recovered_data = recovered["data"]
    assert isinstance(recovered_data, dict)
    assert recovered_data["run_id"] == paused.run_id
    assert recovered_data["status"] == "failed"
    assert recovered_data["recovered"] is True
    assert set(recovered_data["recovered_lease_ids"]) == {item.lease_id for item in before}
    assert recovered_data["outstanding_lease_ids"] == []
    reconstructed = build_container(state_root)
    assert (
        reconstructed.state.count_executed_intents(paused.run_id, "fixture.record_side_effect") == 0
    )

    repeated = _invoke(
        fleet_executable,
        ["recover", paused.run_id, "--confirm-owner-stopped"],
        environment,
    )
    repeated_data = repeated["data"]
    assert isinstance(repeated_data, dict)
    assert repeated_data["recovered"] is False
    assert repeated_data["recovered_lease_ids"] == []
    assert repeated_data["outstanding_lease_ids"] == []


@pytest.mark.e2e
def test_subprocess_preview_and_adaptive_topologies_are_observable(tmp_path: Path) -> None:
    repository = GitRepositoryAdapter(tmp_path, UuidIdGenerator()).create_canary_fixture(
        tmp_path / "adaptive-repository"
    )
    fleet_executable = Path(sys.executable).parent / "fleet"
    state_root = tmp_path / "adaptive-state"
    environment = {
        key: value
        for key, value in os.environ.items()
        if key in {"PATH", "SYSTEMROOT", "TMPDIR", "TEMP", "TMP", "LANG", "LC_ALL"}
    }
    environment["AGENT_FLEET_HOME"] = str(state_root)

    preview = _invoke(
        fleet_executable,
        ["init", str(repository), "--preview"],
        environment,
    )
    preview_data = preview["data"]
    assert isinstance(preview_data, dict)
    assert "--- a/.fleet/fleet.yaml" in str(preview_data["proposal_patch"])
    assert not (repository / ".fleet").exists()
    assert not state_root.exists()

    rejected = _invoke_failure(
        fleet_executable,
        ["init", str(repository), "--yes"],
        environment,
    )
    assert rejected["ok"] is False
    assert not (repository / ".fleet").exists()
    _seed_legacy_fake_project(repository, state_root)
    direct = _invoke(
        fleet_executable,
        [
            "run",
            "Explain the current repository state",
            "--project",
            str(repository),
            "--fake-scenario",
            "direct",
        ],
        environment,
    )
    direct_data = direct["data"]
    assert isinstance(direct_data, dict)
    assert direct_data["status"] == "completed"
    assert direct_data["fleet_strategy"] == "direct"
    assert direct_data["patch_artifact_id"] is None
    assert direct_data["verified_complete"] is False

    single = _invoke(
        fleet_executable,
        [
            "run",
            "Fix the canary with one engineer",
            "--project",
            str(repository),
            "--fake-scenario",
            "single_engineer",
        ],
        environment,
    )
    single_data = single["data"]
    assert isinstance(single_data, dict)
    assert single_data["status"] == "ready_for_review"
    assert single_data["fleet_strategy"] == "single_engineer"
    assert single_data["verifier_verdict_artifact_id"] is None
    assert single_data["verified_complete"] is False

    logs = _invoke(fleet_executable, ["logs", str(single_data["run_id"])], environment)
    log_data = logs["data"]
    assert isinstance(log_data, list)
    completed_roles = [
        event.get("payload", {}).get("role")
        for event in log_data
        if isinstance(event, dict) and event.get("event_type") == "agent.completed"
    ]
    assert completed_roles == ["cos", "engineer"]
