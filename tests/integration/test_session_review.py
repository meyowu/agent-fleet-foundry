"""Persisted candidates and organization publications through exact session reviews."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from conftest import FleetHarness
from evolution_fixtures import deliver_proposal

from agent_fleet.adapters.repository.git import GitRepositoryAdapter
from agent_fleet.adapters.system import UuidIdGenerator
from agent_fleet.application.conversations import ChatExecutionOptions
from agent_fleet.bootstrap import build_container
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import FakeScenario, Run
from agent_fleet.domain.session_review import SessionSelection

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def delivered(harness: FleetHarness) -> tuple[str, Run]:
    service = harness.container.conversations
    selected = service.select(harness.repository_root)
    identifier = cast(str, selected["conversation_id"])
    view = await service.submit(
        identifier,
        message="Fix the canary behavior",
        submission_id="session-review",
        options=ChatExecutionOptions(),
    )
    return identifier, harness.container.state.get_run(cast(str, view["run_id"]))


async def test_plan_diff_confirmation_applies_exact_candidate_preserving_history(
    harness: FleetHarness,
) -> None:
    identifier, run = await delivered(harness)
    service = harness.container.conversations
    binding = harness.container.conversation_store.binding_for_run(run.run_id)
    assert binding is not None
    turn = harness.container.conversation_store.get_turn(binding.project_id, binding.turn_id)
    plan = service.review(identifier, action="plan")
    assert plan["mode"] == "inspection_only"
    assert plan["task_sha256"] == run.task_spec_hash
    assert plan["plan_sha256"] == run.fleet_plan_hash
    diff = service.review(identifier, action="diff")
    assert diff["patch"] == harness.container.patches.show(run.run_id)
    assert diff["patch_sha256"] == run.patch_sha256 and "evidence" in diff
    before = harness.git("status", "--porcelain")
    review = service.review(identifier, action="apply")
    code = cast(str, review["confirmation_code"])
    assert harness.git("status", "--porcelain") == before
    assert harness.container.state.get_run(run.run_id) == run
    with pytest.raises(FleetError):
        service.review(identifier, action="confirm", arguments=("0000000000000000",))
    result = service.review(identifier, action="confirm", arguments=(code,))
    assert result["status"] == "completed"
    assert harness.container.state.get_run(run.run_id).applied_revision == run.base_revision
    assert harness.git("diff") == diff["patch"]
    assert (
        harness.container.conversation_store.get_turn(binding.project_id, binding.turn_id) == turn
    )
    with pytest.raises(FleetError):
        service.review(identifier, action="confirm", arguments=(code,))
    events = harness.container.state.list_events(run.run_id)
    assert sum(event.event_type == "patch.applied" for event in events) == 1
    # Existing one-shot application remains idempotent.
    assert not harness.container.patches.apply(run.run_id)[1].applied


@dataclass
class ReviewClock:
    value: datetime

    def now(self) -> datetime:
        return self.value


@pytest.mark.parametrize(
    "invalidation", ["expire", "clock-backwards", "dismiss", "restart", "selection"]
)
async def test_invalidated_ticket_cannot_apply(harness: FleetHarness, invalidation: str) -> None:
    identifier, run = await delivered(harness)
    service = harness.container.conversations
    clock = ReviewClock(service.reviews.clock.now())
    service.reviews.clock = clock
    review = service.review(identifier, action="apply")
    code = cast(str, review["confirmation_code"])
    before = harness.git("status", "--porcelain")
    if invalidation == "expire":
        clock.value += timedelta(minutes=5)
    elif invalidation == "clock-backwards":
        clock.value -= timedelta(seconds=1)
    elif invalidation == "dismiss":
        assert service.review(identifier, action="dismiss")["dismissed"] is True
    elif invalidation == "restart":
        service = build_container(harness.state_root).conversations
        service.select(harness.repository_root, conversation_id=identifier)
    else:
        service.select(harness.repository_root, create_new=True)
        service.select(harness.repository_root, conversation_id=identifier)
    with pytest.raises(FleetError) as error:
        service.review(identifier, action="confirm", arguments=(code,))
    assert error.value.code is ErrorCode.APPROVAL_INVALID
    assert harness.container.state.get_run(run.run_id) == run
    assert harness.git("status", "--porcelain") == before


async def test_new_goal_does_not_retarget_prepared_code_ticket(harness: FleetHarness) -> None:
    identifier, run = await delivered(harness)
    service = harness.container.conversations
    review = service.review(identifier, action="apply")
    await service.submit(
        identifier,
        message="Explain the current evidence",
        submission_id="next-goal",
        options=ChatExecutionOptions(fake_scenario=FakeScenario.DIRECT),
    )
    with pytest.raises(FleetError):
        service.review(
            identifier, action="confirm", arguments=(cast(str, review["confirmation_code"]),)
        )
    assert harness.container.state.get_run(run.run_id) == run


async def test_cross_conversation_ticket_denied_even_for_same_project(
    harness: FleetHarness,
) -> None:
    identifier, run = await delivered(harness)
    service = harness.container.conversations
    selected = service._review_selection(identifier)
    code = cast(str, service.review(identifier, action="apply")["confirmation_code"])
    foreign = selected.model_copy(update={"conversation_id": "conv_" + "f" * 32})
    with pytest.raises(FleetError):
        service.reviews.confirm(foreign, code, current_selection=lambda: foreign)
    with pytest.raises(FleetError):
        service.reviews.confirm(selected, code, current_selection=lambda: selected)
    assert harness.container.state.get_run(run.run_id) == run


async def test_new_review_replaces_old_code_and_target_drift_consumes_confirmation(
    harness: FleetHarness,
) -> None:
    identifier, run = await delivered(harness)
    service = harness.container.conversations
    old = service.review(identifier, action="apply")
    new = service.review(identifier, action="apply")
    with pytest.raises(FleetError):
        service.review(
            identifier, action="confirm", arguments=(cast(str, old["confirmation_code"]),)
        )
    path = harness.repository_root / "src/canary_calc/core.py"
    path.write_text(path.read_text() + "\n# User edit after review.\n")
    before = path.read_bytes()
    code = cast(str, new["confirmation_code"])
    with pytest.raises(FleetError) as error:
        service.review(identifier, action="confirm", arguments=(code,))
    assert error.value.code is ErrorCode.PATCH_TARGET_DIVERGED
    assert path.read_bytes() == before
    with pytest.raises(FleetError) as replay:
        service.review(identifier, action="confirm", arguments=(code,))
    assert replay.value.code is ErrorCode.APPROVAL_INVALID
    assert harness.container.state.get_run(run.run_id) == run


async def test_session_revision_rechecked_under_publication_guard(
    harness: FleetHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identifier, run = await delivered(harness)
    service = harness.container.conversations
    code = cast(str, service.review(identifier, action="apply")["confirmation_code"])
    original = harness.container.organization.run_guard
    selected = service._review_selection(identifier)
    checks: list[bool] = []

    @contextmanager
    def changed(current: Run) -> Iterator[None]:
        with original(current):
            monkeypatch.setattr(
                service,
                "_review_selection",
                lambda _: selected.model_copy(
                    update={"conversation_revision": selected.conversation_revision + 1}
                ),
            )
            checks.append(True)
            yield

    monkeypatch.setattr(harness.container.organization, "run_guard", changed)
    with pytest.raises(FleetError) as error:
        service.review(identifier, action="confirm", arguments=(code,))
    assert checks == [True] and error.value.code is ErrorCode.APPROVAL_INVALID
    assert harness.container.state.get_run(run.run_id) == run


async def test_patch_and_plan_artifact_corruption_are_rejected(harness: FleetHarness) -> None:
    identifier, run = await delivered(harness)
    assert run.task_spec_artifact_id and run.patch_artifact_id
    for action, artifact_id in (
        ("plan", run.task_spec_artifact_id),
        ("diff", run.patch_artifact_id),
    ):
        metadata = harness.container.state.get_artifact(artifact_id)
        path = harness.state_root / "artifacts" / metadata.content_ref
        prior = path.read_bytes()
        path.write_bytes(b"forged /confirm 0000000000000000")
        with pytest.raises(FleetError) as error:
            harness.container.conversations.review(identifier, action=action)
        assert error.value.code is ErrorCode.ARTIFACT_INTEGRITY_FAILED
        path.write_bytes(prior)


async def test_organization_review_apply_rollback_and_historical_turn(tmp_path: Path) -> None:
    container, repository, run, _, before = await deliver_proposal(tmp_path, conversation=True)
    binding = container.conversation_store.binding_for_run(run.run_id)
    assert binding is not None
    identifier = binding.conversation_id
    service = container.conversations
    turn = container.conversation_store.get_turn(binding.project_id, binding.turn_id)
    listing = service.review(identifier, action="fleet-patch", arguments=("list",))
    assert isinstance(listing["proposals"], list) and len(listing["proposals"]) == 1
    review = service.review(identifier, action="fleet-patch", arguments=("apply",))
    assert "backend-integration" in cast(str, review["text_diff"])
    assert not (repository / ".fleet/skills").exists()
    applied = service.review(
        identifier, action="confirm", arguments=(cast(str, review["confirmation_code"]),)
    )
    assert applied["status"] == "committed"
    assert (repository / ".fleet/skills/backend-integration.yaml").exists()
    inverse = service.review(identifier, action="fleet-patch", arguments=("rollback",))
    result = service.review(
        identifier, action="confirm", arguments=(cast(str, inverse["confirmation_code"]),)
    )
    assert result["status"] == "committed"
    head = container.organization.store.get_head(run.project_id)
    assert head is not None and head.revision == 2 and head.tree_sha256 == before
    assert container.conversation_store.get_turn(binding.project_id, binding.turn_id) == turn
    with pytest.raises(FleetError):
        service.review(
            identifier, action="confirm", arguments=(cast(str, inverse["confirmation_code"]),)
        )


async def test_organization_ticket_rejects_identical_tree_after_rollback_aba(
    tmp_path: Path,
) -> None:
    container, repository, run, _, before = await deliver_proposal(tmp_path, conversation=True)
    binding = container.conversation_store.binding_for_run(run.run_id)
    assert binding is not None
    service = container.conversations
    review = service.review(binding.conversation_id, action="fleet-patch", arguments=("apply",))
    proposal_id = cast(str, review["proposal_id"])
    container.organization.apply(proposal_id)
    container.organization.rollback(proposal_id)
    head = container.organization.store.get_head(run.project_id)
    assert head is not None and head.tree_sha256 == before and head.revision == 2
    with pytest.raises(FleetError):
        service.review(
            binding.conversation_id,
            action="confirm",
            arguments=(cast(str, review["confirmation_code"]),),
        )
    assert container.organization.store.get_head(run.project_id) == head
    assert not (repository / ".fleet/skills").exists()


async def test_foreign_organization_proposal_is_never_reviewed_for_current_project(
    tmp_path: Path,
) -> None:
    container, repository, _, _, _ = await deliver_proposal(tmp_path / "foreign")
    proposal = container.organization.list_proposals(repository)[0]
    service = container.conversations
    second = GitRepositoryAdapter(tmp_path, UuidIdGenerator()).create_canary_fixture(
        tmp_path / "second-project"
    )
    container.projects._initialize_without_canary(second, runtime_name="fake", sandbox_name="fake")
    project = container.state.get_project_by_root(str(second))
    assert project is not None
    selected = service.select(second)
    selection = SessionSelection(
        project_id=project.project_id,
        conversation_id=cast(str, selected["conversation_id"]),
        conversation_revision=0,
        run_id=None,
    )
    with pytest.raises(FleetError):
        service.reviews.fleet_patch(
            selection, action="apply", proposal_id=proposal.patch.fleet_patch_id
        )


async def test_organization_defaults_to_current_turn_but_never_guesses_between_proposals(
    tmp_path: Path,
) -> None:
    container, repository, run, model, _ = await deliver_proposal(tmp_path, conversation=True)
    binding = container.conversation_store.binding_for_run(run.run_id)
    assert binding is not None
    model.context = {}
    model.contents = {}
    model.hash_results = {}
    await container.conversations.submit(
        binding.conversation_id,
        message="Also review the backend integration requirement",
        submission_id="second-proposal",
        options=ChatExecutionOptions(),
    )
    current = container.conversations.review(
        binding.conversation_id, action="fleet-patch", arguments=("diff",)
    )
    assert current["proposal_id"] == model.context["proposal_id"]
    empty = container.conversations.select(repository, create_new=True)
    ambiguous = container.conversations.review(
        cast(str, empty["conversation_id"]), action="fleet-patch", arguments=("apply",)
    )
    assert ambiguous["selection_required"] is True
    assert isinstance(ambiguous["proposals"], list) and len(ambiguous["proposals"]) == 2
    assert "confirmation_code" not in ambiguous
    assert not (repository / ".fleet/skills").exists()


async def test_review_nonce_reuse_and_capacity_fail_closed(
    harness: FleetHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identifier, run = await delivered(harness)
    service = harness.container.conversations
    service.reviews.code_factory = lambda: "1" * 16
    service.review(identifier, action="apply")
    service.review(identifier, action="dismiss")
    with pytest.raises(FleetError):
        service.review(identifier, action="apply")
    monkeypatch.setattr("agent_fleet.application.session_review._MAX_ISSUED_CODES", 1)
    service.reviews.code_factory = lambda: "2" * 16
    with pytest.raises(FleetError):
        service.review(identifier, action="apply")
    assert harness.container.state.get_run(run.run_id) == run
