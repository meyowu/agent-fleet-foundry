"""One real offline Session process manages models and history without Run IDs."""

from __future__ import annotations

import re

import pytest
from test_persistent_chat_cli import ChatFixture, InteractiveChat
from test_persistent_chat_cli import chat_fixture as chat_fixture

from agent_fleet.domain.models import RuntimeConfiguration

pytestmark = pytest.mark.e2e


def test_same_real_session_inspects_history_and_confirms_future_model_selection(
    chat_fixture: ChatFixture,
) -> None:
    first = chat_fixture.message("First task", "--submission-id", "management-first")
    second = chat_fixture.message("Second task", "--submission-id", "management-second")
    assert first["conversation_id"] == second["conversation_id"]
    container = chat_fixture.reopen()
    original = container.state.get_run(first["run_id"])
    original_bindings = container.model_profiles.store.get_bindings(
        original.project_id, original.run_id
    )
    container.model_profiles.set("small", configuration=RuntimeConfiguration())
    chat = InteractiveChat(chat_fixture)
    try:
        chat.read_until("Type a goal")
        for command, expected in (
            ("/roles", '"requested_tool_ceiling":'),
            ("/readiness", '"baseline_status": "not_checked"'),
            ("/models", '"future_task_selection":'),
            ("/tasks", '"sequence": 1'),
            ("/tasks select 1", f"Inspection: selected  inspected={first['run_id']}"),
            ("/status", f"Run: {first['run_id']}"),
            ("/artifacts", f'"run_id": "{first["run_id"]}"'),
            ("/plan", '"mode": "inspection_only"'),
            ("/apply", "/tasks current"),
            ("/tasks current", f"Inspection: current  inspected={second['run_id']}"),
        ):
            checkpoint = len(chat.output)
            chat.send(command)
            chat.read_until(expected, after=checkpoint)
        checkpoint = len(chat.output)
        chat.send("/models use small --default")
        chat.read_until('"expires_at":', after=checkpoint)
        matched = re.search(r'"confirmation_code": "([0-9a-f]{16})"', chat.output[checkpoint:])
        assert matched is not None
        project = container.state.get_project(original.project_id)
        assert chat_fixture.reopen().model_profiles.selection(project)["revision"] == 0
        checkpoint = len(chat.output)
        chat.send(f"/confirm {matched.group(1)}")
        chat.read_until("Model selection saved for future tasks only", after=checkpoint)
        assert chat_fixture.reopen().model_profiles.selection(project)["default_profile"] == "small"
        checkpoint = len(chat.output)
        chat.send("Third task uses the reviewed model")
        chat.read_until("ready_for_review / presenting", after=checkpoint)
        checkpoint = len(chat.output)
        chat.send("/tasks")
        chat.read_until('"sequence": 3', after=checkpoint)
        chat.send("/exit")
        chat.finish()
        reopened = chat_fixture.reopen()
        turns = reopened.conversations.store.list_turns(
            project.project_id, first["conversation_id"]
        )
        assert len(turns) == 3
        bound = reopened.model_profiles.store.get_bindings(
            project.project_id, turns[0].binding.run_id
        )
        assert bound is not None
        assert {item.profile_name for item in bound.roles.values()} == {"small"}
        assert reopened.state.get_run(original.run_id) == original
        assert (
            reopened.model_profiles.store.get_bindings(project.project_id, original.run_id)
            == original_bindings
        )
        assert "credential_ref" not in chat.output and '"instructions"' not in chat.output
        chat_fixture.unchanged()
    finally:
        chat.close()
