"""Offline roles with genuine Docker/pytest evidence for the exact live fixture.

This proves standalone module repair, not provider connectivity or package builds.
The repair scenario retains failed commands and an earlier Verifier identity. Its
last tests pass, but current completion policy conservatively keeps it unverified.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

import pytest
from live_provider_support import (
    ROOT_LIMITS,
    CanaryEvidence,
    assert_live_canary_verification,
    prepare_live_canary_fixture,
)
from typer.testing import CliRunner

from agent_fleet.bootstrap import build_container
from agent_fleet.cli.app import app
from agent_fleet.domain.evidence import CommandEvidence, EvidenceBundle, EvidenceStrength
from agent_fleet.domain.models import ArtifactKind, RunStatus, TaskSpec, Verdict
from agent_fleet.domain.offline_canary import BROKEN_CANARY

pytestmark = pytest.mark.docker_integration


@pytest.mark.parametrize("scenario", ["success", "repair"])
def test_public_fake_runtime_repairs_live_fixture_with_actual_docker_pytest(
    tmp_path: Path,
    real_docker_image: str,
    request: pytest.FixtureRequest,
    scenario: Literal["success", "repair"],
) -> None:
    state_root = tmp_path / "fleet-state"
    target = tmp_path / "live-provider-repository"
    recorder = CanaryEvidence(state_root, target, (), selected_model="fake")
    request.addfinalizer(recorder.finish)
    target = prepare_live_canary_fixture(target)
    runner = CliRunner()

    def invoke(arguments: list[str]) -> dict[str, Any]:
        result = runner.invoke(app, arguments, env={"AGENT_FLEET_HOME": str(state_root)})
        assert result.exit_code == 0, result.output
        envelope = json.loads(result.stdout)
        assert envelope["ok"] is True
        data = envelope["data"]
        assert isinstance(data, dict)
        return data

    initialized = invoke(
        [
            "init",
            str(target),
            "--runtime",
            "fake",
            "--sandbox",
            "docker",
            "--docker-image",
            real_docker_image,
            "--yes",
            "--json",
        ]
    )
    assert initialized["bootstrap_verified"] is True
    assert initialized["bootstrap_cleanup_complete"] is True
    assert initialized["runtime"] == "fake" and initialized["sandbox"] == "docker"
    assert_live_canary_verification(target)
    container = build_container(state_root)
    baseline = container.repository.inspect(target)
    result = invoke(
        [
            "run",
            "Repair only src/canary_calc/core.py and independently verify the stable error.",
            "--project",
            str(target),
            "--sandbox",
            "docker",
            "--fake-scenario",
            scenario,
            *[
                argument
                for name, value in ROOT_LIMITS.items()
                for argument in ("--" + name.replace("_", "-"), str(value))
            ],
            "--json",
        ]
    )
    run_id = result["run_id"]
    for _ in range(12):
        if result["status"] != "paused_for_approval":
            break
        approval_id = result["pending_approval_id"]
        invoke(["permissions", "explain", approval_id, "--json"])
        invoke(["approve", approval_id, "--run", "--json"])
        result = invoke(["resume", run_id, "--json"])
    assert result["status"] == "ready_for_review"
    status = invoke(["status", run_id, "--json"])
    expected_complete = scenario == "success"
    assert status["verified_complete"] is expected_complete
    assert status["runtime"] == "fake" and status["sandbox"] == "docker"

    container = build_container(state_root)
    run = container.state.get_run(run_id)
    assert run.status is RunStatus.READY_FOR_REVIEW
    assert run.verified_complete is expected_complete
    assert run.repair_iterations == (1 if scenario == "repair" else 0)
    assert run.task_spec_artifact_id is not None
    task = TaskSpec.model_validate_json(container.artifacts.read_text(run.task_spec_artifact_id))
    assert task.allowed_paths == ["src/canary_calc/core.py"]
    assert task.required_verification_command_ids == ["python-test"]
    assert [item.command_id for item in task.verification_commands] == ["python-test"]

    assert run.evidence_bundle_artifact_id is not None
    bundle = EvidenceBundle.model_validate_json(
        container.artifacts.read_text(run.evidence_bundle_artifact_id)
    )
    assert bundle.completion_decision is not None
    assert bundle.completion_decision.verified_complete is expected_complete
    if scenario == "repair":
        # Passing the final tests cannot silently discard the first failed candidate
        # or relabel its distinct Verifier as the owner of the accepted final proof.
        assert bundle.completion_decision.effective_verdict is Verdict.FAIL
        assert set(bundle.completion_decision.reason_codes) == {
            "COMMAND_EXECUTION_FAILED",
            "CRITERION_NOT_PASSING",
            "EVIDENCE_STRENGTH_INVALID",
        }
        assert all(item.verdict is Verdict.FAIL for item in bundle.criterion_assessments)
    else:
        assert bundle.completion_decision.effective_verdict is Verdict.PASS
        assert bundle.completion_decision.reason_codes == []
    assert bundle.proof_gaps == []
    assert bundle.cleanup_complete and bundle.cleanup_receipt_artifact_id is not None
    commands = [
        CommandEvidence.model_validate_json(container.artifacts.read_text(identifier))
        for identifier in run.command_evidence_artifact_ids
    ]
    assert len(commands) == (4 if scenario == "repair" else 2)
    assert {item.command_id for item in commands} == {"python-test"}
    assert {item.principal_role for item in commands} == {"engineer", "verifier"}
    assert len({item.agent_instance_id for item in commands}) >= 2
    for command in commands:
        assert command.executable == "python" and command.argv == ["-m", "pytest"]
        assert command.sandbox_provider == "docker"
        assert command.sandbox_security_level == "isolated" and command.network_mode == "none"
        assert command.sandbox_inspection_artifact_id is not None
        assert not command.timed_out and not command.output_truncated
        assert command.strength is (
            EvidenceStrength.INDEPENDENTLY_VERIFIED
            if command.principal_role == "verifier"
            else EvidenceStrength.OBSERVED
        )
        transcript = container.artifacts.read_text(command.transcript_artifact_id)
        assert ("1 passed" if command.exit_code == 0 else "1 failed") in transcript
    if scenario == "repair":
        assert [item.exit_code for item in commands] == [1, 1, 0, 0]
        verdicts = [
            json.loads(container.artifacts.read_text(item.artifact_id))["verdict"]
            for item in container.state.list_artifacts(run_id)
            if item.kind is ArtifactKind.VERIFIER_VERDICT
        ]
        assert verdicts == [Verdict.FAIL.value, Verdict.PASS.value]
    else:
        assert all(item.exit_code == 0 for item in commands)
    final_verifier = commands[-1]
    assert final_verifier.principal_role == "verifier"
    assert final_verifier.agent_instance_id == run.verifier_agent_instance_id
    assert final_verifier.candidate_patch_sha256 == bundle.patch_sha256

    assert run.patch_artifact_id is not None
    patch = container.artifacts.read_text(run.patch_artifact_id)
    assert [line for line in patch.splitlines() if line.startswith("diff --git ")] == [
        "diff --git a/src/canary_calc/core.py b/src/canary_calc/core.py"
    ]
    assert '+        raise ValueError("division by zero is not allowed")' in patch
    assert (target / "src/canary_calc/core.py").read_text() == BROKEN_CANARY
    current = container.repository.inspect(target)
    assert current.head_revision == baseline.head_revision
    assert current.status_fingerprint == baseline.status_fingerprint
    assert not container.state.outstanding_leases()
    recorder.passed = True
