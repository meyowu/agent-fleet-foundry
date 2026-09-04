"""Artifact registration and redaction policy."""

from __future__ import annotations

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
