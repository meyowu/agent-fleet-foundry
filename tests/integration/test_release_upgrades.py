"""Real lifecycle rows projected to prior schema; never downgrade the original state."""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
from pathlib import Path

import pytest
from conftest import FleetHarness
from evolution_fixtures import deliver_proposal

import agent_fleet.adapters.persistence.sqlite as sqlite_module
from agent_fleet.application.conversations import ChatExecutionOptions
from agent_fleet.bootstrap import build_container
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import FakeScenario, RunStatus

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]
_ORGANIZATION_TABLES = (
    "organization_run_admissions",
    "organization_operations",
    "organization_proposals",
    "organization_heads",
    "organization_versions",
    "organization_trees",
    "organization_events",
)


def _rows(database: Path) -> dict[str, list[tuple[object, ...]]]:
    with sqlite3.connect(database) as connection:
        tables = [
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            if not row[0].startswith("sqlite_") and row[0] != "schema_migrations"
        ]
        assert all(name.replace("_", "").isalnum() for name in tables)
        return {
            name: sorted(
                (tuple(row) for row in connection.execute(f'SELECT * FROM "{name}"')), key=repr
            )
            for name in tables
        }


async def test_schema7_upgrade_preserves_real_paused_chat_budget_graph_and_lease_rows(
    harness: FleetHarness,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = harness.container
    graph_run = await harness.start(FakeScenario.PARALLEL_ENGINEERS)
    assert graph_run.status is RunStatus.READY_FOR_REVIEW
    view = container.conversations.select(harness.repository_root)
    conversation_id = str(view["conversation_id"])
    paused = await container.conversations.submit(
        conversation_id,
        message="Fix the canary behavior",
        submission_id="upgrade-paused-chat",
        options=ChatExecutionOptions(fake_scenario=FakeScenario.APPROVAL),
    )
    run_id = str(paused["run_id"])
    run = container.state.get_run(run_id)
    assert run.status is RunStatus.PAUSED_FOR_APPROVAL and run.pending_approval_id is not None
    binding = container.conversation_store.binding_for_run(run_id)
    assert binding is not None
    turn = container.conversation_store.get_turn(run.project_id, binding.turn_id)
    claim = container.conversation_store.claim_resume(run_id, expected_revision=turn.revision)
    before_original = _rows(container.state.database_path)
    for table in (
        "approvals",
        "resource_leases",
        "runtime_budget_owners",
        "runtime_attempts",
        "conversations",
        "conversation_turns",
        "conversation_turn_claims",
        "fleet_graphs",
        "fleet_graph_nodes",
        "fleet_graph_driver_claims",
    ):
        assert before_original[table], table
    copy_root = tmp_path / "previous-schema-copy"
    copy_root.mkdir()
    shutil.copytree(harness.state_root / "artifacts", copy_root / "artifacts")
    database = copy_root / "state.db"
    with (
        sqlite3.connect(container.state.database_path) as original,
        sqlite3.connect(database) as copy,
    ):
        original.backup(copy)
        # This isolated fixture models schema7; it is not an older-binary execution claim.
        copy.execute("PRAGMA foreign_keys=OFF")
        for table in _ORGANIZATION_TABLES:
            copy.execute(f"DROP TABLE {table}")
        copy.execute("DELETE FROM schema_migrations WHERE version=8")
        assert copy.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 7
    expected = _rows(database)
    try:
        upgraded = build_container(copy_root)
        actual = _rows(database)
        assert {name: actual[name] for name in expected} == expected
        assert all(actual[name] == [] for name in _ORGANIZATION_TABLES)
        assert upgraded.state.get_run(run_id) == run
        assert upgraded.state.get_approval(run.pending_approval_id) == container.state.get_approval(
            run.pending_approval_id
        )
        assert upgraded.budgets.snapshot(run_id) == container.budgets.snapshot(run_id)
        assert upgraded.graphs.get(graph_run.run_id) == container.graphs.get(graph_run.run_id)
        assert upgraded.conversation_store.assert_claim(claim).active_claim_id == claim.claim_id
        with pytest.raises(FleetError):
            upgraded.conversation_store.claim_resume(run_id, expected_revision=turn.revision + 1)
        assert _rows(database) == actual  # No timeout takeover, replay, or budget reset.
        for metadata in upgraded.state.list_artifacts(run_id):
            content = upgraded.artifacts.read_text(metadata.artifact_id).encode()
            assert hashlib.sha256(content).hexdigest() == metadata.sha256
        with monkeypatch.context() as older:
            older.setattr(sqlite_module, "SUPPORTED_SCHEMA_VERSION", 7)
            with pytest.raises(FleetError) as captured:
                upgraded.state.migrate()
            assert captured.value.code is ErrorCode.STATE_SCHEMA_INCOMPATIBLE
        assert _rows(database) == actual
        assert _rows(container.state.database_path) == before_original
    finally:
        await container.recovery.recover_run(run_id)
    assert not container.state.outstanding_leases()


async def test_current_schema_reopen_preserves_published_organization_history(
    tmp_path: Path,
) -> None:
    container, _, run, _, _ = await deliver_proposal(tmp_path)
    proposal = container.organization.store.list_proposals(run.project_id)[0]
    published = container.organization.apply(proposal.patch.fleet_patch_id)
    assert published.version is not None and published.version.version == 1
    before = _rows(container.state.database_path)
    reopened = build_container(container.state_root)
    assert _rows(reopened.state.database_path) == before
    assert reopened.organization.store.get_head(
        run.project_id
    ) == container.organization.store.get_head(run.project_id)
    assert reopened.organization.apply(proposal.patch.fleet_patch_id).version == published.version
    assert _rows(reopened.state.database_path) == before
