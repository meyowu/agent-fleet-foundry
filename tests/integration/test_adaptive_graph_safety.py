"""Adversarial normal graph journeys. Fake commands are not execution proof."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

import pytest
from conftest import FleetHarness

from agent_fleet.adapters.artifacts.local import LocalArtifactStore
from agent_fleet.adapters.runtime.fake import FakeRuntimeAdapter
from agent_fleet.application.runtime import RuntimeRegistry
from agent_fleet.bootstrap import ApplicationContainer, build_container
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.graph import GraphNodeStatus, GraphSnapshot, GraphStatus
from agent_fleet.domain.models import (
    AgentInvocation,
    AgentInvocationResult,
    AgentRole,
    ApprovalChoice,
    ApprovalRequest,
    ApprovalStatus,
    ArtifactKind,
    FakeScenario,
    LeaseKind,
    LeaseStatus,
    Run,
    RunStatus,
    RuntimeToolCall,
)
from agent_fleet.domain.trust import TrustMode
from agent_fleet.ports.runtime import RuntimeInvocationServices

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


class ObservingRuntime(FakeRuntimeAdapter):
    def __init__(self, breach_path: str | None = None) -> None:
        self.requests: list[AgentInvocation] = []
        self.breach_path = breach_path

    async def invoke(
        self, request: AgentInvocation, services: RuntimeInvocationServices
    ) -> AgentInvocationResult:
        self.requests.append(request.model_copy(deep=True))
        task = request.input.get("task_spec")
        if (
            self.breach_path is not None
            and request.role == AgentRole.ENGINEER
            and isinstance(task, dict)
            and task.get("allowed_paths") == ["src/canary_calc/core.py"]
        ):
            call = RuntimeToolCall(
                call_id="adversarial-sibling-write",
                name="workspace_write_file",
                arguments={
                    "path": self.breach_path,
                    "content": "UNAUTHORIZED = True\n",
                    "reason": "Adversarial attempt outside the assigned writer scope.",
                },
            )
            services.tools.validate(call)
            assert services.accounting is not None
            services.accounting.record_simulated_step()
            services.accounting.reserve_tool_batch(1, (call.call_id,))
            await services.tools.execute(call)
            raise AssertionError("the out-of-scope writer unexpectedly executed")
        return await super().invoke(request, services)


def _observe(harness: FleetHarness, breach_path: str | None = None) -> ObservingRuntime:
    runtime = ObservingRuntime(breach_path)
    harness.container.workflow.runtimes = RuntimeRegistry({"fake": runtime})
    return runtime


def _graph(container: ApplicationContainer, parent_id: str) -> GraphSnapshot:
    graph = container.graphs.get(parent_id)
    assert graph is not None
    return graph


def _children(container: ApplicationContainer, graph: GraphSnapshot) -> list[Run]:
    return [container.state.get_run(node.binding.child_run_id) for node in graph.nodes]


def _clean(container: ApplicationContainer, graph: GraphSnapshot) -> None:
    for run_id in (graph.parent_run_id, *(node.binding.child_run_id for node in graph.nodes)):
        assert not container.state.outstanding_leases(run_id)
        for lease in container.state.list_leases(run_id):
            if lease.kind is LeaseKind.WORKTREE:
                assert lease.path is not None
                assert not Path(lease.path).exists()


def _pending(container: ApplicationContainer, child: Run) -> ApprovalRequest:
    assert child.status is RunStatus.PAUSED_FOR_APPROVAL
    assert child.pending_approval_id is not None
    request = container.state.get_approval(child.pending_approval_id)
    assert request.run_id == child.run_id
    assert request.status is ApprovalStatus.PENDING
    assert request.action == "command.run"
    return request


async def _safe_parallel(harness: FleetHarness) -> tuple[Run, GraphSnapshot]:
    harness.container.permissions.configure(
        harness.repository_root, mode=TrustMode.SAFE, allowed_paths=(".",)
    )
    parent = await harness.start(FakeScenario.PARALLEL_ENGINEERS)
    assert parent.status is RunStatus.WAITING_FOR_CHILDREN
    assert parent.pending_approval_id is None
    graph = _graph(harness.container, parent.run_id)
    assert graph.status is GraphStatus.PAUSED
    assert len(graph.nodes) == 2
    assert all(node.status is GraphNodeStatus.WAITING_APPROVAL for node in graph.nodes)
    assert all(
        harness.container.state.outstanding_leases(child.run_id)
        for child in _children(harness.container, graph)
    )
    return parent, graph


@pytest.mark.parametrize("path", ["src/canary_calc/metadata.py", ".fleet/fleet.yaml"])
async def test_parallel_writer_scope_breach_aborts_before_join_and_cleans_descendants(
    harness: FleetHarness, path: str
) -> None:
    before = harness.git("status", "--porcelain")
    runtime = _observe(harness, path)
    with pytest.raises(FleetError) as caught:
        await harness.start(FakeScenario.PARALLEL_ENGINEERS)
    assert caught.value.code is ErrorCode.COMMAND_DENIED
    parent_id = runtime.requests[0].run_id
    parent = harness.container.state.get_run(parent_id)
    graph = _graph(harness.container, parent_id)
    core = next(
        child for child in _children(harness.container, graph) if child.parent_node_id == "core"
    )
    assert harness.container.state.count_executed_intents(core.run_id, "workspace.write_file") == 0
    assert parent.status is RunStatus.FAILED
    assert parent.patch_artifact_id is None and not parent.verified_complete
    assert graph.join_completion is None
    assert all(request.role != AgentRole.VERIFIER for request in runtime.requests)
    _clean(harness.container, graph)
    assert harness.git("status", "--porcelain") == before


@pytest.mark.parametrize("damage", ["foreign-patch", "missing-reference", "missing-content"])
async def test_parallel_artifact_damage_cannot_be_joined_or_verified(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch, damage: str
) -> None:
    before = harness.git("status", "--porcelain")
    runtime = _observe(harness)
    engine = harness.container.workflow
    original = engine.graph_execution.execute_graph_child
    damaged = False

    async def corrupt_after_real_child(child: Run) -> Run:
        nonlocal damaged
        result = await original(child)
        if result.parent_node_id != "core":
            return result
        assert result.patch_artifact_id is not None and result.parent_run_id is not None
        patch = engine.state.get_artifact(result.patch_artifact_id)
        if damage == "foreign-patch":
            parent = engine.state.get_run(result.parent_run_id)
            foreign = engine.artifacts.create_text(
                kind=ArtifactKind.PATCH,
                project_id=parent.project_id,
                run_id=parent.run_id,
                task_id=parent.task_id,
                producer="adversarial-test-foreign-owner",
                content=engine.artifacts.read_text(patch.artifact_id),
                metadata=patch.metadata,
            )
            result = result.model_copy(
                update={"patch_artifact_id": foreign.artifact_id, "patch_sha256": foreign.sha256}
            )
        elif damage == "missing-reference":
            result = result.model_copy(update={"patch_artifact_id": "art_" + "f" * 32})
        else:
            assert isinstance(engine.artifacts.store, LocalArtifactStore)
            blob = engine.artifacts.store.root / patch.content_ref
            blob.rename(blob.with_suffix(".missing-fixture"))
        engine.state.save_run(result, "test.artifact_tampered", {"damage": damage})
        damaged = True
        return result

    monkeypatch.setattr(engine.graph_execution, "execute_graph_child", corrupt_after_real_child)
    with pytest.raises(FleetError):
        await harness.start(FakeScenario.PARALLEL_ENGINEERS)
    assert damaged
    parent_id = runtime.requests[0].run_id
    parent = engine.state.get_run(parent_id)
    graph = _graph(harness.container, parent_id)
    assert parent.status is RunStatus.FAILED
    assert not parent.verified_complete and parent.patch_artifact_id is None
    assert graph.join_completion is None
    assert all(request.role != AgentRole.VERIFIER for request in runtime.requests)
    _clean(harness.container, graph)
    assert harness.git("status", "--porcelain") == before


@pytest.mark.parametrize("damage", ["foreign-task", "missing-content"])
async def test_specialist_dependency_damage_blocks_downstream_role_creation(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch, damage: str
) -> None:
    runtime = _observe(harness)
    engine = harness.container.workflow
    original = engine.graph_execution.execute_graph_child
    damaged = False

    async def corrupt_report(child: Run) -> Run:
        nonlocal damaged
        result = await original(child)
        if result.parent_node_id != "researcher":
            return result
        report = next(
            item
            for item in engine.state.list_artifacts(result.run_id)
            if item.kind is ArtifactKind.SPECIALIST_REPORT
        )
        if damage == "foreign-task":
            assert result.parent_run_id is not None
            parent = engine.state.get_run(result.parent_run_id)
            forged = report.model_copy(update={"task_id": parent.task_id})
            with harness.container.state._connect() as connection:
                connection.execute(
                    "UPDATE artifacts SET data_json = ? WHERE artifact_id = ?",
                    (forged.model_dump_json(), report.artifact_id),
                )
        else:
            assert isinstance(engine.artifacts.store, LocalArtifactStore)
            blob = engine.artifacts.store.root / report.content_ref
            blob.rename(blob.with_suffix(".missing-fixture"))
        damaged = True
        return result

    monkeypatch.setattr(engine.graph_execution, "execute_graph_child", corrupt_report)
    with pytest.raises(FleetError):
        await harness.start(FakeScenario.SPECIALIST)
    assert damaged
    graph = _graph(harness.container, runtime.requests[0].run_id)
    assert [request.role for request in runtime.requests] == [AgentRole.COS, AgentRole.RESEARCHER]
    assert graph.join_completion is None
    assert harness.container.state.get_run(graph.parent_run_id).status is RunStatus.FAILED
    _clean(harness.container, graph)


@pytest.mark.parametrize("clear_parent_flags", [False, True])
async def test_public_child_operations_fail_closed_even_without_mutable_parent_flags(
    harness: FleetHarness, clear_parent_flags: bool
) -> None:
    parent = await harness.start(FakeScenario.PARALLEL_ENGINEERS)
    graph = _graph(harness.container, parent.run_id)
    child = _children(harness.container, graph)[0]
    original = child.model_dump_json()
    if clear_parent_flags:
        payload = json.loads(original)
        for field in ("parent_run_id", "parent_plan_sha256", "parent_node_id", "parent_iteration"):
            payload[field] = None
        with harness.container.state._connect() as connection:
            connection.execute(
                "UPDATE runs SET data_json = ? WHERE run_id = ?",
                (json.dumps(payload), child.run_id),
            )
    try:
        container = build_container(harness.state_root)
        before = container.state.get_run(child.run_id)
        events = container.state.list_events(child.run_id)
        for operation in ("apply", "resume", "cancel", "recover"):
            with pytest.raises(FleetError) as caught:
                if operation == "apply":
                    container.patches.apply(child.run_id)
                elif operation == "resume":
                    await container.workflow.resume(child.run_id)
                elif operation == "cancel":
                    await container.cancellation.cancel(child.run_id)
                else:
                    await container.recovery.recover_run(child.run_id)
            assert caught.value.code is (
                ErrorCode.RECOVERY_REQUIRED
                if clear_parent_flags or operation == "recover"
                else ErrorCode.COMMAND_DENIED
            )
            assert container.state.get_run(child.run_id) == before
            assert container.state.list_events(child.run_id) == events
            assert container.state.get_run(parent.run_id) == parent
    finally:
        with harness.container.state._connect() as connection:
            connection.execute(
                "UPDATE runs SET data_json = ? WHERE run_id = ?", (original, child.run_id)
            )
    _clean(harness.container, graph)


@pytest.mark.parametrize("choice", [ApprovalChoice.ALLOW_ONCE, ApprovalChoice.ALLOW_RUN])
async def test_child_grants_do_not_authorize_sibling_or_parent_after_reconstruction(
    harness: FleetHarness, choice: ApprovalChoice
) -> None:
    parent, graph = await _safe_parallel(harness)
    children = _children(harness.container, graph)
    core = next(child for child in children if child.parent_node_id == "core")
    sibling = next(child for child in children if child.parent_node_id == "metadata")
    sibling_request = _pending(harness.container, sibling)
    grants = []
    for child in (core, sibling):
        for command_id in ("python-build", "python-test"):
            container = build_container(harness.state_root)
            request = _pending(container, container.state.get_run(child.run_id))
            assert request.resource.identifier == command_id
            if child.run_id == core.run_id and command_id == "python-build":
                # The reviewed command/role/stage/isolation scopes are identical;
                # the durable child Run identity still prevents grant transfer.
                assert request.authorization_scope == sibling_request.authorization_scope
                assert request.run_id != sibling_request.run_id
            grants.append(container.approvals.approve(request.request_id, choice=choice))
            container = build_container(harness.state_root)
            parent = await container.workflow.resume(parent.run_id)
            assert all(
                grant.run_id == child.run_id for grant in container.state.list_grants(child.run_id)
            )
            if child.run_id == core.run_id:
                assert parent.status is RunStatus.WAITING_FOR_CHILDREN
                assert (
                    _pending(container, container.state.get_run(sibling.run_id)) == sibling_request
                )
                assert container.state.count_executed_intents(sibling.run_id, "command.run") == 0
                assert container.state.list_grants(sibling.run_id) == []
    container = build_container(harness.state_root)
    assert parent.status is RunStatus.PAUSED_FOR_APPROVAL
    parent_request = _pending(container, parent)
    assert parent_request.principal_role == "verifier"
    assert container.state.count_executed_intents(parent.run_id, "command.run") == 0
    assert container.state.list_grants(parent.run_id) == []
    assert len({grant.grant_id for grant in grants}) == 4
    assert {grant.run_id for grant in grants} == {core.run_id, sibling.run_id}
    assert all(
        container.state.count_executed_intents(child.run_id, "command.run") == 2
        for child in children
    )
    await container.cancellation.cancel(parent.run_id)
    _clean(container, graph)


@pytest.mark.parametrize("operation", ["cancel", "recover"])
async def test_parent_cleanup_releases_exact_descendants_and_preserves_unrelated_run(
    harness: FleetHarness, operation: Literal["cancel", "recover"]
) -> None:
    parent, graph = await _safe_parallel(harness)
    unrelated = await harness.start(FakeScenario.SUCCESS)
    assert unrelated.status is RunStatus.PAUSED_FOR_APPROVAL
    unrelated_leases = harness.container.state.outstanding_leases(unrelated.run_id)
    assert unrelated_leases
    if operation == "recover":
        # Ordinary durable resume boundary: a claim exists, but its test owner
        # stops before dispatch. No finished Run or execution evidence is injected.
        harness.container.graphs.claim_driver(parent.run_id, expected_revision=graph.revision)
        harness.container.state.save_run(
            parent.model_copy(update={"status": RunStatus.RUNNING}),
            "graph.resumed",
            {"status": "running"},
        )
    container = build_container(harness.state_root)
    if operation == "recover":
        result = await container.recovery.recover_run(parent.run_id)
        assert result.status is RunStatus.FAILED
    else:
        result = await container.cancellation.cancel(parent.run_id)
        assert result.status is RunStatus.CANCELLED
    current_graph = _graph(container, parent.run_id)
    assert current_graph.status is GraphStatus.CANCELLED
    assert current_graph.driver_claim is None and current_graph.cancel_requested_at is not None
    assert all(child.status is RunStatus.CANCELLED for child in _children(container, current_graph))
    _clean(container, current_graph)
    assert container.state.get_run(unrelated.run_id) == unrelated
    assert container.state.outstanding_leases(unrelated.run_id) == unrelated_leases
    await container.cancellation.cancel(unrelated.run_id)


async def test_cancel_retries_failed_descendant_cleanup_without_parent_leases(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent, graph = await _safe_parallel(harness)
    assert not harness.container.state.outstanding_leases(parent.run_id)
    retained = _children(harness.container, graph)[0]
    resources = harness.container.workflow.resources
    original = resources.cleanup_run
    failed = False

    async def fail_one_child(run: Run, *, recovered: bool = False) -> None:
        nonlocal failed
        if run.run_id == retained.run_id and not failed:
            failed = True
            raise FleetError(
                ErrorCode.SANDBOX_CLEANUP_FAILED,
                "Injected child cleanup failure.",
                "Retain exact descendant leases and retry parent cleanup.",
            )
        await original(run, recovered=recovered)

    monkeypatch.setattr(resources, "cleanup_run", fail_one_child)
    with pytest.raises(FleetError) as caught:
        await harness.container.cancellation.cancel(parent.run_id)
    assert caught.value.code is ErrorCode.SANDBOX_CLEANUP_FAILED and failed
    assert harness.container.state.get_run(parent.run_id).status is RunStatus.CANCELLED
    assert harness.container.state.outstanding_leases(retained.run_id)
    assert not harness.container.state.outstanding_leases(parent.run_id)
    container = build_container(harness.state_root)
    result = await container.cancellation.cancel(parent.run_id)
    assert result.status is RunStatus.CANCELLED
    _clean(container, graph)
    assert all(
        lease.status in {LeaseStatus.RELEASED, LeaseStatus.RECOVERED}
        for child in _children(container, graph)
        for lease in container.state.list_leases(child.run_id)
    )
