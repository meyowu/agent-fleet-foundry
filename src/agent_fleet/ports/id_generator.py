from __future__ import annotations

from typing import Protocol

from agent_fleet.domain.ids import IdPrefix


class IdGenerator(Protocol):
    def new(self, prefix: IdPrefix) -> str: ...
