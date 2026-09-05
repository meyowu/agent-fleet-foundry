from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agent_fleet.adapters.runtime.fake import FakeRuntimeAdapter
from agent_fleet.domain.models import (
    AgentInvocation,
    AgentRole,
    FakeScenario,
    ImplementationReport,
    RuntimeConfiguration,
    RuntimeToolCall,
    RuntimeToolDefinition,
    RuntimeToolExecutionRecord,
    RuntimeToolResult,
    ScopeDecision,
    SpecialistReport,
    TaskSpec,
    VerifierVerdict,
    WorkflowStage,
)
from agent_fleet.ports.runtime import EMPTY_RUNTIME_TOOL_CATALOG, RuntimeInvocationServices

NOW = datetime(2026, 9, 5, tzinfo=UTC)


class ReadRecordingCatalog:
    def __init__(self) -> None:
        self.calls: list[RuntimeToolCall] = []

    @property
    def definitions(self) -> tuple[RuntimeToolDefinition, ...]:
        return (
            RuntimeToolDefinition(
                name="repo_list_files",
                description="Read bounded repository file names.",
                parameters_json_schema={"type": "object"},
                side_effect=False,
            ),
        )

    @property
    def records(self) -> tuple[RuntimeToolExecutionRecord, ...]:
        return ()

    def validate(self, call: RuntimeToolCall) -> None:
        assert call.name == "repo_list_files"

    async def execute(self, call: RuntimeToolCall) -> RuntimeToolResult:
        self.validate(call)
        self.calls.append(call)
        return RuntimeToolResult(
            call_id=call.call_id, name=call.name, content={"paths": ["src/canary_calc/core.py"]}
        )


class FixtureRecordingCatalog(ReadRecordingCatalog):
    """Synthetic receipt transport, not execution evidence or a sandbox."""

    def validate(self, call: RuntimeToolCall) -> None:
        assert call.name in {"workspace_write_file", "run_verification"}

    async def execute(self, call: RuntimeToolCall) -> RuntimeToolResult:
        self.validate(call)
        self.calls.append(call)
        return RuntimeToolResult(
            call_id=call.call_id,
            name=call.name,
            content={"command_evidence_artifact_id": "art_" + "9" * 32}
            if call.name == "run_verification"
            else {},
        )


def _invocation(role: AgentRole, scenario: FakeScenario) -> AgentInvocation:
    return AgentInvocation(
        run_id="run_" + "1" * 32,
        task_id="task_" + "2" * 32,
        agent_instance_id="agent_" + "3" * 32,
        role=role,
        stage=WorkflowStage.SCOPING if role is AgentRole.COS else WorkflowStage.IMPLEMENTING,
        iteration=0,
        max_steps=10,
        input={
            "goal": "Fix the canary and add metadata.",
            "fake_scenario": scenario.value,
            "repair_iterations": 0,
            "sandbox_capabilities": {"executes_code": False},
        },
    )


async def _parallel_task() -> tuple[ScopeDecision, TaskSpec]:
    invocation = _invocation(AgentRole.COS, FakeScenario.PARALLEL_ENGINEERS)
    result = await FakeRuntimeAdapter().invoke(
        invocation,
        RuntimeInvocationServices(
            configuration=RuntimeConfiguration(), tools=EMPTY_RUNTIME_TOOL_CATALOG
        ),
    )
    assert isinstance(result.output, ScopeDecision)
    scope = result.output
    task = TaskSpec(
        task_id=invocation.task_id,
        run_id=invocation.run_id,
        original_goal=scope.normalized_goal,
        normalized_goal=scope.normalized_goal,
        base_revision="a" * 40,
        allowed_paths=scope.allowed_paths,
        forbidden_paths=scope.forbidden_paths,
        acceptance_criteria=scope.acceptance_criteria,
        required_evidence=scope.required_evidence,
        max_repair_iterations=1,
        config_snapshot_hash="b" * 64,
        created_at=NOW,
    )
    return scope, task


@pytest.mark.parametrize("role", [AgentRole.RESEARCHER, AgentRole.ARCHITECT])
async def test_fake_specialists_read_once_and_return_exact_role_non_evidence(
    role: AgentRole,
) -> None:
    catalog = ReadRecordingCatalog()
    result = await FakeRuntimeAdapter().invoke(
        _invocation(role, FakeScenario.SPECIALIST),
        RuntimeInvocationServices(configuration=RuntimeConfiguration(), tools=catalog),
    )
    assert isinstance(result.output, SpecialistReport)
    assert result.output.role == role.value
    assert len(catalog.calls) == 1
    assert result.output.proof_gaps
    assert "not execution evidence" in result.output.summary


async def test_fake_specialist_scenario_only_proposes_fixed_strategy() -> None:
    result = await FakeRuntimeAdapter().invoke(
        _invocation(AgentRole.COS, FakeScenario.SPECIALIST),
        RuntimeInvocationServices(
            configuration=RuntimeConfiguration(), tools=EMPTY_RUNTIME_TOOL_CATALOG
        ),
    )
    assert isinstance(result.output, ScopeDecision)
    assert result.output.fleet_strategy == "research_architect_engineer_verifier"
    assert result.output.writer_assignments == []


async def test_fake_parallel_proposal_and_child_scripts_keep_disjoint_scope() -> None:
    scope, task = await _parallel_task()
    assert scope.fleet_strategy == "parallel_engineers"
    assert [item.node_id for item in scope.writer_assignments] == ["core", "metadata"]
    assert len(task.acceptance_criteria) == 2
    for assignment in scope.writer_assignments:
        child = task.model_copy(
            update={
                "allowed_paths": assignment.scope,
                "acceptance_criteria": [
                    item
                    for item in task.acceptance_criteria
                    if item.criterion_id in assignment.criterion_ids
                ],
                "required_evidence": ["canonical_patch", "command_evidence"],
            }
        )
        invocation = _invocation(AgentRole.ENGINEER, FakeScenario.PARALLEL_ENGINEERS)
        invocation.input["task_spec"] = child.model_dump(mode="json")
        catalog = FixtureRecordingCatalog()
        result = await FakeRuntimeAdapter().invoke(
            invocation,
            RuntimeInvocationServices(configuration=RuntimeConfiguration(), tools=catalog),
        )
        assert isinstance(result.output, ImplementationReport)
        assert result.output.intended_changed_paths == assignment.scope
        writes = [call for call in catalog.calls if call.name == "workspace_write_file"]
        assert len(writes) == 1
        assert writes[0].arguments["path"] == assignment.scope[0]
        if assignment.node_id == "metadata":
            assert writes[0].arguments["content"] == "MESSAGE = 'verified new module'\n"


async def test_fake_parallel_verifier_claims_reference_only_returned_receipt_ids() -> None:
    _, task = await _parallel_task()
    invocation = _invocation(AgentRole.VERIFIER, FakeScenario.PARALLEL_ENGINEERS)
    invocation.stage = WorkflowStage.VERIFYING
    invocation.input["task_spec"] = task.model_dump(mode="json")
    catalog = FixtureRecordingCatalog()
    result = await FakeRuntimeAdapter().invoke(
        invocation, RuntimeInvocationServices(configuration=RuntimeConfiguration(), tools=catalog)
    )
    assert isinstance(result.output, VerifierVerdict)
    claims = result.output.structured_criterion_results
    assert claims is not None and len(claims) == 2
    assert {item.criterion_id for item in claims} == {
        item.criterion_id for item in task.acceptance_criteria
    }
    assert all(item.command_ids == ["offline-canary"] for item in claims)
    assert all(item.evidence_artifact_ids == ["art_" + "9" * 32] for item in claims)
    assert result.output.proof_gaps == ["No project code was executed by the configured sandbox."]
    assert [call.name for call in catalog.calls] == ["run_verification"]
