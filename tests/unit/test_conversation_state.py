from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path

import pytest

import agent_fleet.adapters.persistence.sqlite as sqlite_module
from agent_fleet.adapters.persistence.conversations import SqliteConversationStore
from agent_fleet.adapters.persistence.sqlite import SqliteStateStore
from agent_fleet.adapters.system import SystemClock, UuidIdGenerator
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.ids import IdPrefix
from agent_fleet.domain.models import Project, Run
from agent_fleet.domain.security import Redactor


def _state(path: Path) -> SqliteStateStore:
    return SqliteStateStore(path, SystemClock(), UuidIdGenerator(), Redactor())


def _run(state: SqliteStateStore) -> Run:
    now = state.clock.now()
    project = Project(
        project_id=state.ids.new(IdPrefix.PROJECT),
        canonical_root=str(state.database_path.parent / "repository"),
        identity_hash="1" * 64,
        fleet_spec_hash="2" * 64,
        created_at=now,
        updated_at=now,
    )
    state.save_project(project)
    run = Run(
        run_id=state.ids.new(IdPrefix.RUN),
        project_id=project.project_id,
        correlation_id=state.ids.new(IdPrefix.CORRELATION),
        goal="Preserve existing state",
        base_revision="a" * 40,
        target_status_fingerprint="3" * 64,
        created_at=now,
        updated_at=now,
    )
    state.create_run(run)
    return run


def test_schema7_upgrade_is_atomic_and_does_not_fabricate_legacy_conversations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(tmp_path / "state.db")
    with monkeypatch.context() as older:
        older.setattr(sqlite_module, "SUPPORTED_SCHEMA_VERSION", 6)
        assert state.migrate() == 6
    run = _run(state)
    migration = (
        files("agent_fleet.adapters.persistence.migrations").joinpath("0007.sql").read_text()
    )

    class BrokenMigration:
        def joinpath(self, name: str) -> BrokenMigration:
            assert name == "0007.sql"
            return self

        def read_text(self, *, encoding: str) -> str:
            assert encoding == "utf-8"
            return migration + "\nSELECT * FROM injected_missing_migration_table;"

    with monkeypatch.context() as broken:
        broken.setattr(sqlite_module, "files", lambda _: BrokenMigration())
        with pytest.raises(FleetError):
            state.migrate()
    with state._connect() as connection:
        assert connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 6
        assert (
            connection.execute(
                "SELECT name FROM sqlite_master WHERE name LIKE 'conversation%'"
            ).fetchall()
            == []
        )
    assert state.get_run(run.run_id) == run
    assert state.migrate() == sqlite_module.SUPPORTED_SCHEMA_VERSION
    store = SqliteConversationStore(
        state.database_path, state.clock, state.ids, state.redactor, state
    )
    assert store.binding_for_run(run.run_id) is None
    assert store.latest(run.project_id, "1" * 64) is None
    assert state.get_run(run.run_id) == run
    assert [event.event_type for event in state.list_events(run.run_id)] == ["run.created"]


def test_conversation_constructor_is_lazy_and_wrong_database_cannot_receive_run(
    tmp_path: Path,
) -> None:
    path = tmp_path / "absent" / "state.db"
    state = _state(path)
    store = SqliteConversationStore(path, state.clock, state.ids, state.redactor, state)
    assert not path.parent.exists()
    with pytest.raises(FleetError) as error:
        store.latest("prj_" + "1" * 32, "1" * 64)
    assert error.value.code is ErrorCode.STATE_UNAVAILABLE and not path.parent.exists()
    other = SqliteConversationStore(
        tmp_path / "other.db", state.clock, state.ids, state.redactor, state
    )
    with pytest.raises(FleetError) as error:
        other.latest("prj_" + "1" * 32, "1" * 64)
    assert error.value.code is ErrorCode.RECOVERY_REQUIRED


def test_progress_pages_are_ordered_bounded_and_do_not_repeat(tmp_path: Path) -> None:
    state = _state(tmp_path / "state.db")
    state.migrate()
    run = _run(state)
    for index in range(130):
        state.save_run(run, "progress.recorded", {"index": index})
    first = state.list_events_after(run.run_id, limit=64)
    second = state.list_events_after(run.run_id, after_sequence=64, limit=64)
    third = state.list_events_after(run.run_id, after_sequence=128, limit=64)
    assert [event.sequence for event in [*first, *second, *third]] == list(range(1, 132))
    assert state.list_events_after(run.run_id, after_sequence=131) == []
    state.save_run(run, "progress.appended", {})
    assert [
        event.sequence for event in state.list_events_after(run.run_id, after_sequence=131)
    ] == [132]


@pytest.mark.parametrize("after,limit", [(-1, 1), (True, 1), (0, 0), (0, 101), (0, True)])
def test_progress_rejects_invalid_cursor_and_limits(tmp_path: Path, after: int, limit: int) -> None:
    state = _state(tmp_path / "state.db")
    with pytest.raises(FleetError) as error:
        state.list_events_after("run_" + "1" * 32, after_sequence=after, limit=limit)
    assert error.value.code is ErrorCode.COMMAND_DENIED
    assert not state.database_path.exists()


@pytest.mark.parametrize("corruption", ["event_sequence", "event_project", "run_sql", "secret"])
def test_progress_rejects_corrupt_sql_json_and_secret_context(
    tmp_path: Path, corruption: str
) -> None:
    state = _state(tmp_path / "state.db")
    state.migrate()
    run = _run(state)
    sentinel = "pagination-private-token-876543210"
    state.redactor.register_secret(sentinel)
    with state._connect() as connection:
        if corruption == "run_sql":
            connection.execute("UPDATE runs SET status='running' WHERE run_id=?", (run.run_id,))
        else:
            row = connection.execute(
                "SELECT data_json FROM run_events WHERE run_id=?", (run.run_id,)
            ).fetchone()
            data = json.loads(row["data_json"])
            if corruption == "event_sequence":
                data["sequence"] = 99
            elif corruption == "event_project":
                data["project_id"] = "prj_" + "f" * 32
            else:
                data["unknown"] = sentinel
            connection.execute(
                "UPDATE run_events SET data_json=? WHERE run_id=?", (json.dumps(data), run.run_id)
            )
    with pytest.raises(FleetError) as error:
        state.list_events_after(run.run_id)
    assert error.value.code is ErrorCode.RECOVERY_REQUIRED
    assert error.value.__context__ is None and sentinel not in str(error.value)
