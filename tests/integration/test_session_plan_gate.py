"""The persisted planning decision is a real execution boundary, not a UI label."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import cast

import pytest
from conftest import FleetHarness
from test_custom_role_workflow import _install

from agent_fleet.application.conversations import ChatExecutionOptions
from agent_fleet.application.runtime import RuntimeRegistry
from agent_fleet.bootstrap import build_container
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.evidence import EvidenceBundle
from agent_fleet.domain.models import (
    AgentInvocation,
    AgentInvocationResult,
    ApprovalChoice,
    FakeScenario,
    Run,
    RunStatus,
    RuntimeConfiguration,
    WorkflowStage,
)
from agent_fleet.ports.runtime import RuntimeInvocationServices

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def paused(
    harness: FleetHarness, scenario: FakeScenario = FakeScenario.SUCCESS
) -> tuple[str, Run]:
    service = harness.container.conversations
    identifier = cast(str, service.select(harness.repository_root)["conversation_id"])
    view = await service.submit(
        identifier,
        message="Fix the canary behavior",
        submission_id="reviewed-plan",
        options=ChatExecutionOptions(fake_scenario=scenario, review_plan=True),
    )
    run = harness.container.state.get_run(cast(str, view["run_id"]))
    assert run.status is RunStatus.PAUSED_FOR_PLAN
    assert run.stage is WorkflowStage.SCOPING
    assert view["turn_status"] == "waiting" and view["recovery_required"] is False
    assert harness.container.state.list_leases(run.run_id) == []
    assert harness.container.graphs.get(run.run_id) is None
    assert harness.container.graphs.descendants(run.run_id) == ()
    assert run.engineer_checkpoint is None and run.verifier_agent_instance_id is None
    assert run.task_spec_hash and run.fleet_plan_hash and run.config_snapshot_hash
    return identifier, run


@pytest.mark.parametrize(
    "scenario",
    [
        FakeScenario.SUCCESS,
        FakeScenario.DIRECT,
        FakeScenario.SINGLE_ENGINEER,
        FakeScenario.PARALLEL_ENGINEERS,
        FakeScenario.SPECIALIST,
    ],
)
async def test_every_strategy_pauses_before_dispatch_then_resumes_frozen_plan(
    harness: FleetHarness, scenario: FakeScenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    identifier, run = await paused(harness, scenario)
    baseline = harness.git("status", "--porcelain")
    reopened = build_container(harness.state_root)
    service = reopened.conversations
    service.select(harness.repository_root, conversation_id=identifier)

    async def forbidden_scope(*args: object, **kwargs: object) -> Run:
        raise AssertionError("Resuming a reviewed plan must never invoke CoS again")

    monkeypatch.setattr(reopened.workflow, "_scope", forbidden_scope)
    # An unapproved resume remains an orderly waiting turn, without retaining a claim.
    assert (await service.resume(identifier))["turn_status"] == "waiting"
    shown = service.review(identifier, action="plan")
    assert shown["mode"] == "pre_execution_gate"
    prepared = service.review(identifier, action="plan", arguments=("approve",))
    code = cast(str, prepared["confirmation_code"])
    confirmed = service.review(identifier, action="confirm", arguments=(code,))
    assert isinstance(confirmed["checkpoint"], dict)
    assert confirmed["checkpoint"]["status"] == "approved"
    assert reopened.state.get_run(run.run_id) == run
    assert reopened.state.list_leases(run.run_id) == []
    assert reopened.state.list_grants(run.run_id) == []
    assert harness.git("status", "--porcelain") == baseline
    with pytest.raises(FleetError):
        service.review(identifier, action="confirm", arguments=(code,))
    result = await service.resume(identifier)
    assert result["turn_status"] == "delivered"
    final = reopened.state.get_run(run.run_id)
    assert final.status in {RunStatus.READY_FOR_REVIEW, RunStatus.COMPLETED}
    assert (
        final.task_spec_hash == run.task_spec_hash and final.fleet_plan_hash == run.fleet_plan_hash
    )
    assert reopened.plan_reviews.inspect(final).status == "consumed"
    events = reopened.state.list_events(run.run_id)
    assert sum(event.event_type == "fleet.plan_accepted" for event in events) == 1
    before_replay = len(events)
    assert (await reopened.workflow.resume(run.run_id)) == final
    assert len(reopened.state.list_events(run.run_id)) == before_replay
    assert harness.git("status", "--porcelain") == baseline


@dataclass
class ReviewClock:
    value: datetime

    def now(self) -> datetime:
        return self.value


@pytest.mark.parametrize("mode", ["expired", "selection", "already-approved", "cancelled"])
async def test_plan_confirmation_is_one_shot_exact_and_cannot_resume(
    harness: FleetHarness, mode: str
) -> None:
    identifier, run = await paused(harness)
    service = harness.container.conversations
    clock = ReviewClock(service.reviews.clock.now())
    service.reviews.clock = clock
    prepared = service.review(identifier, action="plan", arguments=("approve",))
    code = cast(str, prepared["confirmation_code"])
    if mode == "expired":
        clock.value += timedelta(minutes=5)
    elif mode == "selection":
        service.select(harness.repository_root, create_new=True)
        service.select(harness.repository_root, conversation_id=identifier)
    elif mode == "cancelled":
        await service.cancel(identifier)
    else:
        checkpoint = harness.container.plan_reviews.inspect(run)
        harness.container.plan_reviews.approve(run, checkpoint.checkpoint_sha256)
    with pytest.raises(FleetError):
        service.review(identifier, action="confirm", arguments=(code,))
    with pytest.raises(FleetError):
        service.review(identifier, action="confirm", arguments=(code,))
    assert harness.container.state.list_leases(run.run_id) == []
    assert harness.container.graphs.get(run.run_id) is None
    assert harness.container.plan_reviews.inspect(run).status != "consumed"


async def test_consumed_owner_is_never_reclaimed_even_without_conversation(
    harness: FleetHarness,
) -> None:
    run = await harness.container.workflow.start(
        project_path=harness.repository_root,
        goal="Fix the canary behavior",
        runtime_name=None,
        sandbox_name=None,
        fake_scenario=None,
        review_plan=True,
    )
    checkpoint = harness.container.plan_reviews.inspect(run)
    approved = harness.container.plan_reviews.approve(run, checkpoint.checkpoint_sha256)
    running = harness.container.plan_reviews.consume(run, approved.checkpoint_sha256)
    assert running.status is RunStatus.RUNNING and running.stage is WorkflowStage.SCOPING
    restarted = build_container(harness.state_root)
    with pytest.raises(FleetError) as error:
        await restarted.workflow.resume(run.run_id)
    assert error.value.code is ErrorCode.RECOVERY_REQUIRED
    assert restarted.state.get_run(run.run_id) == running
    assert restarted.state.list_leases(run.run_id) == []
    recovered = await restarted.recovery.recover_run(run.run_id)
    assert recovered.status is RunStatus.FAILED
    assert restarted.plan_reviews.inspect(recovered).status == "consumed"


async def test_two_public_resumes_have_one_execution_owner(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = await harness.container.workflow.start(
        project_path=harness.repository_root,
        goal="Fix the canary behavior",
        runtime_name=None,
        sandbox_name=None,
        fake_scenario=None,
        review_plan=True,
    )
    checkpoint = harness.container.plan_reviews.inspect(run)
    harness.container.plan_reviews.approve(run, checkpoint.checkpoint_sha256)
    entered = asyncio.Event()
    release = asyncio.Event()
    original = harness.container.workflow._dispatch_scoped_plan

    async def held(current: Run) -> Run:
        entered.set()
        await release.wait()
        return await original(current)

    monkeypatch.setattr(harness.container.workflow, "_dispatch_scoped_plan", held)
    first = asyncio.create_task(harness.container.workflow.resume(run.run_id))
    try:
        await asyncio.wait_for(entered.wait(), timeout=10)
        with pytest.raises(FleetError):
            await build_container(harness.state_root).workflow.resume(run.run_id)
        assert harness.container.state.get_run(run.run_id).status is RunStatus.RUNNING
    finally:
        release.set()
    assert (await first).status is RunStatus.READY_FOR_REVIEW


async def test_reviewed_plan_retains_later_exact_tool_approval_resume(
    harness: FleetHarness,
) -> None:
    identifier, run = await paused(harness, FakeScenario.APPROVAL)
    service = harness.container.conversations
    prepared = service.review(identifier, action="plan", arguments=("approve",))
    service.review(
        identifier, action="confirm", arguments=(cast(str, prepared["confirmation_code"]),)
    )
    await service.resume(identifier)
    paused_command = harness.container.state.get_run(run.run_id)
    assert paused_command.status is RunStatus.PAUSED_FOR_APPROVAL
    assert paused_command.pending_approval_id is not None
    reopened = build_container(harness.state_root)
    reopened.conversations.select(harness.repository_root, conversation_id=identifier)
    reopened.conversations.approve(
        identifier, paused_command.pending_approval_id, choice=ApprovalChoice.ALLOW_ONCE
    )
    assert (await reopened.conversations.resume(identifier))["turn_status"] == "delivered"
    assert reopened.plan_reviews.inspect(reopened.state.get_run(run.run_id)).status == "consumed"


@pytest.mark.parametrize("stage", ["pending", "approved"])
async def test_cancellation_preserves_plan_record_and_releases_turn(
    harness: FleetHarness, stage: str
) -> None:
    identifier, run = await paused(harness)
    checkpoint = harness.container.plan_reviews.inspect(run)
    if stage == "approved":
        checkpoint = harness.container.plan_reviews.approve(run, checkpoint.checkpoint_sha256)
    cancelled = await harness.container.conversations.cancel(identifier)
    assert cancelled["turn_status"] == "cancelled" and cancelled["active_turn_id"] is None
    current = harness.container.state.get_run(run.run_id)
    assert current.status is RunStatus.CANCELLED
    assert harness.container.plan_reviews.inspect(current) == checkpoint
    assert await harness.container.workflow.resume(run.run_id) == current


async def test_stale_target_rejected_before_consumption_and_turn_remains_recoverable(
    harness: FleetHarness,
) -> None:
    identifier, run = await paused(harness)
    checkpoint = harness.container.plan_reviews.inspect(run)
    harness.container.plan_reviews.approve(run, checkpoint.checkpoint_sha256)
    (harness.repository_root / "new-user-file.txt").write_text("User changes after planning\n")
    with pytest.raises(FleetError):
        await harness.container.conversations.resume(identifier)
    assert harness.container.state.get_run(run.run_id).status is RunStatus.PAUSED_FOR_PLAN
    assert harness.container.conversations.status(identifier)["turn_status"] == "waiting"
    assert harness.container.plan_reviews.inspect(run).status == "approved"
    assert harness.container.state.list_leases(run.run_id) == []


async def test_versioned_custom_roles_profiles_and_review_checkpoint_compose_across_restart(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, _ = await _install(harness)
    runtime.invocations.clear()
    runtime.kinds.clear()
    service = harness.container.model_profiles
    project = service.project(harness.repository_root)
    configurations = {
        "planning": RuntimeConfiguration(max_requests=9),
        "coding": RuntimeConfiguration(max_requests=11),
        "reviewing": RuntimeConfiguration(max_requests=13),
    }
    for name, configuration in configurations.items():
        service.set(name, configuration=configuration)
    service.bind(project, default=True, profile="planning", expected_revision=0)
    service.bind(project, role="backend", profile="coding", expected_revision=1)
    service.bind(project, role="security", profile="reviewing", expected_revision=2)
    calls: list[tuple[str, RuntimeConfiguration]] = []
    original = runtime.invoke

    async def record(
        request: AgentInvocation, services: RuntimeInvocationServices
    ) -> AgentInvocationResult:
        calls.append((request.role, services.configuration))
        return await original(request, services)

    monkeypatch.setattr(runtime, "invoke", record)
    identifier, run = await paused(harness)
    assert [role for role, _ in calls] == ["cos"]
    checkpoint = harness.container.plan_reviews.inspect(run)
    assert checkpoint.binding.model_bindings_sha256 == run.model_bindings_sha256
    assert checkpoint.binding.organization_admission.revision == 1
    assert run.model_bindings_sha256 is not None
    bindings = service.inspect_bindings(
        project, root_run_id=run.run_id, expected_sha256=run.model_bindings_sha256
    )
    assert bindings.roles["backend"].configuration == configurations["coding"]
    # A user catalog edit while paused is a future-run choice, not an implicit
    # rewrite of the already reviewed task/model authority.
    service.set("coding", configuration=RuntimeConfiguration(max_requests=19), expected_revision=1)
    reopened = build_container(harness.state_root)
    reopened.workflow.runtimes = RuntimeRegistry({"fake": runtime})
    reopened.conversations.select(harness.repository_root, conversation_id=identifier)
    shown = reopened.conversations.review(identifier, action="plan", arguments=("approve",))
    reopened.conversations.review(
        identifier, action="confirm", arguments=(cast(str, shown["confirmation_code"]),)
    )
    assert [role for role, _ in calls] == ["cos"]
    await reopened.conversations.resume(identifier)
    final = reopened.state.get_run(run.run_id)
    assert final.status is RunStatus.READY_FOR_REVIEW
    assert calls == [
        ("cos", configurations["planning"]),
        ("backend", configurations["coding"]),
        ("security", configurations["reviewing"]),
    ]
    consumed = reopened.plan_reviews.inspect(final)
    assert consumed.binding == checkpoint.binding and consumed.status == "consumed"
    events = reopened.state.list_events(run.run_id)
    selections = [event for event in events if event.event_type == "runtime.model_selected"]
    assert [event.payload["role"] for event in selections] == ["cos", "backend", "security"]
    assert all(
        event.payload["model_bindings_sha256"] == run.model_bindings_sha256 for event in selections
    )
    assert final.evidence_bundle_artifact_id is not None
    evidence = EvidenceBundle.model_validate_json(
        reopened.artifacts.read_text(final.evidence_bundle_artifact_id)
    )
    assert evidence.verifier_role == "security"
    assert {command.principal_role for command in evidence.command_evidence} == {
        "backend",
        "security",
    }
    assert all(
        request.instructions and "Custom guidance" in request.instructions
        for request in runtime.invocations
        if request.role != "cos"
    )
    assert not final.verified_complete  # These profiles and sandbox are explicitly scripted.


async def test_waiting_plan_retains_organization_publication_fence(harness: FleetHarness) -> None:
    _, proposal_id = await _install(harness)
    identifier, run = await paused(harness)
    head = harness.container.organization.store.get_head(run.project_id)
    checkpoint = harness.container.plan_reviews.inspect(run)
    with pytest.raises(FleetError):
        harness.container.organization.rollback(proposal_id)
    assert harness.container.organization.store.get_head(run.project_id) == head
    assert harness.container.plan_reviews.inspect(run) == checkpoint
    assert harness.container.conversations.status(identifier)["turn_status"] == "waiting"
    assert (harness.repository_root / ".fleet/agents/roles.yaml").is_file()
