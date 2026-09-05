"""Workflow-owned child execution hooks; graph scheduling grants no new authority."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, cast

from pydantic import JsonValue

from agent_fleet.application.runtime_tools import GatewayRuntimeToolCatalog
from agent_fleet.domain.errors import ApprovalRequiredError, ErrorCode, FleetError
from agent_fleet.domain.fleet_plan import FleetPlan
from agent_fleet.domain.graph import (
    GraphArtifactRef,
    GraphChildSeed,
    GraphJoinInput,
    GraphNodeRecord,
    GraphNodeStatus,
    GraphSnapshot,
    GraphStatus,
)
from agent_fleet.domain.ids import IdPrefix
from agent_fleet.domain.models import (
    AgentExecutionCheckpoint,
    AgentInstance,
    AgentRole,
    AgentStatus,
    ApprovalStatus,
    ArtifactKind,
    ArtifactMetadata,
    Run,
    RunStatus,
    RuntimeCredentialCheck,
    SpecialistReport,
    TaskSpec,
    WorkflowStage,
)
from agent_fleet.domain.paths import path_is_within
from agent_fleet.ports.runtime import RuntimeInvocationServices

if TYPE_CHECKING:
    from agent_fleet.application.workflow import WorkflowEngine


def _invalid() -> FleetError:
    return FleetError(
        ErrorCode.RECOVERY_REQUIRED,
        "Adaptive child or join state does not match its exact frozen execution binding.",
        "Inspect the parent graph and recover its stopped owner; do not replay a child directly.",
    )


class GraphWorkflowExecution:
    def __init__(self, engine: WorkflowEngine) -> None:
        self.engine = engine

    def initialize(self, parent: Run, plan: FleetPlan) -> GraphSnapshot:
        engine = self.engine
        existing = engine.graphs.get(parent.run_id)
        if existing is not None:
            return existing
        if parent.task_id is None or parent.fleet_plan_hash is None:
            raise _invalid()
        parent_task = engine.state.get_task(parent.task_id)
        criterion_ids = {item.criterion_id for item in parent_task.acceptance_criteria}
        if any(
            not node.goal
            or not node.criterion_ids
            or not set(node.criterion_ids).issubset(criterion_ids)
            for node in plan.nodes
        ):
            # Legacy advanced plans remain readable, but were never executable.
            # Execution cannot infer missing task boundaries from a broad parent.
            raise _invalid()
        seeds: list[GraphChildSeed] = []
        for node in sorted(plan.nodes, key=lambda item: item.node_id):
            if node.independent_verifier:
                continue
            now = engine.clock.now()
            run_id = engine.ids.new(IdPrefix.RUN)
            task_id = engine.ids.new(IdPrefix.TASK)
            goal = node.goal
            if goal is None:
                raise _invalid()
            child = Run(
                run_id=run_id,
                project_id=parent.project_id,
                correlation_id=engine.ids.new(IdPrefix.CORRELATION),
                parent_run_id=parent.run_id,
                parent_plan_sha256=parent.fleet_plan_hash,
                parent_node_id=node.node_id,
                parent_iteration=0,
                goal=goal,
                base_revision=parent.base_revision,
                target_status_fingerprint=parent.target_status_fingerprint,
                runtime_name=parent.runtime_name,
                provider_model=parent.provider_model,
                credential_ref=parent.credential_ref,
                sandbox_name=parent.sandbox_name,
                sandbox_configuration=parent.sandbox_configuration,
                sandbox_requirements=parent.sandbox_requirements,
                sandbox_capabilities_snapshot=parent.sandbox_capabilities_snapshot,
                sandbox_image_identity=parent.sandbox_image_identity,
                sandbox_daemon_identity=parent.sandbox_daemon_identity,
                unsafe_local_confirmed=parent.unsafe_local_confirmed,
                fake_scenario=parent.fake_scenario,
                task_id=task_id,
                config_snapshot_hash=parent.config_snapshot_hash,
                max_repair_iterations=0,
                created_at=now,
                updated_at=now,
            )
            selected_criteria = set(node.criterion_ids)
            task = TaskSpec(
                task_id=task_id,
                run_id=run_id,
                original_goal=parent_task.original_goal,
                normalized_goal=goal,
                workflow=parent_task.workflow,
                change_kind="code_change" if node.can_write else "read_only",
                base_revision=parent.base_revision,
                allowed_paths=node.scope,
                forbidden_paths=parent_task.forbidden_paths,
                acceptance_criteria=[
                    item
                    for item in parent_task.acceptance_criteria
                    if item.criterion_id in selected_criteria
                ],
                required_evidence=(
                    ["canonical_patch", "command_evidence"]
                    if node.can_write
                    else ["control_plane_plan"]
                ),
                max_repair_iterations=0,
                config_snapshot_hash=parent_task.config_snapshot_hash,
                verification_commands=parent_task.verification_commands if node.can_write else [],
                required_verification_command_ids=(
                    parent_task.required_verification_command_ids if node.can_write else []
                ),
                created_at=now,
            )
            seeds.append(GraphChildSeed(node_id=node.node_id, run=child, task=task))
        return engine.graphs.initialize(parent.run_id, plan, tuple(seeds))

    def _node(self, child: Run) -> tuple[GraphSnapshot, GraphNodeRecord]:
        engine = self.engine
        binding = engine.graphs.child_binding(child.run_id)
        if binding is None:
            raise _invalid()
        graph = engine.graphs.get(binding.parent_run_id)
        if graph is None or graph.status is not GraphStatus.RUNNING or graph.driver_claim is None:
            raise _invalid()
        matches = [node for node in graph.nodes if node.binding == binding]
        if len(matches) != 1:
            raise _invalid()
        return graph, matches[0]

    async def prepare_graph_child(
        self,
        parent: Run,
        node: GraphNodeRecord,
        dependency_refs: tuple[GraphArtifactRef, ...],
    ) -> Run:
        engine = self.engine
        child = engine.state.get_run(node.binding.child_run_id)
        graph, current_node = self._node(child)
        if graph.parent_run_id != parent.run_id or current_node.binding != node.binding:
            raise _invalid()
        self._read_dependencies(graph, current_node, dependency_refs)
        if child.status is not RunStatus.CREATED:
            return child
        limits = engine.budgets.snapshot(parent.run_id).limits
        if limits is None:
            raise _invalid()
        engine.budgets.initialize_run(child.run_id, limits, parent_run_id=parent.run_id)
        if child.task_id is None or parent.config_snapshot_artifact_id is None:
            raise _invalid()
        task = engine.state.get_task(child.task_id)
        task_artifact = engine.artifacts.create_text(
            kind=ArtifactKind.TASK_SPEC,
            project_id=child.project_id,
            run_id=child.run_id,
            task_id=task.task_id,
            producer="graph-control-plane",
            content=task.model_dump_json(indent=2),
            mime_type="application/json",
            redact=False,
            reject_secret=True,
        )
        config_artifact = engine.artifacts.create_text(
            kind=ArtifactKind.CONFIG_SNAPSHOT,
            project_id=child.project_id,
            run_id=child.run_id,
            task_id=task.task_id,
            producer="graph-control-plane",
            content=engine.artifacts.read_text(parent.config_snapshot_artifact_id),
            mime_type="application/json",
            redact=False,
            reject_secret=True,
        )
        if config_artifact.sha256 != parent.config_snapshot_hash:
            raise _invalid()
        return engine.state.save_run(
            child.model_copy(
                update={
                    "task_spec_artifact_id": task_artifact.artifact_id,
                    "task_spec_hash": task_artifact.sha256,
                    "config_snapshot_artifact_id": config_artifact.artifact_id,
                    "updated_at": engine.clock.now(),
                }
            ),
            "graph.child_prepared",
            {"parent_run_id": parent.run_id, "node_id": node.node.node_id},
        )

    async def execute_graph_child(self, child: Run) -> Run:
        engine = self.engine
        _, node = self._node(child)
        if node.status is not GraphNodeStatus.RUNNING:
            raise _invalid()
        if child.status is RunStatus.COMPLETED:
            return child
        try:
            if child.status is RunStatus.PAUSED_FOR_APPROVAL:
                child = await self._resume_child_approval(child)
                if child.status is not RunStatus.RUNNING:
                    return child
            if child.status is RunStatus.CREATED:
                if child.task_spec_artifact_id is None or child.config_snapshot_artifact_id is None:
                    raise _invalid()
                for stage in (
                    WorkflowStage.INTAKE,
                    WorkflowStage.SCOPING,
                    WorkflowStage.WORKSPACE_PREPARATION,
                ):
                    child = engine._transition(child, RunStatus.RUNNING, stage)
                await engine._prepare_workspace(child)
                child = engine._transition(child, RunStatus.RUNNING, WorkflowStage.IMPLEMENTING)
            if (
                child.status is not RunStatus.RUNNING
                or child.stage is not WorkflowStage.IMPLEMENTING
            ):
                raise _invalid()
            if node.node.can_write:
                # A settled patch is never grounds to create a second Engineer.
                if child.patch_artifact_id is None:
                    await engine._engineer(child)
            else:
                await self._specialist(child, node)
            child = engine.state.get_run(child.run_id)
            await engine.resources.cleanup_run(child)
            child = engine._persist_cleanup_receipt(child)
            child = engine._transition(child, RunStatus.RUNNING, WorkflowStage.PRESENTING)
            return engine.state.save_run(
                child.model_copy(update={"status": RunStatus.COMPLETED}),
                "graph.child_completed",
                {"candidate_only": True, "verified_complete": False},
            )
        except ApprovalRequiredError:
            return engine.state.get_run(child.run_id)
        except asyncio.CancelledError:
            raise
        except FleetError as error:
            latest = engine.state.get_run(child.run_id)
            if latest.status not in {RunStatus.CANCELLED, RunStatus.REJECTED, RunStatus.FAILED}:
                engine.state.save_run(
                    latest.model_copy(
                        update={"status": RunStatus.FAILED, "updated_at": engine.clock.now()}
                    ),
                    "graph.child_failed",
                    {"code": error.code.value},
                )
            await engine.resources.cleanup_run(engine.state.get_run(child.run_id))
            raise

    async def _resume_child_approval(self, child: Run) -> Run:
        engine = self.engine
        if child.pending_approval_id is None:
            raise _invalid()
        approval = engine.state.get_approval(child.pending_approval_id)
        if approval.run_id != child.run_id:
            raise _invalid()
        if approval.status is ApprovalStatus.PENDING:
            return child
        if approval.status is ApprovalStatus.DENIED:
            rejected = engine.state.save_run(
                child.model_copy(
                    update={"status": RunStatus.REJECTED, "updated_at": engine.clock.now()}
                ),
                "run.rejected",
                {"reason": "approval_denied", "request_id": approval.request_id},
            )
            await engine.resources.cleanup_run(rejected)
            return rejected
        spec, _ = engine._active_role_configuration(child)
        if engine.permission_policy is not None:
            engine.permission_policy.validate_run_target(child)
        configuration = engine._runtime_configuration(child)
        engine.runtimes.require(
            configuration,
            required_capabilities=spec.spec.runtime.required_capabilities,
            credential_check=RuntimeCredentialCheck.RESOLVE,
        )
        await engine.resources.rehydrate_paused_sandboxes(child)
        return engine.state.save_run(
            child.model_copy(
                update={
                    "status": RunStatus.RUNNING,
                    "pending_approval_id": None,
                    "updated_at": engine.clock.now(),
                }
            ),
            "run.resumed",
            {"request_id": approval.request_id, "parent_run_id": child.parent_run_id},
        )

    async def _specialist(self, child: Run, node: GraphNodeRecord) -> None:
        engine = self.engine
        if child.task_id is None or node.node.role_id not in {"researcher", "architect"}:
            raise _invalid()
        if any(
            item.kind is ArtifactKind.SPECIALIST_REPORT
            for item in engine.state.list_artifacts(child.run_id)
        ):
            raise _invalid()
        task = engine.state.get_task(child.task_id)
        role = AgentRole(node.node.role_id)
        workspace = engine.resources.candidate_workspace(child.run_id)
        handle = engine.resources.engineer_sandbox(child.run_id)
        before = engine.repository.workspace_status_fingerprint(workspace)
        if engine.repository.compute_patch(workspace).changed_paths:
            raise _invalid()
        checkpoint = child.specialist_checkpoint
        if checkpoint is None:
            checkpoint = AgentExecutionCheckpoint(
                agent_instance_id=engine.ids.new(IdPrefix.AGENT),
                workspace_id=workspace.workspace_id,
                sandbox_id=handle.sandbox_id,
                iteration=0,
                created_at=engine.clock.now(),
            )
            child = engine.state.save_run(
                child.model_copy(update={"specialist_checkpoint": checkpoint}),
                "specialist.checkpoint_created",
                checkpoint.model_dump(mode="json"),
            )
        if (checkpoint.workspace_id, checkpoint.sandbox_id, checkpoint.iteration) != (
            workspace.workspace_id,
            handle.sandbox_id,
            0,
        ):
            raise _invalid()
        agent = AgentInstance(
            agent_instance_id=checkpoint.agent_instance_id,
            run_id=child.run_id,
            task_id=child.task_id,
            role=role,
            status=AgentStatus.RUNNING,
            iteration=0,
            created_at=checkpoint.created_at,
        )
        configuration = engine._runtime_configuration(child)
        catalog = GatewayRuntimeToolCatalog(
            gateway=engine.gateway,
            redactor=engine.redactor,
            run=child,
            task=task,
            agent=agent,
            workspace=workspace,
            sandbox_handle=handle,
            max_calls=configuration.max_tool_calls,
        )
        request = engine._build_invocation(
            run_id=child.run_id,
            task_id=task.task_id,
            agent_instance_id=agent.agent_instance_id,
            role=role,
            stage=WorkflowStage.IMPLEMENTING,
            iteration=0,
            max_steps=min(
                node.node.max_steps, engine._active_role_max_steps(child, role, ceiling=10)
            ),
            instructions=engine._active_role_guidance(child, role),
            context_artifact_ids=self.context_artifact_ids(child),
            input=engine._runtime_input(
                child,
                {
                    "task_spec": task.model_dump(mode="json"),
                    "graph_context": self.model_context(child),
                },
            ),
        )
        engine.state.save_agent_instance(agent)
        engine._emit(child, "agent.started", {"role": role.value}, agent_id=agent.agent_instance_id)
        result = await engine._invoke_runtime_agent(
            child,
            agent,
            engine.runtimes.get(configuration.runtime_name),
            request,
            RuntimeInvocationServices(configuration=configuration, tools=catalog),
        )
        report = cast(SpecialistReport, result.output)
        if (
            report.role != role.value
            or engine.repository.workspace_status_fingerprint(workspace) != before
            or engine.repository.compute_patch(workspace).changed_paths
        ):
            raise _invalid()
        child = engine._persist_runtime_observation(
            child, task.task_id, agent.agent_instance_id, role.value, result
        )
        engine.artifacts.create_text(
            kind=ArtifactKind.SPECIALIST_REPORT,
            project_id=child.project_id,
            run_id=child.run_id,
            task_id=child.task_id,
            producer=f"{child.runtime_name}-runtime:{role.value}",
            content=report.model_dump_json(indent=2),
            mime_type="application/json",
            reject_secret=True,
            metadata={"assurance": "model_report_not_execution_evidence"},
        )
        engine.state.save_run(
            child.model_copy(update={"specialist_checkpoint": None}),
            "specialist.reported",
            {"role": role.value},
        )

    def context_artifact_ids(self, run: Run) -> list[str]:
        if run.parent_run_id is None:
            return []
        graph, node = self._node(run)
        return list(
            dict.fromkeys(
                [
                    graph.plan_artifact_id,
                    *[
                        item.artifact_id
                        for item in node.input_artifacts
                        if item.kind is ArtifactKind.SPECIALIST_REPORT
                    ],
                ]
            )
        )

    def model_context(self, run: Run) -> JsonValue:
        if run.parent_run_id is None:
            return None
        graph, node = self._node(run)
        return {
            "node_id": node.node.node_id,
            "parent_plan_sha256": graph.plan_sha256,
            "dependencies": self._read_dependencies(graph, node, node.input_artifacts),
        }

    def _read_dependencies(
        self,
        graph: GraphSnapshot,
        node: GraphNodeRecord,
        refs: tuple[GraphArtifactRef, ...],
    ) -> list[JsonValue]:
        engine = self.engine
        dependencies = {
            item.node.node_id: item
            for item in graph.nodes
            if item.node.node_id in node.node.depends_on
        }
        reports: list[JsonValue] = []
        for ref in refs:
            matches = [
                item for item in dependencies.values() if item.binding.child_run_id == ref.run_id
            ]
            if len(matches) != 1 or matches[0].status is not GraphNodeStatus.SUCCEEDED:
                raise _invalid()
            if ref not in matches[0].output_artifacts:
                raise _invalid()
            metadata = self._artifact(ref, matches[0].binding.child_task_id)
            if metadata.kind is not ArtifactKind.SPECIALIST_REPORT:
                continue
            text = engine.artifacts.read_text(ref.artifact_id)
            engine._bounded_runtime_text(text, max_bytes=40_000)
            report = SpecialistReport.model_validate_json(text)
            engine._reject_untrusted_secrets(report.model_dump(mode="json"))
            reports.append(
                {
                    "artifact_id": ref.artifact_id,
                    "sha256": ref.sha256,
                    "report": report.model_dump(mode="json"),
                }
            )
        return reports

    def _artifact(self, ref: GraphArtifactRef, task_id: str) -> ArtifactMetadata:
        engine = self.engine
        metadata = engine.state.get_artifact(ref.artifact_id)
        run = engine.state.get_run(ref.run_id)
        if (
            metadata.run_id,
            metadata.project_id,
            metadata.task_id,
            metadata.sha256,
            metadata.kind,
        ) != (ref.run_id, run.project_id, task_id, ref.sha256, ref.kind):
            raise _invalid()
        engine.artifacts.read_text(ref.artifact_id)
        return metadata

    async def join_graph_candidates(
        self, parent: Run, ordered_inputs: tuple[GraphJoinInput, ...]
    ) -> Run:
        engine = self.engine
        graph = engine.graphs.get(parent.run_id)
        if (
            graph is None
            or graph.join_preparation is None
            or graph.join_preparation.ordered_inputs != ordered_inputs
        ):
            raise _invalid()
        if parent.task_id is None or parent.patch_artifact_id is not None:
            raise _invalid()
        task = engine.state.get_task(parent.task_id)
        for binding in engine.graphs.descendants(parent.run_id):
            if engine.state.outstanding_leases(binding.child_run_id):
                raise _invalid()
        engine.artifacts.create_text(
            kind=ArtifactKind.GRAPH_JOIN,
            project_id=parent.project_id,
            run_id=parent.run_id,
            task_id=parent.task_id,
            producer="graph-control-plane",
            content=graph.join_preparation.model_dump_json(indent=2),
            mime_type="application/json",
            reject_secret=True,
        )
        await engine._prepare_workspace(parent)
        workspace = engine.resources.candidate_workspace(parent.run_id)
        for item in ordered_inputs:
            child = engine.state.get_run(item.child_run_id)
            _, node = self._node(child)
            if child.status is not RunStatus.COMPLETED or child.task_id != item.child_task_id:
                raise _invalid()
            if (child.patch_artifact_id, child.patch_sha256) != (
                item.patch_artifact_id,
                item.patch_sha256,
            ):
                raise _invalid()
            metadata = self._artifact(
                GraphArtifactRef(
                    artifact_id=item.patch_artifact_id,
                    sha256=item.patch_sha256,
                    run_id=item.child_run_id,
                    kind=ArtifactKind.PATCH,
                ),
                item.child_task_id,
            )
            changed = metadata.metadata.get("changed_paths")
            if (
                not isinstance(changed, list)
                or not changed
                or any(
                    not isinstance(path, str)
                    or not path_is_within(path, node.node.scope, forbidden=task.forbidden_paths)
                    for path in changed
                )
            ):
                raise _invalid()
            patch = engine.artifacts.read_text(item.patch_artifact_id).encode("utf-8")
            if set(engine.repository.patch_changed_paths(patch)) != set(changed):
                raise _invalid()
            engine.repository.apply_patch_to_workspace(workspace, patch)
        patch_info = engine.repository.compute_patch(workspace)
        if not patch_info.changed_paths or any(
            not path_is_within(path, task.allowed_paths, forbidden=task.forbidden_paths)
            for path in patch_info.changed_paths
        ):
            raise _invalid()
        artifact = engine.artifacts.create_text(
            kind=ArtifactKind.PATCH,
            project_id=parent.project_id,
            run_id=parent.run_id,
            task_id=parent.task_id,
            producer="git-graph-control-plane",
            content=patch_info.content,
            mime_type="text/x-diff",
            redact=False,
            reject_secret=True,
            metadata={"changed_paths": cast(JsonValue, patch_info.changed_paths)},
        )
        joined = engine.state.save_run(
            engine.state.get_run(parent.run_id).model_copy(
                update={
                    "patch_artifact_id": artifact.artifact_id,
                    "patch_sha256": artifact.sha256,
                    "updated_at": engine.clock.now(),
                }
            ),
            "graph.patch_joined",
            {"patch_artifact_id": artifact.artifact_id, "patch_sha256": artifact.sha256},
        )
        return engine._transition(joined, RunStatus.RUNNING, WorkflowStage.VERIFYING)

    async def cleanup_graph_children(self, parent: Run) -> None:
        engine = self.engine
        failures: list[BaseException] = []
        graph = engine.graphs.get(parent.run_id)
        if graph is None:
            raise _invalid()
        nodes = {item.binding.child_run_id: item for item in graph.nodes}
        for binding in engine.graphs.descendants(parent.run_id):
            try:
                child = engine.state.get_run(binding.child_run_id)
                node = nodes[child.run_id]
                if node.status in {GraphNodeStatus.FAILED, GraphNodeStatus.BLOCKED} and (
                    child.status
                    in {RunStatus.CREATED, RunStatus.RUNNING, RunStatus.PAUSED_FOR_APPROVAL}
                ):
                    denied = child.pending_approval_id is not None and (
                        engine.state.get_approval(child.pending_approval_id).status
                        is ApprovalStatus.DENIED
                    )
                    child = engine.state.save_run(
                        child.model_copy(
                            update={
                                "status": RunStatus.REJECTED if denied else RunStatus.FAILED,
                                "pending_approval_id": None,
                                "updated_at": engine.clock.now(),
                            }
                        ),
                        "graph.child_rejected" if denied else "graph.child_failed",
                        {"node_status": node.status.value, "reason": "parent_graph_failed"},
                    )
                await engine.resources.cleanup_run(child)
            except BaseException as error:
                failures.append(error)
        if failures:
            raise failures[0]

    async def cancel_parent(self, run_id: str) -> None:
        """Fence and finish exact cleanup despite repeated caller cancellation."""
        cleanup = asyncio.create_task(self._cancel_parent(run_id))
        while not cleanup.done():
            try:
                await asyncio.wait({cleanup})
            except asyncio.CancelledError:
                continue
        cleanup.result()

    async def _cancel_parent(self, run_id: str) -> None:
        engine = self.engine
        parent = engine.state.get_run(run_id)
        if parent.status not in {
            RunStatus.COMPLETED,
            RunStatus.READY_FOR_REVIEW,
            RunStatus.REJECTED,
            RunStatus.FAILED,
            RunStatus.ABANDONED,
            RunStatus.CANCELLED,
        }:
            parent = engine.state.save_run(
                parent.model_copy(
                    update={"status": RunStatus.CANCELLED, "updated_at": engine.clock.now()}
                ),
                "run.cancelled",
                {"reason": "adaptive_owner_cancelled"},
            )
        failures: list[BaseException] = []
        try:
            graph = engine.graphs.get(run_id)
            if graph is not None and graph.cancel_requested_at is None:
                engine.graphs.request_cancel(run_id, expected_revision=graph.revision)
            await self.cleanup_graph_children(parent)
        except BaseException as error:
            failures.append(error)
        try:
            await engine.resources.cleanup_run(parent)
        except BaseException as error:
            failures.append(error)
        if failures:
            raise FleetError(
                ErrorCode.RECOVERY_REQUIRED,
                "Adaptive cancellation could not prove every owned resource was cleaned.",
                "Confirm the owner stopped and recover the parent run before retrying work.",
            )

    def remaining_graph_active_seconds(self, parent_run_id: str) -> float:
        snapshot = self.engine.budgets.snapshot(parent_run_id)
        if snapshot.limits is None:
            raise _invalid()
        return max(0.0, snapshot.limits.max_active_seconds - snapshot.active_seconds)
