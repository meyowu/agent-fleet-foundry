from __future__ import annotations

from pathlib import Path
from typing import Literal, Protocol

from agent_fleet.domain.config import ConfigSnapshot, FleetSpec, VerificationProfile
from agent_fleet.domain.models import SandboxConfiguration
from agent_fleet.domain.repository_profile import RepositoryProfile
from agent_fleet.domain.role_templates import ResolvedRoleTemplate


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

    def snapshot_from_files(self, files: dict[str, str]) -> tuple[FleetSpec, ConfigSnapshot]: ...

    def hash(self, spec: FleetSpec) -> str: ...

    def snapshot_hash(self, snapshot: ConfigSnapshot) -> str: ...

    def role_templates(
        self, spec: FleetSpec, snapshot: ConfigSnapshot
    ) -> dict[str, ResolvedRoleTemplate]: ...

    def verification_profile(
        self,
        spec: FleetSpec,
        snapshot: ConfigSnapshot,
    ) -> VerificationProfile: ...

    def required_verification_commands(
        self,
        spec: FleetSpec,
        snapshot: ConfigSnapshot,
        *,
        workflow_id: str,
        allowed_paths: tuple[str, ...],
        change_kind: Literal["read_only", "code_change"],
    ) -> tuple[str, ...]: ...

    def check_apply(self, root: Path, files: dict[str, str]) -> FleetSpec: ...

    def stage(self, root: Path, files: dict[str, str]) -> FleetSpec: ...

    def apply(self, root: Path, files: dict[str, str]) -> FleetSpec: ...
