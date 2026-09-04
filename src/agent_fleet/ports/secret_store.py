from __future__ import annotations

from typing import Protocol


class SecretStore(Protocol):
    """Reserved Phase 2 boundary; Phase 0/1 implementations resolve nothing."""

    async def is_configured(self, reference: str) -> bool: ...
