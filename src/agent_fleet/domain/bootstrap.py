"""Evidence-bound repository bootstrap contracts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field, field_validator, model_validator

from agent_fleet.domain.evidence import CompletionDecision
from agent_fleet.domain.models import (
    ArtifactId,
    ArtifactKind,
    FrozenStrictModel,
    ProjectId,
    RunId,
    RunStatus,
    RuntimeConfiguration,
    SandboxCapabilities,
    SandboxConfiguration,
    SandboxPreflight,
    SandboxRequirements,
    SandboxSecurityLevel,
    Sha256,
    TaskId,
    _require_utc,
)
from agent_fleet.domain.security import canonical_json_hash


class BootstrapPolicyMode(StrEnum):
    VERIFIED = "verified"
    DEGRADED_SIMULATION = "degraded_simulation"
    UNSAFE_HOST_DEVELOPMENT = "unsafe_host_development"


class ArtifactReference(FrozenStrictModel):
    artifact_id: ArtifactId
    kind: ArtifactKind
    sha256: Sha256


class BootstrapReport(FrozenStrictModel):
    api_version: Literal["agentfleet.dev/v1alpha1"] = "agentfleet.dev/v1alpha1"
    kind: Literal["BootstrapReport"] = "BootstrapReport"
    target_identity_hash: Sha256
    target_head_revision: str
    target_status_fingerprint: Sha256
    target_runtime_configuration: RuntimeConfiguration
    target_runtime_configuration_sha256: Sha256
    proposal_sha256: Sha256
    proposal: ArtifactReference
    repository_profile: ArtifactReference
    repository_profile_semantic_sha256: Sha256
    project_knowledge: ArtifactReference
    project_knowledge_semantic_sha256: Sha256
    config_snapshot: ArtifactReference
    sandbox_configuration: SandboxConfiguration
    sandbox_configuration_sha256: Sha256
    sandbox_capabilities: SandboxCapabilities
    sandbox_capabilities_sha256: Sha256
    sandbox_requirements: SandboxRequirements
    sandbox_requirements_sha256: Sha256
    sandbox_preflight: SandboxPreflight
    sandbox_preflight_sha256: Sha256
    canary_project_id: ProjectId
    canary_run_id: RunId
    canary_task_id: TaskId
    canary_status: RunStatus
    task_spec: ArtifactReference
    fleet_plan: ArtifactReference
    patch: ArtifactReference
    command_evidence: list[ArtifactReference] = Field(min_length=1, max_length=64)
    command_transcripts: list[ArtifactReference] = Field(min_length=1, max_length=64)
    sandbox_inspections: list[ArtifactReference] = Field(default_factory=list, max_length=64)
    verifier_verdict: ArtifactReference
    evidence_bundle: ArtifactReference
    cleanup_receipt: ArtifactReference
    completion_decision: CompletionDecision
    cleanup_complete: bool
    outstanding_lease_count: int = Field(ge=0, le=1024)
    policy_mode: BootstrapPolicyMode
    publish_allowed: bool
    remaining_risks: list[str] = Field(default_factory=list, max_length=64)
    proof_gaps: list[str] = Field(default_factory=list, max_length=64)
    created_at: datetime
    completed_at: datetime

    _created_utc = field_validator("created_at")(_require_utc)
    _completed_utc = field_validator("completed_at")(_require_utc)

    @field_validator("command_evidence", "command_transcripts", "sandbox_inspections")
    @classmethod
    def validate_unique_artifacts(cls, values: list[ArtifactReference]) -> list[ArtifactReference]:
        identifiers = [item.artifact_id for item in values]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("BootstrapReport artifact references must be unique")
        return values

    @model_validator(mode="after")
    def validate_bindings_and_policy(self) -> BootstrapReport:
        configuration_hash = canonical_json_hash(self.sandbox_configuration.model_dump(mode="json"))
        capabilities_hash = canonical_json_hash(self.sandbox_capabilities.model_dump(mode="json"))
        requirements_hash = canonical_json_hash(self.sandbox_requirements.model_dump(mode="json"))
        runtime_hash = canonical_json_hash(
            self.target_runtime_configuration.model_dump(mode="json")
        )
        if configuration_hash != self.sandbox_configuration_sha256:
            raise ValueError("BootstrapReport sandbox configuration hash does not match")
        if capabilities_hash != self.sandbox_capabilities_sha256:
            raise ValueError("BootstrapReport sandbox capabilities hash does not match")
        if requirements_hash != self.sandbox_requirements_sha256:
            raise ValueError("BootstrapReport sandbox requirements hash does not match")
        if runtime_hash != self.target_runtime_configuration_sha256:
            raise ValueError("BootstrapReport target runtime hash does not match")
        if (
            self.sandbox_preflight.provider != self.sandbox_configuration.provider
            or self.sandbox_preflight.capabilities != self.sandbox_capabilities
            or self.sandbox_preflight.configuration_hash != configuration_hash
            or self.sandbox_preflight.requirements_hash != requirements_hash
            or canonical_json_hash(self.sandbox_preflight.model_dump(mode="json"))
            != self.sandbox_preflight_sha256
            or not self.sandbox_preflight.ready
        ):
            raise ValueError("BootstrapReport sandbox preflight binding does not match")
        expected_kinds = {
            "repository_profile": ArtifactKind.REPOSITORY_PROFILE,
            "project_knowledge": ArtifactKind.PROJECT_KNOWLEDGE,
            "proposal": ArtifactKind.FLEET_CONFIG_PROPOSAL,
            "config_snapshot": ArtifactKind.CONFIG_SNAPSHOT,
            "task_spec": ArtifactKind.TASK_SPEC,
            "fleet_plan": ArtifactKind.FLEET_PLAN,
            "patch": ArtifactKind.PATCH,
            "verifier_verdict": ArtifactKind.VERIFIER_VERDICT,
            "evidence_bundle": ArtifactKind.EVIDENCE_BUNDLE,
            "cleanup_receipt": ArtifactKind.RESOURCE_CLEANUP,
        }
        for field_name, expected_kind in expected_kinds.items():
            if getattr(self, field_name).kind is not expected_kind:
                raise ValueError(f"BootstrapReport {field_name} kind does not match")
        if any(item.kind is not ArtifactKind.COMMAND_EVIDENCE for item in self.command_evidence):
            raise ValueError("BootstrapReport command evidence kind does not match")
        if any(
            item.kind is not ArtifactKind.COMMAND_TRANSCRIPT for item in self.command_transcripts
        ):
            raise ValueError("BootstrapReport command transcript kind does not match")
        if any(
            item.kind is not ArtifactKind.SANDBOX_INSPECTION for item in self.sandbox_inspections
        ):
            raise ValueError("BootstrapReport inspection artifact kind does not match")
        if self.canary_status is not RunStatus.READY_FOR_REVIEW:
            raise ValueError("BootstrapReport canary must be ready for review")
        clean = self.cleanup_complete and self.outstanding_lease_count == 0
        expected_publish = (
            clean
            and self.sandbox_configuration.provider == "docker"
            and self.sandbox_capabilities.security_level is SandboxSecurityLevel.ISOLATED
            and self.sandbox_preflight.image_identity is not None
            and self.completion_decision.verified_complete
            and not self.proof_gaps
        )
        if self.publish_allowed != expected_publish:
            raise ValueError("BootstrapReport publication policy does not match its evidence")
        if self.policy_mode is BootstrapPolicyMode.VERIFIED:
            if (
                self.sandbox_configuration.provider != "docker"
                or self.sandbox_capabilities.security_level is not SandboxSecurityLevel.ISOLATED
            ):
                raise ValueError("verified bootstrap policy requires an isolated Docker sandbox")
        elif self.policy_mode is BootstrapPolicyMode.DEGRADED_SIMULATION:
            if (
                self.sandbox_configuration.provider != "fake"
                or self.completion_decision.verified_complete
                or not self.proof_gaps
                or self.publish_allowed
            ):
                raise ValueError("degraded simulation policy must expose an execution proof gap")
        else:
            if (
                self.sandbox_configuration.provider != "local-unsafe"
                or self.completion_decision.verified_complete
                or not self.remaining_risks
                or self.publish_allowed
            ):
                raise ValueError("unsafe-host bootstrap policy must expose remaining risk")
        return self
