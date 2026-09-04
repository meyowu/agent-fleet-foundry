"""System clock and identifier adapters."""

from __future__ import annotations

from datetime import UTC, datetime

from agent_fleet.domain.ids import IdPrefix, new_id


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class UuidIdGenerator:
    def new(self, prefix: IdPrefix) -> str:
        return new_id(prefix)
