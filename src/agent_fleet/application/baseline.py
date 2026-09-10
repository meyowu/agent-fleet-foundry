"""Explicit user-reviewed one-command baselines; no model or Workflow construction."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from agent_fleet.application.gateway import ToolGateway
from agent_fleet.application.permission_policy import (
    PermissionPolicyService,
    PolicyPermissionBroker,
)
from agent_fleet.application.resources import ResourceService
from agent_fleet.application.sandboxes import (
    SandboxRegistry,
    configuration_from_request,
    requirements_for_configuration,
)
from agent_fleet.domain.baseline import (
    BaselineAuthorization,
    BaselineCanonicalSnapshot,
    BaselineObservationRef,
    BaselineReport,
    BaselineReview,
    BaselineSandboxPolicy,
    baseline_id,
    canonical,
    freeze_command,
    freeze_sandbox,
    freeze_snapshot,
    reconstruct_command,
    snapshot_model,
)
from agent_fleet.domain.baseline_resources import (
    BaselineCleanupClaim,
    BaselineCommandScope,
    BaselineOwnerClaim,
    BaselineSandboxSpec,
    BaselineShow,
    BaselineStoppedOwnerReview,
)
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.ids import IdPrefix
from agent_fleet.domain.models import (
    CommandSpec,
    PermissionOutcome,
    Project,
    SandboxCapabilities,
    SandboxConfiguration,
    SandboxRequirements,
    SandboxSpec,
)
from agent_fleet.domain.security import Redactor, canonical_json_hash, path_is_within
from agent_fleet.domain.trust import UserTrustPolicy
from agent_fleet.ports.baseline import BaselineSessionAdmission, BaselineStore
from agent_fleet.ports.baseline_resources import BaselineAdmissionGuard, BaselineRepositoryPort
from agent_fleet.ports.clock import Clock
from agent_fleet.ports.config import ConfigurationPort
from agent_fleet.ports.id_generator import IdGenerator
from agent_fleet.ports.organization_filesystem import (
    OrganizationFileSystem,
    OrganizationPublicationSession,
)
from agent_fleet.ports.repository import RepositoryPort
from agent_fleet.ports.state_store import StateStore
from agent_fleet.ports.trust_store import TrustReadGuard, TrustStore


def baseline_error(code: ErrorCode = ErrorCode.RECOVERY_REQUIRED) -> FleetError:
    return FleetError(
        code,
        "The exact reviewed baseline operation cannot proceed.",
        "Inspect its review and retained evidence; never replay an uncertain command.",
    )


def bounded_configuration(configuration: SandboxConfiguration) -> SandboxConfiguration:
    if configuration.provider != "docker":
        raise baseline_error(ErrorCode.SANDBOX_CAPABILITY_MISSING)
    data = configuration.model_dump(mode="json")
    data.update(
        cpu_limit=min(configuration.cpu_limit, 1.0),
        memory_mb=min(configuration.memory_mb, 512),
        pids_limit=min(configuration.pids_limit, 64),
        shm_mb=min(configuration.shm_mb, 64),
    )
    data["tmpfs_mb"] = min(configuration.tmpfs_mb, (256 - int(data["shm_mb"])) // 2)
    return SandboxConfiguration.model_validate_json(canonical(data))


@dataclass(frozen=True)
class _AdmissionGuard:
    service: BaselineAdmissionService
    review: BaselineReview
    publication: OrganizationPublicationSession
    trust: TrustReadGuard

    def assert_current(self) -> None:
        self.trust.assert_current()
        self.service._assert_current(self.review, self.publication, self.trust)


class BaselineAdmissionService:
    def __init__(
        self,
        *,
        state: StateStore,
        state_root: Path,
        config: ConfigurationPort,
        repository: RepositoryPort,
        baseline_repository: BaselineRepositoryPort,
        organization_files: OrganizationFileSystem,
        trust: TrustStore,
        permissions: PermissionPolicyService,
        sandboxes: SandboxRegistry,
        clock: Clock,
        ids: IdGenerator,
        redactor: Redactor,
        installation_id: str,
    ) -> None:
        self.state = state
        self.state_root = state_root
        self.config = config
        self.repository = repository
        self.baseline_repository = baseline_repository
        self.organization_files = organization_files
        self.trust = trust
        self.permissions = permissions
        self.sandboxes = sandboxes
        self.clock = clock
        self.ids = ids
        self.redactor = redactor
        self.installation_id = installation_id

    def _project(self, path: Path) -> Project:
        if self.redactor.contains_secret(str(path)):
            raise baseline_error(ErrorCode.CONFIG_INVALID)
        project = self.permissions.project_at(path)
        root = Path(project.canonical_root)
        if path_is_within(self.state_root, root) or path_is_within(root, self.state_root):
            raise baseline_error(ErrorCode.PATH_OUTSIDE_SCOPE)
        return Project.model_validate_json(project.model_dump_json())

    def _source(self, project: Project) -> tuple[str, str, str]:
        boundary = self.repository.inspect_organization_boundary(Path(project.canonical_root))
        info = boundary.repository
        if (
            info.dirty_paths
            or info.status_porcelain
            or info.identity_hash != project.identity_hash
            or info.root != project.canonical_root
        ):
            raise baseline_error(ErrorCode.PROJECT_DIRTY)
        manifest = self.baseline_repository.baseline_source_manifest(
            Path(info.root), info.head_revision
        )
        return (
            info.head_revision,
            canonical_json_hash(boundary.model_dump(mode="json")),
            manifest.digest,
        )

    def _configuration(
        self, publication: OrganizationPublicationSession, command_id: str
    ) -> tuple[str, BaselineCanonicalSnapshot, SandboxConfiguration]:
        tree = publication.capture_target()
        if self.redactor.contains_secret_data(tree.model_dump(mode="json")):
            raise baseline_error(ErrorCode.CONFIG_INVALID)
        spec, snapshot = self.config.snapshot_from_files(
            {item.path: item.content for item in tree.files}
        )
        commands = self.config.verification_profile(spec, snapshot).commands
        if command_id not in commands:
            raise baseline_error(ErrorCode.COMMAND_NOT_REVIEWED)
        raw = commands[command_id]
        command = freeze_command(
            CommandSpec(
                command_id=command_id,
                executable=raw.executable,
                argv=tuple(raw.argv),
                logical_cwd=raw.cwd,
                timeout_seconds=min(raw.timeout_seconds, 180),
            )
            .model_dump_json()
            .encode()
        )
        config = bounded_configuration(configuration_from_request(spec.spec.sandbox))
        return self.config.snapshot_hash(snapshot), command, config

    async def plan(self, path: Path, command_id: str) -> BaselineReview:
        project = self._project(path)
        with (
            self.organization_files.session(
                project, self.ids.new(IdPrefix.ORGANIZATION_OPERATION)
            ) as publication,
            self.trust.read_guard() as trust,
        ):
            policy = UserTrustPolicy.model_validate_json(trust.canonical_policy_utf8)
            if "." not in self.permissions.settings(project, policy).allowed_paths:
                raise baseline_error(ErrorCode.COMMAND_DENIED)
            config_hash, command, configuration = self._configuration(publication, command_id)
            requirements = requirements_for_configuration(configuration)
            self.sandboxes.require_baseline(configuration, requirements)
            revision, repository_state, source = self._source(project)
            policy_snapshot: BaselineCanonicalSnapshot | None = None
            capabilities: BaselineCanonicalSnapshot | None = None
            reason = "ready"
            try:
                preflight = await self.sandboxes.preflight(configuration, requirements)
                if (
                    preflight.image_identity is None
                    or preflight.daemon_identity is None
                    or preflight.recovery_scope_id != self.installation_id
                ):
                    raise baseline_error(ErrorCode.SANDBOX_UNAVAILABLE)
                sandbox = BaselineSandboxPolicy(
                    project_id=project.project_id,
                    configuration=freeze_snapshot(
                        "configuration-v1", configuration.model_dump(mode="json")
                    ),
                    requirements=freeze_snapshot(
                        "requirements-v1", requirements.model_dump(mode="json")
                    ),
                    timeout_seconds=reconstruct_command(command).timeout_seconds,
                    image_identity=preflight.image_identity,
                    daemon_identity=preflight.daemon_identity,
                )
                policy_snapshot = freeze_snapshot(
                    "sandbox-policy-v1", sandbox.model_dump(mode="json", by_alias=True)
                )
                capabilities = freeze_snapshot(
                    "capabilities-v1", preflight.capabilities.model_dump(mode="json")
                )
            except FleetError as error:
                if error.code is ErrorCode.SANDBOX_IMAGE_UNAVAILABLE:
                    reason = "image_unavailable"
                elif error.code in {
                    ErrorCode.SANDBOX_UNAVAILABLE,
                    ErrorCode.SANDBOX_REMOTE_DAEMON_DENIED,
                }:
                    reason = "sandbox_unavailable"
                else:
                    raise
            now = self.clock.now()
            review = BaselineReview.model_validate_json(
                canonical(
                    {
                        "schema_version": 1,
                        "review_id": baseline_id("breview"),
                        "baseline_id": baseline_id("baseline"),
                        "project_id": project.project_id,
                        "project_sha256": canonical_json_hash(project.model_dump(mode="json")),
                        "repository_identity_sha256": project.identity_hash,
                        "repository_root": project.canonical_root,
                        "base_revision": revision,
                        "repository_state_sha256": repository_state,
                        "approved_source_sha256": source,
                        "configuration_sha256": config_hash,
                        "trust_policy_sha256": trust.policy_sha256,
                        "trust_revision": policy.revision,
                        "command": command.model_dump(mode="json", by_alias=True),
                        "sandbox_policy": policy_snapshot.model_dump(mode="json", by_alias=True)
                        if policy_snapshot
                        else None,
                        "capabilities": capabilities.model_dump(mode="json", by_alias=True)
                        if capabilities
                        else None,
                        "installation_id": self.installation_id,
                        "status": "ready" if reason == "ready" else "not_ready",
                        "reason": reason,
                        "created_at": now.isoformat(),
                        "expires_at": (now + timedelta(minutes=5)).isoformat(),
                    }
                )
            )
            self._assert_current(review, publication, trust)
            if capabilities is not None:
                decision = PolicyPermissionBroker(self.permissions).evaluate_baseline(
                    BaselineCommandScope(review=review, claim=None, approved=False),
                    snapshot_model(capabilities, "capabilities-v1", SandboxCapabilities),
                )
                if decision.outcome is PermissionOutcome.DENY:
                    raise baseline_error(ErrorCode.COMMAND_DENIED)
            return review

    def _assert_current(
        self,
        review: BaselineReview,
        publication: OrganizationPublicationSession,
        trust: TrustReadGuard,
    ) -> None:
        trust.assert_current()
        project = self._project(Path(review.repository_root))
        if (
            canonical_json_hash(project.model_dump(mode="json")) != review.project_sha256
            or trust.policy_sha256 != review.trust_policy_sha256
            or review.installation_id != self.installation_id
        ):
            raise baseline_error()
        revision, repository_state, source = self._source(project)
        config_hash, command, configuration = self._configuration(
            publication, reconstruct_command(review.command).command_id
        )
        # A previously ready review does not grant a missing adapter capability.
        # This local lookup must precede consumption/ownership and allocations,
        # not merely the later sandbox creation call.
        self.sandboxes.require_baseline(
            configuration, requirements_for_configuration(configuration)
        )
        if (revision, repository_state, source, config_hash, command) != (
            review.base_revision,
            review.repository_state_sha256,
            review.approved_source_sha256,
            review.configuration_sha256,
            review.command,
        ):
            raise baseline_error()
        if review.sandbox_policy is not None:
            policy = snapshot_model(
                review.sandbox_policy, "sandbox-policy-v1", BaselineSandboxPolicy
            )
            if (
                freeze_snapshot("configuration-v1", configuration.model_dump(mode="json"))
                != policy.configuration
            ):
                raise baseline_error()
        trust.assert_current()

    @contextmanager
    def guard(self, review: BaselineReview) -> Iterator[BaselineAdmissionGuard]:
        review = BaselineReview.from_canonical(review.canonical_bytes())
        project = self._project(Path(review.repository_root))
        with (
            self.organization_files.session(
                project, self.ids.new(IdPrefix.ORGANIZATION_OPERATION)
            ) as publication,
            self.trust.read_guard(expected_sha256=review.trust_policy_sha256) as trust,
        ):
            guard = _AdmissionGuard(self, review, publication, trust)
            guard.assert_current()
            yield guard
            # Command side effects may dirty the source only in a failed boundary;
            # final source drift is reported, not hidden by an exit-time exception.
            trust.assert_current()


class BaselineService:
    def __init__(
        self,
        admission: BaselineAdmissionService,
        store: BaselineStore,
        resources: ResourceService,
        gateway: ToolGateway,
        clock: Clock,
    ) -> None:
        self.admission = admission
        self.store = store
        self.resources = resources
        self.gateway = gateway
        self.clock = clock

    async def plan(self, path: Path, command_id: str) -> BaselineShow:
        review = await self.admission.plan(path, command_id)
        # Recheck under the publication/trust guard through the durable review write.
        with self.admission.guard(review):
            self.store.create_review(review)
        return self.store.show(review.review_id)

    def show(self, identity: str) -> BaselineShow:
        return self.store.show(identity)

    def revoke(self, review_id: str) -> BaselineShow:
        self.store.revoke(review_id)
        return self.store.show(review_id)

    def authorize(
        self,
        review_id: str,
        *,
        review_sha256: str,
        session: BaselineSessionAdmission | None = None,
    ) -> BaselineAuthorization:
        view = self.store.show(review_id)
        if view.review.digest != review_sha256:
            raise baseline_error(ErrorCode.APPROVAL_INVALID)
        with self.admission.guard(view.review):
            return self.store.authorize(review_id, review_sha256, session=session)

    async def run_authorized(
        self,
        review_id: str,
        *,
        review_sha256: str,
        authorization_id: str,
        session: BaselineSessionAdmission | None = None,
    ) -> BaselineShow:
        view = self.store.show(review_id)
        if (
            not authorization_id
            or view.review.digest != review_sha256
            or view.execution.owner_claim_id is not None
        ):
            raise baseline_error(ErrorCode.APPROVAL_INVALID)
        return await self._run(view, authorization_id=authorization_id, session=session)

    async def run(
        self, review_id: str, *, allow_once: bool, review_sha256: str | None
    ) -> BaselineShow:
        view = self.store.show(review_id)
        if not allow_once or review_sha256 is None:
            raise baseline_error(ErrorCode.APPROVAL_REQUIRED)
        if review_sha256 != view.review.digest:
            raise baseline_error(ErrorCode.APPROVAL_INVALID)
        if view.execution.owner_claim_id is not None:
            return view  # A retained spent attempt is never a new dispatch.
        return await self._run(view)

    async def _run(
        self,
        view: BaselineShow,
        *,
        authorization_id: str | None = None,
        session: BaselineSessionAdmission | None = None,
    ) -> BaselineShow:
        review_id, review_sha256 = view.review.review_id, view.review.digest
        if view.review.status != "ready":
            raise baseline_error(ErrorCode.SANDBOX_UNAVAILABLE)
        claim: BaselineOwnerClaim | None = None
        interruption: BaseException | None = None
        controller_error = False
        try:
            async with asyncio.timeout(view.review.max_attempt_seconds):
                with self.admission.guard(view.review):
                    if authorization_id is None:
                        authorization_id = self.store.authorize(
                            review_id, review_sha256
                        ).authorization_id
                    claim = self.store.claim_baseline(
                        review_id,
                        review_sha256,
                        authorization_id,
                        view.execution.revision,
                        session=session,
                    )
                    workspace, _ = self.resources.create_baseline_workspace(claim)
                    if view.review.sandbox_policy is None:
                        raise baseline_error()
                    policy = snapshot_model(
                        view.review.sandbox_policy, "sandbox-policy-v1", BaselineSandboxPolicy
                    )
                    config = snapshot_model(
                        policy.configuration, "configuration-v1", SandboxConfiguration
                    )
                    requirements = snapshot_model(
                        policy.requirements, "requirements-v1", SandboxRequirements
                    )
                    full = freeze_sandbox(
                        SandboxSpec(
                            workspace_host_path=workspace.path,
                            project_id=claim.owner.project_id,
                            configuration=config,
                            requirements=requirements,
                            timeout_seconds=policy.timeout_seconds,
                            image_identity=policy.image_identity,
                            daemon_identity=policy.daemon_identity,
                        )
                        .model_dump_json()
                        .encode()
                    )
                    spec = BaselineSandboxSpec(owner=claim.owner, workspace=workspace, sandbox=full)
                    sandbox = await self.resources.create_baseline_sandbox(claim, spec)
                # Gateway obtains its own fresh guard after allocation. Never nest
                # non-reentrant publication/trust guards or treat a prior read as consent.
                await self.gateway.execute_baseline(
                    claim=claim, workspace=workspace, sandbox_handle=sandbox
                )
        except BaseException as error:
            if claim is None:
                raise
            controller_error = True
            if not isinstance(error, Exception):
                interruption = error
            # An already-spent owner always reaches exact cleanup and an explicit
            # inconclusive report. No exception text enters persisted evidence.
        assert claim is not None
        cleanup = self.store.begin_baseline_cleanup(
            claim, self.store.baseline_resource_snapshot(claim.owner.baseline_id)
        )
        try:
            await self.resources.cleanup_baseline(cleanup)
        except BaseException as error:
            controller_error = True
            if not isinstance(error, Exception):
                interruption = interruption or error
        self._publish(cleanup, controller_error=controller_error)
        if interruption is not None:
            raise interruption
        return self.store.show(claim.owner.baseline_id)

    def _publish(self, cleanup: BaselineCleanupClaim, *, controller_error: bool = False) -> None:
        snapshot = self.store.validate_cleanup(cleanup)
        view = self.store.show(cleanup.owner.baseline_id)
        review = view.review
        controller_error = controller_error or (
            view.report is not None and "controller_error" in view.report.proof_gaps
        )
        observation = self.store.observation(cleanup.owner.baseline_id)
        complete = all(lease.status == "released" for lease in snapshot.leases)
        conclusive = observation is not None and observation.conclusive and not controller_error
        gaps: list[str] = []
        if observation is None:
            gaps.append("missing_result")
        elif not observation.conclusive:
            if observation.post_source_sha256 != observation.approved_source_sha256:
                gaps.append("source_drift")
            else:
                gaps.append("output_incomplete")
        if not complete:
            gaps.append("cleanup_incomplete")
        if controller_error:
            gaps.append("controller_error")
        reference = (
            None
            if observation is None
            else BaselineObservationRef(
                observation_id=f"bobs_{observation.digest}",
                baseline_id=observation.baseline_id,
                execution_id=observation.execution_id,
                record_sha256=observation.digest,
            )
        )
        report = BaselineReport.model_validate_json(
            canonical(
                {
                    "schema_version": 1,
                    "baseline_id": review.baseline_id,
                    "project_id": review.project_id,
                    "review_id": review.review_id,
                    "review_sha256": review.digest,
                    "authorization_id": snapshot.claim.authorization_id,
                    "claim_id": snapshot.claim.claim_id,
                    "command_sha256": review.command.sha256,
                    "approved_source_sha256": review.approved_source_sha256,
                    "observation": reference.model_dump(mode="json") if reference else None,
                    "cleanup_scope_sha256": cleanup.scope_sha256,
                    "cleanup_receipt_sha256s": sorted(
                        lease.receipt_sha256
                        for lease in snapshot.leases
                        if lease.receipt_sha256 is not None
                    ),
                    "cleanup_complete": complete,
                    "status": "observed"
                    if complete and conclusive
                    else "inconclusive"
                    if complete
                    else "recovery_required",
                    "observed_exit_code": observation.exit_code
                    if observation is not None
                    else None,
                    "predecessor_report_sha256": snapshot.execution.current_report_sha256,
                    "completed_at": self.clock.now().isoformat(),
                    "proof_gaps": gaps,
                }
            )
        )
        self.store.publish_baseline_report(
            cleanup, snapshot.execution.revision, report.canonical_bytes()
        )

    async def recover(
        self, identity: str, *, owner_stopped: bool, cleanup_sha256: str | None
    ) -> BaselineShow:
        if not owner_stopped or cleanup_sha256 is None:
            raise baseline_error(ErrorCode.APPROVAL_REQUIRED)
        snapshot = self.store.baseline_resource_snapshot(identity)
        if snapshot.digest != cleanup_sha256:
            raise baseline_error(ErrorCode.APPROVAL_INVALID)
        try:
            os.kill(snapshot.claim.controller_pid, 0)
        except ProcessLookupError:
            stopped = True
        except OSError:
            stopped = False
        else:
            stopped = False
        if not stopped:
            raise baseline_error()
        review = BaselineStoppedOwnerReview(
            owner=snapshot.claim.owner,
            owner_claim_sha256=snapshot.claim.digest,
            snapshot_sha256=snapshot.digest,
            controller_pid=snapshot.claim.controller_pid,
            installation_id=self.admission.installation_id,
            state="absent",
            checked_at=self.clock.now(),
        )
        cleanup = self.store.claim_baseline_cleanup(snapshot, review)
        with suppress(FleetError):
            await self.resources.cleanup_baseline(cleanup)
        self._publish(cleanup)
        return self.store.show(identity)


def baseline_exit_code(view: BaselineShow) -> int:
    if view.report is None:
        return 0 if view.execution.status == "planned" and view.review.status == "ready" else 3
    if view.report.status != "observed":
        return 3
    return 0 if view.report.observed_exit_code == 0 else 1
