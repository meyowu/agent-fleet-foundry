"""Provider-neutral immutable limits and durable runtime accounting records."""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator, model_validator

from agent_fleet.domain.errors import ErrorCode
from agent_fleet.domain.models import (
    AgentInstanceId,
    FrozenStrictModel,
    RoleId,
    RunId,
    RuntimeName,
    TaskId,
    UsageRecord,
    WorkflowStage,
)

RuntimeAttemptId = Annotated[str, StringConstraints(pattern=r"^corr_[0-9a-f]{32}$")]


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("runtime accounting timestamps must be timezone-aware UTC")
    return value


class RunBudgetLimits(FrozenStrictModel):
    max_agent_invocations: int = Field(default=64, ge=1, le=10_000, strict=True)
    max_model_requests: int = Field(default=128, ge=1, le=100_000, strict=True)
    max_tool_calls: int = Field(default=512, ge=0, le=100_000, strict=True)
    max_total_tokens: int = Field(default=262_144, ge=1, le=100_000_000, strict=True)
    max_active_seconds: int = Field(default=3600, ge=1, le=86_400, strict=True)


class RuntimeAttemptStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    PAUSED = "paused"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RuntimeAttempt(FrozenStrictModel):
    attempt_id: RuntimeAttemptId
    owner_run_id: RunId
    run_id: RunId
    agent_instance_id: AgentInstanceId
    task_id: TaskId
    role: RoleId
    stage: WorkflowStage
    iteration: int = Field(ge=0, le=100, strict=True)
    max_steps: int = Field(ge=1, le=100, strict=True)
    runtime_name: RuntimeName
    status: RuntimeAttemptStatus = RuntimeAttemptStatus.RUNNING
    started_at: datetime
    finished_at: datetime | None = None
    error_code: ErrorCode | None = None

    _started_utc = field_validator("started_at")(_utc)
    _finished_utc = field_validator("finished_at")(
        lambda value: _utc(value) if value is not None else value
    )

    @model_validator(mode="after")
    def validate_lifecycle(self) -> RuntimeAttempt:
        if (self.status is RuntimeAttemptStatus.RUNNING) != (self.finished_at is None):
            raise ValueError("runtime attempt lifecycle is inconsistent")
        if self.finished_at is not None and self.finished_at < self.started_at:
            raise ValueError("runtime attempt completion precedes its start")
        return self


class ModelRequestReservation(FrozenStrictModel):
    attempt_id: RuntimeAttemptId
    request_sequence: int = Field(ge=1, le=100_000, strict=True)
    token_allowance: int = Field(ge=1, le=100_000_000, strict=True)
    requested_tokens: int = Field(ge=1, le=100_000_000, strict=True)
    reserved_at: datetime

    _reserved_utc = field_validator("reserved_at")(_utc)


class ModelRequestAccounting(FrozenStrictModel):
    reservation: ModelRequestReservation
    outcome: Literal["reserved", "reported", "unknown"] = "reserved"
    usage: UsageRecord | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> ModelRequestAccounting:
        if self.outcome == "reserved" and self.usage is not None:
            raise ValueError("a reserved request cannot carry response usage")
        if self.outcome == "reported" and (self.usage is None or self.usage.total_tokens is None):
            raise ValueError("model request accounting outcome is inconsistent")
        return self


class RunBudgetSnapshot(FrozenStrictModel):
    api_version: Literal["agentfleet.dev/v1alpha1"] = "agentfleet.dev/v1alpha1"
    kind: Literal["RunBudgetSnapshot"] = "RunBudgetSnapshot"
    run_id: RunId
    owner_run_id: RunId | None = None
    limits: RunBudgetLimits | None = None
    completeness: Literal["complete", "legacy_unknown", "unknown_requests"]
    agent_invocations: int = Field(default=0, ge=0)
    model_requests: int = Field(default=0, ge=0)
    simulated_steps: int = Field(default=0, ge=0)
    tool_calls: int = Field(default=0, ge=0)
    reported_input_tokens: int = Field(default=0, ge=0)
    reported_output_tokens: int = Field(default=0, ge=0)
    reported_total_tokens: int = Field(default=0, ge=0)
    reserved_tokens: int = Field(default=0, ge=0)
    unknown_tokens: int = Field(default=0, ge=0)
    outstanding_requests: int = Field(default=0, ge=0)
    unknown_requests: int = Field(default=0, ge=0)
    active_seconds: float = Field(default=0, ge=0)
    reported_costs: dict[str, str] = Field(default_factory=dict, max_length=16)
    exhausted: bool = False
    token_limit_is_pre_spend_billing_cap: Literal[False] = False
