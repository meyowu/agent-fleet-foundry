"""Artifact registration and redaction policy."""

from __future__ import annotations

from contextlib import suppress

from pydantic import JsonValue

from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.ids import IdPrefix
from agent_fleet.domain.models import ArtifactKind, ArtifactMetadata
from agent_fleet.domain.security import Redactor
from agent_fleet.ports.artifact_store import ArtifactStore
from agent_fleet.ports.clock import Clock
from agent_fleet.ports.id_generator import IdGenerator
from agent_fleet.ports.state_store import StateStore


class ArtifactService:
    def __init__(
        self,
        store: ArtifactStore,
        state: StateStore,
        clock: Clock,
        ids: IdGenerator,
        redactor: Redactor,
    ) -> None:
        self.store = store
        self.state = state
        self.clock = clock
        self.ids = ids
        self.redactor = redactor

    def create_text(
        self,
        *,
        kind: ArtifactKind,
        project_id: str,
        content: str,
        producer: str,
        run_id: str | None = None,
        task_id: str | None = None,
        artifact_id: str | None = None,
        mime_type: str = "text/plain",
        redact: bool = True,
        reject_secret: bool = False,
        metadata: dict[str, JsonValue] | None = None,
    ) -> ArtifactMetadata:
        if reject_secret and self.redactor.contains_secret(content):
            raise FleetError(
                ErrorCode.COMMAND_DENIED,
                "A registered secret value was detected in candidate artifact content.",
                "Remove the secret from the candidate and retry; it was not persisted.",
            )
        if redact:
            content, summary = self.redactor.redact_text(content)
        else:
            summary = []
        content_ref, digest, byte_size = self.store.put(content.encode("utf-8"))
        artifact = ArtifactMetadata(
            artifact_id=artifact_id or self.ids.new(IdPrefix.ARTIFACT),
            kind=kind,
            project_id=project_id,
            run_id=run_id,
            task_id=task_id,
            mime_type=mime_type,
            byte_size=byte_size,
            sha256=digest,
            content_ref=content_ref,
            producer=producer,
            redacted=bool(summary),
            created_at=self.clock.now(),
            metadata=metadata or {},
        )
        self.state.save_artifact(artifact)
        return artifact

    def read_text(self, artifact_id: str) -> str:
        metadata = self.state.get_artifact(artifact_id)
        return self.store.get(metadata.content_ref, metadata.sha256).decode("utf-8")

    def read_bounded_text(self, artifact_id: str, *, max_bytes: int = 16_777_216) -> str:
        """Validate bytes, size, UTF-8 and registered secrets before context use."""
        metadata = self.state.get_artifact(artifact_id)
        if not 0 <= metadata.byte_size <= max_bytes:
            raise _bounded_read_error()
        content = self.store.get(metadata.content_ref, metadata.sha256, max_bytes=max_bytes)
        value: str | None = None
        if len(content) == metadata.byte_size:
            with suppress(UnicodeError):
                value = content.decode("utf-8")
        if value is None or self.redactor.contains_secret(value):
            raise _bounded_read_error()
        return value


def _bounded_read_error() -> FleetError:
    return FleetError(
        ErrorCode.ARTIFACT_INTEGRITY_FAILED,
        "The context artifact exceeds its bound or fails content validation.",
        "Inspect the original artifact; no unvalidated content was used as conversation context.",
    )
