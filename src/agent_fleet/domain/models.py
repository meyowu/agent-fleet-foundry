"""Canonical Phase 0/1 domain and boundary models."""

from __future__ import annotations

import json
import math
import re
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Annotated, Any, Literal

from pydantic import (
    AliasChoices,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    field_validator,
    model_validator,
)

from agent_fleet.domain.security import canonical_json_hash, sha256_bytes

OpaqueId = Annotated[str, StringConstraints(pattern=r"^[a-z]+_[0-9a-f]{32}$")]
ProjectId = Annotated[str, StringConstraints(pattern=r"^prj_[0-9a-f]{32}$")]
RunId = Annotated[str, StringConstraints(pattern=r"^run_[0-9a-f]{32}$")]
TaskId = Annotated[str, StringConstraints(pattern=r"^task_[0-9a-f]{32}$")]
AgentInstanceId = Annotated[str, StringConstraints(pattern=r"^agent_[0-9a-f]{32}$")]
EventId = Annotated[str, StringConstraints(pattern=r"^evt_[0-9a-f]{32}$")]
ApprovalRequestId = Annotated[str, StringConstraints(pattern=r"^perm_[0-9a-f]{32}$")]
GrantId = Annotated[str, StringConstraints(pattern=r"^grant_[0-9a-f]{32}$")]
ArtifactId = Annotated[str, StringConstraints(pattern=r"^art_[0-9a-f]{32}$")]
IntentId = Annotated[str, StringConstraints(pattern=r"^intent_[0-9a-f]{32}$")]
LeaseId = Annotated[str, StringConstraints(pattern=r"^lease_[0-9a-f]{32}$")]
CorrelationId = Annotated[str, StringConstraints(pattern=r"^corr_[0-9a-f]{32}$")]
SandboxId = Annotated[str, StringConstraints(pattern=r"^sandbox_[0-9a-f]{32}$")]
ExecutionId = Annotated[str, StringConstraints(pattern=r"^exec_[0-9a-f]{32}$")]
WorkspaceId = Annotated[str, StringConstraints(pattern=r"^ws_[0-9a-f]{32}$")]
FleetPlanId = Annotated[str, StringConstraints(pattern=r"^plan_[0-9a-f]{32}$")]
FleetPatchId = Annotated[str, StringConstraints(pattern=r"^fpatch_[0-9a-f]{32}$")]
FleetPatchPath = Annotated[
    str,
    StringConstraints(
        min_length=8,
        max_length=4096,
        pattern=r"^\.fleet/[^/\\\x00][^\\\x00]*$",
    ),
]
FleetPatchContent = Annotated[str, StringConstraints(max_length=1_000_000)]
FleetPatchRationale = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4096)
]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
ImageIdentity = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
RoleId = Annotated[
    str, StringConstraints(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_-]*$")
]
RuntimeName = Annotated[
    str, StringConstraints(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9-]*$")
]
ProviderModelId = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=200,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$",
    ),
]
CredentialReferenceString = Annotated[
    str,
    StringConstraints(
        min_length=5,
        max_length=132,
        pattern=r"^env:[A-Za-z_][A-Za-z0-9_]*$",
    ),
]
RuntimeToolName = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z][A-Za-z0-9_-]*$",
    ),
]
RuntimeToolCallId = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$",
    ),
]
WorkflowId = Annotated[
    str, StringConstraints(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_-]*$")
]
ActionId = Annotated[
    str, StringConstraints(min_length=1, max_length=100, pattern=r"^[a-z][a-z0-9_.-]*$")
]
ResourceKind = Annotated[
    str, StringConstraints(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_-]*$")
]
SandboxProviderId = Annotated[
    str, StringConstraints(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_-]*$")
]
SandboxName = Literal["fake", "docker", "local-unsafe"]
SandboxNetworkMode = Literal["none", "approved-unrestricted"]
CriterionId = Annotated[
    str, StringConstraints(min_length=1, max_length=100, pattern=r"^[a-z][a-z0-9_-]*$")
]
NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
BoundedText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=4096),
]
BoundedSummary = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=8192),
]
LogicalRepoPath = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=4096,
        pattern=r"^[^/\\\x00][^\\\x00]*$",
    ),
]
_EVIDENCE_REQUIREMENT_ALIASES = {
    "canonical patch": "canonical_patch",
    "command evidence": "command_evidence",
    "control-plane scope and plan": "control_plane_plan",
    "independent fake verifier verdict": "independent_verifier_verdict",
    "independent verification": "independent_verifier_verdict",
    "independent verifier verdict": "independent_verifier_verdict",
}


def _normalize_evidence_requirement(value: object) -> object:
    if isinstance(value, str):
        return _EVIDENCE_REQUIREMENT_ALIASES.get(value.strip().lower(), value)
    return value


EvidenceRequirementId = Annotated[
    Literal[
        "canonical_patch",
        "command_evidence",
        "control_plane_plan",
        "independent_verifier_verdict",
    ],
    BeforeValidator(_normalize_evidence_requirement),
]
FleetStrategyName = Literal[
    "direct",
    "single_engineer",
    "engineer_verifier",
    "parallel_engineers",
    "research_architect_engineer_verifier",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FrozenStrictModel(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FleetPatchOperation(StrEnum):
    ADD = "add"
    REPLACE = "replace"
    REMOVE = "remove"


class FleetPatchFileChange(StrictModel):
    operation: FleetPatchOperation
    path: FleetPatchPath
    before_sha256: Sha256 | None = None
    after_sha256: Sha256 | None = None
    content: FleetPatchContent | None = None

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if (
            not value
            or any(ord(character) < 32 or ord(character) == 127 for character in value)
            or value.startswith("/")
            or "\\" in value
            or not path.parts
            or ".." in path.parts
            or path.parts[0] != ".fleet"
            or path.as_posix() != value
        ):
            raise ValueError(
                "FleetPatch paths must be canonical repository-relative paths beneath .fleet/"
            )
        return value

    @model_validator(mode="after")
    def validate_operation_content(self) -> FleetPatchFileChange:
        if self.operation is FleetPatchOperation.ADD:
            if self.before_sha256 is not None:
                raise ValueError("add changes cannot declare a prior content hash")
            self._require_content_hash()
        elif self.operation is FleetPatchOperation.REPLACE:
            if self.before_sha256 is None:
                raise ValueError("replace changes require a prior content hash")
            self._require_content_hash()
        elif (
            self.before_sha256 is None or self.after_sha256 is not None or self.content is not None
        ):
            raise ValueError(
                "remove changes require a prior hash and cannot contain an after hash or content"
            )
        return self

    def _require_content_hash(self) -> None:
        if self.content is None or self.after_sha256 is None:
            raise ValueError("add/replace changes require content and its SHA-256 hash")
        actual = sha256_bytes(self.content.encode("utf-8"))
        if self.after_sha256 != actual:
            raise ValueError("FleetPatch after hash does not match its UTF-8 content")


class FleetPatch(StrictModel):
    api_version: Literal["agentfleet.dev/v1alpha1"] = "agentfleet.dev/v1alpha1"
    kind: Literal["FleetPatch"] = "FleetPatch"
    fleet_patch_id: FleetPatchId
    project_id: ProjectId
    base_fleet_spec_sha256: Sha256
    changes: list[FleetPatchFileChange] = Field(min_length=1, max_length=128)
    rationale: FleetPatchRationale
    rollback_of: FleetPatchId | None = None


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value


def _validate_logical_paths(values: list[str], *, field_name: str) -> list[str]:
    folded_paths: list[tuple[str, ...]] = []
    for value in values:
        path = PurePosixPath(value)
        if (
            not value
            or not path.parts
            or value.startswith("/")
            or "\\" in value
            or ".." in path.parts
            or path.as_posix() != value
        ):
            raise ValueError(f"invalid repository-relative {field_name} path: {value!r}")
        folded_paths.append(tuple(part.casefold() for part in path.parts))
    if len(folded_paths) != len(set(folded_paths)):
        raise ValueError(f"{field_name} paths must be case-insensitively unique")
    return values


def _validate_bounded_json(
    value: JsonValue,
    *,
    field_name: str,
    max_bytes: int = 65_536,
    max_depth: int = 16,
    max_nodes: int = 4096,
    max_string_length: int = 32_768,
) -> JsonValue:
    node_count = 0

    def visit(item: JsonValue, depth: int) -> None:
        nonlocal node_count
        node_count += 1
        if node_count > max_nodes:
            raise ValueError(f"{field_name} exceeds the JSON node limit")
        if depth > max_depth:
            raise ValueError(f"{field_name} exceeds the JSON nesting limit")
        if isinstance(item, str):
            if len(item) > max_string_length:
                raise ValueError(f"{field_name} contains an oversized string")
        elif isinstance(item, float) and not math.isfinite(item):
            raise ValueError(f"{field_name} contains a non-finite number")
        elif isinstance(item, dict):
            for key, child in item.items():
                if not key or len(key) > 128 or any(ord(character) < 32 for character in key):
                    raise ValueError(f"{field_name} contains an invalid object key")
                visit(child, depth + 1)
        elif isinstance(item, list):
            for child in item:
                visit(child, depth + 1)

    visit(value, 0)
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > max_bytes:
        raise ValueError(f"{field_name} exceeds the serialized byte limit")
    return value


def _validate_runtime_selection(
    runtime_name: str,
    provider_model: str | None,
    credential_ref: str | None,
) -> None:
    if provider_model is not None:
        provider_prefix, separator, model_name = provider_model.partition(":")
        if (
            not separator
            or not model_name
            or re.fullmatch(r"[a-z][a-z0-9-]*", provider_prefix) is None
        ):
            raise ValueError("provider_model must use a canonical non-empty provider:model ID")
    if runtime_name == "fake" and (provider_model is not None or credential_ref is not None):
        raise ValueError("fake runtime cannot carry provider model or credential metadata")
    if runtime_name in {"pydantic-ai", "openai-agents", "langgraph"} and (
        provider_model is None or credential_ref is None
    ):
        raise ValueError(f"{runtime_name} runtime requires provider_model and credential_ref")


class AgentRole(StrEnum):
    COS = "cos"
    ENGINEER = "engineer"
    VERIFIER = "verifier"
    RESEARCHER = "researcher"
    ARCHITECT = "architect"


class AgentLifecycle(StrEnum):
    PERSISTENT = "persistent"
    PER_TASK = "per_task"


class AgentStatus(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RuntimeCapability(StrEnum):
    STRUCTURED_OUTPUT = "structured_output"
    TOOL_CALLING = "tool_calling"
    STREAMING = "streaming"
    CHECKPOINT = "checkpoint"
    RESUME = "resume"
    USAGE_ACCOUNTING = "usage_accounting"


class RuntimeCredentialCheck(StrEnum):
    NONE = "none"
    INSPECT = "inspect"
    RESOLVE = "resolve"


class RuntimeCredentialStatus(StrEnum):
    NOT_SELECTED = "not_selected"
    NOT_REQUIRED = "not_required"
    NOT_CHECKED = "not_checked"
    CONFIGURED = "configured"
    MISSING = "missing"
    INVALID = "invalid"


class RuntimeToolOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    DENIED = "denied"
    APPROVAL_REQUIRED = "approval_required"
    FAILED = "failed"


class RunStatus(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    WAITING_FOR_CHILDREN = "waiting_for_children"
    PAUSED_FOR_APPROVAL = "paused_for_approval"
    PAUSED_FOR_PLAN = "paused_for_plan"
    READY_FOR_REVIEW = "ready_for_review"
    APPLYING = "applying"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    ABANDONED = "abandoned"


class WorkflowStage(StrEnum):
    INTAKE = "intake"
    SCOPING = "scoping"
    WORKSPACE_PREPARATION = "workspace_preparation"
    IMPLEMENTING = "implementing"
    VERIFYING = "verifying"
    REPAIRING = "repairing"
    PRESENTING = "presenting"
    APPLYING = "applying"
    CLEANUP = "cleanup"


class Verdict(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    INCONCLUSIVE = "inconclusive"


class ArtifactKind(StrEnum):
    FLEET_CONFIG_PROPOSAL = "fleet_config_proposal"
    FLEET_PATCH = "fleet_patch"
    FLEET_PATCH_DIFF = "fleet_patch_diff"
    CONFIG_SNAPSHOT = "config_snapshot"
    TASK_SPEC = "task_spec"
    IMPLEMENTATION_REPORT = "implementation_report"
    SPECIALIST_REPORT = "specialist_report"
    GRAPH_JOIN = "graph_join"
    PATCH = "patch"
    TEST_REPORT = "test_report"
    VERIFIER_VERDICT = "verifier_verdict"
    RUN_SUMMARY = "run_summary"
    COMMAND_TRANSCRIPT = "command_transcript"
    COMMAND_EVIDENCE = "command_evidence"
    REPOSITORY_PROFILE = "repository_profile"
    PROJECT_KNOWLEDGE = "project_knowledge"
    FLEET_PLAN = "fleet_plan"
    EVIDENCE_BUNDLE = "evidence_bundle"
    ERROR_REPORT = "error_report"
    RUNTIME_USAGE = "runtime_usage"
    SANDBOX_INSPECTION = "sandbox_inspection"
    RESOURCE_CLEANUP = "resource_cleanup"
    BOOTSTRAP_REPORT = "bootstrap_report"
    COS_RESPONSE = "cos_response"


class WorkspaceKind(StrEnum):
    CANDIDATE = "candidate"
    VERIFICATION = "verification"


class LeaseKind(StrEnum):
    WORKTREE = "worktree"
    SANDBOX = "sandbox"
    EXECUTION = "execution"


class LeaseStatus(StrEnum):
    CREATING = "creating"
    ACTIVE = "active"
    RELEASING = "releasing"
    RELEASED = "released"
    RECOVERED = "recovered"
    FAILED = "failed"


class PermissionOutcome(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


class ApprovalChoice(StrEnum):
    DENY = "deny"
    ALLOW_ONCE = "allow_once"
    ALLOW_RUN = "allow_run"
    ALLOW_ALWAYS = "allow_always"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"


class IntentStatus(StrEnum):
    PENDING_APPROVAL = "pending_approval"
    RESERVED = "reserved"
    EXECUTED = "executed"
    DENIED = "denied"


class SandboxSecurityLevel(StrEnum):
    FAKE = "fake"
    ISOLATED = "isolated"
    UNSAFE_HOST = "unsafe_host"


class FakeScenario(StrEnum):
    SUCCESS = "success"
    FAIL = "fail"
    REPAIR = "repair"
    APPROVAL = "approval"
    INCONCLUSIVE = "inconclusive"
    VERIFIER_MUTATION = "verifier_mutation"
    DIRECT = "direct"
    SINGLE_ENGINEER = "single_engineer"
    PARALLEL_ENGINEERS = "parallel_engineers"
    SPECIALIST = "specialist"


class RuntimeConfiguration(FrozenStrictModel):
    """Provider-neutral, trusted runtime selection and invocation ceilings."""

    runtime_name: RuntimeName = "fake"
    provider_model: ProviderModelId | None = None
    credential_ref: CredentialReferenceString | None = None
    max_requests: int = Field(default=8, ge=1, le=100)
    max_tool_calls: int = Field(default=32, ge=0, le=256)
    max_total_tokens: int = Field(default=32_768, ge=1, le=2_000_000)
    timeout_seconds: int = Field(default=120, ge=1, le=3600)
    max_retries: int = Field(default=1, ge=0, le=3)

    @model_validator(mode="after")
    def validate_runtime_selection(self) -> RuntimeConfiguration:
        _validate_runtime_selection(
            self.runtime_name,
            self.provider_model,
            self.credential_ref,
        )
        return self


class RuntimePreflight(FrozenStrictModel):
    runtime_name: RuntimeName
    ready: bool
    capabilities: frozenset[RuntimeCapability]
    credential_status: RuntimeCredentialStatus
    diagnostic: BoundedText


class RuntimeProviderMetadata(FrozenStrictModel):
    """Deliberately small metadata projection; raw provider responses are forbidden."""

    provider: RuntimeName | None = None
    model: ProviderModelId | None = None
    finish_reason: (
        Annotated[
            str,
            StringConstraints(
                strip_whitespace=True,
                min_length=1,
                max_length=64,
                pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$",
            ),
        ]
        | None
    ) = None

    @model_validator(mode="after")
    def require_reported_metadata(self) -> RuntimeProviderMetadata:
        if self.provider is None and self.model is None and self.finish_reason is None:
            raise ValueError("runtime provider metadata must contain a reported value")
        return self


class UsageRecord(FrozenStrictModel):
    """Only provider-reported, provider-neutral usage facts."""

    requests: int | None = Field(default=None, ge=0, le=1_000_000)
    input_tokens: int | None = Field(default=None, ge=0, le=2_000_000_000)
    output_tokens: int | None = Field(default=None, ge=0, le=2_000_000_000)
    total_tokens: int | None = Field(default=None, ge=0, le=4_000_000_000)
    tool_calls: int | None = Field(default=None, ge=0, le=1_000_000)
    provider_cost: Decimal | None = Field(default=None, ge=0, le=1_000_000)
    provider_currency: Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")] | None = None

    @model_validator(mode="after")
    def validate_reported_usage(self) -> UsageRecord:
        values = (
            self.requests,
            self.input_tokens,
            self.output_tokens,
            self.total_tokens,
            self.tool_calls,
            self.provider_cost,
            self.provider_currency,
        )
        if all(value is None for value in values):
            raise ValueError("usage record must contain at least one provider-reported value")
        if (self.provider_cost is None) != (self.provider_currency is None):
            raise ValueError("provider cost and currency must be reported together")
        if (
            self.total_tokens is not None
            and self.input_tokens is not None
            and self.output_tokens is not None
            and self.total_tokens < self.input_tokens + self.output_tokens
        ):
            raise ValueError("total_tokens cannot be smaller than input_tokens + output_tokens")
        return self


class Project(StrictModel):
    project_id: ProjectId
    canonical_root: str
    remote_fingerprint: str | None = None
    identity_hash: Sha256
    fleet_spec_hash: Sha256 | None = None
    config_snapshot_artifact_id: ArtifactId | None = None
    runtime_name: RuntimeName = "fake"
    provider_model: ProviderModelId | None = None
    credential_ref: CredentialReferenceString | None = None
    sandbox_name: SandboxName = "fake"
    sandbox_configuration: SandboxConfiguration | None = None
    sandbox_configuration_hash: Sha256 | None = None
    sandbox_image_identity: ImageIdentity | None = None
    sandbox_daemon_identity: Sha256 | None = None
    init_status_fingerprint: Sha256 | None = None
    repository_profile_artifact_id: ArtifactId | None = None
    repository_profile_semantic_hash: Sha256 | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "repository_profile_semantic_hash", "repository_profile_hash"
        ),
    )
    project_knowledge_artifact_id: ArtifactId | None = None
    project_knowledge_semantic_hash: Sha256 | None = Field(
        default=None,
        validation_alias=AliasChoices("project_knowledge_semantic_hash", "project_knowledge_hash"),
    )
    bootstrap_report_artifact_id: ArtifactId | None = None
    bootstrap_report_sha256: Sha256 | None = None
    bootstrap_canary_run_id: RunId | None = None
    bootstrap_verified: bool = False
    permission_scope_required: bool = False
    created_at: datetime
    updated_at: datetime

    _created_utc = field_validator("created_at")(_require_utc)
    _updated_utc = field_validator("updated_at")(_require_utc)

    @model_validator(mode="after")
    def validate_runtime_selection(self) -> Project:
        _validate_runtime_selection(
            self.runtime_name,
            self.provider_model,
            self.credential_ref,
        )
        if self.sandbox_configuration is None:
            if self.sandbox_name != "fake":
                raise ValueError("non-fake Project requires an explicit sandbox configuration")
            self.sandbox_configuration = SandboxConfiguration()
        if self.sandbox_configuration.provider != self.sandbox_name:
            raise ValueError("Project sandbox name and configuration provider must match")
        configuration_hash = canonical_json_hash(self.sandbox_configuration.model_dump(mode="json"))
        if self.sandbox_configuration_hash is None:
            self.sandbox_configuration_hash = configuration_hash
        elif self.sandbox_configuration_hash != configuration_hash:
            raise ValueError("Project sandbox configuration hash does not match its content")
        if self.sandbox_name == "docker" and (
            self.sandbox_image_identity is None or self.sandbox_daemon_identity is None
        ):
            raise ValueError("Docker Project requires immutable image and daemon identities")
        if self.sandbox_name != "docker" and (
            self.sandbox_image_identity is not None or self.sandbox_daemon_identity is not None
        ):
            raise ValueError("Only Docker Project may carry image and daemon identities")
        if (self.bootstrap_report_artifact_id is None) != (self.bootstrap_report_sha256 is None):
            raise ValueError("Project bootstrap report ID and hash must be paired")
        if self.bootstrap_report_artifact_id is None and (
            self.bootstrap_canary_run_id is not None or self.bootstrap_verified
        ):
            raise ValueError("Project bootstrap status requires a report binding")
        return self


class AgentExecutionCheckpoint(FrozenStrictModel):
    """Identity-bound specialist session retained across approval pauses."""

    agent_instance_id: AgentInstanceId
    workspace_id: WorkspaceId
    sandbox_id: SandboxId
    iteration: int = Field(ge=0, le=5)
    created_at: datetime

    _created_utc = field_validator("created_at")(_require_utc)


class VerificationCheckpoint(AgentExecutionCheckpoint):
    patch_sha256: Sha256
    baseline_fingerprint: Sha256


class Run(StrictModel):
    run_id: RunId
    project_id: ProjectId
    correlation_id: CorrelationId
    parent_run_id: RunId | None = None
    parent_plan_sha256: Sha256 | None = None
    parent_node_id: RoleId | None = None
    parent_iteration: int | None = Field(default=None, ge=0, le=5)
    goal: str
    plan_review_required: bool = Field(default=False, exclude_if=lambda value: not value)
    base_revision: str
    target_status_fingerprint: Sha256
    runtime_name: RuntimeName = "fake"
    provider_model: ProviderModelId | None = None
    credential_ref: CredentialReferenceString | None = None
    model_bindings_sha256: Sha256 | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    sandbox_name: SandboxName = "fake"
    sandbox_configuration: SandboxConfiguration | None = None
    sandbox_configuration_hash: Sha256 | None = None
    sandbox_requirements: SandboxRequirements | None = None
    sandbox_capabilities_snapshot: SandboxCapabilities | None = None
    sandbox_capabilities_hash: Sha256 | None = None
    sandbox_image_identity: ImageIdentity | None = None
    sandbox_daemon_identity: Sha256 | None = None
    unsafe_local_confirmed: bool = False
    fake_scenario: FakeScenario = FakeScenario.SUCCESS
    status: RunStatus = RunStatus.CREATED
    stage: WorkflowStage | None = None
    task_id: TaskId | None = None
    task_spec_artifact_id: ArtifactId | None = None
    task_spec_hash: Sha256 | None = None
    config_snapshot_artifact_id: ArtifactId | None = None
    config_snapshot_hash: Sha256 | None = None
    fleet_plan_artifact_id: ArtifactId | None = None
    fleet_plan_hash: Sha256 | None = None
    fleet_strategy: str | None = None
    pending_approval_id: ApprovalRequestId | None = None
    max_repair_iterations: int = Field(default=1, ge=0, le=5)
    repair_iterations: int = Field(default=0, ge=0, le=5)
    patch_artifact_id: ArtifactId | None = None
    patch_sha256: Sha256 | None = None
    command_evidence_artifact_ids: list[ArtifactId] = Field(default_factory=list)
    runtime_usage_artifact_ids: list[ArtifactId] = Field(default_factory=list)
    verifier_agent_instance_id: AgentInstanceId | None = None
    engineer_checkpoint: AgentExecutionCheckpoint | None = None
    specialist_checkpoint: AgentExecutionCheckpoint | None = None
    verification_checkpoint: VerificationCheckpoint | None = None
    verifier_verdict_artifact_id: ArtifactId | None = None
    evidence_bundle_artifact_id: ArtifactId | None = None
    evidence_bundle_hash: Sha256 | None = None
    cleanup_receipt_artifact_id: ArtifactId | None = None
    cleanup_receipt_sha256: Sha256 | None = None
    assurance_verdict: Verdict | None = None
    verified_complete: bool = False
    verifier_workspace_mutated: bool = False
    applied_revision: str | None = None
    created_at: datetime
    updated_at: datetime

    _created_utc = field_validator("created_at")(_require_utc)
    _updated_utc = field_validator("updated_at")(_require_utc)

    @field_validator("runtime_usage_artifact_ids")
    @classmethod
    def validate_runtime_usage_artifact_ids(cls, values: list[str]) -> list[str]:
        if len(values) > 256 or len(values) != len(set(values)):
            raise ValueError("runtime usage artifact IDs must be bounded and unique")
        return values

    @model_validator(mode="after")
    def validate_runtime_selection(self) -> Run:
        child_fields = (
            self.parent_run_id,
            self.parent_plan_sha256,
            self.parent_node_id,
            self.parent_iteration,
        )
        if any(value is not None for value in child_fields) and not all(
            value is not None for value in child_fields
        ):
            raise ValueError("internal child run requires its complete parent binding")
        if self.parent_run_id == self.run_id:
            raise ValueError("a run cannot be its own parent")
        _validate_runtime_selection(
            self.runtime_name,
            self.provider_model,
            self.credential_ref,
        )
        if self.sandbox_configuration is None:
            if self.sandbox_name != "fake":
                raise ValueError("non-fake Run requires an explicit sandbox configuration")
            self.sandbox_configuration = SandboxConfiguration()
        if self.sandbox_configuration.provider != self.sandbox_name:
            raise ValueError("Run sandbox name and configuration provider must match")
        configuration_hash = canonical_json_hash(self.sandbox_configuration.model_dump(mode="json"))
        if self.sandbox_configuration_hash is None:
            self.sandbox_configuration_hash = configuration_hash
        elif self.sandbox_configuration_hash != configuration_hash:
            raise ValueError("Run sandbox configuration hash does not match its content")
        if self.sandbox_requirements is None:
            if self.sandbox_name != "fake":
                raise ValueError("non-fake Run requires explicit sandbox requirements")
            self.sandbox_requirements = SandboxRequirements()
        if self.sandbox_capabilities_snapshot is None:
            if self.sandbox_name != "fake":
                raise ValueError("non-fake Run requires a sandbox capability snapshot")
            self.sandbox_capabilities_snapshot = SandboxCapabilities.phase1_fake()
        if self.sandbox_capabilities_snapshot.provider != self.sandbox_name:
            raise ValueError("Run sandbox name and capability provider must match")
        capabilities_hash = canonical_json_hash(
            self.sandbox_capabilities_snapshot.model_dump(mode="json")
        )
        if self.sandbox_capabilities_hash is None:
            self.sandbox_capabilities_hash = capabilities_hash
        elif self.sandbox_capabilities_hash != capabilities_hash:
            raise ValueError("Run sandbox capabilities hash does not match its content")
        if self.sandbox_name == "docker" and (
            self.sandbox_image_identity is None or self.sandbox_daemon_identity is None
        ):
            raise ValueError("Docker Run requires immutable image and daemon identities")
        if self.sandbox_name != "docker" and (
            self.sandbox_image_identity is not None or self.sandbox_daemon_identity is not None
        ):
            raise ValueError("Only Docker Run may carry image and daemon identities")
        if (self.cleanup_receipt_artifact_id is None) != (self.cleanup_receipt_sha256 is None):
            raise ValueError("Run cleanup receipt ID and hash must be paired")
        return self


class AcceptanceCriterion(StrictModel):
    criterion_id: CriterionId = Field(
        description="Stable identifier for one requested task outcome."
    )
    description: BoundedText = Field(
        description=(
            "Observable task outcome, not a delivery-evidence category copied from "
            "required_evidence. "
            "For code changes, describe requested behavior that admitted independent checks can "
            "support; preserve requested scope and report unsupported proof rather than invent it."
        )
    )


class WriterAssignment(StrictModel):
    """A bounded untrusted subgoal; only the planner may instantiate its writer."""

    node_id: RoleId
    role_id: RoleId | None = Field(default=None, exclude_if=lambda value: value is None)
    goal: BoundedSummary
    scope: list[LogicalRepoPath] = Field(min_length=1, max_length=128)
    criterion_ids: list[CriterionId] = Field(min_length=1, max_length=128)

    @field_validator("scope")
    @classmethod
    def validate_scope(cls, values: list[str]) -> list[str]:
        return _validate_logical_paths(values, field_name="scope")

    @field_validator("criterion_ids")
    @classmethod
    def validate_criteria(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("writer assignment criterion IDs must be unique")
        return values


class ScopeDecision(StrictModel):
    """Untrusted CoS proposal accepted only after control-plane validation."""

    normalized_goal: BoundedSummary
    response: BoundedSummary | None = None
    workflow: WorkflowId = Field(
        default="code-change",
        description=(
            "Exact declared workflow identifier from available_workflows, such as code-change. "
            "This is not a fleet strategy: engineer_verifier selects a team, not a workflow."
        ),
    )
    change_kind: Literal["read_only", "code_change"] = "code_change"
    fleet_strategy: FleetStrategyName = Field(
        description=(
            "Smallest sufficient team strategy, independent of the declared workflow identifier. "
            "The control plane constructs its fixed role nodes; only parallel_engineers "
            "accepts writer_assignments."
        )
    )
    role_selections: dict[Literal["engineer", "verifier", "researcher", "architect"], RoleId] = (
        Field(
            default_factory=dict,
            max_length=4,
            exclude_if=lambda value: not value,
            description="Declared role overrides as a dictionary; use {} when unused, not null.",
        )
    )
    writer_assignments: list[WriterAssignment] = Field(
        default_factory=list,
        max_length=8,
        description=(
            "Parallel Engineer shards only. Must be [] for direct, single_engineer, "
            "engineer_verifier, and research_architect_engineer_verifier. Do not list fixed "
            "Engineer or Verifier nodes here: the control plane constructs them. A Verifier "
            "is independent and never a writer. For parallel_engineers provide 2-8 bounded "
            "writers with unique node IDs, disjoint scopes, and exact criterion coverage."
        ),
    )
    max_parallel_agents: int = Field(default=2, ge=1, le=8)
    allowed_paths: list[LogicalRepoPath] = Field(max_length=128)
    forbidden_paths: list[LogicalRepoPath] = Field(max_length=128)
    acceptance_criteria: list[AcceptanceCriterion] = Field(
        min_length=1,
        max_length=128,
        description=(
            "Observable outcomes of the requested task. Do not blindly copy delivery requirements "
            "such as canonical_patch into behavioral criteria. Code-change proof requires admitted "
            "independent command evidence; unsupported outcomes remain explicit proof gaps."
        ),
    )
    required_evidence: list[EvidenceRequirementId] = Field(
        min_length=1,
        max_length=32,
        description=(
            "Required delivery/proof types, distinct from acceptance_criteria task outcomes: "
            "for example canonical_patch, command_evidence, independent_verifier_verdict. "
            "Direct read-only tasks retain control_plane_plan."
        ),
    )

    @field_validator("allowed_paths", "forbidden_paths")
    @classmethod
    def validate_repository_paths(cls, values: list[str], info: Any) -> list[str]:
        return _validate_logical_paths(values, field_name=info.field_name)

    @field_validator("acceptance_criteria")
    @classmethod
    def validate_acceptance_criteria(
        cls, values: list[AcceptanceCriterion]
    ) -> list[AcceptanceCriterion]:
        criterion_ids = [item.criterion_id for item in values]
        if len(criterion_ids) != len(set(criterion_ids)):
            raise ValueError("ScopeDecision acceptance criterion IDs must be unique")
        return values

    @field_validator("required_evidence")
    @classmethod
    def validate_evidence_requirements(
        cls, values: list[EvidenceRequirementId]
    ) -> list[EvidenceRequirementId]:
        if len(values) != len(set(values)):
            raise ValueError("ScopeDecision evidence requirements must be unique")
        return values

    @model_validator(mode="after")
    def validate_scope_coherence(self) -> ScopeDecision:
        assignments = self.writer_assignments
        if self.fleet_strategy == "parallel_engineers":
            if len(assignments) < 2 or self.max_parallel_agents < 2:
                raise ValueError("parallel strategy requires multiple bounded writer assignments")
            node_ids = [assignment.node_id for assignment in assignments]
            if len(node_ids) != len(set(node_ids)) or "verifier" in node_ids:
                raise ValueError("writer node IDs must be unique and cannot replace the verifier")
            criterion_ids = {item.criterion_id for item in self.acceptance_criteria}
            if {item for assignment in assignments for item in assignment.criterion_ids} != (
                criterion_ids
            ):
                raise ValueError("writer assignments must cover exactly the original criteria")
        elif assignments:
            raise ValueError("only the parallel strategy accepts writer assignments")
        required = set(self.required_evidence)
        if self.change_kind == "read_only":
            if self.fleet_strategy != "direct" or self.allowed_paths:
                raise ValueError("read-only ScopeDecision requires direct strategy and no writes")
            if required != {"control_plane_plan"}:
                raise ValueError("direct ScopeDecision requires control_plane_plan evidence")
            return self
        if self.fleet_strategy == "direct" or not self.allowed_paths:
            raise ValueError("code-change ScopeDecision requires a writer strategy and path scope")
        if not {"canonical_patch", "command_evidence"}.issubset(required):
            raise ValueError("code-change ScopeDecision requires patch and command evidence")
        if (
            self.fleet_strategy
            in {
                "engineer_verifier",
                "parallel_engineers",
                "research_architect_engineer_verifier",
            }
            and "independent_verifier_verdict" not in required
        ):
            raise ValueError("verifier strategy requires independent verifier evidence")
        forbidden = [
            tuple(part.casefold() for part in PurePosixPath(value).parts)
            for value in self.forbidden_paths
        ]
        for allowed_value in self.allowed_paths:
            allowed_parts = tuple(part.casefold() for part in PurePosixPath(allowed_value).parts)
            if allowed_parts and allowed_parts[0] in {".git", ".fleet"}:
                raise ValueError(f"ScopeDecision cannot allow protected path: {allowed_value!r}")
            for blocked in forbidden:
                if (
                    allowed_parts == blocked
                    or allowed_parts[: len(blocked)] == blocked
                    or blocked[: len(allowed_parts)] == allowed_parts
                ):
                    raise ValueError("ScopeDecision allowed and forbidden paths overlap")
        return self


class CommandSpec(FrozenStrictModel):
    command_id: ActionId
    executable: Annotated[
        str,
        StringConstraints(
            min_length=1,
            max_length=128,
            pattern=r"^(?:[A-Za-z0-9._+-]+|\./[A-Za-z0-9._+-]+)$",
        ),
    ]
    argv: tuple[Annotated[str, StringConstraints(max_length=4096)], ...] = Field(
        default_factory=tuple,
        max_length=128,
    )
    logical_cwd: Annotated[str, StringConstraints(min_length=1, max_length=4096)] = "."
    environment: dict[
        Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9_]{0,63}$")],
        Annotated[str, StringConstraints(max_length=4096)],
    ] = Field(default_factory=dict, max_length=32)
    timeout_seconds: int = Field(default=60, ge=1, le=3600)
    max_output_bytes: int = Field(default=64_000, ge=1, le=1_000_000)
    network_requirement: Literal["none", "required"] = "none"

    @field_validator("executable")
    @classmethod
    def reject_shell_executables(cls, value: str) -> str:
        executable_name = PurePosixPath(value).name.casefold()
        if executable_name in {
            "bash",
            "cmd",
            "dash",
            "env",
            "fish",
            "ksh",
            "powershell",
            "pwsh",
            "sh",
            "zsh",
        } or executable_name.endswith((".bat", ".cmd", ".ps1", ".sh")):
            raise ValueError("Phase 3 command profiles cannot execute a shell")
        return value

    @field_validator("argv")
    @classmethod
    def validate_argv_bytes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any("\x00" in value for value in values):
            raise ValueError("command argv cannot contain NUL bytes")
        if sum(len(value.encode("utf-8")) for value in values) > 65_536:
            raise ValueError("command argv exceeds the total byte limit")
        return values

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, values: dict[str, str]) -> dict[str, str]:
        allowed = {
            "CI",
            "LANG",
            "LC_ALL",
            "PYTHONDONTWRITEBYTECODE",
            "PYTHONPATH",
            "PYTHONUNBUFFERED",
        }
        unexpected = set(values) - allowed
        if unexpected:
            raise ValueError(
                "command environment contains names outside the fixed allowlist: "
                f"{sorted(unexpected)}"
            )
        if any("\x00" in value for value in values.values()):
            raise ValueError("command environment values cannot contain NUL bytes")
        return dict(sorted(values.items()))

    @field_validator("logical_cwd")
    @classmethod
    def validate_logical_cwd(cls, value: str) -> str:
        if value == ".":
            return value
        path = PurePosixPath(value)
        if (
            value.startswith("/")
            or "\\" in value
            or "\x00" in value
            or not path.parts
            or "." in path.parts
            or ".." in path.parts
            or path.as_posix() != value
        ):
            raise ValueError("command cwd must be a canonical repository-relative path")
        return value


class TaskSpec(StrictModel):
    task_id: TaskId
    run_id: RunId
    original_goal: str
    normalized_goal: str
    workflow: WorkflowId = "code-change"
    change_kind: Literal["read_only", "code_change"] = "code_change"
    base_revision: str
    allowed_paths: list[str]
    forbidden_paths: list[str]
    acceptance_criteria: list[AcceptanceCriterion] = Field(min_length=1, max_length=128)
    required_evidence: list[EvidenceRequirementId] = Field(min_length=1, max_length=32)
    max_repair_iterations: int = Field(ge=0, le=5)
    config_snapshot_hash: Sha256
    verification_commands: list[CommandSpec] = Field(default_factory=list, max_length=32)
    required_verification_command_ids: list[ActionId] = Field(
        default_factory=list,
        max_length=32,
    )
    created_at: datetime

    _created_utc = field_validator("created_at")(_require_utc)

    @field_validator("required_evidence")
    @classmethod
    def validate_evidence_requirements(
        cls, values: list[EvidenceRequirementId]
    ) -> list[EvidenceRequirementId]:
        if len(values) != len(set(values)):
            raise ValueError("TaskSpec evidence requirements must be unique")
        return values

    @field_validator("acceptance_criteria")
    @classmethod
    def validate_acceptance_criteria(
        cls, values: list[AcceptanceCriterion]
    ) -> list[AcceptanceCriterion]:
        criterion_ids = [item.criterion_id for item in values]
        if len(criterion_ids) != len(set(criterion_ids)):
            raise ValueError("TaskSpec acceptance criterion IDs must be unique")
        return values

    @field_validator("allowed_paths", "forbidden_paths")
    @classmethod
    def validate_repository_paths(cls, values: list[str]) -> list[str]:
        folded_paths: list[tuple[str, ...]] = []
        for value in values:
            path = PurePosixPath(value)
            if (
                not value
                or not path.parts
                or value.startswith("/")
                or "\\" in value
                or ".." in path.parts
                or path.as_posix() != value
            ):
                raise ValueError(f"invalid repository-relative TaskSpec path: {value!r}")
            folded_paths.append(tuple(part.casefold() for part in path.parts))
        if len(folded_paths) != len(set(folded_paths)):
            raise ValueError("TaskSpec repository paths must be case-insensitively unique")
        return values

    @model_validator(mode="after")
    def reject_protected_or_conflicting_write_scope(self) -> TaskSpec:
        required = set(self.required_evidence)
        if self.change_kind == "code_change" and not {
            "canonical_patch",
            "command_evidence",
        }.issubset(required):
            raise ValueError("code-change TaskSpec requires canonical_patch and command_evidence")
        if self.change_kind == "code_change" and not self.allowed_paths:
            raise ValueError("code-change TaskSpec requires a non-empty allowed path scope")
        forbidden = [
            tuple(part.casefold() for part in PurePosixPath(value).parts)
            for value in self.forbidden_paths
        ]
        for allowed_value in self.allowed_paths:
            allowed = PurePosixPath(allowed_value)
            allowed_parts = tuple(part.casefold() for part in allowed.parts)
            if allowed_parts and allowed_parts[0] in {".git", ".fleet"}:
                raise ValueError(f"TaskSpec cannot allow protected path: {allowed_value!r}")
            for blocked in forbidden:
                if (
                    allowed_parts == blocked
                    or allowed_parts[: len(blocked)] == blocked
                    or blocked[: len(allowed_parts)] == allowed_parts
                ):
                    raise ValueError(
                        "TaskSpec allowed and forbidden path scopes overlap: "
                        f"{allowed_value!r} and {'/'.join(blocked)!r}"
                    )
        command_ids = [command.command_id for command in self.verification_commands]
        if len(command_ids) != len(set(command_ids)):
            raise ValueError("TaskSpec verification command IDs must be unique")
        if len(self.required_verification_command_ids) != len(
            set(self.required_verification_command_ids)
        ):
            raise ValueError("TaskSpec required verification command IDs must be unique")
        missing_commands = set(self.required_verification_command_ids) - set(command_ids)
        if missing_commands:
            raise ValueError(
                f"TaskSpec required verification commands are missing: {sorted(missing_commands)}"
            )
        return self


class AgentSpec(StrictModel):
    role: RoleId
    lifecycle: AgentLifecycle
    allowed_tools: list[str]
    max_steps: int = Field(ge=1, le=100)


class AgentInstance(StrictModel):
    agent_instance_id: AgentInstanceId
    run_id: RunId
    task_id: TaskId | None = None
    role: RoleId
    execution_kind: AgentRole | None = Field(default=None, exclude_if=lambda value: value is None)
    status: AgentStatus
    iteration: int = Field(ge=0)
    created_at: datetime
    completed_at: datetime | None = None

    _created_utc = field_validator("created_at")(_require_utc)
    _completed_utc = field_validator("completed_at")(
        lambda value: _require_utc(value) if value is not None else value
    )

    @model_validator(mode="after")
    def require_task_for_specialists(self) -> AgentInstance:
        if self.execution_kind is not None and (
            (self.role in {item.value for item in AgentRole} and self.execution_kind != self.role)
            or (self.role != AgentRole.COS and self.execution_kind is AgentRole.COS)
        ):
            raise ValueError("execution kind cannot replace a built-in or create another CoS")
        if self.task_id is None and self.role != AgentRole.COS.value:
            raise ValueError("only the CoS may exist before a TaskSpec is bound")
        return self

    @property
    def effective_kind(self) -> AgentRole:
        # A custom instance receives this control-plane field only after its
        # exact configuration and FleetPlan node have been validated.
        return self.execution_kind or AgentRole(self.role)


class FleetEvent(StrictModel):
    event_id: EventId
    event_type: str
    schema_version: Literal[1] = 1
    occurred_at: datetime
    project_id: ProjectId
    run_id: RunId | None = None
    task_id: TaskId | None = None
    agent_instance_id: AgentInstanceId | None = None
    correlation_id: CorrelationId
    causation_id: OpaqueId | None = None
    sequence: int | None = Field(default=None, ge=1)
    payload: dict[str, JsonValue] = Field(default_factory=dict)
    redaction_summary: list[str] = Field(default_factory=list)

    _occurred_utc = field_validator("occurred_at")(_require_utc)


class ArtifactMetadata(StrictModel):
    artifact_id: ArtifactId
    kind: ArtifactKind
    project_id: ProjectId
    run_id: RunId | None = None
    task_id: TaskId | None = None
    mime_type: str
    byte_size: int = Field(ge=0)
    sha256: Sha256
    content_ref: str
    producer: str
    redacted: bool
    created_at: datetime
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    _created_utc = field_validator("created_at")(_require_utc)


class RepositoryInfo(StrictModel):
    root: str
    head_revision: str
    remote_fingerprint: str | None
    identity_hash: Sha256
    status_porcelain: str
    status_fingerprint: Sha256
    dirty_paths: list[str]


class Workspace(StrictModel):
    workspace_id: WorkspaceId
    run_id: RunId
    kind: WorkspaceKind
    path: str
    base_revision: str


class PatchInfo(StrictModel):
    content: str
    sha256: Sha256
    changed_paths: list[str]


class ApplyResult(StrictModel):
    applied: bool
    head_revision: str
    changed_paths: list[str]


class ResourceLease(StrictModel):
    lease_id: LeaseId
    run_id: RunId
    kind: LeaseKind
    resource_id: WorkspaceId | SandboxId | ExecutionId
    path: str | None = None
    status: LeaseStatus
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    _created_utc = field_validator("created_at")(_require_utc)
    _updated_utc = field_validator("updated_at")(_require_utc)

    @model_validator(mode="after")
    def validate_resource_identity(self) -> ResourceLease:
        expected_prefix = {
            LeaseKind.WORKTREE: "ws_",
            LeaseKind.SANDBOX: "sandbox_",
            LeaseKind.EXECUTION: "exec_",
        }[self.kind]
        if not self.resource_id.startswith(expected_prefix):
            raise ValueError(
                f"{self.kind.value} leases require a {expected_prefix.rstrip('_')!r} resource ID"
            )
        return self


class CanonicalResource(StrictModel):
    kind: ResourceKind
    identifier: str


class ScriptedAction(StrictModel):
    """Canonical proposed action consumed only by trusted gateway translations."""

    action: ActionId
    resource: CanonicalResource
    parameters: dict[str, JsonValue]
    reason: BoundedText
    side_effect: bool
    idempotency_key: Annotated[str, StringConstraints(min_length=1, max_length=512)]


class ToolIntent(StrictModel):
    intent_id: IntentId
    run_id: RunId
    task_id: TaskId
    agent_instance_id: AgentInstanceId
    principal_role: RoleId
    workflow: WorkflowId
    stage: WorkflowStage
    action: ActionId
    resource: CanonicalResource
    parameters: dict[str, JsonValue]
    reason: str
    side_effect: bool
    idempotency_key: str
    requested_ttl_seconds: int | None = Field(default=None, ge=1, le=3600)
    requested_uses: int | None = Field(default=None, ge=1, le=1)


class StoredToolIntent(StrictModel):
    intent: ToolIntent
    intent_hash: Sha256
    status: IntentStatus
    approval_request_id: ApprovalRequestId | None = None
    result: dict[str, JsonValue] | None = None


class PermissionDecision(StrictModel):
    outcome: PermissionOutcome
    decision_code: str
    explanation: str
    protected: bool = False
    matched_rule_ids: list[Annotated[str, StringConstraints(min_length=1, max_length=128)]] = Field(
        default_factory=list, max_length=128
    )
    effective_scope: dict[str, JsonValue] | None = None
    risk: str = Field(default="unknown", min_length=1, max_length=64)
    available_choices: list[ApprovalChoice] = Field(default_factory=list, max_length=4)
    grant_id: GrantId | None = None
    source_rule_id: Annotated[str, StringConstraints(min_length=1, max_length=128)] | None = None

    @field_validator("effective_scope")
    @classmethod
    def validate_effective_scope(
        cls, value: dict[str, JsonValue] | None
    ) -> dict[str, JsonValue] | None:
        if value is not None:
            _validate_bounded_json(
                value, field_name="effective permission scope", max_bytes=131_072
            )
        return value


class ApprovalRequest(StrictModel):
    request_id: ApprovalRequestId
    intent_id: IntentId
    run_id: RunId
    intent_hash: Sha256
    principal_role: RoleId
    action: ActionId
    resource: CanonicalResource
    reason: str
    status: ApprovalStatus = ApprovalStatus.PENDING
    available_choices: list[ApprovalChoice] = Field(
        default_factory=lambda: [ApprovalChoice.DENY, ApprovalChoice.ALLOW_ONCE],
        min_length=1,
        max_length=4,
    )
    authorization_scope: dict[str, JsonValue] | None = None
    resolution_choice: ApprovalChoice | None = None
    source_rule_id: Annotated[str, StringConstraints(min_length=1, max_length=128)] | None = None
    created_at: datetime
    expires_at: datetime
    resolved_at: datetime | None = None
    denial_reason: str | None = None

    _created_utc = field_validator("created_at")(_require_utc)
    _expires_utc = field_validator("expires_at")(_require_utc)
    _resolved_utc = field_validator("resolved_at")(
        lambda value: _require_utc(value) if value is not None else value
    )

    @field_validator("authorization_scope")
    @classmethod
    def validate_authorization_scope(
        cls, value: dict[str, JsonValue] | None
    ) -> dict[str, JsonValue] | None:
        if value is not None:
            _validate_bounded_json(
                value, field_name="approval authorization scope", max_bytes=131_072
            )
        return value

    @field_validator("available_choices")
    @classmethod
    def validate_available_choices(cls, values: list[ApprovalChoice]) -> list[ApprovalChoice]:
        if len(values) != len(set(values)):
            raise ValueError("approval choices must be unique")
        return values


class CapabilityGrant(StrictModel):
    grant_id: GrantId
    request_id: ApprovalRequestId | None = None
    intent_id: IntentId
    project_id: ProjectId
    run_id: RunId
    task_id: TaskId
    agent_instance_id: AgentInstanceId
    principal_role: RoleId
    action: ActionId
    resource: CanonicalResource
    intent_hash: Sha256
    issued_by: Literal["user"] = "user"
    issued_at: datetime
    expires_at: datetime | None = None
    choice: ApprovalChoice = ApprovalChoice.ALLOW_ONCE
    scope_sha256: Sha256 | None = None
    remaining_uses: int | None = Field(default=1, ge=0, le=10_000)
    consumed_at: datetime | None = None
    revoked_at: datetime | None = None
    source_rule_id: Annotated[str, StringConstraints(min_length=1, max_length=128)] | None = None

    _issued_utc = field_validator("issued_at")(_require_utc)
    _expires_utc = field_validator("expires_at")(
        lambda value: _require_utc(value) if value is not None else value
    )
    _consumed_utc = field_validator("consumed_at")(
        lambda value: _require_utc(value) if value is not None else value
    )
    _revoked_utc = field_validator("revoked_at")(
        lambda value: _require_utc(value) if value is not None else value
    )

    @model_validator(mode="after")
    def validate_grant_choice(self) -> CapabilityGrant:
        if self.choice is ApprovalChoice.DENY:
            raise ValueError("a denied request cannot issue a capability")
        if self.request_id is None and (
            self.choice is not ApprovalChoice.ALLOW_ALWAYS
            or self.source_rule_id is None
            or self.remaining_uses not in {0, 1}
            or (self.remaining_uses == 0 and self.consumed_at is None)
        ):
            raise ValueError("request-free grants require a bounded persistent-rule receipt")
        if self.choice is ApprovalChoice.ALLOW_ONCE and self.remaining_uses not in {0, 1}:
            raise ValueError("allow-once grants have exactly one use before consumption")
        if self.choice is ApprovalChoice.ALLOW_ONCE and (
            self.expires_at is None
            or not 0 < (self.expires_at - self.issued_at).total_seconds() <= 600
        ):
            raise ValueError("allow-once grants require an expiry within ten minutes of issuance")
        if (
            self.choice in {ApprovalChoice.ALLOW_RUN, ApprovalChoice.ALLOW_ALWAYS}
            and self.scope_sha256 is None
        ):
            raise ValueError("reusable grants require an exact authorization scope hash")
        return self


class ImplementationReport(StrictModel):
    summary: BoundedSummary
    intended_changed_paths: list[LogicalRepoPath] = Field(max_length=128)
    tests_added_or_changed: list[BoundedText] = Field(max_length=128)
    criterion_results: list[BoundedText] = Field(max_length=128)
    evidence_artifact_ids: list[ArtifactId] = Field(max_length=256)
    unresolved_limitations: list[BoundedText] = Field(max_length=128)
    verifier_focus: list[BoundedText] = Field(max_length=128)

    @field_validator("intended_changed_paths")
    @classmethod
    def validate_changed_paths(cls, values: list[str]) -> list[str]:
        return _validate_logical_paths(values, field_name="implementation report")

    @field_validator("evidence_artifact_ids")
    @classmethod
    def validate_evidence_artifact_ids(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("ImplementationReport evidence artifact IDs must be unique")
        return values


class SpecialistReport(StrictModel):
    """Untrusted read-only analysis, never execution or verification authority."""

    role: RoleId
    summary: BoundedSummary
    findings: list[BoundedText] = Field(max_length=32)
    recommendations: list[BoundedText] = Field(max_length=32)
    proof_gaps: list[BoundedText] = Field(max_length=32)

    @model_validator(mode="after")
    def validate_total_size(self) -> SpecialistReport:
        if len(self.model_dump_json().encode("utf-8")) > 32_768:
            raise ValueError("specialist report exceeds its 32768-byte context ceiling")
        return self


class CriterionResult(StrictModel):
    criterion_id: CriterionId = Field(
        description="One exact criterion_id from TaskSpec.acceptance_criteria; cover each once."
    )
    verdict: Verdict
    evidence_artifact_ids: list[ArtifactId] = Field(
        max_length=64,
        description=(
            "For passing code-change proof, use only current independent CommandEvidence IDs from "
            "your run_verification result content.command_evidence_artifact_id, one uniquely "
            "latest "
            "receipt per distinct command_id in the same current Verifier workspace/sandbox. "
            "Not generic artifact_ids, transcripts, patches or Engineer receipts. "
            "Empty or unsupported mappings remain proof gaps."
        ),
    )
    command_ids: list[ActionId] = Field(
        max_length=32,
        description=(
            "Exact admitted command_id values used by your verification calls, paired one-to-one "
            "with evidence_artifact_ids. Select the relevant subset for this criterion, not "
            "mechanically every admitted command. Each passing criterion needs a nonempty mapping; "
            "do not "
            "infer an ID from prose or cite a command without its own current receipt."
        ),
    )
    explanation: BoundedText = Field(
        description=(
            "Explain how the selected independent command evidence supports this task outcome. "
            "A current receipt may support multiple genuinely relevant criteria. A later failed "
            "or timed-out receipt cannot be replaced by an earlier pass; inspection alone "
            "is not independently executed command proof. Preserve inadequate-proof gaps."
        )
    )


class VerifierVerdict(StrictModel):
    verdict: Verdict
    criterion_results: list[BoundedText] = Field(
        max_length=128,
        description=(
            "Narrative findings; these do not replace structured_criterion_results mappings."
        ),
    )
    evidence_artifact_ids: list[ArtifactId] = Field(
        max_length=256,
        description=(
            "Current independent command receipt IDs cited by structured_criterion_results, taken "
            "from content.command_evidence_artifact_id of your verification results. Do not copy "
            "generic artifact_ids or include transcript, patch, Engineer or stale receipt IDs. "
            "The control plane independently binds observed records; this list grants no proof."
        ),
    )
    regressions: list[BoundedText] = Field(max_length=128)
    required_repairs: list[BoundedText] = Field(max_length=128)
    proof_gaps: list[BoundedText] = Field(max_length=128)
    rationale: BoundedSummary
    structured_criterion_results: list[CriterionResult] | None = Field(
        default=None,
        max_length=128,
        description=(
            "Explicitly map every TaskSpec acceptance criterion once to your own current "
            "independent "
            "command receipts and exact command IDs. Passing code-change mappings require nonempty "
            "one-to-one command/receipt lists. Missing or inadequate proof remains inconclusive; "
            "never invent, repair or copy unrelated evidence references."
        ),
    )

    @field_validator("evidence_artifact_ids")
    @classmethod
    def validate_evidence_artifact_ids(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("VerifierVerdict evidence artifact IDs must be unique")
        return values


class RuntimeToolDefinition(FrozenStrictModel):
    name: RuntimeToolName
    description: BoundedText
    parameters_json_schema: dict[str, JsonValue]
    side_effect: bool = False

    @field_validator("parameters_json_schema")
    @classmethod
    def validate_parameters_schema(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        _validate_bounded_json(value, field_name="runtime tool schema")
        if value.get("type") != "object":
            raise ValueError("runtime tool parameters schema must describe an object")
        return value


class RuntimeToolCall(FrozenStrictModel):
    call_id: RuntimeToolCallId
    name: RuntimeToolName
    arguments: dict[str, JsonValue]

    @field_validator("arguments")
    @classmethod
    def validate_arguments(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        _validate_bounded_json(value, field_name="runtime tool arguments")
        return value


class RuntimeToolResult(FrozenStrictModel):
    call_id: RuntimeToolCallId
    name: RuntimeToolName
    outcome: RuntimeToolOutcome = RuntimeToolOutcome.SUCCEEDED
    content: dict[str, JsonValue] = Field(default_factory=dict)
    artifact_ids: tuple[ArtifactId, ...] = ()

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        _validate_bounded_json(value, field_name="runtime tool result")
        return value

    @field_validator("artifact_ids")
    @classmethod
    def validate_artifact_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) > 256 or len(values) != len(set(values)):
            raise ValueError("runtime tool result artifact IDs must be bounded and unique")
        return values


class RuntimeToolExecutionRecord(FrozenStrictModel):
    """Safe execution fact surface; arguments and raw executor output are excluded."""

    call_id: RuntimeToolCallId
    name: RuntimeToolName
    outcome: RuntimeToolOutcome
    side_effect: bool
    side_effect_committed: bool
    artifact_ids: tuple[ArtifactId, ...] = ()

    @model_validator(mode="after")
    def validate_side_effect_fact(self) -> RuntimeToolExecutionRecord:
        if len(self.artifact_ids) > 256 or len(self.artifact_ids) != len(set(self.artifact_ids)):
            raise ValueError("runtime tool record artifact IDs must be bounded and unique")
        if self.side_effect_committed and not self.side_effect:
            raise ValueError("only a side-effecting tool can commit a side effect")
        return self


class AgentInvocation(StrictModel):
    run_id: RunId
    task_id: TaskId
    agent_instance_id: AgentInstanceId
    role: RoleId
    stage: WorkflowStage
    iteration: int = Field(ge=0, le=100)
    max_steps: int = Field(ge=1, le=100)
    instructions: Annotated[str, StringConstraints(max_length=32_768)] | None = None
    context_artifact_ids: list[ArtifactId] = Field(default_factory=list, max_length=128)
    checkpoint_ref: ArtifactId | None = None
    input: dict[str, JsonValue]

    @field_validator("context_artifact_ids")
    @classmethod
    def validate_context_artifact_ids(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("runtime context artifact IDs must be unique")
        return values

    @field_validator("input")
    @classmethod
    def reject_execution_capabilities(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        protected = {
            "api_key",
            "candidate_workspace_path",
            "credential",
            "credential_ref",
            "host_path",
            "permission_grant",
            "project_root",
            "repository_path",
            "repository_root",
            "sandbox_handle",
            "sandbox_id",
            "secret_ref",
            "workspace_path",
            "workspace_host_path",
            "verification_workspace_path",
        }

        def visit(item: JsonValue) -> None:
            if isinstance(item, dict):
                for key, child in item.items():
                    lowered = key.casefold()
                    if (
                        lowered in protected
                        or lowered.endswith("_host_path")
                        or lowered.endswith("_filesystem_path")
                        or lowered.endswith("_absolute_path")
                        or lowered.endswith("_api_key")
                        or lowered.endswith("_credential")
                        or lowered.endswith("_secret")
                    ):
                        raise ValueError(
                            f"runtime input cannot contain execution capability {key!r}"
                        )
                    visit(child)
            elif isinstance(item, list):
                for child in item:
                    visit(child)
            elif isinstance(item, str) and (
                item.startswith(("/", "file://", "\\\\"))
                or re.match(r"^[A-Za-z]:[\\/]", item) is not None
            ):
                raise ValueError("runtime input cannot contain an absolute host path")

        _validate_bounded_json(value, field_name="runtime input", max_bytes=262_144)
        visit(value)
        return value


type RuntimeOutput = (
    ScopeDecision | FleetPatch | ImplementationReport | VerifierVerdict | SpecialistReport
)


class AgentInvocationResult(StrictModel):
    output: RuntimeOutput
    usage: UsageRecord | None = None
    checkpoint_ref: ArtifactId | None = None
    provider_metadata: RuntimeProviderMetadata | None = None


class SandboxCapabilities(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: SandboxProviderId
    security_level: SandboxSecurityLevel
    isolation_enforced: bool
    executes_code: bool
    supported_network_modes: tuple[SandboxNetworkMode, ...] = Field(min_length=1, max_length=2)
    supports_resource_limits: bool
    supports_recovery: bool
    supports_non_root: bool = False
    supports_read_only_root: bool = False
    supports_no_new_privileges: bool = False
    supports_capability_drop: bool = False

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, value: str) -> str:
        if not value or value.strip() != value:
            raise ValueError("sandbox provider must be a non-empty canonical identifier")
        return value

    @field_validator("supported_network_modes")
    @classmethod
    def validate_network_modes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        allowed = {"none", "approved-unrestricted"}
        if not values or len(values) != len(set(values)) or set(values) - allowed:
            raise ValueError(
                "sandbox network modes must be unique supported values and include a mode"
            )
        return values

    @model_validator(mode="after")
    def validate_capability_coherence(self) -> SandboxCapabilities:
        if self.provider == "fake" or self.security_level is SandboxSecurityLevel.FAKE:
            if self != self.phase1_fake():
                raise ValueError(
                    "the fake sandbox capability descriptor must exactly declare no "
                    "isolation, no code execution, no resource limits, and network=none"
                )
            return self
        if self.security_level is SandboxSecurityLevel.ISOLATED:
            if (
                not self.isolation_enforced
                or not self.executes_code
                or not self.supports_resource_limits
                or not self.supports_non_root
                or not self.supports_read_only_root
                or not self.supports_no_new_privileges
                or not self.supports_capability_drop
                or "none" not in self.supported_network_modes
            ):
                raise ValueError(
                    "isolated sandbox capabilities require enforced isolation, code "
                    "execution, resource limits, non-root execution, a read-only root, "
                    "no-new-privileges, capability dropping, and a network-none mode"
                )
        elif self.security_level is SandboxSecurityLevel.UNSAFE_HOST and (
            self.isolation_enforced or not self.executes_code
        ):
            raise ValueError(
                "unsafe-host sandbox capabilities cannot claim isolation and must execute code"
            )
        return self

    @classmethod
    def phase1_fake(cls) -> SandboxCapabilities:
        return cls.model_construct(
            provider="fake",
            security_level=SandboxSecurityLevel.FAKE,
            isolation_enforced=False,
            executes_code=False,
            supported_network_modes=("none",),
            supports_resource_limits=False,
            supports_recovery=True,
            supports_non_root=False,
            supports_read_only_root=False,
            supports_no_new_privileges=False,
            supports_capability_drop=False,
        )


class SandboxRequirements(FrozenStrictModel):
    isolation_required: bool = False
    code_execution_required: bool = False
    resource_limits_required: bool = False
    non_root_required: bool = False
    read_only_root_required: bool = False
    no_new_privileges_required: bool = False
    capability_drop_required: bool = False
    network_mode: SandboxNetworkMode = "none"


class SandboxConfiguration(FrozenStrictModel):
    provider: SandboxName = "fake"
    network_mode: SandboxNetworkMode = "none"
    image: (
        Annotated[
            str,
            StringConstraints(
                strip_whitespace=True,
                min_length=1,
                max_length=256,
                pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]*$",
            ),
        ]
        | None
    ) = None
    cpu_limit: float = Field(default=1.0, ge=0.001, le=16, multiple_of=0.001)
    memory_mb: int = Field(default=512, ge=64, le=32768)
    pids_limit: int = Field(default=128, ge=16, le=4096)
    shm_mb: int = Field(default=64, ge=16, le=1024)
    tmpfs_mb: int = Field(default=128, ge=16, le=4096)

    @model_validator(mode="after")
    def validate_provider_configuration(self) -> SandboxConfiguration:
        if self.provider == "docker" and self.image is None:
            raise ValueError("docker sandbox requires an explicit local image reference")
        if self.provider != "docker" and self.image is not None:
            raise ValueError("only the docker sandbox accepts an image reference")
        if self.provider == "local-unsafe" and self.network_mode != "approved-unrestricted":
            raise ValueError("local-unsafe must honestly report unrestricted host networking")
        if self.provider != "local-unsafe" and self.network_mode != "none":
            raise ValueError("Phase 3 isolated and fake configurations support network=none only")
        return self


class SandboxSpec(StrictModel):
    workspace_host_path: str
    project_id: ProjectId | None = None
    configuration: SandboxConfiguration = Field(default_factory=SandboxConfiguration)
    requirements: SandboxRequirements = Field(default_factory=SandboxRequirements)
    timeout_seconds: int = Field(default=60, ge=1, le=3600)
    environment: dict[str, str] = Field(default_factory=dict)
    unsafe_local_confirmed: bool = False
    image_identity: ImageIdentity | None = None
    daemon_identity: Sha256 | None = None

    @model_validator(mode="after")
    def validate_image_binding(self) -> SandboxSpec:
        if self.configuration.provider == "docker" and (
            self.image_identity is None or self.daemon_identity is None
        ):
            raise ValueError("Docker sandbox spec requires preflight image and daemon identities")
        if self.configuration.provider != "docker" and (
            self.image_identity is not None or self.daemon_identity is not None
        ):
            raise ValueError("Only Docker sandbox spec may carry image and daemon identities")
        return self


class SandboxHandle(StrictModel):
    sandbox_id: SandboxId
    run_id: RunId
    project_id: ProjectId | None = None
    workspace_host_path: str
    provider: SandboxName = "fake"
    capabilities: SandboxCapabilities = Field(default_factory=SandboxCapabilities.phase1_fake)
    configuration_hash: Sha256 | None = None
    image_identity: ImageIdentity | None = None
    daemon_identity: Sha256 | None = None
    recovery_scope_id: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{32}$")] | None = None

    @model_validator(mode="after")
    def validate_image_binding(self) -> SandboxHandle:
        if self.provider == "docker" and (
            self.image_identity is None
            or self.daemon_identity is None
            or self.recovery_scope_id is None
        ):
            raise ValueError(
                "Docker sandbox handle requires immutable image, daemon, and recovery identities"
            )
        if self.provider != "docker" and (
            self.image_identity is not None
            or self.daemon_identity is not None
            or self.recovery_scope_id is not None
        ):
            raise ValueError(
                "Only Docker sandbox handles may carry image, daemon, and recovery identities"
            )
        return self


class SandboxInspection(FrozenStrictModel):
    sandbox_id: SandboxId
    provider: SandboxName
    ready: bool
    capabilities: SandboxCapabilities
    configuration_hash: Sha256
    image_identity: ImageIdentity | None = None
    daemon_identity: Sha256 | None = None
    effective_network_mode: SandboxNetworkMode
    non_root: bool
    read_only_root: bool
    no_new_privileges: bool
    capabilities_dropped: bool
    resource_limits_enforced: bool
    exact_mounts: bool
    inspected_at: datetime

    _inspected_utc = field_validator("inspected_at")(_require_utc)

    @model_validator(mode="after")
    def validate_effective_security_claims(self) -> SandboxInspection:
        if self.capabilities.provider != self.provider:
            raise ValueError("sandbox inspection provider and capabilities do not match")
        if self.ready and self.capabilities.security_level is SandboxSecurityLevel.ISOLATED:
            if not all(
                (
                    self.capabilities.isolation_enforced,
                    self.capabilities.executes_code,
                    self.non_root,
                    self.read_only_root,
                    self.no_new_privileges,
                    self.capabilities_dropped,
                    self.resource_limits_enforced,
                    self.exact_mounts,
                )
            ):
                raise ValueError("isolated sandbox inspection reports weakened effective controls")
            if (
                self.image_identity is None
                or self.daemon_identity is None
                or self.effective_network_mode != "none"
            ):
                raise ValueError(
                    "isolated sandbox inspection requires image, daemon, and network binding"
                )
        if self.provider != "docker" and (
            self.image_identity is not None or self.daemon_identity is not None
        ):
            raise ValueError("only Docker inspection may report image and daemon identities")
        return self

    def missing_requirements(self, requirements: SandboxRequirements) -> list[str]:
        checks = {
            "isolation": (
                requirements.isolation_required,
                self.capabilities.isolation_enforced,
            ),
            "code_execution": (
                requirements.code_execution_required,
                self.capabilities.executes_code,
            ),
            "resource_limits": (
                requirements.resource_limits_required,
                self.resource_limits_enforced,
            ),
            "non_root": (requirements.non_root_required, self.non_root),
            "read_only_root": (
                requirements.read_only_root_required,
                self.read_only_root,
            ),
            "no_new_privileges": (
                requirements.no_new_privileges_required,
                self.no_new_privileges,
            ),
            "capability_drop": (
                requirements.capability_drop_required,
                self.capabilities_dropped,
            ),
            f"network:{requirements.network_mode}": (
                True,
                self.effective_network_mode == requirements.network_mode,
            ),
        }
        return sorted(
            name for name, (required, present) in checks.items() if required and not present
        )


class SandboxPreflight(FrozenStrictModel):
    provider: SandboxName
    ready: bool
    capabilities: SandboxCapabilities
    configuration_hash: Sha256
    requirements_hash: Sha256
    image_identity: ImageIdentity | None = None
    daemon_identity: Sha256 | None = None
    recovery_scope_id: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{32}$")] | None = None
    executable_path: Annotated[str, StringConstraints(min_length=1, max_length=4096)] | None = None
    cli_version: Annotated[str, StringConstraints(min_length=1, max_length=128)] | None = None
    daemon_os: Literal["linux"] | None = None
    daemon_architecture: Literal["amd64", "arm64"] | None = None
    daemon_server_version: (
        Annotated[str, StringConstraints(min_length=1, max_length=128)] | None
    ) = None
    endpoint_kind: Literal["none", "local-unix", "host"]
    diagnostic: BoundedText
    checked_at: datetime

    _checked_utc = field_validator("checked_at")(_require_utc)

    @model_validator(mode="after")
    def validate_provider_identity(self) -> SandboxPreflight:
        if self.capabilities.provider != self.provider:
            raise ValueError("sandbox preflight capability provider does not match")
        if self.provider == "docker" and (
            self.image_identity is None
            or self.daemon_identity is None
            or self.recovery_scope_id is None
            or self.executable_path is None
            or self.cli_version is None
            or self.daemon_os is None
            or self.daemon_architecture is None
            or self.daemon_server_version is None
        ):
            raise ValueError(
                "Docker preflight requires complete CLI, daemon, image, and recovery identities"
            )
        if self.provider != "docker" and (
            self.image_identity is not None
            or self.daemon_identity is not None
            or self.recovery_scope_id is not None
            or self.executable_path is not None
            or self.cli_version is not None
            or self.daemon_os is not None
            or self.daemon_architecture is not None
            or self.daemon_server_version is not None
        ):
            raise ValueError("only Docker preflight may report Docker runtime identities")
        return self


class SandboxExecutionHandle(FrozenStrictModel):
    execution_id: ExecutionId
    sandbox_id: SandboxId
    run_id: RunId
    provider: SandboxName
    native_resource_id: Annotated[str, StringConstraints(min_length=1, max_length=256)]
    labels: dict[str, str] = Field(default_factory=dict, min_length=1, max_length=16)
    labels_sha256: Sha256

    @field_validator("labels")
    @classmethod
    def validate_labels(cls, values: dict[str, str]) -> dict[str, str]:
        if any(
            re.fullmatch(r"[a-z][a-z0-9.-]{0,63}", key) is None
            or not value
            or len(value) > 128
            or "\x00" in value
            for key, value in values.items()
        ):
            raise ValueError("sandbox execution labels must be bounded canonical strings")
        return dict(sorted(values.items()))

    @model_validator(mode="after")
    def validate_label_binding(self) -> SandboxExecutionHandle:
        if canonical_json_hash(self.labels) != self.labels_sha256:
            raise ValueError("sandbox execution label hash does not match")
        if self.provider == "docker":
            allowed = {
                "agent-fleet.agent",
                "agent-fleet.daemon",
                "agent-fleet.execution",
                "agent-fleet.installation",
                "agent-fleet.intent",
                "agent-fleet.managed",
                "agent-fleet.project",
                "agent-fleet.run",
                "agent-fleet.sandbox",
                "agent-fleet.stage",
                "agent-fleet.task",
            }
            if (
                set(self.labels) != allowed
                or self.labels.get("agent-fleet.managed") != "true"
                or self.labels.get("agent-fleet.run") != self.run_id
                or self.labels.get("agent-fleet.sandbox") != self.sandbox_id
                or self.labels.get("agent-fleet.execution") != self.execution_id
                or re.fullmatch(r"[0-9a-f]{32}", self.labels.get("agent-fleet.installation", ""))
                is None
                or re.fullmatch(r"[0-9a-f]{64}", self.labels.get("agent-fleet.daemon", "")) is None
            ):
                raise ValueError("Docker execution labels do not match their trusted identities")
        return self


class SandboxExecutionRecoveryRequest(FrozenStrictModel):
    execution_id: ExecutionId
    sandbox_id: SandboxId
    run_id: RunId
    project_id: ProjectId
    provider: SandboxName
    intent_id: IntentId
    task_id: TaskId
    agent_instance_id: AgentInstanceId
    stage: WorkflowStage
    creation_dispatched: bool


class SandboxCleanupResult(FrozenStrictModel):
    provider: SandboxName
    resource_id: Annotated[str, StringConstraints(min_length=1, max_length=256)]
    resources_found: int = Field(ge=0, le=128)
    resources_removed: int = Field(ge=0, le=128)
    reconciled: bool
    complete: bool
    completed_at: datetime

    _cleanup_utc = field_validator("completed_at")(_require_utc)

    @model_validator(mode="after")
    def validate_cleanup_counts(self) -> SandboxCleanupResult:
        if self.resources_removed > self.resources_found:
            raise ValueError("sandbox cleanup cannot remove more resources than it found")
        if self.complete and not self.reconciled:
            raise ValueError("complete sandbox cleanup must be reconciled")
        if self.complete and self.resources_removed != self.resources_found:
            raise ValueError("complete sandbox cleanup must remove every found resource")
        return self


class ExecRequest(StrictModel):
    execution_id: ExecutionId | None = None
    intent_id: IntentId | None = None
    task_id: TaskId | None = None
    agent_instance_id: AgentInstanceId | None = None
    stage: WorkflowStage | None = None
    executable: str
    argv: list[str]
    cwd: str
    environment: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: int = Field(default=60, ge=1, le=3600)
    max_output_bytes: int = Field(default=64_000, ge=1, le=1_000_000)
    network_mode: SandboxNetworkMode = "none"
    command_spec_hash: Sha256 | None = None

    @field_validator("executable")
    @classmethod
    def validate_executable(cls, value: str) -> str:
        if re.fullmatch(r"(?:[A-Za-z0-9._+-]+|\./[A-Za-z0-9._+-]+)", value) is None:
            raise ValueError("execution executable must be a canonical bare or ./ name")
        executable_name = PurePosixPath(value).name.casefold()
        if executable_name in {
            "bash",
            "cmd",
            "dash",
            "env",
            "fish",
            "ksh",
            "powershell",
            "pwsh",
            "sh",
            "zsh",
        } or executable_name.endswith((".bat", ".cmd", ".ps1", ".sh")):
            raise ValueError("execution request cannot invoke a shell")
        return value

    @field_validator("argv")
    @classmethod
    def validate_exec_argv(cls, values: list[str]) -> list[str]:
        if len(values) > 128 or any("\x00" in value or len(value) > 4096 for value in values):
            raise ValueError("execution argv must contain at most 128 bounded non-NUL values")
        if sum(len(value.encode("utf-8")) for value in values) > 65_536:
            raise ValueError("execution argv exceeds the total byte limit")
        return values

    @field_validator("cwd")
    @classmethod
    def validate_exec_cwd(cls, value: str) -> str:
        if value == ".":
            return value
        path = PurePosixPath(value)
        if (
            value.startswith("/")
            or "\\" in value
            or "\x00" in value
            or not path.parts
            or "." in path.parts
            or ".." in path.parts
            or path.as_posix() != value
        ):
            raise ValueError("execution cwd must be a canonical repository-relative path")
        return value

    @field_validator("environment")
    @classmethod
    def validate_exec_environment(cls, values: dict[str, str]) -> dict[str, str]:
        allowed = {
            "CI",
            "LANG",
            "LC_ALL",
            "PYTHONDONTWRITEBYTECODE",
            "PYTHONPATH",
            "PYTHONUNBUFFERED",
        }
        if set(values) - allowed or any("\x00" in value for value in values.values()):
            raise ValueError("execution environment is outside the fixed non-secret allowlist")
        return dict(sorted(values.items()))

    @model_validator(mode="after")
    def validate_execution_identity(self) -> ExecRequest:
        identity_values = (
            self.execution_id,
            self.intent_id,
            self.task_id,
            self.agent_instance_id,
            self.stage,
            self.command_spec_hash,
        )
        if any(value is not None for value in identity_values) and any(
            value is None for value in identity_values
        ):
            raise ValueError("execution identity must be supplied completely or omitted")
        return self


class SandboxExecutionMetadata(FrozenStrictModel):
    execution_id: ExecutionId
    provider: SandboxName
    resource_id_sha256: Sha256
    configuration_hash: Sha256
    capabilities_hash: Sha256
    inspection_hash: Sha256 | None = None
    inspection: SandboxInspection | None = None
    resource_handle: SandboxExecutionHandle
    cleanup_result: SandboxCleanupResult

    @model_validator(mode="after")
    def validate_inspection_binding(self) -> SandboxExecutionMetadata:
        if (self.inspection_hash is None) != (self.inspection is None):
            raise ValueError("sandbox execution inspection content and hash must be paired")
        if self.inspection is not None:
            if self.inspection.provider != self.provider:
                raise ValueError("sandbox execution inspection provider does not match")
            if self.inspection.configuration_hash != self.configuration_hash:
                raise ValueError("sandbox execution inspection configuration does not match")
            if (
                canonical_json_hash(self.inspection.capabilities.model_dump(mode="json"))
                != self.capabilities_hash
            ):
                raise ValueError("sandbox execution inspection capabilities do not match")
            if canonical_json_hash(self.inspection.model_dump(mode="json")) != self.inspection_hash:
                raise ValueError("sandbox execution inspection hash does not match")
        if (
            self.resource_handle.execution_id != self.execution_id
            or self.resource_handle.provider != self.provider
            or self.cleanup_result.provider != self.provider
            or self.cleanup_result.resource_id != self.resource_handle.native_resource_id
            or not self.cleanup_result.complete
        ):
            raise ValueError("sandbox execution resource or cleanup binding does not match")
        return self


class ExecResult(StrictModel):
    exit_code: int
    stdout: str
    stderr: str
    started_at: datetime
    completed_at: datetime
    timed_out: bool = False
    output_truncated: bool = False
    execution: SandboxExecutionMetadata | None = None

    _started_utc = field_validator("started_at")(_require_utc)
    _completed_utc = field_validator("completed_at")(_require_utc)


class DoctorCheck(StrictModel):
    name: str
    ok: bool
    required: bool
    detail: str


class DoctorReport(StrictModel):
    healthy: bool
    checks: list[DoctorCheck]
    warnings: list[str]


class JsonError(StrictModel):
    code: str
    message: str
    remediation: str
    details: dict[str, JsonValue] = Field(default_factory=dict)


class JsonEnvelope(StrictModel):
    api_version: Literal["agentfleet.dev/v1alpha1"] = "agentfleet.dev/v1alpha1"
    ok: bool
    command: str
    correlation_id: CorrelationId
    data: JsonValue | None
    warnings: list[str] = Field(default_factory=list)
    error: JsonError | None = None


def jsonable(value: Any) -> JsonValue:
    """Convert supported domain values to validated JSON-compatible data."""

    class _JsonWrapper(BaseModel):
        value: JsonValue

    return _JsonWrapper(value=value).value
