from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from agent_fleet.domain.evolution import OrganizationAdmission
from agent_fleet.domain.models import Run, RunStatus
from agent_fleet.domain.plan_review import (
    PlanReviewBinding,
    PlanReviewCheckpoint,
    plan_review_run_sha256,
)
from agent_fleet.schemas.generate import SCHEMAS


def _pending() -> PlanReviewCheckpoint:
    now = datetime(2026, 9, 7, tzinfo=UTC)
    project_id = "prj_" + "1" * 32
    return PlanReviewCheckpoint(
        binding=PlanReviewBinding(
            root_run_id="run_" + "2" * 32,
            project_id=project_id,
            task_id="task_" + "3" * 32,
            run_sha256="4" * 64,
            task_spec_artifact_id="art_" + "5" * 32,
            task_spec_sha256="6" * 64,
            fleet_plan_artifact_id="art_" + "7" * 32,
            fleet_plan_sha256="8" * 64,
            config_snapshot_artifact_id="art_" + "9" * 32,
            config_snapshot_sha256="a" * 64,
            repository_root="/review-fixture",
            repository_identity="b" * 64,
            base_revision="c" * 40,
            target_status_fingerprint="d" * 64,
            organization_admission=OrganizationAdmission(
                project_id=project_id,
                revision=0,
                tree_sha256="e" * 64,
                config_snapshot_sha256="a" * 64,
            ),
        ),
        revision=1,
        status="pending",
        created_at=now,
        updated_at=now,
    )


@pytest.mark.parametrize(
    "update",
    [
        {"revision": True},
        {"revision": "1"},
        {"status": "consumed"},
        {"actor": "cos"},
        {"unknown": "not accepted"},
        {"previous_sha256": "0" * 64},
        {"updated_at": datetime(2026, 9, 6, tzinfo=UTC)},
        {"updated_at": datetime(2026, 9, 7, tzinfo=timezone(timedelta(hours=1)))},
        {"updated_at": datetime(2026, 9, 7)},
    ],
)
def test_checkpoint_is_strict_utc_and_monotonic(update: dict[str, object]) -> None:
    value = _pending().model_dump()
    value.update(update)
    with pytest.raises(ValidationError):
        PlanReviewCheckpoint.model_validate(value)


def test_plan_approval_hash_rotates_but_binding_stays_pinned() -> None:
    pending = _pending()
    approved = PlanReviewCheckpoint.model_validate(
        pending.model_copy(
            update={
                "revision": 2,
                "status": "approved",
                "actor": "user",
                "previous_sha256": pending.checkpoint_sha256,
            }
        ).model_dump()
    )
    assert approved.binding_sha256 == pending.binding_sha256
    assert approved.checkpoint_sha256 != pending.checkpoint_sha256
    assert PlanReviewCheckpoint.model_validate_json(approved.model_dump_json()) == approved


def test_legacy_run_wire_omits_review_marker_and_lifecycle_does_not_rebind() -> None:
    now = _pending().created_at
    run = Run(
        run_id="run_" + "2" * 32,
        project_id="prj_" + "1" * 32,
        correlation_id="corr_" + "3" * 32,
        goal="A bounded change",
        base_revision="c" * 40,
        target_status_fingerprint="d" * 64,
        created_at=now,
        updated_at=now,
    )
    assert "plan_review_required" not in run.model_dump(mode="json")
    assert "model_bindings_sha256" not in run.model_dump(mode="json")
    assert plan_review_run_sha256(run) == plan_review_run_sha256(
        run.model_copy(
            update={
                "status": RunStatus.CANCELLED,
                "updated_at": now + timedelta(minutes=1),
            }
        )
    )
    assert plan_review_run_sha256(run) != plan_review_run_sha256(
        run.model_copy(
            update={
                "plan_review_required": True,
            }
        )
    )


def test_profile_and_review_schemas_export_bounded_non_authorizing_records() -> None:
    names = {
        "model-profile.schema.json",
        "project-model-selection.schema.json",
        "resolved-model-binding.schema.json",
        "run-model-bindings.schema.json",
        "model-configuration-audit.schema.json",
        "plan-review-binding.schema.json",
        "plan-review-checkpoint.schema.json",
    }
    for name in names:
        assert SCHEMAS[name].model_json_schema()["additionalProperties"] is False
    checkpoint = SCHEMAS["plan-review-checkpoint.schema.json"].model_json_schema()["properties"]
    assert checkpoint["revision"]["minimum"] == 1 and checkpoint["revision"]["maximum"] == 3
    assert checkpoint["status"]["enum"] == ["pending", "approved", "consumed"]
    assert not {"tool_intent", "credential_ref", "grant", "permission"}.intersection(checkpoint)
    bindings = SCHEMAS["run-model-bindings.schema.json"].model_json_schema()["properties"]
    assert bindings["roles"]["maxProperties"] == 64
