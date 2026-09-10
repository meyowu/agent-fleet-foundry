"""Reviewed current-Session cleanup is not permission to replay an interrupted owner."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path
from typing import cast

import pytest
from conftest import FleetHarness

from agent_fleet.application.conversations import ChatExecutionOptions
from agent_fleet.bootstrap import build_container
from agent_fleet.domain.budgets import RunBudgetLimits
from agent_fleet.domain.errors import FleetError
from agent_fleet.domain.models import FakeScenario, Run, RunStatus, WorkspaceKind
from agent_fleet.domain.recovery_binding import ReviewedRecoveryPlan
from agent_fleet.domain.trust import TrustMode
from agent_fleet.ports.conversation import ConversationStore

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


class StoppedOwner(BaseException):
    pass


async def orphan(harness: FleetHarness, monkeypatch: pytest.MonkeyPatch) -> tuple[str, str]:
    service = harness.container.conversations
    conversation = cast(str, service.select(harness.repository_root)["conversation_id"])

    def stopped(run_id: str, limits: RunBudgetLimits) -> None:
        raise StoppedOwner()

    with monkeypatch.context() as patcher:
        patcher.setattr(harness.container.budgets, "initialize_run", stopped)
        with pytest.raises(StoppedOwner):
            await service.submit(
                conversation,
                message="Explain the stopped owner fixture",
                submission_id="stopped-owner",
                options=ChatExecutionOptions(fake_scenario=FakeScenario.DIRECT),
            )
    view = service.status(conversation)
    assert view["recovery_required"] is True
    return conversation, cast(str, view["run_id"])


async def test_review_is_observational_then_recovers_without_replay_and_allows_new_task(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    conversation, run_id = await orphan(harness, monkeypatch)
    service = harness.container.conversations
    before = harness.container.state.get_run(run_id)
    events = harness.container.state.list_events(run_id)
    preview = await service.recover(conversation)
    assert preview["execution_authorized"] is False
    assert harness.container.state.get_run(run_id) == before
    assert harness.container.state.list_events(run_id) == events
    code = cast(str, preview["recovery_code"])
    result = await service.recover(conversation, code=code, confirm_owner_stopped=True)
    assert result["replayed"] is False and result["recovered_run_id"] == run_id
    assert result["status"] == "failed" and result["outstanding_lease_ids"] == []
    assert not service.status(conversation)["recovery_required"]
    assert not any(
        event.event_type == "agent.started" for event in harness.container.state.list_events(run_id)
    )
    with pytest.raises(FleetError):
        await service.recover(conversation, code=code, confirm_owner_stopped=True)
    # A durable historical fence is not current cleanup work or a new capability.
    with pytest.raises(FleetError):
        await service.recover(conversation)
    next_task = await service.submit(
        conversation,
        message="A new task after explicit recovery",
        submission_id="after-recovery",
        options=ChatExecutionOptions(fake_scenario=FakeScenario.DIRECT),
    )
    assert next_task["conversation_id"] == conversation and next_task["run_id"] != run_id
    next_run = next_task["run"]
    assert isinstance(next_run, dict) and next_run["status"] == "completed"


@pytest.mark.parametrize("change", ["confirmation", "wrong-code", "expired", "aba", "run"])
async def test_stale_or_unconfirmed_recovery_does_not_mutate(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    conversation, run_id = await orphan(harness, monkeypatch)
    service = harness.container.conversations
    preview = await service.recover(conversation)
    code = cast(str, preview["recovery_code"])
    if change == "expired":
        recovery = service.session_recovery
        assert recovery is not None
        future = recovery.clock.now() + timedelta(minutes=6)
        monkeypatch.setattr(recovery.clock, "now", lambda: future)
    elif change == "aba":
        service.tasks(conversation)
        service.tasks(conversation, select_sequence=1)
        service.tasks(conversation, current=True)
    elif change == "run":
        run = harness.container.state.get_run(run_id)
        harness.container.state.save_run(
            run.model_copy(update={"updated_at": run.updated_at + timedelta(seconds=1)}),
            "run.test_observation",
            {},
        )
    before = harness.container.state.get_run(run_id)
    events = harness.container.state.list_events(run_id)
    with pytest.raises(FleetError):
        await service.recover(
            conversation,
            code="0" * 16 if change == "wrong-code" else code,
            confirm_owner_stopped=change != "confirmation",
        )
    assert harness.container.state.get_run(run_id) == before
    assert harness.container.state.list_events(run_id) == events


async def test_recovery_drains_repeated_cancellation_and_blocks_other_mutation(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    conversation, run_id = await orphan(harness, monkeypatch)
    service = harness.container.conversations
    resources = harness.container.workflow.resources
    workspace, _ = resources.create_workspace(
        harness.container.state.get_run(run_id), WorkspaceKind.CANDIDATE
    )
    physical_path = Path(workspace.path)
    assert await asyncio.to_thread(physical_path.is_dir)
    code = cast(str, (await service.recover(conversation))["recovery_code"])
    entered, release = asyncio.Event(), asyncio.Event()
    original = resources.cleanup_run

    async def delayed(
        run: Run,
        *,
        recovered: bool = False,
        review_plan: ReviewedRecoveryPlan | None = None,
        recovery_store: ConversationStore | None = None,
    ) -> None:
        assert run.run_id == run_id and recovered
        entered.set()
        await release.wait()
        await original(
            run, recovered=recovered, review_plan=review_plan, recovery_store=recovery_store
        )

    monkeypatch.setattr(resources, "cleanup_run", delayed)
    task = asyncio.create_task(service.recover(conversation, code=code, confirm_owner_stopped=True))
    await asyncio.wait_for(entered.wait(), 5)
    try:
        for _ in range(3):
            task.cancel()
            await asyncio.sleep(0)
        assert not task.done()
        assert await asyncio.to_thread(physical_path.is_dir)
        assert harness.container.state.outstanding_leases(run_id)
        with pytest.raises(FleetError):
            await service.cancel(conversation)
        with pytest.raises(FleetError):
            await service.submit(
                conversation,
                message="No concurrent task",
                submission_id=None,
                options=ChatExecutionOptions(),
            )
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert harness.container.state.get_run(run_id).status is RunStatus.FAILED
    assert service.session_recovery is not None and not service.session_recovery.active(
        conversation
    )
    assert not service.status(conversation)["recovery_required"]
    assert not await asyncio.to_thread(physical_path.exists)
    assert not harness.container.state.outstanding_leases(run_id)
    assert str(physical_path) not in harness.git("worktree", "list", "--porcelain")


async def test_changed_lease_invalidates_recovery_and_requires_a_fresh_review(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    conversation, run_id = await orphan(harness, monkeypatch)
    service = harness.container.conversations
    resources = harness.container.workflow.resources
    workspace, lease = resources.create_workspace(
        harness.container.state.get_run(run_id), WorkspaceKind.CANDIDATE
    )
    code = cast(str, (await service.recover(conversation))["recovery_code"])
    harness.container.state.update_lease_status(lease.lease_id, "failed")
    events = harness.container.state.list_events(run_id)
    with pytest.raises(FleetError):
        await service.recover(conversation, code=code, confirm_owner_stopped=True)
    assert await asyncio.to_thread(Path(workspace.path).is_dir)
    assert harness.container.state.list_events(run_id) == events
    new_code = cast(str, (await service.recover(conversation))["recovery_code"])
    result = await service.recover(conversation, code=new_code, confirm_owner_stopped=True)
    assert result["outstanding_lease_ids"] == [] and result["replayed"] is False
    assert not await asyncio.to_thread(Path(workspace.path).exists)


async def test_no_id_deny_selects_only_sole_current_request(harness: FleetHarness) -> None:
    service = harness.container.conversations
    conversation = cast(str, service.select(harness.repository_root)["conversation_id"])
    assert service.deny(conversation)["pending_requests"] == []
    view = await service.submit(
        conversation,
        message="Use one exact approval",
        submission_id="deny-sole",
        options=ChatExecutionOptions(fake_scenario=FakeScenario.APPROVAL),
    )
    run_id = cast(str, view["run_id"])
    request = harness.container.state.get_run(run_id).pending_approval_id
    assert request is not None
    denied = service.deny(conversation, reason="Do not execute this operation")
    assert denied == {"request_id": request, "denied": True}
    assert harness.container.state.get_approval(request).status.value == "denied"
    assert harness.container.state.count_executed_intents(run_id, "fixture.record_side_effect") == 0
    await service.cancel(conversation)


@pytest.mark.parametrize("change", ["replaced", "restart", "other-conversation"])
async def test_recovery_ticket_never_crosses_selection_or_process(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    conversation, run_id = await orphan(harness, monkeypatch)
    service = harness.container.conversations
    code = cast(str, (await service.recover(conversation))["recovery_code"])
    selected = conversation
    if change == "replaced":
        await service.recover(conversation)
    elif change == "restart":
        service = build_container(harness.state_root).conversations
        service.select(harness.repository_root, conversation_id=conversation)
    else:
        selected = cast(
            str, service.select(harness.repository_root, create_new=True)["conversation_id"]
        )
    before = harness.container.state.get_run(run_id)
    events = harness.container.state.list_events(run_id)
    with pytest.raises(FleetError):
        await service.recover(selected, code=code, confirm_owner_stopped=True)
    assert harness.container.state.get_run(run_id) == before
    assert harness.container.state.list_events(run_id) == events


async def test_historical_selection_cannot_recover_and_invalidates_current_review(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = harness.container.conversations
    conversation = cast(str, service.select(harness.repository_root)["conversation_id"])
    await service.submit(
        conversation,
        message="A completed first task",
        submission_id="completed-first",
        options=ChatExecutionOptions(fake_scenario=FakeScenario.DIRECT),
    )
    orphan_conversation, run_id = await orphan(harness, monkeypatch)
    assert conversation == orphan_conversation
    code = cast(str, (await service.recover(conversation))["recovery_code"])
    service.tasks(conversation)
    service.tasks(conversation, select_sequence=1)
    before = harness.container.state.get_run(run_id)
    events = harness.container.state.list_events(run_id)
    with pytest.raises(FleetError):
        await service.recover(conversation)
    with pytest.raises(FleetError):
        await service.recover(conversation, code=code, confirm_owner_stopped=True)
    service.tasks(conversation, current=True)
    with pytest.raises(FleetError):
        await service.recover(conversation, code=code, confirm_owner_stopped=True)
    assert harness.container.state.get_run(run_id) == before
    assert harness.container.state.list_events(run_id) == events


@pytest.mark.parametrize("owner", ["_executions", "_cancellations"])
async def test_local_owner_must_use_normal_cancel_not_stopped_owner_recovery(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch, owner: str
) -> None:
    conversation, run_id = await orphan(harness, monkeypatch)
    service = harness.container.conversations
    before = harness.container.state.get_run(run_id)
    events = harness.container.state.list_events(run_id)
    release = asyncio.Event()
    active = asyncio.create_task(release.wait())
    owners = getattr(service, owner)
    owners[conversation] = active
    try:
        with pytest.raises(FleetError):
            await service.recover(conversation)
    finally:
        owners.pop(conversation)
        release.set()
        await active
    assert harness.container.state.get_run(run_id) == before
    assert harness.container.state.list_events(run_id) == events


async def test_no_id_deny_lists_multiple_child_requests_without_selecting_one(
    harness: FleetHarness,
) -> None:
    container = harness.container
    container.permissions.configure(
        harness.repository_root, mode=TrustMode.SAFE, allowed_paths=(".",)
    )
    service = container.conversations
    conversation = cast(str, service.select(harness.repository_root)["conversation_id"])
    submitted = await service.submit(
        conversation,
        message="Two bounded parallel changes",
        submission_id="parallel-deny",
        options=ChatExecutionOptions(fake_scenario=FakeScenario.PARALLEL_ENGINEERS),
    )
    run_id = cast(str, submitted["run_id"])
    children = container.graphs.descendants(run_id)
    requests = [
        container.state.get_approval(
            cast(str, container.state.get_run(child.child_run_id).pending_approval_id)
        )
        for child in children
    ]
    assert len(requests) == 2 and all(request.status.value == "pending" for request in requests)
    view = service.deny(conversation)
    assert view["selection_required"] is True
    pending = view["pending_requests"]
    assert isinstance(pending, list) and len(pending) == 2
    assert [container.state.get_approval(request.request_id) for request in requests] == requests
    for child in children:
        assert container.state.count_executed_intents(child.child_run_id, "command.run") == 0
    await service.cancel(conversation)
    for identity in (run_id, *(child.child_run_id for child in children)):
        assert not container.state.outstanding_leases(identity)
