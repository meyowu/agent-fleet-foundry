"""Phase-aware local diagnostics."""

from __future__ import annotations

from pathlib import Path

from agent_fleet import __version__
from agent_fleet.application.runtime import RuntimeRegistry
from agent_fleet.domain.errors import FleetError
from agent_fleet.domain.models import (
    DoctorCheck,
    DoctorReport,
    RuntimeCapability,
    RuntimeConfiguration,
    RuntimeCredentialCheck,
    RuntimeCredentialStatus,
)
from agent_fleet.domain.security import MINIMUM_GIT_VERSION, git_version_is_supported
from agent_fleet.ports.diagnostics import SystemDiagnostics
from agent_fleet.ports.repository import RepositoryPort
from agent_fleet.ports.state_store import StateStore

_DOCTOR_RUNTIME_CAPABILITIES = frozenset(
    {
        RuntimeCapability.STRUCTURED_OUTPUT,
        RuntimeCapability.TOOL_CALLING,
    }
)


class DoctorService:
    def __init__(
        self,
        state_root: Path,
        state: StateStore,
        repository: RepositoryPort,
        system: SystemDiagnostics,
        runtime_registry: RuntimeRegistry,
    ) -> None:
        self.state_root = state_root
        self.state = state
        self.repository = repository
        self.system = system
        self.runtime_registry = runtime_registry

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
        git_version = self.system.git_version(current_path)
        git_ok = git_version is not None and git_version_is_supported(git_version)
        minimum_git = ".".join(str(item) for item in MINIMUM_GIT_VERSION)
        checks.append(
            DoctorCheck(
                name="git",
                ok=git_ok,
                required=True,
                detail=(
                    git_version
                    if git_ok
                    else f"{git_version or 'not found'}; Git >= {minimum_git} is required"
                ),
            )
        )
        repository_root: str | None = None
        try:
            info = self.repository.inspect(current_path)
            repository_root = info.root
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
        runtime_configuration = RuntimeConfiguration()
        runtime_selection_valid = True
        if sqlite_ok and repository_root is not None:
            try:
                project = self.state.get_project_by_root(repository_root)
                if project is not None:
                    runtime_configuration = RuntimeConfiguration(
                        runtime_name=project.runtime_name,
                        provider_model=project.provider_model,
                        credential_ref=project.credential_ref,
                    )
            except (FleetError, ValueError):
                runtime_selection_valid = False
        checks.append(
            self._provider_credential_check(runtime_configuration, runtime_selection_valid)
        )
        docker_version = self.system.docker_version(current_path)
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
        warnings = [
            (
                "Provider diagnostics inspect local credential presence and validity only; "
                "they do not reveal values or contact a model."
            ),
            "security_level=fake provides no OS isolation and executes no project code.",
        ]
        healthy = all(check.ok for check in checks if check.required)
        return DoctorReport(healthy=healthy, checks=checks, warnings=warnings)

    def _provider_credential_check(
        self,
        configuration: RuntimeConfiguration,
        selection_valid: bool,
    ) -> DoctorCheck:
        status = RuntimeCredentialStatus.INVALID
        ready = False
        preflight_error_code: str | None = None
        if selection_valid:
            try:
                preflight = self.runtime_registry.inspect(
                    configuration,
                    required_capabilities=_DOCTOR_RUNTIME_CAPABILITIES,
                    credential_check=RuntimeCredentialCheck.INSPECT,
                )
            except FleetError as error:
                preflight_error_code = error.code.value
            else:
                status = preflight.credential_status
                ready = preflight.ready
        if configuration.runtime_name == "fake":
            expected_statuses = {RuntimeCredentialStatus.NOT_SELECTED}
        else:
            expected_statuses = {
                RuntimeCredentialStatus.CONFIGURED,
                RuntimeCredentialStatus.MISSING,
                RuntimeCredentialStatus.INVALID,
            }
        if status not in expected_statuses:
            status = RuntimeCredentialStatus.INVALID
            ready = False
        model_detail = (
            f", model={configuration.provider_model}" if configuration.provider_model else ""
        )
        preflight_detail = (
            f"; preflight={preflight_error_code}" if preflight_error_code is not None else ""
        )
        selection_detail = "runtime selection invalid; " if not selection_valid else ""
        return DoctorCheck(
            name="provider_credential",
            ok=ready
            and status
            in {
                RuntimeCredentialStatus.NOT_REQUIRED,
                RuntimeCredentialStatus.NOT_SELECTED,
                RuntimeCredentialStatus.CONFIGURED,
            },
            required=not selection_valid or configuration.runtime_name != "fake",
            detail=(
                f"{selection_detail}runtime={configuration.runtime_name}{model_detail}; "
                f"provider credential status={status.value}{preflight_detail}."
            ),
        )
