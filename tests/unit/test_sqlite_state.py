from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from conftest import FleetHarness

from agent_fleet.adapters.persistence.sqlite import SqliteStateStore
from agent_fleet.adapters.system import SystemClock, UuidIdGenerator
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.ids import IdPrefix
from agent_fleet.domain.models import Project, Run, RunStatus, WorkflowStage
from agent_fleet.domain.security import Redactor, status_fingerprint


def test_empty_migration_is_idempotent_and_reopens(tmp_path: Path) -> None:
    path = tmp_path / "state.db"
    first = SqliteStateStore(path, SystemClock(), UuidIdGenerator(), Redactor())
    assert first.migrate() == 1
    reopened = SqliteStateStore(path, SystemClock(), UuidIdGenerator(), Redactor())
    assert reopened.migrate() == 1
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (0,)
        assert connection.execute("SELECT version FROM schema_migrations").fetchall() == [(1,)]


def test_newer_schema_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "state.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (99, ?)",
            (datetime.now(UTC).isoformat(),),
        )
    state = SqliteStateStore(path, SystemClock(), UuidIdGenerator(), Redactor())
    with pytest.raises(FleetError) as captured:
        state.migrate()
    assert captured.value.code is ErrorCode.STATE_SCHEMA_INCOMPATIBLE


def test_project_reopens_legacy_semantic_hash_field_names() -> None:
    now = datetime.now(UTC)
    project = Project.model_validate(
        {
            "project_id": "prj_" + "1" * 32,
            "canonical_root": "/portable/repository",
            "identity_hash": "a" * 64,
            "repository_profile_hash": "b" * 64,
            "project_knowledge_hash": "c" * 64,
            "created_at": now,
            "updated_at": now,
        }
    )

    assert project.repository_profile_semantic_hash == "b" * 64
    assert project.project_knowledge_semantic_hash == "c" * 64
    assert "repository_profile_semantic_hash" in project.model_dump()
    assert "repository_profile_hash" not in project.model_dump()


def test_transition_and_event_sequence_are_committed_together(harness: FleetHarness) -> None:
    project = harness.container.state.get_project_by_root(str(harness.repository_root.resolve()))
    assert project is not None
    now = datetime.now(UTC)
    run = Run(
        run_id=harness.container.state.ids.new(IdPrefix.RUN),
        project_id=project.project_id,
        correlation_id=harness.container.state.ids.new(IdPrefix.CORRELATION),
        goal="transaction test",
        base_revision=harness.git("rev-parse", "HEAD").strip(),
        target_status_fingerprint=status_fingerprint(""),
        created_at=now,
        updated_at=now,
    )
    harness.container.state.create_run(run)
    intake = run.model_copy(
        update={
            "status": RunStatus.RUNNING,
            "stage": WorkflowStage.INTAKE,
            "updated_at": datetime.now(UTC),
        }
    )
    harness.container.state.save_run(
        intake, "run.stage_changed", {"status": "running", "stage": "intake"}
    )
    stored = harness.container.state.get_run(run.run_id)
    events = harness.container.state.list_events(run.run_id)
    assert stored.stage is WorkflowStage.INTAKE
    assert [event.sequence for event in events] == [1, 2]
    assert events[-1].payload["stage"] == "intake"


def test_foreign_keys_are_enabled(harness: FleetHarness) -> None:
    with (
        harness.container.state._connect() as connection,
        pytest.raises(sqlite3.IntegrityError),
    ):
        connection.execute(
            "INSERT INTO runs(run_id, project_id, status, stage, data_json) VALUES (?, ?, ?, ?, ?)",
            ("run_00000000000000000000000000000099", "missing", "created", None, "{}"),
        )
