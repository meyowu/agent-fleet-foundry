"""Canonical Phase 0/1 domain and boundary models."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints, field_validator

OpaqueId = Annotated[str, StringConstraints(pattern=r"^[a-z]+_[0-9a-f]{32}$")]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


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


class Project(StrictModel):
    project_id: OpaqueId
    canonical_root: str
    remote_fingerprint: str | None = None
    identity_hash: Sha256
    fleet_spec_hash: Sha256 | None = None
    init_status_fingerprint: Sha256 | None = None
    created_at: datetime
    updated_at: datetime

    _created_utc = field_validator("created_at")(_require_utc)
    _updated_utc = field_validator("updated_at")(_require_utc)


class Run(StrictModel):
    run_id: OpaqueId
    project_id: OpaqueId
    correlation_id: OpaqueId
    goal: str
    base_revision: str
    target_status_fingerprint: Sha256
    runtime_name: Literal["fake"] = "fake"
    sandbox_name: Literal["fake"] = "fake"
    fake_scenario: FakeScenario = FakeScenario.SUCCESS
    status: RunStatus = RunStatus.CREATED
    stage: WorkflowStage | None = None
    task_id: OpaqueId | None = None
    pending_approval_id: OpaqueId | None = None
    max_repair_iterations: int = Field(default=1, ge=0, le=5)
    repair_iterations: int = Field(default=0, ge=0, le=5)
    patch_artifact_id: OpaqueId | None = None
    patch_sha256: Sha256 | None = None
    verifier_workspace_mutated: bool = False
    applied_revision: str | None = None
    created_at: datetime
    updated_at: datetime

    _created_utc = field_validator("created_at")(_require_utc)
    _updated_utc = field_validator("updated_at")(_require_utc)


class AcceptanceCriterion(StrictModel):
    criterion_id: str
    description: str


class TaskSpec(StrictModel):
    task_id: OpaqueId
    run_id: OpaqueId
    original_goal: str
    normalized_goal: str
    workflow: Literal["code-change"] = "code-change"
    base_revision: str
    allowed_paths: list[str]
    forbidden_paths: list[str]
    acceptance_criteria: list[AcceptanceCriterion]
    required_evidence: list[str]
    max_repair_iterations: int = Field(ge=0, le=5)
    config_snapshot_hash: Sha256
    created_at: datetime

    _created_utc = field_validator("created_at")(_require_utc)


class AgentSpec(StrictModel):
    role: AgentRole
    lifecycle: AgentLifecycle
    allowed_tools: list[str]
    max_steps: int = Field(ge=1, le=100)


class AgentInstance(StrictModel):
    agent_instance_id: OpaqueId
    run_id: OpaqueId
    task_id: OpaqueId
    role: AgentRole
    status: AgentStatus
    iteration: int = Field(ge=0)
    created_at: datetime
    completed_at: datetime | None = None

    _created_utc = field_validator("created_at")(_require_utc)
    _completed_utc = field_validator("completed_at")(
        lambda value: _require_utc(value) if value is not None else value
    )


class FleetEvent(StrictModel):
    event_id: OpaqueId
    event_type: str
    schema_version: Literal[1] = 1
    occurred_at: datetime
    project_id: OpaqueId
    run_id: OpaqueId | None = None
    task_id: OpaqueId | None = None
    agent_instance_id: OpaqueId | None = None
    correlation_id: OpaqueId
    causation_id: OpaqueId | None = None
    sequence: int | None = Field(default=None, ge=1)
    payload: dict[str, JsonValue] = Field(default_factory=dict)
    redaction_summary: list[str] = Field(default_factory=list)

    _occurred_utc = field_validator("occurred_at")(_require_utc)


class ArtifactMetadata(StrictModel):
    artifact_id: OpaqueId
    kind: ArtifactKind
    project_id: OpaqueId
    run_id: OpaqueId | None = None
    task_id: OpaqueId | None = None
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
    workspace_id: OpaqueId
    run_id: OpaqueId
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
    lease_id: OpaqueId
    run_id: OpaqueId
    kind: LeaseKind
    resource_id: str
    path: str | None = None
    status: LeaseStatus
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    _created_utc = field_validator("created_at")(_require_utc)
    _updated_utc = field_validator("updated_at")(_require_utc)


class CanonicalResource(StrictModel):
    kind: Literal["workspace_path", "fake_command", "fake_side_effect"]
    identifier: str


class ToolIntent(StrictModel):
    intent_id: OpaqueId
    run_id: OpaqueId
    task_id: OpaqueId
    agent_instance_id: OpaqueId
    principal_role: AgentRole
    workflow: Literal["code-change"]
    stage: WorkflowStage
    action: Literal["workspace.write_file", "command.run", "fixture.record_side_effect"]
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
    approval_request_id: OpaqueId | None = None
    result: dict[str, JsonValue] | None = None


class PermissionDecision(StrictModel):
    outcome: PermissionOutcome
    decision_code: str
    explanation: str
    protected: bool = False


class ApprovalRequest(StrictModel):
    request_id: OpaqueId
    intent_id: OpaqueId
    run_id: OpaqueId
    intent_hash: Sha256
    principal_role: AgentRole
    action: str
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
    grant_id: OpaqueId
    request_id: OpaqueId
    intent_id: OpaqueId
    project_id: OpaqueId
    run_id: OpaqueId
    task_id: OpaqueId
    agent_instance_id: OpaqueId
    principal_role: AgentRole
    action: str
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
    run_id: OpaqueId
    task_id: OpaqueId
    agent_instance_id: OpaqueId
    role: AgentRole
    stage: WorkflowStage
    iteration: int
    max_steps: int
    input: dict[str, JsonValue]


class AgentInvocationResult(StrictModel):
    output: dict[str, JsonValue]
    checkpoint_ref: str | None = None


class ScriptedAction(StrictModel):
    action: Literal["workspace.write_file", "command.run", "fixture.record_side_effect"]
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
    evidence_artifact_ids: list[str]
    unresolved_limitations: list[str]
    verifier_focus: list[str]


class EngineerScript(StrictModel):
    actions: list[ScriptedAction]
    report: ImplementationReport


class VerifierVerdict(StrictModel):
    verdict: Verdict
    criterion_results: list[str]
    evidence_artifact_ids: list[str]
    regressions: list[str]
    required_repairs: list[str]
    proof_gaps: list[str]
    rationale: str


class VerifierScript(StrictModel):
    actions: list[ScriptedAction]
    verdict: VerifierVerdict
    simulate_workspace_mutation: bool = False


class SandboxSpec(StrictModel):
    workspace_host_path: str
    timeout_seconds: int = Field(default=60, ge=1, le=3600)
    environment: dict[str, str] = Field(default_factory=dict)


class SandboxHandle(StrictModel):
    sandbox_id: OpaqueId
    run_id: OpaqueId
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
    correlation_id: str
    data: JsonValue | None
    warnings: list[str] = Field(default_factory=list)
    error: JsonError | None = None


def jsonable(value: Any) -> JsonValue:
    """Convert supported domain values to validated JSON-compatible data."""

    class _JsonWrapper(BaseModel):
        value: JsonValue

    return _JsonWrapper(value=value).value
