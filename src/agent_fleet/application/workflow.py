"""Explicit, resumable CoS -> Engineer -> Verifier Phase 1 workflow."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from pydantic import JsonValue

from agent_fleet.application.artifacts import ArtifactService
from agent_fleet.application.gateway import ToolGateway
from agent_fleet.application.resources import ResourceService
from agent_fleet.domain.errors import (
    ApprovalDeniedError,
    ApprovalRequiredError,
    ErrorCode,
    FleetError,
)
from agent_fleet.domain.ids import IdPrefix
from agent_fleet.domain.models import (
    AcceptanceCriterion,
    AgentInstance,
    AgentInvocation,
    AgentRole,
    AgentStatus,
    ArtifactKind,
    EngineerScript,
    FakeScenario,
    FleetEvent,
    Run,
    RunStatus,
    SandboxSpec,
    TaskSpec,
    Verdict,
    VerifierScript,
    WorkflowStage,
    WorkspaceKind,
)
from agent_fleet.domain.security import Redactor
from agent_fleet.ports.clock import Clock
from agent_fleet.ports.config import ConfigurationPort
from agent_fleet.ports.id_generator import IdGenerator
from agent_fleet.ports.repository import RepositoryPort
from agent_fleet.ports.runtime import RuntimeAdapter
from agent_fleet.ports.sandbox import SandboxProvider
from agent_fleet.ports.state_store import StateStore


class WorkflowEngine:
    def __init__(
        self,
        state: StateStore,
        repository: RepositoryPort,
        runtime: RuntimeAdapter,
        sandbox: SandboxProvider,
        artifacts: ArtifactService,
        gateway: ToolGateway,
        resources: ResourceService,
        config: ConfigurationPort,
        clock: Clock,
        ids: IdGenerator,
        redactor: Redactor,
    ) -> None:
        self.state = state
        self.repository = repository
        self.runtime = runtime
        self.sandbox = sandbox
        self.artifacts = artifacts
        self.gateway = gateway
        self.resources = resources
        self.config = config
        self.clock = clock
        self.ids = ids
        self.redactor = redactor

    async def start(
        self,
        *,
        project_path: Path,
        goal: str,
        runtime_name: str,
        sandbox_name: str,
        fake_scenario: FakeScenario,
    ) -> Run:
        if runtime_name != "fake":
            raise FleetError(
                ErrorCode.RUNTIME_UNAVAILABLE,
                f"Runtime {runtime_name!r} is unavailable in Phase 0/1.",
                "Use `--runtime fake`; real provider calls begin in Phase 2.",
            )
        if sandbox_name != "fake" or self.sandbox.security_level.value != "fake":
            raise FleetError(
                ErrorCode.SANDBOX_UNAVAILABLE,
                "Only the non-isolating fake sandbox is available in Phase 0/1.",
                "Use `--sandbox fake`; Docker execution begins in Phase 3.",
            )
        info = self.repository.inspect(project_path)
        project = self.state.get_project_by_root(info.root)
        if project is None:
            raise FleetError(
                ErrorCode.PROJECT_NOT_INITIALIZED,
                "The repository is not registered with this Fleet state directory.",
                "Run `fleet init <path> --runtime fake --sandbox fake --yes` first.",
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
        spec_path = Path(project.canonical_root) / ".fleet" / "fleet.yaml"
        spec = self.config.load(spec_path)
        config_hash = self.config.hash(spec)
        if config_hash != project.fleet_spec_hash:
            raise FleetError(
                ErrorCode.CONFIG_INVALID,
                "The active FleetSpec differs from the registered validated version.",
                "Re-run `fleet init` only after reviewing the configuration change.",
            )
        redacted_goal, _ = self.redactor.redact_text(goal)
        now = self.clock.now()
        run = Run(
            run_id=self.ids.new(IdPrefix.RUN),
            project_id=project.project_id,
            correlation_id=self.ids.new(IdPrefix.CORRELATION),
            goal=redacted_goal,
            base_revision=info.head_revision,
            target_status_fingerprint=info.status_fingerprint,
            fake_scenario=fake_scenario,
            max_repair_iterations=spec.spec.workflows["code-change"].max_repair_iterations,
            created_at=now,
            updated_at=now,
        )
        self.state.create_run(run)
        try:
            run = self._transition(run, RunStatus.RUNNING, WorkflowStage.INTAKE)
            run = self._transition(run, RunStatus.RUNNING, WorkflowStage.SCOPING)
            run = await self._scope(run, config_hash)
            run = self._transition(run, RunStatus.RUNNING, WorkflowStage.WORKSPACE_PREPARATION)
            await self._prepare_workspace(run)
            run = self._transition(run, RunStatus.RUNNING, WorkflowStage.IMPLEMENTING)
            return await self._continue(run)
        except ApprovalRequiredError:
            return self.state.get_run(run.run_id)
        except FleetError as error:
            latest = self.state.get_run(run.run_id)
            if latest.status is not RunStatus.PAUSED_FOR_APPROVAL:
                failed = latest.model_copy(
                    update={"status": RunStatus.FAILED, "updated_at": self.clock.now()}
                )
                self.state.save_run(
                    failed,
                    "run.failed",
                    {"code": error.code.value, "message": error.message},
                )
                await self.resources.cleanup_run(failed)
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
            rejected = self.state.get_run(run_id).model_copy(
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
                failed = latest.model_copy(
                    update={"status": RunStatus.FAILED, "updated_at": self.clock.now()}
                )
                self.state.save_run(
                    failed,
                    "run.failed",
                    {"code": error.code.value, "message": error.message},
                )
                await self.resources.cleanup_run(failed)
            raise

    async def _scope(self, run: Run, config_hash: str) -> Run:
        task_id = self.ids.new(IdPrefix.TASK)
        agent_id = self.ids.new(IdPrefix.AGENT)
        result = await self.runtime.invoke(
            AgentInvocation(
                run_id=run.run_id,
                task_id=task_id,
                agent_instance_id=agent_id,
                role=AgentRole.COS,
                stage=WorkflowStage.SCOPING,
                iteration=0,
                max_steps=10,
                input={"goal": run.goal, "fake_scenario": run.fake_scenario.value},
            )
        )
        acceptance = [
            AcceptanceCriterion.model_validate(item)
            for item in cast(list[dict[str, JsonValue]], result.output["acceptance_criteria"])
        ]
        task = TaskSpec(
            task_id=task_id,
            run_id=run.run_id,
            original_goal=run.goal,
            normalized_goal=str(result.output["normalized_goal"]),
            base_revision=run.base_revision,
            allowed_paths=cast(list[str], result.output["allowed_paths"]),
            forbidden_paths=cast(list[str], result.output["forbidden_paths"]),
            acceptance_criteria=acceptance,
            required_evidence=cast(list[str], result.output["required_evidence"]),
            max_repair_iterations=run.max_repair_iterations,
            config_snapshot_hash=config_hash,
            created_at=self.clock.now(),
        )
        run = run.model_copy(update={"task_id": task_id, "updated_at": self.clock.now()})
        self.state.save_run(run, "run.task_bound", {"task_id": task_id})
        self.state.save_task(task)
        instance = AgentInstance(
            agent_instance_id=agent_id,
            run_id=run.run_id,
            task_id=task.task_id,
            role=AgentRole.COS,
            status=AgentStatus.COMPLETED,
            iteration=0,
            created_at=self.clock.now(),
            completed_at=self.clock.now(),
        )
        self.state.save_agent_instance(instance)
        self._emit(run, "agent.completed", {"role": "cos"}, agent_id=agent_id)
        self.artifacts.create_text(
            kind=ArtifactKind.TASK_SPEC,
            project_id=run.project_id,
            run_id=run.run_id,
            task_id=task.task_id,
            producer="control-plane",
            content=task.model_dump_json(indent=2),
            mime_type="application/json",
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
                run = self._transition(run, RunStatus.RUNNING, WorkflowStage.VERIFYING)
                continue
            if run.stage is WorkflowStage.VERIFYING:
                verifier = await self._verify(run)
                run = self.state.get_run(run.run_id)
                if verifier.verdict.verdict is Verdict.FAIL:
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
                self.artifacts.create_text(
                    kind=ArtifactKind.RUN_SUMMARY,
                    project_id=run.project_id,
                    run_id=run.run_id,
                    task_id=run.task_id,
                    producer="control-plane",
                    content=(
                        "status=ready_for_review\n"
                        f"patch_sha256={run.patch_sha256}\n"
                        "runtime=fake\nsandbox=fake\nsecurity_level=fake\n"
                        "limitation=No model or project code executed.\n"
                    ),
                )
                await self.resources.cleanup_run(run)
                ready = run.model_copy(
                    update={"status": RunStatus.READY_FOR_REVIEW, "updated_at": self.clock.now()}
                )
                self.state.save_run(
                    ready,
                    "patch.ready",
                    {"patch_artifact_id": run.patch_artifact_id, "patch_sha256": run.patch_sha256},
                )
                return ready
            return run

    async def _engineer(self, run: Run) -> None:
        if run.task_id is None:
            raise RuntimeError("run has no task")
        task = self.state.get_task(run.task_id)
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
        self.state.save_agent_instance(agent)
        self._emit(
            run,
            "agent.started",
            {"role": "engineer", "iteration": run.repair_iterations},
            agent_id=agent.agent_instance_id,
        )
        result = await self.runtime.invoke(
            AgentInvocation(
                run_id=run.run_id,
                task_id=task.task_id,
                agent_instance_id=agent.agent_instance_id,
                role=AgentRole.ENGINEER,
                stage=run.stage or WorkflowStage.IMPLEMENTING,
                iteration=run.repair_iterations,
                max_steps=20,
                input={
                    "goal": task.normalized_goal,
                    "fake_scenario": run.fake_scenario.value,
                    "repair_iterations": run.repair_iterations,
                },
            )
        )
        script = EngineerScript.model_validate(result.output)
        for action in script.actions:
            await self.gateway.execute(
                run=run,
                task=task,
                agent=agent,
                workspace=workspace,
                sandbox_handle=handle,
                scripted=action,
            )
        completed = agent.model_copy(
            update={"status": AgentStatus.COMPLETED, "completed_at": self.clock.now()}
        )
        self.state.save_agent_instance(completed)
        self._emit(
            run,
            "agent.completed",
            {"role": "engineer", "iteration": run.repair_iterations},
            agent_id=agent.agent_instance_id,
        )
        self.artifacts.create_text(
            kind=ArtifactKind.IMPLEMENTATION_REPORT,
            project_id=run.project_id,
            run_id=run.run_id,
            task_id=task.task_id,
            producer="fake-runtime:engineer",
            content=script.report.model_dump_json(indent=2),
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
            metadata={"changed_paths": ",".join(patch.changed_paths)},
        )
        updated = self.state.get_run(run.run_id).model_copy(
            update={
                "patch_artifact_id": artifact.artifact_id,
                "patch_sha256": patch.sha256,
                "updated_at": self.clock.now(),
            }
        )
        self.state.save_run(
            updated,
            "implementation.reported",
            {"patch_artifact_id": artifact.artifact_id, "changed_paths": patch.changed_paths},
        )

    async def _verify(self, run: Run) -> VerifierScript:
        if run.task_id is None or run.patch_artifact_id is None:
            raise RuntimeError("run has no task or patch")
        task = self.state.get_task(run.task_id)
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
        self.state.save_agent_instance(agent)
        self._emit(
            run,
            "agent.started",
            {"role": "verifier", "iteration": run.repair_iterations},
            agent_id=agent.agent_instance_id,
        )
        result = await self.runtime.invoke(
            AgentInvocation(
                run_id=run.run_id,
                task_id=task.task_id,
                agent_instance_id=agent.agent_instance_id,
                role=AgentRole.VERIFIER,
                stage=WorkflowStage.VERIFYING,
                iteration=run.repair_iterations,
                max_steps=10,
                input={
                    "goal": task.original_goal,
                    "fake_scenario": run.fake_scenario.value,
                    "repair_iterations": run.repair_iterations,
                    "verification_workspace_path": workspace.path,
                    "patch_sha256": run.patch_sha256,
                },
            )
        )
        script = VerifierScript.model_validate(result.output)
        for action in script.actions:
            await self.gateway.execute(
                run=run,
                task=task,
                agent=agent,
                workspace=workspace,
                sandbox_handle=handle,
                scripted=action,
            )
        after = self.repository.workspace_status_fingerprint(workspace)
        mutated = before != after
        completed = agent.model_copy(
            update={"status": AgentStatus.COMPLETED, "completed_at": self.clock.now()}
        )
        self.state.save_agent_instance(completed)
        self._emit(
            run,
            "agent.completed",
            {"role": "verifier", "iteration": run.repair_iterations},
            agent_id=agent.agent_instance_id,
        )
        verdict_artifact = self.artifacts.create_text(
            kind=ArtifactKind.VERIFIER_VERDICT,
            project_id=run.project_id,
            run_id=run.run_id,
            task_id=task.task_id,
            producer="fake-runtime:verifier",
            content=script.verdict.model_dump_json(indent=2),
            mime_type="application/json",
        )
        updated = self.state.get_run(run.run_id).model_copy(
            update={"verifier_workspace_mutated": mutated, "updated_at": self.clock.now()}
        )
        self.state.save_run(
            updated,
            "verification.completed",
            {
                "verdict": script.verdict.verdict.value,
                "verdict_artifact_id": verdict_artifact.artifact_id,
                "verification_workspace_mutated": mutated,
                "security_level": "fake",
            },
        )
        await self.resources.cleanup_lease(updated, sandbox_lease)
        await self.resources.cleanup_lease(updated, workspace_lease)
        return script

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
