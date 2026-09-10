from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import cast

import pytest
from conftest import FleetHarness

from agent_fleet.adapters.persistence.conversations import SqliteConversationStore
from agent_fleet.application.conversations import ChatExecutionOptions
from agent_fleet.bootstrap import build_container
from agent_fleet.domain.errors import FleetError
from agent_fleet.domain.model_profiles import ProjectModelSelection
from agent_fleet.domain.models import FakeScenario, RuntimeConfiguration
from agent_fleet.domain.session_review import ModelSelectionReview

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _selected(harness: FleetHarness) -> str:
    return cast(
        str, harness.container.conversations.select(harness.repository_root)["conversation_id"]
    )


async def _submit(harness: FleetHarness, identifier: str, key: str) -> str:
    view = await harness.container.conversations.submit(
        identifier,
        message=f"Explain {key}",
        submission_id=key,
        options=ChatExecutionOptions(fake_scenario=FakeScenario.DIRECT),
    )
    return cast(str, view["run_id"])


async def test_same_session_model_review_changes_future_tasks_not_pinned_history(
    harness: FleetHarness,
) -> None:
    service = harness.container.conversations
    identifier = _selected(harness)
    first = await _submit(harness, identifier, "first")
    original_run = harness.container.state.get_run(first)
    original_bindings = harness.container.model_profiles.store.get_bindings(
        original_run.project_id, first
    )
    harness.container.model_profiles.set(
        "small", configuration=RuntimeConfiguration(max_requests=3)
    )
    project = harness.container.state.get_project(original_run.project_id)
    before = harness.container.model_profiles.selection(project)
    review = service.models(identifier, profile="small", default=True)
    assert harness.container.model_profiles.selection(project) == before
    assert review["confirmation_required"] is True
    code = cast(str, review["confirmation_code"])
    confirmed = service.review(identifier, action="confirm", arguments=(code,))
    selection = confirmed["future_task_selection"]
    assert isinstance(selection, dict) and selection["default_profile"] == "small"
    with pytest.raises(FleetError):
        service.review(identifier, action="confirm", arguments=(code,))
    assert harness.container.state.get_run(first) == original_run
    assert (
        harness.container.model_profiles.store.get_bindings(project.project_id, first)
        == original_bindings
    )
    second = await _submit(harness, identifier, "second")
    pinned = harness.container.model_profiles.store.get_bindings(project.project_id, second)
    assert pinned is not None
    assert {binding.profile_name for binding in pinned.roles.values()} == {"small"}
    rebuilt = build_container(harness.state_root)
    assert rebuilt.model_profiles.selection(project)["default_profile"] == "small"
    assert rebuilt.model_profiles.store.get_bindings(project.project_id, first) == original_bindings


async def test_models_can_be_reviewed_before_first_task(harness: FleetHarness) -> None:
    identifier = _selected(harness)
    harness.container.model_profiles.set("small", configuration=RuntimeConfiguration())
    service = harness.container.conversations
    review = service.models(identifier, profile="small", role="engineer")
    assert review["run_id"] is None
    result = service.review(
        identifier, action="confirm", arguments=(cast(str, review["confirmation_code"]),)
    )
    selection = result["future_task_selection"]
    assert isinstance(selection, dict) and selection["role_overrides"] == {"engineer": "small"}
    assert service.models(identifier)["inspected_run_binding"] is None


async def test_history_view_does_not_retarget_active_progress_or_cancellation(
    harness: FleetHarness,
) -> None:
    service = harness.container.conversations
    identifier = _selected(harness)
    first = await _submit(harness, identifier, "first")
    view = await service.submit(
        identifier,
        message="Fix canary",
        submission_id="waiting",
        options=ChatExecutionOptions(fake_scenario=FakeScenario.APPROVAL),
    )
    active = cast(str, view["run_id"])
    first_before = harness.container.state.get_run(first)
    page = service.tasks(identifier)
    assert len(page["tasks"]) == 2  # type: ignore[arg-type]
    selected = service.tasks(identifier, select_sequence=1)
    assert selected["run_id"] == first
    assert selected["active_run_id"] == active
    assert service.artifacts(identifier)["run_id"] == first
    progress = service.progress(identifier)
    assert str(progress["cursor"]).split(":")[1] == active
    for action, arguments in (("apply", ()), ("plan", ("approve",))):
        with pytest.raises(FleetError, match="/tasks current"):
            service.review(identifier, action=action, arguments=arguments)
    with pytest.raises(FleetError, match="/tasks current"):
        await service.resume(identifier)
    cancelled = await service.cancel(identifier)
    assert cancelled["cancelled_run_id"] == active
    assert cancelled["inspected_run_id"] == first
    assert harness.container.state.get_run(active).status.value == "cancelled"
    assert harness.container.state.get_run(first) == first_before
    assert service.tasks(identifier, current=True)["run_id"] == active


async def test_history_selection_invalidates_reviews_even_after_aba(harness: FleetHarness) -> None:
    service = harness.container.conversations
    identifier = _selected(harness)
    await _submit(harness, identifier, "first")
    await _submit(harness, identifier, "second")
    harness.container.model_profiles.set("small", configuration=RuntimeConfiguration())
    review = service.models(identifier, profile="small", default=True)
    service.tasks(identifier)
    service.tasks(identifier, select_sequence=1)
    service.tasks(identifier)
    service.tasks(identifier, select_sequence=2)
    service.tasks(identifier, current=True)
    with pytest.raises(FleetError):
        service.review(
            identifier, action="confirm", arguments=(cast(str, review["confirmation_code"]),)
        )


@pytest.mark.parametrize("change", ["profile", "disabled", "selection", "config", "dismiss"])
async def test_model_confirmation_rejects_changed_review_once(
    harness: FleetHarness, change: str
) -> None:
    service = harness.container.conversations
    identifier = _selected(harness)
    harness.container.model_profiles.set("small", configuration=RuntimeConfiguration())
    review = service.models(identifier, profile="small", default=True)
    code = cast(str, review["confirmation_code"])
    project = harness.container.model_profiles.project(harness.repository_root)
    if change in {"profile", "disabled"}:
        harness.container.model_profiles.set(
            "small",
            configuration=RuntimeConfiguration(max_requests=4),
            expected_revision=1,
            enabled=change != "disabled",
        )
    elif change == "selection":
        harness.container.model_profiles.bind(
            project, expected_revision=0, profile="small", default=True
        )
    elif change == "config":
        path = harness.repository_root / ".fleet/agents/engineer.md"
        path.write_text(path.read_text() + "\nChanged guidance\n")
    else:
        service.review(identifier, action="dismiss")
    before = harness.container.model_profiles.selection(project)
    with pytest.raises(FleetError):
        service.review(identifier, action="confirm", arguments=(code,))
    with pytest.raises(FleetError):
        service.review(identifier, action="confirm", arguments=(code,))
    assert harness.container.model_profiles.selection(project) == before


async def test_role_readiness_and_model_inspection_never_submit(harness: FleetHarness) -> None:
    service = harness.container.conversations
    identifier = _selected(harness)
    first = await _submit(harness, identifier, "first")
    before = harness.container.state.get_run(first)
    events = harness.container.state.list_events(first)
    roles = service.roles(identifier)
    encoded = json.dumps(roles)
    assert "requested_tool_ceiling" in encoded and "template_sha256" in encoded
    assert '"instructions"' not in encoded
    report = service.readiness(identifier)
    assert report["environment_status"] == "unverified"
    assert report["baseline_status"] == "not_checked" and report["commands_executed"] == 0
    models = service.models(identifier)
    assert "future_task_selection" in models and "inspected_run_binding" in models
    assert "credential_ref" not in json.dumps(models)
    assert harness.container.state.get_run(first) == before
    assert harness.container.state.list_events(first) == events
    assert len(service.store.list_turns(before.project_id, identifier)) == 1


@pytest.mark.parametrize("sequence", [0, -1, 1001, True, "run_fake"])
async def test_task_selection_rejects_bounds_and_internal_identifiers(
    harness: FleetHarness, sequence: object
) -> None:
    identifier = _selected(harness)
    await _submit(harness, identifier, "first")
    service = harness.container.conversations
    service.tasks(identifier)
    with pytest.raises(FleetError):
        service.tasks(identifier, select_sequence=sequence)  # type: ignore[arg-type]


async def test_unknown_model_role_does_not_issue_a_review(harness: FleetHarness) -> None:
    identifier = _selected(harness)
    harness.container.model_profiles.set("small", configuration=RuntimeConfiguration())
    with pytest.raises(FleetError):
        harness.container.conversations.models(identifier, profile="small", role="not_configured")


@pytest.mark.parametrize(
    "change", ["profile", "profile-aba", "config", "inspection-aba", "expiry", "conversation"]
)
async def test_model_review_checks_changes_after_application_reads_before_atomic_write(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    service = harness.container.conversations
    identifier = _selected(harness)
    profiles = harness.container.model_profiles
    profiles.set("small", configuration=RuntimeConfiguration())
    review = service.models(identifier, profile="small", default=True)
    code = cast(str, review["confirmation_code"])
    project = profiles.project(harness.repository_root)
    original = profiles.store.save_selection

    class ExpiredClock:
        def now(self) -> datetime:
            return datetime.fromisoformat(cast(str, review["expires_at"])) + timedelta(seconds=1)

    def new_turn() -> None:
        rebuilt = build_container(harness.state_root)
        rebuilt.conversations.select(harness.repository_root, conversation_id=identifier)
        asyncio.run(
            rebuilt.conversations.submit(
                identifier,
                message="Another process submits a task",
                submission_id="concurrent-turn",
                options=ChatExecutionOptions(fake_scenario=FakeScenario.DIRECT),
            )
        )

    def intercepted(
        selection: ProjectModelSelection,
        *,
        expected_revision: int,
        expected_review: ModelSelectionReview | None = None,
        validate_review: Callable[[], None] | None = None,
    ) -> None:
        if change in {"profile", "profile-aba"}:
            profiles.set(
                "small", configuration=RuntimeConfiguration(max_requests=3), expected_revision=1
            )
            if change == "profile-aba":
                profiles.set("small", configuration=RuntimeConfiguration(), expected_revision=2)
        elif change == "config":
            path = harness.repository_root / ".fleet/agents/engineer.md"
            path.write_text(path.read_text() + "\nConcurrent configuration change\n")
        elif change == "inspection-aba":
            service.tasks(identifier, current=True)
        elif change == "expiry":
            service.reviews.clock = ExpiredClock()
        else:
            with ThreadPoolExecutor(max_workers=1) as executor:
                executor.submit(new_turn).result(timeout=15)
        original(
            selection,
            expected_revision=expected_revision,
            expected_review=expected_review,
            validate_review=validate_review,
        )

    monkeypatch.setattr(profiles.store, "save_selection", intercepted)
    with pytest.raises(FleetError):
        service.review(identifier, action="confirm", arguments=(code,))
    assert profiles.selection(project)["revision"] == 0
    assert not any(item.action == "selection.set" for item in profiles.store.list_audit())
    with pytest.raises(FleetError):
        service.review(identifier, action="confirm", arguments=(code,))


async def test_atomic_model_confirmation_does_not_nest_conversation_transactions(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = harness.container.conversations
    identifier = _selected(harness)
    await _submit(harness, identifier, "first")
    profiles = harness.container.model_profiles
    profiles.set("small", configuration=RuntimeConfiguration())
    review = service.models(identifier, profile="small", default=True)
    original = profiles.store.save_selection

    def intercepted(
        selection: ProjectModelSelection,
        *,
        expected_revision: int,
        expected_review: ModelSelectionReview | None = None,
        validate_review: Callable[[], None] | None = None,
    ) -> None:
        with monkeypatch.context() as scoped:
            scoped.setattr(
                SqliteConversationStore,
                "_transaction",
                lambda *_: pytest.fail("Nested conversation transaction during selection write"),
            )
            original(
                selection,
                expected_revision=expected_revision,
                expected_review=expected_review,
                validate_review=validate_review,
            )

    monkeypatch.setattr(profiles.store, "save_selection", intercepted)
    service.review(
        identifier, action="confirm", arguments=(cast(str, review["confirmation_code"]),)
    )
    project = profiles.project(harness.repository_root)
    assert profiles.selection(project)["default_profile"] == "small"


async def test_history_choices_are_conversation_scoped_and_expire_when_page_changes(
    harness: FleetHarness,
) -> None:
    service = harness.container.conversations
    first = _selected(harness)
    first_run = await _submit(harness, first, "first")
    second = cast(str, service.select(harness.repository_root, create_new=True)["conversation_id"])
    await _submit(harness, second, "second")
    second_page = service.tasks(second)
    assert second_page["has_more"] is False
    project_id = harness.container.state.get_run(first_run).project_id
    foreign = service.store.list_turns(project_id, first)[0]
    service._task_choices[second][1] = foreign.binding.turn_id
    with pytest.raises(FleetError, match="this conversation"):
        service.tasks(second, select_sequence=1)
    service.tasks(second)
    service.tasks(second, before_sequence=1)
    with pytest.raises(FleetError, match="displayed page"):
        service.tasks(second, select_sequence=1)


async def test_task_history_paginates_twenty_exact_summaries(harness: FleetHarness) -> None:
    service = harness.container.conversations
    identifier = _selected(harness)
    for sequence in range(1, 22):
        await _submit(harness, identifier, f"task-{sequence}")
    page = service.tasks(identifier)
    tasks = page["tasks"]
    assert isinstance(tasks, list) and len(tasks) == 20
    assert [item["sequence"] for item in tasks if isinstance(item, dict)] == list(range(21, 1, -1))
    assert page["has_more"] is True and page["next_before_sequence"] == 2
    assert all("run_id" not in item for item in tasks if isinstance(item, dict))
    with pytest.raises(FleetError):
        service.tasks(identifier, select_sequence=1)
    older = service.tasks(identifier, before_sequence=2)
    assert isinstance(older["tasks"], list) and len(older["tasks"]) == 1
    assert older["has_more"] is False and older["next_before_sequence"] is None
    assert service.tasks(identifier, select_sequence=1)["inspection_mode"] == "selected"
