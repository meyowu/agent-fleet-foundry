"""Canonical Phase 0/1 domain and boundary models."""

from __future__ import annotations

from datetime import datetime
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


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value


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


class Project(StrictModel):
    project_id: ProjectId
    canonical_root: str
    remote_fingerprint: str | None = None
    identity_hash: Sha256
    fleet_spec_hash: Sha256 | None = None
    config_snapshot_artifact_id: ArtifactId | None = None
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


class Run(StrictModel):
    run_id: RunId
    project_id: ProjectId
    correlation_id: CorrelationId
    goal: str
    base_revision: str
    target_status_fingerprint: Sha256
    runtime_name: Literal["fake"] = "fake"
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


class AcceptanceCriterion(StrictModel):
    criterion_id: CriterionId
    description: NonEmptyText


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
    task_id: TaskId
    role: RoleId
    status: AgentStatus
    iteration: int = Field(ge=0)
    created_at: datetime
    completed_at: datetime | None = None

    _created_utc = field_validator("created_at")(_require_utc)
    _completed_utc = field_validator("completed_at")(
        lambda value: _require_utc(value) if value is not None else value
    )


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


class AgentInvocation(StrictModel):
    run_id: RunId
    task_id: TaskId
    agent_instance_id: AgentInstanceId
    role: RoleId
    stage: WorkflowStage
    iteration: int
    max_steps: int
    input: dict[str, JsonValue]

    @field_validator("input")
    @classmethod
    def reject_execution_capabilities(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        protected = {
            "candidate_workspace_path",
            "host_path",
            "project_root",
            "repository_path",
            "repository_root",
            "sandbox_handle",
            "sandbox_id",
            "workspace_path",
            "workspace_host_path",
            "verification_workspace_path",
        }

        def visit(item: JsonValue) -> None:
            if isinstance(item, dict):
                for key, child in item.items():
                    if (
                        key in protected
                        or key.endswith("_host_path")
                        or key.endswith("_filesystem_path")
                        or key.endswith("_absolute_path")
                    ):
                        raise ValueError(
                            f"runtime input cannot contain execution capability {key!r}"
                        )
                    visit(child)
            elif isinstance(item, list):
                for child in item:
                    visit(child)

        visit(value)
        return value


class AgentInvocationResult(StrictModel):
    output: dict[str, JsonValue]
    checkpoint_ref: str | None = None


class ScriptedAction(StrictModel):
    action: ActionId
    resource: CanonicalResource
    parameters: dict[str, JsonValue]
    reason: str
    side_effect: bool
    idempotency_key: str


class ImplementationReport(StrictModel):
    summary: str
    intended_changed_paths: list[str]
    tests_added_or_changed: list[str]
    criterion_results: list[str]
    evidence_artifact_ids: list[ArtifactId]
    unresolved_limitations: list[str]
    verifier_focus: list[str]


class EngineerScript(StrictModel):
    actions: list[ScriptedAction]
    report: ImplementationReport


class VerifierVerdict(StrictModel):
    verdict: Verdict
    criterion_results: list[str]
    evidence_artifact_ids: list[ArtifactId]
    regressions: list[str]
    required_repairs: list[str]
    proof_gaps: list[str]
    rationale: str

    @field_validator("evidence_artifact_ids")
    @classmethod
    def validate_evidence_artifact_ids(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("VerifierVerdict evidence artifact IDs must be unique")
        return values


class VerifierScript(StrictModel):
    actions: list[ScriptedAction]
    verdict: VerifierVerdict


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
