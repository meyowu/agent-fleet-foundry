"""Canary-before-publication repository bootstrap orchestration."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import cast

from pydantic import BaseModel, ValidationError

from agent_fleet.application.artifacts import ArtifactService
from agent_fleet.application.evidence import EvidenceAssembler
from agent_fleet.application.projects import ProjectService
from agent_fleet.application.runtime import RuntimeRegistry
from agent_fleet.application.sandboxes import (
    SandboxRegistry,
    requirements_for_configuration,
)
from agent_fleet.application.workflow import WorkflowEngine
from agent_fleet.domain.bootstrap import (
    ArtifactReference,
    BootstrapPolicyMode,
    BootstrapReport,
)
from agent_fleet.domain.config import ConfigSnapshot
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.evidence import CommandEvidence, EvidenceBundle, EvidenceStrength
from agent_fleet.domain.fleet_plan import FleetPlan, FleetStrategy, validate_fleet_plan
from agent_fleet.domain.ids import IdPrefix
from agent_fleet.domain.models import (
    ArtifactKind,
    ArtifactMetadata,
    CommandSpec,
    FakeScenario,
    RepositoryInfo,
    RunStatus,
    RuntimeCapability,
    RuntimeConfiguration,
    RuntimeCredentialCheck,
    SandboxConfiguration,
    SandboxInspection,
    SandboxPreflight,
    TaskSpec,
    VerifierVerdict,
    WorkflowStage,
    WorkspaceKind,
)
from agent_fleet.domain.offline_canary import BOOTSTRAP_SANDBOX_PROBE_MARKER
from agent_fleet.domain.repository_profile import ProjectKnowledge, RepositoryProfile
from agent_fleet.domain.security import Redactor, canonical_json_hash, path_is_within
from agent_fleet.domain.trust import TrustMode
from agent_fleet.ports.clock import Clock
from agent_fleet.ports.config import ConfigurationPort
from agent_fleet.ports.id_generator import IdGenerator
from agent_fleet.ports.repository import RepositoryPort
from agent_fleet.ports.state_store import StateStore

_BOOTSTRAP_RUNTIME_CAPABILITIES = frozenset(
    {
        RuntimeCapability.STRUCTURED_OUTPUT,
        RuntimeCapability.TOOL_CALLING,
    }
)


@dataclass(frozen=True, slots=True)
class VerifiedBootstrapReport:
    """Internal publication capability minted only after full graph verification."""

    report_artifact_id: str
    report_artifact_sha256: str
    canary_project_id: str
    canary_run_id: str
    canary_task_id: str
    target_identity_hash: str
    target_head_revision: str
    target_status_fingerprint: str
    proposal_sha256: str
    target_runtime_configuration: RuntimeConfiguration
    sandbox_configuration: SandboxConfiguration
    sandbox_image_identity: str
    sandbox_daemon_identity: str
    verified_at: datetime


class BootstrapService:
    """Run a disposable normal workflow before publishing target configuration."""

    def __init__(
        self,
        *,
        state_root: Path,
        state: StateStore,
        projects: ProjectService,
        workflow: WorkflowEngine,
        repository: RepositoryPort,
        artifacts: ArtifactService,
        evidence: EvidenceAssembler,
        config: ConfigurationPort,
        runtimes: RuntimeRegistry,
        sandboxes: SandboxRegistry,
        clock: Clock,
        ids: IdGenerator,
        redactor: Redactor,
    ) -> None:
        self.state_root = state_root
        self.state = state
        self.projects = projects
        self.workflow = workflow
        self.repository = repository
        self.artifacts = artifacts
        self.evidence = evidence
        self.config = config
        self.runtimes = runtimes
        self.sandboxes = sandboxes
        self.clock = clock
        self.ids = ids
        self.redactor = redactor

    async def initialize(
        self,
        root: Path,
        *,
        runtime_name: str = "fake",
        provider_model: str | None = None,
        credential_ref: str | None = None,
        sandbox_name: str = "fake",
        docker_image: str | None = None,
        allow_unsafe_local: bool = False,
        expected_proposal_hash: str | None = None,
        trust_mode: TrustMode | None = None,
        allowed_paths: tuple[str, ...] | None = None,
        expected_trust_revision: int | None = None,
    ) -> dict[str, object]:
        permissions = self.workflow.permission_policy
        if permissions is None:
            raise FleetError(
                ErrorCode.CONFIG_INVALID,
                "Bootstrap requires a user policy service.",
                "Use the complete Fleet composition root.",
            )
        reviewed = permissions.review_initialization(
            root, mode=trust_mode, allowed_paths=allowed_paths
        )
        reviewed_mode = TrustMode(cast(str, reviewed["trust_mode"]))
        reviewed_paths = tuple(cast(list[str], reviewed["allowed_paths"]))
        reviewed_revision = cast(int, reviewed["policy_revision"])
        if expected_trust_revision is not None and reviewed_revision != expected_trust_revision:
            raise FleetError(
                ErrorCode.CONFIG_INVALID,
                "User trust changed after the initialization preview.",
                "Review the new user policy and retry initialization.",
            )
        started_at = self.clock.now()
        target_info = self.repository.inspect(root)
        target_root = Path(target_info.root)
        if path_is_within(target_root, self.state_root) or path_is_within(
            self.state_root, target_root
        ):
            raise FleetError(
                ErrorCode.PATH_OUTSIDE_SCOPE,
                "The Fleet state directory and target repository must be disjoint.",
                "Choose an AGENT_FLEET_HOME that is neither inside nor an ancestor of the "
                "repository, then retry initialization.",
            )
        runtime_configuration = ProjectService._runtime_configuration(
            runtime_name=runtime_name,
            provider_model=provider_model,
            credential_ref=credential_ref,
        )
        sandbox_configuration = ProjectService._sandbox_configuration(
            sandbox_name,
            docker_image=docker_image,
        )
        if sandbox_name == "local-unsafe" and not allow_unsafe_local:
            raise FleetError(
                ErrorCode.UNSAFE_LOCAL_CONFIRMATION_REQUIRED,
                "Local-unsafe initialization requires a separate high-risk confirmation.",
                "Pass --allow-unsafe-local explicitly; --yes is not sufficient.",
            )
        self.runtimes.require(
            runtime_configuration,
            required_capabilities=_BOOTSTRAP_RUNTIME_CAPABILITIES,
            credential_check=RuntimeCredentialCheck.RESOLVE,
        )
        requirements = requirements_for_configuration(sandbox_configuration)
        preflight = await self.sandboxes.preflight(sandbox_configuration, requirements)

        preview = self.projects.preview(
            root,
            runtime_name=runtime_name,
            provider_model=provider_model,
            credential_ref=credential_ref,
            sandbox_name=sandbox_name,
            docker_image=docker_image,
        )
        proposal_hash = self._required_string(preview, "proposal_sha256")
        if expected_proposal_hash is not None and proposal_hash != expected_proposal_hash:
            raise FleetError(
                ErrorCode.CONFIG_INVALID,
                "The Fleet initialization proposal changed after it was reviewed.",
                "Run `fleet init --preview` again, review the new patch, and retry explicitly.",
            )
        if target_info.root != self._required_string(preview, "repository"):
            raise FleetError(
                ErrorCode.BOOTSTRAP_TARGET_DRIFTED,
                "The preview and repository inspection resolved different targets.",
                "Retry from one stable Git repository path.",
            )

        self.state.migrate()
        bootstrap_id = self.ids.new(IdPrefix.CORRELATION)
        canary_root = self.repository.create_bootstrap_canary_fixture(
            self.state_root / "bootstrap" / bootstrap_id / "repository"
        )
        canary_registration = self.projects.register_bootstrap_canary(
            canary_root,
            sandbox_name=sandbox_name,
            docker_image=docker_image,
            sandbox_image_identity=preflight.image_identity,
            sandbox_daemon_identity=preflight.daemon_identity,
            allow_unsafe_local=allow_unsafe_local,
        )
        canary_project_id = self._required_string(canary_registration, "project_id")

        preparation_references = self._persist_target_preparation(
            preview,
            canary_project_id=canary_project_id,
            bootstrap_id=bootstrap_id,
        )
        try:
            run = await self.workflow.start(
                project_path=canary_root,
                goal="Fix the canary behavior",
                runtime_name="fake",
                sandbox_name=sandbox_name,
                fake_scenario=FakeScenario.SUCCESS,
                allow_unsafe_local=allow_unsafe_local,
            )
        except FleetError as error:
            raise FleetError(
                ErrorCode.BOOTSTRAP_CANARY_FAILED,
                "The disposable bootstrap canary did not complete successfully.",
                "Inspect the preserved canary run artifacts, correct the sandbox, and retry.",
                details={
                    "cause_code": error.code.value,
                    **(
                        {"run_id": error.details["run_id"]}
                        if isinstance(error.details.get("run_id"), str)
                        else {}
                    ),
                },
            ) from None
        if run.status is not RunStatus.READY_FOR_REVIEW:
            raise FleetError(
                ErrorCode.BOOTSTRAP_CANARY_FAILED,
                "The disposable bootstrap canary did not reach ready-for-review state.",
                "Inspect the preserved canary run and retry after correcting the failure.",
                details={"run_id": run.run_id, "status": run.status.value},
            )
        outstanding = list(self.state.outstanding_leases(run.run_id))
        if outstanding:
            raise FleetError(
                ErrorCode.SANDBOX_CLEANUP_FAILED,
                "Bootstrap canary resources remain outstanding after workflow completion.",
                "Run Fleet recovery and retry bootstrap only after cleanup succeeds.",
                details={"run_id": run.run_id, "outstanding_leases": len(outstanding)},
            )
        report = self._assemble_report(
            preview=preview,
            target_info=target_info,
            target_runtime_configuration=runtime_configuration,
            sandbox_configuration=sandbox_configuration,
            preflight=preflight,
            run_id=run.run_id,
            canary_project_id=canary_project_id,
            preparation_references=preparation_references,
            started_at=started_at,
        )
        report_artifact = self.artifacts.create_text(
            kind=ArtifactKind.BOOTSTRAP_REPORT,
            project_id=canary_project_id,
            run_id=run.run_id,
            task_id=run.task_id,
            producer="bootstrap-service",
            content=report.model_dump_json(indent=2),
            mime_type="application/json",
            redact=False,
            reject_secret=True,
        )
        persisted_report = self._read_and_validate_report(report_artifact)
        if persisted_report != report:
            raise FleetError(
                ErrorCode.BOOTSTRAP_REPORT_INVALID,
                "The persisted bootstrap report changed during validation.",
                "Preserve the canary artifacts and retry with a healthy state store.",
            )
        if not report.publish_allowed:
            raise FleetError(
                ErrorCode.BOOTSTRAP_CANARY_FAILED,
                "The disposable bootstrap canary produced diagnostics but not publication proof.",
                "Use the verified Docker sandbox and rerun bootstrap; the target was not changed.",
                details={
                    "report_artifact_id": report_artifact.artifact_id,
                    "report_sha256": report_artifact.sha256,
                    "run_id": run.run_id,
                    "policy_mode": report.policy_mode.value,
                    "proof_gaps": report.proof_gaps,
                },
            )
        current_info = self.repository.inspect(Path(target_info.root))
        if (
            current_info.identity_hash != target_info.identity_hash
            or current_info.head_revision != target_info.head_revision
            or current_info.status_fingerprint != target_info.status_fingerprint
        ):
            raise FleetError(
                ErrorCode.BOOTSTRAP_TARGET_DRIFTED,
                "The target repository changed while the bootstrap canary was running.",
                "Review a fresh proposal and rerun bootstrap.",
            )
        refreshed_preview = self.projects.preview(
            Path(target_info.root),
            runtime_name=runtime_name,
            provider_model=provider_model,
            credential_ref=credential_ref,
            sandbox_name=sandbox_name,
            docker_image=docker_image,
        )
        if self._required_string(refreshed_preview, "proposal_sha256") != proposal_hash:
            raise FleetError(
                ErrorCode.BOOTSTRAP_TARGET_DRIFTED,
                "The target initialization proposal changed during bootstrap.",
                "Review the new proposal and rerun the disposable canary.",
            )
        image_identity = persisted_report.sandbox_preflight.image_identity
        daemon_identity = persisted_report.sandbox_preflight.daemon_identity
        if image_identity is None or daemon_identity is None:
            raise FleetError(
                ErrorCode.BOOTSTRAP_REPORT_INVALID,
                "Verified Docker bootstrap report has no immutable image or daemon identity.",
                "Preserve the canary artifacts and rerun bootstrap.",
            )
        verified_report = VerifiedBootstrapReport(
            report_artifact_id=report_artifact.artifact_id,
            report_artifact_sha256=report_artifact.sha256,
            canary_project_id=persisted_report.canary_project_id,
            canary_run_id=persisted_report.canary_run_id,
            canary_task_id=persisted_report.canary_task_id,
            target_identity_hash=persisted_report.target_identity_hash,
            target_head_revision=persisted_report.target_head_revision,
            target_status_fingerprint=persisted_report.target_status_fingerprint,
            proposal_sha256=persisted_report.proposal_sha256,
            target_runtime_configuration=persisted_report.target_runtime_configuration,
            sandbox_configuration=persisted_report.sandbox_configuration,
            sandbox_image_identity=image_identity,
            sandbox_daemon_identity=daemon_identity,
            verified_at=self.clock.now(),
        )
        initialized = self.projects._publish_bootstrap_target(
            Path(target_info.root),
            verified=verified_report,
        )
        settings = permissions.configure(
            Path(target_info.root),
            mode=reviewed_mode,
            allowed_paths=reviewed_paths,
            expected_revision=reviewed_revision,
        )
        initialized.update(
            {
                "bootstrap_report_artifact_id": report_artifact.artifact_id,
                "bootstrap_report_sha256": report_artifact.sha256,
                "bootstrap_canary_project_id": canary_project_id,
                "bootstrap_canary_run_id": run.run_id,
                "bootstrap_canary_status": run.status.value,
                "bootstrap_policy_mode": report.policy_mode.value,
                "bootstrap_publish_allowed": report.publish_allowed,
                "bootstrap_cleanup_complete": report.cleanup_complete,
                "bootstrap_outstanding_lease_count": report.outstanding_lease_count,
                "bootstrap_verified": report.completion_decision.verified_complete,
                "bootstrap_proof_gaps": report.proof_gaps,
                "bootstrap_remaining_risks": report.remaining_risks,
                "sandbox_preflight": preflight.model_dump(mode="json"),
                "user_permission_settings": settings.model_dump(mode="json"),
            }
        )
        return initialized

    def _persist_target_preparation(
        self,
        preview: dict[str, object],
        *,
        canary_project_id: str,
        bootstrap_id: str,
    ) -> dict[str, ArtifactReference]:
        profile = RepositoryProfile.model_validate(preview["repository_profile"])
        knowledge = ProjectKnowledge.model_validate(preview["project_knowledge"])
        profile_artifact = self.artifacts.create_text(
            kind=ArtifactKind.REPOSITORY_PROFILE,
            project_id=canary_project_id,
            content=profile.model_dump_json(indent=2),
            producer="bootstrap-target-profiler",
            mime_type="application/json",
        )
        knowledge_artifact = self.artifacts.create_text(
            kind=ArtifactKind.PROJECT_KNOWLEDGE,
            project_id=canary_project_id,
            content=knowledge.model_dump_json(indent=2),
            producer="bootstrap-target-profiler",
            mime_type="application/json",
        )
        proposed_files_value = preview.get("proposed_files")
        if not isinstance(proposed_files_value, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in proposed_files_value.items()
        ):
            raise RuntimeError("invalid bootstrap proposal files")
        proposed_files = {
            key.removeprefix(".fleet/"): value for key, value in proposed_files_value.items()
        }
        proposal_patch = self._required_string(preview, "proposal_patch")
        proposal_content = (
            json.dumps(
                {"files": proposed_files, "patch": proposal_patch},
                sort_keys=True,
                indent=2,
            )
            + "\n"
        )
        proposal_artifact = self.artifacts.create_text(
            kind=ArtifactKind.FLEET_CONFIG_PROPOSAL,
            project_id=canary_project_id,
            content=proposal_content,
            producer="bootstrap-service",
            mime_type="application/json",
            redact=False,
            reject_secret=True,
        )
        staging = self.state_root / "bootstrap" / bootstrap_id / "target-staging"
        self.config.stage(staging, proposed_files)
        _, snapshot = self.config.load_snapshot(staging / "fleet.yaml")
        snapshot_artifact = self.artifacts.create_text(
            kind=ArtifactKind.CONFIG_SNAPSHOT,
            project_id=canary_project_id,
            content=snapshot.model_dump_json(indent=2),
            producer="bootstrap-service",
            mime_type="application/json",
            redact=False,
            reject_secret=True,
        )
        if snapshot_artifact.sha256 != self.config.snapshot_hash(snapshot):
            raise RuntimeError("bootstrap target configuration snapshot hash changed")
        return {
            "repository_profile": self._reference(profile_artifact),
            "project_knowledge": self._reference(knowledge_artifact),
            "proposal": self._reference(proposal_artifact),
            "config_snapshot": self._reference(snapshot_artifact),
        }

    def _assemble_report(
        self,
        *,
        preview: dict[str, object],
        target_info: RepositoryInfo,
        target_runtime_configuration: RuntimeConfiguration,
        sandbox_configuration: SandboxConfiguration,
        preflight: SandboxPreflight,
        run_id: str,
        canary_project_id: str,
        preparation_references: dict[str, ArtifactReference],
        started_at: datetime,
    ) -> BootstrapReport:
        run = self.state.get_run(run_id)
        if (
            run.task_id is None
            or run.task_spec_artifact_id is None
            or run.fleet_plan_artifact_id is None
            or run.patch_artifact_id is None
            or run.verifier_verdict_artifact_id is None
            or run.evidence_bundle_artifact_id is None
            or run.cleanup_receipt_artifact_id is None
            or run.sandbox_capabilities_snapshot is None
            or run.sandbox_requirements is None
        ):
            raise FleetError(
                ErrorCode.BOOTSTRAP_REPORT_INVALID,
                "The bootstrap canary is missing required authoritative artifacts.",
                "Inspect the canary run and retry after repairing the workflow.",
                details={"run_id": run_id},
            )
        bundle = EvidenceBundle.model_validate_json(
            self.artifacts.read_text(run.evidence_bundle_artifact_id)
        )
        if bundle.completion_decision is None:
            raise FleetError(
                ErrorCode.BOOTSTRAP_REPORT_INVALID,
                "The bootstrap canary evidence has no completion decision.",
                "Inspect the canary evidence graph and retry.",
            )
        command_models = [
            CommandEvidence.model_validate_json(self.artifacts.read_text(artifact_id))
            for artifact_id in run.command_evidence_artifact_ids
        ]
        command_references = [
            self._reference(self.state.get_artifact(artifact_id))
            for artifact_id in run.command_evidence_artifact_ids
        ]
        transcript_references = [
            self._reference(self.state.get_artifact(command.transcript_artifact_id))
            for command in command_models
        ]
        inspection_references = [
            self._reference(self.state.get_artifact(command.sandbox_inspection_artifact_id))
            for command in command_models
            if command.sandbox_inspection_artifact_id is not None
        ]
        risks = [item.description for item in bundle.remaining_risks]
        gaps = [item.description for item in bundle.proof_gaps]
        if sandbox_configuration.provider == "docker":
            policy_mode = BootstrapPolicyMode.VERIFIED
            publish_allowed = bundle.completion_decision.verified_complete and not gaps
        elif sandbox_configuration.provider == "fake":
            policy_mode = BootstrapPolicyMode.DEGRADED_SIMULATION
            gaps = gaps or ["FakeSandbox did not execute project code."]
            publish_allowed = False
        else:
            policy_mode = BootstrapPolicyMode.UNSAFE_HOST_DEVELOPMENT
            risks = risks or ["Verification executed directly on the unsafe host."]
            publish_allowed = False
        return BootstrapReport(
            target_identity_hash=target_info.identity_hash,
            target_head_revision=target_info.head_revision,
            target_status_fingerprint=target_info.status_fingerprint,
            target_runtime_configuration=target_runtime_configuration,
            target_runtime_configuration_sha256=canonical_json_hash(
                target_runtime_configuration.model_dump(mode="json")
            ),
            proposal_sha256=self._required_string(preview, "proposal_sha256"),
            proposal=preparation_references["proposal"],
            repository_profile=preparation_references["repository_profile"],
            repository_profile_semantic_sha256=self._required_string(
                preview, "repository_profile_semantic_sha256"
            ),
            project_knowledge=preparation_references["project_knowledge"],
            project_knowledge_semantic_sha256=self._required_string(
                preview, "project_knowledge_semantic_sha256"
            ),
            config_snapshot=preparation_references["config_snapshot"],
            sandbox_configuration=sandbox_configuration,
            sandbox_configuration_sha256=canonical_json_hash(
                sandbox_configuration.model_dump(mode="json")
            ),
            sandbox_capabilities=run.sandbox_capabilities_snapshot,
            sandbox_capabilities_sha256=canonical_json_hash(
                run.sandbox_capabilities_snapshot.model_dump(mode="json")
            ),
            sandbox_requirements=run.sandbox_requirements,
            sandbox_requirements_sha256=canonical_json_hash(
                run.sandbox_requirements.model_dump(mode="json")
            ),
            sandbox_preflight=preflight,
            sandbox_preflight_sha256=canonical_json_hash(preflight.model_dump(mode="json")),
            canary_project_id=canary_project_id,
            canary_run_id=run.run_id,
            canary_task_id=run.task_id,
            canary_status=run.status,
            task_spec=self._reference(self.state.get_artifact(run.task_spec_artifact_id)),
            fleet_plan=self._reference(self.state.get_artifact(run.fleet_plan_artifact_id)),
            patch=self._reference(self.state.get_artifact(run.patch_artifact_id)),
            command_evidence=command_references,
            command_transcripts=transcript_references,
            sandbox_inspections=inspection_references,
            verifier_verdict=self._reference(
                self.state.get_artifact(run.verifier_verdict_artifact_id)
            ),
            evidence_bundle=self._reference(
                self.state.get_artifact(run.evidence_bundle_artifact_id)
            ),
            cleanup_receipt=self._reference(
                self.state.get_artifact(run.cleanup_receipt_artifact_id)
            ),
            completion_decision=bundle.completion_decision,
            cleanup_complete=True,
            outstanding_lease_count=0,
            policy_mode=policy_mode,
            publish_allowed=publish_allowed,
            remaining_risks=risks,
            proof_gaps=gaps,
            created_at=started_at,
            completed_at=self.clock.now(),
        )

    def _read_and_validate_report(self, artifact: ArtifactMetadata) -> BootstrapReport:
        try:
            stored_report_artifact = self.state.get_artifact(artifact.artifact_id)
            report = BootstrapReport.model_validate_json(
                self.artifacts.read_text(artifact.artifact_id)
            )
            if (
                stored_report_artifact != artifact
                or artifact.kind is not ArtifactKind.BOOTSTRAP_REPORT
                or artifact.producer != "bootstrap-service"
                or artifact.mime_type != "application/json"
                or artifact.project_id != report.canary_project_id
                or artifact.run_id != report.canary_run_id
                or artifact.task_id != report.canary_task_id
            ):
                raise ValueError("bootstrap report artifact identity mismatch")
            run = self.state.get_run(report.canary_run_id)
            task = self.state.get_task(report.canary_task_id)
            canary_project = self.state.get_project(report.canary_project_id)
            if (
                run.project_id != report.canary_project_id
                or run.task_id != report.canary_task_id
                or task.run_id != report.canary_run_id
                or run.status is not RunStatus.READY_FOR_REVIEW
                or report.canary_status is not run.status
                or run.fleet_strategy != FleetStrategy.ENGINEER_VERIFIER.value
                or run.runtime_name != "fake"
                or run.fake_scenario is not FakeScenario.SUCCESS
                or run.repair_iterations != 0
                or canary_project.runtime_name != "fake"
            ):
                raise ValueError("bootstrap canary aggregate identity mismatch")
            if self.state.outstanding_leases(report.canary_run_id):
                raise ValueError("bootstrap canary still has outstanding resource leases")
            profile = RepositoryProfile.model_validate_json(
                self._validate_reference(
                    report.repository_profile,
                    RepositoryProfile,
                    project_id=report.canary_project_id,
                    run_id=None,
                    task_id=None,
                )
            )
            if (
                canonical_json_hash(profile.model_dump(mode="json"))
                != report.repository_profile_semantic_sha256
            ):
                raise ValueError("repository profile semantic hash mismatch")
            knowledge = ProjectKnowledge.model_validate_json(
                self._validate_reference(
                    report.project_knowledge,
                    ProjectKnowledge,
                    project_id=report.canary_project_id,
                    run_id=None,
                    task_id=None,
                )
            )
            if (
                canonical_json_hash(knowledge.model_dump(mode="json"))
                != report.project_knowledge_semantic_sha256
                or knowledge.source_profile_sha256 != report.repository_profile_semantic_sha256
            ):
                raise ValueError("project knowledge semantic binding mismatch")
            proposal = json.loads(
                self._validate_reference(
                    report.proposal,
                    None,
                    project_id=report.canary_project_id,
                    run_id=None,
                    task_id=None,
                )
            )
            if (
                not isinstance(proposal, dict)
                or canonical_json_hash(proposal) != report.proposal_sha256
            ):
                raise ValueError("bootstrap proposal hash mismatch")
            target_snapshot_content = self._validate_reference(
                report.config_snapshot,
                ConfigSnapshot,
                project_id=report.canary_project_id,
                run_id=None,
                task_id=None,
            )
            target_snapshot = ConfigSnapshot.model_validate_json(target_snapshot_content)
            proposal_files = proposal.get("files")
            proposal_snapshot_files = (
                {key: value for key, value in proposal_files.items() if key != "README.md"}
                if isinstance(proposal_files, dict)
                else None
            )
            if (
                self.config.snapshot_hash(target_snapshot) != report.config_snapshot.sha256
                or not isinstance(proposal_files, dict)
                or {item.path: item.content for item in target_snapshot.files}
                != proposal_snapshot_files
                or "README.md" not in proposal_files
            ):
                raise ValueError("target configuration snapshot semantic hash mismatch")
            task_content = self._validate_reference(
                report.task_spec,
                TaskSpec,
                project_id=report.canary_project_id,
                run_id=report.canary_run_id,
                task_id=report.canary_task_id,
            )
            if TaskSpec.model_validate_json(task_content) != task:
                raise ValueError("bootstrap TaskSpec differs from persisted task")
            plan_content = self._validate_reference(
                report.fleet_plan,
                FleetPlan,
                project_id=report.canary_project_id,
                run_id=report.canary_run_id,
                task_id=report.canary_task_id,
            )
            plan = FleetPlan.model_validate_json(plan_content)
            validate_fleet_plan(
                plan,
                task,
                known_roles={"cos", "engineer", "verifier"},
            )
            patch_content = self._validate_reference(
                report.patch,
                None,
                project_id=report.canary_project_id,
                run_id=report.canary_run_id,
                task_id=report.canary_task_id,
            )
            if (
                report.task_spec.artifact_id != run.task_spec_artifact_id
                or report.task_spec.sha256 != run.task_spec_hash
                or report.fleet_plan.artifact_id != run.fleet_plan_artifact_id
                or report.fleet_plan.sha256 != run.fleet_plan_hash
                or report.patch.artifact_id != run.patch_artifact_id
                or report.patch.sha256 != run.patch_sha256
                or plan.strategy is not FleetStrategy.ENGINEER_VERIFIER
                or not patch_content.strip()
            ):
                raise ValueError("bootstrap authoritative run bindings mismatch")
            expected_command = CommandSpec(
                command_id="bootstrap-unittest",
                executable="python",
                argv=(
                    "-B",
                    "-m",
                    "unittest",
                    "discover",
                    "-s",
                    "tests",
                    "-p",
                    "test_*.py",
                ),
                logical_cwd=".",
                environment={},
                timeout_seconds=60,
                network_requirement="none",
            )
            if (
                task.original_goal != "Fix the canary behavior"
                or task.normalized_goal != "Fix the canary behavior"
                or task.allowed_paths != ["src/canary_calc/core.py"]
                or task.forbidden_paths != [".git", ".fleet"]
                or len(task.acceptance_criteria) != 1
                or task.acceptance_criteria[0].criterion_id != "canary-zero-division"
                or set(task.required_evidence)
                != {
                    "canonical_patch",
                    "command_evidence",
                    "independent_verifier_verdict",
                }
                or task.verification_commands != [expected_command]
                or task.required_verification_command_ids != ["bootstrap-unittest"]
            ):
                raise ValueError("bootstrap canary TaskSpec is not the trusted fixed contract")
            if [item.artifact_id for item in report.command_evidence] != list(
                run.command_evidence_artifact_ids
            ):
                raise ValueError("bootstrap command evidence set mismatch")
            commands = [
                CommandEvidence.model_validate_json(
                    self._validate_reference(
                        reference,
                        CommandEvidence,
                        project_id=report.canary_project_id,
                        run_id=report.canary_run_id,
                        task_id=report.canary_task_id,
                    )
                )
                for reference in report.command_evidence
            ]
            expected_transcripts = [item.transcript_artifact_id for item in commands]
            if [item.artifact_id for item in report.command_transcripts] != expected_transcripts:
                raise ValueError("bootstrap command transcript set mismatch")
            transcript_contents = [
                self._validate_reference(
                    reference,
                    None,
                    project_id=report.canary_project_id,
                    run_id=report.canary_run_id,
                    task_id=report.canary_task_id,
                )
                for reference in report.command_transcripts
            ]
            expected_inspections = [
                item.sandbox_inspection_artifact_id
                for item in commands
                if item.sandbox_inspection_artifact_id is not None
            ]
            if [item.artifact_id for item in report.sandbox_inspections] != expected_inspections:
                raise ValueError("bootstrap sandbox inspection set mismatch")
            inspections = [
                SandboxInspection.model_validate_json(
                    self._validate_reference(
                        reference,
                        SandboxInspection,
                        project_id=report.canary_project_id,
                        run_id=report.canary_run_id,
                        task_id=report.canary_task_id,
                    )
                )
                for reference in report.sandbox_inspections
            ]
            verdict_content = self._validate_reference(
                report.verifier_verdict,
                VerifierVerdict,
                project_id=report.canary_project_id,
                run_id=report.canary_run_id,
                task_id=report.canary_task_id,
            )
            verifier_verdict = VerifierVerdict.model_validate_json(verdict_content)
            if report.verifier_verdict.artifact_id != run.verifier_verdict_artifact_id:
                raise ValueError("bootstrap verifier verdict binding mismatch")
            bundle_content = self._validate_reference(
                report.evidence_bundle,
                EvidenceBundle,
                project_id=report.canary_project_id,
                run_id=report.canary_run_id,
                task_id=report.canary_task_id,
            )
            bundle = EvidenceBundle.model_validate_json(bundle_content)
            self._validate_reference(
                report.cleanup_receipt,
                None,
                project_id=report.canary_project_id,
                run_id=report.canary_run_id,
                task_id=report.canary_task_id,
            )
            reconstructed = self.evidence.assemble(
                run,
                task,
                assembled_at=bundle.assembled_at,
            )
            expected_risks = [item.description for item in bundle.remaining_risks]
            expected_gaps = [item.description for item in bundle.proof_gaps]
            if (
                reconstructed != bundle
                or bundle.completion_decision != report.completion_decision
                or report.evidence_bundle.artifact_id != run.evidence_bundle_artifact_id
                or report.evidence_bundle.sha256 != run.evidence_bundle_hash
                or report.cleanup_receipt.artifact_id != run.cleanup_receipt_artifact_id
                or report.cleanup_receipt.sha256 != run.cleanup_receipt_sha256
                or report.remaining_risks != expected_risks
                or report.proof_gaps != expected_gaps
                or run.sandbox_configuration != report.sandbox_configuration
                or run.sandbox_configuration_hash != report.sandbox_configuration_sha256
                or run.sandbox_requirements != report.sandbox_requirements
                or run.sandbox_capabilities_snapshot != report.sandbox_capabilities
                or run.sandbox_image_identity != report.sandbox_preflight.image_identity
                or run.sandbox_daemon_identity != report.sandbox_preflight.daemon_identity
                or canary_project.sandbox_image_identity != report.sandbox_preflight.image_identity
                or canary_project.sandbox_daemon_identity
                != report.sandbox_preflight.daemon_identity
                or canary_project.sandbox_configuration != report.sandbox_configuration
                or canary_project.sandbox_configuration_hash != report.sandbox_configuration_sha256
                or canary_project.sandbox_name != report.sandbox_configuration.provider
                or report.sandbox_requirements
                != requirements_for_configuration(report.sandbox_configuration)
                or (
                    report.sandbox_configuration.provider == "docker"
                    and report.sandbox_preflight.endpoint_kind != "local-unix"
                )
                or run.verifier_workspace_mutated
                or not (
                    report.created_at
                    <= report.sandbox_preflight.checked_at
                    <= report.completed_at
                    <= artifact.created_at
                )
            ):
                raise ValueError("bootstrap completion decision mismatch")
            engineer_commands = [
                item
                for item in commands
                if item.principal_role == "engineer"
                and item.workflow_stage is WorkflowStage.IMPLEMENTING
                and item.workspace_kind is WorkspaceKind.CANDIDATE
            ]
            verifier_commands = [
                item
                for item in commands
                if item.agent_instance_id == run.verifier_agent_instance_id
                and item.principal_role == "verifier"
                and item.workflow_stage is WorkflowStage.VERIFYING
                and item.workspace_kind is WorkspaceKind.VERIFICATION
            ]
            strict_command_evidence = (
                len(commands) == 2
                and len(engineer_commands) == 1
                and len(verifier_commands) == 1
                and engineer_commands[0].strength is EvidenceStrength.OBSERVED
                and verifier_commands[0].strength is EvidenceStrength.INDEPENDENTLY_VERIFIED
                and engineer_commands[0].workspace_id != verifier_commands[0].workspace_id
                and engineer_commands[0].sandbox_id != verifier_commands[0].sandbox_id
                and all(
                    item.command_id == "bootstrap-unittest"
                    and item.exit_code == 0
                    and not item.timed_out
                    and not item.output_truncated
                    and not item.workspace_mutated_during_execution
                    and item.candidate_patch_sha256 == report.patch.sha256
                    and item.sandbox_image_identity == report.sandbox_preflight.image_identity
                    and item.sandbox_daemon_identity == report.sandbox_preflight.daemon_identity
                    for item in commands
                )
                and all(
                    content.count(BOOTSTRAP_SANDBOX_PROBE_MARKER) == 1
                    for content in transcript_contents
                )
            )
            if report.publish_allowed and (
                report.sandbox_configuration.provider != "docker"
                or report.policy_mode is not BootstrapPolicyMode.VERIFIED
                or bundle.completion_decision is None
                or not bundle.completion_decision.verified_complete
                or bundle.completion_decision.effective_verdict.value != "pass"
                or bundle.proof_gaps
                or not run.verified_complete
                or run.assurance_verdict is None
                or run.assurance_verdict.value != "pass"
                or verifier_verdict.verdict.value != "pass"
                or not strict_command_evidence
                or any(
                    inspection.image_identity != report.sandbox_preflight.image_identity
                    or inspection.missing_requirements(report.sandbox_requirements)
                    for inspection in inspections
                )
            ):
                raise ValueError("bootstrap publication evidence is incomplete")
        except (FleetError, ValidationError, ValueError, TypeError, json.JSONDecodeError) as error:
            raise FleetError(
                ErrorCode.BOOTSTRAP_REPORT_INVALID,
                "The persisted bootstrap report or one of its evidence references is invalid.",
                "Preserve the canary artifacts and retry after repairing the state boundary.",
            ) from error
        return report

    def _validate_reference(
        self,
        reference: ArtifactReference,
        model: type[BaseModel] | None,
        *,
        project_id: str,
        run_id: str | None,
        task_id: str | None,
    ) -> str:
        metadata = self.state.get_artifact(reference.artifact_id)
        if (
            metadata.kind is not reference.kind
            or metadata.sha256 != reference.sha256
            or metadata.project_id != project_id
            or metadata.run_id != run_id
            or metadata.task_id != task_id
        ):
            raise ValueError("bootstrap artifact metadata binding mismatch")
        content = self.artifacts.read_text(reference.artifact_id)
        if model is not None:
            validator = model.model_validate_json
            validator(content)
        return content

    @staticmethod
    def _reference(artifact: ArtifactMetadata) -> ArtifactReference:
        return ArtifactReference(
            artifact_id=artifact.artifact_id,
            kind=artifact.kind,
            sha256=artifact.sha256,
        )

    @staticmethod
    def _required_string(data: dict[str, object], key: str) -> str:
        value = data.get(key)
        if not isinstance(value, str):
            raise RuntimeError(f"bootstrap data is missing {key}")
        return value
