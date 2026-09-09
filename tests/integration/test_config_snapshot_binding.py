from __future__ import annotations

import asyncio
import sqlite3
import traceback
from pathlib import Path

import pytest
from conftest import FleetHarness

from agent_fleet.adapters.repository.git import GitRepositoryAdapter
from agent_fleet.adapters.system import UuidIdGenerator
from agent_fleet.bootstrap import build_container
from agent_fleet.domain.config import ConfigSnapshot
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.ids import IdPrefix
from agent_fleet.domain.models import (
    ArtifactKind,
    FakeScenario,
    Run,
    RunStatus,
    WorkflowStage,
)


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


def _provider_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    secret: str,
) -> tuple[Path, Path]:
    state_root = tmp_path / "fleet-state"
    repository = GitRepositoryAdapter(tmp_path, UuidIdGenerator()).create_canary_fixture(
        tmp_path / "repository"
    )
    monkeypatch.setenv("FLEET_SELECTED_PROVIDER_KEY", secret)
    container = build_container(state_root)
    container.projects._initialize_without_canary(
        repository,
        runtime_name="pydantic-ai",
        provider_model="openai:gpt-test",
        credential_ref="env:FLEET_SELECTED_PROVIDER_KEY",
    )
    return state_root, repository


@pytest.mark.integration
@pytest.mark.asyncio
async def test_fresh_start_registers_selected_key_before_malformed_config_parse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "selected+provider+secret+987654"
    state_root, repository = _provider_project(tmp_path, monkeypatch, secret)
    fleet_yaml = repository / ".fleet" / "fleet.yaml"
    fleet_yaml.write_text(
        fleet_yaml.read_text(encoding="utf-8").replace(
            f"name: {repository.name}", f"name: {secret}"
        ),
        encoding="utf-8",
    )
    fresh = build_container(state_root)

    with pytest.raises(FleetError) as captured:
        await fresh.workflow.start(
            project_path=repository,
            goal="safe goal",
            runtime_name=None,
            provider_model=None,
            credential_ref=None,
            sandbox_name="fake",
            fake_scenario=None,
        )

    rendered = "".join(traceback.format_exception(captured.value))
    assert captured.value.code is ErrorCode.CONFIG_INVALID
    assert fresh.redactor.contains_secret(secret)
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
    assert secret not in rendered
    with fresh.state._connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_fresh_resume_registers_selected_key_before_malformed_config_parse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "selected+provider+secret+resume987654"
    state_root, repository = _provider_project(tmp_path, monkeypatch, secret)
    setup = build_container(state_root)
    project = setup.state.get_project_by_root(str(repository.resolve()))
    assert project is not None
    repository_info = setup.repository.inspect(repository)
    now = setup.state.clock.now()
    run = Run(
        run_id=setup.state.ids.new(IdPrefix.RUN),
        project_id=project.project_id,
        correlation_id=setup.state.ids.new(IdPrefix.CORRELATION),
        goal="safe goal",
        base_revision=repository_info.head_revision,
        target_status_fingerprint=repository_info.status_fingerprint,
        runtime_name=project.runtime_name,
        provider_model=project.provider_model,
        credential_ref=project.credential_ref,
        created_at=now,
        updated_at=now,
    )
    setup.state.create_run(run)
    intake = run.model_copy(
        update={
            "status": RunStatus.RUNNING,
            "stage": WorkflowStage.INTAKE,
            "updated_at": setup.state.clock.now(),
        }
    )
    setup.state.save_run(intake, "run.stage_changed", {"stage": "intake"})
    running = intake.model_copy(
        update={"stage": WorkflowStage.SCOPING, "updated_at": setup.state.clock.now()}
    )
    setup.state.save_run(running, "run.stage_changed", {"stage": "scoping"})
    fleet_yaml = repository / ".fleet" / "fleet.yaml"
    fleet_yaml.write_text(
        fleet_yaml.read_text(encoding="utf-8").replace(
            f"name: {repository.name}", f"name: {secret}"
        ),
        encoding="utf-8",
    )
    fresh = build_container(state_root)

    with pytest.raises(FleetError) as captured:
        await fresh.workflow.resume(run.run_id)

    rendered = "".join(traceback.format_exception(captured.value))
    assert captured.value.code is ErrorCode.RECOVERY_REQUIRED
    assert fresh.redactor.contains_secret(secret)
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
    assert secret not in rendered
    assert fresh.state.get_run(run.run_id).status is RunStatus.RUNNING
    assert fresh.organization.store.get_head(project.project_id) is None


def _legacy_credential_state(harness: FleetHarness) -> Path:
    """Build an isolated pre8 database fixture; never remove a live project's fence.

    The ordinary fake workflow supplies valid historical Run/artifact/event rows.
    A separate test-owned copy omits migration8 and later additions, reproducing the
    old credential-rotation case without bypassing headed production writes.
    The malformed-config rejection must happen before any artifact content read.
    """
    state_root = harness.root / "legacy-credential-state"
    state_root.mkdir()
    with (
        harness.container.state._connect() as original,
        sqlite3.connect(state_root / "state.db") as legacy,
    ):
        assert original.execute("SELECT COUNT(*) FROM organization_operations").fetchone()[0] == 0
        assert original.execute("SELECT MAX(revision) FROM organization_heads").fetchone()[0] == 0
        original.backup(legacy)
        legacy.execute("PRAGMA foreign_keys=OFF")
        for table in (
            "evaluation_executions",
            "evaluation_outcomes",
            "evaluation_reservations",
            "evaluation_slots",
            "evaluation_campaigns",
            "plan_review_heads",
            "plan_review_versions",
            "run_model_bindings",
            "project_model_selection_heads",
            "project_model_selection_versions",
            "model_profile_heads",
            "model_profile_versions",
            "model_configuration_audit",
            "organization_run_admissions",
            "organization_operations",
            "organization_proposals",
            "organization_heads",
            "organization_versions",
            "organization_trees",
            "organization_events",
        ):
            legacy.execute(f"DROP TABLE {table}")
        legacy.execute("DELETE FROM schema_migrations WHERE version>=8")
        assert legacy.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 7
    return state_root


@pytest.mark.integration
@pytest.mark.asyncio
async def test_fresh_patch_apply_registers_project_and_historical_run_credentials(
    harness: FleetHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old_secret = "historical-run-provider-secret-123"
    new_secret = "current-project-provider-secret-456"
    monkeypatch.setenv("FLEET_OLD_PROVIDER_KEY", old_secret)
    monkeypatch.setenv("FLEET_NEW_PROVIDER_KEY", new_secret)
    run = await harness.start(FakeScenario.SUCCESS)
    state_root = _legacy_credential_state(harness)
    legacy = build_container(state_root)
    assert legacy.organization.store.get_head(run.project_id) is None
    provider_run = run.model_copy(
        update={
            "runtime_name": "pydantic-ai",
            "provider_model": "openai:gpt-test",
            "credential_ref": "env:FLEET_OLD_PROVIDER_KEY",
        }
    )
    legacy.state.save_run(
        provider_run,
        "run.runtime_binding_rotated_for_test",
        {"status": provider_run.status.value},
    )
    project = legacy.state.get_project(run.project_id)
    legacy.state.save_project(
        project.model_copy(
            update={
                "runtime_name": "pydantic-ai",
                "provider_model": "openai:gpt-test",
                "credential_ref": "env:FLEET_NEW_PROVIDER_KEY",
            }
        )
    )
    target = harness.repository_root / "src" / "canary_calc" / "core.py"
    target_before = target.read_bytes()
    fleet_yaml = harness.repository_root / ".fleet" / "fleet.yaml"
    fleet_yaml.write_text(f"apiVersion: [{old_secret}\n", encoding="utf-8")
    fresh = build_container(state_root)

    with pytest.raises(FleetError) as captured:
        fresh.patches.apply(run.run_id)

    rendered = "".join(traceback.format_exception(captured.value))
    assert captured.value.code is ErrorCode.RECOVERY_REQUIRED
    assert fresh.redactor.contains_secret(old_secret)
    assert fresh.redactor.contains_secret(new_secret)
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
    for secret in (old_secret, new_secret):
        assert secret not in str(captured.value)
        assert secret not in repr(captured.value)
        assert secret not in rendered
    assert fresh.state.get_run(run.run_id).status is RunStatus.READY_FOR_REVIEW
    assert target.read_bytes() == target_before
    assert fresh.organization.store.get_head(run.project_id) is None
    assert harness.container.state.get_project(run.project_id) == project
