"""Trusted whole-directory mechanics; no harness or user-authorization surface."""

from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Protocol

from agent_fleet.domain.models import Project
from agent_fleet.domain.organization_tree import (
    OrganizationTree,
    PreparedPublication,
    PublicationObservation,
)


class OrganizationPublicationSession(Protocol):
    def capture_target(self) -> OrganizationTree: ...

    def stage(self, after: OrganizationTree) -> PreparedPublication: ...

    def observe(self, prepared: PreparedPublication) -> PublicationObservation: ...

    def exchange(self, prepared: PreparedPublication) -> PublicationObservation: ...

    def sync_exchanged(self, prepared: PreparedPublication) -> PublicationObservation: ...

    def cleanup_owned(
        self,
        prepared: PreparedPublication,
        *,
        expected_target_sha256: str,
        expected_backup_sha256: str | None,
        expected_backup_tree: OrganizationTree | None = None,
    ) -> None: ...


class OrganizationFileSystem(Protocol):
    def session(
        self, project: Project, operation_id: str
    ) -> AbstractContextManager[OrganizationPublicationSession]: ...
