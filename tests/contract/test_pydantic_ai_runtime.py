from __future__ import annotations

import asyncio
import base64
import logging
import os
import socket
from http.cookiejar import CookieJar
from importlib import resources
from types import TracebackType
from typing import Any

import httpx2
import pytest
from openai import AsyncOpenAI as SDKAsyncOpenAI
from openai import OpenAIError
from pydantic_ai import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.exceptions import ModelAPIError
from pydantic_ai.models import Model, override_allow_model_requests
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RequestUsage

import agent_fleet.adapters.runtime.pydantic_ai as runtime_module
from agent_fleet.adapters.runtime.pydantic_ai import PydanticAIRuntimeAdapter
from agent_fleet.domain.errors import ApprovalRequiredError, ErrorCode, FleetError
from agent_fleet.domain.models import (
    AgentInvocation,
    AgentRole,
    ImplementationReport,
    RuntimeConfiguration,
    RuntimeCredentialCheck,
    RuntimeOutput,
    RuntimeProviderMetadata,
    RuntimeToolCall,
    RuntimeToolDefinition,
    RuntimeToolExecutionRecord,
    RuntimeToolOutcome,
    RuntimeToolResult,
    ScopeDecision,
    SpecialistReport,
    UsageRecord,
    Verdict,
    VerifierVerdict,
    WorkflowStage,
)
from agent_fleet.domain.security import Redactor
from agent_fleet.ports.runtime import RuntimeInvocationServices
from agent_fleet.ports.secret_store import (
    SecretInspection,
    SecretRef,
    SecretStatus,
    SecretValue,
)

RUN_ID = "run_00000000000000000000000000000001"
TASK_ID = "task_00000000000000000000000000000001"
AGENT_ID = "agent_00000000000000000000000000000001"


@pytest.fixture
def deny_socket_connections(monkeypatch: pytest.MonkeyPatch) -> None:
    def deny_connection(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("ordinary runtime tests must not open a network connection")

    monkeypatch.setattr(socket, "create_connection", deny_connection)
    monkeypatch.setattr(socket.socket, "connect", deny_connection)


class RecordingCatalog:
    def __init__(self, definitions: tuple[RuntimeToolDefinition, ...] = ()) -> None:
        self._definitions = definitions
        self.calls: list[RuntimeToolCall] = []
        self._records: list[RuntimeToolExecutionRecord] = []

    @property
    def definitions(self) -> tuple[RuntimeToolDefinition, ...]:
        return self._definitions

    @property
    def records(self) -> tuple[RuntimeToolExecutionRecord, ...]:
        return tuple(self._records)

    def validate(self, call: RuntimeToolCall) -> None:
        if not any(definition.name == call.name for definition in self._definitions):
            raise FleetError(
                ErrorCode.RUNTIME_OUTPUT_INVALID,
                "The runtime tool call is not valid for this catalog.",
                "Use a bound tool with schema-valid arguments.",
            )

    async def execute(self, call: RuntimeToolCall) -> RuntimeToolResult:
        definition = next(item for item in self._definitions if item.name == call.name)
        self.calls.append(call)
        self._records.append(
            RuntimeToolExecutionRecord(
                call_id=call.call_id,
                name=call.name,
                outcome=RuntimeToolOutcome.SUCCEEDED,
                side_effect=definition.side_effect,
                side_effect_committed=definition.side_effect,
            )
        )
        return RuntimeToolResult(
            call_id=call.call_id,
            name=call.name,
            content={"accepted": True},
        )


class StaticSecretStore:
    def __init__(self, value: str, status: SecretStatus = SecretStatus.CONFIGURED) -> None:
        self.value = value
        self.status = status
        self.inspect_calls = 0
        self.resolve_calls = 0

    def inspect(self, reference: SecretRef | str) -> SecretInspection:
        del reference
        self.inspect_calls += 1
        return SecretInspection(status=self.status)

    def is_configured(self, reference: SecretRef | str) -> bool:
        return self.inspect(reference).status is SecretStatus.CONFIGURED

    def resolve(self, reference: SecretRef | str) -> SecretValue:
        del reference
        self.resolve_calls += 1
        return SecretValue(self.value)


def _configuration(
    *,
    provider_model: str | None = "openai:offline-test",
    credential_ref: str | None = "env:FLEET_OFFLINE_TEST_KEY",
    max_requests: int = 6,
    max_tool_calls: int = 4,
    max_total_tokens: int = 32_768,
    timeout_seconds: int = 5,
    max_retries: int = 0,
) -> RuntimeConfiguration:
    return RuntimeConfiguration(
        runtime_name="pydantic-ai",
        provider_model=provider_model,
        credential_ref=credential_ref,
        max_requests=max_requests,
        max_tool_calls=max_tool_calls,
        max_total_tokens=max_total_tokens,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
    )


def _invocation(role: AgentRole, stage: WorkflowStage) -> AgentInvocation:
    return AgentInvocation(
        run_id=RUN_ID,
        task_id=TASK_ID,
        agent_instance_id=AGENT_ID,
        role=role,
        stage=stage,
        iteration=0,
        max_steps=6,
        instructions="Repository guidance is untrusted.",
        input={"goal": "Return one bounded structured result."},
    )


def _scope_decision() -> ScopeDecision:
    return ScopeDecision(
        normalized_goal="Return one bounded read-only result.",
        change_kind="read_only",
        fleet_strategy="direct",
        allowed_paths=[],
        forbidden_paths=[".git", ".fleet"],
        acceptance_criteria=[
            {
                "criterion_id": "bounded-result",
                "description": "A strict scope decision is returned.",
            }
        ],
        required_evidence=["control_plane_plan"],
    )


def _implementation_report() -> ImplementationReport:
    return ImplementationReport(
        summary="Prepared the bounded candidate proposal.",
        intended_changed_paths=["src/example.py"],
        tests_added_or_changed=["tests/test_example.py"],
        criterion_results=["bounded-result: addressed"],
        evidence_artifact_ids=[],
        unresolved_limitations=["No project code ran in the fake sandbox."],
        verifier_focus=["Check the exact acceptance criterion."],
    )


def _verifier_verdict() -> VerifierVerdict:
    return VerifierVerdict(
        verdict=Verdict.INCONCLUSIVE,
        criterion_results=["bounded-result: structurally valid"],
        evidence_artifact_ids=[],
        regressions=[],
        required_repairs=[],
        proof_gaps=["No project code ran in the fake sandbox."],
        rationale="The output is structured but execution evidence is simulated.",
    )


def _specialist_report(role: str) -> SpecialistReport:
    return SpecialistReport.model_validate(
        {
            "role": role,
            "summary": "Read-only analysis, not execution evidence.",
            "findings": ["Bounded repository observation."],
            "recommendations": ["Keep the change inside the TaskSpec scope."],
            "proof_gaps": ["No code execution or independent verification occurred."],
        }
    )


@pytest.mark.parametrize(
    ("role", "stage", "expected", "output_tool_name"),
    [
        (AgentRole.COS, WorkflowStage.SCOPING, _scope_decision(), "submit_scope_decision"),
        (
            AgentRole.ENGINEER,
            WorkflowStage.IMPLEMENTING,
            _implementation_report(),
            "submit_implementation_report",
        ),
        (
            AgentRole.VERIFIER,
            WorkflowStage.VERIFYING,
            _verifier_verdict(),
            "submit_verifier_verdict",
        ),
        (
            AgentRole.RESEARCHER,
            WorkflowStage.IMPLEMENTING,
            _specialist_report("researcher"),
            "submit_specialist_report",
        ),
        (
            AgentRole.ARCHITECT,
            WorkflowStage.IMPLEMENTING,
            _specialist_report("architect"),
            "submit_specialist_report",
        ),
    ],
)
async def test_test_model_returns_each_project_owned_output_contract(
    role: AgentRole,
    stage: WorkflowStage,
    expected: RuntimeOutput,
    output_tool_name: str,
) -> None:
    model = TestModel(custom_output_args=expected.model_dump(mode="json"))
    adapter = PydanticAIRuntimeAdapter.for_test_model(model)
    catalog = RecordingCatalog()

    result = await adapter.invoke(
        _invocation(role, stage),
        RuntimeInvocationServices(configuration=_configuration(), tools=catalog),
    )

    assert result.output == expected
    assert isinstance(result.usage, UsageRecord)
    assert result.usage.requests == 1
    assert result.provider_metadata == RuntimeProviderMetadata(
        provider="pydantic-ai-test",
        model="offline:test",
    )
    assert model.last_model_request_parameters is not None
    assert [tool.name for tool in model.last_model_request_parameters.output_tools] == [
        output_tool_name
    ]
    assert model.last_model_request_parameters.function_tools == []


async def test_offline_test_model_succeeds_with_socket_connections_denied(
    deny_socket_connections: None,
) -> None:
    del deny_socket_connections
    expected = _scope_decision()
    adapter = PydanticAIRuntimeAdapter.for_test_model(
        TestModel(custom_output_args=expected.model_dump(mode="json"))
    )

    result = await adapter.invoke(
        _invocation(AgentRole.COS, WorkflowStage.SCOPING),
        RuntimeInvocationServices(configuration=_configuration(), tools=RecordingCatalog()),
    )

    assert result.output == expected


async def test_function_model_deferred_tool_crosses_only_bound_catalog() -> None:
    report = _implementation_report()
    request_count = 0
    visible_tool_sets: list[tuple[str, ...]] = []

    async def scripted_model(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> ModelResponse:
        nonlocal request_count
        assert messages
        request_count += 1
        visible_tool_sets.append(tuple(tool.name for tool in info.function_tools))
        if request_count == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "workspace_write",
                        {"path": "src/example.py", "content": "value = 1\n"},
                        tool_call_id="call-1",
                    )
                ]
            )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    report.model_dump(mode="json"),
                    tool_call_id="output-1",
                )
            ]
        )

    definition = RuntimeToolDefinition(
        name="workspace_write",
        description="Request one bounded candidate-workspace write.",
        parameters_json_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        },
        side_effect=True,
    )
    catalog = RecordingCatalog((definition,))
    adapter = PydanticAIRuntimeAdapter.for_test_model(FunctionModel(scripted_model))

    result = await adapter.invoke(
        _invocation(AgentRole.ENGINEER, WorkflowStage.IMPLEMENTING),
        RuntimeInvocationServices(configuration=_configuration(), tools=catalog),
    )

    assert result.output == report
    assert request_count == 2
    assert visible_tool_sets == [("workspace_write",), ("workspace_write",)]
    assert len(catalog.calls) == 1
    assert catalog.calls[0] == RuntimeToolCall(
        call_id="call-1",
        name="workspace_write",
        arguments={"path": "src/example.py", "content": "value = 1\n"},
    )
    assert result.usage is not None
    assert result.usage.requests == 2
    assert result.usage.tool_calls == 1


async def test_tool_budget_rejects_before_catalog_execution() -> None:
    async def tool_calling_model(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> ModelResponse:
        del messages, info
        return ModelResponse(
            parts=[
                ToolCallPart(
                    "bounded_read",
                    {"logical_path": "README.md"},
                    tool_call_id="call-budget",
                )
            ]
        )

    catalog = RecordingCatalog(
        (
            RuntimeToolDefinition(
                name="bounded_read",
                description="Read one bounded logical path.",
                parameters_json_schema={
                    "type": "object",
                    "properties": {"logical_path": {"type": "string"}},
                    "required": ["logical_path"],
                    "additionalProperties": False,
                },
            ),
        )
    )
    adapter = PydanticAIRuntimeAdapter.for_test_model(FunctionModel(tool_calling_model))

    with pytest.raises(FleetError) as caught:
        await adapter.invoke(
            _invocation(AgentRole.ENGINEER, WorkflowStage.IMPLEMENTING),
            RuntimeInvocationServices(
                configuration=_configuration(max_tool_calls=0),
                tools=catalog,
            ),
        )

    assert caught.value.code is ErrorCode.RUNTIME_BUDGET_EXCEEDED
    assert catalog.calls == []


async def test_token_budget_stops_before_deferred_resume_at_exact_ceiling() -> None:
    model_requests = 0

    async def exact_budget_model(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> ModelResponse:
        nonlocal model_requests
        del messages, info
        model_requests += 1
        return ModelResponse(
            parts=[
                ToolCallPart(
                    "bounded_read",
                    {"logical_path": "README.md"},
                    tool_call_id="call-exact-budget",
                )
            ],
            usage=RequestUsage(input_tokens=5, output_tokens=5),
        )

    catalog = RecordingCatalog(
        (
            RuntimeToolDefinition(
                name="bounded_read",
                description="Read one bounded logical path.",
                parameters_json_schema={
                    "type": "object",
                    "properties": {"logical_path": {"type": "string"}},
                    "required": ["logical_path"],
                    "additionalProperties": False,
                },
            ),
        )
    )
    adapter = PydanticAIRuntimeAdapter.for_test_model(FunctionModel(exact_budget_model))

    with pytest.raises(FleetError) as caught:
        await adapter.invoke(
            _invocation(AgentRole.ENGINEER, WorkflowStage.IMPLEMENTING),
            RuntimeInvocationServices(
                configuration=_configuration(max_total_tokens=10),
                tools=catalog,
            ),
        )

    assert caught.value.code is ErrorCode.RUNTIME_BUDGET_EXCEEDED
    assert model_requests == 1
    assert catalog.calls == []


async def test_request_budget_stops_before_deferred_tool_side_effect() -> None:
    model_requests = 0

    async def last_request_model(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> ModelResponse:
        nonlocal model_requests
        del messages, info
        model_requests += 1
        return ModelResponse(
            parts=[
                ToolCallPart(
                    "workspace_write",
                    {"path": "src/example.py", "content": "value = 1\n"},
                    tool_call_id="call-last-request",
                )
            ]
        )

    catalog = RecordingCatalog(
        (
            RuntimeToolDefinition(
                name="workspace_write",
                description="Request one bounded candidate-workspace write.",
                parameters_json_schema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["path", "content"],
                    "additionalProperties": False,
                },
                side_effect=True,
            ),
        )
    )
    adapter = PydanticAIRuntimeAdapter.for_test_model(FunctionModel(last_request_model))
    request = _invocation(AgentRole.ENGINEER, WorkflowStage.IMPLEMENTING).model_copy(
        update={"max_steps": 1}
    )

    with pytest.raises(FleetError) as caught:
        await adapter.invoke(
            request,
            RuntimeInvocationServices(configuration=_configuration(), tools=catalog),
        )

    assert caught.value.code is ErrorCode.RUNTIME_BUDGET_EXCEEDED
    assert model_requests == 1
    assert catalog.calls == []


async def test_multi_call_tool_budget_is_preflighted_before_any_side_effect() -> None:
    model_requests = 0

    async def oversized_batch_model(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> ModelResponse:
        nonlocal model_requests
        del messages, info
        model_requests += 1
        return ModelResponse(
            parts=[
                ToolCallPart(
                    "workspace_write",
                    {"path": "src/one.py", "content": "one = 1\n"},
                    tool_call_id="call-one",
                ),
                ToolCallPart(
                    "workspace_write",
                    {"path": "src/two.py", "content": "two = 2\n"},
                    tool_call_id="call-two",
                ),
            ]
        )

    definition = RuntimeToolDefinition(
        name="workspace_write",
        description="Request one bounded candidate-workspace write.",
        parameters_json_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        },
        side_effect=True,
    )
    catalog = RecordingCatalog((definition,))
    adapter = PydanticAIRuntimeAdapter.for_test_model(FunctionModel(oversized_batch_model))

    with pytest.raises(FleetError) as caught:
        await adapter.invoke(
            _invocation(AgentRole.ENGINEER, WorkflowStage.IMPLEMENTING),
            RuntimeInvocationServices(
                configuration=_configuration(max_tool_calls=1),
                tools=catalog,
            ),
        )

    assert caught.value.code is ErrorCode.RUNTIME_BUDGET_EXCEEDED
    assert model_requests == 1
    assert catalog.calls == []


async def test_deferred_tool_batch_is_validated_before_any_side_effect() -> None:
    async def invalid_batch_model(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> ModelResponse:
        del messages, info
        return ModelResponse(
            parts=[
                ToolCallPart(
                    "workspace_write",
                    {"path": "src/one.py", "content": "one = 1\n"},
                    tool_call_id="call-one",
                ),
                ToolCallPart(
                    "unbound_write",
                    {"path": "src/two.py", "content": "two = 2\n"},
                    tool_call_id="call-two",
                ),
            ]
        )

    definition = RuntimeToolDefinition(
        name="workspace_write",
        description="Request one bounded candidate-workspace write.",
        parameters_json_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        },
        side_effect=True,
    )
    catalog = RecordingCatalog((definition,))
    adapter = PydanticAIRuntimeAdapter.for_test_model(FunctionModel(invalid_batch_model))

    with pytest.raises(FleetError) as caught:
        await adapter.invoke(
            _invocation(AgentRole.ENGINEER, WorkflowStage.IMPLEMENTING),
            RuntimeInvocationServices(configuration=_configuration(), tools=catalog),
        )

    assert caught.value.code is ErrorCode.RUNTIME_OUTPUT_INVALID
    assert catalog.calls == []


async def test_catalog_validates_complete_batch_before_first_side_effect() -> None:
    async def malformed_known_batch_model(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> ModelResponse:
        del messages, info
        return ModelResponse(
            parts=[
                ToolCallPart(
                    "workspace_write",
                    {"path": "src/one.py", "content": "one = 1\n"},
                    tool_call_id="call-one",
                ),
                ToolCallPart(
                    "workspace_write",
                    {"path": "src/two.py"},
                    tool_call_id="call-two",
                ),
            ]
        )

    class SchemaAwareCatalog(RecordingCatalog):
        def validate(self, call: RuntimeToolCall) -> None:
            super().validate(call)
            if "content" not in call.arguments:
                raise FleetError(
                    ErrorCode.RUNTIME_OUTPUT_INVALID,
                    "The runtime tool arguments failed trusted schema validation.",
                    "Use schema-valid arguments.",
                )

    definition = RuntimeToolDefinition(
        name="workspace_write",
        description="Request one bounded candidate-workspace write.",
        parameters_json_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        },
        side_effect=True,
    )
    catalog = SchemaAwareCatalog((definition,))
    adapter = PydanticAIRuntimeAdapter.for_test_model(FunctionModel(malformed_known_batch_model))

    with pytest.raises(FleetError) as caught:
        await adapter.invoke(
            _invocation(AgentRole.ENGINEER, WorkflowStage.IMPLEMENTING),
            RuntimeInvocationServices(configuration=_configuration(), tools=catalog),
        )

    assert caught.value.code is ErrorCode.RUNTIME_OUTPUT_INVALID
    assert catalog.calls == []


async def test_registered_secret_in_tool_arguments_is_denied_before_catalog() -> None:
    sentinel = "tool-argument-secret-sentinel"

    async def secret_bearing_model(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> ModelResponse:
        del messages, info
        return ModelResponse(
            parts=[
                ToolCallPart(
                    "external_write",
                    {"payload": f"credential={sentinel}"},
                    tool_call_id="call-secret",
                )
            ]
        )

    catalog = RecordingCatalog(
        (
            RuntimeToolDefinition(
                name="external_write",
                description="Request one approval-gated external write.",
                parameters_json_schema={
                    "type": "object",
                    "properties": {"payload": {"type": "string"}},
                    "required": ["payload"],
                    "additionalProperties": False,
                },
                side_effect=True,
            ),
        )
    )
    adapter = PydanticAIRuntimeAdapter.for_test_model(
        FunctionModel(secret_bearing_model),
        redactor=Redactor([sentinel]),
    )

    with pytest.raises(FleetError) as caught:
        await adapter.invoke(
            _invocation(AgentRole.ENGINEER, WorkflowStage.IMPLEMENTING),
            RuntimeInvocationServices(configuration=_configuration(), tools=catalog),
        )

    assert caught.value.code is ErrorCode.COMMAND_DENIED
    assert sentinel not in str(caught.value)
    assert caught.value.__context__ is None
    assert catalog.calls == []


async def test_registered_secret_is_denied_before_model_context_transport() -> None:
    sentinel = "model-context-secret-sentinel"
    model_calls = 0

    async def unreachable_model(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> ModelResponse:
        nonlocal model_calls
        del messages, info
        model_calls += 1
        raise AssertionError("secret-bearing context must not reach the model")

    adapter = PydanticAIRuntimeAdapter.for_test_model(
        FunctionModel(unreachable_model),
        redactor=Redactor([sentinel]),
    )
    request = _invocation(AgentRole.COS, WorkflowStage.SCOPING).model_copy(
        update={"input": {"goal": f"contains {sentinel}"}}
    )

    with pytest.raises(FleetError) as caught:
        await adapter.invoke(
            request,
            RuntimeInvocationServices(configuration=_configuration(), tools=RecordingCatalog()),
        )

    assert caught.value.code is ErrorCode.COMMAND_DENIED
    assert sentinel not in str(caught.value)
    assert model_calls == 0


async def test_registered_secret_collision_in_package_prompt_is_denied_before_model() -> None:
    sentinel = "TaskSpec"
    model_calls = 0

    async def unreachable_model(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> ModelResponse:
        nonlocal model_calls
        del messages, info
        model_calls += 1
        raise AssertionError("secret-bearing package prompt must not reach the model")

    catalog = RecordingCatalog()
    adapter = PydanticAIRuntimeAdapter.for_test_model(
        FunctionModel(unreachable_model),
        redactor=Redactor([sentinel]),
    )

    with pytest.raises(FleetError) as caught:
        await adapter.invoke(
            _invocation(AgentRole.ENGINEER, WorkflowStage.IMPLEMENTING),
            RuntimeInvocationServices(configuration=_configuration(), tools=catalog),
        )

    assert caught.value.code is ErrorCode.COMMAND_DENIED
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert sentinel not in str(caught.value)
    assert model_calls == 0
    assert catalog.calls == []


async def test_registered_secret_collision_in_final_request_envelope_is_denied_before_model() -> (
    None
):
    sentinel = "following"
    model_calls = 0

    async def unreachable_model(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> ModelResponse:
        nonlocal model_calls
        del messages, info
        model_calls += 1
        raise AssertionError("secret-bearing request envelope must not reach the model")

    adapter = PydanticAIRuntimeAdapter.for_test_model(
        FunctionModel(unreachable_model),
        redactor=Redactor([sentinel]),
    )

    with pytest.raises(FleetError) as caught:
        await adapter.invoke(
            _invocation(AgentRole.COS, WorkflowStage.SCOPING),
            RuntimeInvocationServices(configuration=_configuration(), tools=RecordingCatalog()),
        )

    assert caught.value.code is ErrorCode.COMMAND_DENIED
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert sentinel not in str(caught.value)
    assert model_calls == 0


async def test_registered_secret_in_companion_response_is_denied_before_tool_side_effect() -> None:
    sentinel = "hidden-model-secret-sentinel"
    model_calls = 0

    async def secret_companion_model(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> ModelResponse:
        nonlocal model_calls
        del messages, info
        model_calls += 1
        return ModelResponse(
            parts=[
                TextPart(f"provider companion text contains {sentinel}"),
                ToolCallPart(
                    "workspace_write",
                    {"path": "src/example.py", "content": "value = 1\n"},
                    tool_call_id="call-secret-companion",
                ),
            ]
        )

    catalog = RecordingCatalog(
        (
            RuntimeToolDefinition(
                name="workspace_write",
                description="Request one bounded candidate-workspace write.",
                parameters_json_schema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["path", "content"],
                    "additionalProperties": False,
                },
                side_effect=True,
            ),
        )
    )
    adapter = PydanticAIRuntimeAdapter.for_test_model(
        FunctionModel(secret_companion_model),
        redactor=Redactor([sentinel]),
    )

    with pytest.raises(FleetError) as caught:
        await adapter.invoke(
            _invocation(AgentRole.ENGINEER, WorkflowStage.IMPLEMENTING),
            RuntimeInvocationServices(configuration=_configuration(), tools=catalog),
        )

    assert caught.value.code is ErrorCode.COMMAND_DENIED
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert sentinel not in str(caught.value)
    assert model_calls == 1
    assert catalog.calls == []


async def test_registered_secret_in_structured_output_is_rejected_not_redacted() -> None:
    sentinel = "structured-output-secret-sentinel"

    async def secret_output_model(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> ModelResponse:
        del messages
        payload = _scope_decision().model_dump(mode="json")
        payload["normalized_goal"] = f"provider returned {sentinel}"
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    payload,
                    tool_call_id="secret-output",
                )
            ]
        )

    adapter = PydanticAIRuntimeAdapter.for_test_model(
        FunctionModel(secret_output_model),
        redactor=Redactor([sentinel]),
    )

    with pytest.raises(FleetError) as caught:
        await adapter.invoke(
            _invocation(AgentRole.COS, WorkflowStage.SCOPING),
            RuntimeInvocationServices(configuration=_configuration(), tools=RecordingCatalog()),
        )

    assert caught.value.code is ErrorCode.COMMAND_DENIED
    assert sentinel not in str(caught.value)


async def test_invalid_output_after_side_effect_is_not_retried() -> None:
    model_requests = 0

    async def post_side_effect_invalid_model(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> ModelResponse:
        nonlocal model_requests
        del messages, info
        model_requests += 1
        if model_requests == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "workspace_write",
                        {"path": "src/example.py"},
                        tool_call_id="call-side-effect",
                    )
                ]
            )
        return ModelResponse(parts=[TextPart("invalid after the write")])

    catalog = RecordingCatalog(
        (
            RuntimeToolDefinition(
                name="workspace_write",
                description="Request one bounded candidate-workspace write.",
                parameters_json_schema={
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                    "additionalProperties": False,
                },
                side_effect=True,
            ),
        )
    )
    adapter = PydanticAIRuntimeAdapter.for_test_model(FunctionModel(post_side_effect_invalid_model))

    with pytest.raises(FleetError) as caught:
        await adapter.invoke(
            _invocation(AgentRole.ENGINEER, WorkflowStage.IMPLEMENTING),
            RuntimeInvocationServices(
                configuration=_configuration(max_retries=3),
                tools=catalog,
            ),
        )

    assert caught.value.code is ErrorCode.RUNTIME_OUTPUT_INVALID
    assert model_requests == 2
    assert len(catalog.calls) == 1
    assert caught.value.details["runtime_diagnostic"]["category"] == (
        "structured_output_after_side_effect"
    )


@pytest.mark.parametrize(
    ("max_retries", "expected_code"),
    [
        (0, ErrorCode.RUNTIME_OUTPUT_INVALID),
        (1, ErrorCode.RUNTIME_RETRY_EXHAUSTED),
    ],
)
async def test_invalid_structured_output_maps_to_stable_error(
    max_retries: int,
    expected_code: ErrorCode,
) -> None:
    async def invalid_model(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> ModelResponse:
        del messages, info
        return ModelResponse(parts=[TextPart("not a structured Fleet result")])

    adapter = PydanticAIRuntimeAdapter.for_test_model(FunctionModel(invalid_model))

    with pytest.raises(FleetError) as caught:
        await adapter.invoke(
            _invocation(AgentRole.COS, WorkflowStage.SCOPING),
            RuntimeInvocationServices(
                configuration=_configuration(max_retries=max_retries),
                tools=RecordingCatalog(),
            ),
        )

    assert caught.value.code is expected_code
    assert caught.value.__cause__ is None
    assert caught.value.details["runtime_diagnostic"]["category"] == "structured_output"


async def test_provider_failure_is_redacted_and_has_no_exception_context() -> None:
    sentinel = "provider-secret-sentinel"

    async def failing_model(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> ModelResponse:
        del messages, info
        raise ModelAPIError("offline:test", f"upstream leaked {sentinel}")

    adapter = PydanticAIRuntimeAdapter.for_test_model(
        FunctionModel(failing_model),
        redactor=Redactor([sentinel]),
    )

    with pytest.raises(FleetError) as caught:
        await adapter.invoke(
            _invocation(AgentRole.COS, WorkflowStage.SCOPING),
            RuntimeInvocationServices(
                configuration=_configuration(),
                tools=RecordingCatalog(),
            ),
        )

    error = caught.value
    assert error.code is ErrorCode.PROVIDER_FAILED
    assert error.details["runtime_diagnostic"] == {
        "category": "provider_api",
        "cause_category": "unknown",
    }
    assert sentinel not in str(error)
    assert sentinel not in repr(error.details)
    assert error.__cause__ is None
    assert error.__context__ is None


async def test_domain_approval_subtype_survives_raw_sdk_context_removal() -> None:
    sentinel = "raw-sdk-approval-context-sentinel"
    original = ApprovalRequiredError("approval_exact_pending")
    original.add_note(sentinel)

    async def failing_model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del messages, info
        try:
            raise ExceptionGroup("raw provider context", [ValueError(sentinel)])
        except ExceptionGroup as raw:
            raise original from raw

    adapter = PydanticAIRuntimeAdapter.for_test_model(
        FunctionModel(failing_model), redactor=Redactor([sentinel])
    )
    with pytest.raises(ApprovalRequiredError) as caught:
        await adapter.invoke(
            _invocation(AgentRole.COS, WorkflowStage.SCOPING),
            RuntimeInvocationServices(configuration=_configuration(), tools=RecordingCatalog()),
        )
    error = caught.value
    assert error is original
    assert type(error) is ApprovalRequiredError
    assert error.code is ErrorCode.APPROVAL_REQUIRED
    assert error.request_id == "approval_exact_pending"
    assert error.details == {"request_id": "approval_exact_pending"}
    assert error.__context__ is error.__cause__ is None
    assert not getattr(error, "__notes__", [])
    assert sentinel not in str(error)


async def test_total_invocation_timeout_maps_to_cause_free_fleet_error() -> None:
    async def non_returning_model(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> ModelResponse:
        del messages, info
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    adapter = PydanticAIRuntimeAdapter.for_test_model(FunctionModel(non_returning_model))

    with pytest.raises(FleetError) as caught:
        await adapter.invoke(
            _invocation(AgentRole.COS, WorkflowStage.SCOPING),
            RuntimeInvocationServices(
                configuration=_configuration(timeout_seconds=1),
                tools=RecordingCatalog(),
            ),
        )

    assert caught.value.code is ErrorCode.RUNTIME_TIMEOUT
    assert caught.value.details == {
        "timeout_seconds": 1,
        "runtime_diagnostic": {"category": "invocation_timeout", "cause_category": "unknown"},
    }
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_preflight_has_distinct_shape_inspection_and_resolution_modes() -> None:
    store = StaticSecretStore("configured-secret")
    adapter = PydanticAIRuntimeAdapter(store, Redactor())
    configuration = _configuration(
        provider_model="openai:gpt-test",
        credential_ref="env:FLEET_PROVIDER_KEY",
    )

    unchecked = adapter.preflight(configuration, credential_check=RuntimeCredentialCheck.NONE)
    inspected = adapter.preflight(configuration, credential_check=RuntimeCredentialCheck.INSPECT)
    checked = adapter.preflight(configuration, credential_check=RuntimeCredentialCheck.RESOLVE)

    assert unchecked.ready is True
    assert unchecked.credential_status.value == "not_checked"
    assert inspected.ready is True
    assert inspected.credential_status.value == "configured"
    assert checked.ready is True
    assert checked.credential_status.value == "configured"
    assert store.inspect_calls == 1
    assert store.resolve_calls == 1


def test_unsupported_provider_fails_preflight_before_credential_read() -> None:
    store = StaticSecretStore("must-not-be-read")
    adapter = PydanticAIRuntimeAdapter(store, Redactor())

    with pytest.raises(FleetError) as caught:
        adapter.preflight(
            _configuration(
                provider_model="unsupported-provider:offline",
                credential_ref="env:FLEET_PROVIDER_KEY",
            ),
            credential_check=RuntimeCredentialCheck.RESOLVE,
        )

    assert caught.value.code is ErrorCode.PROVIDER_UNSUPPORTED
    assert store.inspect_calls == 0
    assert store.resolve_calls == 0


async def test_explicit_openai_client_pins_transport_and_ignores_ambient_routing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = "explicit-provider-secret"
    store = StaticSecretStore(sentinel)
    redactor = Redactor()
    captured_client_arguments: dict[str, object] = {}
    captured_transport_arguments: dict[str, object] = {}
    report = _implementation_report()

    class OfflineTransport:
        closed = False

        async def aclose(self) -> None:
            self.closed = True

    transport = OfflineTransport()

    def transport_factory(**arguments: object) -> OfflineTransport:
        captured_transport_arguments.update(arguments)
        return transport

    class OfflineClient:
        async def __aenter__(self) -> OfflineClient:
            return self

        async def __aexit__(
            self,
            exception_type: type[BaseException] | None,
            exception: BaseException | None,
            traceback: TracebackType | None,
        ) -> None:
            del exception_type, exception, traceback

    def client_factory(**arguments: object) -> OfflineClient:
        captured_client_arguments.update(arguments)
        return OfflineClient()

    def provider_factory(*, openai_client: object) -> object:
        assert isinstance(openai_client, OfflineClient)
        return object()

    def model_factory(model_name: object, *, provider: object) -> Model:
        assert model_name == "gpt-test"
        assert provider is not None
        return TestModel(custom_output_args=report.model_dump(mode="json"))

    monkeypatch.setattr(runtime_module, "AsyncOpenAI", client_factory)
    monkeypatch.setattr(runtime_module, "DefaultAsyncHttpxClient", transport_factory)
    monkeypatch.setattr(runtime_module, "OpenAIProvider", provider_factory)
    monkeypatch.setattr(runtime_module, "OpenAIResponsesModel", model_factory)
    monkeypatch.setenv("OPENAI_API_KEY", "ambient-wrong-key")
    monkeypatch.setenv("OPENAI_ADMIN_KEY", "ambient-admin-key")
    monkeypatch.setenv("OPENAI_ORG_ID", "ambient-org")
    monkeypatch.setenv("OPENAI_PROJECT_ID", "ambient-project")
    monkeypatch.setenv("OPENAI_WEBHOOK_SECRET", "ambient-webhook")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:8123/v1")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:8124")
    monkeypatch.delenv("OPENAI_CUSTOM_HEADERS", raising=False)
    environment_before = dict(os.environ)

    adapter = PydanticAIRuntimeAdapter(store, redactor)
    result = await adapter.invoke(
        _invocation(AgentRole.ENGINEER, WorkflowStage.IMPLEMENTING),
        RuntimeInvocationServices(
            configuration=_configuration(
                provider_model="openai:gpt-test",
                credential_ref="env:FLEET_PROVIDER_KEY",
            ),
            tools=RecordingCatalog(),
        ),
    )

    assert result.output == report
    assert captured_client_arguments["api_key"] == sentinel
    assert captured_client_arguments["admin_api_key"] == ""
    assert captured_client_arguments["organization"] == ""
    assert captured_client_arguments["project"] == ""
    assert captured_client_arguments["webhook_secret"] == ""
    assert captured_client_arguments["base_url"] == "https://api.openai.com/v1"
    assert captured_client_arguments["default_headers"] == {
        "Authorization": f"Bearer {sentinel}",
        "Host": "api.openai.com",
    }
    assert captured_client_arguments["http_client"] is transport
    assert captured_client_arguments["max_retries"] == 0
    assert captured_client_arguments["timeout"] == 5.0
    assert captured_transport_arguments["trust_env"] is False
    assert captured_transport_arguments["follow_redirects"] is False
    cookie_jar = captured_transport_arguments["cookies"]
    assert isinstance(cookie_jar, CookieJar)
    httpx2.Cookies(cookie_jar).extract_cookies(
        httpx2.Response(
            200,
            headers={"Set-Cookie": "provider_cookie=offline; Path=/; Secure"},
            request=httpx2.Request("POST", "https://api.openai.com/v1/responses"),
        )
    )
    assert len(cookie_jar) == 0
    event_hooks = captured_transport_arguments["event_hooks"]
    assert isinstance(event_hooks, dict)
    request_hooks = event_hooks["request"]
    assert isinstance(request_hooks, list)
    assert len(request_hooks) == 1
    assert callable(request_hooks[0])
    response_hooks = event_hooks["response"]
    assert isinstance(response_hooks, list)
    assert len(response_hooks) == 1
    assert callable(response_hooks[0])
    assert transport.closed is True
    assert dict(os.environ) == environment_before
    assert store.resolve_calls == 1
    assert redactor.contains_secret(sentinel)


async def test_ambient_openai_custom_headers_fail_before_secret_or_client_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = "selected-provider-secret"
    ambient = "Authorization: Bearer ambient-secret\nHost: attacker.invalid"
    store = StaticSecretStore(sentinel)
    adapter = PydanticAIRuntimeAdapter(store, Redactor())
    configuration = _configuration(
        provider_model="openai:gpt-test",
        credential_ref="env:FLEET_PROVIDER_KEY",
    )
    monkeypatch.setenv("OPENAI_CUSTOM_HEADERS", ambient)

    preview = adapter.preflight(configuration, credential_check=RuntimeCredentialCheck.NONE)
    checked = adapter.preflight(configuration, credential_check=RuntimeCredentialCheck.RESOLVE)

    assert preview.ready is True
    assert checked.ready is False
    assert checked.credential_status.value == "invalid"
    assert store.resolve_calls == 0
    with pytest.raises(FleetError) as caught:
        await adapter.invoke(
            _invocation(AgentRole.ENGINEER, WorkflowStage.IMPLEMENTING),
            RuntimeInvocationServices(
                configuration=configuration,
                tools=RecordingCatalog(),
            ),
        )

    assert caught.value.code is ErrorCode.PROVIDER_FAILED
    assert ambient not in str(caught.value)
    assert sentinel not in str(caught.value)
    assert store.resolve_calls == 0


async def test_final_transport_guard_rejects_sdk_merged_ambient_host_before_send(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = "selected-provider-secret"
    sends: list[httpx2.Request] = []

    async def handler(request: httpx2.Request) -> httpx2.Response:
        sends.append(request)
        return httpx2.Response(200, json={"id": "unexpected"}, request=request)

    monkeypatch.setenv("OPENAI_CUSTOM_HEADERS", "host: attacker.invalid\nX-Ambient-Race: yes")
    http_client = httpx2.AsyncClient(
        transport=httpx2.MockTransport(handler),
        trust_env=False,
        follow_redirects=False,
        event_hooks={
            "request": [runtime_module._openai_request_guard(sentinel, Redactor([sentinel]))],
            "response": [runtime_module._openai_response_guard(Redactor([sentinel]))],
        },
    )
    client = SDKAsyncOpenAI(
        api_key=sentinel,
        admin_api_key="",
        organization="",
        project="",
        webhook_secret="",
        base_url="https://api.openai.com/v1",
        default_headers={
            "Authorization": f"Bearer {sentinel}",
            "Host": "api.openai.com",
        },
        http_client=http_client,
        max_retries=0,
        timeout=5.0,
    )
    # Prove the guard validates the SDK's already-merged request, not merely the
    # environment at an earlier check point.
    monkeypatch.delenv("OPENAI_CUSTOM_HEADERS")
    try:
        with pytest.raises(OpenAIError) as caught:
            await client.responses.create(model="gpt-test", input="bounded test input")
    finally:
        await client.close()

    assert sentinel not in str(caught.value)
    assert caught.value.__cause__ is None
    assert sends == []


@pytest.mark.parametrize(
    "ambient_headers",
    [
        "OpenAI-Organization: attacker-org\nOpenAI-Project: attacker-project",
        "X-Unrelated-Secret: ambient-header-secret",
        "Content-Length: 0",
        "Content-Length: 999999",
    ],
)
async def test_final_transport_guard_rejects_sdk_merged_custom_headers_before_send(
    monkeypatch: pytest.MonkeyPatch,
    ambient_headers: str,
) -> None:
    sentinel = "selected-provider-secret"
    sends: list[httpx2.Request] = []

    async def handler(request: httpx2.Request) -> httpx2.Response:
        sends.append(request)
        return httpx2.Response(200, json={"id": "unexpected"}, request=request)

    monkeypatch.setenv("OPENAI_CUSTOM_HEADERS", ambient_headers)
    http_client = httpx2.AsyncClient(
        transport=httpx2.MockTransport(handler),
        trust_env=False,
        follow_redirects=False,
        event_hooks={
            "request": [runtime_module._openai_request_guard(sentinel, Redactor([sentinel]))]
        },
    )
    client = SDKAsyncOpenAI(
        api_key=sentinel,
        admin_api_key="",
        organization="",
        project="",
        webhook_secret="",
        base_url="https://api.openai.com/v1",
        default_headers={
            "Authorization": f"Bearer {sentinel}",
            "Host": "api.openai.com",
        },
        http_client=http_client,
        max_retries=0,
        timeout=5.0,
    )
    monkeypatch.delenv("OPENAI_CUSTOM_HEADERS")
    try:
        with pytest.raises(OpenAIError) as caught:
            await client.responses.create(model="gpt-test", input="bounded test input")
    finally:
        await client.close()

    assert sentinel not in str(caught.value)
    assert ambient_headers not in str(caught.value)
    assert sends == []


async def test_final_transport_guard_rejects_registered_secret_in_body_before_send() -> None:
    sentinel = "serialized-body-secret-sentinel"
    sends: list[httpx2.Request] = []

    async def handler(request: httpx2.Request) -> httpx2.Response:
        sends.append(request)
        return httpx2.Response(200, json={"id": "unexpected"}, request=request)

    redactor = Redactor([sentinel])
    http_client = httpx2.AsyncClient(
        transport=httpx2.MockTransport(handler),
        trust_env=False,
        follow_redirects=False,
        event_hooks={
            "request": [runtime_module._openai_request_guard(sentinel, redactor)],
        },
    )
    client = SDKAsyncOpenAI(
        api_key=sentinel,
        admin_api_key="",
        organization="",
        project="",
        webhook_secret="",
        base_url="https://api.openai.com/v1",
        default_headers={
            "Authorization": f"Bearer {sentinel}",
            "Host": "api.openai.com",
        },
        http_client=http_client,
        max_retries=0,
        timeout=5.0,
    )
    try:
        with pytest.raises(OpenAIError) as caught:
            await client.responses.create(
                model="gpt-test",
                input=f"bounded input containing {sentinel}",
            )
    finally:
        await client.close()

    assert caught.value.__cause__ is None
    assert sentinel not in str(caught.value)
    assert sends == []


async def test_final_transport_guard_minimizes_a_normal_sdk_request() -> None:
    sentinel = "selected-provider-secret"
    sends: list[httpx2.Request] = []

    async def handler(request: httpx2.Request) -> httpx2.Response:
        sends.append(request)
        return httpx2.Response(
            200,
            json={
                "id": "response-test",
                "object": "response",
                "created_at": 0,
                "status": "completed",
                "model": "gpt-test",
                "output": [],
                "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            },
            request=request,
        )

    http_client = httpx2.AsyncClient(
        transport=httpx2.MockTransport(handler),
        trust_env=False,
        follow_redirects=False,
        event_hooks={
            "request": [runtime_module._openai_request_guard(sentinel, Redactor([sentinel]))],
            "response": [runtime_module._openai_response_guard(Redactor([sentinel]))],
        },
    )
    client = SDKAsyncOpenAI(
        api_key=sentinel,
        admin_api_key="",
        organization="",
        project="",
        webhook_secret="",
        base_url="https://api.openai.com/v1",
        default_headers={
            "Authorization": f"Bearer {sentinel}",
            "Host": "api.openai.com",
        },
        http_client=http_client,
        max_retries=0,
        timeout=5.0,
    )
    try:
        await client.responses.create(model="gpt-test", input="bounded test input")
    finally:
        await client.close()

    assert len(sends) == 1
    request = sends[0]
    assert set(request.headers) == {
        "accept",
        "authorization",
        "content-length",
        "content-type",
        "host",
        "user-agent",
    }
    assert request.headers["authorization"] == f"Bearer {sentinel}"
    assert request.headers["content-length"] == str(len(request.content))


@pytest.mark.parametrize("encoded", [False, True])
async def test_response_guard_blocks_secret_bearing_sdk_logs(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    encoded: bool,
) -> None:
    sentinel = "selected-provider-response-secret"
    injected = base64.b64encode(sentinel.encode("utf-8")).decode("ascii") if encoded else sentinel
    redactor = Redactor()
    store = StaticSecretStore(sentinel)

    async def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            500,
            headers={"x-request-id": injected, "x-provider-trace": injected},
            json={"error": {"message": "provider unavailable", "type": "server_error"}},
            request=request,
        )

    def transport_factory(
        *,
        trust_env: bool,
        follow_redirects: bool,
        cookies: CookieJar,
        event_hooks: dict[str, list[Any]],
    ) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(
            transport=httpx2.MockTransport(handler),
            trust_env=trust_env,
            follow_redirects=follow_redirects,
            cookies=cookies,
            event_hooks=event_hooks,
        )

    monkeypatch.setattr(runtime_module, "DefaultAsyncHttpxClient", transport_factory)
    monkeypatch.delenv("OPENAI_CUSTOM_HEADERS", raising=False)
    adapter = PydanticAIRuntimeAdapter(store, redactor)

    with (
        override_allow_model_requests(True),
        caplog.at_level(logging.DEBUG, logger="openai"),
        pytest.raises(FleetError) as caught,
    ):
        await adapter.invoke(
            _invocation(AgentRole.COS, WorkflowStage.SCOPING),
            RuntimeInvocationServices(
                configuration=_configuration(provider_model="openai:gpt-test"),
                tools=RecordingCatalog(),
            ),
        )

    assert caught.value.code is ErrorCode.PROVIDER_FAILED
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert sentinel not in caplog.text
    assert injected not in caplog.text


async def test_request_build_unicode_failure_is_mapped_without_exception_context() -> None:
    ambient = "ambiént-header-secret"

    async def unicode_failure_model(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> ModelResponse:
        del messages, info
        raise UnicodeEncodeError("ascii", ambient, 0, len(ambient), "non-ASCII header")

    adapter = PydanticAIRuntimeAdapter.for_test_model(
        FunctionModel(unicode_failure_model),
        redactor=Redactor([ambient]),
    )

    with pytest.raises(FleetError) as caught:
        await adapter.invoke(
            _invocation(AgentRole.ENGINEER, WorkflowStage.IMPLEMENTING),
            RuntimeInvocationServices(
                configuration=_configuration(),
                tools=RecordingCatalog(),
            ),
        )

    assert caught.value.code is ErrorCode.PROVIDER_FAILED
    assert ambient not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


@pytest.mark.parametrize(
    "name", ["cos.md", "engineer.md", "verifier.md", "researcher.md", "architect.md"]
)
def test_package_owned_prompts_are_loadable_and_state_the_control_boundary(name: str) -> None:
    prompt = (
        resources.files("agent_fleet.adapters.runtime.prompts")
        .joinpath(name)
        .read_text(encoding="utf-8")
    )

    assert prompt.strip()
    assert "control plane" in prompt.casefold()


@pytest.mark.parametrize("role", [AgentRole.RESEARCHER, AgentRole.ARCHITECT])
async def test_specialist_output_cannot_impersonate_other_role(role: AgentRole) -> None:
    wrong_role = "architect" if role is AgentRole.RESEARCHER else "researcher"
    adapter = PydanticAIRuntimeAdapter.for_test_model(
        TestModel(custom_output_args=_specialist_report(wrong_role).model_dump(mode="json"))
    )
    with pytest.raises(FleetError) as caught:
        await adapter.invoke(
            _invocation(role, WorkflowStage.IMPLEMENTING),
            RuntimeInvocationServices(configuration=_configuration(), tools=RecordingCatalog()),
        )
    assert caught.value.code is ErrorCode.RUNTIME_OUTPUT_INVALID
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


@pytest.mark.parametrize("role", [AgentRole.RESEARCHER, AgentRole.ARCHITECT])
@pytest.mark.parametrize("corruption", ["secret", "verdict-field", "oversized"])
async def test_specialist_report_corruption_fails_closed(role: AgentRole, corruption: str) -> None:
    sentinel = "specialist-report-secret-sentinel"
    payload = _specialist_report(role.value).model_dump(mode="json")
    if corruption == "secret":
        payload["summary"] = sentinel
    elif corruption == "verdict-field":
        payload["verdict"] = "pass"
    else:
        payload["findings"] = ["x" * 2048] * 32

    def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del messages
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name, payload, tool_call_id="invalid-specialist-output"
                )
            ]
        )

    catalog = RecordingCatalog()
    adapter = PydanticAIRuntimeAdapter.for_test_model(
        FunctionModel(model), redactor=Redactor([sentinel])
    )
    with pytest.raises(FleetError) as caught:
        await adapter.invoke(
            _invocation(role, WorkflowStage.IMPLEMENTING),
            RuntimeInvocationServices(configuration=_configuration(), tools=catalog),
        )
    assert caught.value.code is (
        ErrorCode.COMMAND_DENIED if corruption == "secret" else ErrorCode.RUNTIME_OUTPUT_INVALID
    )
    assert caught.value.__context__ is None and caught.value.__cause__ is None
    assert sentinel not in str(caught.value)
    assert catalog.calls == []


@pytest.mark.parametrize("role", [AgentRole.RESEARCHER, AgentRole.ARCHITECT])
async def test_specialist_function_model_reads_then_returns_bound_analysis(role: AgentRole) -> None:
    count = 0

    def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal count
        del messages
        count += 1
        assert [tool.name for tool in info.function_tools] == ["repo_list_files"]
        assert [tool.name for tool in info.output_tools] == ["submit_specialist_report"]
        if count == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "repo_list_files",
                        {"reason": "Observe scope."},
                        tool_call_id="specialist-read",
                    )
                ]
            )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    "submit_specialist_report",
                    _specialist_report(role.value).model_dump(mode="json"),
                    tool_call_id="specialist-output",
                )
            ]
        )

    definition = RuntimeToolDefinition(
        name="repo_list_files",
        description="Read bounded scope.",
        parameters_json_schema={
            "type": "object",
            "properties": {"reason": {"type": "string"}},
            "required": ["reason"],
            "additionalProperties": False,
        },
        side_effect=False,
    )
    catalog = RecordingCatalog((definition,))
    result = await PydanticAIRuntimeAdapter.for_test_model(FunctionModel(model)).invoke(
        _invocation(role, WorkflowStage.IMPLEMENTING),
        RuntimeInvocationServices(configuration=_configuration(), tools=catalog),
    )
    assert result.output == _specialist_report(role.value)
    assert len(catalog.calls) == 1
    assert not catalog.records[0].side_effect_committed
    assert result.usage is not None and result.usage.requests == 2
