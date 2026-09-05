"""Explicit, resumable CoS -> Engineer -> Verifier Phase 1 workflow."""

from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from dataclasses import replace
from pathlib import Path
from typing import cast

from pydantic import JsonValue, ValidationError

from agent_fleet.application.artifacts import ArtifactService
from agent_fleet.application.conversation_results import conversation_result
from agent_fleet.application.evidence import EvidenceAssembler
from agent_fleet.application.evolution import OrganizationService
from agent_fleet.application.gateway import ToolGateway
from agent_fleet.application.graph import GraphCoordinator
from agent_fleet.application.graph_workflow import GraphWorkflowExecution
from agent_fleet.application.inspection import InspectionService
from agent_fleet.application.permission_policy import PermissionPolicyService
from agent_fleet.application.planning import FleetPlanner
from agent_fleet.application.proposal_tools import ProposalHashToolCatalog
from agent_fleet.application.resources import CancellationService, ResourceService
from agent_fleet.application.runtime import RuntimeRegistry
from agent_fleet.application.runtime_tools import GatewayRuntimeToolCatalog
from agent_fleet.application.sandboxes import (
    configuration_from_request,
    requirements_for_configuration,
)
from agent_fleet.domain.budgets import RunBudgetLimits, RuntimeAttemptStatus
from agent_fleet.domain.config import ConfigSnapshot, FleetSpec
from agent_fleet.domain.conversation import (
    ConversationClaim,
    ConversationSubmission,
    ConversationTurnStatus,
)
from agent_fleet.domain.errors import (
    ApprovalDeniedError,
    ApprovalRequiredError,
    ConversationOwnershipUnavailableError,
    ErrorCode,
    FleetError,
    GraphOwnershipUnavailableError,
)
from agent_fleet.domain.evidence import (
    CleanupLeaseRecord,
    EvidenceBundle,
    ResourceCleanupReceipt,
)
from agent_fleet.domain.evolution import FleetPatchProposalRecord
from agent_fleet.domain.fleet_patch import validate_fleet_patch
from agent_fleet.domain.fleet_plan import FleetPlan, FleetStrategy
from agent_fleet.domain.graph import GraphDriverClaim, GraphStatus
from agent_fleet.domain.ids import IdPrefix
from agent_fleet.domain.models import (
    AgentExecutionCheckpoint,
    AgentInstance,
    AgentInvocation,
    AgentInvocationResult,
    AgentRole,
    AgentStatus,
    ArtifactKind,
    CommandSpec,
    FakeScenario,
    FleetEvent,
    FleetPatch,
    ImplementationReport,
    LeaseKind,
    LeaseStatus,
    Run,
    RunStatus,
    RuntimeCapability,
    RuntimeConfiguration,
    RuntimeCredentialCheck,
    RuntimeToolExecutionRecord,
    SandboxSecurityLevel,
    SandboxSpec,
    ScopeDecision,
    SpecialistReport,
    TaskSpec,
    Verdict,
    VerificationCheckpoint,
    VerifierVerdict,
    WorkflowStage,
    WorkspaceKind,
)
from agent_fleet.domain.paths import path_is_within
from agent_fleet.domain.security import Redactor
from agent_fleet.ports.clock import Clock
from agent_fleet.ports.config import ConfigurationPort
from agent_fleet.ports.conversation import ConversationStore
from agent_fleet.ports.graph import GraphStore
from agent_fleet.ports.id_generator import IdGenerator
from agent_fleet.ports.repository import RepositoryPort
from agent_fleet.ports.runtime import (
    EMPTY_RUNTIME_TOOL_CATALOG,
    RuntimeAdapter,
    RuntimeInvocationServices,
)
from agent_fleet.ports.runtime_accounting import RuntimeAccounting, RuntimeBudgetStore
from agent_fleet.ports.sandbox import SandboxProvider
from agent_fleet.ports.state_store import StateStore

_MAX_ROLE_GUIDANCE_BYTES = 32_768
_MINIMUM_RUNTIME_CAPABILITIES = frozenset(
    {
        RuntimeCapability.STRUCTURED_OUTPUT,
        RuntimeCapability.TOOL_CALLING,
    }
)


class WorkflowEngine:
    def __init__(
        self,
        state: StateStore,
        repository: RepositoryPort,
        runtimes: RuntimeRegistry,
        sandbox: SandboxProvider,
        artifacts: ArtifactService,
        gateway: ToolGateway,
        resources: ResourceService,
        planner: FleetPlanner,
        evidence: EvidenceAssembler,
        config: ConfigurationPort,
        clock: Clock,
        ids: IdGenerator,
        redactor: Redactor,
        *,
        budgets: RuntimeBudgetStore,
        graphs: GraphStore,
        organization: OrganizationService,
        permission_policy: PermissionPolicyService | None = None,
        conversations: ConversationStore | None = None,
    ) -> None:
        self.state = state
        self.repository = repository
        self.runtimes = runtimes
        self.sandbox = sandbox
        self.artifacts = artifacts
        self.gateway = gateway
        self.resources = resources
        self.planner = planner
        self.evidence = evidence
        self.config = config
        self.clock = clock
        self.ids = ids
        self.budgets = budgets
        self.graphs = graphs
        self.organization = organization
        self.redactor = redactor
        self.permission_policy = permission_policy
        self.conversations = conversations
        self._conversation_claims: dict[str, ConversationClaim] = {}
        self.graph_execution = GraphWorkflowExecution(self)
        self.graph_coordinator = GraphCoordinator(graphs, state, self.graph_execution, clock)

    async def start(
        self,
        *,
        project_path: Path,
        goal: str,
        runtime_name: str | None,
        sandbox_name: str | None,
        fake_scenario: FakeScenario | None,
        provider_model: str | None = None,
        credential_ref: str | None = None,
        allow_unsafe_local: bool = False,
        budget_limits: RunBudgetLimits | None = None,
        conversation_submission: ConversationSubmission | None = None,
    ) -> Run:
        self._reject_untrusted_secrets(
            {
                "project_path": str(project_path),
                "runtime_name": runtime_name,
                "sandbox_name": sandbox_name,
                "provider_model": provider_model,
            }
        )
        info = self.repository.inspect(project_path)
        self._reject_untrusted_secrets(info.model_dump(mode="json"))
        project = self.state.get_project_by_root(info.root)
        if project is None:
            raise FleetError(
                ErrorCode.PROJECT_NOT_INITIALIZED,
                "The repository is not registered with this Fleet state directory.",
                "Run `fleet init <path> --preview`, then initialize with an explicit reviewed "
                "runtime and sandbox selection.",
            )
        if info.identity_hash != project.identity_hash:
            raise FleetError(
                ErrorCode.PROJECT_NOT_GIT,
                "The repository identity no longer matches its registration.",
                "Use the original repository or a fresh Fleet state directory.",
            )
        selected_sandbox_name = project.sandbox_name if sandbox_name is None else sandbox_name
        if selected_sandbox_name != project.sandbox_name:
            raise FleetError(
                ErrorCode.CONFIG_INVALID,
                "Run-time sandbox differs from the reviewed project registration.",
                "Use the registered sandbox, or preserve this project/state and separately "
                "initialize a different protected setup.",
                details={
                    "requested_sandbox": selected_sandbox_name,
                    "registered_sandbox": project.sandbox_name,
                },
            )
        if project.sandbox_name == "local-unsafe" and not allow_unsafe_local:
            raise FleetError(
                ErrorCode.UNSAFE_LOCAL_CONFIRMATION_REQUIRED,
                "This run would execute reviewed commands directly on the host.",
                "Pass --allow-unsafe-local explicitly for this run; --yes is not sufficient.",
            )
        if project.sandbox_configuration is None:
            raise FleetError(
                ErrorCode.CONFIG_INVALID,
                "Project sandbox configuration is missing.",
                "Reinitialize the project with an explicit sandbox selection.",
            )
        sandbox_requirements = requirements_for_configuration(project.sandbox_configuration)
        sandbox_provider = self.resources.sandboxes.require(
            project.sandbox_configuration,
            sandbox_requirements,
        )
        if sandbox_name == "fake" and self.sandbox.capabilities != sandbox_provider.capabilities:
            raise FleetError(
                ErrorCode.SANDBOX_UNAVAILABLE,
                "The selected fake sandbox reported an unexpected capability descriptor.",
                "Use the built-in non-executing FakeSandbox for compatibility runs.",
            )
        if info.dirty_paths and not (
            all(path == ".fleet" or path.startswith(".fleet/") for path in info.dirty_paths)
            and info.status_fingerprint == project.init_status_fingerprint
        ):
            raise FleetError(
                ErrorCode.PROJECT_DIRTY,
                "A code-change run refuses unrecorded working-tree changes.",
                "Commit or manually stash your work and retry. Fleet did not modify it.",
                details={"dirty_paths": info.dirty_paths},
            )
        selected_runtime = project.runtime_name if runtime_name is None else runtime_name
        selected_provider_model = (
            project.provider_model if provider_model is None else provider_model
        )
        selected_credential_ref = (
            project.credential_ref if credential_ref is None else credential_ref
        )
        if (
            selected_runtime != project.runtime_name
            or selected_provider_model != project.provider_model
            or selected_credential_ref != project.credential_ref
        ):
            raise FleetError(
                ErrorCode.CONFIG_INVALID,
                "Run-time provider options differ from the reviewed project registration.",
                "Preserve this project and state. A different protected provider setup "
                "requires a separate reviewed registration; headed projects cannot be "
                "reinitialized.",
            )
        runtime_configuration = RuntimeConfiguration(
            runtime_name=selected_runtime,
            provider_model=selected_provider_model,
            credential_ref=selected_credential_ref,
        )
        self.runtimes.require(
            runtime_configuration,
            required_capabilities=_MINIMUM_RUNTIME_CAPABILITIES,
            credential_check=RuntimeCredentialCheck.RESOLVE,
        )
        spec_path = Path(project.canonical_root) / ".fleet" / "fleet.yaml"
        spec, config_snapshot = self.config.load_snapshot(spec_path)
        config_hash = self.config.snapshot_hash(config_snapshot)
        if config_hash != project.fleet_spec_hash:
            raise FleetError(
                ErrorCode.CONFIG_INVALID,
                "The active FleetSpec differs from the registered validated version.",
                "Preserve the organization and inspect its history. Use reviewed FleetPatch "
                "changes or restore the exact registered configuration; do not bypass its fence.",
            )
        if (
            spec.spec.runtime.adapter != selected_runtime
            or spec.spec.runtime.provider_model != selected_provider_model
            or configuration_from_request(spec.spec.sandbox) != project.sandbox_configuration
        ):
            raise FleetError(
                ErrorCode.CONFIG_INVALID,
                "The active FleetSpec runtime differs from Fleet-owned project settings.",
                "Restore the exact reviewed configuration, or preserve this project/state "
                "and separately initialize a different protected setup.",
            )
        self.runtimes.require(
            runtime_configuration,
            required_capabilities=spec.spec.runtime.required_capabilities,
            credential_check=RuntimeCredentialCheck.NONE,
        )
        with self.organization.admission(project) as admitted:
            if admitted.config_snapshot_sha256 != config_hash:
                raise FleetError(
                    ErrorCode.CONFIG_INVALID,
                    "The organization changed during configuration preflight.",
                    "Inspect its exact version before starting a new Run.",
                )
        sandbox_preflight = await self.resources.sandboxes.preflight(
            project.sandbox_configuration,
            sandbox_requirements,
        )
        if (
            sandbox_preflight.image_identity != project.sandbox_image_identity
            or sandbox_preflight.daemon_identity != project.sandbox_daemon_identity
        ):
            raise FleetError(
                ErrorCode.SANDBOX_IMAGE_UNAVAILABLE,
                "The configured Docker image or daemon no longer matches the reviewed project.",
                "Restore the reviewed local Docker boundary or run a fresh verified bootstrap.",
                details={"sandbox": project.sandbox_name},
            )
        if selected_runtime != "fake" and fake_scenario is not None:
            raise FleetError(
                ErrorCode.CONFIG_INVALID,
                "Fake scenarios are available only with the fake runtime.",
                "Remove `--fake-scenario` or use `--runtime fake`.",
            )
        selected_fake_scenario = fake_scenario or FakeScenario.SUCCESS
        redacted_goal, _ = self.redactor.redact_text(goal)
        now = self.clock.now()
        run = Run(
            run_id=self.ids.new(IdPrefix.RUN),
            project_id=project.project_id,
            correlation_id=self.ids.new(IdPrefix.CORRELATION),
            goal=redacted_goal,
            base_revision=info.head_revision,
            target_status_fingerprint=info.status_fingerprint,
            runtime_name=runtime_configuration.runtime_name,
            provider_model=runtime_configuration.provider_model,
            credential_ref=runtime_configuration.credential_ref,
            sandbox_name=project.sandbox_name,
            sandbox_configuration=project.sandbox_configuration,
            sandbox_requirements=sandbox_requirements,
            sandbox_capabilities_snapshot=sandbox_preflight.capabilities,
            sandbox_image_identity=sandbox_preflight.image_identity,
            sandbox_daemon_identity=sandbox_preflight.daemon_identity,
            unsafe_local_confirmed=allow_unsafe_local,
            fake_scenario=selected_fake_scenario,
            config_snapshot_hash=config_hash,
            max_repair_iterations=spec.spec.workflows["code-change"].max_repair_iterations,
            created_at=now,
            updated_at=now,
        )
        conversation_claim: ConversationClaim | None = None
        with self.organization.admission(project, expected=admitted):
            if conversation_submission is None:
                self.state.create_run(run, organization_admission=admitted)
            else:
                if self.conversations is None:
                    raise ConversationOwnershipUnavailableError()
                self._reject_untrusted_secrets(conversation_submission.model_dump(mode="json"))
                registration = self.conversations.register_turn_run(
                    conversation_submission,
                    run,
                    config_snapshot_sha256=config_hash,
                    budget_limits=budget_limits or RunBudgetLimits(),
                    organization_admission=admitted,
                )
                conversation_claim = registration.claim
                if conversation_claim is None:
                    return self.state.get_run(registration.turn.binding.run_id)
                self._conversation_claims[run.run_id] = conversation_claim
        orderly = False
        try:
            self.budgets.initialize_run(run.run_id, budget_limits or RunBudgetLimits())
            run = self._transition(run, RunStatus.RUNNING, WorkflowStage.INTAKE)
            run = self._transition(run, RunStatus.RUNNING, WorkflowStage.SCOPING)
            run = await self._scope(
                run,
                config_hash,
                config_snapshot,
                runtime_configuration,
                fleet_spec=spec,
                known_roles=set(spec.spec.agents),
            )
            if run.fleet_strategy == FleetStrategy.DIRECT.value:
                run = self._transition(run, RunStatus.RUNNING, WorkflowStage.PRESENTING)
                result = await self._continue(run)
                orderly = True
                return result
            if self._is_adaptive_graph(run):
                if run.fleet_plan_artifact_id is None:
                    raise RuntimeError("The accepted graph has no FleetPlan artifact")
                plan = FleetPlan.model_validate_json(
                    self.artifacts.read_text(run.fleet_plan_artifact_id)
                )
                self.graph_execution.initialize(run, plan)
                run = self._transition(run, RunStatus.RUNNING, WorkflowStage.WORKSPACE_PREPARATION)
                run = self._transition(run, RunStatus.RUNNING, WorkflowStage.IMPLEMENTING)
                result = await self._continue(run)
                orderly = True
                return result
            run = self._transition(run, RunStatus.RUNNING, WorkflowStage.WORKSPACE_PREPARATION)
            await self._prepare_workspace(run)
            run = self._transition(run, RunStatus.RUNNING, WorkflowStage.IMPLEMENTING)
            result = await self._continue(run)
            orderly = True
            return result
        except ApprovalRequiredError:
            orderly = True
            return self.state.get_run(run.run_id)
        except asyncio.CancelledError:
            if conversation_claim is not None:
                await self._cancel_conversation_execution(conversation_claim)
            raise
        except FleetError as error:
            if isinstance(error, ConversationOwnershipUnavailableError):
                raise
            latest = self.state.get_run(run.run_id)
            if latest.status is not RunStatus.PAUSED_FOR_APPROVAL:
                latest = self._persist_failure_evidence(latest, error)
                failed = latest.model_copy(
                    update={"status": RunStatus.FAILED, "updated_at": self.clock.now()}
                )
                self.state.save_run(
                    failed,
                    "run.failed",
                    {"code": error.code.value, "message": error.message},
                )
                await self.resources.cleanup_run(failed)
                error.details.setdefault("run_id", run.run_id)
                orderly = True
            raise
        finally:
            if conversation_claim is not None:
                try:
                    if orderly:
                        self._settle_conversation_execution(conversation_claim)
                finally:
                    self._conversation_claims.pop(run.run_id, None)

    async def resume(self, run_id: str) -> Run:
        # This guard deliberately precedes every terminal, approval and graph
        # shortcut. Public fleet resume is not a conversation-ownership bypass.
        if self.conversations is None:
            return await self._resume_run(run_id)
        binding = self.conversations.binding_for_run(run_id)
        if binding is None:
            return await self._resume_run(run_id)
        turn = self.conversations.get_turn(binding.project_id, binding.turn_id)
        if (
            turn.active_claim_id is not None
            or turn.status is ConversationTurnStatus.RECOVERY_REQUIRED
        ):
            raise ConversationOwnershipUnavailableError()
        if turn.status in {
            ConversationTurnStatus.DELIVERED,
            ConversationTurnStatus.FAILED,
            ConversationTurnStatus.CANCELLED,
        }:
            return self.state.get_run(run_id)
        claim = self.conversations.claim_resume(run_id, expected_revision=turn.revision)
        self._conversation_claims[run_id] = claim
        orderly = False
        try:
            result = await self._resume_run(run_id)
            orderly = True
            return result
        except ApprovalRequiredError:
            orderly = True
            raise
        except asyncio.CancelledError:
            await self._cancel_conversation_execution(claim)
            raise
        except FleetError:
            latest = self.state.get_run(run_id)
            orderly = latest.status in {
                RunStatus.FAILED,
                RunStatus.REJECTED,
                RunStatus.CANCELLED,
                RunStatus.ABANDONED,
            } and not any(
                self.state.outstanding_leases(owned_id)
                for owned_id in (
                    run_id,
                    *(child.child_run_id for child in self.graphs.descendants(run_id)),
                )
            )
            raise
        finally:
            try:
                if orderly:
                    self._settle_conversation_execution(claim)
            finally:
                self._conversation_claims.pop(run_id, None)

    async def _resume_run(self, run_id: str) -> Run:
        continuation_claim: GraphDriverClaim | None = None
        run = self.state.get_run(run_id)
        child_binding = self.graphs.child_binding(run_id)
        if child_binding is not None:
            raise FleetError(
                ErrorCode.COMMAND_DENIED,
                "An internal child cannot be resumed outside its claimed parent coordinator.",
                "Resume the parent run to preserve dependency and concurrency controls.",
                details={"parent_run_id": child_binding.parent_run_id},
            )
        if run.status in {
            RunStatus.COMPLETED,
            RunStatus.REJECTED,
            RunStatus.CANCELLED,
            RunStatus.FAILED,
            RunStatus.ABANDONED,
            RunStatus.READY_FOR_REVIEW,
        }:
            return run
        if self._is_adaptive_graph(run) and run.status is RunStatus.RUNNING:
            # A released child-graph claim does not mean the parent's verifier
            # stopped. Public resume cannot take over an executing parent.
            raise GraphOwnershipUnavailableError()
        with self.organization.run_guard(run):
            # Active/paused Run and retained-claim blockers keep publication
            # fenced after this short exact-generation check is released.
            pass
        runtime_configuration = self._runtime_configuration(run)
        self.runtimes.require(
            runtime_configuration,
            required_capabilities=_MINIMUM_RUNTIME_CAPABILITIES,
            credential_check=RuntimeCredentialCheck.RESOLVE,
        )
        project = self.state.get_project(run.project_id)
        if self.permission_policy is not None:
            self.permission_policy.validate_run_target(run)
        spec, snapshot = self.config.load_snapshot(
            Path(project.canonical_root) / ".fleet" / "fleet.yaml"
        )
        snapshot_hash = self.config.snapshot_hash(snapshot)
        if run.config_snapshot_hash is not None and snapshot_hash != run.config_snapshot_hash:
            raise FleetError(
                ErrorCode.CONFIG_INVALID,
                "The Fleet configuration changed while the run was paused.",
                "Restore the exact reviewed configuration. Preserve the existing state; "
                "a different protected setup requires a separate registration.",
            )
        self.runtimes.require(
            runtime_configuration,
            required_capabilities=spec.spec.runtime.required_capabilities,
            credential_check=RuntimeCredentialCheck.NONE,
        )
        if run.status is RunStatus.PAUSED_FOR_APPROVAL:
            if run.pending_approval_id is None:
                raise FleetError(
                    ErrorCode.RECOVERY_REQUIRED,
                    "Paused run has no persisted approval request.",
                    "Inspect the run events and start a new run if state is inconsistent.",
                )
            request = self.state.get_approval(run.pending_approval_id)
            if request.status.value == "pending":
                raise ApprovalRequiredError(request.request_id)
            if request.status.value == "denied":
                run = self._persist_evidence(run)[0]
                rejected = run.model_copy(
                    update={"status": RunStatus.REJECTED, "updated_at": self.clock.now()}
                )
                self.state.save_run(
                    rejected,
                    "run.rejected",
                    {"reason": "approval_denied", "request_id": request.request_id},
                )
                await self.resources.cleanup_run(rejected)
                return rejected
            if self._is_adaptive_graph(run):
                continuation_claim = self._claim_parent_continuation(run)
            if run.engineer_checkpoint is None and run.stage in {
                WorkflowStage.IMPLEMENTING,
                WorkflowStage.REPAIRING,
            }:
                # Pre-Phase4 runs had no role checkpoint. Adopt only the exact
                # persisted approved identity, never a new principal for its grant.
                intent = self.state.get_intent(request.intent_id).intent
                original_agent = self.state.get_agent_instance(intent.agent_instance_id)
                if (
                    original_agent.role != AgentRole.ENGINEER
                    or original_agent.run_id != run.run_id
                    or original_agent.task_id != run.task_id
                    or original_agent.iteration != run.repair_iterations
                ):
                    raise FleetError(
                        ErrorCode.RECOVERY_REQUIRED,
                        "The legacy approval has no matching Engineer identity.",
                        "Cancel the run; a grant cannot transfer to another principal.",
                    )
                workspace = self.resources.candidate_workspace(run.run_id)
                handle = self.resources.engineer_sandbox(run.run_id)
                checkpoint = AgentExecutionCheckpoint(
                    agent_instance_id=original_agent.agent_instance_id,
                    workspace_id=workspace.workspace_id,
                    sandbox_id=handle.sandbox_id,
                    iteration=original_agent.iteration,
                    created_at=original_agent.created_at,
                )
                run = self.state.save_run(
                    run.model_copy(update={"engineer_checkpoint": checkpoint}),
                    "engineering.checkpoint_adopted",
                    checkpoint.model_dump(mode="json"),
                )
            try:
                await self.resources.rehydrate_paused_sandboxes(run)
            except asyncio.CancelledError:
                if continuation_claim is not None:
                    await self.graph_execution.cancel_parent(run.run_id)
                raise
            except FleetError as error:
                if continuation_claim is not None:
                    latest = self.state.get_run(run_id)
                    self.state.save_run(
                        latest.model_copy(
                            update={"status": RunStatus.FAILED, "updated_at": self.clock.now()}
                        ),
                        "run.failed",
                        {"code": error.code.value, "reason": "parent_resume_rehydration_failed"},
                    )
                    try:
                        graph = self.graphs.get(run_id)
                        if graph is not None and graph.cancel_requested_at is None:
                            self.graphs.request_cancel(run_id, expected_revision=graph.revision)
                    finally:
                        await self.resources.cleanup_run(self.state.get_run(run_id))
                raise
            run = run.model_copy(
                update={
                    "status": RunStatus.RUNNING,
                    "pending_approval_id": None,
                    "updated_at": self.clock.now(),
                }
            )
            self.state.save_run(
                run,
                "run.resumed",
                {"request_id": request.request_id, "stage": run.stage.value if run.stage else None},
            )
        try:
            return await self._continue(run, continuation_claim=continuation_claim)
        except ApprovalRequiredError:
            return self.state.get_run(run_id)
        except ApprovalDeniedError as error:
            current = self._persist_evidence(self.state.get_run(run_id))[0]
            rejected = current.model_copy(
                update={"status": RunStatus.REJECTED, "updated_at": self.clock.now()}
            )
            self.state.save_run(
                rejected,
                "run.rejected",
                {"reason": "approval_denied", "request_id": error.details["request_id"]},
            )
            await self.resources.cleanup_run(rejected)
            return rejected
        except FleetError as error:
            if isinstance(
                error, (GraphOwnershipUnavailableError, ConversationOwnershipUnavailableError)
            ):
                raise
            latest = self.state.get_run(run_id)
            if latest.status is not RunStatus.PAUSED_FOR_APPROVAL:
                latest = self._persist_failure_evidence(latest, error)
                failed = latest.model_copy(
                    update={"status": RunStatus.FAILED, "updated_at": self.clock.now()}
                )
                self.state.save_run(
                    failed,
                    "run.failed",
                    {"code": error.code.value, "message": error.message},
                )
                await self.resources.cleanup_run(failed)
                error.details.setdefault("run_id", run_id)
            raise

    def _assert_conversation_execution(self, run: Run) -> None:
        if self.conversations is None:
            return
        child = self.graphs.child_binding(run.run_id)
        root_id = child.parent_run_id if child is not None else run.run_id
        binding = self.conversations.binding_for_run(root_id)
        if binding is not None:
            claim = self._conversation_claims.get(root_id)
            if claim is None:
                raise ConversationOwnershipUnavailableError()
            self.conversations.assert_claim(claim)

    async def _cancel_conversation_execution(self, claim: ConversationClaim) -> None:
        if self.conversations is None:
            raise ConversationOwnershipUnavailableError()
        self.conversations.assert_claim(claim)
        service = CancellationService(
            self.state, self.resources, self.clock, self.graphs, conversations=self.conversations
        )
        cleanup = asyncio.create_task(service.cancel(claim.run_id, conversation_claim=claim))
        # Strongly retain the exact cleanup until every repeated caller cancel
        # has settled. No input loop or exiting CLI may leave a hidden worker.
        while not cleanup.done():
            try:
                await asyncio.wait({cleanup})
            except asyncio.CancelledError:
                continue
        cleanup.result()

    def _settle_conversation_execution(self, claim: ConversationClaim) -> None:
        if self.conversations is None:
            raise ConversationOwnershipUnavailableError()
        turn = self.conversations.get_turn(claim.project_id, claim.turn_id)
        if turn.active_claim_id != claim.claim_id:
            if turn.fenced_at is not None or turn.settled_at is not None:
                return
            raise ConversationOwnershipUnavailableError()
        run = self.state.get_run(claim.run_id)
        if run.status not in {
            RunStatus.PAUSED_FOR_APPROVAL,
            RunStatus.WAITING_FOR_CHILDREN,
            RunStatus.READY_FOR_REVIEW,
            RunStatus.COMPLETED,
            RunStatus.REJECTED,
            RunStatus.CANCELLED,
            RunStatus.FAILED,
            RunStatus.ABANDONED,
        }:
            # A partial registration/dispatch or uncertain state write is not
            # an orderly pause. Retain the owner for stopped-process recovery.
            return
        self.conversations.assert_claim(claim)
        summary, refs = conversation_result(
            self.state,
            self.artifacts,
            InspectionService(self.state, self.artifacts, self.budgets, self.graphs),
            run,
        )
        self._reject_untrusted_secrets(summary.model_dump(mode="json"))
        self.conversations.settle(
            claim, expected_revision=turn.revision, summary=summary, artifact_refs=refs
        )

    async def _scope(
        self,
        run: Run,
        config_hash: str,
        config_snapshot: ConfigSnapshot,
        runtime_configuration: RuntimeConfiguration,
        *,
        fleet_spec: FleetSpec,
        known_roles: set[str],
    ) -> Run:
        guidance = self._role_guidance(fleet_spec, config_snapshot, AgentRole.COS)
        task_id = self.ids.new(IdPrefix.TASK)
        agent = AgentInstance(
            agent_instance_id=self.ids.new(IdPrefix.AGENT),
            run_id=run.run_id,
            task_id=None,
            role=AgentRole.COS,
            status=AgentStatus.RUNNING,
            iteration=0,
            created_at=self.clock.now(),
        )
        project = self.state.get_project(run.project_id)
        invocation_input: dict[str, JsonValue] = {
            "goal": run.goal,
            "available_roles": cast(JsonValue, sorted(fleet_spec.spec.agents)),
            "delegation_roles": cast(JsonValue, fleet_spec.spec.agents["cos"].may_delegate_to),
            "max_parallel_agents": fleet_spec.spec.workflows["code-change"].max_parallel_agents,
        }
        organization_context = self.organization.proposal_context(run, config_snapshot)
        invocation_input["organization_context"] = organization_context.input
        self._assert_conversation_execution(run)
        if self.conversations is not None:
            binding = self.conversations.binding_for_run(run.run_id)
            if binding is not None:
                turn = self.conversations.get_turn(binding.project_id, binding.turn_id)
                context = turn.context.model_dump(mode="json")
                self._reject_untrusted_secrets(context)
                for entry in turn.context.entries:
                    for ref in entry.artifact_refs:
                        self.artifacts.read_bounded_text(ref.artifact_id)
                invocation_input["conversation_context"] = context
        if run.runtime_name == "fake":
            invocation_input["fake_scenario"] = run.fake_scenario.value
        context_artifact_ids: list[str] = []
        for key, artifact_id in (
            ("repository_profile", project.repository_profile_artifact_id),
            ("project_knowledge", project.project_knowledge_artifact_id),
        ):
            if artifact_id is None:
                continue
            content = self._read_json_context(artifact_id)
            invocation_input[key] = content
            context_artifact_ids.append(artifact_id)
        request = self._build_invocation(
            run_id=run.run_id,
            task_id=task_id,
            agent_instance_id=agent.agent_instance_id,
            role=AgentRole.COS,
            stage=WorkflowStage.SCOPING,
            iteration=0,
            max_steps=min(10, fleet_spec.spec.agents["cos"].max_steps),
            instructions=guidance,
            context_artifact_ids=context_artifact_ids,
            input=invocation_input,
        )
        adapter = self.runtimes.get(runtime_configuration.runtime_name)
        self.state.save_agent_instance(agent)
        self._emit(
            run,
            "agent.started",
            {"role": "cos", "iteration": 0},
            agent_id=agent.agent_instance_id,
        )
        result = await self._invoke_runtime_agent(
            run,
            agent,
            adapter,
            request,
            RuntimeInvocationServices(
                configuration=runtime_configuration,
                tools=(
                    EMPTY_RUNTIME_TOOL_CATALOG
                    if runtime_configuration.runtime_name == "fake"
                    else ProposalHashToolCatalog(self.redactor)
                ),
            ),
        )
        proposal: FleetPatchProposalRecord | None = None
        if isinstance(result.output, FleetPatch):
            proposal = self.organization.propose(run, result.output, organization_context)
            proposal_id = proposal.patch.fleet_patch_id
            decision = ScopeDecision(
                normalized_goal="Propose a reviewable organization update.",
                response=(
                    f"FleetPatch {proposal_id} is proposed and not applied. "
                    f"Inspect it with `fleet fleet-patch diff {proposal_id}`. "
                    "Only explicit user application can activate this organization version."
                ),
                workflow="code-change",
                change_kind="read_only",
                fleet_strategy="direct",
                allowed_paths=[],
                forbidden_paths=[".git", ".fleet"],
                acceptance_criteria=[
                    {
                        "criterion_id": "reviewable-organization-proposal",
                        "description": "Persist an exact validated proposal without applying it.",
                    }
                ],
                required_evidence=["control_plane_plan"],
            )
        else:
            decision = cast(ScopeDecision, result.output)
        if self.permission_policy is not None:
            self.permission_policy.validate_task_paths(project, decision.allowed_paths)
        if decision.workflow not in fleet_spec.spec.workflows:
            raise FleetError(
                ErrorCode.CONFIG_INVALID,
                "CoS proposed an undeclared workflow.",
                "Select a workflow declared in the reviewed FleetSpec.",
            )
        verification_profile = self.config.verification_profile(fleet_spec, config_snapshot)
        verification_commands = [
            CommandSpec(
                command_id=command_id,
                executable=command.executable,
                argv=tuple(command.argv),
                logical_cwd=command.cwd,
                timeout_seconds=command.timeout_seconds,
                network_requirement="required" if command.network_required else "none",
            )
            for command_id, command in sorted(verification_profile.commands.items())
        ]
        task = TaskSpec(
            task_id=task_id,
            run_id=run.run_id,
            original_goal=run.goal,
            normalized_goal=decision.normalized_goal,
            workflow=decision.workflow,
            change_kind=decision.change_kind,
            base_revision=run.base_revision,
            allowed_paths=decision.allowed_paths,
            forbidden_paths=decision.forbidden_paths,
            acceptance_criteria=decision.acceptance_criteria,
            required_evidence=decision.required_evidence,
            max_repair_iterations=run.max_repair_iterations,
            config_snapshot_hash=config_hash,
            verification_commands=verification_commands,
            required_verification_command_ids=list(
                self.config.required_verification_commands(
                    fleet_spec,
                    config_snapshot,
                    workflow_id=decision.workflow,
                    allowed_paths=tuple(decision.allowed_paths),
                    change_kind=decision.change_kind,
                )
            ),
            created_at=self.clock.now(),
        )
        strategy = FleetStrategy(decision.fleet_strategy)
        plan = self.planner.create(
            run,
            task,
            strategy,
            known_roles=known_roles,
            role_max_steps={
                role: request.max_steps for role, request in fleet_spec.spec.agents.items()
            },
            writer_assignments=decision.writer_assignments,
            max_parallel_agents=decision.max_parallel_agents,
            configured_max_parallel_agents=fleet_spec.spec.workflows[
                decision.workflow
            ].max_parallel_agents,
        )
        if {node.role_id for node in plan.nodes} - set(
            fleet_spec.spec.agents["cos"].may_delegate_to
        ):
            raise FleetError(
                ErrorCode.COMMAND_DENIED,
                "The proposed team exceeds the reviewed CoS delegation ceiling.",
                "Select a permitted smaller team or explicitly review an organization update.",
            )
        if strategy is FleetStrategy.DIRECT:
            if decision.response is None:
                raise FleetError(
                    ErrorCode.RUNTIME_OUTPUT_INVALID,
                    "The direct CoS turn did not provide a bounded response.",
                    "Return a factual response with explicit limitations, not only a task plan.",
                )
            self.artifacts.create_text(
                kind=ArtifactKind.COS_RESPONSE,
                project_id=run.project_id,
                run_id=run.run_id,
                task_id=task.task_id,
                producer=f"{run.runtime_name}-runtime:cos",
                content=decision.response,
                metadata={"assurance": "model_response_not_execution_evidence"},
            )
        plan_artifact = self.artifacts.create_text(
            kind=ArtifactKind.FLEET_PLAN,
            project_id=run.project_id,
            run_id=run.run_id,
            task_id=task.task_id,
            producer="control-plane",
            content=plan.model_dump_json(indent=2),
            mime_type="application/json",
        )
        task_artifact = self.artifacts.create_text(
            kind=ArtifactKind.TASK_SPEC,
            project_id=run.project_id,
            run_id=run.run_id,
            task_id=task.task_id,
            producer="control-plane",
            content=task.model_dump_json(indent=2),
            mime_type="application/json",
        )
        config_snapshot_artifact = self.artifacts.create_text(
            kind=ArtifactKind.CONFIG_SNAPSHOT,
            project_id=run.project_id,
            run_id=run.run_id,
            task_id=task.task_id,
            producer="control-plane",
            content=config_snapshot.model_dump_json(indent=2),
            mime_type="application/json",
            redact=False,
            reject_secret=True,
        )
        if config_snapshot_artifact.sha256 != config_hash:
            raise RuntimeError("configuration snapshot hash changed before task binding")
        run = run.model_copy(
            update={
                "task_id": task_id,
                "task_spec_artifact_id": task_artifact.artifact_id,
                "task_spec_hash": task_artifact.sha256,
                "config_snapshot_artifact_id": config_snapshot_artifact.artifact_id,
                "config_snapshot_hash": config_snapshot_artifact.sha256,
                "fleet_plan_artifact_id": plan_artifact.artifact_id,
                "fleet_plan_hash": plan_artifact.sha256,
                "fleet_strategy": strategy.value,
                "updated_at": self.clock.now(),
            }
        )
        self.state.save_task(task)
        self.state.save_agent_instance(
            agent.model_copy(
                update={
                    "task_id": task_id,
                    "status": AgentStatus.COMPLETED,
                    "completed_at": self.clock.now(),
                }
            )
        )
        self.state.save_run(run, "run.task_bound", {"task_id": task_id})
        run = self._persist_runtime_observation(
            run,
            task.task_id,
            agent.agent_instance_id,
            "cos",
            result,
        )
        self._emit(
            run,
            "fleet.plan_accepted",
            {
                "fleet_plan_artifact_id": plan_artifact.artifact_id,
                "fleet_plan_sha256": plan_artifact.sha256,
                "strategy": strategy.value,
                "planned_roles": [node.role_id for node in plan.nodes],
            },
        )
        if proposal is not None:
            self.organization.record_proposal_artifacts(proposal, run)
            self._emit(
                run,
                "fleet_patch.proposed",
                {
                    "fleet_patch_id": proposal.patch.fleet_patch_id,
                    "proposal_sha256": proposal.proposal_sha256,
                },
            )
        return run

    async def _prepare_workspace(self, run: Run) -> None:
        candidate, _ = self.resources.create_workspace(run, WorkspaceKind.CANDIDATE)
        if run.sandbox_configuration is None or run.sandbox_requirements is None:
            raise RuntimeError("Run sandbox binding was not materialized")
        await self.resources.create_sandbox(
            run.run_id,
            SandboxSpec(
                workspace_host_path=candidate.path,
                project_id=run.project_id,
                configuration=run.sandbox_configuration,
                requirements=run.sandbox_requirements,
                environment={},
                unsafe_local_confirmed=run.unsafe_local_confirmed,
                image_identity=run.sandbox_image_identity,
                daemon_identity=run.sandbox_daemon_identity,
            ),
        )

    async def _continue(
        self, run: Run, *, continuation_claim: GraphDriverClaim | None = None
    ) -> Run:
        claim = continuation_claim
        if (
            self._is_adaptive_graph(run)
            and run.stage
            in {
                WorkflowStage.VERIFYING,
                WorkflowStage.REPAIRING,
                WorkflowStage.PRESENTING,
            }
            and claim is None
        ):
            claim = self._claim_parent_continuation(run)
        try:
            return await self._continue_steps(run, continuation_claim=claim)
        except asyncio.CancelledError:
            if self._is_adaptive_graph(run):
                await self.graph_execution.cancel_parent(run.run_id)
            raise
        finally:
            if claim is not None:
                self._release_parent_continuation(claim)

    def _claim_parent_continuation(self, run: Run) -> GraphDriverClaim:
        try:
            graph = self.graphs.get(run.run_id)
            if graph is not None:
                return self.graphs.claim_continuation(run.run_id, expected_revision=graph.revision)
        except Exception:
            pass
        # A failed ownership CAS is not an authorization to fail or clean the
        # winning owner's resources. Keep underlying storage details private.
        raise GraphOwnershipUnavailableError()

    def _release_parent_continuation(self, claim: GraphDriverClaim) -> None:
        graph = self.graphs.get(claim.parent_run_id)
        if graph is None:
            raise GraphOwnershipUnavailableError()
        if graph.cancel_requested_at is not None:
            return
        if graph.driver_claim == claim:
            self.graphs.release_driver(
                claim, expected_revision=graph.revision, status=GraphStatus.JOINED
            )
        elif graph.driver_claim is not None or graph.status is not GraphStatus.JOINED:
            raise GraphOwnershipUnavailableError()

    async def _continue_steps(
        self, run: Run, *, continuation_claim: GraphDriverClaim | None = None
    ) -> Run:
        while True:
            run = self.state.get_run(run.run_id)
            if run.status is RunStatus.PAUSED_FOR_APPROVAL:
                return run
            if self._is_adaptive_graph(run) and run.stage is WorkflowStage.IMPLEMENTING:
                run = await self.graph_coordinator.drive(run.run_id)
                if run.status is not RunStatus.RUNNING or run.stage is not WorkflowStage.VERIFYING:
                    return run
                return await self._continue(run)
            if run.stage in {WorkflowStage.IMPLEMENTING, WorkflowStage.REPAIRING}:
                await self._engineer(run)
                run = self.state.get_run(run.run_id)
                if run.status is RunStatus.PAUSED_FOR_APPROVAL:
                    return run
                next_stage = (
                    WorkflowStage.PRESENTING
                    if run.fleet_strategy == FleetStrategy.SINGLE_ENGINEER.value
                    else WorkflowStage.VERIFYING
                )
                run = self._transition(run, RunStatus.RUNNING, next_stage)
                continue
            if run.stage is WorkflowStage.VERIFYING:
                verifier = await self._verify(run)
                run = self.state.get_run(run.run_id)
                if verifier.verdict is Verdict.FAIL:
                    if run.repair_iterations < run.max_repair_iterations:
                        if self._is_adaptive_graph(run):
                            self._emit(
                                run,
                                "graph.repair_fallback",
                                {
                                    "mode": "sequential_parent_engineer",
                                    "iteration": run.repair_iterations + 1,
                                },
                            )
                        run = run.model_copy(
                            update={
                                "status": RunStatus.RUNNING,
                                "stage": WorkflowStage.REPAIRING,
                                "repair_iterations": run.repair_iterations + 1,
                                "updated_at": self.clock.now(),
                            }
                        )
                        self.state.save_run(
                            run,
                            "repair.requested",
                            {"repair_iteration": run.repair_iterations},
                        )
                        continue
                    if continuation_claim is not None:
                        self._release_parent_continuation(continuation_claim)
                    run = self._persist_evidence(run)[0]
                    rejected = run.model_copy(
                        update={"status": RunStatus.REJECTED, "updated_at": self.clock.now()}
                    )
                    self.state.save_run(
                        rejected,
                        "run.rejected",
                        {"reason": "verifier_fail", "repair_iterations": run.repair_iterations},
                    )
                    await self.resources.cleanup_run(rejected)
                    return rejected
                run = self._transition(run, RunStatus.RUNNING, WorkflowStage.PRESENTING)
                continue
            if run.stage is WorkflowStage.PRESENTING:
                if self._is_adaptive_graph(run):
                    await self.graph_execution.cleanup_graph_children(run)
                await self.resources.cleanup_run(run)
                if self.state.outstanding_leases(run.run_id):
                    raise FleetError(
                        ErrorCode.SANDBOX_CLEANUP_FAILED,
                        "Run resources remain after final cleanup.",
                        "Run Fleet recovery before trusting or publishing this result.",
                    )
                run = self._persist_cleanup_receipt(run)
                if continuation_claim is not None:
                    self._release_parent_continuation(continuation_claim)
                run, bundle = self._persist_evidence(run)
                if bundle.completion_decision is None:
                    raise RuntimeError("EvidenceBundle has no completion decision")
                decision = bundle.completion_decision
                operational_status = (
                    RunStatus.COMPLETED
                    if run.fleet_strategy == FleetStrategy.DIRECT.value
                    else RunStatus.READY_FOR_REVIEW
                )
                sandbox_capabilities = run.sandbox_capabilities_snapshot
                sandbox_security_level = (
                    sandbox_capabilities.security_level.value
                    if sandbox_capabilities is not None
                    else "unknown"
                )
                sandbox_notes = ""
                if sandbox_capabilities is None or not sandbox_capabilities.executes_code:
                    sandbox_notes += "proof_gap=Configured sandbox did not execute project code.\n"
                if (
                    sandbox_capabilities is not None
                    and sandbox_capabilities.security_level is SandboxSecurityLevel.UNSAFE_HOST
                ):
                    sandbox_notes += "remaining_risk=Execution occurred on the unsafe host.\n"
                self.artifacts.create_text(
                    kind=ArtifactKind.RUN_SUMMARY,
                    project_id=run.project_id,
                    run_id=run.run_id,
                    task_id=run.task_id,
                    producer="control-plane",
                    content=(
                        f"status={operational_status.value}\n"
                        f"patch_sha256={run.patch_sha256}\n"
                        f"fleet_strategy={run.fleet_strategy}\n"
                        f"evidence_bundle_artifact_id={run.evidence_bundle_artifact_id}\n"
                        f"assurance_verdict={decision.effective_verdict.value}\n"
                        f"verified_complete={str(run.verified_complete).lower()}\n"
                        f"runtime={run.runtime_name}\n"
                        f"provider_model={run.provider_model or 'none'}\n"
                        f"sandbox={run.sandbox_name}\n"
                        f"security_level={sandbox_security_level}\n"
                        f"runtime_budget={self.budgets.snapshot(run.run_id).model_dump_json()}\n"
                        f"delivery_evidence={self._delivery_evidence_summary(bundle)}\n"
                        f"{sandbox_notes}"
                    ),
                )
                ready = run.model_copy(
                    update={"status": operational_status, "updated_at": self.clock.now()}
                )
                self.state.save_run(
                    ready,
                    "run.completed" if operational_status is RunStatus.COMPLETED else "patch.ready",
                    {
                        "patch_artifact_id": run.patch_artifact_id,
                        "patch_sha256": run.patch_sha256,
                        "verified_complete": run.verified_complete,
                        "assurance_verdict": decision.effective_verdict.value,
                    },
                )
                return ready
            return run

    @staticmethod
    def _is_adaptive_graph(run: Run) -> bool:
        return run.fleet_strategy in {
            FleetStrategy.PARALLEL_ENGINEERS.value,
            FleetStrategy.RESEARCH_ARCHITECT_ENGINEER_VERIFIER.value,
        }

    @staticmethod
    def _delivery_evidence_summary(bundle: EvidenceBundle) -> str:
        return json.dumps(
            {
                "changed_files": bundle.changed_paths,
                "patch_artifact_id": bundle.patch_artifact_id,
                "patch_sha256": bundle.patch_sha256,
                "commands": [
                    {
                        "command_id": command.command_id,
                        "executable": command.executable,
                        "argv": command.argv,
                        "cwd": command.cwd,
                        "exit_code": command.exit_code,
                        "timed_out": command.timed_out,
                        "output_truncated": command.output_truncated,
                        "evidence_artifact_id": command.evidence_id,
                        "transcript_artifact_id": command.transcript_artifact_id,
                        "strength": command.strength.value,
                    }
                    for command in bundle.command_evidence
                ],
                "criterion_assessments": [
                    item.model_dump(mode="json") for item in bundle.criterion_assessments
                ],
                "verifier_verdict_artifact_id": bundle.verifier_verdict_artifact_id,
                "reported_verdict": (
                    bundle.reported_verdict.value if bundle.reported_verdict is not None else None
                ),
                "remaining_risks": [
                    item.model_dump(mode="json") for item in bundle.remaining_risks
                ],
                "proof_gaps": [item.model_dump(mode="json") for item in bundle.proof_gaps],
            },
            sort_keys=True,
        )

    async def _engineer(self, run: Run) -> None:
        if run.task_id is None:
            raise RuntimeError("run has no task")
        task = self.state.get_task(run.task_id)
        guidance = self._active_role_guidance(run, AgentRole.ENGINEER)
        workspace = self.resources.candidate_workspace(run.run_id)
        handle = self.resources.engineer_sandbox(run.run_id)
        checkpoint = run.engineer_checkpoint
        if checkpoint is None:
            checkpoint = AgentExecutionCheckpoint(
                agent_instance_id=self.ids.new(IdPrefix.AGENT),
                workspace_id=workspace.workspace_id,
                sandbox_id=handle.sandbox_id,
                iteration=run.repair_iterations,
                created_at=self.clock.now(),
            )
            run = self.state.save_run(
                self.state.get_run(run.run_id).model_copy(
                    update={"engineer_checkpoint": checkpoint, "updated_at": self.clock.now()}
                ),
                "engineering.checkpoint_created",
                checkpoint.model_dump(mode="json"),
            )
        elif (
            checkpoint.workspace_id != workspace.workspace_id
            or checkpoint.sandbox_id != handle.sandbox_id
            or checkpoint.iteration != run.repair_iterations
        ):
            raise FleetError(
                ErrorCode.RECOVERY_REQUIRED,
                "The paused Engineer identity no longer matches its candidate context.",
                "Cancel or recover the existing run; do not transfer its intents to another agent.",
            )
        agent = AgentInstance(
            agent_instance_id=checkpoint.agent_instance_id,
            run_id=run.run_id,
            task_id=task.task_id,
            role=AgentRole.ENGINEER,
            status=AgentStatus.RUNNING,
            iteration=run.repair_iterations,
            created_at=checkpoint.created_at,
        )
        configuration = self._runtime_configuration(run)
        adapter = self.runtimes.get(configuration.runtime_name)
        catalog = GatewayRuntimeToolCatalog(
            gateway=self.gateway,
            redactor=self.redactor,
            run=run,
            task=task,
            agent=agent,
            workspace=workspace,
            sandbox_handle=handle,
            max_calls=configuration.max_tool_calls,
        )
        request = self._build_invocation(
            run_id=run.run_id,
            task_id=task.task_id,
            agent_instance_id=agent.agent_instance_id,
            role=AgentRole.ENGINEER,
            stage=run.stage or WorkflowStage.IMPLEMENTING,
            iteration=run.repair_iterations,
            max_steps=self._active_role_max_steps(run, AgentRole.ENGINEER, ceiling=20),
            instructions=guidance,
            context_artifact_ids=[
                item
                for item in (
                    run.task_spec_artifact_id,
                    run.fleet_plan_artifact_id,
                    run.config_snapshot_artifact_id,
                    run.verifier_verdict_artifact_id if run.repair_iterations else None,
                )
                if item is not None
            ]
            + self.graph_execution.context_artifact_ids(run),
            input=self._runtime_input(
                run,
                {
                    "task_spec": task.model_dump(mode="json"),
                    "repair_iterations": run.repair_iterations,
                    "previous_verifier_feedback": self._repair_feedback(run),
                    "graph_context": self.graph_execution.model_context(run),
                },
            ),
        )
        self.state.save_agent_instance(agent)
        self._emit(
            run,
            "agent.started",
            {"role": "engineer", "iteration": run.repair_iterations},
            agent_id=agent.agent_instance_id,
        )
        result = await self._invoke_runtime_agent(
            run,
            agent,
            adapter,
            request,
            RuntimeInvocationServices(configuration=configuration, tools=catalog),
        )
        evidence_artifact_ids = self._command_evidence_ids(catalog.records)
        report = cast(ImplementationReport, result.output).model_copy(
            update={"evidence_artifact_ids": evidence_artifact_ids}
        )
        run = self._persist_runtime_observation(
            run,
            task.task_id,
            agent.agent_instance_id,
            "engineer",
            result,
        )
        self.artifacts.create_text(
            kind=ArtifactKind.IMPLEMENTATION_REPORT,
            project_id=run.project_id,
            run_id=run.run_id,
            task_id=task.task_id,
            producer=f"{run.runtime_name}-runtime:engineer",
            content=report.model_dump_json(indent=2),
            mime_type="application/json",
        )
        patch = self.repository.compute_patch(workspace)
        if not patch.changed_paths or any(
            not path_is_within(path, task.allowed_paths, forbidden=task.forbidden_paths)
            for path in patch.changed_paths
        ):
            raise FleetError(
                ErrorCode.COMMAND_DENIED,
                "Canonical candidate changes are empty or outside the TaskSpec path scope.",
                "Restrict Engineer changes to the approved TaskSpec paths.",
                details={"changed_paths": patch.changed_paths},
            )
        artifact = self.artifacts.create_text(
            kind=ArtifactKind.PATCH,
            project_id=run.project_id,
            run_id=run.run_id,
            task_id=task.task_id,
            producer="git-control-plane",
            content=patch.content,
            mime_type="text/x-diff",
            redact=False,
            reject_secret=True,
            metadata={"changed_paths": cast(JsonValue, patch.changed_paths)},
        )
        latest = self.state.get_run(run.run_id)
        updated = latest.model_copy(
            update={
                "engineer_checkpoint": None,
                "patch_artifact_id": artifact.artifact_id,
                "patch_sha256": patch.sha256,
                "command_evidence_artifact_ids": list(
                    dict.fromkeys([*latest.command_evidence_artifact_ids, *evidence_artifact_ids])
                ),
                "updated_at": self.clock.now(),
            }
        )
        self.state.save_run(
            updated,
            "implementation.reported",
            {"patch_artifact_id": artifact.artifact_id, "changed_paths": patch.changed_paths},
        )

    async def _verify(self, run: Run) -> VerifierVerdict:
        if run.task_id is None or run.patch_artifact_id is None:
            raise RuntimeError("run has no task or patch")
        task = self.state.get_task(run.task_id)
        guidance = self._active_role_guidance(run, AgentRole.VERIFIER)
        patch = self.artifacts.read_text(run.patch_artifact_id).encode()
        if run.sandbox_configuration is None or run.sandbox_requirements is None:
            raise RuntimeError("Run sandbox binding was not materialized")
        checkpoint = run.verification_checkpoint
        if checkpoint is None:
            workspace, workspace_lease = self.resources.create_workspace(
                run, WorkspaceKind.VERIFICATION
            )
            self.repository.apply_patch_to_workspace(workspace, patch)
            before = self.repository.workspace_status_fingerprint(workspace)
            handle = await self.resources.create_sandbox(
                run.run_id,
                SandboxSpec(
                    workspace_host_path=workspace.path,
                    project_id=run.project_id,
                    configuration=run.sandbox_configuration,
                    requirements=run.sandbox_requirements,
                    environment={},
                    unsafe_local_confirmed=run.unsafe_local_confirmed,
                    image_identity=run.sandbox_image_identity,
                    daemon_identity=run.sandbox_daemon_identity,
                ),
            )
            if run.patch_sha256 is None:
                raise RuntimeError("Run patch hash is missing")
            checkpoint = VerificationCheckpoint(
                agent_instance_id=self.ids.new(IdPrefix.AGENT),
                workspace_id=workspace.workspace_id,
                sandbox_id=handle.sandbox_id,
                patch_sha256=run.patch_sha256,
                baseline_fingerprint=before,
                iteration=run.repair_iterations,
                created_at=self.clock.now(),
            )
            run = self.state.save_run(
                self.state.get_run(run.run_id).model_copy(
                    update={"verification_checkpoint": checkpoint, "updated_at": self.clock.now()}
                ),
                "verification.checkpoint_created",
                checkpoint.model_dump(mode="json"),
            )
        else:
            workspace = self.resources.checkpoint_workspace(run.run_id, checkpoint.workspace_id)
            handle = self.resources.checkpoint_sandbox(run.run_id, checkpoint.sandbox_id)
            before = checkpoint.baseline_fingerprint
            if (
                checkpoint.patch_sha256 != run.patch_sha256
                or checkpoint.iteration != run.repair_iterations
                or workspace.kind is not WorkspaceKind.VERIFICATION
                or workspace.base_revision != run.base_revision
                or handle.workspace_host_path != workspace.path
                or handle.project_id != run.project_id
                or self.repository.workspace_status_fingerprint(workspace) != before
                or self.repository.compute_patch(workspace).sha256 != checkpoint.patch_sha256
            ):
                raise FleetError(
                    ErrorCode.RECOVERY_REQUIRED,
                    "The paused verification context changed.",
                    "Cancel or recover this run; cached command evidence cannot move contexts.",
                )
            workspace_lease = next(
                lease
                for lease in self.state.active_leases(run.run_id)
                if lease.kind is LeaseKind.WORKTREE and lease.resource_id == workspace.workspace_id
            )
        sandbox_lease = next(
            lease
            for lease in self.state.active_leases(run.run_id)
            if lease.kind is LeaseKind.SANDBOX and lease.resource_id == handle.sandbox_id
        )
        agent = AgentInstance(
            agent_instance_id=checkpoint.agent_instance_id,
            run_id=run.run_id,
            task_id=task.task_id,
            role=AgentRole.VERIFIER,
            status=AgentStatus.RUNNING,
            iteration=run.repair_iterations,
            created_at=checkpoint.created_at,
        )
        configuration = self._runtime_configuration(run)
        adapter = self.runtimes.get(configuration.runtime_name)
        catalog = GatewayRuntimeToolCatalog(
            gateway=self.gateway,
            redactor=self.redactor,
            run=run,
            task=task,
            agent=agent,
            workspace=workspace,
            sandbox_handle=handle,
            max_calls=configuration.max_tool_calls,
        )
        request = self._build_invocation(
            run_id=run.run_id,
            task_id=task.task_id,
            agent_instance_id=agent.agent_instance_id,
            role=AgentRole.VERIFIER,
            stage=WorkflowStage.VERIFYING,
            iteration=run.repair_iterations,
            max_steps=self._active_role_max_steps(run, AgentRole.VERIFIER, ceiling=10),
            instructions=guidance,
            context_artifact_ids=[
                item
                for item in (
                    run.task_spec_artifact_id,
                    run.fleet_plan_artifact_id,
                    run.patch_artifact_id,
                )
                if item is not None
            ],
            input=self._runtime_input(
                run,
                {
                    "task_spec": task.model_dump(mode="json"),
                    "repair_iterations": run.repair_iterations,
                    "patch_sha256": run.patch_sha256,
                    "patch": self._bounded_runtime_text(patch.decode()),
                },
            ),
        )
        self.state.save_agent_instance(agent)
        self._emit(
            run,
            "agent.started",
            {"role": "verifier", "iteration": run.repair_iterations},
            agent_id=agent.agent_instance_id,
        )
        result = await self._invoke_runtime_agent(
            run,
            agent,
            adapter,
            request,
            RuntimeInvocationServices(configuration=configuration, tools=catalog),
        )
        evidence_artifact_ids = self._command_evidence_ids(catalog.records)
        after = self.repository.workspace_status_fingerprint(workspace)
        mutated = (
            before != after
            or self.repository.compute_patch(workspace).sha256 != checkpoint.patch_sha256
        )
        run = self._persist_runtime_observation(
            run,
            task.task_id,
            agent.agent_instance_id,
            "verifier",
            result,
        )
        bound_verdict = cast(VerifierVerdict, result.output).model_copy(
            update={"evidence_artifact_ids": evidence_artifact_ids}
        )
        verdict_artifact = self.artifacts.create_text(
            kind=ArtifactKind.VERIFIER_VERDICT,
            project_id=run.project_id,
            run_id=run.run_id,
            task_id=task.task_id,
            producer=f"{run.runtime_name}-runtime:verifier",
            content=bound_verdict.model_dump_json(indent=2),
            mime_type="application/json",
        )
        # An independently verified result is not authoritative until both fresh
        # verifier resources have been proved absent.  Keep the artifacts unbound
        # if cleanup fails so the completion gate cannot claim success.
        await self.resources.cleanup_lease(run, sandbox_lease)
        await self.resources.cleanup_lease(run, workspace_lease)
        latest = self.state.get_run(run.run_id)
        updated = latest.model_copy(
            update={
                "command_evidence_artifact_ids": list(
                    dict.fromkeys([*latest.command_evidence_artifact_ids, *evidence_artifact_ids])
                ),
                "verifier_agent_instance_id": agent.agent_instance_id,
                "verification_checkpoint": None,
                "verifier_verdict_artifact_id": verdict_artifact.artifact_id,
                "verifier_workspace_mutated": mutated,
                "updated_at": self.clock.now(),
            }
        )
        self.state.save_run(
            updated,
            "verification.completed",
            {
                "verdict": bound_verdict.verdict.value,
                "verdict_artifact_id": verdict_artifact.artifact_id,
                "verification_workspace_mutated": mutated,
                "security_level": (
                    run.sandbox_capabilities_snapshot.security_level.value
                    if run.sandbox_capabilities_snapshot is not None
                    else "unknown"
                ),
            },
        )
        return bound_verdict

    async def _invoke_runtime_agent(
        self,
        run: Run,
        agent: AgentInstance,
        adapter: RuntimeAdapter,
        request: AgentInvocation,
        services: RuntimeInvocationServices,
    ) -> AgentInvocationResult:
        self._assert_conversation_execution(run)
        accounting: RuntimeAccounting | None = None
        attempt_finished = False
        try:
            accounting = self.budgets.begin_attempt(request)
            try:
                async with asyncio.timeout(accounting.remaining_active_seconds()):
                    result = await adapter.invoke(request, replace(services, accounting=accounting))
            except TimeoutError:
                raise FleetError(
                    ErrorCode.RUNTIME_BUDGET_EXCEEDED,
                    "The remaining active runtime time budget was exhausted.",
                    "Review preserved usage and artifacts; approval does not reset this limit.",
                ) from None
            if isinstance(result.output, FleetPatch):
                validate_fleet_patch(
                    result.output,
                    current_fleet_spec_sha256=result.output.base_fleet_spec_sha256,
                    redactor=self.redactor,
                )
            raw_result = result.model_dump(mode="json", warnings=False)
            self._reject_untrusted_secrets(raw_result)
            validated_result: AgentInvocationResult | None = None
            with suppress(ValueError, TypeError):
                # A harness returns data, not an already-trusted domain object.
                # Reparse even model_copy/model_construct results at this boundary.
                validated_result = AgentInvocationResult.model_validate(raw_result)
            if validated_result is None:
                raise FleetError(
                    ErrorCode.RUNTIME_OUTPUT_INVALID,
                    "The runtime returned data outside the bounded output contract.",
                    "Use the exact structured output schema for the active role.",
                ) from None
            result = validated_result
            expected_outputs: dict[
                str,
                tuple[
                    type[ScopeDecision]
                    | type[FleetPatch]
                    | type[ImplementationReport]
                    | type[VerifierVerdict]
                    | type[SpecialistReport],
                    ...,
                ],
            ] = {
                AgentRole.COS.value: (ScopeDecision, FleetPatch),
                AgentRole.ENGINEER.value: (ImplementationReport,),
                AgentRole.VERIFIER.value: (VerifierVerdict,),
                AgentRole.RESEARCHER.value: (SpecialistReport,),
                AgentRole.ARCHITECT.value: (SpecialistReport,),
            }
            expected_output = expected_outputs.get(str(request.role))
            if expected_output is None or not isinstance(result.output, expected_output):
                raise FleetError(
                    ErrorCode.RUNTIME_OUTPUT_INVALID,
                    f"The {agent.role} runtime returned the wrong structured output type.",
                    "Use a runtime that returns the project schema for the active role.",
                )
            accounting.finish(RuntimeAttemptStatus.COMPLETED)
            attempt_finished = True
            completed = agent.model_copy(
                update={"status": AgentStatus.COMPLETED, "completed_at": self.clock.now()}
            )
            self.state.save_agent_instance(completed)
            self._emit(
                run,
                "agent.completed",
                {"role": str(agent.role), "iteration": agent.iteration},
                agent_id=agent.agent_instance_id,
            )
            return result
        except ApprovalRequiredError:
            if accounting is not None and not attempt_finished:
                accounting.finish(RuntimeAttemptStatus.PAUSED)
            self.state.save_agent_instance(agent.model_copy(update={"status": AgentStatus.PAUSED}))
            self._emit(
                run,
                "agent.paused",
                {"role": str(agent.role), "iteration": agent.iteration},
                agent_id=agent.agent_instance_id,
            )
            raise
        except FleetError as error:
            if accounting is not None and not attempt_finished:
                accounting.finish(RuntimeAttemptStatus.FAILED, error_code=error.code)
            self._mark_agent_failed(run, agent, error.code)
            raise
        except asyncio.CancelledError:
            if accounting is not None and not attempt_finished:
                accounting.finish(RuntimeAttemptStatus.CANCELLED)
            self.state.save_agent_instance(
                agent.model_copy(
                    update={"status": AgentStatus.CANCELLED, "completed_at": self.clock.now()}
                )
            )
            self._emit(
                run,
                "agent.cancelled",
                {"role": str(agent.role), "iteration": agent.iteration},
                agent_id=agent.agent_instance_id,
            )
            raise
        except Exception:
            if accounting is not None and not attempt_finished:
                accounting.finish(RuntimeAttemptStatus.FAILED, error_code=ErrorCode.INTERNAL_ERROR)
            self._mark_agent_failed(run, agent, ErrorCode.INTERNAL_ERROR)
        # Leave the exception handler before raising so even inspectable
        # __context__ cannot retain a raw provider/harness exception.
        raise FleetError(
            ErrorCode.INTERNAL_ERROR,
            f"The {agent.role} runtime invocation failed unexpectedly.",
            "Inspect redacted run events and retry with a healthy runtime.",
        ) from None

    def _mark_agent_failed(
        self,
        run: Run,
        agent: AgentInstance,
        error_code: ErrorCode,
    ) -> None:
        failed = agent.model_copy(
            update={"status": AgentStatus.FAILED, "completed_at": self.clock.now()}
        )
        self.state.save_agent_instance(failed)
        self._emit(
            run,
            "agent.failed",
            {"role": str(agent.role), "code": error_code.value},
            agent_id=agent.agent_instance_id,
        )

    @staticmethod
    def _runtime_input(run: Run, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        capabilities = run.sandbox_capabilities_snapshot
        enriched: dict[str, JsonValue] = {
            **value,
            "sandbox_capabilities": (
                capabilities.model_dump(mode="json") if capabilities is not None else None
            ),
        }
        if run.runtime_name == "fake":
            enriched["fake_scenario"] = run.fake_scenario.value
        return enriched

    @staticmethod
    def _runtime_configuration(run: Run) -> RuntimeConfiguration:
        return RuntimeConfiguration(
            runtime_name=run.runtime_name,
            provider_model=run.provider_model,
            credential_ref=run.credential_ref,
        )

    def _persist_runtime_observation(
        self,
        run: Run,
        task_id: str,
        agent_id: str,
        role: str,
        result: AgentInvocationResult,
    ) -> Run:
        if (
            result.usage is None
            and result.provider_metadata is None
            and result.checkpoint_ref is None
        ):
            return self.state.get_run(run.run_id)
        observation: dict[str, JsonValue] = {
            "role": role,
            "agent_instance_id": agent_id,
            "usage": (result.usage.model_dump(mode="json") if result.usage is not None else None),
            "provider_metadata": (
                result.provider_metadata.model_dump(mode="json")
                if result.provider_metadata is not None
                else None
            ),
            "checkpoint_ref": result.checkpoint_ref,
        }
        self._reject_untrusted_secrets(observation)
        artifact = self.artifacts.create_text(
            kind=ArtifactKind.RUNTIME_USAGE,
            project_id=run.project_id,
            run_id=run.run_id,
            task_id=task_id,
            producer=f"{run.runtime_name}-runtime",
            content=json.dumps(observation, indent=2, sort_keys=True) + "\n",
            mime_type="application/json",
        )
        latest = self.state.get_run(run.run_id)
        updated = latest.model_copy(
            update={
                "runtime_usage_artifact_ids": [
                    *latest.runtime_usage_artifact_ids,
                    artifact.artifact_id,
                ],
                "updated_at": self.clock.now(),
            }
        )
        return self.state.save_run(
            updated,
            "runtime.usage_recorded",
            {
                "role": role,
                "agent_instance_id": agent_id,
                "usage_artifact_id": artifact.artifact_id,
            },
        )

    def _command_evidence_ids(self, records: tuple[RuntimeToolExecutionRecord, ...]) -> list[str]:
        result: list[str] = []
        for record in records:
            for artifact_id in record.artifact_ids:
                if self.state.get_artifact(artifact_id).kind is ArtifactKind.COMMAND_EVIDENCE:
                    result.append(artifact_id)
        return list(dict.fromkeys(result))

    def _read_json_context(self, artifact_id: str) -> JsonValue:
        try:
            value = json.loads(self.artifacts.read_text(artifact_id))
        except (TypeError, ValueError):
            raise FleetError(
                ErrorCode.ARTIFACT_INTEGRITY_FAILED,
                "A runtime context artifact is not valid JSON.",
                "Re-initialize the project from trusted repository metadata.",
            ) from None
        validated = cast(JsonValue, value)
        self._reject_untrusted_secrets(validated)
        return validated

    @staticmethod
    def _build_invocation(
        *,
        run_id: str,
        task_id: str,
        agent_instance_id: str,
        role: AgentRole,
        stage: WorkflowStage,
        iteration: int,
        max_steps: int,
        instructions: str,
        context_artifact_ids: list[str],
        input: dict[str, JsonValue],
    ) -> AgentInvocation:
        invocation: AgentInvocation | None = None
        with suppress(ValidationError):
            invocation = AgentInvocation(
                run_id=run_id,
                task_id=task_id,
                agent_instance_id=agent_instance_id,
                role=role,
                stage=stage,
                iteration=iteration,
                max_steps=max_steps,
                instructions=instructions,
                context_artifact_ids=context_artifact_ids,
                input=input,
            )
        if invocation is None:
            raise FleetError(
                ErrorCode.RUNTIME_BUDGET_EXCEEDED,
                "The runtime invocation context exceeds the bounded input contract.",
                "Reduce repository metadata or task context before starting a new run.",
            ) from None
        return invocation

    def _active_role_guidance(self, run: Run, role: AgentRole) -> str:
        spec, snapshot = self._active_role_configuration(run)
        return self._role_guidance(spec, snapshot, role)

    def _active_role_max_steps(self, run: Run, role: AgentRole, *, ceiling: int) -> int:
        spec, _ = self._active_role_configuration(run)
        return min(ceiling, spec.spec.agents[role.value].max_steps)

    def _active_role_configuration(self, run: Run) -> tuple[FleetSpec, ConfigSnapshot]:
        project = self.state.get_project(run.project_id)
        spec, snapshot = self.config.load_snapshot(
            Path(project.canonical_root) / ".fleet" / "fleet.yaml"
        )
        snapshot_hash = self.config.snapshot_hash(snapshot)
        if run.config_snapshot_hash is None or snapshot_hash != run.config_snapshot_hash:
            raise FleetError(
                ErrorCode.CONFIG_INVALID,
                "The Fleet role guidance changed after the task was bound.",
                "Restore the exact Run-bound configuration or start a new run.",
            )
        return spec, snapshot

    def _repair_feedback(self, run: Run) -> JsonValue:
        if not run.repair_iterations:
            return None
        artifact_id = run.verifier_verdict_artifact_id
        if artifact_id is None:
            raise FleetError(
                ErrorCode.ARTIFACT_INTEGRITY_FAILED,
                "Repair requires the preceding independent verifier verdict.",
                "Recover this run instead of reconstructing feedback from model claims.",
            )
        metadata = self.state.get_artifact(artifact_id)
        if (
            metadata.kind is not ArtifactKind.VERIFIER_VERDICT
            or metadata.run_id != run.run_id
            or metadata.task_id != run.task_id
            or metadata.project_id != run.project_id
        ):
            raise FleetError(
                ErrorCode.ARTIFACT_INTEGRITY_FAILED,
                "Repair feedback is not bound to this task.",
                "Do not reuse another task's verifier artifact.",
            )
        try:
            verdict = VerifierVerdict.model_validate_json(self.artifacts.read_text(artifact_id))
        except ValueError:
            raise FleetError(
                ErrorCode.ARTIFACT_INTEGRITY_FAILED,
                "Repair feedback does not match the verifier schema.",
                "Inspect the redacted artifact and recover this run.",
            ) from None
        feedback = verdict.model_dump(mode="json")
        self._reject_untrusted_secrets(feedback)
        self._bounded_runtime_text(json.dumps(feedback), max_bytes=32_768)
        return feedback

    @staticmethod
    def _role_guidance(spec: FleetSpec, snapshot: ConfigSnapshot, role: AgentRole) -> str:
        request = spec.spec.agents.get(role.value)
        if request is None:
            raise FleetError(
                ErrorCode.CONFIG_INVALID,
                "The active FleetSpec does not define the required runtime role.",
                "Restore the generated CoS, Engineer, and Verifier role definitions.",
            )
        contents = {item.path: item.content for item in snapshot.files}
        guidance = contents.get(request.instructions)
        if guidance is None:
            raise FleetError(
                ErrorCode.CONFIG_INVALID,
                "The required runtime role guidance is missing from ConfigSnapshot.",
                "Restore the exact registered role file, or review a supported FleetPatch "
                "before starting a new Run.",
            )
        if len(guidance.encode("utf-8")) > _MAX_ROLE_GUIDANCE_BYTES:
            raise FleetError(
                ErrorCode.RUNTIME_BUDGET_EXCEEDED,
                "Runtime role guidance exceeds the Phase 2 input ceiling.",
                "Reduce the referenced role guidance below 32768 UTF-8 bytes.",
                details={"max_role_guidance_bytes": _MAX_ROLE_GUIDANCE_BYTES},
            )
        return guidance

    @staticmethod
    def _bounded_runtime_text(value: str, *, max_bytes: int = 120_000) -> str:
        if len(value.encode("utf-8")) > max_bytes:
            raise FleetError(
                ErrorCode.RUNTIME_BUDGET_EXCEEDED,
                "Runtime patch context exceeds the Phase 2 input ceiling.",
                "Reduce the task scope or review the patch without a model invocation.",
                details={"max_patch_context_bytes": max_bytes},
            )
        return value

    def _persist_evidence(self, run: Run) -> tuple[Run, EvidenceBundle]:
        current = self.state.get_run(run.run_id)
        if current.evidence_bundle_artifact_id is not None:
            bundle = EvidenceBundle.model_validate_json(
                self.artifacts.read_text(current.evidence_bundle_artifact_id)
            )
            return current, bundle
        if current.task_id is None:
            raise RuntimeError("evidence run has no task")
        task = self.state.get_task(current.task_id)
        bundle = self.evidence.assemble(current, task)
        evidence_artifact = self.artifacts.create_text(
            kind=ArtifactKind.EVIDENCE_BUNDLE,
            project_id=current.project_id,
            run_id=current.run_id,
            task_id=task.task_id,
            producer="control-plane",
            content=bundle.model_dump_json(indent=2),
            mime_type="application/json",
        )
        if bundle.completion_decision is None:
            raise RuntimeError("EvidenceBundle has no completion decision")
        decision = bundle.completion_decision
        updated = current.model_copy(
            update={
                "evidence_bundle_artifact_id": evidence_artifact.artifact_id,
                "evidence_bundle_hash": evidence_artifact.sha256,
                "assurance_verdict": decision.effective_verdict,
                "verified_complete": decision.verified_complete,
                "updated_at": self.clock.now(),
            }
        )
        self.state.save_run(
            updated,
            "evidence.assembled",
            {
                "evidence_bundle_artifact_id": evidence_artifact.artifact_id,
                "verified_complete": updated.verified_complete,
                "assurance_verdict": decision.effective_verdict.value,
                "reason_codes": decision.reason_codes,
            },
        )
        return updated, bundle

    def _persist_cleanup_receipt(self, run: Run) -> Run:
        current = self.state.get_run(run.run_id)
        if current.cleanup_receipt_artifact_id is not None:
            return current
        if current.task_id is None:
            raise RuntimeError("cleanup receipt run has no task")
        leases = list(self.state.list_leases(current.run_id))
        if any(
            lease.status not in {LeaseStatus.RELEASED, LeaseStatus.RECOVERED} for lease in leases
        ):
            raise FleetError(
                ErrorCode.SANDBOX_CLEANUP_FAILED,
                "A run lease is not terminal after cleanup.",
                "Run Fleet recovery before trusting or publishing this result.",
            )
        receipt = ResourceCleanupReceipt(
            run_id=current.run_id,
            leases=[
                CleanupLeaseRecord(
                    lease_id=lease.lease_id,
                    kind=lease.kind,
                    resource_id=lease.resource_id,
                    status=lease.status,
                )
                for lease in leases
            ],
            complete=True,
            completed_at=self.clock.now(),
        )
        artifact = self.artifacts.create_text(
            kind=ArtifactKind.RESOURCE_CLEANUP,
            project_id=current.project_id,
            run_id=current.run_id,
            task_id=current.task_id,
            producer="resource-service",
            content=receipt.model_dump_json(indent=2),
            mime_type="application/json",
        )
        updated = current.model_copy(
            update={
                "cleanup_receipt_artifact_id": artifact.artifact_id,
                "cleanup_receipt_sha256": artifact.sha256,
                "updated_at": self.clock.now(),
            }
        )
        self.state.save_run(
            updated,
            "resources.cleanup_recorded",
            {
                "cleanup_receipt_artifact_id": artifact.artifact_id,
                "lease_count": len(leases),
            },
        )
        return updated

    def _persist_failure_evidence(self, run: Run, error: FleetError) -> Run:
        if (
            run.task_id is None
            or run.fleet_plan_artifact_id is None
            or error.code is ErrorCode.ARTIFACT_INTEGRITY_FAILED
        ):
            return run
        try:
            return self._persist_evidence(run)[0]
        except FleetError as evidence_error:
            if evidence_error.code not in {
                ErrorCode.ARTIFACT_INTEGRITY_FAILED,
                ErrorCode.RECOVERY_REQUIRED,
            }:
                raise
            # Incomplete or corrupted provenance must not interrupt the original
            # failed-run transition and cleanup with a second assembly error.
            self._emit(
                run,
                "evidence.unavailable",
                {"code": evidence_error.code.value, "original_failure_code": error.code.value},
            )
            return run

    def _reject_untrusted_secrets(self, value: object) -> None:
        if self.redactor.contains_secret_data(value):
            raise FleetError(
                ErrorCode.COMMAND_DENIED,
                "Untrusted workflow data contained registered secret material.",
                "Remove secret material from runtime input or output and start a new run; it "
                "was not persisted.",
            )

    def _transition(self, run: Run, status: RunStatus, stage: WorkflowStage) -> Run:
        updated = run.model_copy(
            update={"status": status, "stage": stage, "updated_at": self.clock.now()}
        )
        return self.state.save_run(
            updated,
            "run.stage_changed",
            {"status": status.value, "stage": stage.value},
        )

    def _emit(
        self,
        run: Run,
        event_type: str,
        payload: dict[str, JsonValue],
        *,
        agent_id: str | None = None,
    ) -> None:
        cleaned, summary = self.redactor.redact_data(payload)
        self.state.append_event(
            FleetEvent(
                event_id=self.ids.new(IdPrefix.EVENT),
                event_type=event_type,
                occurred_at=self.clock.now(),
                project_id=run.project_id,
                run_id=run.run_id,
                task_id=run.task_id,
                agent_instance_id=agent_id,
                correlation_id=run.correlation_id,
                payload=cast(dict[str, JsonValue], cleaned),
                redaction_summary=summary,
            )
        )
