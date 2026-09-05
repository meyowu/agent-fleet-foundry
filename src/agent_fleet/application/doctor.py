"""Phase-aware local diagnostics."""

from __future__ import annotations

from pathlib import Path

from agent_fleet import __version__
from agent_fleet.application.runtime import RuntimeRegistry
from agent_fleet.application.sandboxes import (
    SandboxRegistry,
    requirements_for_configuration,
)
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import (
    DoctorCheck,
    DoctorReport,
    Project,
    RuntimeCapability,
    RuntimeConfiguration,
    RuntimeCredentialCheck,
    RuntimeCredentialStatus,
    SandboxConfiguration,
    SandboxPreflight,
)
from agent_fleet.domain.security import MINIMUM_GIT_VERSION, Redactor, git_version_is_supported
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
        sandboxes: SandboxRegistry | None = None,
        redactor: Redactor | None = None,
    ) -> None:
        self.state_root = state_root
        self.state = state
        self.repository = repository
        self.system = system
        self.runtime_registry = runtime_registry
        self.sandboxes = sandboxes
        self.redactor = redactor or Redactor()

    async def inspect(
        self,
        current_path: Path,
        *,
        sandbox_name: str | None = None,
        docker_image: str | None = None,
    ) -> DoctorReport:
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
        sandbox_configuration = SandboxConfiguration()
        runtime_selection_valid = True
        project: Project | None = None
        if sqlite_ok and repository_root is not None:
            try:
                project = self.state.get_project_by_root(repository_root)
                if project is not None:
                    runtime_configuration = RuntimeConfiguration(
                        runtime_name=project.runtime_name,
                        provider_model=project.provider_model,
                        credential_ref=project.credential_ref,
                    )
                    if project.sandbox_configuration is None:
                        raise ValueError("Project sandbox configuration was not materialized")
                    sandbox_configuration = project.sandbox_configuration
            except (FleetError, ValueError):
                runtime_selection_valid = False
        checks.append(
            self._provider_credential_check(runtime_configuration, runtime_selection_valid)
        )
        sandbox_configuration = self._selected_sandbox_configuration(
            project,
            current=sandbox_configuration,
            sandbox_name=sandbox_name,
            docker_image=docker_image,
        )
        uses_registered_sandbox = (
            project is not None and sandbox_configuration == project.sandbox_configuration
        )
        expected_image_identity = (
            project.sandbox_image_identity
            if project is not None and uses_registered_sandbox
            else None
        )
        expected_daemon_identity = (
            project.sandbox_daemon_identity
            if project is not None and uses_registered_sandbox
            else None
        )
        sandbox_check, sandbox_preflight = await self._sandbox_preflight_check(
            sandbox_configuration,
            expected_image_identity=expected_image_identity,
            expected_daemon_identity=expected_daemon_identity,
        )
        checks.append(sandbox_check)
        docker_selected = sandbox_configuration.provider == "docker"
        docker_ok = sandbox_preflight is not None if docker_selected else False
        docker_detail = "Docker was not inspected because a non-Docker sandbox is selected."
        if docker_selected and sandbox_preflight is not None:
            docker_detail = (
                f"trusted_cli={sandbox_preflight.executable_path}; "
                f"client={sandbox_preflight.cli_version}; "
                f"server={sandbox_preflight.daemon_server_version}; "
                f"platform={sandbox_preflight.daemon_os}/{sandbox_preflight.daemon_architecture}; "
                "endpoint=local-unix."
            )
        elif docker_selected:
            docker_detail = (
                "Trusted Docker CLI/daemon/image preflight failed; no container created."
            )
        checks.append(
            DoctorCheck(
                name="docker",
                ok=docker_ok,
                required=docker_selected,
                detail=docker_detail,
            )
        )
        warnings = [
            (
                "Provider diagnostics inspect local credential presence and validity only; "
                "they do not reveal values or contact a model."
            ),
            self._sandbox_warning(sandbox_configuration),
        ]
        healthy = all(check.ok for check in checks if check.required)
        report = DoctorReport(healthy=healthy, checks=checks, warnings=warnings)
        safe_report, _ = self.redactor.redact_data(report.model_dump(mode="json"))
        return DoctorReport.model_validate(safe_report)

    @staticmethod
    def _selected_sandbox_configuration(
        project: Project | None,
        *,
        current: SandboxConfiguration,
        sandbox_name: str | None,
        docker_image: str | None,
    ) -> SandboxConfiguration:
        if sandbox_name is None:
            if docker_image is not None:
                raise FleetError(
                    ErrorCode.CONFIG_INVALID,
                    "A Docker image was supplied without selecting the Docker sandbox.",
                    "Pass --sandbox docker together with --docker-image.",
                )
            return current
        if sandbox_name == "docker" and docker_image is None:
            if project is not None and current.provider == "docker":
                return current
            raise FleetError(
                ErrorCode.CONFIG_INVALID,
                "Docker diagnostics require an explicit local image reference.",
                "Pass --docker-image with the preloaded local runner image.",
            )
        try:
            return SandboxConfiguration(
                provider=sandbox_name,
                image=docker_image,
                network_mode=(
                    "approved-unrestricted" if sandbox_name == "local-unsafe" else "none"
                ),
            )
        except ValueError:
            raise FleetError(
                ErrorCode.CONFIG_INVALID,
                "The requested doctor sandbox selection is invalid.",
                "Use fake, Docker with an explicit local image, or local-unsafe.",
            ) from None

    async def _sandbox_preflight_check(
        self,
        configuration: SandboxConfiguration,
        *,
        expected_image_identity: str | None,
        expected_daemon_identity: str | None,
    ) -> tuple[DoctorCheck, SandboxPreflight | None]:
        if self.sandboxes is None:
            return (
                DoctorCheck(
                    name="sandbox_preflight",
                    ok=configuration.provider == "fake",
                    required=True,
                    detail=f"sandbox={configuration.provider}; preflight registry unavailable.",
                ),
                None,
            )
        try:
            preflight = await self.sandboxes.preflight(
                configuration,
                requirements_for_configuration(configuration),
            )
        except FleetError as error:
            return (
                DoctorCheck(
                    name="sandbox_preflight",
                    ok=False,
                    required=True,
                    detail=(
                        f"sandbox={configuration.provider}; preflight={error.code.value}; "
                        "no container was created."
                    ),
                ),
                None,
            )
        if (
            expected_image_identity is not None
            and preflight.image_identity != expected_image_identity
        ) or (
            expected_daemon_identity is not None
            and preflight.daemon_identity != expected_daemon_identity
        ):
            return (
                DoctorCheck(
                    name="sandbox_preflight",
                    ok=False,
                    required=True,
                    detail=(
                        f"sandbox={configuration.provider}; preflight=SANDBOX_BINDING_DRIFTED; "
                        "no container was created."
                    ),
                ),
                None,
            )
        image_detail = (
            f"; image_identity={preflight.image_identity}"
            if preflight.image_identity is not None
            else ""
        )
        daemon_detail = (
            f"; daemon_identity={preflight.daemon_identity}; "
            f"platform={preflight.daemon_os}/{preflight.daemon_architecture}"
            if preflight.daemon_identity is not None
            else ""
        )
        return (
            DoctorCheck(
                name="sandbox_preflight",
                ok=preflight.ready,
                required=True,
                detail=(
                    f"sandbox={configuration.provider}; endpoint={preflight.endpoint_kind}"
                    f"{image_detail}{daemon_detail}; inspect-only preflight complete."
                ),
            ),
            preflight,
        )

    @staticmethod
    def _sandbox_warning(configuration: SandboxConfiguration) -> str:
        if configuration.provider == "fake":
            return "security_level=fake provides no OS isolation and executes no project code."
        if configuration.provider == "local-unsafe":
            return (
                "security_level=unsafe_host executes directly on the host and cannot provide "
                "independent isolation evidence."
            )
        return (
            "Docker doctor performed inspect-only checks; it did not create a container or "
            "run repository code."
        )

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
