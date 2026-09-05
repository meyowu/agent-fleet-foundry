"""Generate deterministic JSON Schemas from canonical Pydantic models."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pydantic import BaseModel

from agent_fleet.domain.bootstrap import BootstrapReport
from agent_fleet.domain.budgets import (
    ModelRequestAccounting,
    ModelRequestReservation,
    RunBudgetLimits,
    RunBudgetSnapshot,
    RuntimeAttempt,
)
from agent_fleet.domain.config import ConfigSnapshot, FleetSpec, VerificationProfile
from agent_fleet.domain.evidence import (
    CommandEvidence,
    EvidenceBundle,
    GraphDeliveryEvidence,
    ResourceCleanupReceipt,
)
from agent_fleet.domain.fleet_patch import FleetPatch
from agent_fleet.domain.fleet_plan import FleetPlan
from agent_fleet.domain.graph import (
    GraphArtifactRef,
    GraphChildBinding,
    GraphChildSeed,
    GraphDriverClaim,
    GraphJoinCompletion,
    GraphJoinInput,
    GraphJoinPreparation,
    GraphNodeRecord,
    GraphSnapshot,
)
from agent_fleet.domain.models import (
    AgentExecutionCheckpoint,
    ApprovalRequest,
    CapabilityGrant,
    CommandSpec,
    CriterionResult,
    ImplementationReport,
    JsonEnvelope,
    PermissionDecision,
    SandboxCapabilities,
    SandboxCleanupResult,
    SandboxConfiguration,
    SandboxExecutionHandle,
    SandboxExecutionMetadata,
    SandboxExecutionRecoveryRequest,
    SandboxInspection,
    SandboxPreflight,
    SandboxRequirements,
    ScopeDecision,
    SpecialistReport,
    TaskSpec,
    ToolIntent,
    UsageRecord,
    VerificationCheckpoint,
    VerifierVerdict,
    WriterAssignment,
)
from agent_fleet.domain.repository_profile import ProjectKnowledge, RepositoryProfile
from agent_fleet.domain.trust import (
    ExactPermissionScope,
    ProjectTrustSettings,
    UserTrustPolicy,
    UserTrustRule,
)

SCHEMAS: dict[str, type[BaseModel]] = {
    "fleet.schema.json": FleetSpec,
    "verification-profile.schema.json": VerificationProfile,
    "config-snapshot.schema.json": ConfigSnapshot,
    "cli-envelope.schema.json": JsonEnvelope,
    "task-spec.schema.json": TaskSpec,
    "scope-decision.schema.json": ScopeDecision,
    "writer-assignment.schema.json": WriterAssignment,
    "specialist-report.schema.json": SpecialistReport,
    "implementation-report.schema.json": ImplementationReport,
    "usage-record.schema.json": UsageRecord,
    "run-budget-limits.schema.json": RunBudgetLimits,
    "run-budget-snapshot.schema.json": RunBudgetSnapshot,
    "runtime-attempt.schema.json": RuntimeAttempt,
    "model-request-reservation.schema.json": ModelRequestReservation,
    "model-request-accounting.schema.json": ModelRequestAccounting,
    "criterion-result.schema.json": CriterionResult,
    "tool-intent.schema.json": ToolIntent,
    "approval-request.schema.json": ApprovalRequest,
    "capability-grant.schema.json": CapabilityGrant,
    "permission-decision.schema.json": PermissionDecision,
    "verification-checkpoint.schema.json": VerificationCheckpoint,
    "agent-execution-checkpoint.schema.json": AgentExecutionCheckpoint,
    "exact-permission-scope.schema.json": ExactPermissionScope,
    "project-trust-settings.schema.json": ProjectTrustSettings,
    "user-trust-policy.schema.json": UserTrustPolicy,
    "user-trust-rule.schema.json": UserTrustRule,
    "verifier-verdict.schema.json": VerifierVerdict,
    "repository-profile.schema.json": RepositoryProfile,
    "project-knowledge.schema.json": ProjectKnowledge,
    "fleet-plan.schema.json": FleetPlan,
    "graph-snapshot.schema.json": GraphSnapshot,
    "graph-child-seed.schema.json": GraphChildSeed,
    "graph-child-binding.schema.json": GraphChildBinding,
    "graph-driver-claim.schema.json": GraphDriverClaim,
    "graph-artifact-ref.schema.json": GraphArtifactRef,
    "graph-node-record.schema.json": GraphNodeRecord,
    "graph-join-input.schema.json": GraphJoinInput,
    "graph-join-preparation.schema.json": GraphJoinPreparation,
    "graph-join-completion.schema.json": GraphJoinCompletion,
    "graph-delivery-evidence.schema.json": GraphDeliveryEvidence,
    "sandbox-capabilities.schema.json": SandboxCapabilities,
    "sandbox-configuration.schema.json": SandboxConfiguration,
    "sandbox-requirements.schema.json": SandboxRequirements,
    "sandbox-preflight.schema.json": SandboxPreflight,
    "sandbox-inspection.schema.json": SandboxInspection,
    "sandbox-execution-handle.schema.json": SandboxExecutionHandle,
    "sandbox-execution-metadata.schema.json": SandboxExecutionMetadata,
    "sandbox-execution-recovery-request.schema.json": SandboxExecutionRecoveryRequest,
    "sandbox-cleanup-result.schema.json": SandboxCleanupResult,
    "command-spec.schema.json": CommandSpec,
    "command-evidence.schema.json": CommandEvidence,
    "evidence-bundle.schema.json": EvidenceBundle,
    "resource-cleanup-receipt.schema.json": ResourceCleanupReceipt,
    "bootstrap-report.schema.json": BootstrapReport,
    "fleet-patch.schema.json": FleetPatch,
}


def rendered_schemas() -> dict[str, str]:
    return {
        name: json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n"
        for name, model in SCHEMAS.items()
    }


def generate(output: Path, *, check: bool) -> int:
    mismatches: list[str] = []
    for name, content in rendered_schemas().items():
        destination = output / name
        if check:
            if not destination.exists() or destination.read_text(encoding="utf-8") != content:
                mismatches.append(name)
        else:
            output.mkdir(parents=True, exist_ok=True)
            destination.write_text(content, encoding="utf-8")
    if mismatches:
        raise SystemExit(f"generated schemas differ: {', '.join(mismatches)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    return generate(args.output, check=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
