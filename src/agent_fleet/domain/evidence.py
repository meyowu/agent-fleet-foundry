"""Structured evidence and deterministic completion assurance."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field, field_validator

from agent_fleet.domain.fleet_plan import FleetStrategy
from agent_fleet.domain.models import (
    AgentInstanceId,
    ArtifactId,
    CriterionId,
    EvidenceRequirementId,
    ProjectId,
    RunId,
    SandboxSecurityLevel,
    Sha256,
    StrictModel,
    TaskId,
    Verdict,
    _require_utc,
)


class EvidenceStrength(StrEnum):
    SIMULATED = "simulated"
    OBSERVED = "observed"
    INDEPENDENTLY_VERIFIED = "independently_verified"


class CommandEvidence(StrictModel):
    evidence_id: ArtifactId
    run_id: RunId
    task_id: TaskId
    agent_instance_id: AgentInstanceId
    executable: str
    argv: list[str]
    cwd: str
    sandbox_provider: str
    sandbox_security_level: SandboxSecurityLevel
    strength: EvidenceStrength
    exit_code: int
    timed_out: bool
    output_truncated: bool
    transcript_artifact_id: ArtifactId
    workspace_base_revision: str
    config_snapshot_sha256: Sha256
    candidate_patch_sha256: Sha256 | None = None
    started_at: datetime
    completed_at: datetime

    _started_utc = field_validator("started_at")(_require_utc)
    _completed_utc = field_validator("completed_at")(_require_utc)


class CriterionAssessment(StrictModel):
    criterion_id: CriterionId
    verdict: Verdict
    evidence_artifact_ids: list[ArtifactId] = Field(default_factory=list)
    explanation: str


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
    criterion_assessments: list[CriterionAssessment] = Field(min_length=1, max_length=128)
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
        if len(command_artifact_ids) != len(set(command_artifact_ids)):
            reasons.append("COMMAND_EVIDENCE_DUPLICATE")
        declared_artifact_ids = {
            bundle.config_snapshot_artifact_id,
            bundle.task_spec_artifact_id,
            bundle.fleet_plan_artifact_id,
            *(item.evidence_id for item in bundle.command_evidence),
            *(item.transcript_artifact_id for item in bundle.command_evidence),
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
            and item.agent_instance_id != bundle.verifier_agent_instance_id
            for item in bundle.command_evidence
        ):
            reasons.append("EVIDENCE_STRENGTH_INVALID")
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
        if bundle.reported_verdict is Verdict.FAIL or command_failed:
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
