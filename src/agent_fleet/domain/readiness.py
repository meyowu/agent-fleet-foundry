"""Bounded static observations: neither execution readiness nor baseline evidence."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import (
    ConfigDict,
    Field,
    StringConstraints,
    ValidationInfo,
    field_validator,
    model_validator,
)

from agent_fleet.domain.models import FrozenStrictModel, Sha256
from agent_fleet.domain.repository_profile import CommandPurpose, Confidence, Ecosystem

MAX_READINESS_MANIFESTS = 64
MAX_READINESS_DECLARATIONS = 512
MAX_READINESS_COMMANDS = 256
MAX_READINESS_BOUNDARIES = 64
MAX_READINESS_DIAGNOSTICS = 128
MAX_READINESS_BYTES = 1_048_576

StaticPath = Annotated[
    str, StringConstraints(min_length=1, max_length=4096, pattern=r"^[^:\\\x00]+$")
]
StaticName = Annotated[
    str, StringConstraints(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_@./+-]+$")
]
StaticConstraint = Annotated[
    str,
    StringConstraints(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9.*<>=!~^|, +_-]+$"),
]
DiagnosticCode = Literal[
    "profile_incomplete",
    "manifest_limit",
    "declaration_limit",
    "command_limit",
    "boundary_limit",
    "diagnostic_limit",
    "invalid_declaration",
    "dynamic_declaration",
    "unsupported_dependency_source",
    "unsupported_metadata",
    "unsafe_projection",
    "configuration_invalid",
    "verification_commands_missing",
    "metadata_capture_failed",
    "report_byte_limit",
]


def static_path(value: str) -> str:
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path.as_posix() != value
        or ".." in path.parts
        or any(
            ord(char) < 32 or ord(char) == 127 or 0xD800 <= ord(char) <= 0xDFFF for char in value
        )
        or len(value.encode("utf-8")) > 4096
    ):
        raise ValueError("static provenance must be a bounded canonical logical path")
    return value


class ReadinessModel(FrozenStrictModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, strict=True, revalidate_instances="always"
    )


class ReadinessDiagnostic(ReadinessModel):
    code: DiagnosticCode
    path: StaticPath | None = None

    @field_validator("path")
    @classmethod
    def safe_path(cls, value: str | None) -> str | None:
        return static_path(value) if value is not None else None


class StaticManifest(ReadinessModel):
    path: StaticPath
    ecosystem: Literal["python", "node"]
    sha256: Sha256

    _path = field_validator("path")(static_path)


class StaticDeclaration(ReadinessModel):
    manifest_path: StaticPath
    ecosystem: Literal["python", "node"]
    category: Literal[
        "requires_python",
        "dependency",
        "optional_dependency",
        "dependency_group",
        "dynamic",
        "package_manager",
        "engine",
        "dev_dependency",
    ]
    name: StaticName | None = None
    group: StaticName | None = None
    constraint: StaticConstraint | None = None
    source_type: Literal["registry", "url", "vcs", "path", "workspace", "dynamic", "unsupported"]

    _path = field_validator("manifest_path")(static_path)

    @model_validator(mode="after")
    def source_projection(self) -> StaticDeclaration:
        if self.source_type != "registry" and self.constraint is not None:
            raise ValueError("non-registry declarations cannot retain dependency payloads")
        return self


class StaticReadinessMetadata(ReadinessModel):
    manifests: tuple[StaticManifest, ...] = Field(default=(), max_length=MAX_READINESS_MANIFESTS)
    declarations: tuple[StaticDeclaration, ...] = Field(
        default=(), max_length=MAX_READINESS_DECLARATIONS
    )
    diagnostics: tuple[ReadinessDiagnostic, ...] = Field(
        default=(), max_length=MAX_READINESS_DIAGNOSTICS
    )
    omitted_manifests: int = Field(default=0, ge=0, le=20_000)
    omitted_declarations: int = Field(default=0, ge=0, le=512_000)
    omitted_diagnostics: int = Field(default=0, ge=0, le=512_000)


class ReadinessBoundary(ReadinessModel):
    path: StaticPath
    ecosystems: tuple[Ecosystem, ...] = Field(max_length=8)

    _path = field_validator("path")(static_path)


class ReadinessCommand(ReadinessModel):
    name: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    purpose: CommandPurpose
    executable: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    argv: tuple[Annotated[str, StringConstraints(max_length=4096)], ...] = Field(max_length=128)
    cwd: StaticPath
    provenance_path: StaticPath | None = None
    confidence: Confidence | None = None
    sha256: Sha256
    profile_required: bool = False
    execution_authorized: Literal[False] = False

    _cwd = field_validator("cwd")(static_path)

    @field_validator("provenance_path")
    @classmethod
    def safe_provenance(cls, value: str | None) -> str | None:
        return static_path(value) if value is not None else None

    @field_validator("execution_authorized", mode="before")
    @classmethod
    def exact_false(cls, value: object) -> object:
        if type(value) is not bool:
            raise ValueError("static authorization must be a boolean")
        return value


class ReadinessReport(ReadinessModel):
    api_version: Literal["agentfleet.dev/v1alpha1"] = "agentfleet.dev/v1alpha1"
    kind: Literal["ReadinessReport"] = "ReadinessReport"
    repository_identity: Sha256
    head_revision: Annotated[str, StringConstraints(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")]
    status_fingerprint: Sha256
    dirty: bool
    profile_sha256: Sha256
    configuration_status: Literal["absent", "valid", "invalid"]
    config_snapshot_sha256: Sha256 | None = None
    ecosystems: tuple[Ecosystem, ...] = Field(max_length=8)
    boundaries: tuple[ReadinessBoundary, ...] = Field(max_length=MAX_READINESS_BOUNDARIES)
    lock_files: tuple[StaticPath, ...] = Field(default=(), max_length=64)
    metadata: StaticReadinessMetadata
    detected_candidates: tuple[ReadinessCommand, ...] = Field(max_length=MAX_READINESS_COMMANDS)
    configured_commands: tuple[ReadinessCommand, ...] = Field(max_length=MAX_READINESS_COMMANDS)
    diagnostics: tuple[ReadinessDiagnostic, ...] = Field(max_length=MAX_READINESS_DIAGNOSTICS)
    omitted_commands: int = Field(default=0, ge=0, le=1_000_000)
    omitted_boundaries: int = Field(default=0, ge=0, le=20_000)
    omitted_diagnostics: int = Field(default=0, ge=0, le=1_000_000)
    omitted_lock_files: int = Field(default=0, ge=0, le=20_000)
    environment_status: Literal["unverified"] = "unverified"
    baseline_status: Literal["not_checked"] = "not_checked"
    execution_authorized: Literal[False] = False
    commands_executed: Literal[0] = 0
    inspection_complete: bool
    next_steps: tuple[
        Literal[
            "review_static_issues", "prepare_reviewed_environment", "run_approved_baseline_later"
        ],
        ...,
    ] = Field(min_length=2, max_length=3)

    @field_validator("lock_files")
    @classmethod
    def safe_locks(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            static_path(value)
        return values

    @field_validator("execution_authorized", "commands_executed", mode="before")
    @classmethod
    def exact_non_authorization(cls, value: object, info: ValidationInfo) -> object:
        # Literal equality alone treats False and 0 as interchangeable.
        expected = bool if info.field_name == "execution_authorized" else int
        if type(value) is not expected:
            raise ValueError("static execution fields require their exact types")
        return value

    @model_validator(mode="after")
    def coherent(self) -> ReadinessReport:
        if (self.configuration_status == "valid") != (self.config_snapshot_sha256 is not None):
            raise ValueError("configuration status and snapshot identity disagree")
        incomplete = bool(
            self.diagnostics
            or self.metadata.diagnostics
            or self.omitted_commands
            or self.omitted_boundaries
            or self.omitted_diagnostics
            or self.metadata.omitted_manifests
            or self.metadata.omitted_declarations
            or self.metadata.omitted_diagnostics
            or self.omitted_lock_files
        )
        if self.inspection_complete == incomplete:
            raise ValueError("static inspection completeness disagrees with its gaps")
        if self.configuration_status == "invalid" and not incomplete:
            raise ValueError("invalid configuration requires a static issue")
        expected_steps = (("review_static_issues",) if incomplete else ()) + (
            "prepare_reviewed_environment",
            "run_approved_baseline_later",
        )
        if self.next_steps != expected_steps:
            raise ValueError("static next steps disagree with inspection status")
        if len(self.detected_candidates) + len(self.configured_commands) > MAX_READINESS_COMMANDS:
            raise ValueError("combined command projection exceeds its limit")
        if len(self.diagnostics) + len(self.metadata.diagnostics) > MAX_READINESS_DIAGNOSTICS:
            raise ValueError("combined diagnostics exceed their limit")
        if len(self.model_dump_json().encode("utf-8")) > MAX_READINESS_BYTES:
            raise ValueError("readiness report exceeds its UTF-8 byte limit")
        return self
