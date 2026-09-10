"""Real local controller processes race for a single permanent baseline owner."""

import multiprocessing
from multiprocessing.connection import Connection
from pathlib import Path

import pytest
from business_baseline_fixtures import baseline_fixture

from agent_fleet.adapters.persistence.baseline import SqliteBaselineStore
from agent_fleet.adapters.persistence.sqlite import SqliteStateStore
from agent_fleet.adapters.system import SystemClock, UuidIdGenerator
from agent_fleet.domain.baseline_resources import BaselineStoppedOwnerReview
from agent_fleet.domain.errors import FleetError
from agent_fleet.domain.security import Redactor


def _claim_child(
    database: str,
    installation: str,
    review: str,
    digest: str,
    authorization: str,
    signal: Connection,
) -> None:
    try:
        store = SqliteBaselineStore(
            SqliteStateStore(Path(database), SystemClock(), UuidIdGenerator(), Redactor()),
            installation_id=installation,
        )
        signal.send("ready")
        assert signal.recv() == "claim"
        try:
            store.claim_baseline(review, digest, authorization, 0)
        except FleetError:
            signal.send("refused")
        else:
            signal.send("claimed")
    finally:
        signal.close()


def test_two_processes_claim_once_and_stopped_owner_cleanup_never_dispatches(
    tmp_path: Path,
) -> None:
    h = baseline_fixture(tmp_path)
    authorization = h.store.authorize(h.review.review_id, h.review.digest)
    context = multiprocessing.get_context("spawn")
    pipes = [context.Pipe() for _ in range(2)]
    processes = [
        context.Process(
            target=_claim_child,
            args=(
                str(h.state.database_path),
                h.review.installation_id,
                h.review.review_id,
                h.review.digest,
                authorization.authorization_id,
                pair[1],
            ),
        )
        for pair in pipes
    ]
    try:
        for process, pair in zip(processes, pipes, strict=True):
            process.start()
            pair[1].close()
        for parent, _ in pipes:
            assert parent.poll(10), "owner readiness watchdog expired"
            assert parent.recv() == "ready"
        for parent, _ in pipes:
            parent.send("claim")
        results = []
        for parent, _ in pipes:
            assert parent.poll(10), "claim watchdog expired"
            results.append(parent.recv())
        assert sorted(results) == ["claimed", "refused"]
        for process in processes:
            process.join(5)
            assert process.exitcode == 0
        snapshot = h.store.baseline_resource_snapshot(h.review.baseline_id)
        assert snapshot.dispatch is None and snapshot.leases == ()
        assert snapshot.claim.controller_pid in {process.pid for process in processes}
        with pytest.raises(FleetError):
            h.store.begin_baseline_cleanup(snapshot.claim, snapshot)
        stopped = BaselineStoppedOwnerReview(
            owner=snapshot.claim.owner,
            owner_claim_sha256=snapshot.claim.digest,
            snapshot_sha256=snapshot.digest,
            controller_pid=snapshot.claim.controller_pid,
            installation_id=h.review.installation_id,
            state="absent",
            checked_at=h.state.clock.now(),
        )
        cleanup = h.store.claim_baseline_cleanup(snapshot, stopped)
        assert h.store.validate_cleanup(cleanup).execution.status == "cleaning"
        with pytest.raises(FleetError):
            h.store.claim_baseline(
                h.review.review_id, h.review.digest, authorization.authorization_id, 0
            )
        assert h.store.baseline_resource_snapshot(h.review.baseline_id).dispatch is None
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(5)
        for pair in pipes:
            for pipe in pair:
                pipe.close()
        for process in processes:
            if process.exitcode is not None:
                process.close()
