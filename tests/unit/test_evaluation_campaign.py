from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any, cast

import pytest
from evaluation_ledger_fixtures import ledger_harness, ledger_manifest, preflight_record
from pydantic import ValidationError

from agent_fleet.domain.evaluation_campaign import (
    CampaignRegistration,
    EvaluationCommitments,
    EvaluationLedgerSnapshot,
    EvaluationReservation,
    committed_envelopes,
)
from agent_fleet.domain.outcomes import OutcomeArtifactRef, OutcomeUsage


@pytest.fixture(params=["registration", "reservation", "snapshot"])
def authorization_model(
    request: pytest.FixtureRequest,
) -> CampaignRegistration | EvaluationReservation | EvaluationLedgerSnapshot:
    manifest = ledger_manifest()
    registration = CampaignRegistration(manifest=manifest, registered_at=manifest.frozen_at)
    slot = manifest.slots[0]
    case = next(case for case in manifest.cases if case.case_id == slot.case_id)
    reservation = EvaluationReservation(
        campaign_id=manifest.campaign_id,
        manifest_sha256=manifest.sha256,
        case_id=slot.case_id,
        repetition=slot.repetition,
        attempt_id="attempt_" + "1" * 32,
        idempotency_sha256="2" * 64,
        reserved_at=manifest.frozen_at,
        commitment=case.run_budget,
    )
    if request.param == "registration":
        return registration
    if request.param == "reservation":
        return reservation
    return EvaluationLedgerSnapshot(
        registration=registration,
        reservations=(reservation,),
        committed=committed_envelopes((reservation,)),
    )


@pytest.mark.parametrize("value", [0, 0.0, 1, "false", None, True])
@pytest.mark.parametrize("entry", ["constructor", "model_validate", "model_copy", "json"])
def test_all_authorization_entries_reject_non_false_boolean_values(
    authorization_model: CampaignRegistration | EvaluationReservation | EvaluationLedgerSnapshot,
    value: object,
    entry: str,
) -> None:
    instance = authorization_model
    model = type(instance)
    values = instance.model_dump()
    values["execution_authorized"] = value
    with pytest.raises(ValidationError):
        if entry == "constructor":
            model(**values)
        elif entry == "model_validate":
            model.model_validate(values)
        elif entry == "model_copy":
            model.model_validate(instance.model_copy(update={"execution_authorized": value}))
        else:
            encoded = instance.model_dump(mode="json")
            encoded["execution_authorized"] = value
            model.model_validate_json(json.dumps(encoded))


def test_exact_false_and_default_remain_valid_at_every_entry(
    authorization_model: CampaignRegistration | EvaluationReservation | EvaluationLedgerSnapshot,
) -> None:
    instance = authorization_model
    model = type(instance)
    values = instance.model_dump()
    assert model(**values) == instance
    assert model.model_validate(values) == instance
    assert (
        model.model_validate(instance.model_copy(update={"execution_authorized": False}))
        == instance
    )
    assert model.model_validate_json(instance.model_dump_json()) == instance
    del values["execution_authorized"]
    assert model(**values) == instance


def test_empty_ledger_is_immutable_and_never_authorizes_execution() -> None:
    manifest = ledger_manifest()
    registration = CampaignRegistration(manifest=manifest, registered_at=manifest.frozen_at)
    snapshot = EvaluationLedgerSnapshot(
        registration=registration,
        committed=EvaluationCommitments(
            attempts=0,
            agent_invocations=0,
            model_requests=0,
            tool_calls=0,
            total_tokens=0,
            active_seconds=0,
        ),
    )
    assert not snapshot.execution_authorized and not registration.execution_authorized
    assert EvaluationLedgerSnapshot.model_validate_json(snapshot.model_dump_json()) == snapshot
    with pytest.raises(ValidationError):
        cast(Any, snapshot.committed).attempts = 1
    with pytest.raises(ValidationError):
        EvaluationLedgerSnapshot.model_validate(snapshot.model_copy(update={"reservations": []}))
    with pytest.raises(ValidationError):
        CampaignRegistration.model_validate(
            registration.model_copy(update={"execution_authorized": True})
        )
    with pytest.raises(ValidationError):
        CampaignRegistration(
            manifest=manifest, registered_at=manifest.frozen_at - timedelta(microseconds=1)
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate_slot",
        "duplicate_key",
        "commitment",
        "counter",
        "chronology",
        "outcome_time",
        "unreserved",
        "unknown",
        "model",
        "tool",
        "tokens",
        "cost",
        "artifact",
        "run",
        "product",
        "apply",
        "acceptance",
    ],
)
def test_snapshot_rejects_contradictory_or_executed_preflight(
    tmp_path: Path, mutation: str
) -> None:
    h = ledger_harness(tmp_path)
    manifest = ledger_manifest()
    h.service.register(manifest)
    slot = manifest.slots[0]
    reservation = h.service.reserve(manifest.campaign_id, slot.case_id, slot.repetition, "key")
    record = preflight_record(manifest, reservation)
    snapshot = h.service.record_preflight_outcome(record)
    values = snapshot.model_dump()
    if mutation == "duplicate_slot":
        values["reservations"] = (reservation, reservation)
    elif mutation == "duplicate_key":
        second = manifest.slots[1]
        other = h.service.reserve(manifest.campaign_id, second.case_id, second.repetition, "other")
        values["reservations"] = (
            reservation,
            other.model_copy(update={"idempotency_sha256": reservation.idempotency_sha256}),
        )
    elif mutation == "commitment":
        values["reservations"] = (
            reservation.model_copy(
                update={
                    "commitment": reservation.commitment.model_copy(
                        update={"max_model_requests": 1}
                    )
                }
            ),
        )
    elif mutation == "counter":
        values["committed"]["attempts"] = 0
    elif mutation == "chronology":
        values["reservations"] = (
            reservation.model_copy(
                update={"reserved_at": reservation.reserved_at - timedelta(seconds=1)}
            ),
        )
    else:
        changes: dict[str, object] = {}
        if mutation == "outcome_time":
            changes["recorded_at"] = record.recorded_at - timedelta(seconds=1)
        elif mutation == "unreserved":
            changes["attempt_id"] = "attempt_" + "f" * 32
        elif mutation == "unknown":
            changes["external_result"] = "dispatch_unknown"
        elif mutation in {"model", "tool", "tokens"}:
            field = {"model": "model_requests", "tool": "tool_calls", "tokens": "input_tokens"}[
                mutation
            ]
            changes["usage"] = (OutcomeUsage(segment_id="preflight", **{field: 1}),)
        elif mutation == "cost":
            changes.update(reported_cost_microunits=1, currency="USD")
        elif mutation == "artifact":
            changes["artifacts"] = (
                OutcomeArtifactRef(
                    artifact_id="art_" + "1" * 32, category="oracle", run_id=None, sha256="a" * 64
                ),
            )
        elif mutation == "run":
            changes["root_run_id"] = "run_" + "1" * 32
        elif mutation == "product":
            changes["product_verified_complete"] = False
        elif mutation == "apply":
            changes["apply_status"] = "failed"
        elif mutation == "acceptance":
            changes["user_acceptance"] = "accepted"
        values["outcomes"] = (record.model_copy(update=changes),)
    with pytest.raises(ValidationError):
        EvaluationLedgerSnapshot.model_validate(values)
