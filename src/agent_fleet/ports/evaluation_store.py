"""Non-executing durable evaluation preregistration boundary."""

from typing import Protocol

from agent_fleet.domain.evaluation import EvaluationManifest
from agent_fleet.domain.evaluation_campaign import (
    CampaignRegistration,
    EvaluationLedgerSnapshot,
    EvaluationReservation,
)
from agent_fleet.domain.outcomes import OutcomeRecord


class EvaluationStore(Protocol):
    def register(self, manifest: EvaluationManifest) -> CampaignRegistration: ...

    def reserve(
        self, campaign_id: str, case_id: str, repetition: int, idempotency_key: str
    ) -> EvaluationReservation: ...

    def record_preflight_outcome(self, record: OutcomeRecord) -> EvaluationLedgerSnapshot: ...

    def snapshot(self, campaign_id: str) -> EvaluationLedgerSnapshot: ...
