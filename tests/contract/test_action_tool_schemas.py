from __future__ import annotations

import json
import re
import traceback
from importlib import resources
from pathlib import Path
from typing import Any

import httpx2
import pytest
from action_tool_fixtures import (
    SENTINEL,
    configuration,
    make_action_tools,
    persist_action_tools,
    sdk_adapter,
    tool_response,
    wire_tools,
)
from pydantic import JsonValue, ValidationError
from pydantic_ai.exceptions import UserError
from pydantic_ai.models import override_allow_model_requests
from pydantic_ai.profiles.openai import OpenAIJsonSchemaTransformer

from agent_fleet.application.proposal_tools import ProposalHashToolCatalog
from agent_fleet.domain.budgets import RuntimeAttemptStatus
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import (
    AgentRole,
    RuntimeToolCall,
    RuntimeToolDefinition,
    RuntimeToolResult,
)
from agent_fleet.domain.security import Redactor, sha256_bytes
from agent_fleet.ports.runtime import RuntimeInvocationServices, RuntimeToolCatalog

_VALID_ARGUMENTS: dict[str, dict[str, JsonValue]] = {
    "repo_list_files": {"reason": "Inspect files."},
    "repo_read_file": {"path": "src/canary_calc/core.py", "reason": "Inspect file."},
    "repo_search_text": {"query": "divide", "reason": "Inspect matches."},
    "workspace_get_diff": {"reason": "Inspect candidate."},
    "workspace_write_file": {"path": "src/canary_calc/core.py", "content": "", "reason": "Repair."},
    "workspace_apply_edit": {
        "path": "src/canary_calc/core.py",
        "expected_sha256": "a" * 64,
        "old": "old",
        "new": "new",
        "expected_matches": 1,
        "reason": "Repair.",
    },
    "workspace_delete_file": {
        "path": "src/canary_calc/core.py",
        "expected_sha256": "a" * 64,
        "reason": "Remove.",
    },
    "run_verification": {"command_id": "python-test", "reason": "Verify."},
    "record_approval_probe": {"record": "approved-once", "reason": "Offline fixture."},
}


@pytest.mark.parametrize("provider", ["openai", "openai-chat"])
@pytest.mark.parametrize("kind", ["gateway", "proposal"])
async def test_actual_sdk_advertises_all_builtin_action_schemas_as_strict(
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    kind: str,
) -> None:
    tools = make_action_tools()
    catalog: RuntimeToolCatalog = (
        tools.catalog
        if kind == "gateway"
        else ProposalHashToolCatalog(Redactor(), visible_paths=frozenset({".fleet/README.md"}))
    )
    originals = {d.name: d.model_dump_json() for d in catalog.definitions}
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return tool_response(
            request,
            [
                (
                    "submit_implementation_report",
                    {
                        "summary": "Offline schema inspection only.",
                        "intended_changed_paths": [],
                        "tests_added_or_changed": [],
                        "criterion_results": [],
                        "evidence_artifact_ids": [],
                        "unresolved_limitations": ["No real project execution."],
                        "verifier_focus": [],
                    },
                )
            ],
        )

    adapter, clients = sdk_adapter(monkeypatch, handler)
    with override_allow_model_requests(True):
        await adapter.invoke(
            tools.invocation,
            RuntimeInvocationServices(
                configuration=configuration(provider),
                tools=catalog,
            ),
        )

    assert len(seen) == 1
    wire = wire_tools(seen[0])
    assert set(originals) == (
        set(_VALID_ARGUMENTS) if kind == "gateway" else {"fleet_content_sha256"}
    )
    assert set(wire) == set(originals) | {"submit_implementation_report"}
    assert json.loads(seen[0].content)["parallel_tool_calls"] is False
    for definition in catalog.definitions:
        function = wire[definition.name]
        assert function["strict"] is True
        schema = function["parameters"]
        original = definition.parameters_json_schema
        properties, required = original["properties"], original["required"]
        assert isinstance(properties, dict) and isinstance(required, list)
        assert all(isinstance(name, str) for name in required)
        assert schema["type"] == "object" and schema["additionalProperties"] is False
        assert set(schema["properties"]) == set(properties)
        assert set(schema["required"]) == set(required) == set(schema["properties"])
        for name, property_schema in properties.items():
            assert isinstance(property_schema, dict)
            target = schema["properties"][name]
            for key, value in property_schema.items():
                if key in {"minLength", "maxLength"}:
                    assert key not in target
                    assert f"{key}={value}" in target["description"]
                elif key not in {"title", "description"}:
                    assert target[key] == value
        assert definition.model_dump_json() == originals[definition.name]
    if kind == "gateway":
        read = wire["repo_read_file"]["parameters"]
        path = read["properties"]["path"]
        assert re.search(path["pattern"], "SRC/CANARY_CALC/CORE.PY")
        assert re.search(path["pattern"], "src/canary_calc/core.py/descendant")
        assert re.search(path["pattern"], "README.md") is None
        assert re.search(path["pattern"], "\u212a/\u017f")
        assert "enum" not in path
        assert set(read["required"]) == {"path", "reason"}
        assert "minLength=1" in path["description"] and "maxLength=4096" in path["description"]
        assert wire["run_verification"]["parameters"]["properties"]["command_id"]["enum"] == [
            "python-test"
        ]
    assert all(client.is_closed for client in clients)
    assert tools.gateway.calls == [] and catalog.records == ()


@pytest.mark.parametrize("provider", ["openai", "openai-chat"])
async def test_target_bound_hash_crosses_real_sdk_round_trip_without_effects(
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
) -> None:
    tools = make_action_tools()
    catalog = ProposalHashToolCatalog(Redactor(), visible_paths=frozenset({".fleet/README.md"}))
    seen: list[httpx2.Request] = []
    content = "Reviewed organization note.\n"

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        if len(seen) == 1:
            return tool_response(
                request,
                [
                    (
                        "fleet_content_sha256",
                        {
                            "operation": "replace",
                            "path": ".fleet/README.md",
                            "content": content,
                        },
                    )
                ],
            )
        assert len(seen) == 2
        body = json.loads(request.content)
        if provider == "openai":
            returns = [item for item in body["input"] if item.get("type") == "function_call_output"]
            assert len(returns) == 1 and returns[0]["call_id"] == "call-1-0"
            returned = json.loads(returns[0]["output"])
        else:
            returns = [item for item in body["messages"] if item["role"] == "tool"]
            assert len(returns) == 1 and returns[0]["tool_call_id"] == "call-1-0"
            returned = json.loads(returns[0]["content"])
        assert returned["content"] == {
            "operation": "replace",
            "path": ".fleet/README.md",
            "sha256": sha256_bytes(content.encode()),
            "size_bytes": len(content.encode()),
        }
        return tool_response(
            request,
            [
                (
                    "submit_implementation_report",
                    {
                        "summary": "Offline pure helper contract only.",
                        "intended_changed_paths": [],
                        "tests_added_or_changed": [],
                        "criterion_results": [],
                        "evidence_artifact_ids": [],
                        "unresolved_limitations": ["No actual project changes or model execution."],
                        "verifier_focus": [],
                    },
                )
            ],
            index=2,
        )

    adapter, clients = sdk_adapter(monkeypatch, handler)
    with override_allow_model_requests(True):
        result = await adapter.invoke(
            tools.invocation,
            RuntimeInvocationServices(
                configuration=configuration(provider),
                tools=catalog,
            ),
        )
    assert len(seen) == 2 and len(catalog.records) == 1
    assert result.usage is not None and result.usage.tool_calls == 1
    assert not catalog.records[0].side_effect_committed
    assert tools.gateway.calls == [] and all(client.is_closed for client in clients)


@pytest.mark.parametrize("provider", ["openai", "openai-chat"])
async def test_invalid_target_in_real_sdk_batch_blocks_every_hash_before_execution(
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
) -> None:
    tools = make_action_tools()
    catalog = ProposalHashToolCatalog(Redactor(), visible_paths=frozenset({".fleet/README.md"}))
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        assert len(seen) == 1, "A rejected target must not trigger a retry"
        return tool_response(
            request,
            [
                (
                    "fleet_content_sha256",
                    {
                        "operation": "replace",
                        "path": ".fleet/README.md",
                        "content": "Allowed note.",
                    },
                ),
                (
                    "fleet_content_sha256",
                    {
                        "operation": "add",
                        "path": "src/calculator.py",
                        "content": "Business source is not an organization target.",
                    },
                ),
            ],
        )

    adapter, clients = sdk_adapter(monkeypatch, handler)
    with override_allow_model_requests(True), pytest.raises(FleetError) as caught:
        await adapter.invoke(
            tools.invocation,
            RuntimeInvocationServices(
                configuration=configuration(provider),
                tools=catalog,
            ),
        )
    assert caught.value.code is ErrorCode.COMMAND_DENIED
    assert len(seen) == 1 and catalog.records == () and catalog._completed == {}
    assert tools.gateway.calls == [] and all(client.is_closed for client in clients)


def test_all_shipped_action_schemas_match_the_reviewed_flat_closed_required_subset() -> None:
    definitions = (
        *make_action_tools().catalog.definitions,
        *ProposalHashToolCatalog(
            Redactor(), visible_paths=frozenset({".fleet/README.md"})
        ).definitions,
    )
    assert len(definitions) == 10
    for definition in definitions:
        schema = definition.parameters_json_schema
        assert schema["type"] == "object" and schema["additionalProperties"] is False
        assert set(schema) <= {"type", "properties", "required", "additionalProperties", "title"}
        properties, required = schema["properties"], schema["required"]
        assert isinstance(properties, dict) and isinstance(required, list)
        assert all(isinstance(name, str) for name in required)
        assert set(properties) == set(required)
        for field in properties.values():
            assert isinstance(field, dict) and field["type"] in {"string", "integer"}
            assert set(field) <= {
                "type",
                "title",
                "description",
                "minLength",
                "maxLength",
                "minimum",
                "maximum",
                "pattern",
                "enum",
            }
            if "enum" in field:
                assert isinstance(field["enum"], list) and field["enum"]


@pytest.mark.parametrize("name", sorted(_VALID_ARGUMENTS))
def test_every_original_catalog_shape_still_enforces_local_required_and_length_limits(
    name: str,
) -> None:
    tools = make_action_tools()
    arguments = _VALID_ARGUMENTS[name]
    tools.catalog.validate(RuntimeToolCall(call_id="valid", name=name, arguments=arguments))
    for invalid in (
        {k: v for k, v in arguments.items() if k != "reason"},
        {**arguments, "reason": "x" * 4097},
        {**arguments, "extra": "untrusted"},
    ):
        with pytest.raises(ValidationError):
            tools.catalog.validate(RuntimeToolCall(call_id="invalid", name=name, arguments=invalid))
    assert tools.catalog.records == () and tools.gateway.calls == []


@pytest.mark.parametrize("role", [AgentRole.ENGINEER, AgentRole.VERIFIER])
def test_no_admitted_commands_omits_verification_tool_without_inventing_an_enum(
    role: AgentRole,
) -> None:
    unavailable = make_action_tools(role=role, sandbox="docker", with_commands=False)
    assert "run_verification" not in {d.name for d in unavailable.catalog.definitions}
    with pytest.raises(FleetError) as caught:
        unavailable.catalog.validate(
            RuntimeToolCall(
                call_id="forged",
                name="run_verification",
                arguments={"command_id": "python-test", "reason": "Try an unadmitted command."},
            )
        )
    assert caught.value.code is ErrorCode.COMMAND_NOT_REVIEWED
    available = make_action_tools(role=role, with_commands=False)
    definition = next(d for d in available.catalog.definitions if d.name == "run_verification")
    properties = definition.parameters_json_schema["properties"]
    assert isinstance(properties, dict)
    command_property = properties["command_id"]
    assert isinstance(command_property, dict) and command_property["enum"] == ["offline-canary"]
    assert available.gateway.calls == unavailable.gateway.calls == []


@pytest.mark.parametrize("role", ["engineer", "verifier"])
def test_role_guidance_requires_exact_command_id_and_independent_evidence(role: str) -> None:
    prompt = (
        resources.files("agent_fleet.adapters.runtime.prompts").joinpath(role + ".md").read_text()
    )
    assert "run_verification" in prompt and "command_id" in prompt
    assert "reason" in prompt and "verification_commands" in prompt
    assert "does not supply command_id" in prompt.replace("\n", " ") or (
        "does not supply command_id" in " ".join(prompt.split())
    )


@pytest.mark.parametrize("provider", ["openai", "openai-chat"])
@pytest.mark.parametrize("hostile_metadata", [False, True], ids=["sdk-error", "hostile-sdk-error"])
async def test_incompatible_strict_schema_fails_before_transport_without_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    hostile_metadata: bool,
) -> None:
    tools = make_action_tools()
    budget = persist_action_tools(tmp_path, tools)
    accounting = budget.begin_attempt(tools.invocation)
    definition = RuntimeToolDefinition(
        name="unsupported_array",
        description="Unsupported fixture.",
        parameters_json_schema={
            "type": "object",
            "properties": {"items": {"type": "array", "items": {}}},
            "required": ["items"],
            "additionalProperties": False,
        },
        side_effect=True,
    )
    original = definition.model_dump_json()
    if hostile_metadata:
        original_transform = OpenAIJsonSchemaTransformer.transform

        def hostile_transform(
            self: OpenAIJsonSchemaTransformer, schema: dict[str, Any]
        ) -> dict[str, Any]:
            if schema.get("type") == "array" and self.strict is True:
                error = UserError(SENTINEL)
                error.add_note(SENTINEL)
                raise error from ValueError(SENTINEL)
            return original_transform(self, schema)

        monkeypatch.setattr(OpenAIJsonSchemaTransformer, "transform", hostile_transform)

    class UnsupportedCatalog:
        definitions = (definition,)
        records = ()

        def validate(self, call: RuntimeToolCall) -> None:
            raise AssertionError("incompatible schema must not reach argument validation")

        async def execute(self, call: RuntimeToolCall) -> RuntimeToolResult:
            raise AssertionError("incompatible schema must not execute")

    sends: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        sends.append(request)
        raise AssertionError("incompatible schema must not reach transport")

    adapter, clients = sdk_adapter(monkeypatch, handler)
    with override_allow_model_requests(True), pytest.raises(FleetError) as caught:
        await adapter.invoke(
            tools.invocation,
            RuntimeInvocationServices(
                configuration=configuration(provider),
                tools=UnsupportedCatalog(),
                accounting=accounting,
            ),
        )
    accounting.finish(RuntimeAttemptStatus.FAILED, error_code=caught.value.code)
    assert caught.value.code is ErrorCode.PROVIDER_FAILED
    assert caught.value.details["runtime_diagnostic"]["category"] == "request_construction"
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert SENTINEL not in "".join(traceback.format_exception(caught.value))
    assert SENTINEL not in str(caught.value.details)
    assert sends == [] and tools.gateway.calls == []
    snapshot = budget.snapshot(tools.run.run_id)
    assert snapshot.tool_calls == 0
    # The real accounting wrapper may reserve before the SDK transforms a schema.
    # Preserve that conservative unknown request; never infer a refund from no send.
    assert snapshot.model_requests == snapshot.unknown_requests == 1
    assert snapshot.reported_total_tokens == 0
    assert snapshot.reserved_tokens == 0
    assert snapshot.outstanding_requests == 0
    assert snapshot.unknown_tokens == configuration(provider).max_total_tokens == 32768
    assert snapshot.completeness == "unknown_requests"
    assert definition.model_dump_json() == original
    assert all(client.is_closed for client in clients)
