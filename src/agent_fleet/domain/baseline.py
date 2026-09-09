"""Model-free baseline contracts: owned canonical bytes, never borrowed authority."""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta
from pathlib import PurePosixPath
from typing import Annotated, Literal, Self
from uuid import uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationInfo,
    WithJsonSchema,
    field_serializer,
    field_validator,
    model_validator,
)

from agent_fleet.domain.evaluation import require_utc
from agent_fleet.domain.models import (
    CommandSpec,
    ImageIdentity,
    ProjectId,
    SandboxCapabilities,
    SandboxConfiguration,
    SandboxRequirements,
    SandboxSpec,
    Sha256,
)
from agent_fleet.domain.security import sha256_bytes

BaselineId = Annotated[str, StringConstraints(pattern=r"^baseline_[0-9a-f]{32}$")]
BaselineReviewId = Annotated[str, StringConstraints(pattern=r"^breview_[0-9a-f]{32}$")]
BaselineAuthorizationId = Annotated[str, StringConstraints(pattern=r"^bauth_[0-9a-f]{32}$")]
BaselineClaimId = Annotated[str, StringConstraints(pattern=r"^bclaim_[0-9a-f]{32}$")]
BaselineWorkspaceId = Annotated[str, StringConstraints(pattern=r"^bws_[0-9a-f]{32}$")]
BaselineSandboxId = Annotated[str, StringConstraints(pattern=r"^bsandbox_[0-9a-f]{32}$")]
BaselineExecutionId = Annotated[str, StringConstraints(pattern=r"^bexec_[0-9a-f]{32}$")]
BaselineLeaseId = Annotated[str, StringConstraints(pattern=r"^blease_[0-9a-f]{32}$")]
BaselineObservationId = Annotated[str, StringConstraints(pattern=r"^bobs_[0-9a-f]{64}$")]
BaselineReportId = Annotated[str, StringConstraints(pattern=r"^brpt_[0-9a-f]{64}$")]
CommitId = Annotated[str, StringConstraints(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")]
InstallationId = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{32}$")]
BaselinePrefix = Literal[
    "baseline", "breview", "bauth", "bclaim", "bws", "bsandbox", "bexec", "blease"
]
SnapshotTag = Literal[
    "command-v1",
    "sandbox-spec-v1",
    "sandbox-policy-v1",
    "sandbox-inspection-v1",
    "capabilities-v1",
    "configuration-v1",
    "requirements-v1",
    "source-manifest-v1",
    "native-handle-v1",
    "cleanup-v1",
]
MAX_REVIEW_BYTES = 131_072
MAX_OBSERVATION_BYTES = 131_072
MAX_REPORT_BYTES = 262_144
MAX_OUTPUT_BYTES = 64_000


def baseline_id(prefix: BaselinePrefix) -> str:
    if prefix not in {
        "baseline",
        "breview",
        "bauth",
        "bclaim",
        "bws",
        "bsandbox",
        "bexec",
        "blease",
    }:
        raise ValueError("unknown baseline identity kind")
    return f"{prefix}_{uuid4().hex}"


def _plain(value: object, depth: int = 0, budget: list[int] | None = None) -> None:
    if budget is None:
        budget = [30_000]
    budget[0] -= 1
    if depth > 24 or budget[0] < 0:
        raise ValueError("baseline JSON exceeds structural bounds")
    if value is None or type(value) in {bool, int, str}:
        return
    if type(value) is float and math.isfinite(value):
        return
    if type(value) is list:
        for item in value:
            _plain(item, depth + 1, budget)
        return
    if type(value) is dict and all(type(key) is str for key in value):
        for item in value.values():
            _plain(item, depth + 1, budget)
        return
    raise ValueError("baseline JSON must contain only finite plain JSON values")


def canonical(value: object, *, limit: int = MAX_REPORT_BYTES) -> bytes:
    _plain(value)
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8", errors="strict")
    if len(raw) > limit:
        raise ValueError("baseline canonical record exceeds byte limit")
    return raw


def decode_json(raw: bytes, *, limit: int = MAX_REPORT_BYTES) -> object:
    if type(raw) is not bytes or not raw or len(raw) > limit:
        raise ValueError("baseline JSON requires bounded owned bytes")

    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate baseline JSON key")
            result[key] = value
        return result

    value = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=pairs)
    _plain(value)
    return value


class BaselineModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        revalidate_instances="always",
        populate_by_name=True,
    )

    def canonical_bytes(self, *, limit: int = MAX_REPORT_BYTES) -> bytes:
        return canonical(self.model_dump(mode="json", by_alias=True), limit=limit)

    @property
    def digest(self) -> str:
        return sha256_bytes(self.canonical_bytes())

    @classmethod
    def from_canonical(cls, raw: bytes, *, limit: int = MAX_REPORT_BYTES) -> Self:
        if canonical(decode_json(raw, limit=limit), limit=limit) != raw:
            raise ValueError("baseline record is not canonical")
        result = cls.model_validate_json(raw)
        if result.canonical_bytes(limit=limit) != raw:
            raise ValueError("baseline record does not match its full schema")
        return result


class BaselineCanonicalSnapshot(BaselineModel):
    schema_tag: SnapshotTag
    canonical_utf8: Annotated[bytes, WithJsonSchema({"type": "string"})] = Field(
        alias="canonical_json"
    )
    sha256: Sha256

    @field_validator("canonical_utf8", mode="before")
    @classmethod
    def owned_bytes(cls, value: object, info: ValidationInfo) -> bytes:
        if info.mode == "json" and type(value) is str:
            return value.encode("utf-8", errors="strict")
        if type(value) is not bytes:
            raise ValueError("snapshot authority must be owned bytes")
        return value

    @field_serializer("canonical_utf8")
    def wire_text(self, value: bytes) -> str:
        return value.decode("utf-8", errors="strict")

    @model_validator(mode="after")
    def integrity(self) -> Self:
        cap = (
            MAX_REVIEW_BYTES if self.schema_tag in {"command-v1", "source-manifest-v1"} else 16_384
        )
        if (
            canonical(decode_json(self.canonical_utf8, limit=cap), limit=cap) != self.canonical_utf8
            or sha256_bytes(self.canonical_utf8) != self.sha256
        ):
            raise ValueError("snapshot content/hash mismatch")
        return self


def freeze_snapshot(tag: SnapshotTag, value: object) -> BaselineCanonicalSnapshot:
    raw = canonical(value)
    return BaselineCanonicalSnapshot(schema_tag=tag, canonical_utf8=raw, sha256=sha256_bytes(raw))


def snapshot_model[T: BaseModel](
    snapshot: BaselineCanonicalSnapshot, tag: SnapshotTag, model: type[T]
) -> T:
    owned = BaselineCanonicalSnapshot.model_validate_json(snapshot.model_dump_json(by_alias=True))
    if owned.schema_tag != tag:
        raise ValueError("snapshot schema mismatch")
    result = model.model_validate_json(owned.canonical_utf8)
    if canonical(result.model_dump(mode="json", by_alias=True)) != owned.canonical_utf8:
        raise ValueError("snapshot schema is incomplete or noncanonical")
    return result


def freeze_command(raw_json: bytes) -> BaselineCanonicalSnapshot:
    decode_json(raw_json, limit=MAX_REVIEW_BYTES)
    command = CommandSpec.model_validate_json(raw_json)
    if (
        command.environment
        or command.network_requirement != "none"
        or command.timeout_seconds > 180
        or command.max_output_bytes > MAX_OUTPUT_BYTES
    ):
        raise ValueError("baseline command exceeds its hard safety ceiling")
    return freeze_snapshot("command-v1", command.model_dump(mode="json"))


def reconstruct_command(snapshot: BaselineCanonicalSnapshot) -> CommandSpec:
    command = snapshot_model(snapshot, "command-v1", CommandSpec)
    if freeze_command(snapshot.canonical_utf8) != snapshot:
        raise ValueError("baseline command binding mismatch")
    return command


def validate_configuration(configuration: SandboxConfiguration) -> None:
    if (
        configuration.provider != "docker"
        or configuration.network_mode != "none"
        or configuration.cpu_limit > 1
        or configuration.memory_mb > 512
        or configuration.pids_limit > 64
        or 2 * configuration.tmpfs_mb + configuration.shm_mb > 256
    ):
        raise ValueError("baseline sandbox exceeds its hard safety ceiling")


class BaselineSandboxPolicy(BaselineModel):
    project_id: ProjectId
    configuration: BaselineCanonicalSnapshot
    requirements: BaselineCanonicalSnapshot
    timeout_seconds: int = Field(ge=1, le=180)
    image_identity: ImageIdentity
    daemon_identity: Sha256
    mount_policy: Literal["baseline-readonly-v1"] = "baseline-readonly-v1"
    environment: tuple[tuple[str, str], ...] = Field(default=(), max_length=0)

    @model_validator(mode="after")
    def controlled(self) -> Self:
        config = snapshot_model(self.configuration, "configuration-v1", SandboxConfiguration)
        validate_configuration(config)
        requirements = snapshot_model(self.requirements, "requirements-v1", SandboxRequirements)
        if (
            not all(
                (
                    requirements.isolation_required,
                    requirements.code_execution_required,
                    requirements.resource_limits_required,
                    requirements.non_root_required,
                    requirements.read_only_root_required,
                    requirements.no_new_privileges_required,
                    requirements.capability_drop_required,
                )
            )
            or requirements.network_mode != "none"
        ):
            raise ValueError("baseline requires complete Docker controls")
        return self


def freeze_sandbox(raw_json: bytes) -> BaselineCanonicalSnapshot:
    decode_json(raw_json, limit=16_384)
    spec = SandboxSpec.model_validate_json(raw_json)
    validate_configuration(spec.configuration)
    if spec.environment or spec.unsafe_local_confirmed or spec.timeout_seconds > 180:
        raise ValueError("baseline sandbox has unreviewed environment or limits")
    snapshot = freeze_snapshot("sandbox-spec-v1", spec.model_dump(mode="json"))
    sandbox_policy(snapshot)
    return snapshot


def reconstruct_sandbox(snapshot: BaselineCanonicalSnapshot) -> SandboxSpec:
    spec = snapshot_model(snapshot, "sandbox-spec-v1", SandboxSpec)
    if freeze_sandbox(snapshot.canonical_utf8) != snapshot:
        raise ValueError("baseline sandbox binding mismatch")
    return spec


def sandbox_policy(snapshot: BaselineCanonicalSnapshot) -> BaselineCanonicalSnapshot:
    spec = snapshot_model(snapshot, "sandbox-spec-v1", SandboxSpec)
    if spec.project_id is None or spec.image_identity is None or spec.daemon_identity is None:
        raise ValueError("baseline sandbox lacks exact identities")
    policy = BaselineSandboxPolicy(
        project_id=spec.project_id,
        configuration=freeze_snapshot(
            "configuration-v1", spec.configuration.model_dump(mode="json")
        ),
        requirements=freeze_snapshot("requirements-v1", spec.requirements.model_dump(mode="json")),
        timeout_seconds=spec.timeout_seconds,
        image_identity=spec.image_identity,
        daemon_identity=spec.daemon_identity,
    )
    return freeze_snapshot("sandbox-policy-v1", policy.model_dump(mode="json", by_alias=True))


class BaselineSourceEntry(BaselineModel):
    path: str = Field(min_length=1, max_length=4096)
    kind: Literal["file"] = "file"
    mode: Literal["100644", "100755"]
    size: int = Field(ge=0, le=2_000_000)
    content_sha256: Sha256

    @field_validator("path")
    @classmethod
    def safe_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if (
            path.is_absolute()
            or not path.parts
            or path.as_posix() != value
            or ".." in path.parts
            or "\\" in value
            or any(part.casefold() == ".git" for part in path.parts)
            or any(ord(char) < 32 or ord(char) == 127 for char in value)
        ):
            raise ValueError("baseline source path is not canonical")
        return value


class BaselineSourceManifest(BaselineModel):
    schema_version: Literal[1] = 1
    entries: tuple[BaselineSourceEntry, ...] = Field(max_length=4096)

    @model_validator(mode="after")
    def complete_tree(self) -> Self:
        paths = tuple(item.path for item in self.entries)
        if (
            paths != tuple(sorted(paths))
            or len({path.casefold() for path in paths}) != len(paths)
            or sum(item.size for item in self.entries) > 32_000_000
        ):
            raise ValueError("baseline source manifest exceeds canonical tree bounds")
        return self


class BaselineReview(BaselineModel):
    schema_version: Literal[1] = 1
    review_id: BaselineReviewId
    baseline_id: BaselineId
    project_id: ProjectId
    project_sha256: Sha256
    repository_identity_sha256: Sha256
    repository_root: str = Field(min_length=1, max_length=4096)
    base_revision: CommitId
    repository_state_sha256: Sha256
    approved_source_sha256: Sha256
    configuration_sha256: Sha256
    trust_policy_sha256: Sha256
    trust_revision: int = Field(ge=0)
    command: BaselineCanonicalSnapshot
    sandbox_policy: BaselineCanonicalSnapshot | None
    capabilities: BaselineCanonicalSnapshot | None
    installation_id: InstallationId
    status: Literal["ready", "not_ready"]
    reason: Literal["ready", "sandbox_unavailable", "image_unavailable", "capability_missing"]
    created_at: datetime
    expires_at: datetime
    max_attempt_seconds: int = Field(default=300, ge=1, le=300)
    source_scope: Literal["whole_committed_tree"] = "whole_committed_tree"

    _utc = field_validator("created_at", "expires_at")(require_utc)

    @model_validator(mode="after")
    def binding(self) -> Self:
        reconstruct_command(self.command)
        if self.expires_at != self.created_at + timedelta(minutes=5):
            raise ValueError("baseline review must expire after exactly five minutes")
        if self.status == "ready":
            if self.reason != "ready" or self.sandbox_policy is None or self.capabilities is None:
                raise ValueError("ready review requires exact sandbox prerequisites")
            policy = snapshot_model(self.sandbox_policy, "sandbox-policy-v1", BaselineSandboxPolicy)
            caps = snapshot_model(self.capabilities, "capabilities-v1", SandboxCapabilities)
            if policy.project_id != self.project_id or caps.provider != "docker":
                raise ValueError("review sandbox owner/capability mismatch")
        elif (
            self.reason == "ready"
            or self.sandbox_policy is not None
            or self.capabilities is not None
        ):
            raise ValueError("not-ready review cannot confer sandbox authority")
        self.canonical_bytes(limit=MAX_REVIEW_BYTES)
        return self


class BaselineAuthorization(BaselineModel):
    authorization_id: BaselineAuthorizationId
    review_id: BaselineReviewId
    baseline_id: BaselineId
    review_sha256: Sha256
    revision: int = Field(ge=0)
    status: Literal["available", "consumed", "revoked"]
    choice: Literal["allow_once"] = "allow_once"
    created_at: datetime
    expires_at: datetime
    consumed_at: datetime | None = None
    revoked_at: datetime | None = None

    _utc = field_validator("created_at", "expires_at")(require_utc)

    @field_validator("consumed_at", "revoked_at")
    @classmethod
    def optional_utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else require_utc(value)

    @model_validator(mode="after")
    def lifecycle(self) -> Self:
        if self.expires_at <= self.created_at:
            raise ValueError("baseline authorization expiry is invalid")
        if (self.status == "consumed") != (self.consumed_at is not None):
            raise ValueError("baseline consumption state is inconsistent")
        if (self.status == "revoked") != (self.revoked_at is not None):
            raise ValueError("baseline revocation state is inconsistent")
        for value in (self.consumed_at, self.revoked_at):
            if value is not None and require_utc(value) < self.created_at:
                raise ValueError("baseline authorization chronology is inconsistent")
        return self


class BaselineExecution(BaselineModel):
    schema_version: Literal[1] = 1
    baseline_id: BaselineId
    review_id: BaselineReviewId
    review_sha256: Sha256
    project_id: ProjectId
    revision: int = Field(ge=0)
    status: Literal[
        "planned",
        "revoked",
        "owned",
        "executing",
        "cleaning",
        "observed",
        "inconclusive",
        "recovery_required",
    ]
    owner_claim_id: BaselineClaimId | None = None
    current_report_sha256: Sha256 | None = None
    created_at: datetime
    updated_at: datetime

    _utc = field_validator("created_at", "updated_at")(require_utc)

    @model_validator(mode="after")
    def lifecycle(self) -> Self:
        if self.updated_at < self.created_at:
            raise ValueError("baseline execution chronology is inconsistent")
        if (self.status in {"planned", "revoked"}) != (self.owner_claim_id is None):
            raise ValueError("baseline execution ownership is inconsistent")
        return self


class BaselineObservationRef(BaselineModel):
    observation_id: BaselineObservationId
    baseline_id: BaselineId
    execution_id: BaselineExecutionId
    record_sha256: Sha256

    @model_validator(mode="after")
    def content_id(self) -> Self:
        if self.observation_id != f"bobs_{self.record_sha256}":
            raise ValueError("baseline observation content identity mismatch")
        return self


class BaselineReportRef(BaselineModel):
    report_id: BaselineReportId
    baseline_id: BaselineId
    record_sha256: Sha256

    @model_validator(mode="after")
    def content_id(self) -> Self:
        if self.report_id != f"brpt_{self.record_sha256}":
            raise ValueError("baseline report content identity mismatch")
        return self


class BaselineCommandObservation(BaselineModel):
    schema_version: Literal[1] = 1
    baseline_id: BaselineId
    project_id: ProjectId
    review_id: BaselineReviewId
    review_sha256: Sha256
    authorization_id: BaselineAuthorizationId
    claim_id: BaselineClaimId
    execution_id: BaselineExecutionId
    workspace_id: BaselineWorkspaceId
    sandbox_id: BaselineSandboxId
    command_sha256: Sha256
    sandbox_policy_sha256: Sha256
    sandbox_spec_sha256: Sha256
    request_sha256: Sha256
    approved_source_sha256: Sha256
    materialized_source_sha256: Sha256
    post_source_sha256: Sha256 | None
    native_handle: BaselineCanonicalSnapshot
    inspection: BaselineCanonicalSnapshot
    started_at: datetime
    completed_at: datetime
    exit_code: int | None = Field(ge=0, le=255)
    timed_out: bool
    cancelled: bool
    capture_truncated: bool
    redaction_truncated: bool
    decoding_replaced: bool
    stdout: str = Field(max_length=MAX_OUTPUT_BYTES)
    stderr: str = Field(max_length=MAX_OUTPUT_BYTES)
    stdout_sha256: Sha256
    stderr_sha256: Sha256

    _utc = field_validator("started_at", "completed_at")(require_utc)

    @model_validator(mode="after")
    def complete_binding(self) -> Self:
        if (
            self.completed_at < self.started_at
            or self.materialized_source_sha256 != self.approved_source_sha256
            or self.native_handle.schema_tag != "native-handle-v1"
            or self.inspection.schema_tag != "sandbox-inspection-v1"
            or len(self.stdout.encode()) + len(self.stderr.encode()) > MAX_OUTPUT_BYTES
            or sha256_bytes(self.stdout.encode()) != self.stdout_sha256
            or sha256_bytes(self.stderr.encode()) != self.stderr_sha256
            or any(
                (ord(char) < 32 and char not in "\n\t") or ord(char) == 127
                for char in self.stdout + self.stderr
            )
        ):
            raise ValueError("baseline observation binding is inconsistent")
        self.canonical_bytes(limit=MAX_OBSERVATION_BYTES)
        return self

    @property
    def conclusive(self) -> bool:
        return (
            self.exit_code is not None
            and not self.timed_out
            and not self.cancelled
            and not self.capture_truncated
            and not self.redaction_truncated
            and self.post_source_sha256 == self.approved_source_sha256
        )


class BaselineReport(BaselineModel):
    schema_version: Literal[1] = 1
    baseline_id: BaselineId
    project_id: ProjectId
    review_id: BaselineReviewId
    review_sha256: Sha256
    authorization_id: BaselineAuthorizationId
    claim_id: BaselineClaimId
    command_sha256: Sha256
    approved_source_sha256: Sha256
    observation: BaselineObservationRef | None
    cleanup_scope_sha256: Sha256
    cleanup_receipt_sha256s: tuple[Sha256, ...] = Field(max_length=3)
    cleanup_complete: bool
    status: Literal["observed", "inconclusive", "recovery_required"]
    observed_exit_code: int | None = Field(ge=0, le=255)
    predecessor_report_sha256: Sha256 | None = None
    completed_at: datetime
    completion_assurance: Literal["baseline_observation_only"] = "baseline_observation_only"
    target_applied: Literal[False] = False
    proof_gaps: tuple[
        Literal[
            "missing_result",
            "output_incomplete",
            "source_drift",
            "cleanup_incomplete",
            "controller_error",
        ],
        ...,
    ] = Field(max_length=5)

    _utc = field_validator("completed_at")(require_utc)

    @model_validator(mode="after")
    def no_inferred_success(self) -> Self:
        if self.observation is not None and self.observation.baseline_id != self.baseline_id:
            raise ValueError("report observation belongs to another baseline")
        if self.status == "observed" and (
            self.observation is None
            or self.observed_exit_code is None
            or not self.cleanup_complete
            or self.proof_gaps
        ):
            raise ValueError("observed report needs complete observed evidence")
        if not self.cleanup_complete and self.status != "recovery_required":
            raise ValueError("incomplete cleanup requires recovery")
        if self.observation is None and self.observed_exit_code is not None:
            raise ValueError("missing observation cannot imply an exit code")
        self.canonical_bytes(limit=MAX_REPORT_BYTES)
        return self
