"""Read-only run inspection use cases."""

from __future__ import annotations

from agent_fleet.application.artifacts import ArtifactService
from agent_fleet.ports.state_store import StateStore


class InspectionService:
    def __init__(self, state: StateStore, artifacts: ArtifactService) -> None:
        self.state = state
        self.artifacts = artifacts

    def status(self, run_id: str) -> dict[str, object]:
        run = self.state.get_run(run_id)
        return {
            "run_id": run.run_id,
            "project_id": run.project_id,
            "status": run.status.value,
            "stage": run.stage.value if run.stage else None,
            "repair_iterations": run.repair_iterations,
            "pending_approval_id": run.pending_approval_id,
            "patch_artifact_id": run.patch_artifact_id,
            "patch_sha256": run.patch_sha256,
            "verifier_workspace_mutated": run.verifier_workspace_mutated,
            "runtime": run.runtime_name,
            "sandbox": run.sandbox_name,
            "security_level": "fake",
        }

    def logs(self, run_id: str) -> list[dict[str, object]]:
        return [event.model_dump(mode="json") for event in self.state.list_events(run_id)]

    def artifacts_for_run(self, run_id: str) -> list[dict[str, object]]:
        self.state.get_run(run_id)
        return [artifact.model_dump(mode="json") for artifact in self.state.list_artifacts(run_id)]
