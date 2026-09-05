from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import (
    AcceptanceCriterion,
    ImplementationReport,
    LeaseKind,
    LeaseStatus,
    ResourceLease,
    Run,
    RunStatus,
    SandboxCleanupResult,
    TaskSpec,
    WorkflowStage,
)
from agent_fleet.domain.workflow import validate_transition


def _run() -> Run:
    now = datetime(2026, 9, 3, tzinfo=UTC)
    return Run(
        run_id="run_00000000000000000000000000000001",
        project_id="prj_00000000000000000000000000000001",
        correlation_id="corr_00000000000000000000000000000001",
        goal="goal",
        base_revision="abc",
        target_status_fingerprint="0" * 64,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.parametrize(
    "stage", [WorkflowStage.IMPLEMENTING, WorkflowStage.REPAIRING, WorkflowStage.VERIFYING]
)
def test_valid_transition_path_and_pause_resume(stage: WorkflowStage) -> None:
    run = _run()
    validate_transition(run, RunStatus.RUNNING, WorkflowStage.INTAKE)
    implementing = run.model_copy(update={"status": RunStatus.RUNNING, "stage": stage})
    validate_transition(implementing, RunStatus.PAUSED_FOR_APPROVAL, stage)
    paused = implementing.model_copy(update={"status": RunStatus.PAUSED_FOR_APPROVAL})
    validate_transition(paused, RunStatus.RUNNING, stage)


def test_invalid_transition_has_stable_error() -> None:
    with pytest.raises(FleetError) as captured:
        validate_transition(_run(), RunStatus.READY_FOR_REVIEW, WorkflowStage.PRESENTING)
    assert captured.value.code is ErrorCode.WORKFLOW_INVALID_TRANSITION


def test_naive_timestamps_are_rejected() -> None:
    data = _run().model_dump()
    data["created_at"] = datetime(2026, 9, 3)
    with pytest.raises(ValueError, match="timezone-aware"):
        Run.model_validate(data)


@pytest.mark.parametrize(
    ("field", "wrong_id"),
    [
        ("run_id", "task_" + "1" * 32),
        ("project_id", "art_" + "1" * 32),
        ("correlation_id", "run_" + "1" * 32),
    ],
)
def test_run_rejects_cross_type_id_prefixes(field: str, wrong_id: str) -> None:
    payload = _run().model_dump()
    payload[field] = wrong_id

    with pytest.raises(ValueError, match="string_pattern_mismatch"):
        Run.model_validate(payload)


def test_run_accepts_legacy_json_without_task_spec_binding() -> None:
    legacy = _run().model_dump(
        exclude={
            "task_spec_artifact_id",
            "task_spec_hash",
            "config_snapshot_artifact_id",
            "config_snapshot_hash",
        }
    )

    restored = Run.model_validate(legacy)

    assert restored.task_spec_artifact_id is None
    assert restored.task_spec_hash is None
    assert restored.config_snapshot_artifact_id is None
    assert restored.config_snapshot_hash is None


def _task_with_scope(allowed: list[str], forbidden: list[str]) -> TaskSpec:
    return TaskSpec(
        task_id="task_00000000000000000000000000000001",
        run_id="run_00000000000000000000000000000001",
        original_goal="goal",
        normalized_goal="goal",
        base_revision="abc",
        allowed_paths=allowed,
        forbidden_paths=forbidden,
        acceptance_criteria=[
            AcceptanceCriterion(criterion_id="criterion", description="criterion")
        ],
        required_evidence=["canonical_patch", "command_evidence"],
        max_repair_iterations=1,
        config_snapshot_hash="0" * 64,
        created_at=datetime(2026, 9, 3, tzinfo=UTC),
    )


@pytest.mark.parametrize("path", [".GIT/config", ".FLEET/project/charter.md"])
def test_task_scope_rejects_casefolded_protected_paths(path: str) -> None:
    with pytest.raises(ValueError, match="protected path"):
        _task_with_scope([path], ["vendor"])


def test_task_scope_rejects_casefolded_overlap_and_duplicates() -> None:
    with pytest.raises(ValueError, match="overlap"):
        _task_with_scope(["Src"], ["src/generated"])
    with pytest.raises(ValueError, match="case-insensitively unique"):
        _task_with_scope(["src/Foo.py", "src/foo.py"], ["vendor"])


@pytest.mark.parametrize(
    ("field", "wrong_id"),
    [
        ("task_id", "run_" + "1" * 32),
        ("run_id", "task_" + "1" * 32),
    ],
)
def test_task_spec_rejects_cross_type_id_prefixes(field: str, wrong_id: str) -> None:
    payload = _task_with_scope(["src"], ["vendor"]).model_dump()
    payload[field] = wrong_id

    with pytest.raises(ValueError, match="string_pattern_mismatch"):
        TaskSpec.model_validate(payload)


@pytest.mark.parametrize(
    ("kind", "resource_id"),
    [
        (LeaseKind.WORKTREE, "sandbox_" + "1" * 32),
        (LeaseKind.SANDBOX, "ws_" + "1" * 32),
        (LeaseKind.EXECUTION, "sandbox_" + "1" * 32),
        (LeaseKind.EXECUTION, "ws_" + "1" * 32),
        (LeaseKind.WORKTREE, "garbage"),
    ],
)
def test_resource_lease_rejects_wrong_resource_identity(kind: LeaseKind, resource_id: str) -> None:
    now = datetime(2026, 9, 3, tzinfo=UTC)

    with pytest.raises(ValueError):
        ResourceLease(
            lease_id="lease_" + "1" * 32,
            run_id="run_" + "1" * 32,
            kind=kind,
            resource_id=resource_id,
            status=LeaseStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )


def test_implementation_report_rejects_non_artifact_evidence_id() -> None:
    with pytest.raises(ValueError, match="string_pattern_mismatch"):
        ImplementationReport(
            summary="summary",
            intended_changed_paths=[],
            tests_added_or_changed=[],
            criterion_results=[],
            evidence_artifact_ids=["run_" + "1" * 32],
            unresolved_limitations=[],
            verifier_focus=[],
        )


def test_complete_sandbox_cleanup_must_be_reconciled() -> None:
    with pytest.raises(ValueError, match="complete sandbox cleanup must be reconciled"):
        SandboxCleanupResult(
            provider="fake",
            resource_id="sandbox_" + "1" * 32,
            resources_found=0,
            resources_removed=0,
            reconciled=False,
            complete=True,
            completed_at=datetime(2026, 9, 4, tzinfo=UTC),
        )
