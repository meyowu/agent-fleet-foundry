"""Non-authorizing inspection; terminal recording is blocked pending safe writes."""

from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.evaluation_observation import EvaluationObservation
from agent_fleet.domain.outcomes import OutcomeRecord
from agent_fleet.ports.clock import Clock
from agent_fleet.ports.evaluation_evidence import EvaluationEvidence
from agent_fleet.ports.id_generator import IdGenerator


class EvaluationOutcomeService:
    def __init__(self, evidence: EvaluationEvidence, clock: Clock, ids: IdGenerator) -> None:
        self.evidence, self.clock, self.ids = evidence, clock, ids

    def inspect_attempt(self, campaign_id: str, attempt_id: str) -> EvaluationObservation:
        return self.evidence.inspect_attempt(campaign_id, attempt_id)

    def record_final_outcome(
        self, campaign_id: str, attempt_id: str, expected_observation_sha256: str
    ) -> OutcomeRecord:
        # Reject before inspection, clocks or IDs: even the old read path is unqualified.
        raise FleetError(
            ErrorCode.STATE_UNAVAILABLE,
            "Evaluation terminal recording is disabled: its write boundary is unqualified.",
            "Preserve the original attempt and evidence. "
            "No result, refund or replay is authorized.",
            details={
                "feature": "evaluation_terminal_recording",
                "reason": "write_boundary_unqualified",
            },
        )
