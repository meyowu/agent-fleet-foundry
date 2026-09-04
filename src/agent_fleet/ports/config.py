from __future__ import annotations

from pathlib import Path
from typing import Protocol

from agent_fleet.domain.config import ConfigSnapshot, FleetSpec
from agent_fleet.domain.repository_profile import RepositoryProfile


class ConfigurationPort(Protocol):
    def default_files(
        self, repository_name: str, profile: RepositoryProfile | None = None
    ) -> dict[str, str]: ...

    def validate_files(self, files: dict[str, str]) -> FleetSpec: ...

    def load(self, path: Path) -> FleetSpec: ...

    def load_snapshot(self, path: Path) -> tuple[FleetSpec, ConfigSnapshot]: ...

    def hash(self, spec: FleetSpec) -> str: ...

    def snapshot_hash(self, snapshot: ConfigSnapshot) -> str: ...

    def stage(self, root: Path, files: dict[str, str]) -> FleetSpec: ...

    def apply(self, root: Path, files: dict[str, str]) -> FleetSpec: ...
