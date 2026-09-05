from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from conftest import FleetHarness

from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.ids import IdPrefix
from agent_fleet.domain.models import ArtifactKind, FakeScenario, Run


def _assemble(harness: FleetHarness, run: Run) -> None:
    assert run.task_id is not None
    task = harness.container.state.get_task(run.task_id)
    harness.container.workflow.evidence.assemble(run, task)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_workflow_binds_task_spec_content_address_into_evidence(
    harness: FleetHarness,
) -> None:
    run = await harness.start(FakeScenario.SUCCESS)

    assert run.task_spec_artifact_id is not None
    assert run.task_spec_hash is not None
    metadata = harness.container.state.get_artifact(run.task_spec_artifact_id)
    assert metadata.kind is ArtifactKind.TASK_SPEC
    assert metadata.sha256 == run.task_spec_hash
    bundle = harness.container.artifacts.read_text(run.evidence_bundle_artifact_id or "")
    assert f'"task_spec_artifact_id": "{run.task_spec_artifact_id}"' in bundle
    assert f'"task_spec_sha256": "{run.task_spec_hash}"' in bundle


@pytest.mark.integration
@pytest.mark.asyncio
async def test_missing_task_spec_run_binding_is_rejected(harness: FleetHarness) -> None:
    run = await harness.start(FakeScenario.SUCCESS)
    unbound = run.model_copy(update={"task_spec_artifact_id": None, "task_spec_hash": None})

    with pytest.raises(FleetError) as captured:
        _assemble(harness, unbound)

    assert captured.value.code is ErrorCode.ARTIFACT_INTEGRITY_FAILED


@pytest.mark.integration
@pytest.mark.asyncio
async def test_wrong_kind_task_spec_binding_is_rejected(harness: FleetHarness) -> None:
    run = await harness.start(FakeScenario.SUCCESS)
    assert run.fleet_plan_artifact_id is not None
    plan = harness.container.state.get_artifact(run.fleet_plan_artifact_id)
    wrong_kind = run.model_copy(
        update={
            "task_spec_artifact_id": plan.artifact_id,
            "task_spec_hash": plan.sha256,
        }
    )

    with pytest.raises(FleetError) as captured:
        _assemble(harness, wrong_kind)

    assert captured.value.code is ErrorCode.ARTIFACT_INTEGRITY_FAILED


@pytest.mark.integration
@pytest.mark.asyncio
async def test_foreign_task_spec_artifact_is_rejected(harness: FleetHarness) -> None:
    run = await harness.start(FakeScenario.SUCCESS)
    assert run.task_id is not None
    task = harness.container.state.get_task(run.task_id)
    now = harness.container.state.clock.now()
    foreign_run = Run(
        run_id=harness.container.state.ids.new(IdPrefix.RUN),
        project_id=run.project_id,
        correlation_id=harness.container.state.ids.new(IdPrefix.CORRELATION),
        goal="foreign task binding fixture",
        base_revision=run.base_revision,
        target_status_fingerprint=run.target_status_fingerprint,
        config_snapshot_hash=run.config_snapshot_hash,
        created_at=now,
        updated_at=now,
    )
    project = harness.container.state.get_project(run.project_id)
    with harness.container.organization.admission(project) as admission:
        harness.container.state.create_run(foreign_run, organization_admission=admission)
    assert harness.container.organization.store.admission_for_run(foreign_run.run_id) == admission
    foreign_task_id = harness.container.state.ids.new(IdPrefix.TASK)
    foreign_artifact = harness.container.artifacts.create_text(
        kind=ArtifactKind.TASK_SPEC,
        project_id=run.project_id,
        run_id=foreign_run.run_id,
        task_id=foreign_task_id,
        producer="test-fixture",
        content=task.model_copy(
            update={"run_id": foreign_run.run_id, "task_id": foreign_task_id}
        ).model_dump_json(indent=2),
        mime_type="application/json",
    )
    foreign_bound = run.model_copy(
        update={
            "task_spec_artifact_id": foreign_artifact.artifact_id,
            "task_spec_hash": foreign_artifact.sha256,
        }
    )

    with pytest.raises(FleetError) as captured:
        _assemble(harness, foreign_bound)

    assert captured.value.code is ErrorCode.ARTIFACT_INTEGRITY_FAILED


@pytest.mark.integration
@pytest.mark.asyncio
async def test_task_spec_run_hash_mismatch_is_rejected(harness: FleetHarness) -> None:
    run = await harness.start(FakeScenario.SUCCESS)
    hash_mismatch = run.model_copy(update={"task_spec_hash": "0" * 64})

    with pytest.raises(FleetError) as captured:
        _assemble(harness, hash_mismatch)

    assert captured.value.code is ErrorCode.ARTIFACT_INTEGRITY_FAILED


@pytest.mark.integration
@pytest.mark.asyncio
async def test_corrupt_task_spec_content_is_rejected(harness: FleetHarness) -> None:
    run = await harness.start(FakeScenario.SUCCESS)
    assert run.task_spec_artifact_id is not None
    metadata = harness.container.state.get_artifact(run.task_spec_artifact_id)
    artifact_path = Path(harness.state_root, "artifacts", metadata.content_ref)
    await asyncio.to_thread(
        artifact_path.write_text,
        "corrupt TaskSpec\n",
        encoding="utf-8",
    )

    with pytest.raises(FleetError) as captured:
        _assemble(harness, run)

    assert captured.value.code is ErrorCode.ARTIFACT_INTEGRITY_FAILED
