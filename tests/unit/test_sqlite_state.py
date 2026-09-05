from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path

import pytest
from conftest import FleetHarness

from agent_fleet.adapters.persistence.sqlite import SUPPORTED_SCHEMA_VERSION, SqliteStateStore
from agent_fleet.adapters.system import SystemClock, UuidIdGenerator
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.ids import IdPrefix
from agent_fleet.domain.models import (
    LeaseKind,
    LeaseStatus,
    Project,
    ResourceLease,
    Run,
    RunStatus,
    SandboxCapabilities,
    SandboxHandle,
    SandboxSecurityLevel,
    WorkflowStage,
)
from agent_fleet.domain.security import Redactor, canonical_json_hash, status_fingerprint


def test_empty_migration_is_idempotent_and_reopens(tmp_path: Path) -> None:
    path = tmp_path / "state.db"
    first = SqliteStateStore(path, SystemClock(), UuidIdGenerator(), Redactor())
    assert first.migrate() == SUPPORTED_SCHEMA_VERSION
    reopened = SqliteStateStore(path, SystemClock(), UuidIdGenerator(), Redactor())
    assert reopened.migrate() == SUPPORTED_SCHEMA_VERSION
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (0,)
        assert connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall() == [(1,), (2,), (3,)]


def test_v1_migration_preserves_agents_and_allows_only_unbound_cos(tmp_path: Path) -> None:
    path = tmp_path / "state.db"
    migration_v1 = (
        resources.files("agent_fleet.adapters.persistence.migrations")
        .joinpath("0001.sql")
        .read_text(encoding="utf-8")
    )
    with sqlite3.connect(path) as connection:
        connection.executescript(
            "CREATE TABLE schema_migrations "
            "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);\n" + migration_v1
        )
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (1, ?)",
            (datetime.now(UTC).isoformat(),),
        )
        connection.execute(
            "INSERT INTO projects(project_id, canonical_root, data_json) VALUES (?, ?, ?)",
            ("prj_legacy", "/legacy", "{}"),
        )
        connection.execute(
            "INSERT INTO runs(run_id, project_id, status, stage, data_json) VALUES (?, ?, ?, ?, ?)",
            ("run_legacy", "prj_legacy", "running", "scoping", "{}"),
        )
        connection.execute(
            "INSERT INTO tasks(task_id, run_id, data_json) VALUES (?, ?, ?)",
            ("task_legacy", "run_legacy", "{}"),
        )
        connection.execute(
            "INSERT INTO agent_instances(agent_instance_id, run_id, task_id, role, data_json) "
            "VALUES (?, ?, ?, ?, ?)",
            ("agent_legacy", "run_legacy", "task_legacy", "engineer", "{}"),
        )

    state = SqliteStateStore(path, SystemClock(), UuidIdGenerator(), Redactor())
    assert state.migrate() == SUPPORTED_SCHEMA_VERSION

    with state._connect() as connection:
        row = connection.execute(
            "SELECT run_id, task_id, role, data_json FROM agent_instances "
            "WHERE agent_instance_id = 'agent_legacy'"
        ).fetchone()
        assert tuple(row) == ("run_legacy", "task_legacy", "engineer", "{}")
        connection.execute(
            "INSERT INTO agent_instances(agent_instance_id, run_id, task_id, role, data_json) "
            "VALUES (?, ?, NULL, ?, ?)",
            ("agent_cos", "run_legacy", "cos", "{}"),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO agent_instances"
                "(agent_instance_id, run_id, task_id, role, data_json) "
                "VALUES (?, ?, NULL, ?, ?)",
                ("agent_invalid", "run_legacy", "engineer", "{}"),
            )


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


def test_terminal_lease_finalization_is_exactly_idempotent_and_hash_audited(
    harness: FleetHarness,
) -> None:
    project = harness.container.state.get_project_by_root(str(harness.repository_root.resolve()))
    assert project is not None
    now = datetime.now(UTC)
    run = Run(
        run_id=harness.container.state.ids.new(IdPrefix.RUN),
        project_id=project.project_id,
        correlation_id=harness.container.state.ids.new(IdPrefix.CORRELATION),
        goal="terminal lease transaction",
        base_revision=harness.git("rev-parse", "HEAD").strip(),
        target_status_fingerprint=status_fingerprint(""),
        created_at=now,
        updated_at=now,
    )
    harness.container.state.create_run(run)
    lease = ResourceLease(
        lease_id=harness.container.state.ids.new(IdPrefix.LEASE),
        run_id=run.run_id,
        kind=LeaseKind.EXECUTION,
        resource_id=harness.container.state.ids.new(IdPrefix.EXECUTION),
        status=LeaseStatus.ACTIVE,
        created_at=now,
        updated_at=now,
        metadata={"phase": "active"},
    )
    harness.container.state.save_lease(lease)
    terminal_metadata = {
        "schema_version": 3,
        "terminal_result": {"exit_code": 0, "timed_out": False},
    }

    finalized = harness.container.state.finalize_lease(
        lease.lease_id,
        LeaseStatus.RELEASED.value,
        terminal_metadata,
    )
    event_count = len(harness.container.state.list_events(run.run_id))
    repeated = harness.container.state.finalize_lease(
        lease.lease_id,
        LeaseStatus.RELEASED.value,
        terminal_metadata,
    )

    assert finalized == repeated
    assert repeated.status is LeaseStatus.RELEASED
    assert repeated.metadata == terminal_metadata
    assert len(harness.container.state.list_events(run.run_id)) == event_count
    assert repeated not in harness.container.state.outstanding_leases(run.run_id)
    terminal_events = [
        event
        for event in harness.container.state.list_events(run.run_id)
        if event.event_type == "sandbox.exec_finished"
    ]
    assert len(terminal_events) == 1
    assert terminal_events[0].payload["terminal_metadata_sha256"] == canonical_json_hash(
        terminal_metadata
    )

    with pytest.raises(FleetError) as captured:
        harness.container.state.finalize_lease(
            lease.lease_id,
            LeaseStatus.RELEASED.value,
            {**terminal_metadata, "terminal_result": {"exit_code": 1, "timed_out": False}},
        )

    assert captured.value.code is ErrorCode.RECOVERY_REQUIRED
    assert harness.container.state.get_lease(lease.lease_id) == finalized


def test_execution_dispatch_checkpoint_is_atomic_one_way_and_identity_bound(
    harness: FleetHarness,
) -> None:
    state = harness.container.state
    project = state.get_project_by_root(str(harness.repository_root.resolve()))
    assert project is not None
    now = datetime.now(UTC)
    run = Run(
        run_id=state.ids.new(IdPrefix.RUN),
        project_id=project.project_id,
        correlation_id=state.ids.new(IdPrefix.CORRELATION),
        goal="dispatch checkpoint",
        base_revision=harness.git("rev-parse", "HEAD").strip(),
        target_status_fingerprint=status_fingerprint(""),
        created_at=now,
        updated_at=now,
    )
    state.create_run(run)
    capabilities = SandboxCapabilities(
        provider="docker",
        security_level=SandboxSecurityLevel.ISOLATED,
        isolation_enforced=True,
        executes_code=True,
        supported_network_modes=("none",),
        supports_resource_limits=True,
        supports_recovery=True,
        supports_non_root=True,
        supports_read_only_root=True,
        supports_no_new_privileges=True,
        supports_capability_drop=True,
    )
    sandbox = SandboxHandle(
        sandbox_id=state.ids.new(IdPrefix.SANDBOX),
        run_id=run.run_id,
        project_id=project.project_id,
        workspace_host_path=str(harness.repository_root),
        provider="docker",
        capabilities=capabilities,
        configuration_hash="a" * 64,
        image_identity="sha256:" + "b" * 64,
        daemon_identity="c" * 64,
        recovery_scope_id="d" * 32,
    )
    lease = ResourceLease(
        lease_id=state.ids.new(IdPrefix.LEASE),
        run_id=run.run_id,
        kind=LeaseKind.EXECUTION,
        resource_id=state.ids.new(IdPrefix.EXECUTION),
        status=LeaseStatus.CREATING,
        created_at=now,
        updated_at=now,
        metadata={
            "schema_version": 2,
            "provider": "docker",
            "intent_id": state.ids.new(IdPrefix.INTENT),
            "project_id": project.project_id,
            "task_id": state.ids.new(IdPrefix.TASK),
            "agent_instance_id": state.ids.new(IdPrefix.AGENT),
            "stage": WorkflowStage.VERIFYING.value,
            "creation_dispatched": False,
            "sandbox_handle": sandbox.model_dump(mode="json"),
        },
    )
    state.save_lease(lease)

    dispatched = state.mark_execution_creation_dispatched(lease.lease_id)

    assert dispatched.status is LeaseStatus.CREATING
    assert dispatched.metadata["creation_dispatched"] is True
    assert state.get_lease(lease.lease_id) == dispatched
    dispatch_events = [
        event
        for event in state.list_events(run.run_id)
        if event.event_type == "sandbox.exec_dispatch_recorded"
    ]
    assert len(dispatch_events) == 1
    with pytest.raises(FleetError) as captured:
        state.mark_execution_creation_dispatched(lease.lease_id)
    assert captured.value.code is ErrorCode.RECOVERY_REQUIRED
    assert (
        len(
            [
                event
                for event in state.list_events(run.run_id)
                if event.event_type == "sandbox.exec_dispatch_recorded"
            ]
        )
        == 1
    )
