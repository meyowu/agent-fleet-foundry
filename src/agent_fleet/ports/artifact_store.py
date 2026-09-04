from __future__ import annotations

from typing import Protocol


class ArtifactStore(Protocol):
    def put(self, content: bytes) -> tuple[str, str, int]: ...

    def get(self, content_ref: str, expected_sha256: str) -> bytes: ...
