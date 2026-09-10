"""Actual additive migration/transaction checks; not older-distribution qualification."""

import sqlite3
from pathlib import Path

import pytest
from business_baseline_fixtures import baseline_fixture

import agent_fleet.adapters.persistence.sqlite as sqlite_adapter
from agent_fleet.domain.errors import ErrorCode, FleetError

BASELINE_TABLES = (
    "baseline_events",
    "baseline_cleanup_receipts",
    "baseline_reports",
    "baseline_command_observations",
    "baseline_resource_leases",
    "baseline_dispatch_claims",
    "baseline_owner_claims",
    "baseline_authorizations",
    "baseline_reviews",
    "baseline_executions",
)


def _legacy_rows(connection: sqlite3.Connection) -> dict[str, list[tuple[object, ...]]]:
    tables = [
        row[0]
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        if row[0] not in BASELINE_TABLES and row[0] != "schema_migrations"
    ]
    return {name: connection.execute(f'SELECT * FROM "{name}"').fetchall() for name in tables}


def test_real_v12_upgrade_preserves_legacy_rows_and_adds_exactly_ten_tables(tmp_path: Path) -> None:
    h = baseline_fixture(tmp_path)
    with sqlite3.connect(h.state.database_path) as connection:
        for name in BASELINE_TABLES:
            connection.execute(f"DROP TABLE {name}")
        connection.execute("DELETE FROM schema_migrations WHERE version=13")
        assert connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 12
        before = _legacy_rows(connection)
    assert h.state.migrate() == 13
    assert h.state.get_project(h.project.project_id) == h.project
    with sqlite3.connect(h.state.database_path) as connection:
        assert _legacy_rows(connection) == before
        found = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            if row[0].startswith("baseline_")
        }
        assert found == set(BASELINE_TABLES)
        assert all(
            connection.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] == 0
            for name in BASELINE_TABLES
        )
    assert h.state.migrate() == 13


def test_migration13_failure_rolls_back_every_new_table(tmp_path: Path) -> None:
    h = baseline_fixture(tmp_path)
    with sqlite3.connect(h.state.database_path) as connection:
        for name in BASELINE_TABLES:
            connection.execute(f"DROP TABLE {name}")
        connection.execute("DELETE FROM schema_migrations WHERE version=13")
        before = _legacy_rows(connection)
        connection.execute("CREATE TABLE baseline_events (fixture INTEGER)")
    with pytest.raises(FleetError):
        h.state.migrate()
    with sqlite3.connect(h.state.database_path) as connection:
        assert connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 12
        assert _legacy_rows(connection) == before
        for name in BASELINE_TABLES:
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
            ).fetchone()
            assert bool(exists) == (name == "baseline_events")


def test_older_version_admission_refuses_new_schema_without_baseline_repair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = baseline_fixture(tmp_path)
    before = h.store.show(h.review.review_id)
    with monkeypatch.context() as previous_version:
        previous_version.setattr(sqlite_adapter, "SUPPORTED_SCHEMA_VERSION", 12)
        with pytest.raises(FleetError) as denied:
            h.state.migrate()
        assert denied.value.code is ErrorCode.STATE_SCHEMA_INCOMPATIBLE
    assert h.store.show(h.review.review_id) == before
