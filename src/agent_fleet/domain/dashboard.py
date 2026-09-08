"""Bounded, read-only observation contracts; no execution authority."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from pydantic import Field, TypeAdapter

from agent_fleet.domain.models import AgentInstance, FleetEvent, Run, RunId

MAX_DASHBOARD_RUNS = 50
MAX_DASHBOARD_CHILDREN = 16
MAX_DASHBOARD_AGENTS = 128
MAX_DASHBOARD_EVENTS = 50
MAX_DASHBOARD_RESPONSE = 1_048_576
DashboardCursors = dict[RunId, Annotated[int, Field(strict=True, ge=0, le=2**53 - 1)]]
CURSOR_ADAPTER: TypeAdapter[DashboardCursors] = TypeAdapter(
    Annotated[DashboardCursors, Field(max_length=17)]
)


@dataclass(frozen=True, slots=True)
class DashboardCatalog:
    runs: tuple[Run, ...]
    conversation_ids: tuple[str, ...]
    before: int | None


@dataclass(frozen=True, slots=True)
class DashboardReadFrame:
    runs: tuple[Run, ...]
    agents: tuple[AgentInstance, ...]
    events: tuple[FleetEvent, ...]
    cursors: DashboardCursors
    high_watermarks: DashboardCursors
    resync: bool
    truncated_agents: bool
    earlier_events: bool


def checked_cursors(value: object) -> DashboardCursors:
    return CURSOR_ADAPTER.validate_python(value)
