from __future__ import annotations

import base64
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

from agent_fleet.application.doctor import DoctorService
from agent_fleet.application.runtime import RuntimeRegistry
from agent_fleet.application.sandboxes import (
    SandboxRegistry,
    requirements_for_configuration,
)
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import (
    Project,
    RepositoryInfo,
    RuntimeCapability,
    RuntimeConfiguration,
    RuntimeCredentialCheck,
    RuntimeCredentialStatus,
    RuntimePreflight,
    SandboxCapabilities,
    SandboxConfiguration,
    SandboxPreflight,
    SandboxSecurityLevel,
)
from agent_fleet.domain.security import Redactor, canonical_json_hash
from agent_fleet.ports.diagnostics import SystemDiagnostics
from agent_fleet.ports.repository import RepositoryPort
from agent_fleet.ports.state_store import StateStore

_CAPABILITIES = frozenset(
    {
        RuntimeCapability.STRUCTURED_OUTPUT,
        RuntimeCapability.TOOL_CALLING,
    }
)


class DoctorState:
    def __init__(self, project: Project | None) -> None:
        self.project = project
        self.roots: list[str] = []

    def migrate(self) -> int:
        return 1

    def get_project_by_root(self, canonical_root: str) -> Project | None:
        self.roots.append(canonical_root)
        return self.project


class CorruptDoctorState(DoctorState):
    def get_project_by_root(self, canonical_root: str) -> Project | None:
        self.roots.append(canonical_root)
        raise FleetError(
            ErrorCode.STATE_UNAVAILABLE,
            "corrupt provider state with untrusted detail",
            "repair state",
        )


class DoctorRepository:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def inspect(self, root: Path) -> RepositoryInfo:
        del root
        return RepositoryInfo(
            root=str(self.root),
            head_revision="a" * 40,
            remote_fingerprint=None,
            identity_hash="b" * 64,
            status_porcelain="",
            status_fingerprint="c" * 64,
            dirty_paths=[],
        )


class HealthySystem:
    def python_version(self) -> tuple[bool, str]:
        return True, "3.14.0"

    def git_version(self, *untrusted_roots: Path) -> str:
        del untrusted_roots
        return "git version 2.45.0"

    def docker_version(self, *untrusted_roots: Path) -> None:
        del untrusted_roots
        return None

    def sqlite_version(self) -> str:
        return "3.50.0"

    def state_directory_writable(self, path: Path) -> tuple[bool, str]:
        return True, f"Writable state directory: {path}"


class NoPathDockerSystem(HealthySystem):
    def docker_version(self, *untrusted_roots: Path) -> None:
        del untrusted_roots
        raise AssertionError("doctor must not resolve Docker from PATH")


class RecordingSandboxRegistry:
    def __init__(self, preflight: SandboxPreflight) -> None:
        self.response = preflight
        self.calls: list[tuple[SandboxConfiguration, object]] = []

    async def preflight(
        self,
        configuration: SandboxConfiguration,
        requirements: object,
    ) -> SandboxPreflight:
        self.calls.append((configuration, requirements))
        return self.response


class RecordingDoctorRegistry:
    def __init__(
        self,
        status: RuntimeCredentialStatus,
        *,
        ready: bool,
        error: FleetError | None = None,
    ) -> None:
        self.status = status
        self.ready = ready
        self.error = error
        self.calls: list[
            tuple[RuntimeConfiguration, frozenset[RuntimeCapability], RuntimeCredentialCheck]
        ] = []

    def inspect(
        self,
        configuration: RuntimeConfiguration,
        *,
        required_capabilities: Iterable[RuntimeCapability],
        credential_check: RuntimeCredentialCheck,
    ) -> RuntimePreflight:
        self.calls.append((configuration, frozenset(required_capabilities), credential_check))
        if self.error is not None:
            raise self.error
        return RuntimePreflight(
            runtime_name=configuration.runtime_name,
            ready=self.ready,
            capabilities=_CAPABILITIES,
            credential_status=self.status,
            diagnostic="Local credential presence inspection completed without a provider call.",
        )


def _project(root: Path) -> Project:
    now = datetime(2026, 9, 4, tzinfo=UTC)
    return Project(
        project_id=f"prj_{'0' * 32}",
        canonical_root=str(root.resolve()),
        identity_hash="b" * 64,
        runtime_name="pydantic-ai",
        provider_model="openai:gpt-5-mini",
        credential_ref="env:DOCTOR_PROVIDER_KEY",
        created_at=now,
        updated_at=now,
    )


def _docker_project(root: Path) -> Project:
    now = datetime(2026, 9, 4, tzinfo=UTC)
    configuration = SandboxConfiguration(provider="docker", image="fleet-runner:test")
    return Project(
        project_id=f"prj_{'1' * 32}",
        canonical_root=str(root.resolve()),
        identity_hash="b" * 64,
        sandbox_name="docker",
        sandbox_configuration=configuration,
        sandbox_image_identity="sha256:" + "c" * 64,
        sandbox_daemon_identity="d" * 64,
        created_at=now,
        updated_at=now,
    )


def _docker_preflight(
    configuration: SandboxConfiguration,
    *,
    image_identity: str = "sha256:" + "c" * 64,
    daemon_identity: str = "d" * 64,
) -> SandboxPreflight:
    capabilities = SandboxCapabilities(
        provider="docker",
        security_level=SandboxSecurityLevel.ISOLATED,
        isolation_enforced=True,
        executes_code=True,
        supported_network_modes=("none",),
        supports_resource_limits=True,
        supports_recovery=True,
        supports_non_root=True,
        supports_read_only_root=True,
        supports_no_new_privileges=True,
        supports_capability_drop=True,
    )
    requirements = requirements_for_configuration(configuration)
    return SandboxPreflight(
        provider="docker",
        ready=True,
        capabilities=capabilities,
        configuration_hash=canonical_json_hash(configuration.model_dump(mode="json")),
        requirements_hash=canonical_json_hash(requirements.model_dump(mode="json")),
        image_identity=image_identity,
        daemon_identity=daemon_identity,
        recovery_scope_id="e" * 32,
        executable_path="/Applications/Docker.app/Contents/Resources/bin/docker",
        cli_version="28.3.3",
        daemon_os="linux",
        daemon_architecture="arm64",
        daemon_server_version="28.3.3",
        endpoint_kind="local-unix",
        diagnostic="inspect-only",
        checked_at=datetime(2026, 9, 4, tzinfo=UTC),
    )


def _doctor(
    tmp_path: Path,
    project: Project | None,
    registry: RecordingDoctorRegistry,
) -> tuple[DoctorService, DoctorState]:
    state = DoctorState(project)
    return (
        DoctorService(
            tmp_path / "state",
            cast(StateStore, state),
            cast(RepositoryPort, DoctorRepository(tmp_path / "repository")),
            cast(SystemDiagnostics, HealthySystem()),
            cast(RuntimeRegistry, registry),
        ),
        state,
    )


@pytest.mark.asyncio
async def test_doctor_reports_fake_runtime_credential_as_not_selected(tmp_path: Path) -> None:
    registry = RecordingDoctorRegistry(RuntimeCredentialStatus.NOT_SELECTED, ready=True)
    doctor, state = _doctor(tmp_path, None, registry)

    report = await doctor.inspect(tmp_path / "repository")

    credential = next(check for check in report.checks if check.name == "provider_credential")
    assert credential.ok is True
    assert credential.required is False
    assert credential.detail == "runtime=fake; provider credential status=not_selected."
    assert report.healthy is True
    [(configuration, capabilities, credential_check)] = registry.calls
    assert configuration == RuntimeConfiguration()
    assert capabilities == _CAPABILITIES
    assert credential_check is RuntimeCredentialCheck.INSPECT
    assert state.roots == [str((tmp_path / "repository").resolve())]


@pytest.mark.asyncio
async def test_doctor_treats_corrupt_project_runtime_state_as_required_failure(
    tmp_path: Path,
) -> None:
    state = CorruptDoctorState(None)
    registry = RecordingDoctorRegistry(RuntimeCredentialStatus.NOT_SELECTED, ready=True)
    doctor = DoctorService(
        tmp_path / "state",
        cast(StateStore, state),
        cast(RepositoryPort, DoctorRepository(tmp_path / "repository")),
        cast(SystemDiagnostics, HealthySystem()),
        cast(RuntimeRegistry, registry),
    )

    report = await doctor.inspect(tmp_path / "repository")

    credential = next(check for check in report.checks if check.name == "provider_credential")
    assert credential.required is True
    assert credential.ok is False
    assert "runtime selection invalid" in credential.detail
    assert "provider credential status=invalid" in credential.detail
    assert "untrusted detail" not in credential.detail
    assert report.healthy is False
    assert registry.calls == []


@pytest.mark.asyncio
async def test_doctor_preserves_safe_preflight_error_code_without_message(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path / "repository")
    registry = RecordingDoctorRegistry(
        RuntimeCredentialStatus.INVALID,
        ready=False,
        error=FleetError(
            ErrorCode.PROVIDER_UNSUPPORTED,
            "untrusted provider detail",
            "untrusted remediation",
        ),
    )
    doctor, _state = _doctor(tmp_path, project, registry)

    report = await doctor.inspect(tmp_path / "repository")

    credential = next(check for check in report.checks if check.name == "provider_credential")
    assert credential.required is True
    assert credential.ok is False
    assert "preflight=PROVIDER_UNSUPPORTED" in credential.detail
    assert "untrusted" not in credential.detail
    assert report.healthy is False


@pytest.mark.parametrize(
    ("status", "ready", "expected_ok", "expected_healthy"),
    [
        (RuntimeCredentialStatus.CONFIGURED, True, True, True),
        (RuntimeCredentialStatus.MISSING, False, False, False),
        (RuntimeCredentialStatus.INVALID, False, False, False),
    ],
)
@pytest.mark.asyncio
async def test_doctor_reports_selected_provider_status_without_reference_or_provider_call(
    tmp_path: Path,
    status: RuntimeCredentialStatus,
    ready: bool,
    expected_ok: bool,
    expected_healthy: bool,
) -> None:
    project = _project(tmp_path / "repository")
    registry = RecordingDoctorRegistry(status, ready=ready)
    doctor, _state = _doctor(tmp_path, project, registry)

    report = await doctor.inspect(tmp_path / "repository")

    credential = next(check for check in report.checks if check.name == "provider_credential")
    assert credential.ok is expected_ok
    assert credential.required is True
    assert f"provider credential status={status.value}" in credential.detail
    assert "runtime=pydantic-ai" in credential.detail
    assert "model=openai:gpt-5-mini" in credential.detail
    serialized = report.model_dump_json()
    assert project.credential_ref is not None
    assert project.credential_ref not in serialized
    assert "DOCTOR_PROVIDER_KEY" not in serialized
    assert report.healthy is expected_healthy
    [(configuration, capabilities, credential_check)] = registry.calls
    assert configuration.credential_ref == project.credential_ref
    assert capabilities == _CAPABILITIES
    assert credential_check is RuntimeCredentialCheck.INSPECT


@pytest.mark.asyncio
async def test_docker_doctor_uses_only_fixed_provider_preflight_and_reports_bindings(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    project = _docker_project(repository_root)
    state = DoctorState(project)
    runtime_registry = RecordingDoctorRegistry(
        RuntimeCredentialStatus.NOT_SELECTED,
        ready=True,
    )
    configuration = project.sandbox_configuration
    assert configuration is not None
    sandbox_registry = RecordingSandboxRegistry(_docker_preflight(configuration))
    doctor = DoctorService(
        tmp_path / "state",
        cast(StateStore, state),
        cast(RepositoryPort, DoctorRepository(repository_root)),
        cast(SystemDiagnostics, NoPathDockerSystem()),
        cast(RuntimeRegistry, runtime_registry),
        cast(SandboxRegistry, sandbox_registry),
    )

    report = await doctor.inspect(repository_root)

    assert report.healthy is True
    preflight_check = next(item for item in report.checks if item.name == "sandbox_preflight")
    docker_check = next(item for item in report.checks if item.name == "docker")
    assert preflight_check.ok is True
    assert "daemon_identity=" + "d" * 64 in preflight_check.detail
    assert "platform=linux/arm64" in preflight_check.detail
    assert docker_check.ok is True
    assert docker_check.required is True
    assert "trusted_cli=/Applications/Docker.app/Contents/Resources/bin/docker" in (
        docker_check.detail
    )
    assert "client=28.3.3" in docker_check.detail
    assert "server=28.3.3" in docker_check.detail
    assert sandbox_registry.calls == [
        (configuration, requirements_for_configuration(configuration))
    ]


@pytest.mark.asyncio
async def test_docker_doctor_redacts_registered_metadata_forms(tmp_path: Path) -> None:
    repository_root = tmp_path / "repository"
    project = _docker_project(repository_root)
    configuration = project.sandbox_configuration
    assert configuration is not None
    secret = "doctor-docker-metadata-secret"
    encoded = base64.b64encode(secret.encode()).decode()
    preflight = _docker_preflight(configuration).model_copy(
        update={
            "cli_version": secret,
            "daemon_server_version": encoded,
            "executable_path": f"/trusted/{secret}/docker",
        }
    )
    doctor = DoctorService(
        tmp_path / "state",
        cast(StateStore, DoctorState(project)),
        cast(RepositoryPort, DoctorRepository(repository_root)),
        cast(SystemDiagnostics, NoPathDockerSystem()),
        cast(
            RuntimeRegistry,
            RecordingDoctorRegistry(RuntimeCredentialStatus.NOT_SELECTED, ready=True),
        ),
        cast(SandboxRegistry, RecordingSandboxRegistry(preflight)),
        Redactor([secret]),
    )

    report = await doctor.inspect(repository_root)
    serialized = report.model_dump_json()

    assert secret not in serialized
    assert encoded not in serialized
    assert "<redacted:1>" in serialized


@pytest.mark.asyncio
async def test_registered_docker_doctor_fails_closed_on_image_binding_drift(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    project = _docker_project(repository_root)
    configuration = project.sandbox_configuration
    assert configuration is not None
    sandbox_registry = RecordingSandboxRegistry(
        _docker_preflight(
            configuration,
            image_identity="sha256:" + "f" * 64,
        )
    )
    doctor = DoctorService(
        tmp_path / "state",
        cast(StateStore, DoctorState(project)),
        cast(RepositoryPort, DoctorRepository(repository_root)),
        cast(SystemDiagnostics, NoPathDockerSystem()),
        cast(
            RuntimeRegistry,
            RecordingDoctorRegistry(RuntimeCredentialStatus.NOT_SELECTED, ready=True),
        ),
        cast(SandboxRegistry, sandbox_registry),
    )

    report = await doctor.inspect(repository_root)

    assert report.healthy is False
    preflight_check = next(item for item in report.checks if item.name == "sandbox_preflight")
    docker_check = next(item for item in report.checks if item.name == "docker")
    assert preflight_check.ok is False
    assert "SANDBOX_BINDING_DRIFTED" in preflight_check.detail
    assert docker_check.ok is False
