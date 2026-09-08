"""Durable plan decisions use exact SQLite records, never mock approval state."""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from conftest import FleetHarness
from plan_review_fixtures import PlanReviewHarness, make_plan_review

from agent_fleet.adapters.persistence.plan_review import SqlitePlanReviewStore
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.ids import IdPrefix
from agent_fleet.domain.model_profiles import ModelProfile, ProjectModelSelection
from agent_fleet.domain.models import (
    LeaseKind,
    LeaseStatus,
    ResourceLease,
    RunStatus,
    RuntimeConfiguration,
    WorkflowStage,
)


@pytest.fixture
def plan_review(harness: FleetHarness) -> PlanReviewHarness:
    return make_plan_review(harness)


def test_decisions_reopen_and_consume_once_atomically(plan_review: PlanReviewHarness) -> None:
    h = plan_review
    c = h.fleet.container
    pending = h.service.create(h.scoped)
    paused = h.run
    assert (paused.status, paused.stage) == (RunStatus.PAUSED_FOR_PLAN, WorkflowStage.SCOPING)
    assert SqlitePlanReviewStore(c.state).get(paused) == pending
    assert not c.state.list_leases(paused.run_id)
    approved = h.store.approve(paused, expected_sha256=pending.checkpoint_sha256, actor="user")
    assert h.run == paused  # Approval itself does not advance execution or manufacture grants.
    assert approved.revision == 2
    assert approved.binding_sha256 == pending.binding_sha256
    assert approved.checkpoint_sha256 != pending.checkpoint_sha256
    resumed = h.store.consume(paused, expected_sha256=approved.checkpoint_sha256)
    assert (resumed.status, resumed.stage) == (RunStatus.RUNNING, WorkflowStage.SCOPING)
    consumed = SqlitePlanReviewStore(c.state).get(resumed)
    assert consumed.revision == 3 and consumed.status == "consumed"
    assert consumed.previous_sha256 == approved.checkpoint_sha256
    with pytest.raises(FleetError) as repeated:
        h.store.consume(paused, expected_sha256=approved.checkpoint_sha256)
    assert repeated.value.code is ErrorCode.APPROVAL_INVALID
    with sqlite3.connect(c.state.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM plan_review_versions").fetchone()[0] == 3
        assert connection.execute("SELECT COUNT(*) FROM capability_grants").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM fleet_graphs").fetchone()[0] == 0
    assert [
        event.event_type
        for event in c.state.list_events(resumed.run_id)
        if event.event_type.startswith("plan_review.")
    ] == ["plan_review.pending", "plan_review.approved", "plan_review.consumed"]


@pytest.mark.parametrize("operation", ["approve", "consume"])
def test_concurrent_decision_has_one_winner(plan_review: PlanReviewHarness, operation: str) -> None:
    h = plan_review
    checkpoint = h.service.create(h.scoped)
    if operation == "consume":
        checkpoint = h.service.approve(h.run, checkpoint.checkpoint_sha256)
    paused = h.run
    barrier = Barrier(2)

    def claim() -> str:
        store = SqlitePlanReviewStore(h.fleet.container.state)
        barrier.wait(timeout=10)
        try:
            if operation == "approve":
                store.approve(paused, expected_sha256=checkpoint.checkpoint_sha256, actor="user")
            else:
                store.consume(paused, expected_sha256=checkpoint.checkpoint_sha256)
            return "won"
        except FleetError as error:
            return error.code.value

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: claim(), range(2)))
    assert sorted(results) == ["APPROVAL_INVALID", "won"]
    assert h.store.get(h.run).revision == (2 if operation == "approve" else 3)


@pytest.mark.parametrize("operation", ["create", "approve", "consume"])
def test_failure_rolls_back_run_journal_and_event(
    plan_review: PlanReviewHarness, operation: str
) -> None:
    h = plan_review
    checkpoint = None
    if operation != "create":
        checkpoint = h.service.create(h.scoped)
    if operation == "consume":
        assert checkpoint is not None
        checkpoint = h.service.approve(h.run, checkpoint.checkpoint_sha256)
    before = h.run
    state = h.fleet.container.state
    events = tuple(state.list_events(before.run_id))
    with sqlite3.connect(state.database_path) as connection:
        connection.execute(
            "CREATE TRIGGER reject_plan BEFORE INSERT ON plan_review_versions "
            "BEGIN SELECT RAISE(ABORT, 'fixture transaction fault'); END"
        )
    with pytest.raises(FleetError) as failure:
        if operation == "create":
            h.service.create(before)
        elif operation == "approve":
            assert checkpoint is not None
            h.service.approve(before, checkpoint.checkpoint_sha256)
        else:
            assert checkpoint is not None
            h.service.consume(before, checkpoint.checkpoint_sha256)
    assert failure.value.code is ErrorCode.STATE_UNAVAILABLE
    assert h.run == before
    assert tuple(state.list_events(before.run_id)) == events
    if checkpoint is not None:
        assert h.store.get(before) == checkpoint


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE plan_review_versions SET checkpoint_sha256='" + "0" * 64 + "'",
        "UPDATE plan_review_versions SET status='consumed'",
        "UPDATE plan_review_versions SET data_json='{}'",
        "DELETE FROM plan_review_heads",
        "DELETE FROM plan_review_versions",
        "DELETE FROM run_events WHERE event_type='plan_review.pending'",
        "UPDATE run_events SET data_json='{}' WHERE event_type='plan_review.pending'",
    ],
)
def test_corrupt_or_missing_checkpoint_fails_closed(
    plan_review: PlanReviewHarness, sql: str
) -> None:
    h = plan_review
    h.service.create(h.scoped)
    with sqlite3.connect(h.fleet.container.state.database_path) as connection:
        connection.execute(sql)
    with pytest.raises(FleetError) as error:
        h.store.get(h.run)
    assert error.value.code is ErrorCode.RECOVERY_REQUIRED


def test_rolled_back_head_and_missing_consumed_version_are_not_replayable(
    plan_review: PlanReviewHarness,
) -> None:
    h = plan_review
    pending = h.service.create(h.scoped)
    approved = h.service.approve(h.run, pending.checkpoint_sha256)
    h.service.consume(h.run, approved.checkpoint_sha256)
    with sqlite3.connect(h.fleet.container.state.database_path) as connection:
        connection.execute("DELETE FROM plan_review_versions WHERE revision=3")
        connection.execute("UPDATE plan_review_heads SET revision=2")
    with pytest.raises(FleetError) as error:
        h.store.get(h.run)
    assert error.value.code is ErrorCode.RECOVERY_REQUIRED


def test_migration10_preserves_all_existing_model_and_run_bytes(
    plan_review: PlanReviewHarness,
) -> None:
    h = plan_review
    state = h.fleet.container.state
    service = h.fleet.container.model_profiles
    project = state.get_project(h.run.project_id)
    service.store.save_profile(
        ModelProfile(name="fixture", revision=1, configuration=RuntimeConfiguration()),
        expected_revision=0,
    )
    service.store.save_selection(
        ProjectModelSelection(
            project_id=project.project_id,
            repository_identity=project.identity_hash,
            revision=1,
            default_profile="fixture",
            permitted_profiles=("fixture",),
        ),
        expected_revision=0,
    )
    bindings = service.resolve(
        project,
        root_run_id=h.run.run_id,
        roles=("cos",),
        legacy_configuration=RuntimeConfiguration(),
    )
    service.save_bindings(bindings)
    tables = (
        "runs",
        "projects",
        "run_model_bindings",
        "model_profile_heads",
        "model_profile_versions",
        "model_configuration_audit",
        "project_model_selection_heads",
        "project_model_selection_versions",
    )
    with sqlite3.connect(state.database_path) as connection:
        expected = {
            table: connection.execute(f"SELECT * FROM {table}").fetchall() for table in tables
        }
        assert all(expected.values())
        connection.execute("DROP TABLE plan_review_heads")
        connection.execute("DROP TABLE plan_review_versions")
        connection.execute("DELETE FROM schema_migrations WHERE version=10")
    assert state.migrate() == 10
    with sqlite3.connect(state.database_path) as connection:
        actual = {
            table: connection.execute(f"SELECT * FROM {table}").fetchall() for table in tables
        }
        assert actual == expected
    assert service.store.get_bindings(project.project_id, h.run.run_id) == bindings


def test_required_marker_missing_decision_and_legacy_false_do_not_fallback(
    plan_review: PlanReviewHarness,
) -> None:
    h = plan_review
    with pytest.raises(FleetError) as missing:
        h.service.inspect(h.scoped)
    assert missing.value.code is ErrorCode.RECOVERY_REQUIRED
    with pytest.raises(FleetError):
        h.store.get(h.scoped.model_copy(update={"plan_review_required": False}))


@pytest.mark.parametrize("operation", ["create", "consume"])
def test_existing_resource_authority_prevents_planning_handoff(
    plan_review: PlanReviewHarness,
    operation: str,
) -> None:
    h = plan_review
    approved = None
    if operation == "consume":
        pending = h.service.create(h.scoped)
        approved = h.service.approve(h.run, pending.checkpoint_sha256)
    state = h.fleet.container.state
    now = state.clock.now()
    lease = ResourceLease(
        lease_id=state.ids.new(IdPrefix.LEASE),
        run_id=h.run.run_id,
        kind=LeaseKind.WORKTREE,
        resource_id=state.ids.new(IdPrefix.WORKSPACE),
        status=LeaseStatus.CREATING,
        created_at=now,
        updated_at=now,
    )
    state.save_lease(lease)
    before = h.run
    with pytest.raises(FleetError) as error:
        if operation == "create":
            h.service.create(before)
        else:
            assert approved is not None
            h.service.consume(before, approved.checkpoint_sha256)
    assert error.value.code is ErrorCode.RECOVERY_REQUIRED
    assert h.run == before and list(state.list_leases(before.run_id)) == [lease]
