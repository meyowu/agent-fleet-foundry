"""Packaged definitions and safe collision inspection, never installation."""

from pathlib import Path
from typing import Protocol

from agent_fleet.domain.config import ConfigSnapshot, FleetSpec
from agent_fleet.domain.role_bundles import RoleBundleDefinition


class RoleBundleAssets(Protocol):
    def definitions(self) -> tuple[RoleBundleDefinition, ...]: ...

    def assert_new_paths_absent(self, root: Path, paths: tuple[str, ...]) -> None: ...

    def render(
        self,
        bundle: RoleBundleDefinition,
        spec: FleetSpec,
        snapshot: ConfigSnapshot,
        *,
        workflow_id: str,
        scopes: tuple[str, ...],
        command_ids: tuple[str, ...],
    ) -> dict[str, str]: ...
