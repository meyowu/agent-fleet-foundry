"""Planning decisions recheck actual artifacts, repository and organization authority."""

from __future__ import annotations

import json
import sqlite3
import traceback
from datetime import timedelta

import pytest
from conftest import FleetHarness
from plan_review_fixtures import PlanReviewHarness, make_plan_review
from pydantic import ValidationError

from agent_fleet.adapters.artifacts.local import LocalArtifactStore
from agent_fleet.domain.config import ConfigSnapshot
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import (
    FleetPatch,
    FleetPatchFileChange,
    FleetPatchOperation,
    RunStatus,
)
from agent_fleet.domain.plan_review import PlanReviewCheckpoint, plan_review_run_sha256
from agent_fleet.domain.security import sha256_bytes


@pytest.fixture
def plan_review(harness: FleetHarness) -> PlanReviewHarness:
    return make_plan_review(harness)


@pytest.mark.parametrize("actor", ["cos", "engineer", "verifier", "User", "", "user\n"])
def test_only_explicit_user_actor_can_approve(plan_review: PlanReviewHarness, actor: str) -> None:
    h = plan_review
    pending = h.service.create(h.scoped)
    with pytest.raises(FleetError) as error:
        h.service.approve(h.run, pending.checkpoint_sha256, actor=actor)
    assert error.value.code is ErrorCode.APPROVAL_INVALID
    assert h.service.inspect(h.run) == pending


def test_approval_is_not_execution_and_pending_hash_cannot_consume(
    plan_review: PlanReviewHarness,
) -> None:
    h = plan_review
    pending = h.service.create(h.scoped)
    with pytest.raises(FleetError) as premature:
        h.service.consume(h.run, pending.checkpoint_sha256)
    assert premature.value.code is ErrorCode.APPROVAL_INVALID
    approved = h.service.approve(h.run, pending.checkpoint_sha256)
    assert h.run.status is RunStatus.PAUSED_FOR_PLAN
    with pytest.raises(FleetError):
        h.service.consume(h.run, pending.checkpoint_sha256)
    assert h.service.inspect(h.run) == approved
    assert not h.fleet.container.state.list_leases(h.run.run_id)


@pytest.mark.parametrize("decision", ["approve", "consume"])
def test_repository_drift_prevents_action_but_preserves_inspection(
    plan_review: PlanReviewHarness,
    decision: str,
) -> None:
    h = plan_review
    checkpoint = h.service.create(h.scoped)
    if decision == "consume":
        checkpoint = h.service.approve(h.run, checkpoint.checkpoint_sha256)
    target = h.fleet.repository_root / "src/canary_calc/core.py"
    target.write_text(target.read_text() + "\n# Unrelated work after planning\n")
    assert h.service.inspect(h.run) == checkpoint
    with pytest.raises(FleetError) as error:
        getattr(h.service, decision)(h.run, checkpoint.checkpoint_sha256)
    assert error.value.code is ErrorCode.PATCH_TARGET_DIVERGED
    assert h.run.status is RunStatus.PAUSED_FOR_PLAN


def test_changed_head_cannot_reuse_review(plan_review: PlanReviewHarness) -> None:
    h = plan_review
    pending = h.service.create(h.scoped)
    h.fleet.git(
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.test",
        "commit",
        "--allow-empty",
        "-m",
        "A newer fixture base",
    )
    with pytest.raises(FleetError) as error:
        h.service.approve(h.run, pending.checkpoint_sha256)
    assert error.value.code is ErrorCode.PATCH_TARGET_DIVERGED


def test_review_callback_failure_is_inside_guard_before_cas(
    plan_review: PlanReviewHarness,
) -> None:
    h = plan_review
    pending = h.service.create(h.scoped)
    calls = []

    def expired() -> None:
        calls.append(h.fleet.container.organization.store.admission_for_run(h.run.run_id))
        raise FleetError(ErrorCode.APPROVAL_INVALID, "Review expired.", "Review again.")

    with pytest.raises(FleetError) as error:
        h.service.approve(h.run, pending.checkpoint_sha256, validate_review=expired)
    assert error.value.code is ErrorCode.APPROVAL_INVALID
    assert calls == [pending.binding.organization_admission]
    assert h.service.inspect(h.run) == pending


@pytest.mark.parametrize(
    "artifact_field",
    [
        "task_spec_artifact_id",
        "fleet_plan_artifact_id",
        "config_snapshot_artifact_id",
    ],
)
def test_artifact_byte_corruption_is_not_presented_or_approved(
    plan_review: PlanReviewHarness,
    artifact_field: str,
) -> None:
    h = plan_review
    pending = h.service.create(h.scoped)
    artifact_id = getattr(h.run, artifact_field)
    metadata = h.fleet.container.state.get_artifact(artifact_id)
    # Artifact storage paths are private hashed refs; the real adapter resolves them.
    store = h.fleet.container.artifacts.store
    assert isinstance(store, LocalArtifactStore)
    path = store.root / metadata.content_ref
    path.write_bytes(b"corrupted")
    with pytest.raises(FleetError) as error:
        h.service.inspect(h.run)
    assert error.value.code is ErrorCode.ARTIFACT_INTEGRITY_FAILED
    with pytest.raises(FleetError):
        h.service.approve(h.run, pending.checkpoint_sha256)


def test_changed_task_table_is_not_accepted_as_exact_artifact(
    plan_review: PlanReviewHarness,
) -> None:
    h = plan_review
    h.service.create(h.scoped)
    with sqlite3.connect(h.fleet.container.state.database_path) as connection:
        raw = connection.execute("SELECT data_json FROM tasks").fetchone()[0]
        value = json.loads(raw)
        value["normalized_goal"] = "Different bounded task"
        connection.execute("UPDATE tasks SET data_json=?", (json.dumps(value),))
    with pytest.raises(FleetError) as error:
        h.service.inspect(h.run)
    assert error.value.code is ErrorCode.ARTIFACT_INTEGRITY_FAILED


def test_historical_decision_survives_organization_evolution_without_new_authority(
    plan_review: PlanReviewHarness,
) -> None:
    h = plan_review
    c = h.fleet.container
    pending = h.service.create(h.scoped)
    assert h.run.config_snapshot_artifact_id is not None
    snapshot = ConfigSnapshot.model_validate_json(
        c.artifacts.read_text(h.run.config_snapshot_artifact_id)
    )
    context = c.organization.proposal_context(h.run, snapshot)
    head = c.organization.store.get_head(h.run.project_id)
    assert head is not None
    tree = c.organization.store.get_tree(head.tree_sha256)
    before = next(item for item in tree.files if item.path == "agents/engineer.md")
    content = before.content + "\nDocument remaining verification risks explicitly.\n"
    proposal = c.organization.propose(
        h.run,
        FleetPatch(
            fleet_patch_id=context.proposal_id,
            project_id=h.run.project_id,
            base_fleet_spec_sha256=head.config_snapshot_sha256,
            changes=[
                FleetPatchFileChange(
                    operation=FleetPatchOperation.REPLACE,
                    path=".fleet/agents/engineer.md",
                    before_sha256=before.sha256,
                    after_sha256=sha256_bytes(content.encode()),
                    content=content,
                )
            ],
            rationale="Keep explicit verification risk guidance.",
        ),
        context,
    )
    # Waiting decisions fence publication just like existing tool-approval pauses.
    with pytest.raises(FleetError):
        c.organization.apply(proposal.patch.fleet_patch_id)
    assert h.service.inspect(h.run) == pending
    c.state.save_run(h.run.model_copy(update={"status": RunStatus.CANCELLED}), "run.cancelled", {})
    result = c.organization.apply(proposal.patch.fleet_patch_id)
    assert result.version is not None and result.version.version == 1
    assert h.service.inspect(h.run) == pending
    with pytest.raises(FleetError):
        h.service.approve(h.run, pending.checkpoint_sha256)
    assert h.run.status is RunStatus.CANCELLED


def test_cancelled_and_consumed_history_remains_inspectable(plan_review: PlanReviewHarness) -> None:
    h = plan_review
    pending = h.service.create(h.scoped)
    approved = h.service.approve(h.run, pending.checkpoint_sha256)
    resumed = h.service.consume(h.run, approved.checkpoint_sha256)
    c = h.fleet.container
    cancelled = c.state.save_run(
        resumed.model_copy(update={"status": RunStatus.CANCELLED}), "run.cancelled", {}
    )
    assert h.service.inspect(cancelled).status == "consumed"
    with pytest.raises(FleetError) as repeat:
        h.service.consume(cancelled, approved.checkpoint_sha256)
    assert repeat.value.code is ErrorCode.APPROVAL_INVALID


def test_secret_corruption_never_escapes_errors_or_projection(
    plan_review: PlanReviewHarness,
) -> None:
    h = plan_review
    pending = h.service.create(h.scoped)
    secret = "fixture-private-review-credential-value"
    h.fleet.container.redactor.register_secret(secret)
    with sqlite3.connect(h.fleet.container.state.database_path) as connection:
        value = json.loads(pending.model_dump_json())
        value["binding"]["repository_root"] = secret
        connection.execute("UPDATE plan_review_versions SET data_json=?", (json.dumps(value),))
    with pytest.raises(FleetError) as error:
        h.service.inspect(h.run)
    rendered = "".join(traceback.format_exception(error.value))
    assert secret not in rendered
    assert error.value.code is ErrorCode.RECOVERY_REQUIRED
    projected = json.dumps(pending.safe_projection())
    assert "credential_ref" not in projected and "repository_root" not in projected


def test_json_escaped_secret_is_rejected_after_decode(plan_review: PlanReviewHarness) -> None:
    h = plan_review
    c = h.fleet.container
    run = h.run
    assert run.task_spec_artifact_id is not None
    metadata = c.state.get_artifact(run.task_spec_artifact_id)
    task = json.loads(c.artifacts.read_text(metadata.artifact_id))
    secret = "private-escaped-plan-review-value"
    task["normalized_goal"] = secret
    escaped = "".join(f"\\u{ord(char):04x}" for char in secret)
    text = json.dumps(task).replace(secret, escaped)
    assert secret not in text
    content_ref, digest, size = c.artifacts.store.put(text.encode())
    changed_metadata = metadata.model_copy(
        update={
            "sha256": digest,
            "content_ref": content_ref,
            "byte_size": size,
        }
    )
    with sqlite3.connect(c.state.database_path) as connection:
        connection.execute(
            "UPDATE artifacts SET sha256=?, data_json=? WHERE artifact_id=?",
            (digest, changed_metadata.model_dump_json(), metadata.artifact_id),
        )
    changed_run = c.state.save_run(
        run.model_copy(update={"task_spec_hash": digest}), "fixture.changed_artifact", {}
    )
    c.redactor.register_secret(secret)
    with pytest.raises(FleetError) as error:
        h.service.create(changed_run)
    assert error.value.code is ErrorCode.ARTIFACT_INTEGRITY_FAILED
    assert secret not in "".join(traceback.format_exception(error.value))


def test_decision_domain_rejects_coercion_revision_and_time_travel(
    plan_review: PlanReviewHarness,
) -> None:
    h = plan_review
    pending = h.service.create(h.scoped)
    for update in (
        {"revision": True},
        {"revision": "1"},
        {"status": "consumed"},
        {"actor": "cos"},
        {"updated_at": pending.created_at - timedelta(seconds=1)},
        {"unexpected": "not accepted"},
    ):
        value = pending.model_dump()
        value.update(update)
        with pytest.raises(ValidationError):
            PlanReviewCheckpoint.model_validate(value)
    changed = h.run.model_copy(
        update={
            "status": RunStatus.CANCELLED,
            "repair_iterations": 1,
            "updated_at": h.run.updated_at + timedelta(seconds=1),
        }
    )
    assert plan_review_run_sha256(changed) == plan_review_run_sha256(h.run)
    assert plan_review_run_sha256(h.run.model_copy(update={"goal": "Other task"})) != (
        plan_review_run_sha256(h.run)
    )
