from __future__ import annotations

from typing import Protocol

from agent_fleet.domain.models import FleetEvent


class EventSink(Protocol):
    def emit(self, event: FleetEvent) -> FleetEvent: ...
