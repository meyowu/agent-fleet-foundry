"""Real SDK wire contracts over in-memory transport; never provider qualification."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Never, cast

import httpx2
import pytest
from openai import AsyncOpenAI
from pydantic import ValidationError
from pydantic_ai import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models import override_allow_model_requests
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel
from pydantic_ai.profiles.openai import OpenAIModelProfile
from pydantic_ai.providers.openai import OpenAIProvider

import agent_fleet.adapters.runtime.pydantic_ai as runtime_module
from agent_fleet.adapters.runtime.pydantic_ai import PydanticAIRuntimeAdapter
from agent_fleet.domain.budgets import ModelRequestReservation, RuntimeAttemptStatus
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import (
    AgentInvocation,
    AgentRole,
    RuntimeConfiguration,
    RuntimeProviderMetadata,
    RuntimeToolCall,
    RuntimeToolDefinition,
    RuntimeToolExecutionRecord,
    RuntimeToolOutcome,
    RuntimeToolResult,
    UsageRecord,
    VerifierVerdict,
    WorkflowStage,
)
from agent_fleet.domain.security import Redactor
from agent_fleet.ports.runtime import RuntimeInvocationServices
from agent_fleet.ports.secret_store import SecretInspection, SecretRef, SecretStatus, SecretValue

_PROVIDERS = ("openai", "openai-chat")
_SYNTHETIC_CREDENTIAL = "synthetic-offline-transport-credential"


class _Secrets:
    """Only a fixed test value; never inspect environment or actual credentials."""

    def inspect(self, reference: SecretRef | str) -> SecretInspection:
        return SecretInspection(status=SecretStatus.CONFIGURED)

    def is_configured(self, reference: SecretRef | str) -> bool:
        return True

    def resolve(self, reference: SecretRef | str) -> SecretValue:
        return SecretValue(_SYNTHETIC_CREDENTIAL)


class _Catalog:
    def __init__(self) -> None:
        self.calls: list[RuntimeToolCall] = []
        self._records: list[RuntimeToolExecutionRecord] = []

    @property
    def definitions(self) -> tuple[RuntimeToolDefinition, ...]:
        return (
            RuntimeToolDefinition(
                name="run_verification",
                description="Count one synthetic side effect; no project command runs.",
                parameters_json_schema={
                    "type": "object",
                    "properties": {},
                    "required": [],
                    "additionalProperties": False,
                },
                side_effect=True,
            ),
        )

    @property
    def records(self) -> tuple[RuntimeToolExecutionRecord, ...]:
        return tuple(self._records)

    def validate(self, call: RuntimeToolCall) -> None:
        assert call.name == "run_verification" and call.arguments == {}

    async def execute(self, call: RuntimeToolCall) -> RuntimeToolResult:
        self.validate(call)
        self.calls.append(call)
        self._records.append(
            RuntimeToolExecutionRecord(
                call_id=call.call_id,
                name=call.name,
                outcome=RuntimeToolOutcome.SUCCEEDED,
                side_effect=True,
                side_effect_committed=True,
            )
        )
        return RuntimeToolResult(call_id=call.call_id, name=call.name, content={"synthetic": True})


class _NoAccounting:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def _unexpected(self, operation: str) -> Never:
        self.calls.append(operation)
        raise AssertionError("unsupported strict profile reached accounting")

    @property
    def attempt_id(self) -> Never:
        self._unexpected("attempt_id")

    def reserve_request(self, request_sequence: int, *, requested_tokens: int) -> Never:
        self._unexpected("reserve_request")

    def record_response(self, reservation: ModelRequestReservation, usage: UsageRecord) -> Never:
        self._unexpected("record_response")

    def record_unknown(self, reservation: ModelRequestReservation) -> Never:
        self._unexpected("record_unknown")

    def reserve_tool_batch(self, batch_sequence: int, call_ids: tuple[str, ...]) -> Never:
        self._unexpected("reserve_tool_batch")

    def record_simulated_step(self) -> Never:
        self._unexpected("record_simulated_step")

    def remaining_active_seconds(self) -> Never:
        self._unexpected("remaining_active_seconds")

    def finish(self, status: RuntimeAttemptStatus, *, error_code: ErrorCode | None = None) -> Never:
        self._unexpected("finish")


def _configuration(provider: str, *, retries: int = 3) -> RuntimeConfiguration:
    return RuntimeConfiguration(
        runtime_name="pydantic-ai",
        provider_model=f"{provider}:gpt-5-nano",
        credential_ref="env:FLEET_SYNTHETIC_STRICT_TEST",
        max_requests=6,
        max_tool_calls=4,
        max_total_tokens=32_768,
        timeout_seconds=5,
        max_retries=retries,
    )


def _invocation(
    role: AgentRole = AgentRole.VERIFIER, *, fleet_patch: bool = False
) -> AgentInvocation:
    return AgentInvocation(
        run_id="run_" + "1" * 32,
        task_id="task_" + "2" * 32,
        agent_instance_id="agent_" + "3" * 32,
        role=role,
        stage=(
            WorkflowStage.SCOPING
            if role is AgentRole.COS
            else WorkflowStage.VERIFYING
            if role is AgentRole.VERIFIER
            else WorkflowStage.IMPLEMENTING
        ),
        iteration=0,
        max_steps=6,
        instructions="Synthetic offline transport contract.",
        input={"organization_context": {}} if fleet_patch else {},
    )


def _verdict(*, mapped: bool = True) -> dict[str, Any]:
    # Synthetic references exercise shape only, never actual acceptance evidence.
    return {
        "verdict": "inconclusive",
        "criterion_results": ["Only synthetic transport behavior was observed."],
        "evidence_artifact_ids": [],
        "regressions": [],
        "required_repairs": [],
        "proof_gaps": ["This is not physical verification evidence."],
        "rationale": "No real provider or project command was executed.",
        "structured_criterion_results": (
            [
                {
                    "criterion_id": "bounded-result",
                    "verdict": "inconclusive",
                    "evidence_artifact_ids": [],
                    "command_ids": [],
                    "explanation": "Synthetic evidence cannot establish task completion.",
                }
            ]
            if mapped
            else None
        ),
    }


def _role_payload(role: AgentRole) -> tuple[str, dict[str, Any]]:
    if role is AgentRole.VERIFIER:
        return "submit_verifier_verdict", _verdict()
    if role is AgentRole.COS:
        return "submit_scope_decision", {
            "normalized_goal": "A synthetic bounded result.",
            "change_kind": "read_only",
            "fleet_strategy": "direct",
            "allowed_paths": [],
            "forbidden_paths": [".git", ".fleet"],
            "acceptance_criteria": [
                {"criterion_id": "bounded-result", "description": "Return a bounded result."}
            ],
            "required_evidence": ["control_plane_plan"],
        }
    if role is AgentRole.ENGINEER:
        return "submit_implementation_report", {
            "summary": "Synthetic implementation report.",
            "intended_changed_paths": [],
            "tests_added_or_changed": [],
            "criterion_results": [],
            "evidence_artifact_ids": [],
            "unresolved_limitations": [],
            "verifier_focus": [],
        }
    return "submit_specialist_report", {
        "role": role.value,
        "summary": "Synthetic specialist report.",
        "findings": [],
        "recommendations": [],
        "proof_gaps": [],
    }


class _WireProbe:
    def __init__(self, provider: str, outputs: list[tuple[str, dict[str, Any]]]) -> None:
        self.provider = provider
        self.outputs = outputs
        self.requests: list[dict[str, Any]] = []
        self.http_clients: list[httpx2.AsyncClient] = []
        self.sdk_clients: list[AsyncOpenAI] = []

    async def _handle(self, request: httpx2.Request) -> httpx2.Response:
        expected_path = "/v1/responses" if self.provider == "openai" else "/v1/chat/completions"
        assert request.url.host == "api.openai.com" and request.url.path == expected_path
        body = json.loads(request.content)
        assert _SYNTHETIC_CREDENTIAL not in json.dumps(body)
        self.requests.append(body)
        assert len(self.requests) <= len(self.outputs), "unexpected replay or correction request"
        name, arguments = self.outputs[len(self.requests) - 1]
        sequence = len(self.requests)
        if self.provider == "openai":
            response = {
                "id": f"resp_offline_{sequence}",
                "object": "response",
                "created_at": 1,
                "model": "gpt-5-nano",
                "status": "completed",
                "output": [
                    {
                        "id": f"fc_offline_{sequence}",
                        "type": "function_call",
                        "call_id": f"call_offline_{sequence}",
                        "name": name,
                        "arguments": json.dumps(arguments),
                        "status": "completed",
                    }
                ],
                "usage": {"input_tokens": 5, "output_tokens": 5, "total_tokens": 10},
            }
        else:
            response = {
                "id": f"chatcmpl_offline_{sequence}",
                "object": "chat.completion",
                "created": 1,
                "model": "gpt-5-nano",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": f"call_offline_{sequence}",
                                    "type": "function",
                                    "function": {"name": name, "arguments": json.dumps(arguments)},
                                }
                            ],
                        },
                    }
                ],
                "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10},
            }
        return httpx2.Response(200, json=response, request=request)

    def transport_factory(self, **kwargs: Any) -> httpx2.AsyncClient:
        client = httpx2.AsyncClient(transport=httpx2.MockTransport(self._handle), **kwargs)
        self.http_clients.append(client)
        return client

    def client_factory(self, **kwargs: Any) -> AsyncOpenAI:
        client = AsyncOpenAI(**kwargs)
        self.sdk_clients.append(client)
        return client

    def runtime(self, monkeypatch: pytest.MonkeyPatch) -> PydanticAIRuntimeAdapter:
        monkeypatch.setattr(runtime_module, "DefaultAsyncHttpxClient", self.transport_factory)
        monkeypatch.setattr(runtime_module, "AsyncOpenAI", self.client_factory)
        return PydanticAIRuntimeAdapter(_Secrets(), Redactor())

    def tools(self, index: int = 0) -> dict[str, dict[str, Any]]:
        tools = self.requests[index]["tools"]
        definitions = [item if self.provider == "openai" else item["function"] for item in tools]
        return {item["name"]: item for item in definitions}

    def assert_closed(self) -> None:
        assert len(self.http_clients) == len(self.sdk_clients) == 1
        assert self.http_clients[0].is_closed and self.sdk_clients[0].is_closed()


@pytest.mark.parametrize("provider", _PROVIDERS)
@pytest.mark.parametrize("mapped", [True, False])
async def test_production_verifier_wire_is_strict_and_preserves_nullable_semantics(
    monkeypatch: pytest.MonkeyPatch, provider: str, mapped: bool
) -> None:
    payload = _verdict(mapped=mapped)
    probe = _WireProbe(provider, [("submit_verifier_verdict", payload)])
    original = VerifierVerdict.model_json_schema()
    with override_allow_model_requests(True):
        result = await probe.runtime(monkeypatch).invoke(
            _invocation(),
            RuntimeInvocationServices(configuration=_configuration(provider), tools=_Catalog()),
        )
    assert result.output == VerifierVerdict.model_validate(payload)
    assert len(probe.requests) == 1
    definition = probe.tools()["submit_verifier_verdict"]
    assert definition["strict"] is True
    schema = definition["parameters"]
    assert set(schema["required"]) == set(original["properties"])
    assert len(schema["required"]) == 8 and schema["additionalProperties"] is False
    assert schema["properties"]["criterion_results"]["items"]["type"] == "string"
    assert schema["$defs"]["Verdict"]["enum"] == ["pass", "fail", "inconclusive"]
    criterion = schema["$defs"]["CriterionResult"]
    assert criterion["additionalProperties"] is False
    assert set(criterion["required"]) == set(criterion["properties"])
    structured = schema["properties"]["structured_criterion_results"]
    assert "default" not in structured
    assert {item["type"] for item in structured["anyOf"]} == {"array", "null"}
    assert "minLength" not in schema["properties"]["rationale"]
    assert "minLength=1" in schema["properties"]["rationale"]["description"]
    assert probe.tools()["run_verification"]["strict"] is True
    assert probe.requests[0]["parallel_tool_calls"] is False
    assert set(probe.tools()) == {"submit_verifier_verdict", "run_verification"}
    assert VerifierVerdict.model_json_schema() == original
    assert "structured_criterion_results" not in original["required"]
    probe.assert_closed()


@pytest.mark.parametrize("provider", _PROVIDERS)
async def test_explicit_model_override_retains_old_actual_sdk_wire_despite_openai_metadata(
    provider: str,
) -> None:
    payload = _verdict(mapped=False)
    del payload["structured_criterion_results"]
    probe = _WireProbe(provider, [("submit_verifier_verdict", payload)])
    http_client = probe.transport_factory(trust_env=False, follow_redirects=False)
    client = probe.client_factory(
        api_key=_SYNTHETIC_CREDENTIAL, http_client=http_client, max_retries=0
    )
    model_type = OpenAIResponsesModel if provider == "openai" else OpenAIChatModel
    model = model_type("gpt-5-nano", provider=OpenAIProvider(openai_client=client))
    adapter = PydanticAIRuntimeAdapter.for_test_model(
        model, metadata=RuntimeProviderMetadata(provider="openai", model="openai:gpt-5-nano")
    )
    try:
        with override_allow_model_requests(True):
            result = await adapter.invoke(
                _invocation(),
                RuntimeInvocationServices(configuration=_configuration(provider), tools=_Catalog()),
            )
        assert isinstance(result.output, VerifierVerdict)
        assert result.output.structured_criterion_results is None
        definition = probe.tools()["submit_verifier_verdict"]
        assert definition.get("strict", False) is False
        assert "structured_criterion_results" not in definition["parameters"]["required"]
        assert (
            definition["parameters"]["properties"]["structured_criterion_results"]["default"]
            is None
        )
    finally:
        await client.close()
        await http_client.aclose()
    probe.assert_closed()


@pytest.mark.parametrize("provider", _PROVIDERS)
@pytest.mark.parametrize(
    "role", [AgentRole.COS, AgentRole.ENGINEER, AgentRole.RESEARCHER, AgentRole.ARCHITECT]
)
async def test_other_production_output_roles_and_fleet_patch_are_not_made_strict(
    monkeypatch: pytest.MonkeyPatch, provider: str, role: AgentRole
) -> None:
    name, payload = _role_payload(role)
    probe = _WireProbe(provider, [(name, payload)])
    with override_allow_model_requests(True):
        await probe.runtime(monkeypatch).invoke(
            _invocation(role, fleet_patch=role is AgentRole.COS),
            RuntimeInvocationServices(configuration=_configuration(provider), tools=_Catalog()),
        )
    assert probe.tools()[name].get("strict", False) is False
    assert probe.tools()["run_verification"]["strict"] is True
    if role is AgentRole.COS:
        assert probe.tools()["submit_fleet_patch"].get("strict", False) is False
    probe.assert_closed()


@pytest.mark.parametrize("provider", _PROVIDERS)
@pytest.mark.parametrize("support", [False, None, 0, "true"])
async def test_unsupported_production_profile_has_no_dispatch_accounting_or_effects_and_closes(
    monkeypatch: pytest.MonkeyPatch, provider: str, support: object
) -> None:
    probe = _WireProbe(provider, [])
    adapter = probe.runtime(monkeypatch)
    model_type = OpenAIResponsesModel if provider == "openai" else OpenAIChatModel

    def model_factory(*args: Any, **kwargs: Any) -> Any:
        return model_type(
            *args,
            **kwargs,
            profile=cast(OpenAIModelProfile, {"openai_supports_strict_tool_definition": support}),
        )

    monkeypatch.setattr(runtime_module, model_type.__name__, model_factory)
    accounting, catalog = _NoAccounting(), _Catalog()
    with override_allow_model_requests(True), pytest.raises(FleetError) as caught:
        await adapter.invoke(
            _invocation(),
            RuntimeInvocationServices(
                configuration=_configuration(provider), tools=catalog, accounting=accounting
            ),
        )
    assert caught.value.code is ErrorCode.RUNTIME_CAPABILITY_MISSING
    assert not probe.requests and not accounting.calls and not catalog.calls and not catalog.records
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    probe.assert_closed()


@pytest.mark.parametrize("provider", _PROVIDERS)
@pytest.mark.parametrize(
    ("malformation", "field", "issue"),
    [
        ("uppercase", "verdict", "enum"),
        ("missing", "rationale", "missing"),
        ("object", "criterion_results", "type"),
        ("empty", "rationale", "length"),
        ("long", "rationale", "length"),
    ],
)
async def test_invalid_strict_provider_output_after_effect_is_locally_rejected_without_replay(
    monkeypatch: pytest.MonkeyPatch, provider: str, malformation: str, field: str, issue: str
) -> None:
    payload = _verdict()
    if malformation == "uppercase":
        payload["verdict"] = "PASS"
    elif malformation == "missing":
        del payload["rationale"]
    elif malformation == "object":
        payload["criterion_results"] = [{"criterion_id": "bounded-result"}]
        del payload["structured_criterion_results"]
    else:
        payload["rationale"] = "" if malformation == "empty" else "x" * 8193
    probe = _WireProbe(provider, [("run_verification", {}), ("submit_verifier_verdict", payload)])
    catalog = _Catalog()
    with override_allow_model_requests(True), pytest.raises(FleetError) as caught:
        await probe.runtime(monkeypatch).invoke(
            _invocation(),
            RuntimeInvocationServices(configuration=_configuration(provider), tools=catalog),
        )
    assert caught.value.code is ErrorCode.RUNTIME_OUTPUT_INVALID
    assert len(probe.requests) == 2 and len(catalog.calls) == len(catalog.records) == 1
    assert catalog.records[0].side_effect_committed is True
    assert all(
        probe.tools(index)["submit_verifier_verdict"]["strict"] is True for index in range(2)
    )
    assert caught.value.details["runtime_diagnostic"]["validation_issues"] == [
        {"field": field, "issue": issue}
    ]
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    probe.assert_closed()


@pytest.mark.parametrize("provider", _PROVIDERS)
async def test_valid_mapped_output_after_one_effect_is_unchanged(
    monkeypatch: pytest.MonkeyPatch, provider: str
) -> None:
    payload = _verdict()
    probe = _WireProbe(provider, [("run_verification", {}), ("submit_verifier_verdict", payload)])
    catalog = _Catalog()
    with override_allow_model_requests(True):
        result = await probe.runtime(monkeypatch).invoke(
            _invocation(),
            RuntimeInvocationServices(configuration=_configuration(provider), tools=catalog),
        )
    assert result.output == VerifierVerdict.model_validate(payload)
    assert len(probe.requests) == 2 and len(catalog.calls) == 1
    probe.assert_closed()


def test_public_model_keeps_omitted_null_and_local_string_validation_semantics() -> None:
    payload = _verdict(mapped=False)
    del payload["structured_criterion_results"]
    assert VerifierVerdict.model_validate(payload).structured_criterion_results is None
    payload["structured_criterion_results"] = None
    assert VerifierVerdict.model_validate(payload).structured_criterion_results is None
    for rationale in ("", "x" * 8193):
        with pytest.raises(ValidationError):
            VerifierVerdict.model_validate({**payload, "rationale": rationale})


@pytest.mark.parametrize("provider", _PROVIDERS)
async def test_one_pre_effect_correction_remains_available(
    monkeypatch: pytest.MonkeyPatch, provider: str
) -> None:
    payload = _verdict()
    probe = _WireProbe(
        provider,
        [
            ("submit_verifier_verdict", {**payload, "verdict": "PASS"}),
            ("submit_verifier_verdict", payload),
        ],
    )
    catalog = _Catalog()
    with override_allow_model_requests(True):
        result = await probe.runtime(monkeypatch).invoke(
            _invocation(),
            RuntimeInvocationServices(
                configuration=_configuration(provider, retries=1), tools=catalog
            ),
        )
    assert result.output == VerifierVerdict.model_validate(payload)
    assert len(probe.requests) == 2 and not catalog.calls and not catalog.records
    assert all(
        probe.tools(index)["submit_verifier_verdict"]["strict"] is True for index in range(2)
    )
    probe.assert_closed()


@pytest.mark.parametrize("provider", _PROVIDERS)
async def test_only_exact_trusted_verifier_output_identity_enables_strictness(
    monkeypatch: pytest.MonkeyPatch, provider: str
) -> None:
    class OtherVerdict(VerifierVerdict):
        pass

    monkeypatch.setitem(
        runtime_module._OUTPUT_BY_ROLE,
        AgentRole.VERIFIER.value,
        (OtherVerdict, "submit_verifier_verdict", "verifier.md"),
    )
    probe = _WireProbe(provider, [("submit_verifier_verdict", _verdict())])
    with override_allow_model_requests(True):
        await probe.runtime(monkeypatch).invoke(
            _invocation(),
            RuntimeInvocationServices(configuration=_configuration(provider), tools=_Catalog()),
        )
    assert probe.tools()["submit_verifier_verdict"].get("strict", False) is False
    probe.assert_closed()


@pytest.mark.parametrize("provider", ["anthropic", "google"])
async def test_other_provider_construction_branches_do_not_enable_openai_policy(
    monkeypatch: pytest.MonkeyPatch, provider: str
) -> None:
    observed: list[bool | None] = []

    async def output(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        observed.append(info.output_tools[0].strict)
        return ModelResponse(
            parts=[ToolCallPart("submit_verifier_verdict", _verdict(), tool_call_id="synthetic")]
        )

    @asynccontextmanager
    async def open_synthetic_model(*args: Any, **kwargs: Any) -> AsyncIterator[FunctionModel]:
        yield FunctionModel(
            output, profile=OpenAIModelProfile(openai_supports_strict_tool_definition=False)
        )

    monkeypatch.setattr(runtime_module, f"open_{provider}_model", open_synthetic_model)

    def no_openai(*args: object, **kwargs: object) -> Never:
        raise AssertionError("other providers must not construct OpenAI clients")

    monkeypatch.setattr(runtime_module, "AsyncOpenAI", no_openai)
    result = await PydanticAIRuntimeAdapter(_Secrets(), Redactor()).invoke(
        _invocation(),
        RuntimeInvocationServices(configuration=_configuration(provider), tools=_Catalog()),
    )
    assert result.output == VerifierVerdict.model_validate(_verdict())
    assert observed == [None]
