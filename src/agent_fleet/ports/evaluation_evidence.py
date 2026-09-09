"""Read-only observation and compare-and-set terminal recording."""

from typing import Protocol

from agent_fleet.domain.evaluation_observation import EvaluationObservation
from agent_fleet.domain.outcomes import OutcomeRecord


class EvaluationEvidence(Protocol):
    def inspect_attempt(self, campaign_id: str, attempt_id: str) -> EvaluationObservation: ...

    def record_terminal(
        self, observation: EvaluationObservation, record: OutcomeRecord
    ) -> OutcomeRecord: ...
