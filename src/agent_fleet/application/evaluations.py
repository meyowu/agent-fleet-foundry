"""Durable preparation and recomputed reporting without any execution capability."""

from agent_fleet.domain.evaluation import EvaluationManifest
from agent_fleet.domain.evaluation_campaign import (
    CampaignRegistration,
    EvaluationLedgerSnapshot,
    EvaluationReservation,
)
from agent_fleet.domain.evaluation_metrics import EvaluationReport, evaluate_records
from agent_fleet.domain.outcomes import OutcomeRecord
from agent_fleet.ports.evaluation_store import EvaluationStore


class EvaluationLedgerService:
    def __init__(self, store: EvaluationStore) -> None:
        self.store = store

    def register(self, manifest: EvaluationManifest) -> CampaignRegistration:
        return self.store.register(manifest)

    def reserve(
        self, campaign_id: str, case_id: str, repetition: int, idempotency_key: str
    ) -> EvaluationReservation:
        return self.store.reserve(campaign_id, case_id, repetition, idempotency_key)

    def record_preflight_outcome(self, record: OutcomeRecord) -> EvaluationLedgerSnapshot:
        return self.store.record_preflight_outcome(record)

    def snapshot(self, campaign_id: str) -> EvaluationLedgerSnapshot:
        return self.store.snapshot(campaign_id)

    def report(self, campaign_id: str) -> EvaluationReport:
        snapshot = EvaluationLedgerSnapshot.model_validate(self.store.snapshot(campaign_id))
        return evaluate_records(snapshot.registration.manifest, snapshot.outcomes)
