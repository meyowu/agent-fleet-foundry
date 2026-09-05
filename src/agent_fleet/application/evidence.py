"""Assemble authoritative run evidence and compute its assurance boundary."""

from __future__ import annotations

from datetime import datetime
from typing import cast

from agent_fleet.application.artifacts import ArtifactService
from agent_fleet.domain.config import ConfigSnapshot
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.evidence import (
    CleanupLeaseRecord,
    CommandEvidence,
    CompletionGate,
    CriterionAssessment,
    EvidenceBundle,
    EvidenceStrength,
    ProofGap,
    RemainingRisk,
    ResourceCleanupReceipt,
)
from agent_fleet.domain.fleet_plan import FleetPlan, FleetStrategy
from agent_fleet.domain.models import (
    ArtifactKind,
    ArtifactMetadata,
    Run,
    SandboxInspection,
    TaskSpec,
    Verdict,
    VerifierVerdict,
)
from agent_fleet.domain.security import canonical_json_hash, sha256_bytes
from agent_fleet.ports.clock import Clock
from agent_fleet.ports.state_store import StateStore


class EvidenceAssembler:
    def __init__(
        self,
        state: StateStore,
        artifacts: ArtifactService,
        clock: Clock,
    ) -> None:
        self.state = state
        self.artifacts = artifacts
        self.clock = clock

    def assemble(
        self,
        run: Run,
        task: TaskSpec,
        *,
        assembled_at: datetime | None = None,
    ) -> EvidenceBundle:
        if run.config_snapshot_artifact_id is None or run.config_snapshot_hash is None:
            raise _integrity_error("Run has no content-addressed configuration snapshot binding.")
        config_metadata, config_content = self._read_bound_artifact(
            run.config_snapshot_artifact_id,
            ArtifactKind.CONFIG_SNAPSHOT,
            run,
            task,
        )
        if (
            config_metadata.sha256 != run.config_snapshot_hash
            or sha256_bytes(config_content.encode("utf-8")) != run.config_snapshot_hash
            or task.config_snapshot_hash != run.config_snapshot_hash
        ):
            raise _integrity_error("Configuration snapshot hash is not bound to the task and run.")
        try:
            ConfigSnapshot.model_validate_json(config_content)
        except ValueError as error:
            raise _integrity_error("Configuration snapshot artifact is invalid.") from error
        if run.task_spec_artifact_id is None or run.task_spec_hash is None:
            raise _integrity_error("Run has no content-addressed TaskSpec binding.")
        task_metadata, task_content = self._read_bound_artifact(
            run.task_spec_artifact_id,
            ArtifactKind.TASK_SPEC,
            run,
            task,
        )
        if (
            task_metadata.sha256 != run.task_spec_hash
            or sha256_bytes(task_content.encode("utf-8")) != run.task_spec_hash
        ):
            raise _integrity_error("TaskSpec content hash is not bound to the run record.")
        try:
            artifact_task = TaskSpec.model_validate_json(task_content)
        except ValueError as error:
            raise _integrity_error("TaskSpec artifact does not match its schema.") from error
        if artifact_task != task:
            raise _integrity_error(
                "TaskSpec artifact content does not match the persisted task record."
            )
        if run.fleet_plan_artifact_id is None or run.fleet_plan_hash is None:
            raise RuntimeError("run has no persisted FleetPlan")
        plan_metadata, plan_content = self._read_bound_artifact(
            run.fleet_plan_artifact_id,
            ArtifactKind.FLEET_PLAN,
            run,
            task,
        )
        if plan_metadata.sha256 != run.fleet_plan_hash:
            raise _integrity_error("FleetPlan hash is not bound to the run record.")
        try:
            plan = FleetPlan.model_validate_json(plan_content)
        except ValueError as error:
            raise _integrity_error("FleetPlan artifact does not match its schema.") from error
        if plan.run_id != run.run_id or plan.task_id != task.task_id:
            raise _integrity_error("FleetPlan identity does not match the current run and task.")

        cleanup_complete = False
        if run.cleanup_receipt_artifact_id is not None:
            if run.cleanup_receipt_sha256 is None:
                raise _integrity_error("Run cleanup receipt hash is missing.")
            cleanup_metadata, cleanup_content = self._read_bound_artifact(
                run.cleanup_receipt_artifact_id,
                ArtifactKind.RESOURCE_CLEANUP,
                run,
                task,
            )
            if cleanup_metadata.sha256 != run.cleanup_receipt_sha256:
                raise _integrity_error("Run cleanup receipt hash does not match its artifact.")
            try:
                cleanup_receipt = ResourceCleanupReceipt.model_validate_json(cleanup_content)
            except ValueError as error:
                raise _integrity_error("Resource cleanup receipt is invalid.") from error
            current_records = [
                CleanupLeaseRecord(
                    lease_id=lease.lease_id,
                    kind=lease.kind,
                    resource_id=lease.resource_id,
                    status=lease.status,
                )
                for lease in self.state.list_leases(run.run_id)
            ]
            if (
                cleanup_receipt.run_id != run.run_id
                or cleanup_receipt.leases != current_records
                or self.state.outstanding_leases(run.run_id)
                or not cleanup_receipt.complete
            ):
                raise _integrity_error(
                    "Resource cleanup receipt does not match current terminal leases."
                )
            cleanup_complete = True

        capabilities = run.sandbox_capabilities_snapshot
        requirements = run.sandbox_requirements
        if capabilities is None or run.sandbox_capabilities_hash is None or requirements is None:
            raise _integrity_error("Run has no immutable sandbox capability binding.")
        if (
            canonical_json_hash(capabilities.model_dump(mode="json"))
            != run.sandbox_capabilities_hash
        ):
            raise _integrity_error("Run sandbox capability hash does not match its content.")
        command_hashes = {
            command.command_id: canonical_json_hash(command.model_dump(mode="json"))
            for command in task.verification_commands
        }
        command_evidence: list[CommandEvidence] = []
        for artifact_id in run.command_evidence_artifact_ids:
            _, content = self._read_bound_artifact(
                artifact_id,
                ArtifactKind.COMMAND_EVIDENCE,
                run,
                task,
            )
            try:
                command = CommandEvidence.model_validate_json(content)
            except ValueError as error:
                raise _integrity_error("CommandEvidence artifact is invalid.") from error
            if (
                command.evidence_id != artifact_id
                or command.run_id != run.run_id
                or command.task_id != task.task_id
            ):
                raise _integrity_error(
                    "CommandEvidence identity does not match its artifact, run, and task."
                )
            self._read_bound_artifact(
                command.transcript_artifact_id,
                ArtifactKind.COMMAND_TRANSCRIPT,
                run,
                task,
            )
            if (
                command.sandbox_inspection_artifact_id is None
                or command.sandbox_inspection_sha256 is None
            ):
                raise _integrity_error("CommandEvidence has no sandbox inspection binding.")
            inspection_metadata, inspection_content = self._read_bound_artifact(
                command.sandbox_inspection_artifact_id,
                ArtifactKind.SANDBOX_INSPECTION,
                run,
                task,
            )
            try:
                inspection = SandboxInspection.model_validate_json(inspection_content)
            except ValueError as error:
                raise _integrity_error("SandboxInspection artifact is invalid.") from error
            if (
                inspection_metadata.sha256 != command.sandbox_inspection_sha256
                or inspection.sandbox_id != command.sandbox_id
                or inspection.provider != command.sandbox_provider
                or inspection.capabilities != capabilities
                or inspection.configuration_hash != run.sandbox_configuration_hash
                or inspection.image_identity != run.sandbox_image_identity
                or inspection.daemon_identity != run.sandbox_daemon_identity
                or command.sandbox_daemon_identity != run.sandbox_daemon_identity
                or inspection.effective_network_mode != command.network_mode
                or not inspection.ready
                or inspection.missing_requirements(requirements)
            ):
                raise _integrity_error(
                    "SandboxInspection does not match its command and immutable Run binding."
                )
            if (
                run.sandbox_name == "fake"
                and command.command_id == "approval-proof"
                and command.strength is EvidenceStrength.SIMULATED
            ):
                # The Phase 1 approval probe is audit evidence for a one-use logical
                # side effect, not verification evidence for a TaskSpec criterion.
                command_evidence.append(command)
                continue
            expected_command_hash = command_hashes.get(command.command_id)
            if command_hashes and (
                expected_command_hash is None
                or command.command_spec_sha256 != expected_command_hash
            ):
                raise _integrity_error(
                    "CommandEvidence is not bound to a reviewed TaskSpec command."
                )
            if task.verification_commands and (
                command.sandbox_provider != run.sandbox_name
                or command.sandbox_security_level is not capabilities.security_level
                or command.sandbox_capabilities_sha256 != run.sandbox_capabilities_hash
                or command.sandbox_configuration_sha256 != run.sandbox_configuration_hash
                or command.sandbox_requirements_sha256
                != canonical_json_hash(requirements.model_dump(mode="json"))
            ):
                raise _integrity_error(
                    "CommandEvidence sandbox identity does not match the immutable Run."
                )
            command_evidence.append(command)

        reported_verdict: Verdict | None = None
        verifier_verdict: VerifierVerdict | None = None
        verifier_evidence_artifact_ids: list[str] = []
        if run.verifier_verdict_artifact_id is not None:
            _, content = self._read_bound_artifact(
                run.verifier_verdict_artifact_id,
                ArtifactKind.VERIFIER_VERDICT,
                run,
                task,
            )
            try:
                verifier_verdict = VerifierVerdict.model_validate_json(content)
            except ValueError as error:
                raise _integrity_error("VerifierVerdict artifact is invalid.") from error
            reported_verdict = verifier_verdict.verdict
            verifier_evidence_artifact_ids = verifier_verdict.evidence_artifact_ids

        changed_paths: list[str] = []
        if run.patch_artifact_id is not None:
            patch_metadata, _ = self._read_bound_artifact(
                run.patch_artifact_id,
                ArtifactKind.PATCH,
                run,
                task,
            )
            if run.patch_sha256 != patch_metadata.sha256:
                raise _integrity_error("Patch hash is not bound to the patch artifact.")
            encoded_paths = patch_metadata.metadata.get("changed_paths", [])
            if isinstance(encoded_paths, list) and all(
                isinstance(path, str) for path in encoded_paths
            ):
                changed_paths = sorted(set(cast(list[str], encoded_paths)))
            elif isinstance(encoded_paths, str):
                # Backward compatibility for Phase 1 artifacts, which used a comma-delimited
                # field before metadata supported native JSON arrays.
                changed_paths = sorted(path for path in encoded_paths.split(",") if path)
            else:
                raise _integrity_error("Patch changed-path metadata is malformed.")
            if not changed_paths or any(path not in task.allowed_paths for path in changed_paths):
                raise _integrity_error(
                    "Patch changed-path metadata is empty or outside the TaskSpec scope."
                )

        evidence_ids = list(run.command_evidence_artifact_ids)
        if run.verifier_verdict_artifact_id is not None:
            evidence_ids.append(run.verifier_verdict_artifact_id)
        criterion_verdict = self._criterion_verdict(
            reported_verdict,
            command_evidence,
            criterion_count=len(task.acceptance_criteria),
        )
        assessments = [
            CriterionAssessment(
                criterion_id=criterion.criterion_id,
                verdict=criterion_verdict,
                evidence_artifact_ids=evidence_ids,
                explanation=self._criterion_explanation(criterion_verdict),
            )
            for criterion in task.acceptance_criteria
        ]
        proof_gaps = self._proof_gaps(
            run,
            plan.strategy,
            command_evidence,
            verifier_proof_gaps=(verifier_verdict.proof_gaps if verifier_verdict else []),
        )
        if len(task.acceptance_criteria) > 1:
            proof_gaps.append(
                ProofGap(
                    code="STRUCTURED_CRITERION_MAPPING_UNAVAILABLE",
                    description=(
                        "The Phase 1 verifier contract does not bind evidence independently "
                        "to multiple acceptance criteria."
                    ),
                    required_strength=EvidenceStrength.INDEPENDENTLY_VERIFIED,
                )
            )
        bundle = EvidenceBundle(
            run_id=run.run_id,
            project_id=run.project_id,
            task_id=task.task_id,
            base_revision=run.base_revision,
            config_snapshot_artifact_id=run.config_snapshot_artifact_id,
            config_snapshot_sha256=task.config_snapshot_hash,
            task_spec_artifact_id=run.task_spec_artifact_id,
            task_spec_sha256=run.task_spec_hash,
            fleet_plan_artifact_id=run.fleet_plan_artifact_id,
            fleet_plan_sha256=run.fleet_plan_hash,
            fleet_strategy=plan.strategy,
            required_evidence=plan.required_evidence,
            sandbox_provider=run.sandbox_name,
            sandbox_security_level=capabilities.security_level,
            sandbox_configuration_sha256=run.sandbox_configuration_hash,
            sandbox_requirements=requirements,
            sandbox_requirements_sha256=canonical_json_hash(requirements.model_dump(mode="json")),
            sandbox_image_identity=run.sandbox_image_identity,
            sandbox_daemon_identity=run.sandbox_daemon_identity,
            sandbox_capabilities=capabilities,
            sandbox_capabilities_sha256=run.sandbox_capabilities_hash,
            verification_command_hashes=command_hashes,
            required_verification_command_ids=task.required_verification_command_ids,
            patch_artifact_id=run.patch_artifact_id,
            patch_sha256=run.patch_sha256,
            changed_paths=changed_paths,
            command_evidence=command_evidence,
            verifier_agent_instance_id=run.verifier_agent_instance_id,
            verifier_verdict_artifact_id=run.verifier_verdict_artifact_id,
            verifier_evidence_artifact_ids=verifier_evidence_artifact_ids,
            verifier_workspace_mutated=run.verifier_workspace_mutated,
            reported_verdict=reported_verdict,
            verifier_required_repairs=(
                verifier_verdict.required_repairs if verifier_verdict else []
            ),
            verifier_regressions=(verifier_verdict.regressions if verifier_verdict else []),
            cleanup_receipt_artifact_id=run.cleanup_receipt_artifact_id,
            cleanup_receipt_sha256=run.cleanup_receipt_sha256,
            cleanup_complete=cleanup_complete,
            criterion_assessments=assessments,
            remaining_risks=self._remaining_risks(run),
            proof_gaps=proof_gaps,
            assembled_at=assembled_at or self.clock.now(),
        )
        decision = CompletionGate.evaluate(
            bundle,
            expected_criteria={item.criterion_id for item in task.acceptance_criteria},
            authoritative_artifact_ids={
                artifact.artifact_id for artifact in self.state.list_artifacts(run.run_id)
            },
        )
        return bundle.model_copy(update={"completion_decision": decision})

    @staticmethod
    def _criterion_verdict(
        reported: Verdict | None,
        commands: list[CommandEvidence],
        *,
        criterion_count: int,
    ) -> Verdict:
        if reported is Verdict.FAIL or any(
            command.exit_code != 0 or command.timed_out for command in commands
        ):
            return Verdict.FAIL
        if criterion_count == 1 and reported is Verdict.PASS and commands:
            return Verdict.PASS
        return Verdict.INCONCLUSIVE

    @staticmethod
    def _criterion_explanation(verdict: Verdict) -> str:
        if verdict is Verdict.PASS:
            return (
                "Control-plane records agree with the reported verdict; "
                "strength is gated separately."
            )
        if verdict is Verdict.FAIL:
            return "A command record or verifier verdict reports failure."
        return "No authoritative executed evidence establishes this criterion."

    @staticmethod
    def _proof_gaps(
        run: Run,
        strategy: FleetStrategy,
        commands: list[CommandEvidence],
        *,
        verifier_proof_gaps: list[str],
    ) -> list[ProofGap]:
        gaps: list[ProofGap] = []
        gaps.extend(
            ProofGap(
                code="VERIFIER_REPORTED_PROOF_GAP",
                description=description,
                required_strength=EvidenceStrength.INDEPENDENTLY_VERIFIED,
            )
            for description in verifier_proof_gaps
        )
        if any(command.strength is EvidenceStrength.SIMULATED for command in commands):
            gaps.append(
                ProofGap(
                    code="SIMULATED_EXECUTION",
                    description=(
                        "The selected sandbox recorded simulated output and did not execute "
                        "the reviewed project command."
                    ),
                    required_strength=EvidenceStrength.OBSERVED,
                )
            )
        if run.patch_sha256 is not None and not any(
            command.candidate_patch_sha256 == run.patch_sha256 for command in commands
        ):
            gaps.append(
                ProofGap(
                    code="PATCH_EVIDENCE_UNBOUND",
                    description="No command evidence is bound to the final candidate patch hash.",
                    required_strength=EvidenceStrength.OBSERVED,
                )
            )
        if not commands:
            gaps.append(
                ProofGap(
                    code="NO_COMMAND_EVIDENCE",
                    description="No execution evidence exists for this offline run.",
                    required_strength=EvidenceStrength.OBSERVED,
                )
            )
        if strategy is FleetStrategy.SINGLE_ENGINEER:
            gaps.append(
                ProofGap(
                    code="NO_INDEPENDENT_VERIFIER",
                    description=(
                        "This topology intentionally did not create an independent Verifier."
                    ),
                    required_strength=EvidenceStrength.INDEPENDENTLY_VERIFIED,
                )
            )
        if run.verifier_workspace_mutated:
            gaps.append(
                ProofGap(
                    code="VERIFIER_WORKSPACE_MUTATED",
                    description=(
                        "The verifier workspace changed after canonical patch reconstruction; "
                        "verifier-generated changes are untrusted and discarded."
                    ),
                )
            )
        return gaps

    @staticmethod
    def _remaining_risks(run: Run) -> list[RemainingRisk]:
        if run.sandbox_name == "fake":
            return [
                RemainingRisk(
                    code="FAKE_SANDBOX_NO_ISOLATION",
                    description=(
                        "The fake provider neither executes code nor enforces OS isolation."
                    ),
                )
            ]
        if run.sandbox_name == "local-unsafe":
            return [
                RemainingRisk(
                    code="LOCAL_UNSAFE_HOST_EXECUTION",
                    description=(
                        "The explicitly selected local-unsafe provider executes directly on "
                        "the host without an isolation boundary."
                    ),
                )
            ]
        return [
            RemainingRisk(
                code="CONTAINER_NOT_VM_BOUNDARY",
                description=(
                    "Docker containers share the host kernel and are not a VM-strength boundary."
                ),
            ),
            RemainingRisk(
                code="WORKSPACE_DISK_QUOTA_NOT_PORTABLE",
                description=(
                    "Phase 3 does not claim a portable disk quota for the writable workspace bind."
                ),
            ),
            RemainingRisk(
                code="NETWORK_NONE_RETAINS_LOOPBACK",
                description=(
                    "Docker network=none removes external interfaces but retains "
                    "container loopback."
                ),
            ),
        ]

    def _read_bound_artifact(
        self,
        artifact_id: str,
        expected_kind: ArtifactKind,
        run: Run,
        task: TaskSpec,
    ) -> tuple[ArtifactMetadata, str]:
        try:
            metadata = self.state.get_artifact(artifact_id)
        except FleetError as error:
            raise _integrity_error(
                f"Required {expected_kind.value} artifact is missing: {artifact_id}."
            ) from error
        if (
            metadata.kind is not expected_kind
            or metadata.project_id != run.project_id
            or metadata.run_id != run.run_id
            or metadata.task_id != task.task_id
        ):
            raise _integrity_error(
                f"Artifact {artifact_id} is not a bound {expected_kind.value} record."
            )
        return metadata, self.artifacts.read_text(artifact_id)


def _integrity_error(message: str) -> FleetError:
    return FleetError(
        ErrorCode.ARTIFACT_INTEGRITY_FAILED,
        message,
        "Do not use this evidence bundle; inspect local artifacts and rerun the task.",
    )
