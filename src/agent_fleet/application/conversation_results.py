"""Deterministic bounded conversation summaries of authoritative Run results."""

from __future__ import annotations

from agent_fleet.application.artifacts import ArtifactService
from agent_fleet.application.inspection import InspectionService
from agent_fleet.domain.conversation import ConversationArtifactRef, ConversationSummary
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import ArtifactKind, Run, RunStatus
from agent_fleet.ports.state_store import StateStore


def bounded_summary(text: str, *, limit: int) -> ConversationSummary:
    """Truncate display context only, never the executed user goal."""
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return ConversationSummary(text=text, truncated=False)
    marker = " [summary truncated]"
    prefix = encoded[: limit - len(marker.encode("utf-8"))].decode("utf-8", errors="ignore")
    return ConversationSummary(text=prefix + marker, truncated=True)


def conversation_result(
    state: StateStore,
    artifacts: ArtifactService,
    inspection: InspectionService,
    run: Run,
) -> tuple[ConversationSummary, tuple[ConversationArtifactRef, ...]]:
    data = inspection.status(run.run_id)
    text = (
        f"Run {run.run_id}: {run.status.value}; "
        f"assurance={data['assurance_verdict'] or 'unproven'}; "
        f"verified_complete={str(run.verified_complete).lower()}."
    )
    if run.status is RunStatus.READY_FOR_REVIEW:
        text += " Candidate patch is not applied to the target repository."
    priorities = {
        ArtifactKind.EVIDENCE_BUNDLE: 0,
        ArtifactKind.PATCH: 1,
        ArtifactKind.COS_RESPONSE: 2,
        ArtifactKind.RUN_SUMMARY: 3,
        ArtifactKind.RESOURCE_CLEANUP: 4,
        ArtifactKind.RUNTIME_USAGE: 5,
    }
    selected = sorted(
        (item for item in state.list_artifacts(run.run_id) if item.kind in priorities),
        key=lambda item: (priorities[item.kind], item.created_at, item.artifact_id),
    )[:8]
    refs: list[ConversationArtifactRef] = []
    for item in selected:
        if item.kind is ArtifactKind.RUNTIME_USAGE and item.task_id != run.task_id:
            # A CoS attempt may fail before any TaskSpec exists. Its usage stays
            # in the Run ledger; do not invent a task binding for chat history.
            continue
        if (item.project_id, item.run_id, item.task_id) != (
            run.project_id,
            run.run_id,
            run.task_id,
        ):
            raise FleetError(
                ErrorCode.ARTIFACT_INTEGRITY_FAILED,
                "A conversation result artifact belongs to another task.",
                "Inspect the original evidence; no conversation result was accepted.",
            )
        content = artifacts.read_bounded_text(item.artifact_id)
        refs.append(
            ConversationArtifactRef(
                artifact_id=item.artifact_id,
                sha256=item.sha256,
                run_id=run.run_id,
                kind=item.kind,
            )
        )
        if item.kind is ArtifactKind.COS_RESPONSE:
            text += "\nCoS response (model content, not execution evidence):\n" + content
    if isinstance(data["evidence"], dict):
        evidence = data["evidence"]
        text += (
            f"\nChanged files: {evidence['changed_paths']}. "
            f"Proof gaps: {evidence['proof_gaps']}. Remaining risks: {evidence['remaining_risks']}."
        )
    return bounded_summary(text, limit=4096), tuple(refs)
