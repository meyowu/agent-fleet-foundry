"""Phase-aware local diagnostics."""

from __future__ import annotations

from pathlib import Path

from agent_fleet import __version__
from agent_fleet.domain.errors import FleetError
from agent_fleet.domain.models import DoctorCheck, DoctorReport
from agent_fleet.ports.diagnostics import SystemDiagnostics
from agent_fleet.ports.repository import RepositoryPort
from agent_fleet.ports.state_store import StateStore


class DoctorService:
    def __init__(
        self,
        state_root: Path,
        state: StateStore,
        repository: RepositoryPort,
        system: SystemDiagnostics,
    ) -> None:
        self.state_root = state_root
        self.state = state
        self.repository = repository
        self.system = system

    def inspect(self, current_path: Path) -> DoctorReport:
        checks: list[DoctorCheck] = []
        python_ok, python_version = self.system.python_version()
        checks.append(
            DoctorCheck(
                name="python",
                ok=python_ok,
                required=True,
                detail=f"Python {python_version}; agent-fleet {__version__}",
            )
        )
        git_version = self.system.git_version()
        checks.append(
            DoctorCheck(
                name="git",
                ok=git_version is not None,
                required=True,
                detail=git_version or "not found",
            )
        )
        try:
            info = self.repository.inspect(current_path)
            repository_detail = f"Git repository at {info.root}"
            repository_ok = True
        except FleetError:
            repository_detail = "Current path is not in a Git repository (optional for doctor)."
            repository_ok = False
        checks.append(
            DoctorCheck(
                name="current_repository",
                ok=repository_ok,
                required=False,
                detail=repository_detail,
            )
        )
        writable, write_detail = self.system.state_directory_writable(self.state_root)
        checks.append(
            DoctorCheck(name="state_directory", ok=writable, required=True, detail=write_detail)
        )
        try:
            version = self.state.migrate()
            sqlite_detail = f"SQLite {self.system.sqlite_version()}; schema {version}"
            sqlite_ok = True
        except FleetError as error:
            sqlite_detail = f"SQLite migration failed: {error}"
            sqlite_ok = False
        checks.append(DoctorCheck(name="sqlite", ok=sqlite_ok, required=True, detail=sqlite_detail))
        docker_version = self.system.docker_version()
        docker_detail = "Docker CLI not found; optional until Phase 3."
        if docker_version:
            docker_detail = docker_version
        checks.append(
            DoctorCheck(
                name="docker",
                ok=docker_version is not None,
                required=False,
                detail=docker_detail,
            )
        )
        checks.append(
            DoctorCheck(
                name="provider_credential",
                ok=False,
                required=False,
                detail="Not configured or resolved; live providers are deferred to Phase 2.",
            )
        )
        warnings = [
            "Only FakeRuntimeAdapter and FakeSandboxProvider are implemented.",
            "security_level=fake provides no OS isolation and executes no project code.",
        ]
        healthy = all(check.ok for check in checks if check.required)
        return DoctorReport(healthy=healthy, checks=checks, warnings=warnings)
