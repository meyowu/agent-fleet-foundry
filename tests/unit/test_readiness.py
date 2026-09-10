from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from agent_fleet.adapters.repository.profile import StaticRepositoryProfiler
from agent_fleet.application.readiness import ReadinessService
from agent_fleet.domain.errors import FleetError
from agent_fleet.domain.models import RepositoryInfo
from agent_fleet.domain.readiness import (
    ReadinessBoundary,
    ReadinessCommand,
    ReadinessDiagnostic,
    ReadinessReport,
    StaticDeclaration,
    StaticManifest,
    StaticReadinessMetadata,
)
from agent_fleet.domain.repository_profile import CommandProvenance, RepositoryCommand
from agent_fleet.domain.security import Redactor
from agent_fleet.ports.config import ConfigurationPort
from agent_fleet.ports.readiness import ReadinessProfilerPort
from agent_fleet.ports.repository import RepositoryPort


def _service(
    tmp_path: Path,
    *,
    metadata: StaticReadinessMetadata | None = None,
    commands: list[RepositoryCommand] | None = None,
    redactor: Redactor | None = None,
) -> ReadinessService:
    (tmp_path / "pyproject.toml").write_text('[project]\ndependencies=["pytest"]\n')
    result = StaticRepositoryProfiler().profile(tmp_path)
    if commands is not None:
        result.profile.commands = commands
    repository = Mock(spec=RepositoryPort)
    repository.inspect.return_value = RepositoryInfo(
        root=str(tmp_path),
        head_revision="a" * 40,
        remote_fingerprint=None,
        identity_hash="b" * 64,
        status_porcelain="",
        status_fingerprint="c" * 64,
        dirty_paths=[],
    )
    profiler = Mock(spec=ReadinessProfilerPort)
    profiler.profile_with_metadata.return_value = (result, metadata or StaticReadinessMetadata())
    return ReadinessService(
        repository, profiler, Mock(spec=ConfigurationPort), redactor or Redactor()
    )


def _command(name: str = "test", argv: list[str] | None = None) -> RepositoryCommand:
    return RepositoryCommand(
        name=name,
        purpose="test",
        executable="python",
        argv=argv or ["-m", "pytest"],
        cwd=".",
        provenance=CommandProvenance(path="pyproject.toml", source="manifest"),
        confidence="high",
    )


def test_complete_static_report_is_never_execution_ready(tmp_path: Path) -> None:
    report = _service(tmp_path).inspect(tmp_path)
    assert report.inspection_complete
    assert report.configuration_status == "absent"
    assert report.environment_status == "unverified"
    assert report.baseline_status == "not_checked"
    assert report.execution_authorized is False
    assert type(report.commands_executed) is int and report.commands_executed == 0
    assert ReadinessReport.model_validate_json(report.model_dump_json()) == report
    with pytest.raises(ValidationError):
        report.inspection_complete = False  # type: ignore[misc]


def test_admission_failure_drops_raw_exception_chain(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.repository.inspect.side_effect = ValueError("PRIVATE parser payload")  # type: ignore[attr-defined]
    with pytest.raises(FleetError) as caught:
        service.inspect(tmp_path)
    assert "PRIVATE" not in str(caught.value)
    assert caught.value.__context__ is None
    assert caught.value.__cause__ is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("environment_status", "ready"),
        ("baseline_status", "passed"),
        ("execution_authorized", True),
        ("execution_authorized", 0),
        ("commands_executed", False),
        ("commands_executed", 1),
        ("inspection_complete", "true"),
        ("omitted_commands", True),
        ("configuration_status", "valid"),
        ("extra_field", "unrecognized"),
    ],
)
def test_report_rejects_false_claims_and_coercions(
    tmp_path: Path, field: str, value: object
) -> None:
    data = _service(tmp_path).inspect(tmp_path).model_dump(mode="json")
    data[field] = value
    with pytest.raises(ValidationError):
        ReadinessReport.model_validate_json(json.dumps(data))


@pytest.mark.parametrize(
    "argv",
    [
        ["-c", "PRIVATE"],
        ["--eval", "PRIVATE"],
        ["https://user:PRIVATE@host"],
        ["-m", "PRIVATE"],
        ["$(PRIVATE)"],
        ["value\nPRIVATE"],
    ],
)
def test_unsafe_command_projection_omits_whole_candidate(tmp_path: Path, argv: list[str]) -> None:
    report = _service(
        tmp_path, commands=[_command(argv=argv)], redactor=Redactor(["PRIVATE"])
    ).inspect(tmp_path)
    assert not report.detected_candidates
    assert not report.inspection_complete
    assert report.omitted_commands == 1
    assert "PRIVATE" not in report.model_dump_json()


def test_aggregate_command_limit_is_explicit(tmp_path: Path) -> None:
    report = _service(tmp_path, commands=[_command(f"test{i}") for i in range(300)]).inspect(
        tmp_path
    )
    assert len(report.detected_candidates) == 256
    assert report.omitted_commands == 44
    assert not report.inspection_complete


def test_registered_metadata_secret_is_not_projected(tmp_path: Path) -> None:
    metadata = StaticReadinessMetadata(
        declarations=(
            StaticDeclaration(
                manifest_path="pyproject.toml",
                ecosystem="python",
                category="dependency",
                name="PRIVATE",
                source_type="registry",
            ),
        )
    )
    report = _service(tmp_path, metadata=metadata, redactor=Redactor(["PRIVATE"])).inspect(tmp_path)
    assert not report.metadata.declarations
    assert report.metadata.omitted_declarations == 1
    assert "PRIVATE" not in report.model_dump_json()


def test_wire_byte_limit_truncates_declarations_honestly(tmp_path: Path) -> None:
    metadata = StaticReadinessMetadata(
        declarations=tuple(
            StaticDeclaration(
                manifest_path="a" * 3900,
                ecosystem="python",
                category="dependency",
                name=f"d{i}",
                source_type="registry",
            )
            for i in range(512)
        )
    )
    report = _service(tmp_path, metadata=metadata).inspect(tmp_path)
    assert len(report.model_dump_json().encode()) <= 1_048_576
    assert report.metadata.omitted_declarations > 0
    assert not report.inspection_complete


def test_wire_limit_covers_configured_commands_and_all_other_collections(tmp_path: Path) -> None:
    data = _service(tmp_path).inspect(tmp_path).model_dump(mode="python")
    long_path = "a" * 4080
    data["detected_candidates"] = ()
    data["configuration_status"] = "valid"
    data["config_snapshot_sha256"] = "d" * 64
    data["configured_commands"] = tuple(
        ReadinessCommand(
            name=f"check{i}",
            purpose="check",
            executable="python",
            argv=("x" * 256,) * 128,
            cwd=".",
            provenance_path=long_path,
            sha256="e" * 64,
        )
        for i in range(32)
    )
    data["boundaries"] = tuple(
        ReadinessBoundary(path=f"{long_path}{i}", ecosystems=("python",)) for i in range(64)
    )
    data["lock_files"] = tuple(f"{long_path}{i}/uv.lock" for i in range(64))
    data["metadata"] = StaticReadinessMetadata(
        manifests=tuple(
            StaticManifest(path=f"{long_path}{i}", ecosystem="python", sha256="f" * 64)
            for i in range(64)
        ),
        diagnostics=tuple(
            ReadinessDiagnostic(code="unsupported_metadata", path=long_path) for _ in range(128)
        ),
    )
    report = ReadinessService._bounded_report(data)
    assert len(report.model_dump_json().encode()) <= 1_048_576
    assert report.omitted_commands > 0
    assert report.metadata.omitted_manifests > 0
    assert report.omitted_boundaries > 0
    assert not report.inspection_complete
    assert report.baseline_status == "not_checked"


def test_nested_command_cannot_coerce_zero_into_authorization(tmp_path: Path) -> None:
    data = _service(tmp_path).inspect(tmp_path).model_dump(mode="json")
    data["detected_candidates"][0]["execution_authorized"] = 0
    with pytest.raises(ValidationError):
        ReadinessReport.model_validate_json(json.dumps(data))
