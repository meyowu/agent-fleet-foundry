"""SQLite dispatch ownership prevents concurrent or restarted intent replay."""

from __future__ import annotations

import asyncio
import sqlite3
import threading
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass

import pytest
from conftest import FleetHarness
from pydantic import JsonValue

from agent_fleet.application.gateway import ToolGateway
from agent_fleet.bootstrap import build_container
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import (
    AgentInstance,
    AgentStatus,
    ApprovalChoice,
    ApprovalRequest,
    FakeScenario,
    IntentStatus,
    PermissionDecision,
    PermissionOutcome,
    Run,
    RunStatus,
    SandboxCapabilities,
    SandboxHandle,
    ScriptedAction,
    TaskSpec,
    ToolIntent,
    Workspace,
)
from agent_fleet.domain.trust import TrustMode

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@dataclass(frozen=True)
class _Invocation:
    run: Run
    task: TaskSpec
    agent: AgentInstance
    workspace: Workspace
    sandbox_handle: SandboxHandle
    scripted: ScriptedAction

    async def execute(self, gateway: ToolGateway) -> dict[str, JsonValue]:
        return await gateway.execute(
            run=self.run,
            task=self.task,
            agent=self.agent,
            workspace=self.workspace,
            sandbox_handle=self.sandbox_handle,
            scripted=self.scripted,
        )


async def _approved_invocation(
    harness: FleetHarness,
    scenario: FakeScenario,
    choice: ApprovalChoice = ApprovalChoice.ALLOW_ONCE,
) -> tuple[_Invocation, ApprovalRequest]:
    if scenario is FakeScenario.SUCCESS:
        harness.container.permissions.configure(
            harness.repository_root, mode=TrustMode.SAFE, allowed_paths=(".",)
        )
    paused = await harness.start(scenario)
    assert paused.status is RunStatus.PAUSED_FOR_APPROVAL
    assert paused.pending_approval_id is not None
    request = harness.container.state.get_approval(paused.pending_approval_id)
    assert request.action == (
        "command.run" if scenario is FakeScenario.SUCCESS else "fixture.record_side_effect"
    )
    harness.container.approvals.approve(request.request_id, choice=choice)
    stored = harness.container.state.get_intent(request.intent_id)
    intent = stored.intent
    run = paused.model_copy(update={"status": RunStatus.RUNNING, "pending_approval_id": None})
    harness.container.state.save_run(
        run, "run.resumed", {"approval_request_id": request.request_id}
    )
    with sqlite3.connect(harness.container.state.database_path) as connection:
        row = connection.execute(
            "SELECT data_json FROM agent_instances WHERE agent_instance_id = ?",
            (intent.agent_instance_id,),
        ).fetchone()
    assert row is not None
    agent = AgentInstance.model_validate_json(row[0]).model_copy(
        update={"status": AgentStatus.RUNNING, "completed_at": None}
    )
    harness.container.state.save_agent_instance(agent)
    resources = harness.container.recovery.resources
    return (
        _Invocation(
            run=run,
            task=harness.container.state.get_task(intent.task_id),
            agent=agent,
            workspace=resources.candidate_workspace(run.run_id),
            sandbox_handle=resources.engineer_sandbox(run.run_id),
            scripted=ScriptedAction(
                action=intent.action,
                resource=intent.resource,
                parameters=intent.parameters,
                reason=intent.reason,
                side_effect=intent.side_effect,
                idempotency_key=intent.idempotency_key,
            ),
        ),
        request,
    )


@pytest.mark.parametrize("scenario", [FakeScenario.SUCCESS, FakeScenario.APPROVAL])
async def test_simultaneous_approved_resumes_dispatch_exact_once_intent_only_once(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch, scenario: FakeScenario
) -> None:
    invocation, request = await _approved_invocation(harness, scenario)
    rebuilt = [build_container(harness.state_root), build_container(harness.state_root)]
    gateways = [container.workflow.gateway for container in rebuilt]
    assert rebuilt[0].state is not rebuilt[1].state
    assert rebuilt[0].state.database_path == rebuilt[1].state.database_path
    evaluated = threading.Barrier(2, timeout=10)
    release_dispatch = threading.Event()
    dispatch_lock = threading.Lock()
    executions: list[str] = []
    expected: dict[str, JsonValue] = {"dispatch_probe": "one exact approved operation"}

    def synchronize_decisions(gateway: ToolGateway) -> None:
        evaluate = gateway.permission_broker.evaluate

        def after_evaluate(
            intent: ToolIntent, task: TaskSpec, sandbox: SandboxCapabilities
        ) -> PermissionDecision:
            decision = evaluate(intent, task, sandbox)
            assert decision.outcome is PermissionOutcome.ALLOW
            # Both callers read the same approval and authorize before either reserves it.
            evaluated.wait()
            return decision

        monkeypatch.setattr(gateway.permission_broker, "evaluate", after_evaluate)

    async def intercepted_executor(
        *,
        run: Run,
        task: TaskSpec,
        workspace: Workspace,
        sandbox_handle: SandboxHandle,
        intent: ToolIntent,
    ) -> dict[str, JsonValue]:
        assert intent.intent_id == request.intent_id
        with dispatch_lock:
            executions.append(intent.intent_id)
            if len(executions) > 1:
                # A regression must report duplicate dispatch, not hang at a second barrier.
                release_dispatch.set()
        assert release_dispatch.wait(timeout=10), "The concurrent loser did not finish safely."
        return expected

    def invoke(gateway: ToolGateway) -> dict[str, JsonValue] | FleetError:
        try:
            return asyncio.run(invocation.execute(gateway))
        except FleetError as error:
            return error

    for gateway in gateways:
        synchronize_decisions(gateway)
        monkeypatch.setattr(gateway, "_execute_reserved", intercepted_executor)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(invoke, gateway) for gateway in gateways]
        try:
            done, _ = await asyncio.to_thread(
                wait, futures, timeout=10, return_when=FIRST_COMPLETED
            )
            assert done, "Neither concurrent resume made a bounded decision."
        finally:
            release_dispatch.set()
        outcomes = [future.result(timeout=10) for future in futures]

    assert executions == [request.intent_id]
    successes = [outcome for outcome in outcomes if isinstance(outcome, dict)]
    assert successes and all(outcome == expected for outcome in successes)
    for outcome in outcomes:
        if isinstance(outcome, FleetError):
            assert outcome.code is ErrorCode.COMMAND_OUTCOME_AMBIGUOUS
    reopened = build_container(harness.state_root)
    stored = reopened.state.get_intent(request.intent_id)
    assert stored.status is IntentStatus.EXECUTED
    assert stored.result == expected
    events = reopened.state.list_events(invocation.run.run_id)
    for event_type in ("capability.consumed", "intent.dispatch_claimed"):
        matching = [
            event
            for event in events
            if event.event_type == event_type
            and event.payload.get("intent_id") == request.intent_id
        ]
        assert len(matching) == 1
    grant = reopened.state.list_grants(invocation.run.run_id)[0]
    assert grant.remaining_uses == 0


@pytest.mark.parametrize("scenario", [FakeScenario.SUCCESS, FakeScenario.APPROVAL])
@pytest.mark.parametrize("choice", [ApprovalChoice.ALLOW_ONCE, ApprovalChoice.ALLOW_RUN])
async def test_restart_after_dispatch_claim_never_replays_incomplete_intent(
    harness: FleetHarness,
    monkeypatch: pytest.MonkeyPatch,
    scenario: FakeScenario,
    choice: ApprovalChoice,
) -> None:
    invocation, request = await _approved_invocation(harness, scenario, choice)
    state = harness.container.state
    reserved = state.consume_grant_and_reserve(request.request_id, request.intent_hash)
    assert reserved.status is IntentStatus.RESERVED
    assert state.claim_reserved_intent_for_dispatch(request.intent_id, request.intent_hash)

    reopened = build_container(harness.state_root)
    executions: list[str] = []

    async def reject_replay(
        *,
        run: Run,
        task: TaskSpec,
        workspace: Workspace,
        sandbox_handle: SandboxHandle,
        intent: ToolIntent,
    ) -> dict[str, JsonValue]:
        executions.append(intent.intent_id)
        raise AssertionError("Restart replayed an operation with an uncertain dispatch outcome.")

    monkeypatch.setattr(reopened.workflow.gateway, "_execute_reserved", reject_replay)
    with pytest.raises(FleetError) as captured:
        await invocation.execute(reopened.workflow.gateway)
    if choice is ApprovalChoice.ALLOW_ONCE:
        assert captured.value.code in {
            ErrorCode.APPROVAL_INVALID,
            ErrorCode.COMMAND_OUTCOME_AMBIGUOUS,
        }
    else:
        assert captured.value.code is ErrorCode.COMMAND_OUTCOME_AMBIGUOUS
    assert executions == []
    stored = reopened.state.get_intent(request.intent_id)
    assert stored.status is IntentStatus.RESERVED and stored.result is None
    dispatches = [
        event
        for event in reopened.state.list_events(invocation.run.run_id)
        if event.event_type == "intent.dispatch_claimed"
        and event.payload.get("intent_id") == request.intent_id
    ]
    assert len(dispatches) == 1
    assert not reopened.state.claim_reserved_intent_for_dispatch(
        request.intent_id, request.intent_hash
    )
