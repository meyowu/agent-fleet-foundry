"""Trusted durable accounting sideband; no provider objects or message histories."""

from __future__ import annotations

from typing import Protocol

from agent_fleet.domain.budgets import (
    ModelRequestReservation,
    RunBudgetLimits,
    RunBudgetSnapshot,
    RuntimeAttemptStatus,
)
from agent_fleet.domain.errors import ErrorCode
from agent_fleet.domain.models import AgentInvocation, UsageRecord


class RuntimeAccounting(Protocol):
    @property
    def attempt_id(self) -> str: ...

    def reserve_request(
        self, request_sequence: int, *, requested_tokens: int
    ) -> ModelRequestReservation: ...

    def record_response(
        self, reservation: ModelRequestReservation, usage: UsageRecord
    ) -> RunBudgetSnapshot: ...

    def record_unknown(self, reservation: ModelRequestReservation) -> None: ...

    def reserve_tool_batch(self, batch_sequence: int, call_ids: tuple[str, ...]) -> None: ...

    def record_simulated_step(self) -> None: ...

    def remaining_active_seconds(self) -> float: ...

    def finish(
        self, status: RuntimeAttemptStatus, *, error_code: ErrorCode | None = None
    ) -> RunBudgetSnapshot: ...


class RuntimeBudgetStore(Protocol):
    def initialize_run(
        self, run_id: str, limits: RunBudgetLimits, *, parent_run_id: str | None = None
    ) -> RunBudgetSnapshot: ...

    def begin_attempt(
        self, request: AgentInvocation, *, attempt_id: str | None = None
    ) -> RuntimeAccounting: ...

    def snapshot(self, run_id: str) -> RunBudgetSnapshot: ...
