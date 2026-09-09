"""Explicit execution ownership, separate from the observational evaluation store."""

from pathlib import Path
from typing import Protocol

from agent_fleet.domain.evaluation import EvaluationManifest
from agent_fleet.domain.evaluation_execution import (
    EvaluationAdmission,
    EvaluationClaim,
    EvaluationExecutionRecord,
    EvaluationRegistration,
    EvaluationSubmission,
)
from agent_fleet.domain.evolution import OrganizationAdmission
from agent_fleet.domain.model_profiles import RunModelBindings
from agent_fleet.domain.models import Run


class EvaluationExecutionStore(Protocol):
    def submission(
        self,
        campaign_id: str,
        expected_manifest_sha256: str,
        case_id: str,
        repetition: int,
        idempotency_key: str,
    ) -> EvaluationSubmission: ...
    def manifest(self, submission: EvaluationSubmission) -> EvaluationManifest: ...
    def for_attempt(self, submission: EvaluationSubmission) -> EvaluationExecutionRecord | None: ...
    def for_run(self, run_id: str) -> EvaluationExecutionRecord | None: ...
    def register(
        self,
        submission: EvaluationSubmission,
        run: Run,
        admission: EvaluationAdmission,
        bindings: RunModelBindings,
        *,
        organization_admission: OrganizationAdmission,
    ) -> EvaluationRegistration: ...
    def assert_claim(self, claim: EvaluationClaim) -> EvaluationExecutionRecord: ...
    def settle(self, claim: EvaluationClaim) -> EvaluationExecutionRecord: ...
    def fence(self, root_run_id: str) -> EvaluationExecutionRecord: ...


class ReservedWorkflow(Protocol):
    async def execute_evaluation(
        self, submission: EvaluationSubmission, project_path: Path
    ) -> Run: ...
