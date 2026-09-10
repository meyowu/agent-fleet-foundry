"""Credential-free immutable fixtures for the separate model-free baseline owner."""

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from agent_fleet.adapters.persistence.baseline import SqliteBaselineStore
from agent_fleet.adapters.persistence.sqlite import SqliteStateStore
from agent_fleet.adapters.system import SystemClock, UuidIdGenerator
from agent_fleet.domain.baseline import (
    BaselineCommandObservation,
    BaselineReview,
    baseline_id,
    canonical,
    freeze_command,
    freeze_sandbox,
    freeze_snapshot,
    sandbox_policy,
)
from agent_fleet.domain.baseline_resources import (
    BaselineCommandPayload,
    BaselineControlInspection,
    BaselineExecRequest,
    BaselineExecutionHandle,
    BaselineOwnerClaim,
    BaselineResourceLease,
    BaselineSandboxHandle,
    BaselineSandboxInspection,
    BaselineSandboxPayload,
    BaselineSandboxSpec,
    BaselineWorkspace,
    BaselineWorkspacePayload,
    baseline_labels,
)
from agent_fleet.domain.models import (
    CommandSpec,
    Project,
    SandboxCapabilities,
    SandboxConfiguration,
    SandboxRequirements,
    SandboxSecurityLevel,
    SandboxSpec,
)
from agent_fleet.domain.security import Redactor, canonical_json_hash, sha256_bytes


@dataclass
class BaselineFixture:
    state: SqliteStateStore
    store: SqliteBaselineStore
    project: Project
    review: BaselineReview
    spec: BaselineSandboxSpec

    def dispatched_observation(self, claim: BaselineOwnerClaim) -> BaselineCommandObservation:
        """Persist a synthetic transport's exact lease facts, not physical Docker evidence."""
        self.workspace(claim)
        sandbox = self.sandbox(claim)
        request = BaselineExecRequest(
            owner=claim.owner,
            claim_id=claim.claim_id,
            execution_id=baseline_id("bexec"),
            workspace_id=self.spec.workspace.workspace_id,
            command=self.review.command,
        )
        now = self.state.clock.now()
        lease = BaselineResourceLease(
            lease_id=baseline_id("blease"),
            owner=claim.owner,
            revision=0,
            status="creating",
            payload=BaselineCommandPayload(request=request, sandbox=sandbox),
            created_at=now,
            updated_at=now,
        )
        snapshot = self.store.baseline_resource_snapshot(self.review.baseline_id)
        self.store.claim_baseline_dispatch(claim, snapshot.digest, request, lease)
        self.store.mark_baseline_creation_dispatched(claim, lease.lease_id, 0)
        labels = baseline_labels(sandbox, request)
        native = BaselineExecutionHandle(
            owner=claim.owner,
            claim_id=claim.claim_id,
            execution_id=request.execution_id,
            sandbox_id=sandbox.sandbox_id,
            native_resource_id="7" * 64,
            labels=labels,
            labels_sha256=sha256_bytes(canonical(dict(labels))),
        )
        self.store.activate_baseline_execution(claim, lease.lease_id, 1, native)
        controls = BaselineControlInspection(
            ready=True,
            capabilities=sandbox.capabilities,
            configuration_sha256=sandbox.configuration_sha256,
            image_identity=sandbox.image_identity,
            daemon_identity=sandbox.daemon_identity,
            non_root=True,
            read_only_root=True,
            no_new_privileges=True,
            capabilities_dropped=True,
            resource_limits_enforced=True,
            exact_mounts=True,
            inspected_at=now,
        )
        inspection = BaselineSandboxInspection(
            owner=claim.owner,
            sandbox_id=sandbox.sandbox_id,
            execution_id=request.execution_id,
            native_resource_id=native.native_resource_id,
            legacy_control_inspection=freeze_snapshot(
                "sandbox-inspection-v1", controls.model_dump(mode="json", by_alias=True)
            ),
            workspace_read_only=True,
            tmp_scratch_mb=64,
            cache_scratch_mb=64,
            shm_scratch_mb=64,
            mount_inspection_sha256="8" * 64,
        )
        assert self.review.sandbox_policy is not None
        return BaselineCommandObservation(
            baseline_id=self.review.baseline_id,
            project_id=self.review.project_id,
            review_id=self.review.review_id,
            review_sha256=self.review.digest,
            authorization_id=claim.authorization_id,
            claim_id=claim.claim_id,
            execution_id=request.execution_id,
            workspace_id=request.workspace_id,
            sandbox_id=sandbox.sandbox_id,
            command_sha256=self.review.command.sha256,
            sandbox_policy_sha256=self.review.sandbox_policy.sha256,
            sandbox_spec_sha256=self.spec.sandbox.sha256,
            request_sha256=request.digest,
            approved_source_sha256=self.review.approved_source_sha256,
            materialized_source_sha256=self.review.approved_source_sha256,
            post_source_sha256=self.review.approved_source_sha256,
            native_handle=freeze_snapshot(
                "native-handle-v1", native.model_dump(mode="json", by_alias=True)
            ),
            inspection=freeze_snapshot(
                "sandbox-inspection-v1", inspection.model_dump(mode="json", by_alias=True)
            ),
            started_at=now,
            completed_at=self.state.clock.now(),
            exit_code=0,
            timed_out=False,
            cancelled=False,
            capture_truncated=False,
            redaction_truncated=False,
            decoding_replaced=False,
            stdout="synthetic output\n",
            stderr="",
            stdout_sha256=sha256_bytes(b"synthetic output\n"),
            stderr_sha256=sha256_bytes(b""),
        )

    def claim(self) -> BaselineOwnerClaim:
        authorization = self.store.authorize(self.review.review_id, self.review.digest)
        return self.store.claim_baseline(
            self.review.review_id, self.review.digest, authorization.authorization_id, 0
        )

    def workspace(self, claim: BaselineOwnerClaim) -> BaselineResourceLease:
        raw = self.spec.workspace.model_dump(mode="json", by_alias=True)
        raw["materialized_source_sha256"] = None
        from agent_fleet.domain.baseline import canonical

        workspace = BaselineWorkspace.model_validate_json(canonical(raw))
        now = self.state.clock.now()
        lease = BaselineResourceLease(
            lease_id=baseline_id("blease"),
            owner=claim.owner,
            revision=0,
            status="creating",
            payload=BaselineWorkspacePayload(workspace=workspace),
            created_at=now,
            updated_at=now,
        )
        self.store.reserve_baseline_lease(claim, lease)
        return self.store.activate_baseline_lease(claim, lease.lease_id, 0, self.spec.workspace)

    def sandbox(self, claim: BaselineOwnerClaim) -> BaselineSandboxHandle:
        sandbox_id = baseline_id("bsandbox")
        now = self.state.clock.now()
        lease = BaselineResourceLease(
            lease_id=baseline_id("blease"),
            owner=claim.owner,
            revision=0,
            status="creating",
            payload=BaselineSandboxPayload(sandbox_id=sandbox_id, spec=self.spec),
            created_at=now,
            updated_at=now,
        )
        self.store.reserve_baseline_lease(claim, lease)
        assert self.review.capabilities is not None and self.review.sandbox_policy is not None
        from agent_fleet.domain.baseline import reconstruct_sandbox

        configuration = reconstruct_sandbox(self.spec.sandbox).configuration
        handle = BaselineSandboxHandle(
            owner=claim.owner,
            sandbox_id=sandbox_id,
            workspace_id=self.spec.workspace.workspace_id,
            workspace_host_path=self.spec.workspace.path,
            capabilities=self.review.capabilities,
            configuration_sha256=canonical_json_hash(configuration.model_dump(mode="json")),
            sandbox_policy_sha256=self.review.sandbox_policy.sha256,
            sandbox_spec_sha256=self.spec.sandbox.sha256,
            approved_source_sha256=self.review.approved_source_sha256,
            materialized_source_sha256=self.review.approved_source_sha256,
            image_identity="sha256:" + "a" * 64,
            daemon_identity="b" * 64,
            recovery_scope_id=self.review.installation_id,
        )
        self.store.activate_baseline_lease(claim, lease.lease_id, 0, handle)
        return handle


def baseline_fixture(tmp_path: Path) -> BaselineFixture:
    clock = SystemClock()
    state = SqliteStateStore(tmp_path / "state.db", clock, UuidIdGenerator(), Redactor())
    assert state.migrate() == 13
    now = clock.now()
    project = Project(
        project_id="prj_" + "1" * 32,
        canonical_root=str(tmp_path / "project"),
        identity_hash="1" * 64,
        created_at=now,
        updated_at=now,
    )
    state.save_project(project)
    identity = baseline_id("baseline")
    workspace_id = baseline_id("bws")
    workspace_path = str(tmp_path / "baseline-workspaces" / identity / workspace_id)
    configuration = SandboxConfiguration(
        provider="docker", image="test:prepared", pids_limit=64, tmpfs_mb=64
    )
    requirements = SandboxRequirements(
        isolation_required=True,
        code_execution_required=True,
        resource_limits_required=True,
        non_root_required=True,
        read_only_root_required=True,
        no_new_privileges_required=True,
        capability_drop_required=True,
    )
    sandbox = freeze_sandbox(
        SandboxSpec(
            workspace_host_path=workspace_path,
            project_id=project.project_id,
            configuration=configuration,
            requirements=requirements,
            timeout_seconds=10,
            image_identity="sha256:" + "a" * 64,
            daemon_identity="b" * 64,
        )
        .model_dump_json()
        .encode()
    )
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
    review = BaselineReview(
        review_id=baseline_id("breview"),
        baseline_id=identity,
        project_id=project.project_id,
        project_sha256=canonical_json_hash(project.model_dump(mode="json")),
        repository_identity_sha256=project.identity_hash,
        repository_root=project.canonical_root,
        base_revision="a" * 40,
        repository_state_sha256="2" * 64,
        approved_source_sha256="3" * 64,
        configuration_sha256="4" * 64,
        trust_policy_sha256="5" * 64,
        trust_revision=0,
        command=freeze_command(
            CommandSpec(
                command_id="test", executable="python", argv=("-m", "unittest"), timeout_seconds=10
            )
            .model_dump_json()
            .encode()
        ),
        sandbox_policy=sandbox_policy(sandbox),
        capabilities=freeze_snapshot("capabilities-v1", capabilities.model_dump(mode="json")),
        installation_id="6" * 32,
        status="ready",
        reason="ready",
        created_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    from agent_fleet.domain.baseline_resources import BaselineResourceOwner

    owner = BaselineResourceOwner(
        baseline_id=identity, project_id=project.project_id, review_sha256=review.digest
    )
    workspace = BaselineWorkspace(
        owner=owner,
        workspace_id=workspace_id,
        path=workspace_path,
        base_revision=review.base_revision,
        approved_source_sha256=review.approved_source_sha256,
        materialized_source_sha256=review.approved_source_sha256,
    )
    store = SqliteBaselineStore(state, installation_id=review.installation_id)
    store.create_review(review)
    return BaselineFixture(
        state,
        store,
        project,
        review,
        BaselineSandboxSpec(owner=owner, workspace=workspace, sandbox=sandbox),
    )
