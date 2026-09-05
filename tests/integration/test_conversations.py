from __future__ import annotations

from typing import cast

import pytest
from conftest import FleetHarness

from agent_fleet.application.conversations import ChatExecutionOptions
from agent_fleet.bootstrap import build_container
from agent_fleet.domain.conversation import ConversationTurnStatus
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import ApprovalChoice, FakeScenario, RunStatus

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _selected(harness: FleetHarness) -> str:
    view = harness.container.conversations.select(harness.repository_root)
    return cast(str, view["conversation_id"])


async def test_two_direct_turns_reopen_and_old_submission_is_not_replayed(
    harness: FleetHarness,
) -> None:
    service = harness.container.conversations
    conversation_id = _selected(harness)
    options = ChatExecutionOptions(fake_scenario=FakeScenario.DIRECT)
    before = harness.git("status", "--porcelain")
    first = await service.submit(
        conversation_id, message="Explain the canary", submission_id="first", options=options
    )
    first_run_id = cast(str, first["run_id"])
    first_run = harness.container.state.get_run(first_run_id)
    assert first_run.status is RunStatus.COMPLETED
    assert first["turn_status"] == "delivered"
    assert first["result_summary"] and not first["recovery_required"]
    first_budget = harness.container.budgets.snapshot(first_run_id)
    second = await service.submit(
        conversation_id, message="Explain the proof limits", submission_id="second", options=options
    )
    second_run_id = cast(str, second["run_id"])
    binding = harness.container.conversation_store.binding_for_run(second_run_id)
    assert binding is not None
    turn = harness.container.conversation_store.get_turn(binding.project_id, binding.turn_id)
    assert len(turn.context.entries) == 1
    assert turn.context.entries[0].run_id == first_run_id
    assert turn.context.entries[0].artifact_refs
    rebuilt = build_container(harness.state_root)
    selected = rebuilt.conversations.select(harness.repository_root)
    assert selected["conversation_id"] == conversation_id and selected["run_id"] == second_run_id
    duplicate = await rebuilt.conversations.submit(
        conversation_id, message="Explain the canary", submission_id="first", options=options
    )
    assert duplicate["run_id"] == first_run_id
    assert rebuilt.budgets.snapshot(first_run_id) == first_budget
    turns = rebuilt.conversation_store.list_turns(binding.project_id, conversation_id)
    assert len(turns) == 2
    assert harness.git("status", "--porcelain") == before


async def test_exact_approval_resume_via_public_workflow_settles_same_chat(
    harness: FleetHarness,
) -> None:
    conversation_id = _selected(harness)
    view = await harness.container.conversations.submit(
        conversation_id,
        message="Fix the canary behavior",
        submission_id="approval-turn",
        options=ChatExecutionOptions(fake_scenario=FakeScenario.APPROVAL),
    )
    run_id = cast(str, view["run_id"])
    paused = harness.container.state.get_run(run_id)
    assert paused.status is RunStatus.PAUSED_FOR_APPROVAL and paused.pending_approval_id is not None
    assert view["turn_status"] == "waiting"
    binding = harness.container.conversation_store.binding_for_run(run_id)
    assert binding is not None
    initial = harness.container.conversation_store.get_turn(binding.project_id, binding.turn_id)
    assert initial.active_claim_id is None
    rebuilt = build_container(harness.state_root)
    rebuilt.conversations.select(harness.repository_root, conversation_id=conversation_id)
    rebuilt.conversations.approve(
        conversation_id, paused.pending_approval_id, choice=ApprovalChoice.ALLOW_ONCE
    )
    result = await rebuilt.workflow.resume(run_id)
    assert result.status is RunStatus.READY_FOR_REVIEW and not result.verified_complete
    settled = rebuilt.conversation_store.get_turn(binding.project_id, binding.turn_id)
    assert settled.status is ConversationTurnStatus.DELIVERED
    assert settled.owner_generation == initial.owner_generation + 1
    assert settled.active_claim_id is None and settled.binding == initial.binding
    assert not rebuilt.state.outstanding_leases(run_id)
    assert rebuilt.conversations.status(conversation_id)["run_id"] == run_id


async def test_waiting_turn_blocks_new_goal_but_can_be_cancelled(harness: FleetHarness) -> None:
    conversation_id = _selected(harness)
    view = await harness.container.conversations.submit(
        conversation_id,
        message="Fix the canary behavior",
        submission_id="waiting",
        options=ChatExecutionOptions(fake_scenario=FakeScenario.APPROVAL),
    )
    with pytest.raises(FleetError) as error:
        await harness.container.conversations.submit(
            conversation_id,
            message="Another task",
            submission_id="not-queued",
            options=ChatExecutionOptions(),
        )
    assert error.value.code is ErrorCode.RECOVERY_REQUIRED
    run_id = cast(str, view["run_id"])
    cancelled = await harness.container.conversations.cancel(conversation_id)
    assert cancelled["turn_status"] == "cancelled"
    assert cancelled["active_turn_id"] is None
    assert harness.container.state.get_run(run_id).status is RunStatus.CANCELLED
    assert not harness.container.state.outstanding_leases(run_id)


async def test_progress_is_bounded_and_cursor_bound_to_selected_conversation(
    harness: FleetHarness,
) -> None:
    service = harness.container.conversations
    conversation_id = _selected(harness)
    await service.submit(
        conversation_id,
        message="Explain the canary",
        submission_id="progress",
        options=ChatExecutionOptions(fake_scenario=FakeScenario.DIRECT),
    )
    first = service.progress(conversation_id, limit=2)
    assert isinstance(first["events"], list) and len(first["events"]) == 2
    second = service.progress(conversation_id, cursor=cast(str, first["cursor"]), limit=2)
    assert first["events"] != second["events"]
    foreign = service.select(harness.repository_root, create_new=True)
    with pytest.raises(FleetError):
        service.progress(cast(str, foreign["conversation_id"]), cursor=cast(str, first["cursor"]))
    for size in (0, 101, True):
        with pytest.raises(FleetError):
            service.progress(conversation_id, limit=size)


@pytest.mark.parametrize("scenario", [FakeScenario.PARALLEL_ENGINEERS, FakeScenario.SPECIALIST])
async def test_adaptive_chat_keeps_one_root_turn_and_no_child_conversations(
    harness: FleetHarness, scenario: FakeScenario
) -> None:
    conversation_id = _selected(harness)
    before = harness.git("status", "--porcelain")
    view = await harness.container.conversations.submit(
        conversation_id,
        message="Fix the canary behavior",
        submission_id="adaptive",
        options=ChatExecutionOptions(fake_scenario=scenario),
    )
    run_id = cast(str, view["run_id"])
    assert view["turn_status"] == "delivered" and view["active_turn_id"] is None
    run = harness.container.state.get_run(run_id)
    assert run.status is RunStatus.READY_FOR_REVIEW and not run.verified_complete
    graph = harness.container.graphs.get(run_id)
    assert graph is not None
    for node in graph.nodes:
        child_id = node.binding.child_run_id
        assert harness.container.conversation_store.binding_for_run(child_id) is None
        assert not harness.container.state.outstanding_leases(child_id)
    assert not harness.container.state.outstanding_leases(run_id)
    assert harness.git("status", "--porcelain") == before
