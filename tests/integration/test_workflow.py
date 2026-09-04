from __future__ import annotations

import json
import runpy
from pathlib import Path

import pytest
from conftest import FleetHarness

from agent_fleet.adapters.repository.git import BROKEN_CANARY, FIXED_CANARY
from agent_fleet.bootstrap import build_container
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import ArtifactKind, FakeScenario, RunStatus
from agent_fleet.domain.security import sha256_bytes


@pytest.mark.integration
@pytest.mark.asyncio
async def test_successful_run_persists_ordered_evidence_and_applies_exact_patch(
    harness: FleetHarness,
) -> None:
    run = await harness.start()
    assert run.status is RunStatus.READY_FOR_REVIEW
    assert run.patch_artifact_id is not None
    patch = harness.container.patches.show(run.run_id)
    assert '+        raise ValueError("division by zero is not allowed")' in patch
    assert run.patch_sha256 == sha256_bytes(patch.encode())
    assert (harness.repository_root / "src/canary_calc/core.py").read_text() == BROKEN_CANARY

    events = harness.container.state.list_events(run.run_id)
    assert [event.sequence for event in events] == list(range(1, len(events) + 1))
    assert {"task.scoped", "verification.completed", "patch.ready"} <= {
        event.event_type for event in events
    }
    artifacts = harness.container.state.list_artifacts(run.run_id)
    kinds = {artifact.kind for artifact in artifacts}
    assert {
        ArtifactKind.TASK_SPEC,
        ArtifactKind.IMPLEMENTATION_REPORT,
        ArtifactKind.PATCH,
        ArtifactKind.VERIFIER_VERDICT,
        ArtifactKind.RUN_SUMMARY,
    } <= kinds
    assert harness.container.state.active_leases(run.run_id) == []

    completed, result = harness.container.patches.apply(run.run_id)
    assert completed.status is RunStatus.COMPLETED
    assert result.changed_paths == ["src/canary_calc/core.py"]
    assert (harness.repository_root / "src/canary_calc/core.py").read_text() == FIXED_CANARY
    namespace = runpy.run_path(str(harness.repository_root / "src/canary_calc/core.py"))
    with pytest.raises(ValueError, match="division by zero is not allowed"):
        namespace["divide"](1, 0)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_verifier_fail_reaches_rejected_after_bound(harness: FleetHarness) -> None:
    run = await harness.start(FakeScenario.FAIL)
    assert run.status is RunStatus.REJECTED
    assert run.repair_iterations == 1
    verdicts = [
        item
        for item in harness.container.state.list_artifacts(run.run_id)
        if item.kind is ArtifactKind.VERIFIER_VERDICT
    ]
    assert len(verdicts) == 2
    assert harness.container.state.active_leases(run.run_id) == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_one_repair_iteration_then_pass(harness: FleetHarness) -> None:
    run = await harness.start(FakeScenario.REPAIR)
    assert run.status is RunStatus.READY_FOR_REVIEW
    assert run.repair_iterations == 1
    assert (
        sum(
            event.event_type == "repair.requested"
            for event in harness.container.state.list_events(run.run_id)
        )
        == 1
    )
    assert harness.container.patches.show(run.run_id).count("division by zero is not allowed") >= 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_inconclusive_is_presented_with_proof_gap(harness: FleetHarness) -> None:
    run = await harness.start(FakeScenario.INCONCLUSIVE)
    assert run.status is RunStatus.READY_FOR_REVIEW
    verdicts = [
        item
        for item in harness.container.state.list_artifacts(run.run_id)
        if item.kind is ArtifactKind.VERIFIER_VERDICT
    ]
    content = harness.container.artifacts.read_text(verdicts[-1].artifact_id)
    assert '"verdict": "inconclusive"' in content
    assert "No project code was executed" in content


@pytest.mark.integration
@pytest.mark.asyncio
async def test_verifier_mutation_is_detected_discarded_and_absent_from_patch(
    harness: FleetHarness,
) -> None:
    run = await harness.start(FakeScenario.VERIFIER_MUTATION)
    assert run.status is RunStatus.READY_FOR_REVIEW
    assert run.verifier_workspace_mutated is True
    assert "verifier-untrusted-note" not in harness.container.patches.show(run.run_id)
    assert not (harness.repository_root / "verifier-untrusted-note.txt").exists()
    assert harness.container.state.active_leases(run.run_id) == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_dirty_target_refuses_apply_without_losing_file(harness: FleetHarness) -> None:
    run = await harness.start()
    user_file = harness.repository_root / "user-work.txt"
    user_file.write_text("preserve me\n", encoding="utf-8")
    with pytest.raises(FleetError) as captured:
        harness.container.patches.apply(run.run_id)
    assert captured.value.code is ErrorCode.PATCH_TARGET_DIVERGED
    assert user_file.read_text(encoding="utf-8") == "preserve me\n"
    assert harness.container.state.get_run(run.run_id).status is RunStatus.READY_FOR_REVIEW


@pytest.mark.integration
@pytest.mark.asyncio
async def test_patch_application_rechecks_run_to_artifact_hash_binding(
    harness: FleetHarness,
) -> None:
    run = await harness.start()
    tampered = run.model_copy(
        update={"patch_sha256": "0" * 64, "updated_at": harness.container.state.clock.now()}
    )
    harness.container.state.save_run(
        tampered, "patch.metadata_tampered_for_test", {"test_only": True}
    )
    with pytest.raises(FleetError) as captured:
        harness.container.patches.apply(run.run_id)
    assert captured.value.code is ErrorCode.ARTIFACT_INTEGRITY_FAILED
    assert (harness.repository_root / "src/canary_calc/core.py").read_text() == BROKEN_CANARY


@pytest.mark.integration
@pytest.mark.asyncio
async def test_diverged_head_refuses_apply(harness: FleetHarness) -> None:
    run = await harness.start()
    harness.git("add", ".fleet")
    harness.git(
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-m",
        "commit fleet config",
    )
    with pytest.raises(FleetError) as captured:
        harness.container.patches.apply(run.run_id)
    assert captured.value.code is ErrorCode.PATCH_TARGET_DIVERGED
    assert (harness.repository_root / "src/canary_calc/core.py").read_text() == BROKEN_CANARY


@pytest.mark.integration
@pytest.mark.asyncio
async def test_init_emits_proposal_and_exposes_disposable_canary(harness: FleetHarness) -> None:
    project = harness.container.state.get_project_by_root(str(harness.repository_root.resolve()))
    assert project is not None
    assert (harness.repository_root / ".fleet/fleet.yaml").exists()
    canary = harness.state_root / "projects" / project.project_id / "canaries" / "bootstrap"
    assert (canary / ".git").exists()
    with harness.container.state._connect() as connection:
        proposal_artifacts = connection.execute(
            "SELECT data_json FROM artifacts WHERE project_id = ? AND run_id IS NULL",
            (project.project_id,),
        ).fetchall()
    assert proposal_artifacts
    assert json.loads(proposal_artifacts[0]["data_json"])["kind"] == "fleet_config_proposal"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_secret_sentinel_is_absent_from_persistent_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sentinel = "FLEET-SUPER-SECRET-SENTINEL"
    monkeypatch.setenv("AGENT_FLEET_REDACT_VALUES", sentinel)
    bootstrap = build_container(tmp_path / "fixture-tools")
    repository_root = bootstrap.repository.create_canary_fixture(
        tmp_path / "fixture-tools" / "target"
    )
    state_root = tmp_path / "redacted-state"
    container = build_container(state_root)
    container.projects.initialize(repository_root, runtime_name="fake", sandbox_name="fake")
    run = await container.workflow.start(
        project_path=repository_root,
        goal=f"Fix the canary behavior; never reveal {sentinel}",
        runtime_name="fake",
        sandbox_name="fake",
        fake_scenario=FakeScenario.SUCCESS,
    )
    assert run.status is RunStatus.READY_FOR_REVIEW
    paused = await container.workflow.start(
        project_path=repository_root,
        goal="Exercise approval redaction",
        runtime_name="fake",
        sandbox_name="fake",
        fake_scenario=FakeScenario.APPROVAL,
    )
    assert paused.pending_approval_id is not None
    container.approvals.deny(paused.pending_approval_id, f"do not expose {sentinel}")
    for path in state_root.rglob("*"):
        if path.is_file():
            assert sentinel.encode() not in path.read_bytes(), path
    assert all(not request.environment for request in container.sandbox.requests)
