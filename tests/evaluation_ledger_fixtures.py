"""Synthetic manifests and real SQLite state, with no runtime or dispatch fixture."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from agent_fleet.adapters.persistence.evaluations import SqliteEvaluationStore
from agent_fleet.adapters.persistence.sqlite import SUPPORTED_SCHEMA_VERSION, SqliteStateStore
from agent_fleet.adapters.system import UuidIdGenerator
from agent_fleet.application.evaluations import EvaluationLedgerService
from agent_fleet.domain.evaluation import EvaluationManifest
from agent_fleet.domain.evaluation_campaign import EvaluationReservation
from agent_fleet.domain.outcomes import OutcomeKind, OutcomeRecord
from agent_fleet.domain.security import Redactor


@dataclass
class EvaluationClock:
    value: datetime = datetime(2026, 1, 2, tzinfo=UTC)

    def now(self) -> datetime:
        return self.value


def ledger_manifest() -> EvaluationManifest:
    path = Path(__file__).parent / "fixtures/evaluations/domain-cohort-v1.json"
    return EvaluationManifest.model_validate_json(path.read_text())


@dataclass
class LedgerHarness:
    state: SqliteStateStore
    store: SqliteEvaluationStore
    service: EvaluationLedgerService
    clock: EvaluationClock


def ledger_harness(root: Path, *, migrate: bool = True) -> LedgerHarness:
    clock = EvaluationClock()
    state = SqliteStateStore(root / "state.db", clock, UuidIdGenerator(), Redactor())
    if migrate:
        assert state.migrate() == SUPPORTED_SCHEMA_VERSION
    store = SqliteEvaluationStore(state)
    return LedgerHarness(state, store, EvaluationLedgerService(store), clock)


def preflight_record(
    manifest: EvaluationManifest,
    reservation: EvaluationReservation,
    result: OutcomeKind = "environment_failure",
    *,
    suffix: int = 1,
) -> OutcomeRecord:
    case = next(case for case in manifest.cases if case.case_id == reservation.case_id)
    return OutcomeRecord(
        outcome_id=f"outcome_{suffix:032x}",
        campaign_id=manifest.campaign_id,
        manifest_sha256=manifest.sha256,
        case_id=case.case_id,
        repetition=reservation.repetition,
        attempt_id=reservation.attempt_id,
        recorded_at=reservation.reserved_at,
        configuration_sha256=case.configuration_sha256,
        oracle_sha256=case.oracle_sha256,
        scoring_sha256=case.scoring_sha256,
        external_result=result,
        apply_status="not_applied" if case.task_kind == "code_change" else "not_applicable",
    )
