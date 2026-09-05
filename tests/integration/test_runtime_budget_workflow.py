from __future__ import annotations

import asyncio
import json

import pytest
from conftest import FleetHarness

from agent_fleet.adapters.runtime.fake import FakeRuntimeAdapter
from agent_fleet.application.runtime import RuntimeRegistry
from agent_fleet.bootstrap import build_container
from agent_fleet.domain.budgets import RunBudgetLimits
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import (
    AgentInvocation,
    AgentInvocationResult,
    AgentRole,
    AgentStatus,
    ArtifactKind,
    FakeScenario,
    RunStatus,
)
from agent_fleet.ports.runtime import RuntimeInvocationServices

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_normal_workflow_persists_aggregate_budget_and_inspection(
    harness: FleetHarness,
) -> None:
    run = await harness.start()
    snapshot = harness.container.budgets.snapshot(run.run_id)
    assert snapshot.completeness == "complete"
    assert snapshot.agent_invocations == snapshot.simulated_steps == 3
    assert snapshot.model_requests == 0
    assert snapshot.tool_calls > 0
    assert snapshot.reported_total_tokens == 0
    assert snapshot.token_limit_is_pre_spend_billing_cap is False
    reopened = build_container(harness.state_root)
    assert reopened.budgets.snapshot(run.run_id) == snapshot
    assert reopened.inspection.status(run.run_id)["runtime_budget"] == snapshot.model_dump(
        mode="json"
    )
    summary = next(
        item
        for item in reopened.state.list_artifacts(run.run_id)
        if item.kind is ArtifactKind.RUN_SUMMARY
    )
    summary_fields = dict(
        line.split("=", 1)
        for line in reopened.artifacts.read_text(summary.artifact_id).splitlines()
    )
    delivery = json.loads(summary_fields["delivery_evidence"])
    assert delivery["changed_files"] == ["src/canary_calc/core.py"]
    assert delivery["patch_sha256"] == run.patch_sha256
    assert delivery["commands"]
    assert all(item["strength"] == "simulated" for item in delivery["commands"])
    assert delivery["proof_gaps"]


@pytest.mark.parametrize(
    "limits",
    [RunBudgetLimits(max_agent_invocations=1), RunBudgetLimits(max_tool_calls=0)],
)
async def test_budget_stops_before_engineer_effect_and_cleans_resources(
    harness: FleetHarness, limits: RunBudgetLimits
) -> None:
    before = harness.git("status", "--porcelain")
    with pytest.raises(FleetError) as captured:
        await harness.container.workflow.start(
            project_path=harness.repository_root,
            goal="Fix the canary behavior",
            runtime_name="fake",
            sandbox_name="fake",
            fake_scenario=FakeScenario.SUCCESS,
            budget_limits=limits,
        )
    assert captured.value.code is ErrorCode.RUNTIME_BUDGET_EXCEEDED
    run_id = str(captured.value.details["run_id"])
    run = harness.container.state.get_run(run_id)
    assert run.status is RunStatus.FAILED
    assert not harness.container.state.outstanding_leases(run_id)
    assert harness.container.state.count_executed_intents(run_id, "workspace.write_file") == 0
    assert harness.git("status", "--porcelain") == before
    snapshot = harness.container.budgets.snapshot(run_id)
    assert snapshot.limits == limits
    assert snapshot.agent_invocations <= limits.max_agent_invocations
    assert snapshot.tool_calls == 0


async def test_approval_restart_cannot_reset_aggregate_invocation_ceiling(
    harness: FleetHarness,
) -> None:
    paused = await harness.container.workflow.start(
        project_path=harness.repository_root,
        goal="Fix the canary behavior",
        runtime_name="fake",
        sandbox_name="fake",
        fake_scenario=FakeScenario.APPROVAL,
        budget_limits=RunBudgetLimits(max_agent_invocations=2),
    )
    assert paused.status is RunStatus.PAUSED_FOR_APPROVAL
    assert paused.pending_approval_id is not None
    before = harness.container.budgets.snapshot(paused.run_id)
    assert before.agent_invocations == 2
    restarted = build_container(harness.state_root)
    restarted.approvals.approve_once(paused.pending_approval_id)
    with pytest.raises(FleetError) as captured:
        await restarted.workflow.resume(paused.run_id)
    assert captured.value.code is ErrorCode.RUNTIME_BUDGET_EXCEEDED
    assert restarted.budgets.snapshot(paused.run_id).agent_invocations == 2
    assert restarted.state.count_executed_intents(paused.run_id, "fixture.record_side_effect") == 0
    assert not restarted.state.outstanding_leases(paused.run_id)


class BlockingAccountedRuntime(FakeRuntimeAdapter):
    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.run_id: str | None = None
        self.agent_id: str | None = None

    async def invoke(
        self, request: AgentInvocation, services: RuntimeInvocationServices
    ) -> AgentInvocationResult:
        if request.role != AgentRole.ENGINEER:
            return await super().invoke(request, services)
        assert services.accounting is not None
        services.accounting.record_simulated_step()
        self.run_id = request.run_id
        self.agent_id = request.agent_instance_id
        self.entered.set()
        await asyncio.Event().wait()
        raise AssertionError("The blocked runtime must be cancelled")


class ExplodingAccountedRuntime(FakeRuntimeAdapter):
    async def invoke(
        self, request: AgentInvocation, services: RuntimeInvocationServices
    ) -> AgentInvocationResult:
        assert services.accounting is not None
        services.accounting.record_simulated_step()
        raise RuntimeError("private-harness-error-sentinel")


async def test_unexpected_harness_error_has_no_raw_exception_context(
    harness: FleetHarness,
) -> None:
    harness.container.redactor.register_secrets(["private-harness-error-sentinel"])
    harness.container.workflow.runtimes = RuntimeRegistry({"fake": ExplodingAccountedRuntime()})
    with pytest.raises(FleetError) as captured:
        await harness.start()
    error = captured.value
    assert error.code is ErrorCode.INTERNAL_ERROR
    assert error.__context__ is None and error.__cause__ is None
    run_id = str(error.details["run_id"])
    assert "private-harness-error-sentinel" not in str(harness.container.inspection.logs(run_id))
    assert harness.container.budgets.snapshot(run_id).simulated_steps == 1


async def test_aggregate_active_deadline_interrupts_blocked_runtime_and_cleans_up(
    harness: FleetHarness,
) -> None:
    runtime = BlockingAccountedRuntime()
    harness.container.workflow.runtimes = RuntimeRegistry({"fake": runtime})
    with pytest.raises(FleetError) as captured:
        async with asyncio.timeout(10):
            await harness.container.workflow.start(
                project_path=harness.repository_root,
                goal="Fix the canary behavior",
                runtime_name="fake",
                sandbox_name="fake",
                fake_scenario=FakeScenario.SUCCESS,
                budget_limits=RunBudgetLimits(max_active_seconds=1),
            )
    assert captured.value.code is ErrorCode.RUNTIME_BUDGET_EXCEEDED
    assert runtime.run_id is not None and runtime.agent_id is not None
    assert harness.container.state.get_run(runtime.run_id).status is RunStatus.FAILED
    assert harness.container.state.get_agent_instance(runtime.agent_id).status is AgentStatus.FAILED
    assert not harness.container.state.outstanding_leases(runtime.run_id)
    snapshot = harness.container.budgets.snapshot(runtime.run_id)
    assert snapshot.exhausted
    assert snapshot.simulated_steps == 2


async def test_cancelled_invocation_retains_charged_usage_and_exact_agent_status(
    harness: FleetHarness,
) -> None:
    runtime = BlockingAccountedRuntime()
    harness.container.workflow.runtimes = RuntimeRegistry({"fake": runtime})
    execution = asyncio.create_task(harness.start())
    try:
        await asyncio.wait_for(runtime.entered.wait(), timeout=10)
        execution.cancel()
        with pytest.raises(asyncio.CancelledError):
            await execution
        assert runtime.run_id is not None and runtime.agent_id is not None
        agent = harness.container.state.get_agent_instance(runtime.agent_id)
        assert agent.status is AgentStatus.CANCELLED
        snapshot = harness.container.budgets.snapshot(runtime.run_id)
        assert snapshot.agent_invocations == snapshot.simulated_steps == 2
        assert snapshot.outstanding_requests == 0
        await harness.container.cancellation.cancel(runtime.run_id)
        assert not harness.container.state.outstanding_leases(runtime.run_id)
        assert harness.container.budgets.snapshot(runtime.run_id).simulated_steps == 2
    finally:
        if not execution.done():
            execution.cancel()
            await asyncio.gather(execution, return_exceptions=True)
        if runtime.run_id is not None:
            await harness.container.cancellation.cancel(runtime.run_id)
