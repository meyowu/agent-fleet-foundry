"""Structured evidence and deterministic completion assurance."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field, field_validator, model_validator

from agent_fleet.domain.fleet_plan import FleetStrategy
from agent_fleet.domain.models import (
    ActionId,
    AgentInstanceId,
    ArtifactId,
    CriterionId,
    CriterionResult,
    EvidenceRequirementId,
    ImageIdentity,
    LeaseId,
    LeaseKind,
    LeaseStatus,
    ProjectId,
    RoleId,
    RunId,
    SandboxCapabilities,
    SandboxId,
    SandboxNetworkMode,
    SandboxProviderId,
    SandboxRequirements,
    SandboxSecurityLevel,
    Sha256,
    StrictModel,
    TaskId,
    Verdict,
    WorkflowStage,
    WorkspaceId,
    WorkspaceKind,
    _require_utc,
)
from agent_fleet.domain.security import canonical_json_hash


class EvidenceStrength(StrEnum):
    SIMULATED = "simulated"
    OBSERVED = "observed"
    INDEPENDENTLY_VERIFIED = "independently_verified"


class CommandEvidence(StrictModel):
    evidence_id: ArtifactId
    run_id: RunId
    task_id: TaskId
    agent_instance_id: AgentInstanceId
    principal_role: RoleId | None = None
    workflow_stage: WorkflowStage | None = None
    workspace_id: WorkspaceId | None = None
    sandbox_id: SandboxId | None = None
    command_id: ActionId = "legacy-verification"
    command_spec_sha256: Sha256 | None = None
    executable: str
    argv: list[str]
    cwd: str
    sandbox_provider: str
    sandbox_security_level: SandboxSecurityLevel
    sandbox_capabilities_sha256: Sha256 | None = None
    sandbox_configuration_sha256: Sha256 | None = None
    sandbox_requirements_sha256: Sha256 | None = None
    sandbox_image_identity: ImageIdentity | None = None
    sandbox_daemon_identity: Sha256 | None = None
    strength: EvidenceStrength
    exit_code: int
    timed_out: bool
    output_truncated: bool
    transcript_artifact_id: ArtifactId
    workspace_base_revision: str
    config_snapshot_sha256: Sha256
    candidate_patch_sha256: Sha256 | None = None
    workspace_kind: WorkspaceKind = WorkspaceKind.CANDIDATE
    network_mode: SandboxNetworkMode = "none"
    workspace_mutated_during_execution: bool = False
    execution_id: str | None = None
    sandbox_inspection_artifact_id: ArtifactId | None = None
    sandbox_inspection_sha256: Sha256 | None = None
    started_at: datetime
    completed_at: datetime

    _started_utc = field_validator("started_at")(_require_utc)
    _completed_utc = field_validator("completed_at")(_require_utc)


class CriterionAssessment(StrictModel):
    criterion_id: CriterionId
    verdict: Verdict
    evidence_artifact_ids: list[ArtifactId] = Field(default_factory=list)
    explanation: str


def assess_criterion_results(
    results: list[CriterionResult],
    *,
    expected_criteria: set[str],
    commands: list[CommandEvidence],
    verifier_evidence_artifact_ids: list[str],
    run_id: str,
    task_id: str,
    verifier_agent_instance_id: str | None,
    base_revision: str,
    config_snapshot_sha256: str,
    patch_sha256: str | None,
    command_hashes: dict[str, str],
) -> tuple[list[CriterionAssessment], list[ProofGap]]:
    """Resolve model references only against exact current control-plane records.

    Each criterion selects one explicit artifact per command. Repeated execution
    is supported, but only the uniquely latest current-patch artifact can prove a
    command; an ambiguous timestamp or cherry-picked earlier result cannot pass.
    """

    identifiers = [result.criterion_id for result in results]
    invalid_catalog = (
        len(identifiers) != len(set(identifiers))
        or set(identifiers) != expected_criteria
        or len(commands) != len({command.evidence_id for command in commands})
    )
    catalog = {command.evidence_id: command for command in commands}
    by_criterion = {result.criterion_id: result for result in results}
    declared = set(verifier_evidence_artifact_ids)
    assessments: list[CriterionAssessment] = []
    gaps: list[ProofGap] = []
    for criterion_id in sorted(expected_criteria):
        result = by_criterion.get(criterion_id)
        valid = not invalid_catalog and result is not None
        selected: list[CommandEvidence] = []
        if result is not None:
            selected = [catalog[item] for item in result.evidence_artifact_ids if item in catalog]
            valid = valid and (
                bool(selected)
                and len(selected) == len(result.evidence_artifact_ids)
                and len(result.evidence_artifact_ids) == len(set(result.evidence_artifact_ids))
                and len(result.command_ids) == len(set(result.command_ids))
                and len(selected) == len(result.command_ids)
                and {item.command_id for item in selected} == set(result.command_ids)
                and set(result.evidence_artifact_ids).issubset(declared)
            )
        for command in selected:
            matching = [
                item
                for item in commands
                if item.command_id == command.command_id
                and item.agent_instance_id == verifier_agent_instance_id
                and item.candidate_patch_sha256 == patch_sha256
            ]
            latest = max((item.completed_at for item in matching), default=None)
            valid = valid and (
                command.run_id == run_id
                and command.task_id == task_id
                and command.agent_instance_id == verifier_agent_instance_id
                and command.principal_role == "verifier"
                and command.workflow_stage is WorkflowStage.VERIFYING
                and command.workspace_kind is WorkspaceKind.VERIFICATION
                and command.workspace_id is not None
                and command.sandbox_id is not None
                and command.workspace_base_revision == base_revision
                and command.config_snapshot_sha256 == config_snapshot_sha256
                and command.candidate_patch_sha256 == patch_sha256
                and command.command_id in command_hashes
                and command.command_spec_sha256 == command_hashes.get(command.command_id)
                and command.strength is EvidenceStrength.INDEPENDENTLY_VERIFIED
                and command.sandbox_security_level is SandboxSecurityLevel.ISOLATED
                and command.sandbox_provider not in {"fake", "local-unsafe"}
                and not command.workspace_mutated_during_execution
                and not command.output_truncated
                and command.completed_at >= command.started_at
                and command.completed_at == latest
                and sum(item.completed_at == latest for item in matching) == 1
            )
        if len({(item.workspace_id, item.sandbox_id) for item in selected}) > 1:
            valid = False
        verdict = Verdict.INCONCLUSIVE
        if valid and result is not None:
            verdict = result.verdict
            if any(item.exit_code != 0 or item.timed_out for item in selected):
                verdict = Verdict.FAIL
        else:
            gaps.append(
                ProofGap(
                    code="STRUCTURED_CRITERION_MAPPING_INVALID",
                    description=(
                        f"Criterion {criterion_id} lacks an exact current verifier mapping."
                    ),
                    required_strength=EvidenceStrength.INDEPENDENTLY_VERIFIED,
                )
            )
        assessments.append(
            CriterionAssessment(
                criterion_id=criterion_id,
                verdict=verdict,
                evidence_artifact_ids=(result.evidence_artifact_ids if valid and result else []),
                explanation=(
                    "Exact current independent verifier command records resolve this criterion."
                    if valid
                    else "The criterion mapping is missing, ambiguous, or unbound."
                ),
            )
        )
    return assessments, gaps


class RemainingRisk(StrictModel):
    code: str
    description: str


class ProofGap(StrictModel):
    code: str
    description: str
    required_strength: EvidenceStrength | None = None


class CompletionDecision(StrictModel):
    verified_complete: bool
    effective_verdict: Verdict
    reason_codes: list[str]


class CleanupLeaseRecord(StrictModel):
    lease_id: LeaseId
    kind: LeaseKind
    resource_id: str
    status: LeaseStatus


class ResourceCleanupReceipt(StrictModel):
    api_version: Literal["agentfleet.dev/v1alpha1"] = "agentfleet.dev/v1alpha1"
    kind: Literal["ResourceCleanupReceipt"] = "ResourceCleanupReceipt"
    run_id: RunId
    leases: list[CleanupLeaseRecord] = Field(max_length=1024)
    complete: bool
    completed_at: datetime

    _completed_utc = field_validator("completed_at")(_require_utc)

    @model_validator(mode="after")
    def validate_terminal_snapshot(self) -> ResourceCleanupReceipt:
        identifiers = [item.lease_id for item in self.leases]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("cleanup receipt lease identities must be unique")
        all_terminal = all(
            item.status in {LeaseStatus.RELEASED, LeaseStatus.RECOVERED} for item in self.leases
        )
        if self.complete != all_terminal:
            raise ValueError("cleanup receipt completeness does not match lease states")
        return self


class EvidenceBundle(StrictModel):
    api_version: Literal["agentfleet.dev/v1alpha1"] = "agentfleet.dev/v1alpha1"
    kind: Literal["EvidenceBundle"] = "EvidenceBundle"
    run_id: RunId
    project_id: ProjectId
    task_id: TaskId
    base_revision: str
    config_snapshot_artifact_id: ArtifactId
    config_snapshot_sha256: Sha256
    task_spec_artifact_id: ArtifactId
    task_spec_sha256: Sha256
    fleet_plan_artifact_id: ArtifactId
    fleet_plan_sha256: Sha256
    fleet_strategy: FleetStrategy
    required_evidence: list[EvidenceRequirementId] = Field(min_length=1, max_length=32)
    sandbox_provider: SandboxProviderId = "fake"
    sandbox_security_level: SandboxSecurityLevel = SandboxSecurityLevel.FAKE
    sandbox_configuration_sha256: Sha256 | None = None
    sandbox_requirements: SandboxRequirements | None = None
    sandbox_requirements_sha256: Sha256 | None = None
    sandbox_image_identity: ImageIdentity | None = None
    sandbox_daemon_identity: Sha256 | None = None
    sandbox_capabilities: SandboxCapabilities = Field(
        default_factory=SandboxCapabilities.phase1_fake
    )
    sandbox_capabilities_sha256: Sha256 | None = None
    verification_command_hashes: dict[ActionId, Sha256] = Field(
        default_factory=dict,
        max_length=32,
    )
    required_verification_command_ids: list[ActionId] = Field(
        default_factory=list,
        max_length=32,
    )
    patch_artifact_id: ArtifactId | None = None
    patch_sha256: Sha256 | None = None
    changed_paths: list[str] = Field(default_factory=list)
    command_evidence: list[CommandEvidence] = Field(default_factory=list)
    verifier_agent_instance_id: AgentInstanceId | None = None
    verifier_verdict_artifact_id: ArtifactId | None = None
    verifier_evidence_artifact_ids: list[ArtifactId] = Field(default_factory=list)
    verifier_workspace_mutated: bool = False
    reported_verdict: Verdict | None = None
    verifier_required_repairs: list[str] = Field(default_factory=list)
    verifier_regressions: list[str] = Field(default_factory=list)
    cleanup_receipt_artifact_id: ArtifactId | None = None
    cleanup_receipt_sha256: Sha256 | None = None
    cleanup_complete: bool = False
    criterion_assessments: list[CriterionAssessment] = Field(min_length=1, max_length=128)
    structured_criterion_results: list[CriterionResult] | None = Field(default=None, max_length=128)
    remaining_risks: list[RemainingRisk] = Field(default_factory=list)
    proof_gaps: list[ProofGap] = Field(default_factory=list)
    completion_decision: CompletionDecision | None = None
    assembled_at: datetime

    _assembled_utc = field_validator("assembled_at")(_require_utc)

    @field_validator("required_evidence")
    @classmethod
    def validate_evidence_requirements(
        cls, values: list[EvidenceRequirementId]
    ) -> list[EvidenceRequirementId]:
        if len(values) != len(set(values)):
            raise ValueError("EvidenceBundle evidence requirements must be unique")
        return values

    @model_validator(mode="after")
    def validate_cleanup_binding(self) -> EvidenceBundle:
        if (self.cleanup_receipt_artifact_id is None) != (self.cleanup_receipt_sha256 is None):
            raise ValueError("EvidenceBundle cleanup receipt ID and hash must be paired")
        if self.cleanup_complete and self.cleanup_receipt_artifact_id is None:
            raise ValueError("complete cleanup requires a receipt artifact")
        if (self.sandbox_requirements is None) != (self.sandbox_requirements_sha256 is None):
            raise ValueError("EvidenceBundle sandbox requirements and hash must be paired")
        if (
            self.sandbox_requirements is not None
            and canonical_json_hash(self.sandbox_requirements.model_dump(mode="json"))
            != self.sandbox_requirements_sha256
        ):
            raise ValueError("EvidenceBundle sandbox requirements hash does not match")
        return self

    @field_validator("required_verification_command_ids")
    @classmethod
    def validate_required_command_ids(cls, values: list[ActionId]) -> list[ActionId]:
        if len(values) != len(set(values)):
            raise ValueError("EvidenceBundle required verification command IDs must be unique")
        return values

    @field_validator("criterion_assessments")
    @classmethod
    def validate_criterion_assessments(
        cls, values: list[CriterionAssessment]
    ) -> list[CriterionAssessment]:
        criterion_ids = [item.criterion_id for item in values]
        if len(criterion_ids) != len(set(criterion_ids)):
            raise ValueError("EvidenceBundle criterion assessment IDs must be unique")
        return values


class CompletionGate:
    """Compute assurance only from control-plane evidence, never agent prose."""

    @staticmethod
    def evaluate(
        bundle: EvidenceBundle,
        *,
        expected_criteria: set[str],
        authoritative_artifact_ids: set[str],
    ) -> CompletionDecision:
        reasons: list[str] = []
        if bundle.structured_criterion_results is not None:
            mapped, mapping_gaps = assess_criterion_results(
                bundle.structured_criterion_results,
                expected_criteria=expected_criteria,
                commands=bundle.command_evidence,
                verifier_evidence_artifact_ids=bundle.verifier_evidence_artifact_ids,
                run_id=bundle.run_id,
                task_id=bundle.task_id,
                verifier_agent_instance_id=bundle.verifier_agent_instance_id,
                base_revision=bundle.base_revision,
                config_snapshot_sha256=bundle.config_snapshot_sha256,
                patch_sha256=bundle.patch_sha256,
                command_hashes=bundle.verification_command_hashes,
            )
            if (
                mapping_gaps
                or sorted(bundle.criterion_assessments, key=lambda item: item.criterion_id)
                != mapped
            ):
                reasons.append("STRUCTURED_CRITERION_MAPPING_INVALID")
        elif len(expected_criteria) > 1:
            reasons.append("STRUCTURED_CRITERION_MAPPING_UNAVAILABLE")
        if (
            not bundle.cleanup_complete
            or bundle.cleanup_receipt_artifact_id is None
            or bundle.cleanup_receipt_sha256 is None
            or bundle.cleanup_receipt_artifact_id not in authoritative_artifact_ids
        ):
            reasons.append("RESOURCE_CLEANUP_UNPROVEN")
        if not expected_criteria:
            reasons.append("CRITERIA_NOT_DEFINED")
        assessments = {item.criterion_id: item for item in bundle.criterion_assessments}
        command_artifact_ids = [item.evidence_id for item in bundle.command_evidence]
        verifier_commands = [
            item
            for item in bundle.command_evidence
            if item.agent_instance_id == bundle.verifier_agent_instance_id
        ]
        verifier_command_artifact_ids = {item.evidence_id for item in verifier_commands}
        computed_capabilities_hash = canonical_json_hash(
            bundle.sandbox_capabilities.model_dump(mode="json")
        )
        if bundle.sandbox_requirements is None or bundle.sandbox_requirements_sha256 is None:
            reasons.append("SANDBOX_REQUIREMENTS_BINDING_MISSING")
        if (
            bundle.sandbox_capabilities.provider != bundle.sandbox_provider
            or bundle.sandbox_capabilities.security_level is not bundle.sandbox_security_level
        ):
            reasons.append("SANDBOX_CAPABILITY_IDENTITY_MISMATCH")
        if (
            bundle.sandbox_capabilities_sha256 is None
            or bundle.sandbox_capabilities_sha256 != computed_capabilities_hash
        ):
            reasons.append("SANDBOX_CAPABILITY_BINDING_INVALID")
        if (
            bundle.sandbox_security_level is SandboxSecurityLevel.ISOLATED
            and bundle.sandbox_configuration_sha256 is None
        ):
            reasons.append("SANDBOX_CONFIGURATION_BINDING_MISSING")
        if (
            bundle.sandbox_security_level is SandboxSecurityLevel.ISOLATED
            and bundle.sandbox_image_identity is None
        ):
            reasons.append("SANDBOX_IMAGE_BINDING_MISSING")
        if (
            bundle.sandbox_security_level is SandboxSecurityLevel.ISOLATED
            and bundle.sandbox_daemon_identity is None
        ):
            reasons.append("SANDBOX_DAEMON_BINDING_MISSING")
        reviewed_command_ids = set(bundle.verification_command_hashes)
        required_command_ids = set(bundle.required_verification_command_ids)
        if not required_command_ids.issubset(reviewed_command_ids):
            reasons.append("REQUIRED_COMMAND_PROFILE_INVALID")
        if (
            bundle.sandbox_security_level is SandboxSecurityLevel.ISOLATED
            and not reviewed_command_ids
        ):
            reasons.append("REVIEWED_COMMAND_PROFILE_MISSING")
        if len(command_artifact_ids) != len(set(command_artifact_ids)):
            reasons.append("COMMAND_EVIDENCE_DUPLICATE")
        declared_artifact_ids = {
            bundle.config_snapshot_artifact_id,
            bundle.task_spec_artifact_id,
            bundle.fleet_plan_artifact_id,
            *(item.evidence_id for item in bundle.command_evidence),
            *(item.transcript_artifact_id for item in bundle.command_evidence),
            *(
                item.sandbox_inspection_artifact_id
                for item in bundle.command_evidence
                if item.sandbox_inspection_artifact_id is not None
            ),
        }
        criterion_evidence_ids = set(command_artifact_ids)
        if bundle.patch_artifact_id is not None:
            declared_artifact_ids.add(bundle.patch_artifact_id)
        if bundle.verifier_verdict_artifact_id is not None:
            declared_artifact_ids.add(bundle.verifier_verdict_artifact_id)
            criterion_evidence_ids.add(bundle.verifier_verdict_artifact_id)
        if not declared_artifact_ids.issubset(authoritative_artifact_ids):
            reasons.append("ARTIFACT_REFERENCE_MISSING")
        missing_requirements: list[str] = []
        for requirement in bundle.required_evidence:
            requirement_missing = (
                (
                    requirement == "control_plane_plan"
                    and bundle.fleet_plan_artifact_id not in authoritative_artifact_ids
                )
                or (
                    requirement == "canonical_patch"
                    and (
                        bundle.patch_artifact_id is None
                        or bundle.patch_sha256 is None
                        or not bundle.changed_paths
                    )
                )
                or (requirement == "command_evidence" and not bundle.command_evidence)
                or (
                    requirement == "independent_verifier_verdict"
                    and (
                        bundle.verifier_agent_instance_id is None
                        or bundle.verifier_verdict_artifact_id is None
                        or bundle.reported_verdict is None
                        or not verifier_command_artifact_ids
                        or not bundle.verifier_evidence_artifact_ids
                    )
                )
            )
            if requirement_missing:
                missing_requirements.append(requirement)
        if missing_requirements:
            reasons.append("REQUIRED_EVIDENCE_MISSING")
        if len(assessments) != len(bundle.criterion_assessments):
            reasons.append("CRITERIA_EVIDENCE_DUPLICATE")
        if set(assessments) != expected_criteria:
            reasons.append("CRITERIA_EVIDENCE_INCOMPLETE")
        if any(item.verdict is not Verdict.PASS for item in assessments.values()):
            reasons.append("CRITERION_NOT_PASSING")
        if any(
            item.verdict is Verdict.PASS and not item.evidence_artifact_ids
            for item in assessments.values()
        ):
            reasons.append("CRITERION_EVIDENCE_MISSING")
        if any(
            not set(item.evidence_artifact_ids).issubset(criterion_evidence_ids)
            or not set(item.evidence_artifact_ids).issubset(authoritative_artifact_ids)
            for item in assessments.values()
        ):
            reasons.append("CRITERION_EVIDENCE_UNBOUND")
        if bundle.proof_gaps:
            reasons.append("PROOF_GAPS_PRESENT")
        if bundle.fleet_strategy is FleetStrategy.ENGINEER_VERIFIER and (
            bundle.verifier_agent_instance_id is None or bundle.verifier_verdict_artifact_id is None
        ):
            reasons.append("INDEPENDENT_VERIFIER_MISSING")
        requires_independent_verifier = (
            "independent_verifier_verdict" in bundle.required_evidence
            or bundle.fleet_strategy
            in {
                FleetStrategy.ENGINEER_VERIFIER,
                FleetStrategy.RESEARCH_ARCHITECT_ENGINEER_VERIFIER,
            }
        )
        if requires_independent_verifier and not verifier_command_artifact_ids:
            reasons.append("INDEPENDENT_VERIFIER_EVIDENCE_MISSING")
        if bundle.verifier_verdict_artifact_id is not None and (
            not bundle.verifier_evidence_artifact_ids
            or set(bundle.verifier_evidence_artifact_ids) != verifier_command_artifact_ids
            or not set(bundle.verifier_evidence_artifact_ids).issubset(authoritative_artifact_ids)
        ):
            reasons.append("VERIFIER_EVIDENCE_BINDING_INVALID")
        if bundle.verifier_workspace_mutated:
            reasons.append("VERIFIER_WORKSPACE_MUTATED")
        if bundle.reported_verdict is Verdict.PASS and bundle.verifier_required_repairs:
            reasons.append("VERIFIER_PASS_WITH_REQUIRED_REPAIRS")
        if bundle.reported_verdict is Verdict.PASS and bundle.verifier_regressions:
            reasons.append("VERIFIER_PASS_WITH_REGRESSIONS")
        if bundle.reported_verdict is Verdict.FAIL:
            reasons.append("VERIFIER_REPORTED_FAIL")
        if (bundle.reported_verdict is None) != (bundle.verifier_verdict_artifact_id is None):
            reasons.append("VERIFIER_VERDICT_IDENTITY_INCOMPLETE")
        if bundle.patch_artifact_id is not None and not bundle.command_evidence:
            reasons.append("COMMAND_EVIDENCE_MISSING")
        if (bundle.patch_artifact_id is None) != (bundle.patch_sha256 is None):
            reasons.append("PATCH_IDENTITY_INCOMPLETE")
        if bundle.patch_artifact_id is None and bundle.changed_paths:
            reasons.append("PATCH_IDENTITY_INCOMPLETE")
        if any(
            item.run_id != bundle.run_id or item.task_id != bundle.task_id
            for item in bundle.command_evidence
        ):
            reasons.append("COMMAND_EVIDENCE_IDENTITY_MISMATCH")
        if bundle.verification_command_hashes and any(
            (
                item.command_id not in bundle.verification_command_hashes
                or item.command_spec_sha256
                != bundle.verification_command_hashes.get(item.command_id)
            )
            and not _is_auxiliary_approval_evidence(bundle, item)
            for item in bundle.command_evidence
        ):
            reasons.append("COMMAND_SPEC_BINDING_INVALID")
        observed_command_ids = {item.command_id for item in bundle.command_evidence}
        if not required_command_ids.issubset(observed_command_ids):
            reasons.append("REQUIRED_COMMAND_EVIDENCE_MISSING")
        if requires_independent_verifier and not required_command_ids.issubset(
            {item.command_id for item in verifier_commands}
        ):
            reasons.append("VERIFIER_REQUIRED_COMMAND_EVIDENCE_MISSING")
        if any(
            item.sandbox_provider != bundle.sandbox_provider
            or item.sandbox_security_level is not bundle.sandbox_security_level
            or item.sandbox_capabilities_sha256 != bundle.sandbox_capabilities_sha256
            or item.sandbox_configuration_sha256 != bundle.sandbox_configuration_sha256
            or item.sandbox_requirements_sha256 != bundle.sandbox_requirements_sha256
            or item.sandbox_image_identity != bundle.sandbox_image_identity
            or item.sandbox_daemon_identity != bundle.sandbox_daemon_identity
            for item in bundle.command_evidence
        ):
            reasons.append("SANDBOX_EVIDENCE_BINDING_INVALID")
        if any(
            item.sandbox_security_level is SandboxSecurityLevel.ISOLATED
            and (
                item.sandbox_inspection_artifact_id is None
                or item.sandbox_inspection_sha256 is None
            )
            for item in bundle.command_evidence
        ):
            reasons.append("SANDBOX_INSPECTION_EVIDENCE_MISSING")
        if any(
            item.sandbox_security_level is SandboxSecurityLevel.ISOLATED
            and item.execution_id is None
            for item in bundle.command_evidence
        ):
            reasons.append("EXECUTION_IDENTITY_MISSING")
        if any(
            item.network_mode not in bundle.sandbox_capabilities.supported_network_modes
            or item.network_mode != "none"
            for item in bundle.command_evidence
        ):
            reasons.append("COMMAND_NETWORK_EVIDENCE_INVALID")
        if any(item.exit_code != 0 or item.timed_out for item in bundle.command_evidence):
            reasons.append("COMMAND_EXECUTION_FAILED")
        if any(item.completed_at < item.started_at for item in bundle.command_evidence):
            reasons.append("COMMAND_TIMING_INVALID")
        if any(item.output_truncated for item in bundle.command_evidence):
            reasons.append("COMMAND_OUTPUT_TRUNCATED")
        if any(
            item.strength is EvidenceStrength.SIMULATED
            or item.sandbox_security_level is SandboxSecurityLevel.FAKE
            for item in bundle.command_evidence
        ):
            reasons.append("SIMULATED_EVIDENCE_ONLY")
        if any(
            item.sandbox_security_level is SandboxSecurityLevel.FAKE
            and item.strength is not EvidenceStrength.SIMULATED
            for item in bundle.command_evidence
        ):
            reasons.append("EVIDENCE_STRENGTH_INVALID")
        if any(
            item.strength is EvidenceStrength.INDEPENDENTLY_VERIFIED
            and (
                item.agent_instance_id != bundle.verifier_agent_instance_id
                or item.principal_role != "verifier"
                or item.workflow_stage is not WorkflowStage.VERIFYING
                or item.workspace_id is None
                or item.sandbox_id is None
                or item.sandbox_security_level is not SandboxSecurityLevel.ISOLATED
                or item.workspace_kind is not WorkspaceKind.VERIFICATION
                or item.workspace_mutated_during_execution
            )
            for item in bundle.command_evidence
        ):
            reasons.append("EVIDENCE_STRENGTH_INVALID")
        if any(item.workspace_mutated_during_execution for item in verifier_commands):
            reasons.append("VERIFIER_COMMAND_MUTATED_WORKSPACE")
        if any(
            item.principal_role != "verifier"
            or item.workflow_stage is not WorkflowStage.VERIFYING
            or item.workspace_id is None
            or item.sandbox_id is None
            for item in verifier_commands
        ):
            reasons.append("VERIFIER_PROVENANCE_INVALID")
        if requires_independent_verifier and any(
            item.strength is not EvidenceStrength.INDEPENDENTLY_VERIFIED
            or item.sandbox_security_level is not SandboxSecurityLevel.ISOLATED
            or item.workspace_kind is not WorkspaceKind.VERIFICATION
            or item.workspace_mutated_during_execution
            for item in verifier_commands
        ):
            reasons.append("VERIFIER_EVIDENCE_STRENGTH_INSUFFICIENT")
        if any(
            item.config_snapshot_sha256 != bundle.config_snapshot_sha256
            for item in bundle.command_evidence
        ):
            reasons.append("CONFIG_EVIDENCE_STALE")
        if any(
            item.workspace_base_revision != bundle.base_revision for item in bundle.command_evidence
        ):
            reasons.append("BASE_REVISION_EVIDENCE_STALE")
        if bundle.patch_sha256 is not None and not any(
            item.candidate_patch_sha256 == bundle.patch_sha256 for item in bundle.command_evidence
        ):
            reasons.append("PATCH_EVIDENCE_UNBOUND")
        if (
            requires_independent_verifier
            and bundle.patch_sha256 is not None
            and (
                not verifier_commands
                or any(
                    item.candidate_patch_sha256 != bundle.patch_sha256 for item in verifier_commands
                )
            )
        ):
            reasons.append("VERIFIER_PATCH_EVIDENCE_UNBOUND")
        verified = not reasons and bundle.reported_verdict in {None, Verdict.PASS}
        command_failed = any(
            item.exit_code != 0 or item.timed_out for item in bundle.command_evidence
        )
        if (
            bundle.reported_verdict is Verdict.FAIL
            or command_failed
            or any(item.verdict is Verdict.FAIL for item in bundle.criterion_assessments)
        ):
            effective = Verdict.FAIL
        elif verified:
            effective = Verdict.PASS
        else:
            effective = Verdict.INCONCLUSIVE
        return CompletionDecision(
            verified_complete=verified,
            effective_verdict=effective,
            reason_codes=sorted(set(reasons)),
        )


def _is_auxiliary_approval_evidence(
    bundle: EvidenceBundle,
    item: CommandEvidence,
) -> bool:
    return (
        bundle.sandbox_provider == "fake"
        and item.command_id == "approval-proof"
        and item.strength is EvidenceStrength.SIMULATED
    )
