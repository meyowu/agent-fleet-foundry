"""Independent graph-delivery checks built from normal offline workflow runs."""

from __future__ import annotations

from typing import Literal

import pytest
from conftest import FleetHarness
from pydantic import ValidationError

from agent_fleet.bootstrap import ApplicationContainer, build_container
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.evidence import CompletionGate, EvidenceBundle
from agent_fleet.domain.graph import GraphJoinInput, GraphSnapshot, GraphStatus
from agent_fleet.domain.models import ApprovalChoice, ArtifactKind, FakeScenario, Run, RunStatus
from agent_fleet.domain.security import canonical_json_hash
from agent_fleet.domain.trust import TrustMode

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _graph(container: ApplicationContainer, run_id: str) -> GraphSnapshot:
    graph = container.graphs.get(run_id)
    assert graph is not None
    return graph


def _assert_clean(container: ApplicationContainer, graph: GraphSnapshot) -> None:
    assert not container.state.outstanding_leases(graph.parent_run_id)
    assert all(
        not container.state.outstanding_leases(node.binding.child_run_id) for node in graph.nodes
    )


async def _parent_verifier_pause(harness: FleetHarness) -> Run:
    harness.container.permissions.configure(
        harness.repository_root, mode=TrustMode.SAFE, allowed_paths=(".",)
    )
    parent = await harness.start(FakeScenario.PARALLEL_ENGINEERS)
    for _ in range(4):
        if parent.status is RunStatus.PAUSED_FOR_APPROVAL:
            assert parent.pending_approval_id is not None
            request = harness.container.state.get_approval(parent.pending_approval_id)
            assert request.principal_role == "verifier"
            assert harness.container.state.count_executed_intents(parent.run_id, "command.run") == 0
            return parent
        assert parent.status is RunStatus.WAITING_FOR_CHILDREN
        graph = _graph(harness.container, parent.run_id)
        for node in graph.nodes:
            child = harness.container.state.get_run(node.binding.child_run_id)
            if child.status is RunStatus.PAUSED_FOR_APPROVAL:
                assert child.pending_approval_id is not None
                harness.container.approvals.approve(
                    child.pending_approval_id, choice=ApprovalChoice.ALLOW_ONCE
                )
        parent = await build_container(harness.state_root).workflow.resume(parent.run_id)
    raise AssertionError("normal graph did not reach its bounded parent verifier pause")


@pytest.mark.parametrize("failure", ["rehydration", "resume-persistence"])
async def test_parent_continuation_failure_cannot_replay_and_is_explicitly_recoverable(
    harness: FleetHarness,
    monkeypatch: pytest.MonkeyPatch,
    failure: Literal["rehydration", "resume-persistence"],
) -> None:
    parent = await _parent_verifier_pause(harness)
    assert parent.pending_approval_id is not None
    grant = harness.container.approvals.approve(
        parent.pending_approval_id, choice=ApprovalChoice.ALLOW_ONCE
    )
    resuming = build_container(harness.state_root)
    graph_before = _graph(resuming, parent.run_id)
    child_commands = {
        node.binding.child_run_id: resuming.state.count_executed_intents(
            node.binding.child_run_id, "command.run"
        )
        for node in graph_before.nodes
    }
    code = (
        ErrorCode.SANDBOX_INSPECTION_FAILED
        if failure == "rehydration"
        else ErrorCode.STATE_UNAVAILABLE
    )
    injected = False

    async def failed_rehydrate(run: Run) -> None:
        nonlocal injected
        assert run.run_id == parent.run_id
        injected = True
        raise FleetError(
            code, "Injected failure after continuation ownership.", "Recover the exact owner."
        )

    original_save = resuming.state.save_run

    def failed_save(run: Run, event_type: str, payload: dict[str, object]) -> Run:
        nonlocal injected
        if run.run_id == parent.run_id and event_type == "run.resumed":
            injected = True
            raise FleetError(
                code, "Injected lost resume persistence.", "Recover the stopped owner."
            )
        return original_save(run, event_type, payload)

    if failure == "rehydration":
        monkeypatch.setattr(
            resuming.workflow.resources, "rehydrate_paused_sandboxes", failed_rehydrate
        )
    else:
        monkeypatch.setattr(resuming.state, "save_run", failed_save)
    with pytest.raises(FleetError) as caught:
        await resuming.workflow.resume(parent.run_id)
    assert injected and caught.value.code is code
    current = resuming.state.get_run(parent.run_id)
    graph = _graph(resuming, parent.run_id)
    assert resuming.state.count_executed_intents(parent.run_id, "command.run") == 0
    assert resuming.state.get_grant(grant.grant_id).remaining_uses == 1
    assert all(
        resuming.state.count_executed_intents(run_id, "command.run") == count
        for run_id, count in child_commands.items()
    )
    if failure == "rehydration":
        assert current.status is RunStatus.FAILED
        assert graph.driver_claim is None
        assert graph.status is GraphStatus.CANCELLED and graph.cancel_requested_at is not None
        _assert_clean(resuming, graph)
    else:
        # A generic StateStore error cannot prove rollback/no side effect. The
        # retained claim is deliberately non-reclaimable by ordinary resume.
        assert current.status is RunStatus.PAUSED_FOR_APPROVAL
        assert graph.driver_claim is not None and graph.status is GraphStatus.RUNNING
        reopened = build_container(harness.state_root)
        with pytest.raises(FleetError) as retry:
            await reopened.workflow.resume(parent.run_id)
        assert retry.value.code is ErrorCode.RECOVERY_REQUIRED
        assert reopened.state.count_executed_intents(parent.run_id, "command.run") == 0
        recovered = await reopened.recovery.recover_run(parent.run_id)
        assert recovered.status is RunStatus.FAILED
        graph = _graph(reopened, parent.run_id)
        assert graph.status is GraphStatus.CANCELLED and graph.driver_claim is None
        _assert_clean(reopened, graph)


@pytest.mark.parametrize("changed_paths", [[], ["src/canary_calc/metadata.py"]])
async def test_join_rechecks_child_patch_scope_metadata_before_parent_verification(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch, changed_paths: list[str]
) -> None:
    engine = harness.container.workflow
    original = engine.graph_execution.join_graph_candidates
    parent_id: str | None = None

    async def tampered_join(parent: Run, inputs: tuple[GraphJoinInput, ...]) -> Run:
        nonlocal parent_id
        parent_id = parent.run_id
        item = next(value for value in inputs if value.node_id == "core")
        artifact = engine.state.get_artifact(item.patch_artifact_id)
        damaged = artifact.model_copy(update={"metadata": {"changed_paths": changed_paths}})
        with harness.container.state._connect() as connection:
            connection.execute(
                "UPDATE artifacts SET data_json = ? WHERE artifact_id = ?",
                (damaged.model_dump_json(), artifact.artifact_id),
            )
        return await original(parent, inputs)

    monkeypatch.setattr(engine.graph_execution, "join_graph_candidates", tampered_join)
    with pytest.raises(FleetError):
        await harness.start(FakeScenario.PARALLEL_ENGINEERS)
    assert parent_id is not None
    run = engine.state.get_run(parent_id)
    graph = _graph(harness.container, parent_id)
    assert run.status is RunStatus.FAILED
    assert run.patch_artifact_id is None and run.verifier_agent_instance_id is None
    assert graph.join_completion is None
    _assert_clean(harness.container, graph)


@pytest.mark.parametrize("corruption", ["child-scope", "coherent-plan-substitution"])
@pytest.mark.parametrize("boundary", ["json-schema", "model-copy"])
async def test_delivery_gate_rejects_graph_definitions_unbound_to_original_plan(
    harness: FleetHarness, corruption: str, boundary: str
) -> None:
    run = await harness.start(FakeScenario.PARALLEL_ENGINEERS)
    assert run.evidence_bundle_artifact_id is not None and run.task_id is not None
    bundle = EvidenceBundle.model_validate_json(
        harness.container.artifacts.read_text(run.evidence_bundle_artifact_id)
    )
    delivery = bundle.graph_delivery
    assert delivery is not None
    graph = delivery.snapshot
    authoritative = {
        item.artifact_id
        for owner in [run.run_id, *[node.binding.child_run_id for node in graph.nodes]]
        for item in harness.container.state.list_artifacts(owner)
    }
    expected = {
        item.criterion_id
        for item in harness.container.state.get_task(run.task_id).acceptance_criteria
    }
    assert (
        "GRAPH_DELIVERY_UNPROVEN"
        not in CompletionGate.evaluate(
            bundle, expected_criteria=expected, authoritative_artifact_ids=authoritative
        ).reason_codes
    )
    first = graph.nodes[0]
    if corruption == "child-scope":
        changed_node = first.node.model_copy(update={"scope": ["src/canary_calc"]})
        changed_plan = graph.plan
    else:
        changed_node = first.node.model_copy(
            update={"goal": "Substitute an unreviewed child goal."}
        )
        changed_plan = graph.plan.model_copy(
            update={
                "nodes": [
                    changed_node if node.node_id == first.node.node_id else node
                    for node in graph.plan.nodes
                ]
            }
        )
    changed_record = first.model_copy(
        update={
            "node": changed_node,
            "binding": first.binding.model_copy(
                update={
                    "node_sha256": canonical_json_hash(changed_node.model_dump(mode="json")),
                }
            ),
        }
    )
    changed_graph = graph.model_copy(
        update={"plan": changed_plan, "nodes": (changed_record, *graph.nodes[1:])}
    )
    altered = bundle.model_copy(
        update={"graph_delivery": delivery.model_copy(update={"snapshot": changed_graph})}
    )
    if boundary == "json-schema":
        try:
            altered = EvidenceBundle.model_validate_json(altered.model_dump_json())
        except ValidationError:
            return  # The validated public boundary itself rejected the mismatch.
    decision = CompletionGate.evaluate(
        altered, expected_criteria=expected, authoritative_artifact_ids=authoritative
    )
    assert "GRAPH_DELIVERY_UNPROVEN" in decision.reason_codes
    assert not decision.verified_complete


async def test_delivery_assembler_rejects_removed_child_cleanup_bytes(
    harness: FleetHarness,
) -> None:
    run = await harness.start(FakeScenario.PARALLEL_ENGINEERS)
    graph = _graph(harness.container, run.run_id)
    child = harness.container.state.get_run(graph.nodes[0].binding.child_run_id)
    assert child.cleanup_receipt_artifact_id is not None and run.task_id is not None
    metadata = harness.container.state.get_artifact(child.cleanup_receipt_artifact_id)
    assert metadata.kind is ArtifactKind.RESOURCE_CLEANUP
    store = harness.container.artifacts.store
    from agent_fleet.adapters.artifacts.local import LocalArtifactStore

    assert isinstance(store, LocalArtifactStore)
    path = store.root / metadata.content_ref
    missing = path.with_suffix(".missing-fixture")
    path.rename(missing)
    try:
        with pytest.raises(FleetError) as caught:
            harness.container.workflow.evidence.assemble(
                run, harness.container.state.get_task(run.task_id)
            )
        assert caught.value.code is ErrorCode.ARTIFACT_INTEGRITY_FAILED
        assert caught.value.__context__ is None
        assert str(harness.state_root) not in str(caught.value)
    finally:
        missing.rename(path)


@pytest.mark.parametrize("corruption", ["cleanup-content", "join-hash"])
async def test_delivery_gate_binds_embedded_receipts_to_their_artifact_hashes(
    harness: FleetHarness, corruption: str
) -> None:
    run = await harness.start(FakeScenario.PARALLEL_ENGINEERS)
    assert run.evidence_bundle_artifact_id is not None and run.task_id is not None
    bundle = EvidenceBundle.model_validate_json(
        harness.container.artifacts.read_text(run.evidence_bundle_artifact_id)
    )
    delivery = bundle.graph_delivery
    assert delivery is not None
    authoritative = {
        artifact.artifact_id
        for owner in [
            run.run_id,
            *[node.binding.child_run_id for node in delivery.snapshot.nodes],
        ]
        for artifact in harness.container.state.list_artifacts(owner)
    }
    expected = {
        item.criterion_id
        for item in harness.container.state.get_task(run.task_id).acceptance_criteria
    }
    baseline = CompletionGate.evaluate(
        bundle, expected_criteria=expected, authoritative_artifact_ids=authoritative
    )
    assert "GRAPH_DELIVERY_UNPROVEN" not in baseline.reason_codes
    if corruption == "cleanup-content":
        first = delivery.child_cleanup_receipts[0]
        assert first.leases and first.complete
        forged = delivery.model_copy(
            update={
                "child_cleanup_receipts": (
                    first.model_copy(update={"leases": []}),
                    *delivery.child_cleanup_receipts[1:],
                )
            }
        )
    else:
        forged = delivery.model_copy(
            update={"join_artifact": delivery.join_artifact.model_copy(update={"sha256": "0" * 64})}
        )
    altered = EvidenceBundle.model_validate_json(
        bundle.model_copy(update={"graph_delivery": forged}).model_dump_json()
    )
    decision = CompletionGate.evaluate(
        altered, expected_criteria=expected, authoritative_artifact_ids=authoritative
    )
    assert "GRAPH_DELIVERY_UNPROVEN" in decision.reason_codes
    assert not decision.verified_complete
