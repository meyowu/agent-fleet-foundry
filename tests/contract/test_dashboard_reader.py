"""Read-only observation uses actual SQLite records and per-run durable cursors."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from conftest import FleetHarness

from agent_fleet.adapters.persistence.dashboard import SqliteDashboardReader
from agent_fleet.domain.errors import FleetError
from agent_fleet.domain.models import FakeScenario


def test_missing_state_is_not_created(tmp_path: Path) -> None:
    path = tmp_path / "missing" / "state.db"
    with pytest.raises(FleetError):
        SqliteDashboardReader(path).catalog("prj_" + "1" * 32)
    assert not path.parent.exists()


@pytest.mark.asyncio
async def test_real_graph_snapshot_replay_resync_and_read_only(harness: FleetHarness) -> None:
    run = await harness.start(FakeScenario.PARALLEL_ENGINEERS)
    reader = SqliteDashboardReader(harness.state_root / "state.db")
    with sqlite3.connect(reader.database_path) as connection:
        before = tuple(connection.iterdump())
    first = reader.frame(run.project_id, run.run_id)
    assert len(first.runs) == 3  # Two child writers; joined verification belongs to the root.
    assert {agent.role for agent in first.agents} >= {"cos", "engineer", "verifier"}
    assert first.events
    for event in first.events:
        assert event.run_id is not None and event.sequence is not None
        assert event.sequence <= first.high_watermarks[event.run_id]
    quiet = reader.frame(run.project_id, run.run_id, cursors=first.cursors)
    assert quiet.events == () and quiet.cursors == first.cursors
    assert not quiet.resync
    replay = reader.frame(run.project_id, run.run_id, cursors=dict.fromkeys(first.cursors, 0))
    for run_id in first.cursors:
        events = [item.sequence for item in replay.events if item.run_id == run_id]
        assert events == list(range(1, len(events) + 1))
    future = reader.frame(
        run.project_id,
        run.run_id,
        cursors={key: value + 1 for key, value in first.high_watermarks.items()},
    )
    assert future.resync and future.cursors == first.cursors
    foreign = reader.frame(run.project_id, run.run_id, cursors={"run_" + "f" * 32: 1})
    assert foreign.resync
    catalog = reader.catalog(run.project_id)
    assert [item.run_id for item in catalog.runs] == [run.run_id]
    with sqlite3.connect(reader.database_path) as connection:
        assert tuple(connection.iterdump()) == before


@pytest.mark.asyncio
async def test_foreign_project_child_selection_corrupt_rows_and_cursor_are_denied(
    harness: FleetHarness,
) -> None:
    run = await harness.start(FakeScenario.PARALLEL_ENGINEERS)
    reader = SqliteDashboardReader(harness.state_root / "state.db")
    frame = reader.frame(run.project_id, run.run_id)
    with pytest.raises(FleetError):
        reader.frame("prj_" + "f" * 32, run.run_id)
    with pytest.raises(FleetError):
        reader.frame(run.project_id, frame.runs[1].run_id)
    with pytest.raises(FleetError):
        reader.frame(run.project_id, run.run_id, cursors={run.run_id: -1})
    with sqlite3.connect(reader.database_path) as connection:
        connection.execute("UPDATE runs SET status='failed' WHERE run_id=?", (run.run_id,))
    with pytest.raises(FleetError):
        reader.frame(run.project_id, run.run_id)


@pytest.mark.asyncio
async def test_missing_sequence_is_not_silently_advanced(harness: FleetHarness) -> None:
    run = await harness.start()
    reader = SqliteDashboardReader(harness.state_root / "state.db")
    with sqlite3.connect(reader.database_path) as connection:
        connection.execute("DELETE FROM run_events WHERE run_id=? AND sequence=2", (run.run_id,))
    with pytest.raises(FleetError):
        reader.frame(run.project_id, run.run_id, cursors={run.run_id: 0})
