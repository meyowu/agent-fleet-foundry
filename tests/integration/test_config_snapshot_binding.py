from __future__ import annotations

import asyncio
import traceback
from pathlib import Path

import pytest
from conftest import FleetHarness

from agent_fleet.bootstrap import build_container
from agent_fleet.domain.config import ConfigSnapshot
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import ArtifactKind, FakeScenario, Run


def _assemble(harness: FleetHarness, run: Run) -> None:
    assert run.task_id is not None
    task = harness.container.state.get_task(run.task_id)
    harness.container.workflow.evidence.assemble(run, task)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_workflow_binds_exact_configuration_snapshot_into_evidence(
    harness: FleetHarness,
) -> None:
    run = await harness.start(FakeScenario.SUCCESS)

    assert run.config_snapshot_artifact_id is not None
    assert run.config_snapshot_hash is not None
    metadata = harness.container.state.get_artifact(run.config_snapshot_artifact_id)
    assert metadata.kind is ArtifactKind.CONFIG_SNAPSHOT
    assert metadata.sha256 == run.config_snapshot_hash
    snapshot = ConfigSnapshot.model_validate_json(
        harness.container.artifacts.read_text(run.config_snapshot_artifact_id)
    )
    assert {item.path for item in snapshot.files} >= {
        "fleet.yaml",
        "agents/cos.md",
        "agents/engineer.md",
        "agents/verifier.md",
        "project/verification.yaml",
        "workflows/code-change.yaml",
    }
    bundle = harness.container.artifacts.read_text(run.evidence_bundle_artifact_id or "")
    assert f'"config_snapshot_artifact_id": "{run.config_snapshot_artifact_id}"' in bundle
    assert f'"config_snapshot_sha256": "{run.config_snapshot_hash}"' in bundle


@pytest.mark.integration
@pytest.mark.asyncio
async def test_missing_config_snapshot_run_binding_is_rejected(harness: FleetHarness) -> None:
    run = await harness.start(FakeScenario.SUCCESS)
    unbound = run.model_copy(
        update={"config_snapshot_artifact_id": None, "config_snapshot_hash": None}
    )

    with pytest.raises(FleetError) as captured:
        _assemble(harness, unbound)

    assert captured.value.code is ErrorCode.ARTIFACT_INTEGRITY_FAILED


@pytest.mark.integration
@pytest.mark.asyncio
async def test_wrong_kind_config_snapshot_binding_is_rejected(harness: FleetHarness) -> None:
    run = await harness.start(FakeScenario.SUCCESS)
    assert run.fleet_plan_artifact_id is not None
    plan = harness.container.state.get_artifact(run.fleet_plan_artifact_id)
    wrong_kind = run.model_copy(
        update={
            "config_snapshot_artifact_id": plan.artifact_id,
            "config_snapshot_hash": plan.sha256,
        }
    )

    with pytest.raises(FleetError) as captured:
        _assemble(harness, wrong_kind)

    assert captured.value.code is ErrorCode.ARTIFACT_INTEGRITY_FAILED


@pytest.mark.integration
@pytest.mark.asyncio
async def test_foreign_run_config_snapshot_binding_is_rejected(harness: FleetHarness) -> None:
    run = await harness.start(FakeScenario.SUCCESS)
    foreign_run = await harness.start(FakeScenario.SUCCESS)
    assert foreign_run.config_snapshot_artifact_id is not None
    assert foreign_run.config_snapshot_hash is not None
    foreign_bound = run.model_copy(
        update={
            "config_snapshot_artifact_id": foreign_run.config_snapshot_artifact_id,
            "config_snapshot_hash": foreign_run.config_snapshot_hash,
        }
    )

    with pytest.raises(FleetError) as captured:
        _assemble(harness, foreign_bound)

    assert captured.value.code is ErrorCode.ARTIFACT_INTEGRITY_FAILED


@pytest.mark.integration
@pytest.mark.asyncio
async def test_config_snapshot_hash_mismatch_is_rejected(harness: FleetHarness) -> None:
    run = await harness.start(FakeScenario.SUCCESS)
    hash_mismatch = run.model_copy(update={"config_snapshot_hash": "0" * 64})

    with pytest.raises(FleetError) as captured:
        _assemble(harness, hash_mismatch)

    assert captured.value.code is ErrorCode.ARTIFACT_INTEGRITY_FAILED


@pytest.mark.integration
@pytest.mark.asyncio
async def test_corrupt_config_snapshot_content_is_rejected(harness: FleetHarness) -> None:
    run = await harness.start(FakeScenario.SUCCESS)
    assert run.config_snapshot_artifact_id is not None
    metadata = harness.container.state.get_artifact(run.config_snapshot_artifact_id)
    artifact_path = Path(harness.state_root, "artifacts", metadata.content_ref)
    await asyncio.to_thread(
        artifact_path.write_text,
        "corrupt configuration snapshot\n",
        encoding="utf-8",
    )

    with pytest.raises(FleetError) as captured:
        _assemble(harness, run)

    assert captured.value.code is ErrorCode.ARTIFACT_INTEGRITY_FAILED


@pytest.mark.integration
@pytest.mark.asyncio
async def test_malformed_config_secret_fails_before_run_without_exception_leak(
    harness: FleetHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "FLEET-WORKFLOW-YAML-REGISTERED-SECRET"
    monkeypatch.setenv("AGENT_FLEET_REDACT_VALUES", secret)
    container = build_container(harness.state_root)
    fleet_yaml = harness.repository_root / ".fleet" / "fleet.yaml"
    fleet_yaml.write_text(f"apiVersion: [{secret}\n", encoding="utf-8")

    with pytest.raises(FleetError, match="registered secret material") as captured:
        await container.workflow.start(
            project_path=harness.repository_root,
            goal="safe goal",
            runtime_name="fake",
            sandbox_name="fake",
            fake_scenario=FakeScenario.SUCCESS,
        )

    rendered = "".join(traceback.format_exception(captured.value))
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
    assert secret not in str(captured.value)
    assert secret not in rendered
    with container.state._connect() as connection:
        row = connection.execute("SELECT COUNT(*) FROM runs").fetchone()
        assert row is not None
        assert row[0] == 0
    assert all(
        secret.encode() not in path.read_bytes()
        for path in harness.state_root.rglob("*")
        if path.is_file()
    )
