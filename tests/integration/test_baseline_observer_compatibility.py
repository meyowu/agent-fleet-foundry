"""Schema13 baseline rows remain outside the existing Run observer's evidence."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from business_baseline_fixtures import baseline_fixture
from conftest import FleetHarness
from test_evaluation_capture_workflow import drained, instrumented_child
from test_evaluation_observation_workflow import attempt_id, failed, service
from test_evaluation_observation_workflow import (
    observation_children_are_reaped as observation_children_are_reaped,
)

if TYPE_CHECKING:
    from test_baseline_migrations import BASELINE_TABLES
else:
    from contract.test_baseline_migrations import BASELINE_TABLES

from agent_fleet.adapters.persistence import evaluation_capture as capture
from agent_fleet.adapters.persistence.baseline import SqliteBaselineStore
from agent_fleet.domain.errors import ErrorCode, FleetError

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_migrated_v12_run_observation_and_quiescent_baseline_rows_are_independent(
    harness: FleetHarness,
    tmp_path: Path,
) -> None:
    fixture, run = await failed(harness)
    selected = attempt_id(harness)
    original = service(harness).inspect_attempt(fixture.manifest.campaign_id, selected)
    assert original.state == "failed"
    state = harness.container.state
    with sqlite3.connect(state.database_path) as connection:
        retained_run = connection.execute(
            "SELECT * FROM runs WHERE run_id=?", (run.run_id,)
        ).fetchone()
        for table in BASELINE_TABLES:
            connection.execute(f"DROP TABLE {table}")
        connection.execute("DELETE FROM schema_migrations WHERE version=13")
    # The new fixed child does not silently migrate a source DB.
    assert (
        service(harness).inspect_attempt(fixture.manifest.campaign_id, selected).state == "corrupt"
    )
    assert state.migrate() == 13
    assert service(harness).inspect_attempt(fixture.manifest.campaign_id, selected) == original
    baseline = baseline_fixture(tmp_path / "unrelated-baseline-fixture")
    state.save_project(baseline.project)
    store = SqliteBaselineStore(state, installation_id=baseline.review.installation_id)
    store.create_review(baseline.review)
    store.authorize(baseline.review.review_id, baseline.review.digest)
    assert store.show(baseline.review.review_id).execution.owner_claim_id is None
    assert service(harness).inspect_attempt(fixture.manifest.campaign_id, selected) == original
    with sqlite3.connect(state.database_path) as connection:
        assert (
            connection.execute("SELECT * FROM runs WHERE run_id=?", (run.run_id,)).fetchone()
            == retained_run
        )
    with pytest.raises(FleetError) as denied:
        service(harness).record_final_outcome(
            fixture.manifest.campaign_id, selected, original.sha256
        )
    assert denied.value.code is ErrorCode.STATE_UNAVAILABLE


async def test_concurrent_unrelated_baseline_write_rejects_capture_without_widening_semantics(
    harness: FleetHarness,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture, _ = await failed(harness)
    selected = attempt_id(harness)
    baseline = baseline_fixture(tmp_path / "unrelated-baseline-fixture")
    state = harness.container.state
    state.save_project(baseline.project)
    store = SqliteBaselineStore(state, installation_id=baseline.review.installation_id)
    store.create_review(baseline.review)
    original = service(harness).inspect_attempt(fixture.manifest.campaign_id, selected)
    assert original.state == "failed"
    # A deterministic cooperating writer runs between the two actual child
    # descriptor passes. Even an unrelated row invalidates this capture.
    code = f"""
original = capture.DescriptorCapture.second
def write_between_passes(self):
    from agent_fleet.adapters.persistence.baseline import SqliteBaselineStore
    from agent_fleet.adapters.persistence.sqlite import SqliteStateStore
    from agent_fleet.adapters.system import SystemClock, UuidIdGenerator
    from agent_fleet.domain.security import Redactor
    state = SqliteStateStore(
        Path({str(state.database_path)!r}), SystemClock(), UuidIdGenerator(), Redactor()
    )
    store = SqliteBaselineStore(state, installation_id={baseline.review.installation_id!r})
    store.authorize({baseline.review.review_id!r}, {baseline.review.digest!r})
    return original(self)
capture.DescriptorCapture.second = write_between_passes
"""
    with monkeypatch.context() as scoped:
        children = instrumented_child(harness, scoped, code)
        observed = service(harness).inspect_attempt(fixture.manifest.campaign_id, selected)
    assert observed.state == "corrupt", observed
    drained(children)
    assert service(harness).inspect_attempt(fixture.manifest.campaign_id, selected) == original
    with sqlite3.connect(state.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM baseline_authorizations").fetchone()[0] == 1
    assert capture.MAX_FILE == 32 * 1024 * 1024
    assert capture.MAX_READ == 128 * 1024 * 1024
