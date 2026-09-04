from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

from agent_fleet.application.doctor import DoctorService
from agent_fleet.application.runtime import RuntimeRegistry
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import (
    Project,
    RepositoryInfo,
    RuntimeCapability,
    RuntimeConfiguration,
    RuntimeCredentialCheck,
    RuntimeCredentialStatus,
    RuntimePreflight,
)
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


def test_doctor_reports_fake_runtime_credential_as_not_selected(tmp_path: Path) -> None:
    registry = RecordingDoctorRegistry(RuntimeCredentialStatus.NOT_SELECTED, ready=True)
    doctor, state = _doctor(tmp_path, None, registry)

    report = doctor.inspect(tmp_path / "repository")

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


def test_doctor_treats_corrupt_project_runtime_state_as_required_failure(
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

    report = doctor.inspect(tmp_path / "repository")

    credential = next(check for check in report.checks if check.name == "provider_credential")
    assert credential.required is True
    assert credential.ok is False
    assert "runtime selection invalid" in credential.detail
    assert "provider credential status=invalid" in credential.detail
    assert "untrusted detail" not in credential.detail
    assert report.healthy is False
    assert registry.calls == []


def test_doctor_preserves_safe_preflight_error_code_without_message(
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

    report = doctor.inspect(tmp_path / "repository")

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
def test_doctor_reports_selected_provider_status_without_reference_or_provider_call(
    tmp_path: Path,
    status: RuntimeCredentialStatus,
    ready: bool,
    expected_ok: bool,
    expected_healthy: bool,
) -> None:
    project = _project(tmp_path / "repository")
    registry = RecordingDoctorRegistry(status, ready=ready)
    doctor, _state = _doctor(tmp_path, project, registry)

    report = doctor.inspect(tmp_path / "repository")

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
