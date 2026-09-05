from __future__ import annotations

import pytest
from conftest import FleetHarness

from agent_fleet.bootstrap import build_container
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.evidence import CompletionGate, EvidenceBundle
from agent_fleet.domain.graph import GraphNodeStatus, GraphStatus
from agent_fleet.domain.models import ArtifactKind, FakeScenario, RunStatus

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.mark.parametrize(
    ("scenario", "roles"),
    [
        (FakeScenario.PARALLEL_ENGINEERS, ["engineer", "engineer"]),
        (FakeScenario.SPECIALIST, ["architect", "engineer", "researcher"]),
    ],
)
async def test_adaptive_graph_runs_normal_children_and_parent_verifier(
    harness: FleetHarness, scenario: FakeScenario, roles: list[str]
) -> None:
    before = harness.git("status", "--porcelain")
    run = await harness.start(scenario)
    assert run.status is RunStatus.READY_FOR_REVIEW
    assert not run.verified_complete
    container = build_container(harness.state_root)
    graph = container.graphs.get(run.run_id)
    assert graph is not None and graph.status is GraphStatus.JOINED
    assert sorted(item.node.role_id for item in graph.nodes) == roles
    assert all(item.status is GraphNodeStatus.SUCCEEDED for item in graph.nodes)
    assert graph.join_preparation is not None and graph.join_completion is not None
    assert graph.join_completion.parent_patch_sha256 == run.patch_sha256
    assert harness.git("status", "--porcelain") == before
    assert not container.state.outstanding_leases(run.run_id)
    for node in graph.nodes:
        child = container.state.get_run(node.binding.child_run_id)
        assert child.status is RunStatus.COMPLETED and not child.verified_complete
        assert child.parent_run_id == run.run_id
        assert not container.state.outstanding_leases(child.run_id)
        assert container.budgets.snapshot(child.run_id).owner_run_id == run.run_id
        with pytest.raises(FleetError) as apply_error:
            container.patches.apply(child.run_id)
        assert apply_error.value.code is ErrorCode.COMMAND_DENIED
        with pytest.raises(FleetError) as resume_error:
            await container.workflow.resume(child.run_id)
        assert resume_error.value.code is ErrorCode.COMMAND_DENIED
    assert run.command_evidence_artifact_ids
    assert all(
        container.state.get_artifact(item).run_id == run.run_id
        for item in run.command_evidence_artifact_ids
    )
    assert any(
        item.kind is ArtifactKind.GRAPH_JOIN for item in container.state.list_artifacts(run.run_id)
    )
    expected_invocations = 4 if scenario is FakeScenario.PARALLEL_ENGINEERS else 5
    assert container.budgets.snapshot(run.run_id).agent_invocations == expected_invocations
    assert container.inspection.status(run.run_id)["graph"] is not None
    assert run.evidence_bundle_artifact_id is not None
    bundle = EvidenceBundle.model_validate_json(
        container.artifacts.read_text(run.evidence_bundle_artifact_id)
    )
    assert bundle.graph_delivery is not None
    assert bundle.graph_delivery.snapshot == graph
    assert len(bundle.graph_delivery.child_cleanup_receipts) == len(roles)
    assert bundle.completion_decision is not None
    assert "GRAPH_DELIVERY_UNPROVEN" not in bundle.completion_decision.reason_codes


async def test_graph_completion_gate_rejects_unbound_or_missing_provenance(
    harness: FleetHarness,
) -> None:
    run = await harness.start(FakeScenario.PARALLEL_ENGINEERS)
    assert run.evidence_bundle_artifact_id is not None and run.task_id is not None
    state = harness.container.state
    task = state.get_task(run.task_id)
    bundle = EvidenceBundle.model_validate_json(
        harness.container.artifacts.read_text(run.evidence_bundle_artifact_id)
    )
    delivery = bundle.graph_delivery
    assert delivery is not None
    graph = delivery.snapshot
    artifact_ids = {item.artifact_id for item in state.list_artifacts(run.run_id)}
    artifact_ids.update(ref.artifact_id for node in graph.nodes for ref in node.output_artifacts)
    variants = [
        bundle.model_copy(update={"graph_delivery": None}),
        bundle.model_copy(update={"patch_sha256": "0" * 64}),
        bundle.model_copy(
            update={"graph_delivery": delivery.model_copy(update={"child_cleanup_receipts": ()})}
        ),
        bundle.model_copy(
            update={
                "graph_delivery": delivery.model_copy(
                    update={"snapshot": graph.model_copy(update={"status": GraphStatus.PAUSED})}
                )
            }
        ),
        bundle.model_copy(
            update={
                "graph_delivery": delivery.model_copy(
                    update={"snapshot": graph.model_copy(update={"plan_sha256": "0" * 64})}
                )
            }
        ),
    ]
    for candidate in variants:
        decision = CompletionGate.evaluate(
            candidate,
            expected_criteria={item.criterion_id for item in task.acceptance_criteria},
            authoritative_artifact_ids=artifact_ids,
        )
        assert not decision.verified_complete
        assert "GRAPH_DELIVERY_UNPROVEN" in decision.reason_codes
    child_artifact = graph.nodes[0].output_artifacts[0].artifact_id
    decision = CompletionGate.evaluate(
        bundle,
        expected_criteria={item.criterion_id for item in task.acceptance_criteria},
        authoritative_artifact_ids=artifact_ids - {child_artifact},
    )
    assert "GRAPH_DELIVERY_UNPROVEN" in decision.reason_codes


async def test_graph_delivery_rechecks_actual_child_artifact_bytes(
    harness: FleetHarness,
) -> None:
    run = await harness.start(FakeScenario.SPECIALIST)
    assert run.task_id is not None
    graph = harness.container.graphs.get(run.run_id)
    assert graph is not None
    ref = next(
        ref
        for node in graph.nodes
        for ref in node.output_artifacts
        if ref.kind is ArtifactKind.SPECIALIST_REPORT
    )
    metadata = harness.container.state.get_artifact(ref.artifact_id)
    path = harness.state_root / "artifacts" / metadata.content_ref
    assert path.is_file()
    path.write_bytes(b"tampered report")
    with pytest.raises(FleetError) as error:
        harness.container.workflow.evidence.assemble(
            run, harness.container.state.get_task(run.task_id)
        )
    assert error.value.code in {ErrorCode.ARTIFACT_INTEGRITY_FAILED, ErrorCode.RECOVERY_REQUIRED}
