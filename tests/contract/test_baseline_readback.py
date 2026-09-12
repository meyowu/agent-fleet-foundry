"""Hash-consistent corruption is not a substitute for validating referenced facts."""

import sqlite3
from pathlib import Path

import pytest
from business_baseline_fixtures import BaselineFixture, baseline_fixture

from agent_fleet.domain.baseline import (
    BaselineCommandObservation,
    BaselineExecution,
    BaselineObservationRef,
    BaselineReport,
    baseline_id,
    canonical,
    freeze_snapshot,
)
from agent_fleet.domain.baseline_resources import (
    BaselineCleanupClaim,
    BaselineCleanupReceipt,
    BaselineCommandPayload,
    BaselineResourceLease,
    BaselineResourceSnapshot,
    BaselineSandboxPayload,
    BaselineStoppedOwnerReview,
)
from agent_fleet.domain.errors import FleetError
from agent_fleet.domain.models import SandboxCleanupResult


def _report(h: BaselineFixture) -> tuple[BaselineCleanupClaim, BaselineReport]:
    claim = h.claim()
    observation = h.dispatched_observation(claim)
    snapshot = h.store.baseline_resource_snapshot(h.review.baseline_id)
    ref = h.store.record_command_observation(
        claim, snapshot.execution.revision, observation.canonical_bytes()
    )
    cleanup = h.store.begin_baseline_cleanup(
        claim, h.store.baseline_resource_snapshot(h.review.baseline_id)
    )
    report = BaselineReport(
        baseline_id=h.review.baseline_id,
        project_id=h.review.project_id,
        review_id=h.review.review_id,
        review_sha256=h.review.digest,
        authorization_id=claim.authorization_id,
        claim_id=claim.claim_id,
        command_sha256=h.review.command.sha256,
        approved_source_sha256=h.review.approved_source_sha256,
        observation=ref,
        cleanup_scope_sha256=cleanup.scope_sha256,
        cleanup_receipt_sha256s=(),
        cleanup_complete=False,
        status="recovery_required",
        observed_exit_code=0,
        completed_at=h.state.clock.now(),
        proof_gaps=("cleanup_incomplete",),
    )
    return cleanup, report


def test_show_returns_only_validated_observation_after_capture(tmp_path: Path) -> None:
    h = baseline_fixture(tmp_path)
    planned = h.store.show(h.review.review_id)
    assert planned.report is None
    assert planned.observation is None
    claim = h.claim()
    observation = h.dispatched_observation(claim)
    snapshot = h.store.baseline_resource_snapshot(h.review.baseline_id)
    h.store.record_command_observation(
        claim, snapshot.execution.revision, observation.canonical_bytes()
    )
    captured = h.store.show(h.review.baseline_id)
    assert captured.report is None
    assert captured.observation == observation


def test_show_rejects_hash_consistent_observation_resource_substitution(tmp_path: Path) -> None:
    h = baseline_fixture(tmp_path)
    claim = h.claim()
    observation = h.dispatched_observation(claim)
    snapshot = h.store.baseline_resource_snapshot(h.review.baseline_id)
    h.store.record_command_observation(
        claim, snapshot.execution.revision, observation.canonical_bytes()
    )
    data = observation.model_dump(mode="json", by_alias=True)
    data["project_id"] = "prj_" + "9" * 32
    changed = BaselineCommandObservation.model_validate_json(canonical(data))
    with sqlite3.connect(h.state.database_path) as connection:
        connection.execute(
            "UPDATE baseline_command_observations "
            "SET record_id=?,record_sha256=?,payload=? WHERE baseline_id=?",
            (
                "bobs_" + changed.digest,
                changed.digest,
                changed.canonical_bytes(),
                h.review.baseline_id,
            ),
        )
    with pytest.raises(FleetError):
        h.store.show(h.review.baseline_id)


def test_show_rejects_report_whose_observation_was_removed(tmp_path: Path) -> None:
    h = baseline_fixture(tmp_path)
    cleanup, report = _report(h)
    snapshot = h.store.validate_cleanup(cleanup)
    h.store.publish_baseline_report(cleanup, snapshot.execution.revision, report.canonical_bytes())
    with sqlite3.connect(h.state.database_path) as connection:
        connection.execute(
            "DELETE FROM baseline_command_observations WHERE baseline_id=?",
            (h.review.baseline_id,),
        )
    with pytest.raises(FleetError):
        h.store.show(h.review.baseline_id)


@pytest.mark.parametrize(
    "mutation",
    ["exit_code", "cleanup_complete", "claim_id", "scope", "predecessor", "observation_ref"],
)
def test_readback_repeats_report_fact_validation(tmp_path: Path, mutation: str) -> None:
    h = baseline_fixture(tmp_path)
    cleanup, original = _report(h)
    snapshot = h.store.validate_cleanup(cleanup)
    h.store.publish_baseline_report(
        cleanup, snapshot.execution.revision, original.canonical_bytes()
    )
    good = h.store.show(h.review.baseline_id)
    data = original.model_dump(mode="json", by_alias=True)
    if mutation == "exit_code":
        data["observed_exit_code"] = 1
    elif mutation == "cleanup_complete":
        data.update(cleanup_complete=True, status="observed", proof_gaps=[])
    elif mutation == "claim_id":
        data["claim_id"] = baseline_id("bclaim")
    elif mutation == "scope":
        data["cleanup_scope_sha256"] = "0" * 64
    elif mutation == "predecessor":
        data["predecessor_report_sha256"] = original.digest
    else:
        assert original.observation is not None
        data["observation"] = BaselineObservationRef(
            observation_id="bobs_" + "0" * 64,
            baseline_id=original.observation.baseline_id,
            execution_id=original.observation.execution_id,
            record_sha256="0" * 64,
        ).model_dump(mode="json", by_alias=True)
    corrupted = BaselineReport.model_validate_json(canonical(data))
    execution = good.execution.model_dump(mode="json", by_alias=True)
    execution["current_report_sha256"] = corrupted.digest
    redirected = BaselineExecution.model_validate_json(canonical(execution))
    with sqlite3.connect(h.state.database_path) as connection:
        connection.execute(
            "INSERT INTO baseline_reports VALUES(?,?,?,?,?)",
            (
                "brpt_" + corrupted.digest,
                h.review.baseline_id,
                0,
                corrupted.digest,
                corrupted.canonical_bytes(),
            ),
        )
        connection.execute(
            "UPDATE baseline_executions SET record_sha256=?,payload=? WHERE baseline_id=?",
            (redirected.digest, redirected.canonical_bytes(), h.review.baseline_id),
        )
    with pytest.raises(FleetError):
        h.store.show(h.review.baseline_id)


def test_readback_repeats_exact_cleanup_native_identity(tmp_path: Path) -> None:
    h = baseline_fixture(tmp_path)
    cleanup, _ = _report(h)
    execution = next(item for item in cleanup.snapshot.leases if item.kind == "execution")
    now = h.state.clock.now()
    result = SandboxCleanupResult(
        provider="docker",
        resource_id="7" * 64,
        resources_found=1,
        resources_removed=1,
        reconciled=True,
        complete=True,
        completed_at=now,
    )
    receipt = BaselineCleanupReceipt(
        owner=cleanup.owner,
        lease_id=execution.lease_id,
        lease_sha256=execution.digest,
        cleanup_scope_sha256=cleanup.scope_sha256,
        kind="execution",
        complete=True,
        result=freeze_snapshot("cleanup-v1", result.model_dump(mode="json")),
        completed_at=now,
    )
    released = h.store.finalize_baseline_lease(
        cleanup, execution.lease_id, execution.revision, receipt
    )
    assert h.store.validate_cleanup(cleanup).leases
    changed_result = result.model_dump(mode="json")
    changed_result["resource_id"] = "8" * 64
    data = receipt.model_dump(mode="json", by_alias=True)
    data["result"] = freeze_snapshot("cleanup-v1", changed_result).model_dump(
        mode="json", by_alias=True
    )
    changed_receipt = BaselineCleanupReceipt.model_validate_json(canonical(data))
    lease_data = released.model_dump(mode="json", by_alias=True)
    lease_data["receipt_sha256"] = changed_receipt.digest
    changed_lease = BaselineResourceLease.model_validate_json(canonical(lease_data))
    with sqlite3.connect(h.state.database_path) as connection:
        connection.execute(
            "INSERT INTO baseline_cleanup_receipts VALUES(?,?,?,?,?)",
            (
                changed_receipt.digest,
                h.review.baseline_id,
                0,
                changed_receipt.digest,
                changed_receipt.canonical_bytes(),
            ),
        )
        connection.execute(
            "UPDATE baseline_resource_leases SET record_sha256=?,payload=? WHERE record_id=?",
            (changed_lease.digest, changed_lease.canonical_bytes(), changed_lease.lease_id),
        )
    with pytest.raises(FleetError):
        h.store.baseline_resource_snapshot(h.review.baseline_id)


def test_scope_index_cannot_substitute_the_original_payload(tmp_path: Path) -> None:
    h = baseline_fixture(tmp_path)
    cleanup, _ = _report(h)
    with sqlite3.connect(h.state.database_path) as connection:
        connection.execute("UPDATE baseline_events SET scope_sha256=?", ("0" * 64,))
    with pytest.raises(FleetError):
        h.store.validate_cleanup(cleanup)


@pytest.mark.parametrize("omitted", ["all", "execution", "dispatch"])
def test_historical_scope_cannot_omit_permanent_resources(tmp_path: Path, omitted: str) -> None:
    h = baseline_fixture(tmp_path)
    scope, report = _report(h)
    current = h.store.validate_cleanup(scope)
    h.store.publish_baseline_report(scope, current.execution.revision, report.canonical_bytes())
    good = h.store.show(h.review.baseline_id)
    snapshot_data = scope.snapshot.model_dump(mode="json", by_alias=True)
    snapshot_data["dispatch"] = None
    if omitted == "all":
        snapshot_data["leases"] = []
    elif omitted == "execution":
        snapshot_data["leases"] = [
            item for item in snapshot_data["leases"] if item["payload"]["kind"] != "execution"
        ]
    changed_snapshot = BaselineResourceSnapshot.model_validate_json(canonical(snapshot_data))
    scope_data = scope.model_dump(mode="json", by_alias=True)
    scope_data.update(
        snapshot=changed_snapshot.model_dump(mode="json", by_alias=True),
        scope_sha256=changed_snapshot.digest,
    )
    changed_scope = BaselineCleanupClaim.model_validate_json(canonical(scope_data))
    report_data = report.model_dump(mode="json", by_alias=True)
    report_data.update(
        cleanup_scope_sha256=changed_scope.scope_sha256,
        cleanup_complete=True,
        status="observed",
        proof_gaps=[],
    )
    changed_report = BaselineReport.model_validate_json(canonical(report_data))
    execution_data = good.execution.model_dump(mode="json", by_alias=True)
    execution_data["current_report_sha256"] = changed_report.digest
    changed_execution = BaselineExecution.model_validate_json(canonical(execution_data))
    with sqlite3.connect(h.state.database_path) as connection:
        connection.execute(
            "UPDATE baseline_events SET scope_sha256=?,record_sha256=?,payload=? "
            "WHERE baseline_id=?",
            (
                changed_scope.scope_sha256,
                changed_scope.digest,
                changed_scope.canonical_bytes(),
                h.review.baseline_id,
            ),
        )
        connection.execute(
            "INSERT INTO baseline_reports VALUES(?,?,?,?,?)",
            (
                "brpt_" + changed_report.digest,
                h.review.baseline_id,
                0,
                changed_report.digest,
                changed_report.canonical_bytes(),
            ),
        )
        connection.execute(
            "UPDATE baseline_executions SET record_sha256=?,payload=? WHERE baseline_id=?",
            (changed_execution.digest, changed_execution.canonical_bytes(), h.review.baseline_id),
        )
    with pytest.raises(FleetError):
        h.store.show(h.review.baseline_id)


def test_new_cleanup_scope_preserves_original_report_and_receipts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = baseline_fixture(tmp_path)
    original_scope, original_report = _report(h)
    current = h.store.validate_cleanup(original_scope)
    h.store.publish_baseline_report(
        original_scope, current.execution.revision, original_report.canonical_bytes()
    )
    snapshot = h.store.baseline_resource_snapshot(h.review.baseline_id)
    stopped = BaselineStoppedOwnerReview(
        owner=snapshot.claim.owner,
        owner_claim_sha256=snapshot.claim.digest,
        snapshot_sha256=snapshot.digest,
        controller_pid=snapshot.claim.controller_pid,
        installation_id=h.review.installation_id,
        state="absent",
        checked_at=h.state.clock.now(),
    )
    # This control isolates historical transactional binding, not OS owner-death proof.
    monkeypatch.setattr("agent_fleet.adapters.persistence.baseline._pid_absent", lambda _: True)
    successor = h.store.claim_baseline_cleanup(snapshot, stopped)
    assert h.store.show(h.review.baseline_id).report == original_report
    tiers = {"execution": 0, "sandbox": 1, "workspace": 2}
    for lease in sorted(successor.snapshot.leases, key=lambda item: tiers[item.kind]):
        now = h.state.clock.now()
        payload = lease.payload
        if isinstance(payload, BaselineCommandPayload):
            assert payload.handle is not None
            result = SandboxCleanupResult(
                provider="docker",
                resource_id=payload.handle.native_resource_id,
                resources_found=1,
                resources_removed=1,
                reconciled=True,
                complete=True,
                completed_at=now,
            )
        elif isinstance(payload, BaselineSandboxPayload):
            result = SandboxCleanupResult(
                provider="docker",
                resource_id=payload.sandbox_id,
                resources_found=0,
                resources_removed=0,
                reconciled=True,
                complete=True,
                completed_at=now,
            )
        else:
            result = None
        receipt = BaselineCleanupReceipt(
            owner=successor.owner,
            lease_id=lease.lease_id,
            lease_sha256=lease.digest,
            cleanup_scope_sha256=successor.scope_sha256,
            kind=lease.kind,
            complete=True,
            result=None
            if result is None
            else freeze_snapshot("cleanup-v1", result.model_dump(mode="json")),
            completed_at=now,
        )
        h.store.finalize_baseline_lease(successor, lease.lease_id, lease.revision, receipt)
        assert h.store.show(h.review.baseline_id).report == original_report
    current = h.store.validate_cleanup(successor)
    assert all(item.receipt_sha256 is not None for item in current.leases)
    data = original_report.model_dump(mode="json", by_alias=True)
    data.update(
        cleanup_scope_sha256=successor.scope_sha256,
        cleanup_receipt_sha256s=sorted(
            item.receipt_sha256 for item in current.leases if item.receipt_sha256 is not None
        ),
        cleanup_complete=True,
        status="observed",
        proof_gaps=[],
        predecessor_report_sha256=original_report.digest,
        completed_at=h.state.clock.now().isoformat(),
    )
    report = BaselineReport.model_validate_json(canonical(data))
    h.store.publish_baseline_report(successor, current.execution.revision, report.canonical_bytes())
    assert h.store.show(h.review.baseline_id).report == report
    with sqlite3.connect(h.state.database_path) as connection:
        historical = connection.execute(
            "SELECT payload FROM baseline_reports WHERE record_id=?",
            ("brpt_" + original_report.digest,),
        ).fetchone()[0]
    assert historical == original_report.canonical_bytes()


@pytest.mark.parametrize("already_complete", [True, False])
def test_recovery_preserves_released_lease_but_can_retry_failed_lease(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, already_complete: bool
) -> None:
    h = baseline_fixture(tmp_path)
    owner = h.claim()
    workspace = h.workspace(owner)
    first = h.store.begin_baseline_cleanup(
        owner, h.store.baseline_resource_snapshot(h.review.baseline_id)
    )
    receipt = BaselineCleanupReceipt(
        owner=owner.owner,
        lease_id=workspace.lease_id,
        lease_sha256=workspace.digest,
        cleanup_scope_sha256=first.scope_sha256,
        kind="workspace",
        complete=already_complete,
        result=None,
        completed_at=h.state.clock.now(),
    )
    h.store.finalize_baseline_lease(first, workspace.lease_id, workspace.revision, receipt)
    before = h.store.baseline_resource_snapshot(h.review.baseline_id)
    stopped = BaselineStoppedOwnerReview(
        owner=owner.owner,
        owner_claim_sha256=owner.digest,
        snapshot_sha256=before.digest,
        controller_pid=owner.controller_pid,
        installation_id=owner.installation_id,
        state="absent",
        checked_at=h.state.clock.now(),
    )
    # OS death is independently checked by test_baseline_owner; this isolates lease CAS.
    monkeypatch.setattr("agent_fleet.adapters.persistence.baseline._pid_absent", lambda _: True)
    recovery = h.store.claim_baseline_cleanup(before, stopped)
    current = h.store.validate_cleanup(recovery)
    original = current.leases[0]
    successor = BaselineCleanupReceipt(
        owner=owner.owner,
        lease_id=original.lease_id,
        lease_sha256=original.digest,
        cleanup_scope_sha256=recovery.scope_sha256,
        kind="workspace",
        complete=True,
        result=None,
        completed_at=h.state.clock.now(),
    )
    if already_complete:
        with pytest.raises(FleetError):
            h.store.finalize_baseline_lease(
                recovery, original.lease_id, original.revision, successor
            )
        assert h.store.validate_cleanup(recovery) == current
    else:
        released = h.store.finalize_baseline_lease(
            recovery, original.lease_id, original.revision, successor
        )
        assert released.status == "released" and released.revision == original.revision + 1
        assert h.store.validate_cleanup(recovery).leases == (released,)
