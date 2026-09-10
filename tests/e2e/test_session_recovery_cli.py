"""An actual stopped CLI owner can be cleaned in the same observing Session."""

from __future__ import annotations

import re

import pytest
from test_persistent_chat_cli import ChatFixture, InteractiveChat
from test_persistent_chat_cli import chat_fixture as chat_fixture

from agent_fleet.domain.models import RunStatus

pytestmark = pytest.mark.e2e


def test_stopped_owner_recovery_and_next_task_stay_in_one_session(
    chat_fixture: ChatFixture,
) -> None:
    owner = InteractiveChat(chat_fixture, held_role="cos")
    try:
        owner.read_until("Type a goal")
        owner.send("Fix the canary")
        owner.read_until("scoping")
        before = chat_fixture.reopen().conversations.select(chat_fixture.repository)
        run_id, conversation = str(before["run_id"]), str(before["conversation_id"])
    finally:
        owner.close()
    observer = InteractiveChat(chat_fixture, conversation=conversation)
    try:
        observer.read_until("Type a goal")
        checkpoint = len(observer.output)
        observer.send("/recover")
        observer.read_until('"recovery_code":', after=checkpoint)
        observer.read_until('"expires_at":', after=checkpoint)
        match = re.search(r'"recovery_code": "([0-9a-f]{16})"', observer.output[checkpoint:])
        assert match is not None
        assert chat_fixture.reopen().state.get_run(run_id).status is RunStatus.RUNNING
        checkpoint = len(observer.output)
        observer.send("/recover --confirm-owner-stopped")
        observer.read_until("CONFIG_INVALID", after=checkpoint)
        assert chat_fixture.reopen().state.get_run(run_id).status is RunStatus.RUNNING
        checkpoint = len(observer.output)
        observer.send(f"/recover --confirm-owner-stopped {match.group(1)}")
        observer.read_until('"replayed": false', after=checkpoint)
        observer.read_until('"status": "failed"', after=checkpoint)
        reopened = chat_fixture.reopen()
        assert not reopened.state.outstanding_leases(run_id)
        assert (
            sum(
                event.event_type == "agent.started" and event.payload.get("role") == "cos"
                for event in reopened.state.list_events(run_id)
            )
            == 1
        )
        checkpoint = len(observer.output)
        observer.send("Fix the canary with a new bounded task")
        observer.read_until("ready_for_review / presenting", after=checkpoint)
        checkpoint = len(observer.output)
        observer.send("/tasks")
        observer.read_until('"sequence": 2', after=checkpoint)
        observer.send("/exit")
        observer.finish()
        assert (
            chat_fixture.reopen().conversations.select(chat_fixture.repository)["conversation_id"]
            == conversation
        )
        chat_fixture.unchanged()
    finally:
        observer.close()


def test_no_id_deny_stays_in_session_and_does_not_execute_pending_tool(
    chat_fixture: ChatFixture,
) -> None:
    first = chat_fixture.message("Fix the canary", "--fake-scenario", "approval")
    run_id = first["run_id"]
    chat = InteractiveChat(chat_fixture, conversation=first["conversation_id"])
    try:
        chat.read_until("Type a goal")
        checkpoint = len(chat.output)
        chat.send("/deny --reason 'Do not run this operation'")
        chat.read_until('"denied": true', after=checkpoint)
        state = chat_fixture.reopen().state
        assert state.get_approval(first["run"]["pending_approval_id"]).status.value == "denied"
        assert state.count_executed_intents(run_id, "fixture.record_side_effect") == 0
        checkpoint = len(chat.output)
        chat.send("/cancel")
        chat.read_until("cancelled", after=checkpoint)
        chat.send("/exit")
        chat.finish()
        assert not chat_fixture.reopen().state.outstanding_leases(run_id)
        chat_fixture.unchanged()
    finally:
        chat.close()
