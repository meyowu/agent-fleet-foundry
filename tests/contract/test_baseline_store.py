from __future__ import annotations

import multiprocessing
import sqlite3
from datetime import timedelta
from multiprocessing.connection import Connection
from pathlib import Path

import pytest
from business_baseline_fixtures import baseline_fixture
from pydantic import ValidationError

from agent_fleet.adapters.persistence.baseline import SqliteBaselineStore
from agent_fleet.adapters.persistence.sqlite import SqliteStateStore
from agent_fleet.adapters.system import SystemClock, UuidIdGenerator
from agent_fleet.domain.baseline import (
    BaselineCommandObservation,
    BaselineReport,
    baseline_id,
    canonical,
    freeze_snapshot,
)
from agent_fleet.domain.baseline_resources import (
    BaselineCleanupReceipt,
    BaselineCommandPayload,
    BaselineExecRequest,
    BaselineResourceLease,
    BaselineSandboxHandle,
    BaselineSandboxPayload,
    BaselineWorkspacePayload,
    baseline_sandbox_handle,
)
from agent_fleet.domain.errors import FleetError
from agent_fleet.domain.models import SandboxCleanupResult
from agent_fleet.domain.security import Redactor


def _foreign_controller(
    database: str, installation: str, identity: str, workspace_bytes: bytes, pipe: Connection
) -> None:
    state = SqliteStateStore(Path(database), SystemClock(), UuidIdGenerator(), Redactor())
    store = SqliteBaselineStore(state, installation_id=installation)
    try:
        claim = store.owner_claim(identity)
        snapshot = store.baseline_resource_snapshot(identity)
        refused = 0
        try:
            store.begin_baseline_cleanup(claim, snapshot)
        except FleetError:
            refused += 1
        from agent_fleet.domain.baseline_resources import BaselineWorkspace

        workspace = BaselineWorkspace.from_canonical(workspace_bytes)
        now = state.clock.now()
        lease = BaselineResourceLease(
            lease_id=baseline_id("blease"),
            owner=claim.owner,
            revision=0,
            status="creating",
            payload=BaselineWorkspacePayload(workspace=workspace),
            created_at=now,
            updated_at=now,
        )
        try:
            store.reserve_baseline_lease(claim, lease)
        except FleetError:
            refused += 1
        pipe.send("refused" if refused == 2 else "unexpected")
    finally:
        pipe.close()


def test_spawned_controller_cannot_reuse_owner_for_cleanup(tmp_path: Path) -> None:
    h = baseline_fixture(tmp_path)
    h.claim()
    before = h.store.baseline_resource_snapshot(h.review.baseline_id)
    workspace_data = h.spec.workspace.model_dump(mode="json", by_alias=True)
    workspace_data["materialized_source_sha256"] = None
    context = multiprocessing.get_context("spawn")
    reader, writer = context.Pipe(duplex=False)
    child = context.Process(
        target=_foreign_controller,
        args=(
            str(h.state.database_path),
            h.review.installation_id,
            h.review.baseline_id,
            canonical(workspace_data),
            writer,
        ),
    )
    try:
        child.start()
        writer.close()
        assert reader.poll(10), "controller watchdog expired"
        assert reader.recv() == "refused"
        child.join(5)
        assert child.exitcode == 0
    finally:
        if child.is_alive():
            child.terminate()
            child.join(5)
        reader.close()
        writer.close()
        if child.exitcode is not None:
            child.close()
    assert h.store.baseline_resource_snapshot(h.review.baseline_id) == before


@pytest.mark.parametrize(
    "mutation", ["empty", "writable", "scratch", "capability", "before_owner", "after_start"]
)
def test_observation_rejects_unproved_effective_controls(tmp_path: Path, mutation: str) -> None:
    h = baseline_fixture(tmp_path)
    claim = h.claim()
    observation = h.dispatched_observation(claim)
    import json

    data = observation.model_dump(mode="json", by_alias=True)
    inspection = json.loads(observation.inspection.canonical_utf8)
    controls = json.loads(inspection["legacy_control_inspection"]["canonical_json"])
    if mutation == "empty":
        controls = {}
    elif mutation == "writable":
        controls["read_only_root"] = False
    elif mutation == "scratch":
        inspection["tmp_scratch_mb"] = 32
    elif mutation == "capability":
        controls["configuration_sha256"] = "0" * 64
    else:
        controls["inspected_at"] = (
            claim.claimed_at - timedelta(seconds=1)
            if mutation == "before_owner"
            else observation.started_at + timedelta(seconds=1)
        ).isoformat()
    inspection["legacy_control_inspection"] = freeze_snapshot(
        "sandbox-inspection-v1",
        controls,
    ).model_dump(mode="json", by_alias=True)
    data["inspection"] = freeze_snapshot("sandbox-inspection-v1", inspection).model_dump(
        mode="json",
        by_alias=True,
    )
    changed = BaselineCommandObservation.model_validate_json(canonical(data))
    before = h.store.baseline_resource_snapshot(h.review.baseline_id)
    with pytest.raises(FleetError):
        h.store.record_command_observation(
            claim, before.execution.revision, changed.canonical_bytes()
        )
    assert h.store.observation(h.review.baseline_id) is None
    assert h.store.baseline_resource_snapshot(h.review.baseline_id) == before


def test_report_reference_binds_execution_not_only_observation_hash(tmp_path: Path) -> None:
    h = baseline_fixture(tmp_path)
    claim = h.claim()
    observation = h.dispatched_observation(claim)
    before = h.store.baseline_resource_snapshot(h.review.baseline_id)
    ref = h.store.record_command_observation(
        claim, before.execution.revision, observation.canonical_bytes()
    )
    assert h.store.observation(h.review.baseline_id) == observation
    cleanup = h.store.begin_baseline_cleanup(
        claim, h.store.baseline_resource_snapshot(h.review.baseline_id)
    )
    snapshot = h.store.validate_cleanup(cleanup)
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
    data = report.model_dump(mode="json", by_alias=True)
    data["observation"]["execution_id"] = baseline_id("bexec")
    altered = BaselineReport.model_validate_json(canonical(data))
    with pytest.raises(FleetError):
        h.store.publish_baseline_report(
            cleanup, snapshot.execution.revision, altered.canonical_bytes()
        )
    assert h.store.validate_cleanup(cleanup) == snapshot
    h.store.publish_baseline_report(cleanup, snapshot.execution.revision, report.canonical_bytes())
    assert h.store.show(h.review.baseline_id).report == report


def test_review_owner_is_permanent_and_never_invents_a_run(tmp_path: Path) -> None:
    h = baseline_fixture(tmp_path)
    before = h.store.show(h.review.review_id)
    assert before.execution.status == "planned" and before.recovery_scope_sha256 is None
    claim = h.claim()
    assert h.store.owner_claim(h.review.baseline_id) == claim
    with pytest.raises(FleetError):
        h.claim()
    with pytest.raises(FleetError):
        h.store.revoke(h.review.review_id)
    with sqlite3.connect(h.state.database_path) as connection:
        for table in (
            "runs",
            "tasks",
            "agent_instances",
            "tool_intents",
            "tool_dispatch_claims",
            "resource_leases",
        ):
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    assert (
        SqliteBaselineStore(h.state, installation_id=h.review.installation_id).owner_claim(
            h.review.baseline_id
        )
        == claim
    )


def test_revocation_precedes_claim_and_cannot_be_reauthorized(tmp_path: Path) -> None:
    h = baseline_fixture(tmp_path)
    h.store.authorize(h.review.review_id, h.review.digest)
    assert h.store.revoke(h.review.review_id).status == "revoked"
    with pytest.raises(FleetError):
        h.claim()


def test_full_allocation_dispatch_and_no_replay(tmp_path: Path) -> None:
    h = baseline_fixture(tmp_path)
    claim = h.claim()
    h.workspace(claim)
    sandbox = h.sandbox(claim)
    snapshot = h.store.baseline_resource_snapshot(h.review.baseline_id)
    request = BaselineExecRequest(
        owner=claim.owner,
        claim_id=claim.claim_id,
        execution_id=baseline_id("bexec"),
        workspace_id=h.spec.workspace.workspace_id,
        command=h.review.command,
    )
    now = h.state.clock.now()
    lease = BaselineResourceLease(
        lease_id=baseline_id("blease"),
        owner=claim.owner,
        revision=0,
        status="creating",
        payload=BaselineCommandPayload(request=request, sandbox=sandbox),
        created_at=now,
        updated_at=now,
    )
    dispatch = h.store.claim_baseline_dispatch(claim, snapshot.digest, request, lease)
    assert dispatch.request == request
    with pytest.raises(FleetError):
        h.store.claim_baseline_dispatch(claim, snapshot.digest, request, lease)
    marked = h.store.mark_baseline_creation_dispatched(claim, lease.lease_id, 0)
    assert isinstance(marked.payload, BaselineCommandPayload) and marked.payload.creation_dispatched
    with pytest.raises(FleetError):
        h.store.mark_baseline_creation_dispatched(claim, lease.lease_id, 1)


def test_cleanup_fences_whole_payload_before_effects(tmp_path: Path) -> None:
    h = baseline_fixture(tmp_path)
    claim = h.claim()
    lease = h.workspace(claim)
    stale = h.store.baseline_resource_snapshot(h.review.baseline_id)
    h.sandbox(claim)
    with pytest.raises(FleetError):
        h.store.begin_baseline_cleanup(claim, stale)
    current = h.store.baseline_resource_snapshot(h.review.baseline_id)
    cleanup = h.store.begin_baseline_cleanup(claim, current)
    assert h.store.validate_cleanup(cleanup).execution.status == "cleaning"
    with pytest.raises(FleetError):
        h.store.reserve_baseline_lease(claim, lease)
    with pytest.raises(FleetError):
        h.store.finalize_baseline_lease(
            cleanup,
            lease.lease_id,
            lease.revision,
            BaselineCleanupReceipt(
                owner=claim.owner,
                lease_id=lease.lease_id,
                lease_sha256=lease.digest,
                cleanup_scope_sha256=cleanup.scope_sha256,
                kind="workspace",
                complete=True,
                result=None,
                completed_at=h.state.clock.now(),
            ),
        )


def test_cleanup_receipt_is_immutable_and_wrong_owner_is_denied(tmp_path: Path) -> None:
    h = baseline_fixture(tmp_path)
    claim = h.claim()
    lease = h.workspace(claim)
    assert isinstance(lease.payload, BaselineWorkspacePayload)
    cleanup = h.store.begin_baseline_cleanup(
        claim, h.store.baseline_resource_snapshot(h.review.baseline_id)
    )
    receipt = BaselineCleanupReceipt(
        owner=claim.owner,
        lease_id=lease.lease_id,
        lease_sha256=lease.digest,
        cleanup_scope_sha256=cleanup.scope_sha256,
        kind="workspace",
        complete=True,
        result=None,
        completed_at=h.state.clock.now(),
    )
    released = h.store.finalize_baseline_lease(cleanup, lease.lease_id, lease.revision, receipt)
    assert released.status == "released"
    assert h.store.validate_cleanup(cleanup).leases == (released,)
    with pytest.raises(FleetError):
        h.store.finalize_baseline_lease(cleanup, lease.lease_id, lease.revision, receipt)


@pytest.mark.parametrize(
    "column,value", [("record_sha256", "0" * 64), ("revision", 9), ("payload", b"{}")]
)
def test_index_payload_hash_corruption_never_repairs(
    tmp_path: Path, column: str, value: object
) -> None:
    h = baseline_fixture(tmp_path)
    with sqlite3.connect(h.state.database_path) as connection:
        connection.execute(f"UPDATE baseline_executions SET {column}=?", (value,))
    with pytest.raises(FleetError) as rejected:
        h.store.show(h.review.review_id)
    assert rejected.value.__context__ is None and rejected.value.__cause__ is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("configuration_sha256", "0" * 64),
        ("image_identity", "sha256:" + "0" * 64),
        ("daemon_identity", "0" * 64),
        ("recovery_scope_id", "0" * 32),
    ],
)
def test_sandbox_activation_cannot_substitute_reserved_identity(
    tmp_path: Path, field: str, value: str
) -> None:
    h = baseline_fixture(tmp_path)
    claim = h.claim()
    h.workspace(claim)
    sandbox_id = baseline_id("bsandbox")
    now = h.state.clock.now()
    lease = BaselineResourceLease(
        lease_id=baseline_id("blease"),
        owner=claim.owner,
        revision=0,
        status="creating",
        payload=BaselineSandboxPayload(sandbox_id=sandbox_id, spec=h.spec),
        created_at=now,
        updated_at=now,
    )
    h.store.reserve_baseline_lease(claim, lease)
    handle = baseline_sandbox_handle(h.spec, sandbox_id, h.review)
    data = handle.model_dump(mode="json", by_alias=True)
    data[field] = value
    altered = BaselineSandboxHandle.model_validate_json(canonical(data))
    before = h.store.baseline_resource_snapshot(h.review.baseline_id)
    with pytest.raises(FleetError):
        h.store.activate_baseline_lease(claim, lease.lease_id, 0, altered)
    assert h.store.baseline_resource_snapshot(h.review.baseline_id) == before


def test_new_process_cannot_continue_a_persisted_controller_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = baseline_fixture(tmp_path)
    claim = h.claim()
    with monkeypatch.context() as context:
        context.setattr(
            "agent_fleet.adapters.persistence.baseline.os.getpid", lambda: claim.controller_pid + 1
        )
        with pytest.raises(FleetError):
            h.workspace(claim)
    assert h.store.baseline_resource_snapshot(h.review.baseline_id).leases == ()


def test_unknown_dispatched_create_with_no_match_cannot_release(tmp_path: Path) -> None:
    h = baseline_fixture(tmp_path)
    claim = h.claim()
    h.workspace(claim)
    sandbox = h.sandbox(claim)
    snapshot = h.store.baseline_resource_snapshot(h.review.baseline_id)
    request = BaselineExecRequest(
        owner=claim.owner,
        claim_id=claim.claim_id,
        execution_id=baseline_id("bexec"),
        workspace_id=h.spec.workspace.workspace_id,
        command=h.review.command,
    )
    now = h.state.clock.now()
    lease = BaselineResourceLease(
        lease_id=baseline_id("blease"),
        owner=claim.owner,
        revision=0,
        status="creating",
        payload=BaselineCommandPayload(request=request, sandbox=sandbox),
        created_at=now,
        updated_at=now,
    )
    h.store.claim_baseline_dispatch(claim, snapshot.digest, request, lease)
    marked = h.store.mark_baseline_creation_dispatched(claim, lease.lease_id, 0)
    cleanup = h.store.begin_baseline_cleanup(
        claim, h.store.baseline_resource_snapshot(h.review.baseline_id)
    )
    now = h.state.clock.now()
    with pytest.raises(ValidationError):
        BaselineCleanupReceipt(
            owner=claim.owner,
            lease_id=lease.lease_id,
            lease_sha256=marked.digest,
            cleanup_scope_sha256=cleanup.scope_sha256,
            kind="execution",
            complete=True,
            result=None,
            completed_at=now,
        )
    result = SandboxCleanupResult(
        provider="docker",
        resource_id=request.execution_id,
        resources_found=0,
        resources_removed=0,
        reconciled=True,
        complete=True,
        completed_at=now,
    )
    receipt = BaselineCleanupReceipt(
        owner=claim.owner,
        lease_id=lease.lease_id,
        lease_sha256=marked.digest,
        cleanup_scope_sha256=cleanup.scope_sha256,
        kind="execution",
        complete=True,
        result=freeze_snapshot("cleanup-v1", result.model_dump(mode="json")),
        completed_at=now,
    )
    with pytest.raises(FleetError):
        h.store.finalize_baseline_lease(cleanup, lease.lease_id, marked.revision, receipt)
    assert h.store.validate_cleanup(cleanup).leases == cleanup.snapshot.leases
