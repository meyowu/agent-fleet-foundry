from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from agent_fleet.domain.graph import (
    GraphDriverClaim,
    GraphJoinPreparation,
)


@pytest.mark.parametrize("generation", [0, -1, True, "1"])
def test_driver_generation_is_strict_and_positive(generation: object) -> None:
    with pytest.raises(ValidationError):
        GraphDriverClaim.model_validate(
            {
                "parent_run_id": "run_" + "a" * 32,
                "plan_sha256": "b" * 64,
                "claim_id": "corr_" + "c" * 32,
                "generation": generation,
                "claimed_at": datetime.now(UTC),
            }
        )


@pytest.mark.parametrize(
    "instant", [datetime(2026, 9, 5), datetime(2026, 9, 5, tzinfo=timezone(timedelta(hours=1)))]
)
def test_driver_timestamp_requires_utc(instant: datetime) -> None:
    with pytest.raises(ValidationError):
        GraphDriverClaim(
            parent_run_id="run_" + "a" * 32,
            plan_sha256="b" * 64,
            claim_id="corr_" + "c" * 32,
            generation=1,
            claimed_at=instant,
        )


def test_join_order_is_canonical_and_receipt_cannot_contain_unknown_fields() -> None:
    items = [
        {
            "node_id": f"writer-{i}",
            "child_run_id": "run_" + str(i) * 32,
            "child_task_id": "task_" + str(i) * 32,
            "patch_artifact_id": "art_" + str(i) * 32,
            "patch_sha256": "a" * 64,
            "report_artifact_id": "art_" + str(i + 2) * 32,
            "report_sha256": "b" * 64,
        }
        for i in range(2)
    ]
    data = {
        "parent_run_id": "run_" + "a" * 32,
        "parent_task_id": "task_" + "b" * 32,
        "config_snapshot_sha256": "c" * 64,
        "plan_sha256": "d" * 64,
        "base_revision": "e" * 40,
        "ordered_inputs": items,
        "created_at": datetime.now(UTC),
    }
    receipt = GraphJoinPreparation.model_validate(data)
    assert len(receipt.preparation_sha256) == 64
    with pytest.raises(ValidationError):
        GraphJoinPreparation.model_validate({**data, "ordered_inputs": list(reversed(items))})
    with pytest.raises(ValidationError):
        GraphJoinPreparation.model_validate({**data, "auto_reclaim": True})
