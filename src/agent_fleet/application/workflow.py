"""Explicit, resumable CoS -> Engineer -> Verifier Phase 1 workflow."""

from __future__ import annotations

import json
from contextlib import suppress
from pathlib import Path
from typing import cast

from pydantic import JsonValue, ValidationError

from agent_fleet.application.artifacts import ArtifactService
from agent_fleet.application.evidence import EvidenceAssembler
from agent_fleet.application.gateway import ToolGateway
from agent_fleet.application.planning import FleetPlanner
from agent_fleet.application.resources import ResourceService
from agent_fleet.application.runtime import RuntimeRegistry
from agent_fleet.application.runtime_tools import GatewayRuntimeToolCatalog
from agent_fleet.domain.config import ConfigSnapshot, FleetSpec
from agent_fleet.domain.errors import (
    ApprovalDeniedError,
    ApprovalRequiredError,
    ErrorCode,
    FleetError,
)
from agent_fleet.domain.evidence import EvidenceBundle
from agent_fleet.domain.fleet_plan import FleetStrategy
from agent_fleet.domain.ids import IdPrefix
from agent_fleet.domain.models import (
    AgentInstance,
    AgentInvocation,
    AgentInvocationResult,
    AgentRole,
    AgentStatus,
    ArtifactKind,
    FakeScenario,
    FleetEvent,
    ImplementationReport,
    Run,
    RunStatus,
    RuntimeCapability,
    RuntimeConfiguration,
    RuntimeCredentialCheck,
    RuntimeToolExecutionRecord,
    SandboxCapabilities,
    SandboxSpec,
    ScopeDecision,
    TaskSpec,
    Verdict,
    VerifierVerdict,
    WorkflowStage,
    WorkspaceKind,
)
from agent_fleet.domain.security import Redactor
from agent_fleet.ports.clock import Clock
from agent_fleet.ports.config import ConfigurationPort
from agent_fleet.ports.id_generator import IdGenerator
from agent_fleet.ports.repository import RepositoryPort
from agent_fleet.ports.runtime import (
    EMPTY_RUNTIME_TOOL_CATALOG,
    RuntimeAdapter,
    RuntimeInvocationServices,
)
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
        self.redactor = redactor

    async def start(
        self,
        *,
        project_path: Path,
        goal: str,
        runtime_name: str | None,
        sandbox_name: str,
        fake_scenario: FakeScenario | None,
        provider_model: str | None = None,
        credential_ref: str | None = None,
    ) -> Run:
        self._reject_untrusted_secrets(
            {
                "project_path": str(project_path),
                "runtime_name": runtime_name,
                "sandbox_name": sandbox_name,
                "provider_model": provider_model,
            }
        )
        if sandbox_name != "fake" or self.sandbox.capabilities != SandboxCapabilities.phase1_fake():
            raise FleetError(
                ErrorCode.SANDBOX_UNAVAILABLE,
                "Only the non-isolating fake sandbox is available in Phase 2.",
                "Use `--sandbox fake`; Docker execution begins in Phase 3.",
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
                "Preview the desired initialization, then move the conflicting generated "
                ".fleet tree and re-run `fleet init` with explicit provider options.",
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
                "Run `fleet init --preview`; after review, move the conflicting generated "
                ".fleet tree and initialize again with explicit options.",
            )
        if (
            spec.spec.runtime.adapter != selected_runtime
            or spec.spec.runtime.provider_model != selected_provider_model
        ):
            raise FleetError(
                ErrorCode.CONFIG_INVALID,
                "The active FleetSpec runtime differs from Fleet-owned project settings.",
                "Review the repository configuration with `fleet init --preview` before "
                "reinitializing explicitly.",
            )
        self.runtimes.require(
            runtime_configuration,
            required_capabilities=spec.spec.runtime.required_capabilities,
            credential_check=RuntimeCredentialCheck.NONE,
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
            fake_scenario=selected_fake_scenario,
            max_repair_iterations=spec.spec.workflows["code-change"].max_repair_iterations,
            created_at=now,
            updated_at=now,
        )
        self.state.create_run(run)
        try:
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
                return await self._continue(run)
            run = self._transition(run, RunStatus.RUNNING, WorkflowStage.WORKSPACE_PREPARATION)
            await self._prepare_workspace(run)
            run = self._transition(run, RunStatus.RUNNING, WorkflowStage.IMPLEMENTING)
            return await self._continue(run)
        except ApprovalRequiredError:
            return self.state.get_run(run.run_id)
        except FleetError as error:
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
            raise

    async def resume(self, run_id: str) -> Run:
        run = self.state.get_run(run_id)
        if run.status in {
            RunStatus.COMPLETED,
            RunStatus.REJECTED,
            RunStatus.CANCELLED,
            RunStatus.FAILED,
            RunStatus.ABANDONED,
            RunStatus.READY_FOR_REVIEW,
        }:
            return run
        runtime_configuration = self._runtime_configuration(run)
        self.runtimes.require(
            runtime_configuration,
            required_capabilities=_MINIMUM_RUNTIME_CAPABILITIES,
            credential_check=RuntimeCredentialCheck.RESOLVE,
        )
        project = self.state.get_project(run.project_id)
        spec, snapshot = self.config.load_snapshot(
            Path(project.canonical_root) / ".fleet" / "fleet.yaml"
        )
        snapshot_hash = self.config.snapshot_hash(snapshot)
        if run.config_snapshot_hash is not None and snapshot_hash != run.config_snapshot_hash:
            raise FleetError(
                ErrorCode.CONFIG_INVALID,
                "The Fleet configuration changed while the run was paused.",
                "Restore the reviewed configuration or abandon this run and initialize again.",
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
            return await self._continue(run)
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
        invocation_input: dict[str, JsonValue] = {"goal": run.goal}
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
            max_steps=10,
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
                tools=EMPTY_RUNTIME_TOOL_CATALOG,
            ),
        )
        decision = cast(ScopeDecision, result.output)
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
            created_at=self.clock.now(),
        )
        strategy = FleetStrategy(decision.fleet_strategy)
        plan = self.planner.create(run, task, strategy, known_roles=known_roles)
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
        return run

    async def _prepare_workspace(self, run: Run) -> None:
        project = self.state.get_project(run.project_id)
        candidate = self.repository.create_workspace(
            Path(project.canonical_root),
            run.run_id,
            run.base_revision,
            WorkspaceKind.CANDIDATE,
        )
        self.resources.lease_workspace(candidate)
        handle = await self.sandbox.create(
            run.run_id,
            SandboxSpec(workspace_host_path=candidate.path, environment={}),
        )
        self.resources.lease_sandbox(handle)

    async def _continue(self, run: Run) -> Run:
        while True:
            run = self.state.get_run(run.run_id)
            if run.status is RunStatus.PAUSED_FOR_APPROVAL:
                return run
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
                run, bundle = self._persist_evidence(run)
                if bundle.completion_decision is None:
                    raise RuntimeError("EvidenceBundle has no completion decision")
                decision = bundle.completion_decision
                operational_status = (
                    RunStatus.COMPLETED
                    if run.fleet_strategy == FleetStrategy.DIRECT.value
                    else RunStatus.READY_FOR_REVIEW
                )
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
                        "sandbox=fake\nsecurity_level=fake\n"
                        "proof_gap=FakeSandbox did not execute project code.\n"
                    ),
                )
                await self.resources.cleanup_run(run)
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

    async def _engineer(self, run: Run) -> None:
        if run.task_id is None:
            raise RuntimeError("run has no task")
        task = self.state.get_task(run.task_id)
        guidance = self._active_role_guidance(run, AgentRole.ENGINEER)
        workspace = self.resources.candidate_workspace(run.run_id)
        handle = self.resources.engineer_sandbox(run.run_id)
        agent = AgentInstance(
            agent_instance_id=self.ids.new(IdPrefix.AGENT),
            run_id=run.run_id,
            task_id=task.task_id,
            role=AgentRole.ENGINEER,
            status=AgentStatus.RUNNING,
            iteration=run.repair_iterations,
            created_at=self.clock.now(),
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
            max_steps=20,
            instructions=guidance,
            context_artifact_ids=[
                item
                for item in (
                    run.task_spec_artifact_id,
                    run.fleet_plan_artifact_id,
                    run.config_snapshot_artifact_id,
                )
                if item is not None
            ],
            input=self._runtime_input(
                run,
                {
                    "task_spec": task.model_dump(mode="json"),
                    "repair_iterations": run.repair_iterations,
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
            path not in task.allowed_paths for path in patch.changed_paths
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
        project = self.state.get_project(run.project_id)
        patch = self.artifacts.read_text(run.patch_artifact_id).encode()
        workspace = self.repository.create_workspace(
            Path(project.canonical_root),
            run.run_id,
            run.base_revision,
            WorkspaceKind.VERIFICATION,
        )
        workspace_lease = self.resources.lease_workspace(workspace)
        self.repository.apply_patch_to_workspace(workspace, patch)
        before = self.repository.workspace_status_fingerprint(workspace)
        handle = await self.sandbox.create(
            run.run_id, SandboxSpec(workspace_host_path=workspace.path, environment={})
        )
        sandbox_lease = self.resources.lease_sandbox(handle)
        agent = AgentInstance(
            agent_instance_id=self.ids.new(IdPrefix.AGENT),
            run_id=run.run_id,
            task_id=task.task_id,
            role=AgentRole.VERIFIER,
            status=AgentStatus.RUNNING,
            iteration=run.repair_iterations,
            created_at=self.clock.now(),
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
            max_steps=10,
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
        mutated = before != after
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
        latest = self.state.get_run(run.run_id)
        updated = latest.model_copy(
            update={
                "command_evidence_artifact_ids": list(
                    dict.fromkeys([*latest.command_evidence_artifact_ids, *evidence_artifact_ids])
                ),
                "verifier_agent_instance_id": agent.agent_instance_id,
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
                "security_level": self.sandbox.capabilities.security_level.value,
            },
        )
        await self.resources.cleanup_lease(updated, sandbox_lease)
        await self.resources.cleanup_lease(updated, workspace_lease)
        return bound_verdict

    async def _invoke_runtime_agent(
        self,
        run: Run,
        agent: AgentInstance,
        adapter: RuntimeAdapter,
        request: AgentInvocation,
        services: RuntimeInvocationServices,
    ) -> AgentInvocationResult:
        try:
            result = await adapter.invoke(request, services)
            self._reject_untrusted_secrets(result.model_dump(mode="json"))
            expected_outputs: dict[
                str,
                type[ScopeDecision] | type[ImplementationReport] | type[VerifierVerdict],
            ] = {
                AgentRole.COS.value: ScopeDecision,
                AgentRole.ENGINEER.value: ImplementationReport,
                AgentRole.VERIFIER.value: VerifierVerdict,
            }
            expected_output = expected_outputs.get(str(request.role))
            if expected_output is None or not isinstance(result.output, expected_output):
                raise FleetError(
                    ErrorCode.RUNTIME_OUTPUT_INVALID,
                    f"The {agent.role} runtime returned the wrong structured output type.",
                    "Use a runtime that returns the project schema for the active role.",
                )
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
        except FleetError as error:
            self._mark_agent_failed(run, agent, error.code)
            raise
        except Exception:
            self._mark_agent_failed(run, agent, ErrorCode.INTERNAL_ERROR)
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
        if run.runtime_name == "fake":
            return {**value, "fake_scenario": run.fake_scenario.value}
        return value

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
        return self._role_guidance(spec, snapshot, role)

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
                "Restore the referenced role file and initialize again.",
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

    def _persist_failure_evidence(self, run: Run, error: FleetError) -> Run:
        if (
            run.task_id is None
            or run.fleet_plan_artifact_id is None
            or error.code is ErrorCode.ARTIFACT_INTEGRITY_FAILED
        ):
            return run
        return self._persist_evidence(run)[0]

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
