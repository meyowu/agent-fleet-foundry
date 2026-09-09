"""The explicit reserved-execution entrypoint; reports never call this service."""

from pathlib import Path

from agent_fleet.domain.models import Run
from agent_fleet.ports.evaluation_execution import EvaluationExecutionStore, ReservedWorkflow


class EvaluationExecutionService:
    def __init__(self, store: EvaluationExecutionStore, workflow: ReservedWorkflow) -> None:
        self.store = store
        self.workflow = workflow

    async def execute_reserved(
        self,
        campaign_id: str,
        expected_manifest_sha256: str,
        case_id: str,
        repetition: int,
        idempotency_key: str,
        project_path: Path,
    ) -> Run:
        submission = self.store.submission(
            campaign_id, expected_manifest_sha256, case_id, repetition, idempotency_key
        )
        return await self.workflow.execute_evaluation(submission, project_path)
