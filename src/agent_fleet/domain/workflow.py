"""Explicit workflow transition policy."""

from __future__ import annotations

from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import Run, RunStatus, WorkflowStage

State = tuple[RunStatus, WorkflowStage | None]

_ALLOWED: dict[State, frozenset[State]] = {
    (RunStatus.CREATED, None): frozenset({(RunStatus.RUNNING, WorkflowStage.INTAKE)}),
    (RunStatus.RUNNING, WorkflowStage.INTAKE): frozenset(
        {(RunStatus.RUNNING, WorkflowStage.SCOPING)}
    ),
    (RunStatus.RUNNING, WorkflowStage.SCOPING): frozenset(
        {
            (RunStatus.RUNNING, WorkflowStage.WORKSPACE_PREPARATION),
            (RunStatus.RUNNING, WorkflowStage.PRESENTING),
        }
    ),
    (RunStatus.RUNNING, WorkflowStage.WORKSPACE_PREPARATION): frozenset(
        {(RunStatus.RUNNING, WorkflowStage.IMPLEMENTING)}
    ),
    (RunStatus.RUNNING, WorkflowStage.IMPLEMENTING): frozenset(
        {
            (RunStatus.PAUSED_FOR_APPROVAL, WorkflowStage.IMPLEMENTING),
            (RunStatus.RUNNING, WorkflowStage.VERIFYING),
            (RunStatus.RUNNING, WorkflowStage.PRESENTING),
        }
    ),
    (RunStatus.PAUSED_FOR_APPROVAL, WorkflowStage.IMPLEMENTING): frozenset(
        {(RunStatus.RUNNING, WorkflowStage.IMPLEMENTING)}
    ),
    (RunStatus.RUNNING, WorkflowStage.VERIFYING): frozenset(
        {
            (RunStatus.RUNNING, WorkflowStage.REPAIRING),
            (RunStatus.RUNNING, WorkflowStage.PRESENTING),
            (RunStatus.REJECTED, WorkflowStage.VERIFYING),
        }
    ),
    (RunStatus.RUNNING, WorkflowStage.REPAIRING): frozenset(
        {
            (RunStatus.PAUSED_FOR_APPROVAL, WorkflowStage.REPAIRING),
            (RunStatus.RUNNING, WorkflowStage.VERIFYING),
        }
    ),
    (RunStatus.PAUSED_FOR_APPROVAL, WorkflowStage.REPAIRING): frozenset(
        {(RunStatus.RUNNING, WorkflowStage.REPAIRING)}
    ),
    (RunStatus.RUNNING, WorkflowStage.PRESENTING): frozenset(
        {
            (RunStatus.READY_FOR_REVIEW, WorkflowStage.PRESENTING),
            (RunStatus.COMPLETED, WorkflowStage.PRESENTING),
        }
    ),
    (RunStatus.READY_FOR_REVIEW, WorkflowStage.PRESENTING): frozenset(
        {(RunStatus.APPLYING, WorkflowStage.APPLYING)}
    ),
    (RunStatus.APPLYING, WorkflowStage.APPLYING): frozenset(
        {(RunStatus.RUNNING, WorkflowStage.CLEANUP)}
    ),
    (RunStatus.RUNNING, WorkflowStage.CLEANUP): frozenset(
        {(RunStatus.COMPLETED, WorkflowStage.CLEANUP)}
    ),
}

_TERMINAL = {
    RunStatus.COMPLETED,
    RunStatus.FAILED,
    RunStatus.CANCELLED,
    RunStatus.REJECTED,
    RunStatus.ABANDONED,
}


def validate_transition(
    current: Run, target_status: RunStatus, target_stage: WorkflowStage | None
) -> None:
    """Reject all transitions not explicitly represented by the workflow."""

    current_state = (current.status, current.stage)
    target_state = (target_status, target_stage)
    if current_state == target_state:
        return
    if current.status not in _TERMINAL and target_status in {
        RunStatus.FAILED,
        RunStatus.CANCELLED,
        RunStatus.REJECTED,
        RunStatus.ABANDONED,
    }:
        return
    if target_state not in _ALLOWED.get(current_state, frozenset()):
        raise FleetError(
            ErrorCode.WORKFLOW_INVALID_TRANSITION,
            f"Invalid workflow transition {current.status.value}/{current.stage} -> "
            f"{target_status.value}/{target_stage}.",
            "Inspect the run event history; do not mutate workflow state manually.",
            details={
                "current_status": current.status.value,
                "current_stage": current.stage.value if current.stage else None,
                "target_status": target_status.value,
                "target_stage": target_stage.value if target_stage else None,
            },
        )


def is_terminal(status: RunStatus) -> bool:
    return status in _TERMINAL
