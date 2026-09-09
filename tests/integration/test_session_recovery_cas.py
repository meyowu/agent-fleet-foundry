"""Real-store interleavings for reviewed recovery, never a dynamic cleanup sweep."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Literal, cast

import pytest
from conftest import FleetHarness
from pydantic import JsonValue
from test_session_recovery import orphan

from agent_fleet.application.conversations import ChatExecutionOptions
from agent_fleet.bootstrap import build_container
from agent_fleet.domain.conversation import ConversationClaim, ConversationTurn
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.ids import IdPrefix
from agent_fleet.domain.models import (
    FakeScenario,
    LeaseKind,
    LeaseStatus,
    ResourceLease,
    Run,
    SandboxExecutionHandle,
    SandboxHandle,
    Workspace,
    WorkspaceKind,
)
from agent_fleet.domain.recovery_binding import (
    RecoveryBinding,
    RecoveryLeaseClaim,
    ReviewedRecoveryPlan,
)
from agent_fleet.domain.security import canonical_json_hash
from agent_fleet.domain.session_review import SessionSelection
from agent_fleet.domain.trust import TrustMode
from agent_fleet.ports.conversation import ConversationStore

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _replace_lease(harness: FleetHarness, lease: ResourceLease) -> None:
    with sqlite3.connect(harness.container.state.database_path) as connection:
        connection.execute(
            "UPDATE resource_leases SET resource_id=?,status=?,data_json=? WHERE lease_id=?",
            (lease.resource_id, lease.status.value, lease.model_dump_json(), lease.lease_id),
        )


async def _fresh_cleanup(harness: FleetHarness, conversation: str) -> None:
    service = harness.container.conversations
    code = cast(str, (await service.recover(conversation))["recovery_code"])
    result = await service.recover(conversation, code=code, confirm_owner_stopped=True)
    assert result["outstanding_lease_ids"] == [] and result["replayed"] is False


@pytest.mark.parametrize("corruption", ["missing-kind", "invalid-kind", "missing-path"])
async def test_corrupt_original_workspace_is_rejected_without_fencing(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch, corruption: str
) -> None:
    conversation, run_id = await orphan(harness, monkeypatch)
    container = harness.container
    workspace, lease = container.workflow.resources.create_workspace(
        container.state.get_run(run_id), WorkspaceKind.CANDIDATE
    )
    invalid = lease.model_copy(
        update={"path": None}
        if corruption == "missing-path"
        else {
            "metadata": {}
            if corruption == "missing-kind"
            else lease.metadata | {"workspace_kind": "untrusted-invalid-kind"}
        }
    )
    _replace_lease(harness, invalid)
    service = container.conversations
    before_run = container.state.get_run(run_id)
    before_events = container.state.list_events(run_id)
    before_view = service.status(conversation)
    try:
        code = cast(str, (await service.recover(conversation))["recovery_code"])
        with pytest.raises(FleetError) as caught:
            await service.recover(conversation, code=code, confirm_owner_stopped=True)
        assert caught.value.code is ErrorCode.RECOVERY_REQUIRED
        assert caught.value.message == "A reviewed resource has an invalid cleanup identity."
        assert caught.value.__cause__ is None and caught.value.__context__ is None
        assert container.state.get_run(run_id) == before_run
        assert container.state.list_events(run_id) == before_events
        assert container.state.get_lease(lease.lease_id) == invalid
        assert service.status(conversation) == before_view
        assert await asyncio.to_thread(Path(workspace.path).is_dir)
        with pytest.raises(FleetError):
            await service.recover(conversation, code=code, confirm_owner_stopped=True)
    finally:
        _replace_lease(harness, lease)
        await _fresh_cleanup(harness, conversation)
    assert not await asyncio.to_thread(Path(workspace.path).exists)


@pytest.mark.parametrize(
    "corruption",
    [
        "sandbox-missing",
        "sandbox-hash",
        "execution-missing-sandbox",
        "execution-malformed-handle",
        "execution-binding",
        "execution-incomplete-intent",
    ],
)
async def test_captured_sandbox_and_execution_preflight_is_pure_and_fail_closed(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch, corruption: str
) -> None:
    conversation, run_id = await orphan(harness, monkeypatch)
    container = harness.container
    resources = container.workflow.resources
    workspace, lease = resources.create_workspace(
        container.state.get_run(run_id), WorkspaceKind.CANDIDATE
    )
    service = container.conversations
    code = cast(str, (await service.recover(conversation))["recovery_code"])
    recovery = service.session_recovery
    assert recovery is not None
    snapshot = recovery._tickets[code].binding.snapshot()
    sandbox = SandboxHandle(
        sandbox_id=resources.ids.new(IdPrefix.SANDBOX),
        run_id=run_id,
        project_id=snapshot.project.project_id,
        workspace_host_path=workspace.path,
    )
    execution = SandboxExecutionHandle(
        execution_id=resources.ids.new(IdPrefix.EXECUTION),
        sandbox_id=sandbox.sandbox_id,
        run_id=run_id,
        provider="fake",
        native_resource_id="not-created",
        labels={"fixture": "not-created"},
        labels_sha256=canonical_json_hash({"fixture": "not-created"}),
    )
    metadata: dict[str, JsonValue]
    if corruption.startswith("sandbox-"):
        metadata = (
            {}
            if corruption == "sandbox-missing"
            else {"handle": sandbox.model_dump(mode="json"), "capabilities_hash": "0" * 64}
        )
        invalid = lease.model_copy(
            update={
                "kind": LeaseKind.SANDBOX,
                "resource_id": sandbox.sandbox_id,
                "path": None,
                "metadata": metadata,
            }
        )
    else:
        metadata = {"provider": "fake", "sandbox_handle": sandbox.model_dump(mode="json")}
        if corruption == "execution-missing-sandbox":
            metadata.clear()
        elif corruption == "execution-malformed-handle":
            metadata["execution_handle"] = {"native_resource_id": "untrusted-invalid-handle"}
        elif corruption == "execution-binding":
            metadata["execution_handle"] = execution.model_copy(
                update={"execution_id": resources.ids.new(IdPrefix.EXECUTION)}
            ).model_dump(mode="json")
        invalid = lease.model_copy(
            update={
                "kind": LeaseKind.EXECUTION,
                "resource_id": execution.execution_id,
                "path": None,
                "metadata": metadata,
            }
        )
    snapshot.leases = (invalid,)
    binding = RecoveryBinding(snapshot_json=snapshot.model_dump_json())
    before_events = container.state.list_events(run_id)

    class NoPortAccess:
        def __getattr__(self, name: str) -> object:
            raise AssertionError(f"Pure preflight accessed an external port: {name}")

    try:
        with monkeypatch.context() as patch:
            for name in ("state", "repository", "sandboxes", "clock", "ids"):
                patch.setattr(resources, name, NoPortAccess())
            with pytest.raises(FleetError) as caught:
                resources.validate_reviewed_recovery(binding)
        assert caught.value.code is ErrorCode.RECOVERY_REQUIRED
        assert caught.value.message == "A reviewed resource has an invalid cleanup identity."
        assert caught.value.__cause__ is None and caught.value.__context__ is None
        assert container.state.list_events(run_id) == before_events
        assert container.state.get_lease(lease.lease_id) == lease
        assert await asyncio.to_thread(Path(workspace.path).is_dir)
    finally:
        await _fresh_cleanup(harness, conversation)


@pytest.mark.parametrize("boundary", ["after-snapshot", "after-fence", "before-claim"])
async def test_late_real_lease_is_never_added_to_old_review(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch, boundary: str
) -> None:
    conversation, run_id = await orphan(harness, monkeypatch)
    service = harness.container.conversations
    store = harness.container.conversation_store
    resources = harness.container.workflow.resources
    resources.create_workspace(harness.container.state.get_run(run_id), WorkspaceKind.CANDIDATE)
    code = cast(str, (await service.recover(conversation))["recovery_code"])
    recovery = service.session_recovery
    assert recovery is not None
    added: list[tuple[Workspace, ResourceLease]] = []

    def add() -> None:
        added.append(
            resources.create_workspace(
                harness.container.state.get_run(run_id), WorkspaceKind.VERIFICATION
            )
        )

    original_snapshot = recovery._snapshot
    original_prepare = store.prepare_reviewed_recovery
    original_claim = store.claim_recovery_lease

    def snapshot(selection: SessionSelection) -> tuple[Run, RecoveryBinding, dict[str, JsonValue]]:
        result = original_snapshot(selection)
        add()
        return result

    def prepare(binding: RecoveryBinding) -> ReviewedRecoveryPlan:
        result = original_prepare(binding)
        add()
        return result

    def claim(plan: ReviewedRecoveryPlan, lease_id: str) -> RecoveryLeaseClaim:
        add()
        return original_claim(plan, lease_id)

    before_events = harness.container.state.list_events(run_id)
    with monkeypatch.context() as patch:
        if boundary == "after-snapshot":
            patch.setattr(recovery, "_snapshot", snapshot)
        elif boundary == "after-fence":
            patch.setattr(store, "prepare_reviewed_recovery", prepare)
        else:
            patch.setattr(store, "claim_recovery_lease", claim)
        with pytest.raises(FleetError):
            await service.recover(conversation, code=code, confirm_owner_stopped=True)
    assert len(added) == 1
    workspace, lease = added[0]
    assert await asyncio.to_thread(Path(workspace.path).is_dir)
    assert harness.container.state.get_lease(lease.lease_id) == lease
    assert service.status(conversation)["recovery_required"]
    if boundary == "after-snapshot":
        assert not any(
            event.event_type == "conversation.turn_fenced"
            for event in harness.container.state.list_events(run_id)[len(before_events) :]
        )
    await _fresh_cleanup(harness, conversation)
    assert not await asyncio.to_thread(Path(workspace.path).exists)


@pytest.mark.parametrize("change", ["path", "metadata"])
async def test_same_id_full_payload_change_before_claim_is_not_substituted(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    conversation, run_id = await orphan(harness, monkeypatch)
    service = harness.container.conversations
    resources = harness.container.workflow.resources
    workspace, lease = resources.create_workspace(
        harness.container.state.get_run(run_id), WorkspaceKind.CANDIDATE
    )
    other, _ = resources.create_workspace(
        harness.container.state.get_run(run_id), WorkspaceKind.VERIFICATION
    )
    code = cast(str, (await service.recover(conversation))["recovery_code"])
    store = harness.container.conversation_store
    original = store.prepare_reviewed_recovery
    replacement = lease.model_copy(
        update={"path": other.path}
        if change == "path"
        else {"metadata": lease.metadata | {"late_metadata": "not reviewed"}}
    )

    def prepare(binding: RecoveryBinding) -> ReviewedRecoveryPlan:
        plan = original(binding)
        _replace_lease(harness, replacement)
        return plan

    with monkeypatch.context() as patch:
        patch.setattr(store, "prepare_reviewed_recovery", prepare)
        with pytest.raises(FleetError):
            await service.recover(conversation, code=code, confirm_owner_stopped=True)
    assert harness.container.state.get_lease(lease.lease_id) == replacement
    assert await asyncio.to_thread(Path(workspace.path).is_dir)
    assert await asyncio.to_thread(Path(other.path).is_dir)
    _replace_lease(harness, lease)
    await _fresh_cleanup(harness, conversation)


async def test_after_claim_replacement_is_not_cleaned_or_overwritten(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    conversation, run_id = await orphan(harness, monkeypatch)
    service = harness.container.conversations
    resources = harness.container.workflow.resources
    run = harness.container.state.get_run(run_id)
    workspace, lease = resources.create_workspace(run, WorkspaceKind.CANDIDATE)
    # Materialize an exact, independently owned fixture workspace without adding
    # it to the reviewed lease set. The test restores/journals it for cleanup.
    repository = resources.repository
    other = repository.prepare_workspace(run_id, run.base_revision, WorkspaceKind.VERIFICATION)
    repository.materialize_workspace(harness.repository_root, other)
    code = cast(str, (await service.recover(conversation))["recovery_code"])
    store = harness.container.conversation_store
    original = store.claim_recovery_lease
    claimed: list[ResourceLease] = []
    replacement: list[ResourceLease] = []

    def claim(plan: ReviewedRecoveryPlan, lease_id: str) -> RecoveryLeaseClaim:
        result = original(plan, lease_id)
        claimed.append(result.lease())
        replacement.append(
            result.lease().model_copy(
                update={
                    "path": other.path,
                    "resource_id": other.workspace_id,
                    "metadata": {
                        "workspace_kind": other.kind.value,
                        "base_revision": other.base_revision,
                    },
                }
            )
        )
        _replace_lease(harness, replacement[-1])
        return result

    with monkeypatch.context() as patch:
        patch.setattr(store, "claim_recovery_lease", claim)
        with pytest.raises(FleetError):
            await service.recover(conversation, code=code, confirm_owner_stopped=True)
    assert len(claimed) == 1
    assert not await asyncio.to_thread(Path(workspace.path).exists)
    assert await asyncio.to_thread(Path(other.path).is_dir)
    assert harness.container.state.get_lease(lease.lease_id) == replacement[0]
    assert service.status(conversation)["recovery_required"]
    _replace_lease(harness, claimed[0])
    resources.lease_workspace(other)
    await _fresh_cleanup(harness, conversation)


async def test_original_revision_is_compared_and_fenced_in_one_write_transaction(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    conversation, run_id = await orphan(harness, monkeypatch)
    service = harness.container.conversations
    store = harness.container.conversation_store
    code = cast(str, (await service.recover(conversation))["recovery_code"])
    recovery = service.session_recovery
    assert recovery is not None
    original_turn = recovery._tickets[code].binding.snapshot().turn
    original_fence = store._fence_in_transaction
    observed: list[int] = []

    def fence(
        connection: sqlite3.Connection,
        selected_run: str,
        *,
        expected_revision: int,
        reason: Literal["cancel", "recovery"],
        claim: ConversationClaim | None = None,
    ) -> ConversationTurn:
        assert connection.in_transaction
        assert selected_run == run_id and expected_revision == original_turn.revision
        with (
            sqlite3.connect(store.database_path, timeout=0) as contender,
            pytest.raises(sqlite3.OperationalError, match="locked"),
        ):
            contender.execute("BEGIN IMMEDIATE")
        observed.append(expected_revision)
        return original_fence(
            connection,
            selected_run,
            expected_revision=expected_revision,
            reason=reason,
            claim=claim,
        )

    with monkeypatch.context() as patch:
        patch.setattr(store, "_fence_in_transaction", fence)
        await service.recover(conversation, code=code, confirm_owner_stopped=True)
    assert observed == [original_turn.revision]


async def test_new_owner_revision_after_snapshot_is_not_refreshed(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    conversation, run_id = await orphan(harness, monkeypatch)
    service = harness.container.conversations
    store = harness.container.conversation_store
    resources = harness.container.workflow.resources
    workspace, lease = resources.create_workspace(
        harness.container.state.get_run(run_id), WorkspaceKind.CANDIDATE
    )
    code = cast(str, (await service.recover(conversation))["recovery_code"])
    recovery = service.session_recovery
    assert recovery is not None
    original = recovery._snapshot

    def snapshot(selection: SessionSelection) -> tuple[Run, RecoveryBinding, dict[str, JsonValue]]:
        result = original(selection)
        store.fence(run_id, expected_revision=result[1].snapshot().turn.revision, reason="recovery")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(recovery, "_snapshot", snapshot)
        with pytest.raises(FleetError):
            await service.recover(conversation, code=code, confirm_owner_stopped=True)
    assert await asyncio.to_thread(Path(workspace.path).is_dir)
    assert harness.container.state.get_lease(lease.lease_id) == lease
    assert (
        sum(
            event.event_type == "conversation.turn_fenced"
            for event in harness.container.state.list_events(run_id)
        )
        == 1
    )
    await _fresh_cleanup(harness, conversation)


async def test_two_independent_confirmations_have_only_one_cleanup_owner(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    conversation, run_id = await orphan(harness, monkeypatch)
    resources = harness.container.workflow.resources
    workspace, _ = resources.create_workspace(
        harness.container.state.get_run(run_id), WorkspaceKind.CANDIDATE
    )
    first = harness.container.conversations
    second = build_container(harness.state_root).conversations
    second.select(harness.repository_root, conversation_id=conversation)
    first_code = cast(str, (await first.recover(conversation))["recovery_code"])
    second_code = cast(str, (await second.recover(conversation))["recovery_code"])
    results = await asyncio.gather(
        first.recover(conversation, code=first_code, confirm_owner_stopped=True),
        second.recover(conversation, code=second_code, confirm_owner_stopped=True),
        return_exceptions=True,
    )
    assert sum(isinstance(result, FleetError) for result in results) == 1
    assert sum(isinstance(result, dict) for result in results) == 1
    assert not await asyncio.to_thread(Path(workspace.path).exists)
    events = harness.container.state.list_events(run_id)
    assert sum(event.event_type == "conversation.recovery_prepared" for event in events) == 1
    assert sum(event.event_type == "conversation.recovery_lease_claimed" for event in events) == 1
    assert sum(event.event_type == "conversation.recovery_lease_finished" for event in events) == 1


async def test_conflicting_retained_joiners_cannot_change_the_reviewed_cleanup(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    conversation, run_id = await orphan(harness, monkeypatch)
    service = harness.container.conversations
    resources = harness.container.workflow.resources
    workspace, original_lease = resources.create_workspace(
        harness.container.state.get_run(run_id), WorkspaceKind.CANDIDATE
    )
    code = cast(str, (await service.recover(conversation))["recovery_code"])
    entered, release = asyncio.Event(), asyncio.Event()
    held: list[RecoveryLeaseClaim] = []
    original = resources._cleanup_lease_once

    async def cleanup(
        run: Run,
        lease: ResourceLease,
        *,
        status: LeaseStatus,
        recovery_claim: RecoveryLeaseClaim | None = None,
        recovery_store: ConversationStore | None = None,
    ) -> None:
        assert recovery_claim is not None
        held.append(recovery_claim)
        entered.set()
        await release.wait()
        await original(
            run, lease, status=status, recovery_claim=recovery_claim, recovery_store=recovery_store
        )

    with monkeypatch.context() as patch:
        patch.setattr(resources, "_cleanup_lease_once", cleanup)
        owner = asyncio.create_task(
            service.recover(conversation, code=code, confirm_owner_stopped=True)
        )
        await asyncio.wait_for(entered.wait(), 5)
        try:
            plan = held[0].plan
            run = plan.binding.snapshot().runs[0]
            different = plan.model_copy(update={"plan_id": "corr_" + "f" * 32})
            before = harness.container.state.list_events(run_id)
            with pytest.raises(FleetError):
                await resources.cleanup_run(
                    run,
                    recovered=True,
                    review_plan=different,
                    recovery_store=harness.container.conversation_store,
                )
            with pytest.raises(FleetError):
                await resources.cleanup_run(run, recovered=True)
            with pytest.raises(FleetError):
                resources._lease_cleanup_task(
                    run,
                    original_lease,
                    status=LeaseStatus.RECOVERED,
                    review_plan=different,
                    recovery_store=harness.container.conversation_store,
                )
            with pytest.raises(FleetError):
                resources._lease_cleanup_task(
                    run,
                    original_lease.model_copy(update={"path": "changed"}),
                    status=LeaseStatus.RECOVERED,
                    review_plan=plan,
                    recovery_store=harness.container.conversation_store,
                )
            with pytest.raises(FleetError):
                await harness.container.recovery.recover_run(run_id)
            assert harness.container.state.list_events(run_id) == before
            for _ in range(3):
                owner.cancel()
                await asyncio.sleep(0)
            assert not owner.done() and service.session_recovery is not None
            assert service.session_recovery.active(conversation)
            assert await asyncio.to_thread(Path(workspace.path).exists)
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await owner
    assert not await asyncio.to_thread(Path(workspace.path).exists)
    assert not harness.container.state.outstanding_leases(run_id)
    assert not service.status(conversation)["recovery_required"]


@pytest.mark.parametrize("boundary", ["before-fence", "after-fence", "before-reconcile"])
@pytest.mark.parametrize("identity", ["graph-node", "unlisted-run"])
async def test_late_child_identity_is_never_swept_or_silently_settled(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch, boundary: str, identity: str
) -> None:
    container = harness.container
    container.permissions.configure(
        harness.repository_root, mode=TrustMode.SAFE, allowed_paths=(".",)
    )
    service = container.conversations
    conversation = cast(str, service.select(harness.repository_root)["conversation_id"])
    submitted = await service.submit(
        conversation,
        message="Paused parallel cleanup fixture",
        submission_id="graph-recovery",
        options=ChatExecutionOptions(fake_scenario=FakeScenario.PARALLEL_ENGINEERS),
    )
    run_id = cast(str, submitted["run_id"])
    unrelated = await harness.start(FakeScenario.SUCCESS)
    assert unrelated.task_id is not None
    unrelated_leases = tuple(container.state.outstanding_leases(unrelated.run_id))
    graph = container.graphs.get(run_id)
    assert graph is not None and len(graph.nodes) == 2
    turn_binding = container.conversation_store.binding_for_run(run_id)
    assert turn_binding is not None
    turn = container.conversation_store.get_turn(turn_binding.project_id, turn_binding.turn_id)
    container.conversation_store.claim_resume(run_id, expected_revision=turn.revision)
    container.graphs.claim_driver(run_id, expected_revision=graph.revision)
    code = cast(str, (await service.recover(conversation))["recovery_code"])
    store = container.conversation_store
    original_prepare = store.prepare_reviewed_recovery
    original_reconcile = store.reconcile_reviewed_recovery

    def add() -> None:
        with sqlite3.connect(store.database_path) as connection:
            if identity == "graph-node":
                connection.execute(
                    "INSERT INTO fleet_graph_nodes "
                    "(parent_run_id,node_id,iteration,child_run_id,child_task_id,revision,status,"
                    "binding_json,data_json) SELECT parent_run_id,?,iteration,?,?,revision,status,"
                    "binding_json,data_json FROM fleet_graph_nodes "
                    "WHERE parent_run_id=? AND node_id=? AND iteration=0",
                    (
                        "late-child",
                        unrelated.run_id,
                        unrelated.task_id,
                        run_id,
                        graph.nodes[0].binding.node_id,
                    ),
                )
            else:
                late = unrelated.model_copy(
                    update={
                        "parent_run_id": run_id,
                        "parent_plan_sha256": graph.plan_sha256,
                        "parent_node_id": "late-child",
                        "parent_iteration": 0,
                    }
                )
                connection.execute(
                    "UPDATE runs SET data_json=? WHERE run_id=?",
                    (late.model_dump_json(), unrelated.run_id),
                )

    def prepare(binding: RecoveryBinding) -> ReviewedRecoveryPlan:
        if boundary == "before-fence":
            add()
        plan = original_prepare(binding)
        if boundary == "after-fence":
            add()
        return plan

    def reconcile(plan: ReviewedRecoveryPlan) -> Run:
        add()
        return original_reconcile(plan)

    with monkeypatch.context() as patch:
        if boundary == "before-reconcile":
            patch.setattr(store, "reconcile_reviewed_recovery", reconcile)
        else:
            patch.setattr(store, "prepare_reviewed_recovery", prepare)
        with pytest.raises(FleetError):
            await service.recover(conversation, code=code, confirm_owner_stopped=True)
    assert tuple(container.state.outstanding_leases(unrelated.run_id)) == unrelated_leases
    for lease in unrelated_leases:
        if lease.path:
            assert await asyncio.to_thread(Path(lease.path).is_dir)
    with sqlite3.connect(store.database_path) as connection:
        if identity == "graph-node":
            connection.execute(
                "DELETE FROM fleet_graph_nodes WHERE parent_run_id=? AND node_id=? "
                "AND child_run_id=?",
                (run_id, "late-child", unrelated.run_id),
            )
        else:
            connection.execute(
                "UPDATE runs SET data_json=? WHERE run_id=?",
                (unrelated.model_dump_json(), unrelated.run_id),
            )
    assert service.status(conversation)["recovery_required"]
    if boundary != "before-reconcile":
        for node in graph.nodes:
            assert container.state.outstanding_leases(node.binding.child_run_id)
    await _fresh_cleanup(harness, conversation)
    for node in graph.nodes:
        assert not container.state.outstanding_leases(node.binding.child_run_id)
    assert tuple(container.state.outstanding_leases(unrelated.run_id)) == unrelated_leases
    await container.cancellation.cancel(unrelated.run_id)


async def test_claim_receipt_prevents_replaying_a_lease_cleanup(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    conversation, run_id = await orphan(harness, monkeypatch)
    resources = harness.container.workflow.resources
    workspace, lease = resources.create_workspace(
        harness.container.state.get_run(run_id), WorkspaceKind.CANDIDATE
    )
    service = harness.container.conversations
    code = cast(str, (await service.recover(conversation))["recovery_code"])
    recovery = service.session_recovery
    assert recovery is not None
    binding = recovery._tickets[code].binding
    # Returned decoded objects cannot mutate the retained review.
    decoded = binding.snapshot()
    decoded.leases[0].metadata["untrusted_mutation"] = True
    assert "untrusted_mutation" not in binding.snapshot().leases[0].metadata
    store = harness.container.conversation_store
    plan = store.prepare_reviewed_recovery(binding)
    claim = store.claim_recovery_lease(plan, lease.lease_id)
    with pytest.raises(FleetError):
        store.claim_recovery_lease(plan, lease.lease_id)
    store.finish_recovery_lease(claim, LeaseStatus.FAILED)
    before = harness.container.state.list_events(run_id)
    with pytest.raises(FleetError):
        store.finish_recovery_lease(claim, LeaseStatus.RECOVERED)
    with pytest.raises(FleetError):
        store.reconcile_reviewed_recovery(plan)
    assert harness.container.state.list_events(run_id) == before
    assert await asyncio.to_thread(Path(workspace.path).is_dir)
    await _fresh_cleanup(harness, conversation)


@pytest.mark.parametrize("missing", ["plan", "claim", "outcome"])
async def test_missing_cleanup_receipt_cannot_reopen_the_same_plan(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    conversation, run_id = await orphan(harness, monkeypatch)
    resources = harness.container.workflow.resources
    workspace, lease = resources.create_workspace(
        harness.container.state.get_run(run_id), WorkspaceKind.CANDIDATE
    )
    harness.container.state.update_lease_status(lease.lease_id, LeaseStatus.RELEASING.value)
    releasing = harness.container.state.get_lease(lease.lease_id)
    service = harness.container.conversations
    code = cast(str, (await service.recover(conversation))["recovery_code"])
    recovery = service.session_recovery
    assert recovery is not None
    store = harness.container.conversation_store
    plan = store.prepare_reviewed_recovery(recovery._tickets[code].binding)
    with monkeypatch.context() as patch:
        patch.setattr(store.clock, "now", lambda: releasing.updated_at)
        claim = store.claim_recovery_lease(plan, lease.lease_id)
    assert claim.lease().updated_at > releasing.updated_at
    if missing == "outcome":
        store.finish_recovery_lease(claim, LeaseStatus.FAILED)
    event_type = {
        "plan": "conversation.recovery_prepared",
        "claim": "conversation.recovery_lease_claimed",
        "outcome": "conversation.recovery_lease_finished",
    }[missing]
    with sqlite3.connect(store.database_path) as connection:
        connection.execute(
            "DELETE FROM run_events WHERE run_id=? AND event_type=?", (run_id, event_type)
        )
    before = harness.container.state.get_lease(lease.lease_id)
    with pytest.raises(FleetError):
        store.claim_recovery_lease(plan, lease.lease_id)
    with pytest.raises(FleetError):
        store.reconcile_reviewed_recovery(plan)
    assert harness.container.state.get_lease(lease.lease_id) == before
    assert await asyncio.to_thread(Path(workspace.path).exists)
    await _fresh_cleanup(harness, conversation)
