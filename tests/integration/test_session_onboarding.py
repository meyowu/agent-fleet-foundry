"""Actual public preview/bootstrap and permission resolution from a selected session."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from conftest import FleetHarness

from agent_fleet.adapters.repository.git import GitRepositoryAdapter
from agent_fleet.adapters.system import UuidIdGenerator
from agent_fleet.application.conversations import ChatExecutionOptions, SessionBootstrapOptions
from agent_fleet.bootstrap import build_container
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import (
    ApprovalChoice,
    ApprovalStatus,
    FakeScenario,
    RunStatus,
    SandboxConfiguration,
    SandboxPreflight,
    SandboxRequirements,
)
from agent_fleet.domain.trust import TrustMode

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_real_public_preview_is_nonexecuting_and_failure_never_publishes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = GitRepositoryAdapter(tmp_path, UuidIdGenerator()).create_canary_fixture(
        tmp_path / "target"
    )
    container = build_container(tmp_path / "state")
    service = container.conversations
    calls: list[str] = []

    async def unavailable(
        configuration: SandboxConfiguration, requirements: SandboxRequirements
    ) -> SandboxPreflight:
        calls.append(configuration.provider)
        raise FleetError(
            ErrorCode.SANDBOX_UNAVAILABLE, "No existing local image.", "Prepare one explicitly."
        )

    monkeypatch.setattr(container.sandboxes, "preflight", unavailable)
    options = SessionBootstrapOptions(docker_image="fleet-local:prepared")
    preview = service.preview_initialization(repository, options=options)
    assert "+++ b/.fleet/fleet.yaml" in cast(str, preview["proposal_patch"])
    assert calls == [] and not (repository / ".fleet").exists()
    assert container.state.get_project_by_root(str(repository)) is None
    assert not (container.state_root / "bootstrap").exists()
    with pytest.raises(FleetError) as error:
        await service.initialize(code=cast(str, preview["confirmation_code"]))
    assert error.value.code is ErrorCode.SANDBOX_UNAVAILABLE
    assert calls == ["docker"]
    assert container.state.get_project_by_root(str(repository)) is None
    assert not (repository / ".fleet").exists()
    assert not (container.state_root / "bootstrap").exists()
    with pytest.raises(FleetError):
        await service.initialize(code=cast(str, preview["confirmation_code"]))
    assert calls == ["docker"]


async def test_setup_review_cannot_reinitialize_registered_project(harness: FleetHarness) -> None:
    before = harness.git("status", "--porcelain")
    with pytest.raises(FleetError):
        harness.container.conversations.preview_initialization(
            harness.repository_root,
            options=SessionBootstrapOptions(docker_image="fleet-local:prepared"),
        )
    assert harness.git("status", "--porcelain") == before


async def test_no_id_approval_reviews_exact_scope_then_grants_without_resume(
    harness: FleetHarness,
) -> None:
    service = harness.container.conversations
    selected = service.select(harness.repository_root)
    identifier = cast(str, selected["conversation_id"])
    view = await service.submit(
        identifier,
        message="Fix the canary",
        submission_id="no-id-approval",
        options=ChatExecutionOptions(fake_scenario=FakeScenario.APPROVAL),
    )
    run_id = cast(str, view["run_id"])
    paused = harness.container.state.get_run(run_id)
    request_id = paused.pending_approval_id
    assert request_id is not None and paused.status is RunStatus.PAUSED_FOR_APPROVAL
    shown = service.approve(identifier)
    assert isinstance(shown["request"], dict) and shown["request"]["request_id"] == request_id
    prepared = service.approve(identifier, choice=ApprovalChoice.ALLOW_ONCE)
    assert isinstance(prepared["request"], dict) and prepared["request"]["request_id"] == request_id
    assert harness.container.state.get_approval(request_id).status is ApprovalStatus.PENDING
    code = cast(str, prepared["confirmation_code"])
    service.review(identifier, action="confirm", arguments=(code,))
    assert harness.container.state.get_approval(request_id).status is ApprovalStatus.APPROVED
    assert harness.container.state.get_run(run_id) == paused
    with pytest.raises(FleetError):
        service.review(identifier, action="confirm", arguments=(code,))
    resumed = await service.resume(identifier)
    assert resumed["run_id"] == run_id
    assert harness.container.state.get_run(run_id).status is RunStatus.READY_FOR_REVIEW


async def test_no_id_selection_never_guesses_between_parallel_child_approvals(
    harness: FleetHarness,
) -> None:
    harness.container.permissions.configure(
        harness.repository_root, mode=TrustMode.SAFE, allowed_paths=(".",)
    )
    service = harness.container.conversations
    identifier = cast(str, service.select(harness.repository_root)["conversation_id"])
    view = await service.submit(
        identifier,
        message="Fix the canary",
        submission_id="parallel-no-id",
        options=ChatExecutionOptions(fake_scenario=FakeScenario.PARALLEL_ENGINEERS),
    )
    run_id = cast(str, view["run_id"])
    response = service.approve(identifier, choice=ApprovalChoice.ALLOW_ONCE)
    assert response["selection_required"] is True
    pending = response["pending_requests"]
    assert isinstance(pending, list) and len(pending) == 2
    assert "confirmation_code" not in response
    assert all(isinstance(item, dict) and item["status"] == "pending" for item in pending)
    await service.cancel(identifier)
    assert not harness.container.state.outstanding_leases(run_id)


async def test_resolved_or_cancelled_request_invalidates_approval_review(
    harness: FleetHarness,
) -> None:
    service = harness.container.conversations
    identifier = cast(str, service.select(harness.repository_root)["conversation_id"])
    view = await service.submit(
        identifier,
        message="Fix the canary",
        submission_id="stale-approval",
        options=ChatExecutionOptions(fake_scenario=FakeScenario.APPROVAL),
    )
    run_id = cast(str, view["run_id"])
    request_id = harness.container.state.get_run(run_id).pending_approval_id
    assert request_id is not None
    review = service.approve(identifier, choice=ApprovalChoice.ALLOW_ONCE)
    service.deny(identifier, request_id)
    with pytest.raises(FleetError):
        service.review(
            identifier, action="confirm", arguments=(cast(str, review["confirmation_code"]),)
        )
    assert harness.container.state.get_approval(request_id).status is ApprovalStatus.DENIED
    await service.cancel(identifier)
