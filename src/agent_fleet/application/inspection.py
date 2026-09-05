"""Read-only run inspection use cases."""

from __future__ import annotations

from agent_fleet.application.artifacts import ArtifactService
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.evidence import EvidenceBundle
from agent_fleet.domain.models import ApprovalStatus, ArtifactKind, Run, RunStatus
from agent_fleet.domain.security import canonical_json_hash
from agent_fleet.ports.graph import GraphStore
from agent_fleet.ports.runtime_accounting import RuntimeBudgetStore
from agent_fleet.ports.state_store import StateStore


class InspectionService:
    def __init__(
        self,
        state: StateStore,
        artifacts: ArtifactService,
        budgets: RuntimeBudgetStore | None = None,
        graphs: GraphStore | None = None,
    ) -> None:
        self.state = state
        self.artifacts = artifacts
        self.budgets = budgets
        self.graphs = graphs

    def status(self, run_id: str) -> dict[str, object]:
        run = self.state.get_run(run_id)
        graph = self.graphs.get(run_id) if self.graphs is not None else None
        pending_children: list[str] = []
        if graph is not None:
            for node in graph.nodes:
                child = self.state.get_run(node.binding.child_run_id)
                request_id = child.pending_approval_id
                if request_id is not None and (
                    child.status is RunStatus.PAUSED_FOR_APPROVAL
                    and self.state.get_approval(request_id).status is ApprovalStatus.PENDING
                ):
                    pending_children.append(request_id)
        return {
            "run_id": run.run_id,
            "project_id": run.project_id,
            "status": run.status.value,
            "stage": run.stage.value if run.stage else None,
            "repair_iterations": run.repair_iterations,
            "pending_approval_id": run.pending_approval_id,
            "pending_child_approval_ids": pending_children,
            "parent_run_id": run.parent_run_id,
            "parent_node_id": run.parent_node_id,
            "graph": graph.model_dump(mode="json") if graph is not None else None,
            "patch_artifact_id": run.patch_artifact_id,
            "patch_sha256": run.patch_sha256,
            "config_snapshot_artifact_id": run.config_snapshot_artifact_id,
            "config_snapshot_sha256": run.config_snapshot_hash,
            "task_spec_artifact_id": run.task_spec_artifact_id,
            "task_spec_sha256": run.task_spec_hash,
            "fleet_plan_artifact_id": run.fleet_plan_artifact_id,
            "fleet_plan_sha256": run.fleet_plan_hash,
            "fleet_strategy": run.fleet_strategy,
            "command_evidence_artifact_ids": run.command_evidence_artifact_ids,
            "verifier_verdict_artifact_id": run.verifier_verdict_artifact_id,
            "evidence_bundle_artifact_id": run.evidence_bundle_artifact_id,
            "evidence_bundle_sha256": run.evidence_bundle_hash,
            "assurance_verdict": run.assurance_verdict.value if run.assurance_verdict else None,
            "verified_complete": run.verified_complete,
            "verifier_workspace_mutated": run.verifier_workspace_mutated,
            "evidence": self._evidence_summary(run),
            "runtime": run.runtime_name,
            "provider_model": run.provider_model,
            "runtime_usage_artifact_ids": run.runtime_usage_artifact_ids,
            "runtime_budget": (
                self.budgets.snapshot(run_id).model_dump(mode="json")
                if self.budgets is not None
                else None
            ),
            "sandbox": run.sandbox_name,
            "security_level": (
                run.sandbox_capabilities_snapshot.security_level.value
                if run.sandbox_capabilities_snapshot is not None
                else "unknown"
            ),
            "sandbox_configuration_sha256": run.sandbox_configuration_hash,
            "sandbox_capabilities_sha256": run.sandbox_capabilities_hash,
        }

    def _evidence_summary(self, run: Run) -> dict[str, object] | None:
        if run.evidence_bundle_artifact_id is None:
            if (
                run.evidence_bundle_hash is not None
                or run.verified_complete
                or run.assurance_verdict is not None
            ):
                raise _integrity_error(
                    "Run has assurance claims without an evidence bundle binding."
                )
            return None
        if run.evidence_bundle_hash is None or run.task_id is None:
            raise _integrity_error("Run has an incomplete evidence bundle binding.")
        try:
            metadata = self.state.get_artifact(run.evidence_bundle_artifact_id)
        except FleetError as error:
            raise _integrity_error("Run evidence bundle artifact is missing.") from error
        if (
            metadata.kind is not ArtifactKind.EVIDENCE_BUNDLE
            or metadata.project_id != run.project_id
            or metadata.run_id != run.run_id
            or metadata.task_id != run.task_id
            or metadata.sha256 != run.evidence_bundle_hash
        ):
            raise _integrity_error("Run evidence bundle metadata is not authoritatively bound.")
        try:
            bundle = EvidenceBundle.model_validate_json(
                self.artifacts.read_text(run.evidence_bundle_artifact_id)
            )
        except ValueError as error:
            raise _integrity_error("Run evidence bundle content is invalid.") from error
        decision = bundle.completion_decision
        if (
            bundle.run_id != run.run_id
            or bundle.project_id != run.project_id
            or bundle.task_id != run.task_id
            or bundle.base_revision != run.base_revision
            or bundle.config_snapshot_artifact_id != run.config_snapshot_artifact_id
            or bundle.config_snapshot_sha256 != run.config_snapshot_hash
            or bundle.task_spec_artifact_id != run.task_spec_artifact_id
            or bundle.task_spec_sha256 != run.task_spec_hash
            or bundle.fleet_plan_artifact_id != run.fleet_plan_artifact_id
            or bundle.fleet_plan_sha256 != run.fleet_plan_hash
            or bundle.fleet_strategy.value != run.fleet_strategy
            or bundle.sandbox_provider != run.sandbox_name
            or (
                run.sandbox_capabilities_snapshot is None
                or bundle.sandbox_security_level
                is not run.sandbox_capabilities_snapshot.security_level
                or bundle.sandbox_capabilities != run.sandbox_capabilities_snapshot
                or bundle.sandbox_capabilities_sha256 != run.sandbox_capabilities_hash
                or bundle.sandbox_capabilities_sha256
                != canonical_json_hash(bundle.sandbox_capabilities.model_dump(mode="json"))
            )
            or bundle.sandbox_configuration_sha256 != run.sandbox_configuration_hash
            or bundle.patch_artifact_id != run.patch_artifact_id
            or bundle.patch_sha256 != run.patch_sha256
            or [item.evidence_id for item in bundle.command_evidence]
            != run.command_evidence_artifact_ids
            or bundle.verifier_agent_instance_id != run.verifier_agent_instance_id
            or bundle.verifier_verdict_artifact_id != run.verifier_verdict_artifact_id
            or bundle.verifier_workspace_mutated != run.verifier_workspace_mutated
            or decision is None
            or decision.verified_complete != run.verified_complete
            or decision.effective_verdict != run.assurance_verdict
        ):
            raise _integrity_error("Run state and evidence bundle conclusions do not match.")
        return {
            "changed_paths": bundle.changed_paths,
            "reported_verdict": (
                bundle.reported_verdict.value if bundle.reported_verdict is not None else None
            ),
            "effective_verdict": decision.effective_verdict.value,
            "verified_complete": decision.verified_complete,
            "completion_reason_codes": decision.reason_codes,
            "criterion_assessments": [
                item.model_dump(mode="json") for item in bundle.criterion_assessments
            ],
            "command_results": [
                {
                    "evidence_artifact_id": item.evidence_id,
                    "agent_instance_id": item.agent_instance_id,
                    "executable": item.executable,
                    "argv": item.argv,
                    "cwd": item.cwd,
                    "exit_code": item.exit_code,
                    "timed_out": item.timed_out,
                    "output_truncated": item.output_truncated,
                    "transcript_artifact_id": item.transcript_artifact_id,
                    "workspace_base_revision": item.workspace_base_revision,
                    "config_snapshot_sha256": item.config_snapshot_sha256,
                    "strength": item.strength.value,
                    "sandbox_provider": item.sandbox_provider,
                    "sandbox_security_level": item.sandbox_security_level.value,
                    "sandbox_capabilities_sha256": item.sandbox_capabilities_sha256,
                    "sandbox_configuration_sha256": item.sandbox_configuration_sha256,
                    "command_id": item.command_id,
                    "command_spec_sha256": item.command_spec_sha256,
                    "workspace_kind": item.workspace_kind.value,
                    "network_mode": item.network_mode,
                    "execution_id": item.execution_id,
                    "sandbox_inspection_artifact_id": item.sandbox_inspection_artifact_id,
                    "sandbox_inspection_sha256": item.sandbox_inspection_sha256,
                    "workspace_mutated_during_execution": (item.workspace_mutated_during_execution),
                    "candidate_patch_sha256": item.candidate_patch_sha256,
                }
                for item in bundle.command_evidence
            ],
            "proof_gaps": [item.model_dump(mode="json") for item in bundle.proof_gaps],
            "remaining_risks": [item.model_dump(mode="json") for item in bundle.remaining_risks],
            "verifier_required_repairs": bundle.verifier_required_repairs,
            "verifier_regressions": bundle.verifier_regressions,
        }

    def logs(self, run_id: str) -> list[dict[str, object]]:
        return [event.model_dump(mode="json") for event in self.state.list_events(run_id)]

    def artifacts_for_run(self, run_id: str) -> list[dict[str, object]]:
        self.state.get_run(run_id)
        return [artifact.model_dump(mode="json") for artifact in self.state.list_artifacts(run_id)]


def _integrity_error(message: str) -> FleetError:
    return FleetError(
        ErrorCode.ARTIFACT_INTEGRITY_FAILED,
        message,
        "Do not rely on this status result; inspect local state and rerun the task.",
    )
