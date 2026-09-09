"""Shared admission/output subset, not complete Harness or execution qualification."""

from __future__ import annotations

from typing import cast

import pytest
from pydantic_ai.models.test import TestModel

from agent_fleet.adapters.runtime.fake import FakeRuntimeAdapter
from agent_fleet.adapters.runtime.pydantic_ai import PydanticAIRuntimeAdapter
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import (
    AgentInvocation,
    AgentRole,
    FakeScenario,
    ImplementationReport,
    RuntimeCapability,
    RuntimeConfiguration,
    RuntimeOutput,
    RuntimeToolCall,
    RuntimeToolDefinition,
    RuntimeToolExecutionRecord,
    RuntimeToolResult,
    ScopeDecision,
    SpecialistReport,
    Verdict,
    VerifierVerdict,
    WorkflowStage,
)
from agent_fleet.domain.security import Redactor
from agent_fleet.ports.runtime import RuntimeAdapter, RuntimeInvocationServices
from agent_fleet.ports.runtime_accounting import RuntimeAccounting
from agent_fleet.ports.secret_store import SecretStore


class SyntheticCatalog:
    """Explicit non-executing fixture; its returned references are not real evidence."""

    def __init__(self, *, with_tools: bool = True) -> None:
        self.calls: list[RuntimeToolCall] = []
        self.with_tools = with_tools

    @property
    def definitions(self) -> tuple[RuntimeToolDefinition, ...]:
        return (
            tuple(
                RuntimeToolDefinition(
                    name=name,
                    description="Synthetic test transport only.",
                    parameters_json_schema={"type": "object", "properties": {}},
                    side_effect=name != "repo_list_files",
                )
                for name in ("workspace_write_file", "run_verification", "repo_list_files")
            )
            if self.with_tools
            else ()
        )

    @property
    def records(self) -> tuple[RuntimeToolExecutionRecord, ...]:
        return ()

    def validate(self, call: RuntimeToolCall) -> None:
        assert call.name in {definition.name for definition in self.definitions}

    async def execute(self, call: RuntimeToolCall) -> RuntimeToolResult:
        self.validate(call)
        self.calls.append(call)
        return RuntimeToolResult(call_id=call.call_id, name=call.name, content={})


class NoAccountingEffects:
    def record_simulated_step(self) -> None:
        raise AssertionError("rejected invocation must not consume a simulated step")

    def remaining_active_seconds(self) -> float:
        raise AssertionError("rejected invocation must not enter a model loop")


class NoSecretAccess:
    def inspect(self, *args: object) -> object:
        raise AssertionError("rejected invocation must not inspect a credential")

    def resolve(self, *args: object) -> object:
        raise AssertionError("rejected invocation must not resolve a credential")


def request(role: str) -> AgentInvocation:
    return AgentInvocation(
        run_id="run_" + "1" * 32,
        task_id="task_" + "2" * 32,
        agent_instance_id="agent_" + "3" * 32,
        role=role,
        stage=WorkflowStage.SCOPING if role == "cos" else WorkflowStage.IMPLEMENTING,
        iteration=0,
        max_steps=5,
        input={
            "goal": "Return a bounded output.",
            "fake_scenario": FakeScenario.SUCCESS.value,
            "repair_iterations": 0,
            "sandbox_capabilities": {"executes_code": False},
        },
    )


def configuration(name: str) -> RuntimeConfiguration:
    return (
        RuntimeConfiguration()
        if name == "fake"
        else RuntimeConfiguration(
            runtime_name="pydantic-ai",
            provider_model="openai:offline-conformance",
            credential_ref="env:FLEET_CONFORMANCE_TEST_ONLY",
            max_retries=0,
        )
    )


def expected_output(kind: AgentRole, role: str) -> RuntimeOutput:
    if kind is AgentRole.COS:
        return ScopeDecision(
            normalized_goal="Return a bounded output.",
            change_kind="read_only",
            fleet_strategy="direct",
            allowed_paths=[],
            forbidden_paths=[".git", ".fleet"],
            acceptance_criteria=[{"criterion_id": "bounded", "description": "Bounded output."}],
            required_evidence=["control_plane_plan"],
        )
    if kind is AgentRole.ENGINEER:
        return ImplementationReport(
            summary="A typed proposal only.",
            intended_changed_paths=["src/example.py"],
            tests_added_or_changed=[],
            criterion_results=["bounded: proposal"],
            evidence_artifact_ids=[],
            unresolved_limitations=["No actual execution."],
            verifier_focus=["Check bounded behavior."],
        )
    if kind is AgentRole.VERIFIER:
        return VerifierVerdict(
            verdict=Verdict.INCONCLUSIVE,
            criterion_results=["bounded: unverified"],
            evidence_artifact_ids=[],
            regressions=[],
            required_repairs=[],
            proof_gaps=["No actual execution."],
            rationale="A typed verdict is not proof of correctness.",
        )
    return SpecialistReport(
        role=role,
        summary="Bounded analysis only.",
        findings=["A repository observation."],
        recommendations=["Keep the bounded scope."],
        proof_gaps=["No actual execution."],
    )


@pytest.mark.parametrize("runtime", ["fake", "pydantic-ai"])
@pytest.mark.parametrize(
    ("kind", "custom"),
    [(kind, False) for kind in AgentRole]
    + [(kind, True) for kind in AgentRole if kind is not AgentRole.COS],
)
async def test_shared_role_output_matrix(runtime: str, kind: AgentRole, custom: bool) -> None:
    role = "custom-" + kind.value if custom else kind.value
    expected = expected_output(kind, role)
    # TestModel is explicitly offline and emits only the configured typed output.
    model = TestModel(call_tools=[], custom_output_args=expected.model_dump(mode="json"))
    adapter: RuntimeAdapter = (
        FakeRuntimeAdapter()
        if runtime == "fake"
        else PydanticAIRuntimeAdapter.for_test_model(model)
    )
    catalog = SyntheticCatalog(with_tools=kind is not AgentRole.COS)
    result = await adapter.invoke(
        request(role),
        RuntimeInvocationServices(
            configuration=configuration(runtime),
            tools=catalog,
            execution_kind=kind if custom else None,
        ),
    )
    assert isinstance(result.output, type(expected))
    if isinstance(result.output, SpecialistReport):
        assert result.output.role == role
    if runtime == "pydantic-ai":
        assert result.output == expected
        assert model.last_model_request_parameters is not None
    else:
        assert result.usage is None
        if kind is not AgentRole.COS:
            assert catalog.calls
    assert RuntimeCapability.CHECKPOINT not in adapter.capabilities
    assert RuntimeCapability.RESUME not in adapter.capabilities


@pytest.mark.parametrize("runtime", ["fake", "pydantic-ai"])
@pytest.mark.parametrize("use_offline_model", [False, True])
@pytest.mark.parametrize("case", ["checkpoint", "wrong-runtime", "unbound", "rebound", "cos-alias"])
async def test_shared_rejection_precedes_model_secret_accounting_and_tools(
    runtime: str, use_offline_model: bool, case: str
) -> None:
    model = TestModel()
    adapter: RuntimeAdapter
    if runtime == "fake":
        adapter = FakeRuntimeAdapter()
    elif use_offline_model:
        adapter = PydanticAIRuntimeAdapter.for_test_model(model)
    else:
        adapter = PydanticAIRuntimeAdapter(cast(SecretStore, NoSecretAccess()), Redactor())
    invocation = request("engineer")
    selected = runtime
    kind = None
    code = ErrorCode.RUNTIME_CAPABILITY_MISSING
    if case == "checkpoint":
        invocation.checkpoint_ref = "art_" + "4" * 32
    elif case == "wrong-runtime":
        selected = "pydantic-ai" if runtime == "fake" else "fake"
        code = ErrorCode.RUNTIME_UNAVAILABLE
    elif case == "unbound":
        invocation.role = "unbound-specialist"
    elif case == "rebound":
        kind = AgentRole.VERIFIER
        code = ErrorCode.RUNTIME_OUTPUT_INVALID
    else:
        invocation.role = "cos-alias"
        kind = AgentRole.COS
        code = ErrorCode.RUNTIME_OUTPUT_INVALID
    catalog = SyntheticCatalog()
    before = invocation.model_dump_json()
    with pytest.raises(FleetError) as captured:
        await adapter.invoke(
            invocation,
            RuntimeInvocationServices(
                configuration=configuration(selected),
                tools=catalog,
                execution_kind=kind,
                accounting=cast(RuntimeAccounting, NoAccountingEffects()),
            ),
        )
    assert captured.value.code is code
    assert captured.value.__context__ is None
    assert catalog.calls == []
    assert model.last_model_request_parameters is None
    assert invocation.model_dump_json() == before


async def test_fake_cos_catalog_rejected_before_simulated_step() -> None:
    with pytest.raises(FleetError) as captured:
        await FakeRuntimeAdapter().invoke(
            request("cos"),
            RuntimeInvocationServices(
                configuration=configuration("fake"),
                tools=SyntheticCatalog(),
                accounting=cast(RuntimeAccounting, NoAccountingEffects()),
            ),
        )
    assert captured.value.code is ErrorCode.RUNTIME_CAPABILITY_MISSING


@pytest.mark.parametrize("runtime", ["fake", "pydantic-ai"])
@pytest.mark.parametrize(
    "missing", [RuntimeCapability.STRUCTURED_OUTPUT, RuntimeCapability.TOOL_CALLING]
)
async def test_missing_declared_capability_stops_the_actual_adapter_entry(
    runtime: str, missing: RuntimeCapability, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = TestModel()
    adapter: RuntimeAdapter = (
        FakeRuntimeAdapter()
        if runtime == "fake"
        else PydanticAIRuntimeAdapter.for_test_model(model)
    )
    supported = adapter.capabilities - {missing}
    monkeypatch.setattr(type(adapter), "capabilities", property(lambda _: supported))
    catalog = SyntheticCatalog()
    with pytest.raises(FleetError) as captured:
        await adapter.invoke(
            request("engineer"),
            RuntimeInvocationServices(
                configuration=configuration(runtime),
                tools=catalog,
                accounting=cast(RuntimeAccounting, NoAccountingEffects()),
            ),
        )
    assert captured.value.code is ErrorCode.RUNTIME_CAPABILITY_MISSING
    assert captured.value.details == {"missing_capabilities": [missing.value]}
    assert catalog.calls == []
    assert model.last_model_request_parameters is None
