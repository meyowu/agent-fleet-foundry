from __future__ import annotations

import pytest
from conftest import FleetHarness

from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.evidence import CommandEvidence
from agent_fleet.domain.models import (
    ArtifactKind,
    CriterionResult,
    FakeScenario,
    Run,
    TaskSpec,
    Verdict,
    VerifierVerdict,
)


async def _multiple_criteria(harness: FleetHarness) -> tuple[Run, TaskSpec]:
    run = await harness.start(FakeScenario.SUCCESS)
    assert run.task_id is not None
    task = harness.container.state.get_task(run.task_id)
    task = task.model_copy(
        update={
            "allowed_paths": ["src"],
            "acceptance_criteria": [
                task.acceptance_criteria[0],
                task.acceptance_criteria[0].model_copy(
                    update={"criterion_id": "additional-behavior"}
                ),
            ],
        }
    )
    artifact = harness.container.artifacts.create_text(
        kind=ArtifactKind.TASK_SPEC,
        project_id=run.project_id,
        run_id=run.run_id,
        task_id=task.task_id,
        content=task.model_dump_json(),
        producer="test-fixture",
    )
    return run.model_copy(
        update={
            "task_spec_artifact_id": artifact.artifact_id,
            "task_spec_hash": artifact.sha256,
        }
    ), task


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True])
async def test_assembler_preserves_multi_criterion_contract_and_fake_assurance_boundary(
    harness: FleetHarness,
    structured: bool,
) -> None:
    run, task = await _multiple_criteria(harness)
    assert run.verifier_verdict_artifact_id is not None
    verdict = VerifierVerdict.model_validate_json(
        harness.container.artifacts.read_text(run.verifier_verdict_artifact_id)
    )
    if structured:
        commands = [
            CommandEvidence.model_validate_json(harness.container.artifacts.read_text(identifier))
            for identifier in run.command_evidence_artifact_ids
        ]
        verifier_command = next(
            item for item in commands if item.agent_instance_id == run.verifier_agent_instance_id
        )
        verdict.structured_criterion_results = [
            CriterionResult(
                criterion_id=criterion.criterion_id,
                verdict=Verdict.PASS,
                evidence_artifact_ids=[verifier_command.evidence_id],
                command_ids=[verifier_command.command_id],
                explanation="Claimed fake mapping is not executed proof.",
            )
            for criterion in task.acceptance_criteria
        ]
    artifact = harness.container.artifacts.create_text(
        kind=ArtifactKind.VERIFIER_VERDICT,
        project_id=run.project_id,
        run_id=run.run_id,
        task_id=task.task_id,
        content=verdict.model_dump_json(),
        producer="test-fixture",
    )
    bundle = harness.container.workflow.evidence.assemble(
        run.model_copy(update={"verifier_verdict_artifact_id": artifact.artifact_id}), task
    )
    assert bundle.changed_paths == ["src/canary_calc/core.py"]
    assert bundle.structured_criterion_results == verdict.structured_criterion_results
    assert all(item.verdict is Verdict.INCONCLUSIVE for item in bundle.criterion_assessments)
    assert bundle.completion_decision is not None
    assert not bundle.completion_decision.verified_complete
    codes = {gap.code for gap in bundle.proof_gaps}
    assert "SIMULATED_EXECUTION" in codes
    assert (
        "STRUCTURED_CRITERION_MAPPING_INVALID"
        if structured
        else "STRUCTURED_CRITERION_MAPPING_UNAVAILABLE"
    ) in codes


@pytest.mark.asyncio
@pytest.mark.parametrize("changed_path", ["src2/evil.py", ".", "src/../evil.py", ".git/config"])
async def test_changed_path_metadata_cannot_widen_reviewed_directory_scope(
    harness: FleetHarness,
    changed_path: str,
) -> None:
    run, task = await _multiple_criteria(harness)
    assert run.patch_artifact_id is not None
    artifact = harness.container.artifacts.create_text(
        kind=ArtifactKind.PATCH,
        project_id=run.project_id,
        run_id=run.run_id,
        task_id=task.task_id,
        content=harness.container.artifacts.read_text(run.patch_artifact_id),
        producer="test-fixture",
        metadata={"changed_paths": [changed_path]},
    )
    with pytest.raises(FleetError) as caught:
        harness.container.workflow.evidence.assemble(
            run.model_copy(update={"patch_artifact_id": artifact.artifact_id}), task
        )
    assert caught.value.code is ErrorCode.ARTIFACT_INTEGRITY_FAILED
