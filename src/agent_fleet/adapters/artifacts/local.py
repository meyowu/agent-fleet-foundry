"""Atomic content-addressed local artifact storage."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.security import resolve_logical_path, sha256_bytes


class LocalArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def put(self, content: bytes) -> tuple[str, str, int]:
        digest = sha256_bytes(content)
        content_ref = f"sha256/{digest[:2]}/{digest}"
        destination = self.root / content_ref
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            self._verify(destination, digest)
            return content_ref, digest, len(content)
        descriptor, temporary_name = tempfile.mkstemp(prefix=".artifact-", dir=destination.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        self._verify(destination, digest)
        return content_ref, digest, len(content)

    def get(self, content_ref: str, expected_sha256: str, *, max_bytes: int | None = None) -> bytes:
        if max_bytes is not None and (
            type(max_bytes) is not int or not 1 <= max_bytes <= 16_777_216
        ):
            raise _integrity_error(content_ref)
        if not self.root.exists():
            raise _integrity_error(content_ref)
        content: bytes | None = None
        try:
            path = resolve_logical_path(self.root, content_ref, allow_missing=False)
            if max_bytes is None:
                content = path.read_bytes()
            else:
                with path.open("rb") as stream:
                    content = stream.read(max_bytes + 1)
        except (OSError, ValueError):
            pass
        if content is None:
            # Preserve a typed cause-free boundary for missing/raced/corrupt
            # storage, without exposing an OS exception's absolute state path.
            raise _integrity_error(content_ref)
        if (max_bytes is not None and len(content) > max_bytes) or sha256_bytes(
            content
        ) != expected_sha256:
            raise _integrity_error(content_ref)
        return content

    @staticmethod
    def _verify(path: Path, expected_sha256: str) -> None:
        if sha256_bytes(path.read_bytes()) != expected_sha256:
            raise _integrity_error(str(path.name))


def _integrity_error(content_ref: str) -> FleetError:
    return FleetError(
        ErrorCode.ARTIFACT_INTEGRITY_FAILED,
        f"Artifact content failed integrity verification: {content_ref}.",
        "Do not use this artifact; inspect local storage and rerun the task.",
        details={"content_ref": content_ref},
    )
