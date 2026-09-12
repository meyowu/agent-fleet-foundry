"""Illegal CoS strategy proposals fail durably before specialist dispatch.

The runtime is an explicit fake CoS fixture, while Session registration,
Workflow planning/validation, resource accounting, and persistence are the real
application and SQLite paths.  This is offline regression evidence only: it
does not qualify a provider, harness, sandbox, or functional task outcome.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal, cast

import pytest
from conftest import FleetHarness

from agent_fleet.adapters.runtime.fake import FakeRuntimeAdapter
from agent_fleet.application.conversations import ChatExecutionOptions
from agent_fleet.application.runtime import RuntimeRegistry
from agent_fleet.domain.conversation import ConversationTurnStatus
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import (
    AgentInvocation,
    AgentInvocationResult,
    AgentRole,
    FakeScenario,
    RunStatus,
    ScopeDecision,
)
from agent_fleet.ports.runtime import RuntimeInvocationServices

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

IllegalProposal = Literal[
    "direct_code_change",
    "single_engineer_independent_verification",
    "ineligible_verifier",
    "overlapping_parallel_writers",
    "undeclared_specialist",
]


class IllegalStrategyRuntime(FakeRuntimeAdapter):
    """Return one deliberately illegal CoS proposal, then ordinary legal output."""

    def __init__(self, proposal: IllegalProposal) -> None:
        self.proposal = proposal
        self.injected = False
        self.invocations: list[AgentInvocation] = []

    async def invoke(
        self,
        request: AgentInvocation,
        services: RuntimeInvocationServices,
    ) -> AgentInvocationResult:
        self.invocations.append(request.model_copy(deep=True))
        result = await super().invoke(request, services)
        if request.role != AgentRole.COS or self.injected:
            return result
        self.injected = True
        assert isinstance(result.output, ScopeDecision)
        data = result.output.model_dump(mode="json")

        if self.proposal == "direct_code_change":
            data.update(
                change_kind="code_change",
                fleet_strategy="direct",
                allowed_paths=["src/canary_calc/core.py"],
                required_evidence=[
                    "canonical_patch",
                    "command_evidence",
                    "independent_verifier_verdict",
                ],
            )
            # A Harness may return a constructed object, but the production
            # runtime boundary reparses its serialized data and must reject it.
            decision = ScopeDecision.model_construct(**data)
        elif self.proposal == "single_engineer_independent_verification":
            data["required_evidence"] = [
                "canonical_patch",
                "command_evidence",
                "independent_verifier_verdict",
            ]
            decision = ScopeDecision.model_validate(data)
        elif self.proposal == "ineligible_verifier":
            data["role_selections"] = {"verifier": "engineer"}
            decision = ScopeDecision.model_validate(data)
        elif self.proposal == "overlapping_parallel_writers":
            assignments = cast(list[dict[str, object]], data["writer_assignments"])
            assignments[1]["scope"] = ["src/canary_calc/core.py"]
            decision = ScopeDecision.model_validate(data)
        else:
            data["role_selections"] = {"researcher": "undeclared_researcher"}
            decision = ScopeDecision.model_validate(data)
        return result.model_copy(update={"output": decision})


def _target_snapshot(harness: FleetHarness) -> tuple[str, str, dict[str, bytes]]:
    fleet_root = harness.repository_root / ".fleet"
    files = {
        path.relative_to(harness.repository_root).as_posix(): path.read_bytes()
        for path in sorted(fleet_root.rglob("*"))
        if path.is_file()
    }
    return (
        harness.git("rev-parse", "HEAD"),
        harness.git("status", "--porcelain=v1", "--untracked-files=all"),
        files,
    )


def _durable_counts(harness: FleetHarness, run_id: str) -> dict[str, object]:
    run = harness.container.state.get_run(run_id)
    with harness.container.state._connect() as connection:
        roles = connection.execute(
            "SELECT role FROM agent_instances WHERE run_id = ? ORDER BY rowid", (run_id,)
        ).fetchall()
        counts = {
            table: cast(
                int,
                connection.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE run_id = ?", (run_id,)
                ).fetchone()[0],
            )
            for table in ("tool_intents", "capability_grants", "resource_leases")
        }
        project_runs = cast(
            int,
            connection.execute(
                "SELECT COUNT(*) FROM runs WHERE project_id = ?", (run.project_id,)
            ).fetchone()[0],
        )
    return {
        "roles": [row["role"] for row in roles],
        "project_runs": project_runs,
        **counts,
    }


@pytest.mark.parametrize(
    ("proposal", "scenario", "expected_code", "message_check"),
    [
        pytest.param(
            "direct_code_change",
            FakeScenario.DIRECT,
            ErrorCode.RUNTIME_OUTPUT_INVALID,
            lambda message: "bounded output contract" in message,
            id="direct-requests-code-change-assurance",
        ),
        pytest.param(
            "single_engineer_independent_verification",
            FakeScenario.SINGLE_ENGINEER,
            ErrorCode.CONFIG_INVALID,
            lambda message: "no independent verifier" in message,
            id="single-engineer-claims-independent-verification",
        ),
        pytest.param(
            "ineligible_verifier",
            FakeScenario.SUCCESS,
            ErrorCode.CONFIG_INVALID,
            lambda message: "no compatible reviewed template" in message,
            id="engineer-verifier-selects-ineligible-verifier",
        ),
        pytest.param(
            "overlapping_parallel_writers",
            FakeScenario.PARALLEL_ENGINEERS,
            ErrorCode.CONFIG_INVALID,
            lambda message: "Writer scopes overlap" in message,
            id="parallel-engineers-overlap-write-scopes",
        ),
        pytest.param(
            "undeclared_specialist",
            FakeScenario.SPECIALIST,
            ErrorCode.CONFIG_INVALID,
            lambda message: "no compatible reviewed template" in message,
            id="specialist-plan-references-undeclared-role",
        ),
    ],
)
async def test_illegal_strategy_fails_before_dispatch_and_next_session_task_is_legal(
    harness: FleetHarness,
    proposal: IllegalProposal,
    scenario: FakeScenario,
    expected_code: ErrorCode,
    message_check: Callable[[str], bool],
) -> None:
    runtime = IllegalStrategyRuntime(proposal)
    harness.container.workflow.runtimes = RuntimeRegistry({"fake": runtime})
    service = harness.container.conversations
    conversation_id = cast(str, service.select(harness.repository_root)["conversation_id"])
    target_before = _target_snapshot(harness)
    project_before = harness.container.state.get_project_by_root(str(harness.repository_root))
    assert project_before is not None

    with pytest.raises(FleetError) as captured:
        await service.submit(
            conversation_id,
            message=f"Reject illegal strategy fixture: {proposal}",
            submission_id=f"illegal-{proposal}",
            options=ChatExecutionOptions(fake_scenario=scenario),
        )

    assert captured.value.code is expected_code
    assert message_check(captured.value.message)
    run_id = cast(str, captured.value.details["run_id"])
    failed = harness.container.state.get_run(run_id)
    assert failed.status is RunStatus.FAILED
    assert failed.task_id is None and failed.fleet_plan_artifact_id is None
    assert failed.command_evidence_artifact_ids == []
    events = harness.container.state.list_events(run_id)
    failures = [event for event in events if event.event_type == "run.failed"]
    assert len(failures) == 1 and failures[0].payload["code"] == expected_code.value
    assert [request.role for request in runtime.invocations] == [AgentRole.COS]
    assert _durable_counts(harness, run_id) == {
        "roles": ["cos"],
        "project_runs": 1,
        "tool_intents": 0,
        "capability_grants": 0,
        "resource_leases": 0,
    }
    assert harness.container.graphs.get(run_id) is None
    assert harness.container.graphs.descendants(run_id) == ()
    assert harness.container.state.list_grants(run_id) == []
    assert harness.container.state.count_executed_intents(run_id, "command.run") == 0
    assert _target_snapshot(harness) == target_before
    assert (
        harness.container.state.get_project_by_root(str(harness.repository_root)) == project_before
    )
    binding = harness.container.conversation_store.binding_for_run(run_id)
    assert binding is not None
    rejected_turn = harness.container.conversation_store.get_turn(
        binding.project_id, binding.turn_id
    )
    assert rejected_turn.status is ConversationTurnStatus.FAILED
    assert service.status(conversation_id)["active_turn_id"] is None
    old_event_ids = [event.event_id for event in events]

    legal = await service.submit(
        conversation_id,
        message="Explain the canary without changing it",
        submission_id=f"legal-after-{proposal}",
        options=ChatExecutionOptions(fake_scenario=FakeScenario.DIRECT),
    )
    legal_run_id = cast(str, legal["run_id"])
    assert legal_run_id != run_id
    assert legal["turn_status"] == "delivered"
    assert harness.container.state.get_run(legal_run_id).status is RunStatus.COMPLETED
    assert [request.role for request in runtime.invocations] == [AgentRole.COS, AgentRole.COS]
    assert harness.container.state.get_run(run_id) == failed
    assert [
        event.event_id for event in harness.container.state.list_events(run_id)
    ] == old_event_ids
    assert (
        harness.container.conversation_store.get_turn(binding.project_id, binding.turn_id)
        == rejected_turn
    )
    assert _target_snapshot(harness) == target_before
