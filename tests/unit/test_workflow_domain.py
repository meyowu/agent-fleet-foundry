from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import Run, RunStatus, WorkflowStage
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


def test_valid_transition_path_and_pause_resume() -> None:
    run = _run()
    validate_transition(run, RunStatus.RUNNING, WorkflowStage.INTAKE)
    implementing = run.model_copy(
        update={"status": RunStatus.RUNNING, "stage": WorkflowStage.IMPLEMENTING}
    )
    validate_transition(implementing, RunStatus.PAUSED_FOR_APPROVAL, WorkflowStage.IMPLEMENTING)
    paused = implementing.model_copy(update={"status": RunStatus.PAUSED_FOR_APPROVAL})
    validate_transition(paused, RunStatus.RUNNING, WorkflowStage.IMPLEMENTING)


def test_invalid_transition_has_stable_error() -> None:
    with pytest.raises(FleetError) as captured:
        validate_transition(_run(), RunStatus.READY_FOR_REVIEW, WorkflowStage.PRESENTING)
    assert captured.value.code is ErrorCode.WORKFLOW_INVALID_TRANSITION


def test_naive_timestamps_are_rejected() -> None:
    data = _run().model_dump()
    data["created_at"] = datetime(2026, 9, 3)
    with pytest.raises(ValueError, match="timezone-aware"):
        Run.model_validate(data)
