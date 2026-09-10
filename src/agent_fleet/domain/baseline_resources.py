"""Immutable sibling resource ownership; no Run-compatible identity or metadata."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, field_validator, model_validator

from agent_fleet.domain.baseline import (
    BaselineAuthorizationId,
    BaselineCanonicalSnapshot,
    BaselineClaimId,
    BaselineExecution,
    BaselineExecutionId,
    BaselineId,
    BaselineLeaseId,
    BaselineModel,
    BaselineReport,
    BaselineReview,
    BaselineSandboxId,
    BaselineSandboxPolicy,
    BaselineWorkspaceId,
    CommitId,
    InstallationId,
    canonical,
    reconstruct_command,
    reconstruct_sandbox,
    sandbox_policy,
    snapshot_model,
)
from agent_fleet.domain.evaluation import require_utc
from agent_fleet.domain.models import (
    ImageIdentity,
    ProjectId,
    SandboxCapabilities,
    SandboxCleanupResult,
    Sha256,
)
from agent_fleet.domain.security import sha256_bytes

NativeId = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class BaselineResourceOwner(BaselineModel):
    baseline_id: BaselineId
    project_id: ProjectId
    review_sha256: Sha256


class BaselineWorkspace(BaselineModel):
    owner: BaselineResourceOwner
    workspace_id: BaselineWorkspaceId
    path: str = Field(min_length=1, max_length=4096)
    base_revision: CommitId
    approved_source_sha256: Sha256
    materialized_source_sha256: Sha256 | None = None

    @model_validator(mode="after")
    def exact_path(self) -> Self:
        path = Path(self.path)
        if (
            not path.is_absolute()
            or str(path) != self.path
            or ".." in path.parts
            or path.name != self.workspace_id
            or path.parent.name != self.owner.baseline_id
            or path.parent.parent.name != "baseline-workspaces"
            or self.materialized_source_sha256 not in {None, self.approved_source_sha256}
        ):
            raise ValueError("baseline workspace path/source binding is inconsistent")
        return self


class BaselineSandboxSpec(BaselineModel):
    owner: BaselineResourceOwner
    workspace: BaselineWorkspace
    sandbox: BaselineCanonicalSnapshot
    mount_policy: Literal["baseline-readonly-v1"] = "baseline-readonly-v1"

    @model_validator(mode="after")
    def exact_workspace(self) -> Self:
        spec = reconstruct_sandbox(self.sandbox)
        if (
            self.owner != self.workspace.owner
            or self.workspace.materialized_source_sha256 != self.workspace.approved_source_sha256
            or spec.project_id != self.owner.project_id
            or spec.workspace_host_path != self.workspace.path
        ):
            raise ValueError("baseline sandbox spec does not bind activated source")
        return self


class BaselineSandboxHandle(BaselineModel):
    owner: BaselineResourceOwner
    sandbox_id: BaselineSandboxId
    workspace_id: BaselineWorkspaceId
    workspace_host_path: str = Field(min_length=1, max_length=4096)
    provider: Literal["docker"] = "docker"
    capabilities: BaselineCanonicalSnapshot
    configuration_sha256: Sha256
    sandbox_policy_sha256: Sha256
    sandbox_spec_sha256: Sha256
    approved_source_sha256: Sha256
    materialized_source_sha256: Sha256
    image_identity: ImageIdentity
    daemon_identity: Sha256
    recovery_scope_id: InstallationId
    mount_policy: Literal["baseline-readonly-v1"] = "baseline-readonly-v1"

    @model_validator(mode="after")
    def exact_bindings(self) -> Self:
        caps = snapshot_model(self.capabilities, "capabilities-v1", SandboxCapabilities)
        if (
            caps.provider != "docker"
            or not caps.isolation_enforced
            or not caps.supports_recovery
            or self.approved_source_sha256 != self.materialized_source_sha256
            or Path(self.workspace_host_path).name != self.workspace_id
            or Path(self.workspace_host_path).parent.name != self.owner.baseline_id
            or Path(self.workspace_host_path).parent.parent.name != "baseline-workspaces"
        ):
            raise ValueError("baseline sandbox handle identity is inconsistent")
        return self


def baseline_sandbox_handle(
    spec: BaselineSandboxSpec, sandbox_id: str, review: BaselineReview
) -> BaselineSandboxHandle:
    """Derive every prepared identity from the exact persisted reservation/review."""
    if (
        review.digest != spec.owner.review_sha256
        or review.baseline_id != spec.owner.baseline_id
        or review.project_id != spec.owner.project_id
        or review.capabilities is None
        or review.sandbox_policy is None
        or sandbox_policy(spec.sandbox) != review.sandbox_policy
        or spec.workspace.approved_source_sha256 != review.approved_source_sha256
    ):
        raise ValueError("baseline sandbox reservation differs from its approval")
    policy = snapshot_model(review.sandbox_policy, "sandbox-policy-v1", BaselineSandboxPolicy)
    return BaselineSandboxHandle(
        owner=spec.owner,
        sandbox_id=sandbox_id,
        workspace_id=spec.workspace.workspace_id,
        workspace_host_path=spec.workspace.path,
        capabilities=review.capabilities,
        configuration_sha256=policy.configuration.sha256,
        sandbox_policy_sha256=review.sandbox_policy.sha256,
        sandbox_spec_sha256=spec.sandbox.sha256,
        approved_source_sha256=review.approved_source_sha256,
        materialized_source_sha256=review.approved_source_sha256,
        image_identity=policy.image_identity,
        daemon_identity=policy.daemon_identity,
        recovery_scope_id=review.installation_id,
    )


class BaselineExecRequest(BaselineModel):
    owner: BaselineResourceOwner
    claim_id: BaselineClaimId
    execution_id: BaselineExecutionId
    workspace_id: BaselineWorkspaceId
    command: BaselineCanonicalSnapshot

    @model_validator(mode="after")
    def command_contract(self) -> Self:
        reconstruct_command(self.command)
        return self


def baseline_labels(
    sandbox: BaselineSandboxHandle, request: BaselineExecRequest
) -> tuple[tuple[str, str], ...]:
    if sandbox.owner != request.owner or sandbox.workspace_id != request.workspace_id:
        raise ValueError("baseline request belongs to another sandbox owner")
    return tuple(
        sorted(
            {
                "agent-fleet.managed": "true",
                "agent-fleet.installation": sandbox.recovery_scope_id,
                "agent-fleet.owner-kind": "baseline",
                "agent-fleet.baseline": request.owner.baseline_id,
                "agent-fleet.project": request.owner.project_id,
                "agent-fleet.review": request.owner.review_sha256,
                "agent-fleet.claim": request.claim_id,
                "agent-fleet.sandbox": sandbox.sandbox_id,
                "agent-fleet.execution": request.execution_id,
                "agent-fleet.command": request.command.sha256,
                "agent-fleet.daemon": sandbox.daemon_identity,
            }.items()
        )
    )


class BaselineExecutionHandle(BaselineModel):
    owner: BaselineResourceOwner
    claim_id: BaselineClaimId
    execution_id: BaselineExecutionId
    sandbox_id: BaselineSandboxId
    provider: Literal["docker"] = "docker"
    native_resource_id: NativeId
    labels: tuple[tuple[str, str], ...] = Field(min_length=11, max_length=11)
    labels_sha256: Sha256

    @model_validator(mode="after")
    def exact_labels(self) -> Self:
        labels = dict(self.labels)
        fixed = {
            "agent-fleet.managed": "true",
            "agent-fleet.owner-kind": "baseline",
            "agent-fleet.baseline": self.owner.baseline_id,
            "agent-fleet.project": self.owner.project_id,
            "agent-fleet.review": self.owner.review_sha256,
            "agent-fleet.claim": self.claim_id,
            "agent-fleet.sandbox": self.sandbox_id,
            "agent-fleet.execution": self.execution_id,
        }
        from pydantic import TypeAdapter

        if (
            self.labels != tuple(sorted(labels.items()))
            or set(labels)
            != set(fixed)
            | {"agent-fleet.installation", "agent-fleet.command", "agent-fleet.daemon"}
            or any(labels.get(key) != value for key, value in fixed.items())
            or sha256_bytes(canonical(labels)) != self.labels_sha256
        ):
            raise ValueError("baseline native labels are not exact")
        TypeAdapter(InstallationId).validate_python(labels["agent-fleet.installation"], strict=True)
        TypeAdapter(Sha256).validate_python(labels["agent-fleet.command"], strict=True)
        TypeAdapter(Sha256).validate_python(labels["agent-fleet.daemon"], strict=True)
        return self

    @property
    def native_name(self) -> str:
        return f"agent-fleet-baseline-{self.execution_id}"


class BaselineExecutionRecoveryRequest(BaselineModel):
    request: BaselineExecRequest
    sandbox: BaselineSandboxHandle
    creation_dispatched: bool
    expected_labels: tuple[tuple[str, str], ...] = Field(min_length=11, max_length=11)

    @model_validator(mode="after")
    def exact_request(self) -> Self:
        if self.expected_labels != baseline_labels(self.sandbox, self.request):
            raise ValueError("baseline recovery request binding is inconsistent")
        return self


class BaselineControlInspection(BaselineModel):
    """Owner-neutral projection of existing required effective Docker controls."""

    provider: Literal["docker"] = "docker"
    ready: Literal[True]
    capabilities: BaselineCanonicalSnapshot
    configuration_sha256: Sha256
    image_identity: ImageIdentity
    daemon_identity: Sha256
    effective_network_mode: Literal["none"] = "none"
    non_root: Literal[True]
    read_only_root: Literal[True]
    no_new_privileges: Literal[True]
    capabilities_dropped: Literal[True]
    resource_limits_enforced: Literal[True]
    exact_mounts: Literal[True]
    inspected_at: datetime

    _utc = field_validator("inspected_at")(require_utc)

    @model_validator(mode="after")
    def isolated_capabilities(self) -> Self:
        caps = snapshot_model(self.capabilities, "capabilities-v1", SandboxCapabilities)
        if caps.provider != "docker" or not caps.isolation_enforced or not caps.supports_recovery:
            raise ValueError("baseline effective controls require isolated Docker capabilities")
        return self


class BaselineSandboxInspection(BaselineModel):
    owner: BaselineResourceOwner
    sandbox_id: BaselineSandboxId
    execution_id: BaselineExecutionId
    native_resource_id: NativeId
    legacy_control_inspection: BaselineCanonicalSnapshot
    mount_policy: Literal["baseline-readonly-v1"] = "baseline-readonly-v1"
    workspace_read_only: Literal[True]
    tmp_scratch_mb: int = Field(ge=16, le=120)
    cache_scratch_mb: int = Field(ge=16, le=120)
    shm_scratch_mb: int = Field(ge=16, le=64)
    mount_inspection_sha256: Sha256

    @model_validator(mode="after")
    def physical_controls(self) -> Self:
        snapshot_model(
            self.legacy_control_inspection, "sandbox-inspection-v1", BaselineControlInspection
        )
        if (
            self.tmp_scratch_mb + self.cache_scratch_mb + self.shm_scratch_mb > 256
            or self.legacy_control_inspection.schema_tag != "sandbox-inspection-v1"
        ):
            raise ValueError("baseline physical inspection exceeds scratch bounds")
        return self


class BaselineExecutionMetadata(BaselineModel):
    handle: BaselineExecutionHandle
    inspection: BaselineSandboxInspection
    request_sha256: Sha256
    sandbox_spec_sha256: Sha256
    launch_sha256: Sha256

    @model_validator(mode="after")
    def identities(self) -> Self:
        if (
            self.handle.owner != self.inspection.owner
            or self.handle.execution_id != self.inspection.execution_id
            or self.handle.sandbox_id != self.inspection.sandbox_id
            or self.handle.native_resource_id != self.inspection.native_resource_id
        ):
            raise ValueError("baseline execution metadata crosses owners")
        return self


class BaselineExecResult(BaselineModel):
    metadata: BaselineExecutionMetadata
    started_at: datetime
    completed_at: datetime
    exit_code: int | None = Field(ge=0, le=255)
    timed_out: bool
    cancelled: bool
    output_truncated: bool
    stdout: bytes = Field(max_length=64_000, exclude=True)
    stderr: bytes = Field(max_length=64_000, exclude=True)

    _utc = field_validator("started_at", "completed_at")(require_utc)

    @model_validator(mode="after")
    def volatile_bounds(self) -> Self:
        if len(self.stdout) + len(self.stderr) > 64_000 or self.completed_at < self.started_at:
            raise ValueError("baseline transport result exceeds capture bounds")
        return self


class BaselineWorkspacePayload(BaselineModel):
    kind: Literal["workspace"] = "workspace"
    workspace: BaselineWorkspace


class BaselineSandboxPayload(BaselineModel):
    kind: Literal["sandbox"] = "sandbox"
    sandbox_id: BaselineSandboxId
    spec: BaselineSandboxSpec
    handle: BaselineSandboxHandle | None = None

    @model_validator(mode="after")
    def handle_binding(self) -> Self:
        spec = reconstruct_sandbox(self.spec.sandbox)
        if self.handle is not None and (
            self.handle.owner != self.spec.owner
            or self.handle.sandbox_id != self.sandbox_id
            or self.handle.workspace_id != self.spec.workspace.workspace_id
            or self.handle.workspace_host_path != self.spec.workspace.path
            or self.handle.sandbox_spec_sha256 != self.spec.sandbox.sha256
            or self.handle.sandbox_policy_sha256 != sandbox_policy(self.spec.sandbox).sha256
            or self.handle.configuration_sha256
            != sha256_bytes(canonical(spec.configuration.model_dump(mode="json")))
            or self.handle.image_identity != spec.image_identity
            or self.handle.daemon_identity != spec.daemon_identity
            or self.handle.approved_source_sha256 != self.spec.workspace.approved_source_sha256
            or self.handle.materialized_source_sha256
            != self.spec.workspace.materialized_source_sha256
        ):
            raise ValueError("baseline sandbox activation changes its reservation")
        return self


class BaselineCommandPayload(BaselineModel):
    kind: Literal["execution"] = "execution"
    request: BaselineExecRequest
    sandbox: BaselineSandboxHandle
    creation_dispatched: bool = False
    handle: BaselineExecutionHandle | None = None

    @model_validator(mode="after")
    def native_binding(self) -> Self:
        labels = baseline_labels(self.sandbox, self.request)
        if self.handle is not None and (
            not self.creation_dispatched
            or self.handle.owner != self.request.owner
            or self.handle.claim_id != self.request.claim_id
            or self.handle.execution_id != self.request.execution_id
            or self.handle.sandbox_id != self.sandbox.sandbox_id
            or self.handle.labels != labels
        ):
            raise ValueError("baseline native activation changes its dispatch binding")
        return self


class BaselineResourceLease(BaselineModel):
    lease_id: BaselineLeaseId
    owner: BaselineResourceOwner
    revision: int = Field(ge=0)
    status: Literal["creating", "active", "released", "failed"]
    payload: Annotated[
        BaselineWorkspacePayload | BaselineSandboxPayload | BaselineCommandPayload,
        Field(discriminator="kind"),
    ]
    created_at: datetime
    updated_at: datetime
    receipt_sha256: Sha256 | None = None

    _utc = field_validator("created_at", "updated_at")(require_utc)

    @model_validator(mode="after")
    def lease_binding(self) -> Self:
        payload = self.payload
        owner = (
            payload.workspace.owner
            if isinstance(payload, BaselineWorkspacePayload)
            else payload.spec.owner
            if isinstance(payload, BaselineSandboxPayload)
            else payload.request.owner
        )
        if owner != self.owner or self.updated_at < self.created_at:
            raise ValueError("baseline lease owner/chronology mismatch")
        if (self.status in {"released", "failed"}) != (self.receipt_sha256 is not None):
            raise ValueError("baseline terminal lease requires an exact cleanup receipt")
        return self

    @property
    def kind(self) -> Literal["workspace", "sandbox", "execution"]:
        return self.payload.kind


class BaselineOwnerClaim(BaselineModel):
    owner: BaselineResourceOwner
    claim_id: BaselineClaimId
    authorization_id: BaselineAuthorizationId
    controller_pid: int = Field(ge=1, le=2**31 - 1)
    installation_id: InstallationId
    claimed_at: datetime

    _utc = field_validator("claimed_at")(require_utc)


class BaselineDispatchClaim(BaselineModel):
    owner: BaselineResourceOwner
    owner_claim: BaselineOwnerClaim
    request: BaselineExecRequest
    lease_id: BaselineLeaseId
    sandbox_spec_sha256: Sha256
    resource_snapshot_sha256: Sha256
    claimed_at: datetime

    _utc = field_validator("claimed_at")(require_utc)

    @model_validator(mode="after")
    def claim_binding(self) -> Self:
        if (
            self.owner != self.owner_claim.owner
            or self.owner != self.request.owner
            or self.owner_claim.claim_id != self.request.claim_id
        ):
            raise ValueError("baseline dispatch crosses owners")
        return self


class BaselineCleanupReceipt(BaselineModel):
    owner: BaselineResourceOwner
    lease_id: BaselineLeaseId
    lease_sha256: Sha256
    cleanup_scope_sha256: Sha256
    kind: Literal["workspace", "sandbox", "execution"]
    complete: bool
    result: BaselineCanonicalSnapshot | None
    completed_at: datetime

    _utc = field_validator("completed_at")(require_utc)

    @model_validator(mode="after")
    def neutral_result(self) -> Self:
        if self.kind == "workspace":
            if self.result is not None:
                raise ValueError("worktree cleanup does not manufacture a Docker receipt")
        else:
            if self.result is None:
                raise ValueError("Docker cleanup needs a validated bounded result")
            result = snapshot_model(self.result, "cleanup-v1", SandboxCleanupResult)
            if (
                result.provider != "docker"
                or result.complete != self.complete
                or result.completed_at != self.completed_at
            ):
                raise ValueError("baseline cleanup outcome does not match its result")
        return self


class BaselineResourceSnapshot(BaselineModel):
    execution: BaselineExecution
    claim: BaselineOwnerClaim
    dispatch: BaselineDispatchClaim | None
    leases: tuple[BaselineResourceLease, ...] = Field(max_length=3)

    @model_validator(mode="after")
    def whole_set(self) -> Self:
        if (
            self.execution.baseline_id != self.claim.owner.baseline_id
            or self.execution.project_id != self.claim.owner.project_id
            or self.execution.review_sha256 != self.claim.owner.review_sha256
            or self.execution.owner_claim_id != self.claim.claim_id
            or any(lease.owner != self.claim.owner for lease in self.leases)
            or len({lease.kind for lease in self.leases}) != len(self.leases)
            or tuple(lease.lease_id for lease in self.leases)
            != tuple(sorted(lease.lease_id for lease in self.leases))
            or (self.dispatch is not None and self.dispatch.owner_claim != self.claim)
        ):
            raise ValueError("baseline full resource snapshot is inconsistent")
        return self


class BaselineCleanupClaim(BaselineModel):
    owner: BaselineResourceOwner
    claim_id: BaselineClaimId
    snapshot: BaselineResourceSnapshot
    scope_sha256: Sha256
    reason: Literal["owner_drain", "stopped_owner"]
    created_at: datetime

    _utc = field_validator("created_at")(require_utc)

    @model_validator(mode="after")
    def fixed_scope(self) -> Self:
        if self.owner != self.snapshot.claim.owner or self.scope_sha256 != self.snapshot.digest:
            raise ValueError("baseline cleanup claim does not bind the whole original snapshot")
        return self


class BaselineStoppedOwnerReview(BaselineModel):
    owner: BaselineResourceOwner
    owner_claim_sha256: Sha256
    snapshot_sha256: Sha256
    controller_pid: int = Field(ge=1, le=2**31 - 1)
    installation_id: InstallationId
    state: Literal["absent"]
    checked_at: datetime

    _utc = field_validator("checked_at")(require_utc)


class BaselineCommandScope(BaselineModel):
    review: BaselineReview
    claim: BaselineOwnerClaim | None
    approved: bool

    @model_validator(mode="after")
    def no_forged_principals(self) -> Self:
        if self.claim is not None and (
            self.claim.owner.baseline_id != self.review.baseline_id
            or self.claim.owner.review_sha256 != self.review.digest
            or self.claim.owner.project_id != self.review.project_id
        ):
            raise ValueError("baseline permission scope crosses reviews")
        return self


class BaselineShow(BaselineModel):
    review: BaselineReview
    execution: BaselineExecution
    report: BaselineReport | None
    recovery_scope_sha256: Sha256 | None
