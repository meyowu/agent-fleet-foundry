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
WorkspaceId = Annotated[str, StringConstraints(pattern=r"^ws_[0-9a-f]{32}$")]
FleetPlanId = Annotated[str, StringConstraints(pattern=r"^plan_[0-9a-f]{32}$")]
FleetPatchId = Annotated[str, StringConstraints(pattern=r"^fpatch_[0-9a-f]{32}$")]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
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
    if runtime_name == "pydantic-ai" and (provider_model is None or credential_ref is None):
        raise ValueError("pydantic-ai runtime requires provider_model and credential_ref")


class AgentRole(StrEnum):
    COS = "cos"
    ENGINEER = "engineer"
    VERIFIER = "verifier"


class AgentLifecycle(StrEnum):
    PERSISTENT = "persistent"
    PER_TASK = "per_task"


class AgentStatus(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


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
    PAUSED_FOR_APPROVAL = "paused_for_approval"
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
    CONFIG_SNAPSHOT = "config_snapshot"
    TASK_SPEC = "task_spec"
    IMPLEMENTATION_REPORT = "implementation_report"
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


class WorkspaceKind(StrEnum):
    CANDIDATE = "candidate"
    VERIFICATION = "verification"


class LeaseKind(StrEnum):
    WORKTREE = "worktree"
    SANDBOX = "sandbox"


class LeaseStatus(StrEnum):
    ACTIVE = "active"
    RELEASED = "released"
    RECOVERED = "recovered"


class PermissionOutcome(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


class ApprovalChoice(StrEnum):
    DENY = "deny"
    ALLOW_ONCE = "allow_once"


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
        return self


class Run(StrictModel):
    run_id: RunId
    project_id: ProjectId
    correlation_id: CorrelationId
    goal: str
    base_revision: str
    target_status_fingerprint: Sha256
    runtime_name: RuntimeName = "fake"
    provider_model: ProviderModelId | None = None
    credential_ref: CredentialReferenceString | None = None
    sandbox_name: Literal["fake"] = "fake"
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
    verifier_verdict_artifact_id: ArtifactId | None = None
    evidence_bundle_artifact_id: ArtifactId | None = None
    evidence_bundle_hash: Sha256 | None = None
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
        _validate_runtime_selection(
            self.runtime_name,
            self.provider_model,
            self.credential_ref,
        )
        return self


class AcceptanceCriterion(StrictModel):
    criterion_id: CriterionId
    description: BoundedText


class ScopeDecision(StrictModel):
    """Untrusted CoS proposal accepted only after control-plane validation."""

    normalized_goal: BoundedSummary
    workflow: WorkflowId = "code-change"
    change_kind: Literal["read_only", "code_change"] = "code_change"
    fleet_strategy: FleetStrategyName
    allowed_paths: list[LogicalRepoPath] = Field(max_length=128)
    forbidden_paths: list[LogicalRepoPath] = Field(max_length=128)
    acceptance_criteria: list[AcceptanceCriterion] = Field(min_length=1, max_length=128)
    required_evidence: list[EvidenceRequirementId] = Field(min_length=1, max_length=32)

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
        if self.task_id is None and self.role != AgentRole.COS.value:
            raise ValueError("only the CoS may exist before a TaskSpec is bound")
        return self


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
    resource_id: WorkspaceId | SandboxId
    path: str | None = None
    status: LeaseStatus
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    _created_utc = field_validator("created_at")(_require_utc)
    _updated_utc = field_validator("updated_at")(_require_utc)

    @model_validator(mode="after")
    def validate_resource_identity(self) -> ResourceLease:
        expected_prefix = "ws_" if self.kind is LeaseKind.WORKTREE else "sandbox_"
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
        default_factory=lambda: [ApprovalChoice.DENY, ApprovalChoice.ALLOW_ONCE]
    )
    created_at: datetime
    expires_at: datetime
    resolved_at: datetime | None = None
    denial_reason: str | None = None

    _created_utc = field_validator("created_at")(_require_utc)
    _expires_utc = field_validator("expires_at")(_require_utc)
    _resolved_utc = field_validator("resolved_at")(
        lambda value: _require_utc(value) if value is not None else value
    )


class CapabilityGrant(StrictModel):
    grant_id: GrantId
    request_id: ApprovalRequestId
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
    expires_at: datetime
    remaining_uses: int = Field(default=1, ge=0, le=1)
    consumed_at: datetime | None = None

    _issued_utc = field_validator("issued_at")(_require_utc)
    _expires_utc = field_validator("expires_at")(_require_utc)
    _consumed_utc = field_validator("consumed_at")(
        lambda value: _require_utc(value) if value is not None else value
    )


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


class VerifierVerdict(StrictModel):
    verdict: Verdict
    criterion_results: list[BoundedText] = Field(max_length=128)
    evidence_artifact_ids: list[ArtifactId] = Field(max_length=256)
    regressions: list[BoundedText] = Field(max_length=128)
    required_repairs: list[BoundedText] = Field(max_length=128)
    proof_gaps: list[BoundedText] = Field(max_length=128)
    rationale: BoundedSummary

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


type RuntimeOutput = ScopeDecision | ImplementationReport | VerifierVerdict


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
                or "none" not in self.supported_network_modes
            ):
                raise ValueError(
                    "isolated sandbox capabilities require enforced isolation, code "
                    "execution, resource limits, and a network-none mode"
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
        )


class SandboxSpec(StrictModel):
    workspace_host_path: str
    timeout_seconds: int = Field(default=60, ge=1, le=3600)
    environment: dict[str, str] = Field(default_factory=dict)


class SandboxHandle(StrictModel):
    sandbox_id: SandboxId
    run_id: RunId
    workspace_host_path: str


class ExecRequest(StrictModel):
    executable: str
    argv: list[str]
    cwd: str
    environment: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: int = Field(default=60, ge=1, le=3600)
    max_output_bytes: int = Field(default=64_000, ge=1, le=1_000_000)


class ExecResult(StrictModel):
    exit_code: int
    stdout: str
    stderr: str
    started_at: datetime
    completed_at: datetime
    timed_out: bool = False
    output_truncated: bool = False

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
