"""Real Git/SQLite/gateway scheduling; runtime and sandbox remain explicitly fake."""

from __future__ import annotations

import asyncio
from collections import Counter
from pathlib import Path

import pytest
from conftest import FleetHarness

from agent_fleet.adapters.runtime.fake import (
    FakeRuntimeAdapter,
    _EngineerScript,
    _ScriptedAction,
)
from agent_fleet.application.runtime import RuntimeRegistry
from agent_fleet.bootstrap import ApplicationContainer, build_container
from agent_fleet.domain.budgets import RunBudgetLimits
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.evidence import CommandEvidence
from agent_fleet.domain.graph import GraphNodeStatus, GraphSnapshot, GraphStatus
from agent_fleet.domain.models import (
    AcceptanceCriterion,
    AgentInvocation,
    AgentInvocationResult,
    AgentRole,
    ArtifactKind,
    FakeScenario,
    ImplementationReport,
    LeaseKind,
    Run,
    RunStatus,
    ScopeDecision,
    TaskSpec,
    WorkflowStage,
    WriterAssignment,
)
from agent_fleet.domain.trust import TrustMode
from agent_fleet.ports.runtime import RuntimeInvocationServices

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]
EXTRA_PATH = "src/canary_calc/extra.py"


class QueuedRuntime(FakeRuntimeAdapter):
    """Only timing/proposed third fixture shard differ from the normal fake path."""

    def __init__(self, container: ApplicationContainer) -> None:
        self.container = container
        self.entered: asyncio.Queue[tuple[str, str]] = asyncio.Queue()
        self.release = {node: asyncio.Event() for node in ("core", "metadata", "z-extra")}
        self.active: set[str] = set()
        self.max_active = 0
        self.executions: Counter[str] = Counter()

    @staticmethod
    def _scope_decision(request: AgentInvocation, scenario: FakeScenario) -> ScopeDecision:
        proposed = FakeRuntimeAdapter._scope_decision(request, scenario)
        return ScopeDecision.model_validate(
            proposed.model_copy(
                update={
                    "writer_assignments": [
                        *proposed.writer_assignments,
                        WriterAssignment(
                            node_id="z-extra",
                            goal="Add a third independent text module.",
                            scope=[EXTRA_PATH],
                            criterion_ids=["canary-extra"],
                        ),
                    ],
                    "acceptance_criteria": [
                        *proposed.acceptance_criteria,
                        AcceptanceCriterion(
                            criterion_id="canary-extra",
                            description="The extra module defines EXTRA = 3.",
                        ),
                    ],
                }
            )
        )

    @staticmethod
    def _engineer_script(request: AgentInvocation, scenario: FakeScenario) -> _EngineerScript:
        task = TaskSpec.model_validate(request.input["task_spec"])
        if task.allowed_paths != [EXTRA_PATH]:
            return FakeRuntimeAdapter._engineer_script(request, scenario)
        return _EngineerScript(
            actions=(
                _ScriptedAction(
                    call_id="extra_module_write",
                    tool_name="workspace_write_file",
                    arguments={
                        "path": EXTRA_PATH,
                        "content": "EXTRA = 3\n",
                        "reason": "Write the exact assigned module.",
                    },
                ),
            ),
            report=ImplementationReport(
                summary="Produced the exact third fixture module.",
                intended_changed_paths=[EXTRA_PATH],
                tests_added_or_changed=[],
                criterion_results=["canary-extra: scripted candidate produced"],
                evidence_artifact_ids=[],
                unresolved_limitations=["Fake is not execution proof."],
                verifier_focus=["Verify the complete joined candidate independently."],
            ),
        )

    async def invoke(
        self, request: AgentInvocation, services: RuntimeInvocationServices
    ) -> AgentInvocationResult:
        child = self.container.state.get_run(request.run_id)
        if request.role != AgentRole.ENGINEER or child.parent_node_id is None:
            return await super().invoke(request, services)
        node = child.parent_node_id
        self.executions[node] += 1
        self.active.add(node)
        self.max_active = max(self.max_active, len(self.active))
        self.entered.put_nowait((node, child.run_id))
        try:
            await self.release[node].wait()
            return await super().invoke(request, services)
        finally:
            self.active.remove(node)


class ApprovalRuntime(FakeRuntimeAdapter):
    @staticmethod
    def _scope_decision(request: AgentInvocation, scenario: FakeScenario) -> ScopeDecision:
        del scenario
        return FakeRuntimeAdapter._scope_decision(request, FakeScenario.PARALLEL_ENGINEERS)

    @staticmethod
    def _engineer_script(request: AgentInvocation, scenario: FakeScenario) -> _EngineerScript:
        del scenario
        original = FakeRuntimeAdapter._engineer_script(request, FakeScenario.PARALLEL_ENGINEERS)
        return _EngineerScript(
            actions=(
                _ScriptedAction(
                    call_id="graph_approval_probe",
                    tool_name="record_approval_probe",
                    arguments={
                        "record": "approved-once",
                        "reason": "Approve this exact child action once.",
                    },
                ),
                *original.actions,
            ),
            report=original.report,
        )


class BlockingApprovalRuntime(ApprovalRuntime):
    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def invoke(
        self, request: AgentInvocation, services: RuntimeInvocationServices
    ) -> AgentInvocationResult:
        if request.role == AgentRole.ENGINEER:
            self.entered.set()
            await self.release.wait()
        return await super().invoke(request, services)


class ParentApprovalRuntime(FakeRuntimeAdapter):
    """Child candidates make no command claim; only the parent runs verification."""

    @staticmethod
    def _engineer_script(request: AgentInvocation, scenario: FakeScenario) -> _EngineerScript:
        original = FakeRuntimeAdapter._engineer_script(request, scenario)
        return _EngineerScript(
            actions=tuple(
                action for action in original.actions if action.tool_name != "run_verification"
            ),
            report=original.report,
        )


class BlockingVerifierRuntime(ParentApprovalRuntime):
    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.parent_run_id: str | None = None
        self.agent_id: str | None = None
        self.active = False

    async def invoke(
        self, request: AgentInvocation, services: RuntimeInvocationServices
    ) -> AgentInvocationResult:
        if request.role != AgentRole.VERIFIER:
            return await super().invoke(request, services)
        self.parent_run_id = request.run_id
        self.agent_id = request.agent_instance_id
        self.active = True
        self.entered.set()
        try:
            await self.release.wait()
            return await super().invoke(request, services)
        finally:
            self.active = False


def _graph(container: ApplicationContainer, parent: Run) -> GraphSnapshot:
    graph = container.graphs.get(parent.run_id)
    assert graph is not None
    return graph


def _install(container: ApplicationContainer, runtime: FakeRuntimeAdapter) -> None:
    container.workflow.runtimes = RuntimeRegistry({"fake": runtime})


def _reopen(path: Path) -> ApplicationContainer:
    container = build_container(path)
    _install(container, ApprovalRuntime())
    return container


def _children(container: ApplicationContainer, parent: Run) -> dict[str, Run]:
    return {
        node.binding.node_id: container.state.get_run(node.binding.child_run_id)
        for node in _graph(container, parent).nodes
    }


def _commands(container: ApplicationContainer, run: Run) -> list[CommandEvidence]:
    return [
        CommandEvidence.model_validate_json(container.artifacts.read_text(item.artifact_id))
        for item in container.state.list_artifacts(run.run_id)
        if item.kind is ArtifactKind.COMMAND_EVIDENCE
    ]


async def test_three_real_scoped_children_queue_and_reverse_completion_join_identically(
    harness: FleetHarness,
) -> None:
    before = harness.git("status", "--porcelain")
    patch_hashes = []
    for first in ("core", "metadata"):
        container = build_container(harness.state_root)
        runtime = QueuedRuntime(container)
        _install(container, runtime)
        active = asyncio.create_task(
            container.workflow.start(
                project_path=harness.repository_root,
                goal="Produce three independent fixture changes.",
                runtime_name="fake",
                sandbox_name="fake",
                fake_scenario=FakeScenario.PARALLEL_ENGINEERS,
            )
        )
        try:
            entered = [await asyncio.wait_for(runtime.entered.get(), timeout=15) for _ in range(2)]
            assert [item[0] for item in entered] == ["core", "metadata"]
            running = [container.state.get_run(item[1]) for item in entered]
            assert all(child.parent_run_id is not None for child in running)
            parent = container.state.get_run(str(running[0].parent_run_id))
            snapshot = _graph(container, parent)
            assert snapshot.plan.max_parallel_agents == 2
            assert [node.status for node in snapshot.nodes] == [
                GraphNodeStatus.RUNNING,
                GraphNodeStatus.RUNNING,
                GraphNodeStatus.PENDING,
            ]
            workspaces = [
                lease.resource_id
                for child in running
                for lease in container.state.active_leases(child.run_id)
                if lease.kind is LeaseKind.WORKTREE
            ]
            assert len(workspaces) == len(set(workspaces)) == 2
            sandboxes = [
                lease.resource_id
                for child in running
                for lease in container.state.active_leases(child.run_id)
                if lease.kind is LeaseKind.SANDBOX
            ]
            assert len(sandboxes) == len(set(sandboxes)) == 2
            assert all(
                container.state.count_executed_intents(child.run_id, "workspace.write_file") == 0
                for child in running
            )
            runtime.release[first].set()
            third, _ = await asyncio.wait_for(runtime.entered.get(), timeout=15)
            assert third == "z-extra"
            assert len(runtime.active) == 2
            first_node = next(
                node for node in _graph(container, parent).nodes if node.binding.node_id == first
            )
            assert first_node.status is GraphNodeStatus.SUCCEEDED
            assert not container.state.outstanding_leases(first_node.binding.child_run_id)
            for event in runtime.release.values():
                event.set()
            result = await asyncio.wait_for(active, timeout=30)
        finally:
            if not active.done():
                active.cancel()
                await asyncio.gather(active, return_exceptions=True)
        assert result.status is RunStatus.READY_FOR_REVIEW and not result.verified_complete
        assert runtime.max_active == 2 and runtime.executions == {
            "core": 1,
            "metadata": 1,
            "z-extra": 1,
        }
        graph = _graph(container, result)
        assert graph.status is GraphStatus.JOINED and graph.driver_claim is None
        assert graph.join_preparation is not None
        assert [item.node_id for item in graph.join_preparation.ordered_inputs] == [
            "core",
            "metadata",
            "z-extra",
        ]
        assert result.patch_artifact_id is not None and result.patch_sha256 is not None
        patch = container.artifacts.read_text(result.patch_artifact_id)
        assert all(
            path in patch
            for path in ("src/canary_calc/core.py", "src/canary_calc/metadata.py", EXTRA_PATH)
        )
        patch_hashes.append(result.patch_sha256)
        assert all(
            not container.state.outstanding_leases(child.run_id)
            for child in _children(container, result).values()
        )
        assert not container.state.outstanding_leases(result.run_id)
        assert harness.git("status", "--porcelain") == before
    assert patch_hashes[0] == patch_hashes[1]


async def test_rebuilt_parent_resumes_only_exact_approved_child_in_either_order(
    harness: FleetHarness,
) -> None:
    patches = []
    for order in (("core", "metadata"), ("metadata", "core")):
        initial = _reopen(harness.state_root)
        parent = await initial.workflow.start(
            project_path=harness.repository_root,
            goal="Pause two independently scoped writers.",
            runtime_name="fake",
            sandbox_name="fake",
            fake_scenario=FakeScenario.APPROVAL,
        )
        assert parent.status is RunStatus.WAITING_FOR_CHILDREN
        assert parent.pending_approval_id is None
        children = _children(initial, parent)
        identities = {}
        for node_id, child in children.items():
            assert child.status is RunStatus.PAUSED_FOR_APPROVAL
            assert child.engineer_checkpoint is not None and child.pending_approval_id is not None
            checkpoint = child.engineer_checkpoint
            identities[node_id] = checkpoint
            request = initial.state.get_approval(child.pending_approval_id)
            stored = initial.state.get_intent(request.intent_id)
            assert request.run_id == child.run_id
            assert stored.intent.task_id == child.task_id
            assert stored.intent.agent_instance_id == checkpoint.agent_instance_id
        assert len({child.pending_approval_id for child in children.values()}) == 2
        for position, node_id in enumerate(order):
            approving = _reopen(harness.state_root)
            child = _children(approving, parent)[node_id]
            assert child.pending_approval_id is not None
            grant = approving.approvals.approve_once(child.pending_approval_id)
            assert grant.run_id == child.run_id and grant.task_id == child.task_id
            resumed = _reopen(harness.state_root)
            parent = await resumed.workflow.resume(parent.run_id)
            current_children = _children(resumed, parent)
            completed = current_children[node_id]
            assert completed.status is RunStatus.COMPLETED and not completed.verified_complete
            assert (
                resumed.state.count_executed_intents(completed.run_id, "fixture.record_side_effect")
                == 1
            )
            assert (
                resumed.state.count_executed_intents(completed.run_id, "workspace.write_file") == 1
            )
            checkpoint = identities[node_id]
            commands = _commands(resumed, completed)
            assert commands
            assert len({command.command_id for command in commands}) == len(commands)
            assert {
                (command.agent_instance_id, command.workspace_id, command.sandbox_id)
                for command in commands
            } == {(checkpoint.agent_instance_id, checkpoint.workspace_id, checkpoint.sandbox_id)}
            engineer_events = [
                event
                for event in resumed.state.list_events(completed.run_id)
                if event.event_type == "agent.started"
            ]
            assert {event.agent_instance_id for event in engineer_events} == {
                checkpoint.agent_instance_id
            }
            assert not resumed.state.outstanding_leases(completed.run_id)
            if position == 0:
                other = current_children[order[1]]
                assert (
                    parent.status is RunStatus.WAITING_FOR_CHILDREN
                    and parent.pending_approval_id is None
                )
                assert other.status is RunStatus.PAUSED_FOR_APPROVAL
                assert (
                    resumed.state.count_executed_intents(other.run_id, "fixture.record_side_effect")
                    == 0
                )
                assert other.engineer_checkpoint == identities[order[1]]
                assert _graph(resumed, parent).status is GraphStatus.PAUSED
        assert parent.status is RunStatus.READY_FOR_REVIEW and not parent.verified_complete
        assert parent.patch_sha256 is not None
        patches.append(parent.patch_sha256)
        assert not resumed.state.outstanding_leases(parent.run_id)
        assert _graph(resumed, parent).driver_claim is None
    assert patches[0] == patches[1]


async def test_duplicate_public_resume_cannot_fail_the_active_owner(
    harness: FleetHarness,
) -> None:
    initial = _reopen(harness.state_root)
    parent = await initial.workflow.start(
        project_path=harness.repository_root,
        goal="Resume a single owned graph driver.",
        runtime_name="fake",
        sandbox_name="fake",
        fake_scenario=FakeScenario.APPROVAL,
    )
    assert parent.status is RunStatus.WAITING_FOR_CHILDREN
    for child in _children(initial, parent).values():
        assert child.pending_approval_id is not None
        initial.approvals.approve_once(child.pending_approval_id)
    winning = _reopen(harness.state_root)
    blocked = BlockingApprovalRuntime()
    _install(winning, blocked)
    task = asyncio.create_task(winning.workflow.resume(parent.run_id))
    try:
        await asyncio.wait_for(blocked.entered.wait(), timeout=15)
        losing = _reopen(harness.state_root)
        with pytest.raises(FleetError):
            await losing.workflow.resume(parent.run_id)
        assert winning.state.get_run(parent.run_id).status is RunStatus.RUNNING
        assert _graph(winning, parent).driver_claim is not None
        blocked.release.set()
        result = await asyncio.wait_for(task, timeout=30)
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    assert result.status is RunStatus.READY_FOR_REVIEW
    assert result.stage is WorkflowStage.PRESENTING
    for child in _children(winning, result).values():
        assert winning.state.count_executed_intents(child.run_id, "fixture.record_side_effect") == 1
        assert winning.state.count_executed_intents(child.run_id, "workspace.write_file") == 1
        assert not winning.state.outstanding_leases(child.run_id)


async def test_stale_paused_parent_resume_cannot_interfere_with_claimed_verifier(
    harness: FleetHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness.container.permissions.configure(
        harness.repository_root, mode=TrustMode.SAFE, allowed_paths=(".",)
    )
    initial = build_container(harness.state_root)
    _install(initial, ParentApprovalRuntime())
    paused = await initial.workflow.start(
        project_path=harness.repository_root,
        goal="Independently verify the joined candidate.",
        runtime_name="fake",
        sandbox_name="fake",
        fake_scenario=FakeScenario.PARALLEL_ENGINEERS,
    )
    assert paused.status is RunStatus.PAUSED_FOR_APPROVAL
    assert paused.stage is WorkflowStage.VERIFYING and paused.pending_approval_id is not None
    assert paused.verification_checkpoint is not None
    assert _graph(initial, paused).status is GraphStatus.JOINED
    assert all(child.status is RunStatus.COMPLETED for child in _children(initial, paused).values())
    initial.approvals.approve_once(paused.pending_approval_id)
    winning = build_container(harness.state_root)
    runtime = BlockingVerifierRuntime()
    _install(winning, runtime)
    winner = asyncio.create_task(winning.workflow.resume(paused.run_id))
    try:
        await asyncio.wait_for(runtime.entered.wait(), timeout=15)
        losing = build_container(harness.state_root)
        _install(losing, ParentApprovalRuntime())
        actual_get_run = losing.state.get_run
        stale_returned = False

        def stale_initial_read(run_id: str) -> Run:
            nonlocal stale_returned
            if run_id == paused.run_id and not stale_returned:
                stale_returned = True
                return paused.model_copy(deep=True)
            return actual_get_run(run_id)

        monkeypatch.setattr(losing.state, "get_run", stale_initial_read)
        before = winning.state.get_run(paused.run_id)
        with pytest.raises(FleetError):
            await losing.workflow.resume(paused.run_id)
        assert stale_returned
        assert winning.state.get_run(paused.run_id) == before
        assert before.status is RunStatus.RUNNING and runtime.active
        assert before.verification_checkpoint == paused.verification_checkpoint
        assert _graph(winning, paused).driver_claim is not None
        runtime.release.set()
        next_pause = await asyncio.wait_for(winner, timeout=30)
    finally:
        if not winner.done():
            winner.cancel()
            await asyncio.gather(winner, return_exceptions=True)
    assert next_pause.status is RunStatus.PAUSED_FOR_APPROVAL
    assert next_pause.pending_approval_id != paused.pending_approval_id
    assert next_pause.verification_checkpoint == paused.verification_checkpoint
    assert len(_commands(winning, next_pause)) == 1
    assert _graph(winning, next_pause).driver_claim is None
    # Finish the bounded original command list; each subsequent pause uses a new
    # composition root and must keep the same logical verifier/resources.
    for _ in range(8):
        if next_pause.status is not RunStatus.PAUSED_FOR_APPROVAL:
            break
        resumed = build_container(harness.state_root)
        _install(resumed, ParentApprovalRuntime())
        assert next_pause.pending_approval_id is not None
        resumed.approvals.approve_once(next_pause.pending_approval_id)
        next_pause = await resumed.workflow.resume(next_pause.run_id)
    assert next_pause.status is RunStatus.READY_FOR_REVIEW
    assert not next_pause.verified_complete
    assert next_pause.verification_checkpoint is None
    commands = _commands(resumed, next_pause)
    assert len(commands) == len({command.command_id for command in commands})
    assert {command.agent_instance_id for command in commands} == {runtime.agent_id}
    assert not resumed.state.outstanding_leases(next_pause.run_id)


async def test_repeated_cancel_during_parent_verifier_retains_exact_cleanup(
    harness: FleetHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = build_container(harness.state_root)
    runtime = BlockingVerifierRuntime()
    _install(container, runtime)
    active = asyncio.create_task(
        container.workflow.start(
            project_path=harness.repository_root,
            goal="Cancel during independent joined verification.",
            runtime_name="fake",
            sandbox_name="fake",
            fake_scenario=FakeScenario.PARALLEL_ENGINEERS,
        )
    )
    cleanup_started, cleanup_release = asyncio.Event(), asyncio.Event()
    actual_cleanup = container.workflow.resources.cleanup_run
    parent_cleanup_count = 0

    async def controlled_cleanup(run: Run, *, recovered: bool = False) -> None:
        nonlocal parent_cleanup_count
        if run.run_id == runtime.parent_run_id:
            assert not runtime.active
            parent_cleanup_count += 1
            cleanup_started.set()
            await cleanup_release.wait()
        await actual_cleanup(run, recovered=recovered)

    try:
        await asyncio.wait_for(runtime.entered.wait(), timeout=15)
        assert runtime.parent_run_id is not None
        parent = container.state.get_run(runtime.parent_run_id)
        assert parent.stage is WorkflowStage.VERIFYING
        assert _graph(container, parent).driver_claim is not None
        monkeypatch.setattr(container.workflow.resources, "cleanup_run", controlled_cleanup)
        active.cancel()
        await asyncio.wait_for(cleanup_started.wait(), timeout=15)
        assert _graph(container, parent).status is GraphStatus.CANCELLED
        active.cancel()
        await asyncio.sleep(0)
        assert not active.done()
        cleanup_release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(active, timeout=15)
    finally:
        cleanup_release.set()
        if not active.done():
            active.cancel()
            await asyncio.gather(active, return_exceptions=True)
    # Nested workflow frames may retry the idempotent cleanup boundary; actual
    # resource cleanup receipts must still be emitted exactly once per lease.
    assert parent_cleanup_count >= 1 and not runtime.active
    cancelled = container.state.get_run(parent.run_id)
    assert cancelled.status is RunStatus.CANCELLED
    assert not container.state.outstanding_leases(parent.run_id)
    assert not _commands(container, parent)
    assert all(
        not container.state.outstanding_leases(child.run_id)
        for child in _children(container, parent).values()
    )
    assert _graph(container, parent).driver_claim is None
    cleaned = [
        event.payload["lease_id"]
        for event in container.state.list_events(parent.run_id)
        if event.event_type in {"workspace.cleaned", "sandbox.cleaned"}
    ]
    assert cleaned and len(cleaned) == len(set(cleaned))


async def test_real_shared_active_budget_stops_parallel_writers_before_queue_or_join(
    harness: FleetHarness,
) -> None:
    container = build_container(harness.state_root)
    runtime = QueuedRuntime(container)
    _install(container, runtime)
    before = harness.git("status", "--porcelain")
    with pytest.raises(FleetError) as caught:
        await asyncio.wait_for(
            container.workflow.start(
                project_path=harness.repository_root,
                goal="Bound the aggregate parallel wait.",
                runtime_name="fake",
                sandbox_name="fake",
                fake_scenario=FakeScenario.PARALLEL_ENGINEERS,
                budget_limits=RunBudgetLimits(max_active_seconds=2),
            ),
            timeout=15,
        )
    assert caught.value.code is ErrorCode.RUNTIME_BUDGET_EXCEEDED
    parent = container.state.get_run(str(caught.value.details["run_id"]))
    assert parent.status is RunStatus.FAILED
    graph = _graph(container, parent)
    assert graph.status is GraphStatus.FAILED and graph.driver_claim is None
    assert graph.join_preparation is None and graph.join_completion is None
    assert runtime.max_active == 2 and not runtime.active
    assert runtime.executions == {"core": 1, "metadata": 1}
    assert container.budgets.snapshot(parent.run_id).active_seconds >= 2
    for child in _children(container, parent).values():
        assert not container.state.outstanding_leases(child.run_id)
        assert container.state.count_executed_intents(child.run_id, "workspace.write_file") == 0
    assert not container.state.outstanding_leases(parent.run_id)
    assert harness.git("status", "--porcelain") == before
