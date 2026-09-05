from __future__ import annotations

from pathlib import Path
from typing import Protocol

from agent_fleet.domain.models import (
    ApplyResult,
    PatchInfo,
    RepositoryInfo,
    Workspace,
    WorkspaceKind,
)
from agent_fleet.domain.repository_boundary import OrganizationRepositoryBoundary


class RepositoryPort(Protocol):
    def inspect(self, root: Path) -> RepositoryInfo: ...

    def inspect_organization_boundary(self, root: Path) -> OrganizationRepositoryBoundary: ...

    def prepare_workspace(
        self, run_id: str, base_revision: str, kind: WorkspaceKind
    ) -> Workspace: ...

    def materialize_workspace(self, repository_root: Path, workspace: Workspace) -> Workspace: ...

    def create_workspace(
        self,
        repository_root: Path,
        run_id: str,
        base_revision: str,
        kind: WorkspaceKind,
    ) -> Workspace: ...

    def apply_patch_to_workspace(self, workspace: Workspace, patch: bytes) -> None: ...

    def compute_patch(self, workspace: Workspace) -> PatchInfo: ...

    def patch_changed_paths(self, patch: bytes) -> list[str]: ...

    def workspace_status_fingerprint(self, workspace: Workspace) -> str: ...

    def apply_patch_to_target(
        self,
        repository_root: Path,
        patch: bytes,
        expected_identity_hash: str,
        expected_base_revision: str,
        expected_status_fingerprint: str,
    ) -> ApplyResult: ...

    def cleanup_workspace(self, repository_root: Path, workspace: Workspace) -> None: ...

    def create_canary_fixture(self, destination: Path) -> Path: ...

    def create_bootstrap_canary_fixture(self, destination: Path) -> Path: ...
