"""Bounded local scale smoke, not a throughput SLA or an enterprise load claim."""

from __future__ import annotations

import hashlib
import json
import time
import tracemalloc

import pytest
from conftest import FleetHarness

from agent_fleet.bootstrap import build_container
from agent_fleet.domain.ids import IdPrefix
from agent_fleet.domain.models import ArtifactKind, FakeScenario, FleetEvent


@pytest.mark.integration
async def test_event_artifact_scale_keeps_order_hashes_and_bounded_status(
    harness: FleetHarness,
) -> None:
    container = harness.container
    run = await harness.start(FakeScenario.DIRECT)
    baseline = list(container.state.list_events(run.run_id))
    initial_sequence = baseline[-1].sequence
    assert initial_sequence is not None
    tracemalloc.start()
    timings: dict[str, float] = {}
    try:
        start = time.perf_counter()
        for index in range(1000):
            container.state.append_event(
                FleetEvent(
                    event_id=container.state.ids.new(IdPrefix.EVENT),
                    event_type="scale.fixture_observation",
                    occurred_at=container.state.clock.now(),
                    project_id=run.project_id,
                    run_id=run.run_id,
                    correlation_id=run.correlation_id,
                    payload={"index": index, "note": "x" * 128},
                )
            )
        timings["append_1000_events_seconds"] = time.perf_counter() - start
        start = time.perf_counter()
        identities: dict[str, str] = {}
        for index in range(256):
            content = f"{index:08d}\n" + "x" * 4087
            artifact = container.artifacts.create_text(
                kind=ArtifactKind.COS_RESPONSE,
                project_id=run.project_id,
                run_id=run.run_id,
                content=content,
                producer="release-scale-fixture",
            )
            assert artifact.byte_size == 4096
            identities[artifact.artifact_id] = hashlib.sha256(content.encode()).hexdigest()
        timings["write_256_artifacts_seconds"] = time.perf_counter() - start
        reopened = build_container(harness.state_root)
        start = time.perf_counter()
        cursor = initial_sequence
        observed: list[int] = []
        while page := reopened.state.list_events_after(run.run_id, after_sequence=cursor, limit=64):
            for event in page:
                assert event.sequence == cursor + 1
                cursor = event.sequence
                if event.event_type == "scale.fixture_observation":
                    observed_index = event.payload["index"]
                    assert isinstance(observed_index, int)
                    observed.append(observed_index)
                else:
                    assert event.event_type == "artifact.created"
        assert observed == list(range(1000))
        assert cursor == initial_sequence + 1000 + 256
        timings["page_1000_events_seconds"] = time.perf_counter() - start
        start = time.perf_counter()
        for identity, digest in identities.items():
            assert (
                hashlib.sha256(reopened.artifacts.read_text(identity).encode()).hexdigest()
                == digest
            )
        timings["read_256_artifacts_seconds"] = time.perf_counter() - start
        start = time.perf_counter()
        assert reopened.inspection.status(run.run_id)["status"] == run.status.value
        timings["status_seconds"] = time.perf_counter() - start
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    database = container.state.database_path
    database_bytes = sum(
        path.stat().st_size
        for path in (
            database,
            database.with_name(database.name + "-wal"),
            database.with_name(database.name + "-shm"),
        )
        if path.exists()
    )
    metrics = {
        "event_count": 1000,
        "artifact_count": 256,
        "artifact_content_bytes": 256 * 4096,
        "database_and_wal_bytes": database_bytes,
        "peak_traced_bytes": peak,
        "timings": timings,
    }
    (harness.root / "scale-metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
    print(json.dumps(metrics, sort_keys=True))
    assert peak < 64 * 1024 * 1024
    assert database_bytes < 32 * 1024 * 1024
    assert all(value < 120 for value in timings.values())
    assert timings["status_seconds"] < 10
    assert not reopened.state.outstanding_leases()
