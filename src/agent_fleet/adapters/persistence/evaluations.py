"""Atomic, non-executing evaluation ledger in an already migrated Fleet database."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import wraps
from typing import TypeVar

from pydantic import TypeAdapter, ValidationError

from agent_fleet.adapters.persistence.sqlite import SUPPORTED_SCHEMA_VERSION, SqliteStateStore
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.evaluation import (
    CampaignId,
    EvaluationManifest,
    EvaluationModel,
    EvaluationSlot,
    require_utc,
)
from agent_fleet.domain.evaluation_campaign import (
    CampaignRegistration,
    EvaluationLedgerSnapshot,
    EvaluationReservation,
    IdempotencyKey,
    committed_envelopes,
    validate_preflight,
    validate_terminal_outcome,
)
from agent_fleet.domain.evaluation_observation import EvaluationObservation
from agent_fleet.domain.ids import IdPrefix
from agent_fleet.domain.models import CorrelationId
from agent_fleet.domain.outcomes import OutcomeRecord
from agent_fleet.domain.security import sha256_bytes

_Model = TypeVar("_Model", bound=EvaluationModel)
_MAX_BYTES = 2_097_152
_COLUMNS = {
    "evaluation_campaigns": (
        "campaign_id",
        "manifest_id",
        "revision",
        "manifest_sha256",
        "registered_at",
        "record_sha256",
        "data_json",
    ),
    "evaluation_reservations": (
        "attempt_id",
        "campaign_id",
        "case_id",
        "repetition",
        "idempotency_sha256",
        "record_sha256",
        "data_json",
    ),
    "evaluation_outcomes": (
        "outcome_id",
        "attempt_id",
        "campaign_id",
        "record_sha256",
        "data_json",
    ),
    "evaluation_slots": ("campaign_id", "case_id", "repetition"),
}


def _columns(table: str) -> str:
    # Bound bytes in SQLite before moving hostile TEXT/BLOB values into Python.
    # An oversized field becomes invalid NULL, never silently truncated valid data.
    return ",".join(
        name
        if name in {"revision", "repetition"}
        else (f"CASE WHEN length(CAST({name} AS BLOB)) <= {_MAX_BYTES} THEN {name} END AS {name}")
        for name in _COLUMNS[table]
    )


def _invalid() -> FleetError:
    return FleetError(
        ErrorCode.RECOVERY_REQUIRED,
        "The evaluation ledger identity, content or chronology is inconsistent.",
        "Inspect the selected local ledger; do not replace or replay its reservations.",
    )


def _conflict() -> FleetError:
    return FleetError(
        ErrorCode.CONFIG_INVALID,
        "The evaluation preregistration or reservation conflicts with retained state.",
        "Reuse the exact registered identity and content; commitments are permanent.",
    )


def _boundary[**Params, Result](operation: Callable[Params, Result]) -> Callable[Params, Result]:
    @wraps(operation)
    def call(*args: Params.args, **kwargs: Params.kwargs) -> Result:
        error: FleetError
        try:
            return operation(*args, **kwargs)
        except FleetError as caught:
            error = caught
        except (ValidationError, ValueError, TypeError, KeyError, UnicodeError, OverflowError):
            error = _invalid()
        except (sqlite3.Error, OSError):
            error = FleetError(
                ErrorCode.STATE_UNAVAILABLE,
                "The migrated evaluation ledger is unavailable.",
                "Restore the selected local database before preparing an evaluation.",
            )
        error.__context__ = None
        raise error from None

    return call


class SqliteEvaluationStore:
    """No state creation, Run attachment, dispatch, refund or outcome replacement."""

    def __init__(self, state: SqliteStateStore) -> None:
        self.state = state

    @contextmanager
    def _transaction(self, *, write: bool) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(
            f"{self.state.database_path.absolute().as_uri()}?mode=rw", uri=True
        )
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 5000")
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            versions = [
                row[0]
                for row in connection.execute(
                    "SELECT version FROM schema_migrations ORDER BY version LIMIT ?",
                    (SUPPORTED_SCHEMA_VERSION + 2,),
                )
            ]
            if versions != list(range(1, SUPPORTED_SCHEMA_VERSION + 1)):
                raise FleetError(
                    ErrorCode.STATE_SCHEMA_INCOMPATIBLE,
                    "The evaluation ledger requires the exact supported migrated schema.",
                    "Explicitly migrate a compatible database before using this service.",
                )
            for table in _COLUMNS:
                if (
                    connection.execute(
                        "SELECT 1 FROM pragma_foreign_key_check(?) LIMIT 1", (table,)
                    ).fetchone()
                    is not None
                ):
                    raise _invalid()
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _clean(self, value: object) -> None:
        if self.state.redactor.contains_secret_data(value):
            raise _invalid()

    def _encode(self, value: EvaluationModel) -> str:
        content = value.model_dump(mode="json")
        self._clean(content)
        raw = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        if len(raw.encode("utf-8")) > _MAX_BYTES:
            raise _invalid()
        self._clean(raw)
        return raw

    def _validate(self, model: type[_Model], value: _Model) -> _Model:
        # Validate the original strict instance before serialization can coerce a copied value.
        validated = model.model_validate(value)
        self._encode(validated)
        return validated

    def _decode(self, model: type[_Model], row: sqlite3.Row) -> _Model:
        raw = row["data_json"]
        if not isinstance(raw, str) or len(raw.encode("utf-8")) > _MAX_BYTES:
            raise _invalid()
        self._clean(raw)
        if sha256_bytes(raw.encode("utf-8")) != row["record_sha256"]:
            raise _invalid()
        value = model.model_validate_json(raw)
        # This also rejects duplicate JSON keys, noncanonical encodings and hidden data.
        if self._encode(value) != raw:
            raise _invalid()
        return value

    def _campaign_id(self, value: str) -> None:
        TypeAdapter(CampaignId).validate_python(value, strict=True)
        self._clean(value)

    def _registration(self, row: sqlite3.Row) -> CampaignRegistration:
        registration = self._decode(CampaignRegistration, row)
        manifest = registration.manifest
        if (
            manifest.campaign_id != row["campaign_id"]
            or manifest.manifest_id != row["manifest_id"]
            or type(row["revision"]) is not int
            or manifest.revision != row["revision"]
            or manifest.sha256 != row["manifest_sha256"]
            or registration.registered_at.isoformat() != row["registered_at"]
        ):
            raise _invalid()
        return registration

    def _snapshot(
        self, connection: sqlite3.Connection, campaign_id: str
    ) -> EvaluationLedgerSnapshot:
        rows = connection.execute(
            f"SELECT {_columns('evaluation_campaigns')} FROM evaluation_campaigns "
            "WHERE campaign_id=? LIMIT 2",
            (campaign_id,),
        ).fetchall()
        if not rows:
            raise FleetError(
                ErrorCode.RESOURCE_NOT_FOUND,
                "The evaluation campaign is not registered.",
                "Register an immutable manifest before reserving its slots.",
            )
        if len(rows) != 1:
            raise _invalid()
        registration = self._registration(rows[0])
        manifest = registration.manifest
        if manifest.previous_sha256 is not None:
            previous = connection.execute(
                f"SELECT {_columns('evaluation_campaigns')} FROM evaluation_campaigns "
                "WHERE manifest_sha256=? LIMIT 2",
                (manifest.previous_sha256,),
            ).fetchall()
            if len(previous) != 1:
                raise _invalid()
            prior = self._registration(previous[0])
            if (
                prior.manifest.manifest_id != manifest.manifest_id
                or prior.manifest.revision + 1 != manifest.revision
                or prior.manifest.campaign_id == campaign_id
                or prior.registered_at > registration.registered_at
            ):
                raise _invalid()
        slots = connection.execute(
            f"SELECT {_columns('evaluation_slots')} FROM evaluation_slots WHERE campaign_id=? "
            "ORDER BY case_id,repetition LIMIT 257",
            (campaign_id,),
        ).fetchall()
        expected = sorted((slot.case_id, slot.repetition) for slot in manifest.slots)
        actual = []
        for item in slots:
            slot = EvaluationSlot(case_id=item["case_id"], repetition=item["repetition"])
            actual.append((slot.case_id, slot.repetition))
        if actual != expected:
            raise _invalid()
        reservations = []
        for item in connection.execute(
            f"SELECT {_columns('evaluation_reservations')} FROM evaluation_reservations "
            "WHERE campaign_id=? "
            "ORDER BY case_id,repetition LIMIT 257",
            (campaign_id,),
        ):
            reservation = self._decode(EvaluationReservation, item)
            if (
                any(
                    getattr(reservation, field) != item[field]
                    for field in (
                        "campaign_id",
                        "attempt_id",
                        "case_id",
                        "repetition",
                        "idempotency_sha256",
                    )
                )
                or type(item["repetition"]) is not int
            ):
                raise _invalid()
            reservations.append(reservation)
        outcomes = []
        for item in connection.execute(
            f"SELECT {_columns('evaluation_outcomes')} FROM evaluation_outcomes "
            "WHERE campaign_id=? ORDER BY outcome_id LIMIT 257",
            (campaign_id,),
        ):
            record = self._decode(OutcomeRecord, item)
            if any(
                getattr(record, field) != item[field]
                for field in ("campaign_id", "attempt_id", "outcome_id")
            ):
                raise _invalid()
            outcomes.append(record)
        reserved = tuple(reservations)
        return EvaluationLedgerSnapshot(
            registration=registration,
            reservations=reserved,
            outcomes=tuple(outcomes),
            committed=committed_envelopes(reserved),
        )

    @_boundary
    def register(self, manifest: EvaluationManifest) -> CampaignRegistration:
        manifest = self._validate(EvaluationManifest, manifest)
        with self._transaction(write=True) as connection:
            row = connection.execute(
                "SELECT campaign_id FROM evaluation_campaigns "
                "WHERE campaign_id=? OR (manifest_id=? AND revision=?) LIMIT 3",
                (manifest.campaign_id, manifest.manifest_id, manifest.revision),
            ).fetchall()
            if row:
                for item in row:
                    old = self._snapshot(connection, item["campaign_id"]).registration
                    if old.manifest != manifest:
                        raise _conflict()
                return old
            registration = CampaignRegistration(
                manifest=manifest, registered_at=self.state.clock.now()
            )
            if manifest.previous_sha256 is not None:
                prior_rows = connection.execute(
                    "SELECT campaign_id FROM evaluation_campaigns WHERE manifest_sha256=? LIMIT 2",
                    (manifest.previous_sha256,),
                ).fetchall()
                if not prior_rows:
                    raise _conflict()
                if len(prior_rows) != 1:
                    raise _invalid()
                prior = self._snapshot(connection, prior_rows[0]["campaign_id"]).registration
                if (
                    prior.manifest.manifest_id != manifest.manifest_id
                    or prior.manifest.revision + 1 != manifest.revision
                    or prior.registered_at > registration.registered_at
                ):
                    raise _conflict()
            raw = self._encode(registration)
            connection.execute(
                "INSERT INTO evaluation_campaigns VALUES (?,?,?,?,?,?,?)",
                (
                    manifest.campaign_id,
                    manifest.manifest_id,
                    manifest.revision,
                    manifest.sha256,
                    registration.registered_at.isoformat(),
                    sha256_bytes(raw.encode()),
                    raw,
                ),
            )
            connection.executemany(
                "INSERT INTO evaluation_slots VALUES (?,?,?)",
                [(manifest.campaign_id, slot.case_id, slot.repetition) for slot in manifest.slots],
            )
            return self._snapshot(connection, manifest.campaign_id).registration

    @_boundary
    def reserve(
        self, campaign_id: str, case_id: str, repetition: int, idempotency_key: str
    ) -> EvaluationReservation:
        self._campaign_id(campaign_id)
        slot = EvaluationSlot(case_id=case_id, repetition=repetition)
        self._encode(slot)
        TypeAdapter(IdempotencyKey).validate_python(idempotency_key, strict=True)
        self._clean(idempotency_key)
        self._clean(json.dumps(idempotency_key, ensure_ascii=False))
        digest = sha256_bytes(idempotency_key.encode())
        with self._transaction(write=True) as connection:
            snapshot = self._snapshot(connection, campaign_id)
            manifest = snapshot.registration.manifest
            for item in snapshot.reservations:
                same_slot = (item.case_id, item.repetition) == (case_id, repetition)
                same_key = item.idempotency_sha256 == digest
                if same_slot or same_key:
                    if same_slot and same_key:
                        return item
                    raise _conflict()
            if slot not in manifest.slots:
                raise _conflict()
            case = next(item for item in manifest.cases if item.case_id == case_id)
            limits = snapshot.committed.model_dump()
            limits["attempts"] += 1
            for field in limits:
                if field != "attempts":
                    limits[field] += getattr(case.run_budget, "max_" + field)
                if limits[field] > getattr(manifest.budget, "max_" + field):
                    raise FleetError(
                        ErrorCode.RUNTIME_BUDGET_EXCEEDED,
                        "The evaluation campaign cannot commit another complete Run envelope.",
                        "Retain every reservation; this ledger does not refund or execute work.",
                    )
            correlation = self.state.ids.new(IdPrefix.CORRELATION)
            TypeAdapter(CorrelationId).validate_python(correlation, strict=True)
            reservation = EvaluationReservation(
                campaign_id=campaign_id,
                manifest_sha256=manifest.sha256,
                case_id=case_id,
                repetition=repetition,
                attempt_id="attempt_" + correlation.removeprefix("corr_"),
                idempotency_sha256=digest,
                reserved_at=require_utc(self.state.clock.now()),
                commitment=case.run_budget,
            )
            collisions = connection.execute(
                "SELECT campaign_id FROM evaluation_reservations WHERE attempt_id=? LIMIT 2",
                (reservation.attempt_id,),
            ).fetchall()
            if collisions:
                for collision in collisions:
                    self._snapshot(connection, collision["campaign_id"])
                raise _conflict()
            raw = self._encode(reservation)
            connection.execute(
                "INSERT INTO evaluation_reservations VALUES (?,?,?,?,?,?,?)",
                (
                    reservation.attempt_id,
                    campaign_id,
                    case_id,
                    repetition,
                    digest,
                    sha256_bytes(raw.encode()),
                    raw,
                ),
            )
            self._snapshot(connection, campaign_id)
            return reservation

    @_boundary
    def record_preflight_outcome(self, record: OutcomeRecord) -> EvaluationLedgerSnapshot:
        record = self._validate(OutcomeRecord, record)
        validate_preflight(record)
        with self._transaction(write=True) as connection:
            if connection.execute(
                "SELECT 1 FROM evaluation_executions WHERE attempt_id=?", (record.attempt_id,)
            ).fetchone():
                raise _conflict()
            if connection.execute(
                "SELECT 1 FROM run_events WHERE event_type='evaluation.execution_registered' "
                "AND json_extract(data_json, '$.payload.attempt_id')=? LIMIT 1",
                (record.attempt_id,),
            ).fetchone():
                raise _conflict()
            snapshot = self._snapshot(connection, record.campaign_id)
            rows = connection.execute(
                f"SELECT {_columns('evaluation_outcomes')} FROM evaluation_outcomes "
                "WHERE outcome_id=? OR attempt_id=? LIMIT 3",
                (record.outcome_id, record.attempt_id),
            ).fetchall()
            if rows:
                for row in rows:
                    self._snapshot(connection, row["campaign_id"])
                    if self._decode(OutcomeRecord, row) != record:
                        raise _conflict()
                return snapshot
            EvaluationLedgerSnapshot(
                registration=snapshot.registration,
                reservations=snapshot.reservations,
                outcomes=(*snapshot.outcomes, record),
                committed=snapshot.committed,
            )
            raw = self._encode(record)
            connection.execute(
                "INSERT INTO evaluation_outcomes VALUES (?,?,?,?,?)",
                (
                    record.outcome_id,
                    record.attempt_id,
                    record.campaign_id,
                    sha256_bytes(raw.encode()),
                    raw,
                ),
            )
            return self._snapshot(connection, record.campaign_id)

    @_boundary
    def snapshot(self, campaign_id: str) -> EvaluationLedgerSnapshot:
        self._campaign_id(campaign_id)
        with self._transaction(write=False) as connection:
            return self._snapshot(connection, campaign_id)

    def _record_terminal_in_transaction(
        self,
        connection: sqlite3.Connection,
        observation: EvaluationObservation,
        record: OutcomeRecord,
    ) -> OutcomeRecord:
        """Called only after the physical observer's same-transaction identity CAS."""
        record = self._validate(OutcomeRecord, record)
        validate_terminal_outcome(record)
        projected = {
            "campaign_id": observation.campaign_id,
            "attempt_id": observation.attempt_id,
            "manifest_sha256": observation.manifest_sha256,
            "case_id": observation.case_id,
            "repetition": observation.repetition,
            "root_run_id": observation.root_run_id,
            "task_id": observation.task_id,
            "configuration_sha256": observation.configuration_sha256,
            "oracle_sha256": observation.oracle_sha256,
            "scoring_sha256": observation.scoring_sha256,
            "product_status": observation.product_status,
            "product_verdict": observation.product_verdict,
            "product_verified_complete": observation.product_verified_complete,
            "external_result": observation.terminal_result,
            "apply_status": observation.apply_status,
            "artifacts": observation.artifacts,
            "usage": observation.usage,
        }
        if any(getattr(record, key) != value for key, value in projected.items()) or (
            record.reported_cost_microunits is not None or record.currency is not None
        ):
            raise _conflict()
        snapshot = self._snapshot(connection, record.campaign_id)
        existing = [item for item in snapshot.outcomes if item.attempt_id == record.attempt_id]
        if existing:
            original = existing[0]
            if original.model_dump(exclude={"outcome_id", "recorded_at"}) != record.model_dump(
                exclude={"outcome_id", "recorded_at"}
            ):
                raise _conflict()
            return original
        EvaluationLedgerSnapshot(
            registration=snapshot.registration,
            reservations=snapshot.reservations,
            outcomes=(*snapshot.outcomes, record),
            committed=snapshot.committed,
        )
        raw = self._encode(record)
        connection.execute(
            "INSERT INTO evaluation_outcomes VALUES (?,?,?,?,?)",
            (
                record.outcome_id,
                record.attempt_id,
                record.campaign_id,
                sha256_bytes(raw.encode()),
                raw,
            ),
        )
        return record
