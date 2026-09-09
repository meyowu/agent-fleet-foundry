"""Durable preregistration receipts, never model or tool execution authorization."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator, model_validator

from agent_fleet.domain.evaluation import (
    CampaignId,
    CaseId,
    EvaluationManifest,
    EvaluationModel,
    EvaluationRunBudget,
    require_utc,
)
from agent_fleet.domain.evaluation_metrics import evaluate_records
from agent_fleet.domain.models import RunStatus, Sha256
from agent_fleet.domain.outcomes import AttemptId, OutcomeRecord

IdempotencyKey = Annotated[
    str, StringConstraints(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
]
_PREFLIGHT_RESULTS = frozenset(
    {
        "environment_failure",
        "provider_failure",
        "budget_exhausted",
        "timeout",
        "cancelled",
        "inconclusive",
        "not_run",
    }
)


def _exact_authorization_boolean(value: object) -> bool:
    if type(value) is not bool:
        raise ValueError("evaluation authorization must be a boolean")
    return value


def validate_preflight(record: OutcomeRecord) -> None:
    """This ledger cannot attach executed Runs or certify an external success."""
    if (
        record.external_result not in _PREFLIGHT_RESULTS
        or record.root_run_id is not None
        or record.task_id is not None
        or record.product_status is not None
        or record.product_verdict is not None
        or record.product_verified_complete is not None
        or record.apply_status in {"applied", "failed"}
        or record.user_acceptance != "not_observed"
        or any(ref.category != "diagnostic" for ref in record.artifacts)
        or (record.reported_cost_microunits or 0) > 0
        or any(
            any(
                (getattr(segment, field) or 0) > 0
                for field in (
                    "model_requests",
                    "tool_calls",
                    "input_tokens",
                    "output_tokens",
                    "unknown_requests",
                )
            )
            for segment in record.usage
        )
    ):
        raise ValueError("evaluation preflight cannot contain execution observations")


def validate_terminal_outcome(record: OutcomeRecord) -> None:
    """Structural terminal linkage only; physical provenance is checked by the observer."""
    if (
        record.root_run_id is None
        or record.external_result not in _PREFLIGHT_RESULTS | {"dispatch_unknown"}
        or record.external_result == "not_run"
        or record.product_status not in {RunStatus.FAILED, RunStatus.CANCELLED}
        or record.user_acceptance != "not_observed"
        or record.apply_status not in {"unknown", "not_applied", "not_applicable"}
    ):
        raise ValueError("terminal observations cannot certify unmeasured external success")


class CampaignRegistration(EvaluationModel):
    manifest: EvaluationManifest
    registered_at: datetime
    execution_authorized: Literal[False] = False

    _utc = field_validator("registered_at")(require_utc)
    _authorization = field_validator("execution_authorized", mode="before")(
        _exact_authorization_boolean
    )

    @model_validator(mode="after")
    def chronology(self) -> CampaignRegistration:
        if self.registered_at < self.manifest.frozen_at:
            raise ValueError("campaign registration cannot predate its frozen manifest")
        return self


class EvaluationReservation(EvaluationModel):
    campaign_id: CampaignId
    manifest_sha256: Sha256
    case_id: CaseId
    repetition: int = Field(strict=True, ge=0, le=2)
    attempt_id: AttemptId
    idempotency_sha256: Sha256
    reserved_at: datetime
    commitment: EvaluationRunBudget
    execution_authorized: Literal[False] = False

    _utc = field_validator("reserved_at")(require_utc)
    _authorization = field_validator("execution_authorized", mode="before")(
        _exact_authorization_boolean
    )


class EvaluationCommitments(EvaluationModel):
    """Permanent reserved envelopes, not actual usage or monetary spend."""

    attempts: int = Field(strict=True, ge=0, le=256)
    agent_invocations: int = Field(strict=True, ge=0, le=10_000)
    model_requests: int = Field(strict=True, ge=0, le=100_000)
    tool_calls: int = Field(strict=True, ge=0, le=100_000)
    total_tokens: int = Field(strict=True, ge=0, le=100_000_000)
    active_seconds: int = Field(strict=True, ge=0, le=86_400)


def committed_envelopes(
    reservations: tuple[EvaluationReservation, ...],
) -> EvaluationCommitments:
    return EvaluationCommitments(
        attempts=len(reservations),
        **{
            field: sum(getattr(item.commitment, "max_" + field) for item in reservations)
            for field in EvaluationCommitments.model_fields
            if field != "attempts"
        },
    )


class EvaluationLedgerSnapshot(EvaluationModel):
    registration: CampaignRegistration
    reservations: tuple[EvaluationReservation, ...] = Field(default=(), max_length=256)
    outcomes: tuple[OutcomeRecord, ...] = Field(default=(), max_length=256)
    committed: EvaluationCommitments
    execution_authorized: Literal[False] = False

    _authorization = field_validator("execution_authorized", mode="before")(
        _exact_authorization_boolean
    )

    @model_validator(mode="after")
    def coherent(self) -> EvaluationLedgerSnapshot:
        manifest = self.registration.manifest
        cases = {case.case_id: case for case in manifest.cases}
        slots = {(slot.case_id, slot.repetition) for slot in manifest.slots}
        identities: list[set[tuple[str, int] | str]] = [set() for _ in range(3)]
        attempts = {}
        for item in self.reservations:
            slot = (item.case_id, item.repetition)
            if (
                item.campaign_id != manifest.campaign_id
                or item.manifest_sha256 != manifest.sha256
                or slot not in slots
                or item.commitment != cases[item.case_id].run_budget
                or item.reserved_at < self.registration.registered_at
            ):
                raise ValueError("evaluation reservation differs from its preregistration")
            item_identities: tuple[tuple[str, int] | str, ...] = (
                slot,
                item.attempt_id,
                item.idempotency_sha256,
            )
            for seen, identity in zip(identities, item_identities, strict=True):
                if identity in seen:
                    raise ValueError("evaluation reservation identities must be unique")
                seen.add(identity)
            attempts[item.attempt_id] = item
        if self.committed != committed_envelopes(self.reservations):
            raise ValueError("evaluation committed counters differ from permanent reservations")
        for field, value in self.committed.model_dump().items():
            if value > getattr(manifest.budget, "max_" + field):
                raise ValueError("evaluation commitment exceeds its frozen campaign budget")
        for record in self.outcomes:
            if record.root_run_id is None:
                validate_preflight(record)
            else:
                validate_terminal_outcome(record)
            reservation = attempts.get(record.attempt_id)
            if (
                reservation is None
                or (record.case_id, record.repetition)
                != (reservation.case_id, reservation.repetition)
                or record.recorded_at < reservation.reserved_at
            ):
                raise ValueError("evaluation outcome lacks its exact earlier reservation")
        evaluate_records(manifest, self.outcomes)
        return self
