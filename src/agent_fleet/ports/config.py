from __future__ import annotations

from pathlib import Path
from typing import Protocol

from agent_fleet.domain.config import ConfigSnapshot, FleetSpec, VerificationProfile
from agent_fleet.domain.models import SandboxConfiguration
from agent_fleet.domain.repository_profile import RepositoryProfile


class ConfigurationPort(Protocol):
    def default_files(
        self,
        repository_name: str,
        profile: RepositoryProfile | None = None,
        *,
        runtime_name: str = "fake",
        provider_model: str | None = None,
        sandbox_configuration: SandboxConfiguration | None = None,
        trusted_canary: bool = False,
    ) -> dict[str, str]: ...

    def validate_files(self, files: dict[str, str]) -> FleetSpec: ...

    def load(self, path: Path) -> FleetSpec: ...

    def load_snapshot(self, path: Path) -> tuple[FleetSpec, ConfigSnapshot]: ...

    def hash(self, spec: FleetSpec) -> str: ...

    def snapshot_hash(self, snapshot: ConfigSnapshot) -> str: ...

    def verification_profile(
        self,
        spec: FleetSpec,
        snapshot: ConfigSnapshot,
    ) -> VerificationProfile: ...

    def check_apply(self, root: Path, files: dict[str, str]) -> FleetSpec: ...

    def stage(self, root: Path, files: dict[str, str]) -> FleetSpec: ...

    def apply(self, root: Path, files: dict[str, str]) -> FleetSpec: ...
