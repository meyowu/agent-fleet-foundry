from __future__ import annotations

from pathlib import Path
from typing import Protocol

from agent_fleet.domain.config import FleetSpec


class ConfigurationPort(Protocol):
    def default_files(self, repository_name: str) -> dict[str, str]: ...

    def validate_files(self, files: dict[str, str]) -> FleetSpec: ...

    def load(self, path: Path) -> FleetSpec: ...

    def hash(self, spec: FleetSpec) -> str: ...

    def stage(self, root: Path, files: dict[str, str]) -> FleetSpec: ...

    def apply(self, root: Path, files: dict[str, str]) -> FleetSpec: ...
