"""Durable commitments use real transactions, independent processes and hostile rows."""

from __future__ import annotations

import json
import multiprocessing
import sqlite3
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from evaluation_ledger_fixtures import (
    LedgerHarness,
    ledger_harness,
    ledger_manifest,
    preflight_record,
)
from model_profiles_fixtures import make_profile_harness

from agent_fleet.adapters.persistence.evaluations import SqliteEvaluationStore
from agent_fleet.adapters.persistence.sqlite import SUPPORTED_SCHEMA_VERSION
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.evaluation_campaign import EvaluationReservation
from agent_fleet.domain.ids import IdPrefix
from agent_fleet.domain.outcomes import OutcomeUsage
from agent_fleet.domain.security import sha256_bytes


@pytest.fixture
def ledger(tmp_path: Path) -> LedgerHarness:
    return ledger_harness(tmp_path)


def reserve_first(h: LedgerHarness) -> EvaluationReservation:
    manifest = ledger_manifest()
    h.service.register(manifest)
    slot = manifest.slots[0]
    return h.service.reserve(manifest.campaign_id, slot.case_id, slot.repetition, "first")


def assert_safe(error: FleetError, sentinel: str = "hostile-ledger-sentinel") -> None:
    assert sentinel not in str(error)
    assert error.__cause__ is None and error.__context__ is None


def test_exact_idempotency_retains_original_times_and_never_releases(ledger: LedgerHarness) -> None:
    manifest = ledger_manifest()
    first = ledger.service.register(manifest)
    reservation = reserve_first(ledger)
    record = preflight_record(manifest, reservation)
    initial = ledger.service.record_preflight_outcome(record)
    ledger.clock.value += timedelta(days=1)
    reopened = SqliteEvaluationStore(ledger.state)
    assert reopened.register(manifest) == first
    assert (
        reopened.reserve(manifest.campaign_id, reservation.case_id, reservation.repetition, "first")
        == reservation
    )
    assert reopened.record_preflight_outcome(record) == initial
    assert reopened.snapshot(manifest.campaign_id) == initial
    assert initial.committed.attempts == 1
    assert initial.committed.total_tokens == reservation.commitment.max_total_tokens
    assert initial.outcomes[0].reported_cost_microunits is None
    assert not initial.execution_authorized and not reservation.execution_authorized
    with sqlite3.connect(ledger.state.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM evaluation_outcomes").fetchone()[0] == 1
        assert "first" not in "".join(
            row[0] for row in connection.execute("SELECT data_json FROM evaluation_reservations")
        )


@pytest.mark.parametrize("kind", ["slot", "key", "manifest", "outcome", "attempt"])
def test_conflicting_identities_never_replace_committed_rows(
    ledger: LedgerHarness, kind: str
) -> None:
    manifest = ledger_manifest()
    reservation = reserve_first(ledger)
    record = preflight_record(manifest, reservation)
    before = ledger.service.record_preflight_outcome(record)
    with pytest.raises(FleetError) as error:
        if kind == "slot":
            ledger.store.reserve(
                manifest.campaign_id, reservation.case_id, reservation.repetition, "new-key"
            )
        elif kind == "key":
            slot = manifest.slots[1]
            ledger.store.reserve(manifest.campaign_id, slot.case_id, slot.repetition, "first")
        elif kind == "manifest":
            ledger.store.register(
                manifest.model_copy(update={"frozen_at": manifest.frozen_at + timedelta(seconds=1)})
            )
        elif kind == "outcome":
            ledger.store.record_preflight_outcome(
                record.model_copy(update={"external_result": "timeout"})
            )
        else:
            ledger.store.record_preflight_outcome(
                record.model_copy(update={"outcome_id": "outcome_" + "f" * 32})
            )
    assert error.value.code is ErrorCode.CONFIG_INVALID
    assert_safe(error.value)
    assert ledger.store.snapshot(manifest.campaign_id) == before


def test_all_36_preregistered_slots_stay_committed_after_failure_and_reopen(
    ledger: LedgerHarness,
) -> None:
    manifest = ledger_manifest()
    ledger.store.register(manifest)
    for index, slot in enumerate(manifest.slots):
        reservation = ledger.store.reserve(
            manifest.campaign_id, slot.case_id, slot.repetition, f"slot-{index}"
        )
        ledger.store.record_preflight_outcome(
            preflight_record(manifest, reservation, suffix=index + 1)
        )
    reopened = SqliteEvaluationStore(ledger.state).snapshot(manifest.campaign_id)
    assert len(reopened.reservations) == len(reopened.outcomes) == reopened.committed.attempts == 36
    assert reopened.committed.total_tokens == manifest.budget.max_total_tokens
    with pytest.raises(FleetError):
        ledger.store.reserve(manifest.campaign_id, manifest.slots[0].case_id, 2, "replacement")
    assert ledger.store.snapshot(manifest.campaign_id) == reopened


def _race_worker(root: str, slot_index: int, key: str, barrier: Any, results: Any) -> None:
    h = ledger_harness(Path(root), migrate=False)
    manifest = ledger_manifest()
    slot = manifest.slots[slot_index]
    barrier.wait(timeout=10)
    try:
        reservation = h.store.reserve(manifest.campaign_id, slot.case_id, slot.repetition, key)
        results.put(("reserved", reservation.attempt_id))
    except FleetError as error:
        results.put((error.code.value, ""))


@pytest.mark.parametrize("race", ["same_slot", "last_budget", "same_idempotency"])
def test_two_process_race_commits_exactly_one_envelope(ledger: LedgerHarness, race: str) -> None:
    manifest = ledger_manifest()
    if race == "last_budget":
        manifest = manifest.model_copy(
            update={
                "budget": manifest.budget.model_copy(
                    update={"max_model_requests": manifest.cases[0].run_budget.max_model_requests}
                )
            }
        )
    ledger.store.register(manifest)
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(2)
    results = context.Queue()
    processes = [
        context.Process(
            target=_race_worker,
            args=(
                str(ledger.state.database_path.parent),
                index if race == "last_budget" else 0,
                "same" if race == "same_idempotency" else f"worker-{index}",
                barrier,
                results,
            ),
        )
        for index in range(2)
    ]
    for process in processes:
        process.start()
    observations = [results.get(timeout=30) for _ in processes]
    for process in processes:
        process.join(timeout=30)
        assert process.exitcode == 0
        process.close()
    results.close()
    results.join_thread()
    statuses = [item[0] for item in observations]
    if race == "same_idempotency":
        assert statuses == ["reserved", "reserved"]
        assert observations[0][1] == observations[1][1]
    else:
        assert statuses.count("reserved") == 1
        expected = (
            ErrorCode.CONFIG_INVALID if race == "same_slot" else ErrorCode.RUNTIME_BUDGET_EXCEEDED
        )
        assert expected.value in statuses
    snapshot = ledger.store.snapshot(manifest.campaign_id)
    assert snapshot.committed.attempts == len(snapshot.reservations) == 1


@pytest.mark.parametrize("operation", ["register", "reserve", "outcome"])
def test_sql_failure_rolls_back_entire_mutation_and_hides_raw_cause(
    ledger: LedgerHarness, operation: str
) -> None:
    manifest = ledger_manifest()
    table = {
        "register": "evaluation_slots",
        "reserve": "evaluation_reservations",
        "outcome": "evaluation_outcomes",
    }[operation]
    if operation != "register":
        ledger.store.register(manifest)
    reservation = reserve_first(ledger) if operation == "outcome" else None
    with sqlite3.connect(ledger.state.database_path) as connection:
        before = {
            name: connection.execute(f"SELECT * FROM {name}").fetchall()
            for name in (
                "evaluation_campaigns",
                "evaluation_slots",
                "evaluation_reservations",
                "evaluation_outcomes",
            )
        }
        connection.execute(
            f"CREATE TRIGGER reject_ledger BEFORE INSERT ON {table} "
            "BEGIN SELECT RAISE(ABORT, 'hostile-ledger-sentinel'); END"
        )
    with pytest.raises(FleetError) as error:
        if operation == "register":
            ledger.store.register(manifest)
        elif operation == "reserve":
            reserve_first(ledger)
        else:
            assert reservation is not None
            ledger.store.record_preflight_outcome(preflight_record(manifest, reservation))
    assert_safe(error.value)
    with sqlite3.connect(ledger.state.database_path) as connection:
        for name, rows in before.items():
            assert connection.execute(f"SELECT * FROM {name}").fetchall() == rows


@pytest.mark.parametrize(
    "mutation",
    [
        "hash",
        "json",
        "oversized",
        "duplicate_json",
        "slot_missing",
        "slot_extra",
        "binding",
        "outcome_binding",
        "false_counter",
    ],
)
def test_corrupted_persistent_rows_fail_closed(ledger: LedgerHarness, mutation: str) -> None:
    manifest = ledger_manifest()
    reservation = reserve_first(ledger)
    ledger.store.record_preflight_outcome(preflight_record(manifest, reservation))
    with sqlite3.connect(ledger.state.database_path) as connection:
        if mutation == "hash":
            connection.execute("UPDATE evaluation_campaigns SET record_sha256=?", ("f" * 64,))
        elif mutation in {"json", "oversized", "duplicate_json"}:
            raw = "hostile-ledger-sentinel" if mutation == "json" else "x" * 2_097_153
            if mutation == "duplicate_json":
                original = connection.execute(
                    "SELECT data_json FROM evaluation_campaigns"
                ).fetchone()[0]
                raw = '{"execution_authorized":true,' + original[1:]
            connection.execute(
                "UPDATE evaluation_campaigns SET data_json=?,record_sha256=?",
                (raw, sha256_bytes(raw.encode())),
            )
        elif mutation == "slot_missing":
            connection.execute(
                "DELETE FROM evaluation_slots WHERE rowid=(SELECT MIN(rowid) FROM evaluation_slots)"
            )
        elif mutation == "slot_extra":
            connection.execute(
                "INSERT INTO evaluation_slots VALUES (?,?,?)",
                (manifest.campaign_id, "unregistered", 0),
            )
        elif mutation == "binding":
            connection.execute(
                "UPDATE evaluation_reservations SET idempotency_sha256=?", ("f" * 64,)
            )
        elif mutation == "outcome_binding":
            connection.execute(
                "UPDATE evaluation_outcomes SET outcome_id=?", ("outcome_" + "f" * 32,)
            )
        else:
            raw = connection.execute("SELECT data_json FROM evaluation_reservations").fetchone()[0]
            value = json.loads(raw)
            value["commitment"]["max_model_requests"] = 1
            raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            connection.execute(
                "UPDATE evaluation_reservations SET data_json=?,record_sha256=?",
                (raw, sha256_bytes(raw.encode())),
            )
    for operation in (
        lambda: ledger.store.snapshot(manifest.campaign_id),
        lambda: ledger.store.register(manifest),
        lambda: ledger.store.reserve(manifest.campaign_id, reservation.case_id, 0, "first"),
    ):
        with pytest.raises(FleetError) as error:
            operation()
        assert error.value.code is ErrorCode.RECOVERY_REQUIRED
        assert_safe(error.value)


@pytest.mark.parametrize("schema", ["absent", "future", "incomplete", "missing_table"])
def test_no_implicit_creation_or_migration(
    ledger: LedgerHarness, schema: str, tmp_path: Path
) -> None:
    if schema == "absent":
        ledger.state.database_path = tmp_path / "missing" / "state.db"
    else:
        with sqlite3.connect(ledger.state.database_path) as connection:
            if schema == "future":
                connection.execute(
                    "INSERT INTO schema_migrations VALUES (?,?)",
                    (SUPPORTED_SCHEMA_VERSION + 1, "retained"),
                )
            elif schema == "incomplete":
                connection.execute("DELETE FROM schema_migrations WHERE version=3")
            else:
                connection.execute("DROP TABLE evaluation_outcomes")
    with pytest.raises(FleetError) as error:
        ledger.store.register(ledger_manifest())
    assert_safe(error.value)
    if schema == "absent":
        assert not ledger.state.database_path.parent.exists()
    elif schema in {"future", "incomplete"}:
        assert error.value.code is ErrorCode.STATE_SCHEMA_INCOMPATIBLE


@pytest.mark.parametrize("surface", ["manifest", "json_form", "key", "outcome"])
def test_registered_secret_rejected_before_persistence(ledger: LedgerHarness, surface: str) -> None:
    manifest = ledger_manifest()
    sentinel = "synthetic-ledger-secret-123"
    if surface in {"manifest", "json_form"}:
        manifest = manifest.model_copy(
            update={
                "cases": (
                    manifest.cases[0].model_copy(update={"requirement": sentinel}),
                    *manifest.cases[1:],
                )
            }
        )
        ledger.state.redactor.register_secret(
            sentinel if surface == "manifest" else json.dumps(sentinel)
        )
    else:
        ledger.state.redactor.register_secret(sentinel)
    with pytest.raises(FleetError) as error:
        if surface in {"manifest", "json_form"}:
            ledger.store.register(manifest)
        elif surface == "key":
            ledger.store.register(manifest)
            ledger.store.reserve(manifest.campaign_id, manifest.slots[0].case_id, 0, sentinel)
        else:
            reservation = reserve_first(ledger)
            record = preflight_record(manifest, reservation)
            ledger.store.record_preflight_outcome(
                record.model_copy(update={"usage": (OutcomeUsage(segment_id=sentinel),)})
            )
    assert_safe(error.value, sentinel)
    with sqlite3.connect(ledger.state.database_path) as connection:
        assert sentinel not in "\n".join(connection.iterdump())


def test_revisions_require_exact_retained_predecessor_and_new_campaign(
    ledger: LedgerHarness,
) -> None:
    original = ledger_manifest()
    revision = original.model_copy(
        update={
            "revision": 1,
            "previous_sha256": original.sha256,
            "campaign_id": "campaign_" + "b" * 32,
        }
    )
    with pytest.raises(FleetError):
        ledger.store.register(revision)
    reservation = reserve_first(ledger)
    old = ledger.store.snapshot(original.campaign_id)
    registered = ledger.store.register(revision)
    assert registered.manifest.previous_sha256 == original.sha256
    assert ledger.store.snapshot(original.campaign_id) == old
    assert ledger.store.snapshot(original.campaign_id).reservations == (reservation,)
    with pytest.raises(FleetError):
        ledger.store.register(revision.model_copy(update={"campaign_id": "campaign_" + "c" * 32}))


def test_injected_id_collision_does_not_charge_or_replace(ledger: LedgerHarness) -> None:
    first = reserve_first(ledger)

    class RepeatedIds:
        def new(self, prefix: IdPrefix) -> str:
            assert prefix is IdPrefix.CORRELATION
            return "corr_" + first.attempt_id.removeprefix("attempt_")

    ledger.state.ids = RepeatedIds()
    manifest = ledger_manifest()
    slot = manifest.slots[1]
    with pytest.raises(FleetError):
        ledger.store.reserve(manifest.campaign_id, slot.case_id, slot.repetition, "other")
    assert ledger.store.snapshot(manifest.campaign_id).committed.attempts == 1


@pytest.mark.parametrize("mutation", ["earlier", "boolean", "unknown", "usage"])
def test_untrusted_outcomes_cannot_bypass_pure_validation(
    ledger: LedgerHarness, mutation: str
) -> None:
    manifest = ledger_manifest()
    reservation = reserve_first(ledger)
    record = preflight_record(manifest, reservation)
    changes: dict[str, object] = {}
    if mutation == "earlier":
        changes["recorded_at"] = reservation.reserved_at - timedelta(microseconds=1)
    elif mutation == "boolean":
        changes["repetition"] = False
    elif mutation == "unknown":
        changes["external_result"] = "dispatch_unknown"
    else:
        changes["usage"] = (OutcomeUsage(segment_id="preflight", unknown_requests=1),)
    with pytest.raises(FleetError) as error:
        ledger.store.record_preflight_outcome(record.model_copy(update=changes))
    assert_safe(error.value)
    assert ledger.store.snapshot(manifest.campaign_id).outcomes == ()


def test_migration11_preserves_old_tables_and_rolls_back_partial_ddl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with monkeypatch.context() as historical:
        historical.setattr("agent_fleet.adapters.persistence.sqlite.SUPPORTED_SCHEMA_VERSION", 10)
        historical.setattr("model_profiles_fixtures.SUPPORTED_SCHEMA_VERSION", 10)
        h = make_profile_harness(tmp_path)
        h.run()
    with sqlite3.connect(h.state.database_path) as connection:
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name != 'schema_migrations'"
            )
        ]
        expected = {
            name: connection.execute(f'SELECT * FROM "{name}"').fetchall() for name in tables
        }
        assert expected["runs"] and expected["projects"] and expected["run_events"]
        connection.execute("CREATE TABLE evaluation_slots (fixture INTEGER)")
    with pytest.raises(FleetError):
        h.state.migrate()
    with sqlite3.connect(h.state.database_path) as connection:
        assert connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 10
        assert not connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name='evaluation_campaigns'"
        ).fetchall()
        connection.execute("DROP TABLE evaluation_slots")
    assert h.state.migrate() == SUPPORTED_SCHEMA_VERSION
    with sqlite3.connect(h.state.database_path) as connection:
        assert {
            name: connection.execute(f'SELECT * FROM "{name}"').fetchall() for name in tables
        } == expected
        assert connection.execute("SELECT COUNT(*) FROM evaluation_campaigns").fetchone()[0] == 0


def test_backward_clock_cannot_preregister_or_reserve(ledger: LedgerHarness) -> None:
    manifest = ledger_manifest()
    ledger.clock.value = manifest.frozen_at - timedelta(seconds=1)
    with pytest.raises(FleetError):
        ledger.store.register(manifest)
    with sqlite3.connect(ledger.state.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM evaluation_campaigns").fetchone()[0] == 0
    ledger.clock.value = manifest.frozen_at + timedelta(days=1)
    registration = ledger.store.register(manifest)
    ledger.clock.value = registration.registered_at - timedelta(seconds=1)
    with pytest.raises(FleetError):
        ledger.store.reserve(manifest.campaign_id, manifest.slots[0].case_id, 0, "earlier")
    assert ledger.store.snapshot(manifest.campaign_id).committed.attempts == 0


def test_bounded_fetch_rejects_257th_row_without_truncating_report(ledger: LedgerHarness) -> None:
    manifest = ledger_manifest()
    ledger.store.register(manifest)
    with sqlite3.connect(ledger.state.database_path) as connection:
        connection.executemany(
            "INSERT INTO evaluation_slots VALUES (?,?,?)",
            [(manifest.campaign_id, f"extra-{index}", 0) for index in range(257)],
        )
    with pytest.raises(FleetError) as error:
        ledger.service.report(manifest.campaign_id)
    assert error.value.code is ErrorCode.RECOVERY_REQUIRED


def test_cross_campaign_outcome_identity_is_not_reused(ledger: LedgerHarness) -> None:
    original = ledger_manifest()
    first = reserve_first(ledger)
    record = preflight_record(original, first)
    before = ledger.store.record_preflight_outcome(record)
    other = original.model_copy(
        update={"campaign_id": "campaign_" + "b" * 32, "manifest_id": "eval_" + "b" * 32}
    )
    ledger.store.register(other)
    reservation = ledger.store.reserve(other.campaign_id, other.slots[0].case_id, 0, "first")
    with pytest.raises(FleetError):
        ledger.store.record_preflight_outcome(preflight_record(other, reservation))
    assert ledger.store.snapshot(original.campaign_id) == before
    assert ledger.store.snapshot(other.campaign_id).outcomes == ()
