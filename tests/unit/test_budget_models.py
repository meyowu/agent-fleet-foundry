from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from agent_fleet.domain.budgets import (
    ModelRequestAccounting,
    ModelRequestReservation,
    RunBudgetLimits,
    RuntimeAttempt,
    RuntimeAttemptStatus,
)
from agent_fleet.domain.models import UsageRecord


@pytest.mark.parametrize(
    "values",
    [
        {"max_agent_invocations": 0},
        {"max_model_requests": True},
        {"max_tool_calls": -1},
        {"max_total_tokens": "100"},
        {"max_active_seconds": 86_401},
        {"allow_budget_increase": True},
    ],
)
def test_budget_limits_are_strict_bounded_and_have_no_escalation_switch(
    values: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        RunBudgetLimits.model_validate(values)


def _reservation() -> ModelRequestReservation:
    return ModelRequestReservation(
        attempt_id="corr_" + "1" * 32,
        request_sequence=1,
        token_allowance=100,
        requested_tokens=100,
        reserved_at=datetime.now(UTC),
    )


def test_partial_unknown_usage_and_explicit_zero_have_distinct_records() -> None:
    reservation = _reservation()
    unknown = ModelRequestAccounting(
        reservation=reservation, outcome="unknown", usage=UsageRecord(requests=1, input_tokens=5)
    )
    assert unknown.usage is not None and unknown.usage.total_tokens is None
    zero = ModelRequestAccounting(
        reservation=reservation,
        outcome="reported",
        usage=UsageRecord(requests=1, total_tokens=0),
    )
    assert zero.usage is not None and zero.usage.total_tokens == 0
    with pytest.raises(ValidationError):
        ModelRequestAccounting(reservation=reservation, outcome="reported", usage=unknown.usage)
    with pytest.raises(ValidationError):
        ModelRequestAccounting(reservation=reservation, usage=zero.usage)


@pytest.mark.parametrize(
    "timestamp", [datetime(2026, 9, 5), datetime(2026, 9, 5, tzinfo=timezone(timedelta(hours=1)))]
)
def test_accounting_timestamps_require_utc(timestamp: datetime) -> None:
    payload = _reservation().model_dump()
    payload["reserved_at"] = timestamp
    with pytest.raises(ValidationError):
        ModelRequestReservation.model_validate(payload)


def test_attempt_lifecycle_cannot_erase_completion_or_reverse_time() -> None:
    now = datetime.now(UTC)
    attempt = RuntimeAttempt(
        attempt_id="corr_" + "1" * 32,
        owner_run_id="run_" + "2" * 32,
        run_id="run_" + "2" * 32,
        agent_instance_id="agent_" + "3" * 32,
        task_id="task_" + "4" * 32,
        role="cos",
        stage="scoping",
        iteration=0,
        max_steps=2,
        runtime_name="fake",
        started_at=now,
    )
    payload = attempt.model_dump()
    payload["status"] = RuntimeAttemptStatus.COMPLETED
    with pytest.raises(ValidationError):
        RuntimeAttempt.model_validate(payload)
    payload["finished_at"] = now - timedelta(seconds=1)
    with pytest.raises(ValidationError):
        RuntimeAttempt.model_validate(payload)
