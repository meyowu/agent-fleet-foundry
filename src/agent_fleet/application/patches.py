"""Candidate patch inspection and guarded explicit application."""

from __future__ import annotations

from pathlib import Path

from agent_fleet.application.artifacts import ArtifactService
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import ApplyResult, Run, RunStatus, WorkflowStage
from agent_fleet.ports.clock import Clock
from agent_fleet.ports.config import ConfigurationPort
from agent_fleet.ports.repository import RepositoryPort
from agent_fleet.ports.state_store import StateStore


class PatchService:
    def __init__(
        self,
        state: StateStore,
        artifacts: ArtifactService,
        repository: RepositoryPort,
        config: ConfigurationPort,
        clock: Clock,
    ) -> None:
        self.state = state
        self.artifacts = artifacts
        self.repository = repository
        self.config = config
        self.clock = clock

    def show(self, run_id: str) -> str:
        run = self.state.get_run(run_id)
        if run.patch_artifact_id is None:
            raise FleetError(
                ErrorCode.RESOURCE_NOT_FOUND,
                f"Run {run_id} has no candidate patch artifact.",
                "Inspect run status and logs for a pause, failure, or rejection.",
            )
        return self.artifacts.read_text(run.patch_artifact_id)

    def apply(self, run_id: str) -> tuple[Run, ApplyResult]:
        run = self.state.get_run(run_id)
        if run.status is RunStatus.COMPLETED and run.applied_revision is not None:
            return run, ApplyResult(
                applied=False,
                head_revision=run.applied_revision,
                changed_paths=[],
            )
        if run.status is not RunStatus.READY_FOR_REVIEW or run.patch_artifact_id is None:
            raise FleetError(
                ErrorCode.WORKFLOW_INVALID_TRANSITION,
                f"Run {run_id} is not ready for explicit patch application.",
                "Wait for READY_FOR_REVIEW and inspect the patch first.",
            )
        project = self.state.get_project(run.project_id)
        if run.config_snapshot_hash is None:
            raise FleetError(
                ErrorCode.ARTIFACT_INTEGRITY_FAILED,
                "The run has no exact configuration snapshot binding.",
                "Do not apply the patch; inspect state integrity and rerun the task.",
            )
        patch_metadata = self.state.get_artifact(run.patch_artifact_id)
        if run.patch_sha256 != patch_metadata.sha256:
            raise FleetError(
                ErrorCode.ARTIFACT_INTEGRITY_FAILED,
                "The run patch hash does not match its registered artifact metadata.",
                "Do not apply the patch; inspect state integrity and rerun the task.",
            )
        project_root = Path(project.canonical_root)
        _, active_config = self.config.load_snapshot(project_root / ".fleet" / "fleet.yaml")
        if self.config.snapshot_hash(active_config) != run.config_snapshot_hash:
            raise FleetError(
                ErrorCode.PATCH_TARGET_DIVERGED,
                "The Fleet configuration changed after the candidate was created.",
                "Review the configuration change and start a new Fleet run; nothing was applied.",
            )
        current = self.repository.inspect(project_root)
        if (
            current.identity_hash != project.identity_hash
            or current.head_revision != run.base_revision
            or current.status_fingerprint != run.target_status_fingerprint
        ):
            raise FleetError(
                ErrorCode.PATCH_TARGET_DIVERGED,
                "The target repository changed after the candidate was created.",
                "Preserve current work and start a new Fleet run; nothing was applied.",
                details={"dirty_paths": current.dirty_paths},
            )
        patch = self.artifacts.read_text(run.patch_artifact_id).encode()
        applying = run.model_copy(
            update={
                "status": RunStatus.APPLYING,
                "stage": WorkflowStage.APPLYING,
                "updated_at": self.clock.now(),
            }
        )
        self.state.save_run(
            applying,
            "run.stage_changed",
            {"status": "applying", "stage": "applying"},
        )
        try:
            result = self.repository.apply_patch_to_target(
                project_root,
                patch,
                project.identity_hash,
                run.base_revision,
                run.target_status_fingerprint,
            )
        except FleetError as error:
            failed = applying.model_copy(
                update={"status": RunStatus.FAILED, "updated_at": self.clock.now()}
            )
            self.state.save_run(
                failed,
                "run.failed",
                {"code": error.code.value, "message": error.message},
            )
            raise
        cleanup = applying.model_copy(
            update={
                "status": RunStatus.RUNNING,
                "stage": WorkflowStage.CLEANUP,
                "updated_at": self.clock.now(),
            }
        )
        self.state.save_run(
            cleanup,
            "patch.applied",
            {"changed_paths": result.changed_paths, "base_revision": result.head_revision},
        )
        completed = cleanup.model_copy(
            update={
                "status": RunStatus.COMPLETED,
                "applied_revision": result.head_revision,
                "updated_at": self.clock.now(),
            }
        )
        self.state.save_run(completed, "run.completed", {"patch_applied": True})
        return completed, result
