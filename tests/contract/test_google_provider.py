"""Pinned real Google SDK and PydanticAI on an exclusively offline transport."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import socket
import warnings
from pathlib import Path
from typing import Any

import httpx2
import pytest
from action_tool_fixtures import make_action_tools, persist_action_tools
from google_provider_fixtures import (
    CONFIG,
    KEY,
    MODEL,
    install_transport,
    output_call,
    response_body,
    terminals,
)
from pydantic_ai.models import override_allow_model_requests
from test_pydantic_ai_runtime import RecordingCatalog
from test_runtime_budgets import _ledger
from test_runtime_conformance import expected_output, request

import agent_fleet.adapters.runtime.google_provider as provider_module
from agent_fleet.adapters.runtime.google_provider import open_google_model, require_google_policy
from agent_fleet.adapters.runtime.pydantic_ai import PydanticAIRuntimeAdapter
from agent_fleet.domain.budgets import RunBudgetLimits, RuntimeAttemptStatus
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import AgentRole, FleetPatch, RuntimeToolDefinition
from agent_fleet.domain.security import Redactor, sha256_bytes
from agent_fleet.ports.runtime import EMPTY_RUNTIME_TOOL_CATALOG, RuntimeInvocationServices


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*args: object, **kwargs: object) -> None:
        raise AssertionError("Google contracts cannot open sockets")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket, "create_connection", denied)


@pytest.mark.parametrize(
    ("kind", "custom"),
    [(kind, False) for kind in AgentRole]
    + [(kind, True) for kind in AgentRole if kind is not AgentRole.COS],
)
async def test_real_sdk_role_output(
    monkeypatch: pytest.MonkeyPatch, kind: AgentRole, custom: bool
) -> None:
    role = "custom-" + kind.value if custom else kind.value
    output = expected_output(kind, role)
    sent: list[httpx2.Request] = []

    def respond(received: httpx2.Request) -> httpx2.Response:
        sent.append(received)
        return httpx2.Response(200, json=response_body([output_call(received, output)]))

    sync, asynchronous = install_transport(monkeypatch, respond)
    with override_allow_model_requests(True):
        async with open_google_model(
            MODEL, KEY, Redactor([KEY]), timeout_seconds=2, terminal_outputs=terminals(kind)
        ) as model:
            result = await PydanticAIRuntimeAdapter.for_test_model(model).invoke(
                request(role),
                RuntimeInvocationServices(
                    configuration=CONFIG,
                    tools=EMPTY_RUNTIME_TOOL_CATALOG,
                    execution_kind=kind if custom else None,
                ),
            )
    assert result.output == output
    assert result.usage is not None and result.usage.total_tokens == 15
    assert len(sent) == len(sync) == len(asynchronous) == 1
    assert all(client.is_closed for client in [*sync, *asynchronous])
    assert (
        str(sent[0].url)
        == f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
    )
    assert sent[0].headers["x-goog-api-key"] == KEY
    assert "cookie" not in sent[0].headers and "authorization" not in sent[0].headers
    body: dict[str, Any] = json.loads(sent[0].content)
    assert body["generationConfig"]["responseModalities"] == ["TEXT"]
    assert KEY.encode() not in sent[0].content


async def test_actual_sdk_preserves_read_pattern_in_json_schema_declaration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tools = make_action_tools()
    seen: list[dict[str, Any]] = []

    def respond(received: httpx2.Request) -> httpx2.Response:
        body = json.loads(received.content)
        seen.append(body)
        read = next(
            declaration
            for group in body["tools"]
            for declaration in group["functionDeclarations"]
            if declaration["name"] == "repo_read_file"
        )
        assert "strict" not in read and "parameters" not in read
        schema = read["parameters_json_schema"]
        path = schema["properties"]["path"]
        original = next(d for d in tools.catalog.definitions if d.name == "repo_read_file")
        properties = original.parameters_json_schema["properties"]
        assert isinstance(properties, dict) and isinstance(properties["path"], dict)
        assert path["pattern"] == properties["path"]["pattern"]
        assert re.search(path["pattern"], "SRC/CANARY_CALC/CORE.PY")
        assert re.search(path["pattern"], "README.md") is None
        assert re.search(path["pattern"], "\u212a/\u017f")
        assert schema["additionalProperties"] is False and set(schema["required"]) == {
            "path",
            "reason",
        }
        assert path["minLength"] == 1 and path["maxLength"] == 4096
        return httpx2.Response(
            200,
            json=response_body(
                [output_call(received, expected_output(AgentRole.ENGINEER, "engineer"))]
            ),
        )

    sync, clients = install_transport(monkeypatch, respond)
    with override_allow_model_requests(True):
        async with open_google_model(
            MODEL,
            KEY,
            Redactor([KEY]),
            timeout_seconds=2,
            terminal_outputs=terminals(AgentRole.ENGINEER),
        ) as model:
            await PydanticAIRuntimeAdapter.for_test_model(model).invoke(
                tools.invocation,
                RuntimeInvocationServices(configuration=CONFIG, tools=tools.catalog),
            )
    assert len(seen) == 1 and tools.gateway.calls == [] and tools.catalog.records == ()
    assert all(client.is_closed for client in [*sync, *clients])


@pytest.mark.parametrize("signature", [False, True])
async def test_three_turn_local_loop_and_stateless_cookies(
    monkeypatch: pytest.MonkeyPatch, signature: bool
) -> None:
    from google.genai.models import AsyncModels

    original_generate = AsyncModels.generate_content
    sdk_entries = 0

    async def observe_sdk(self: Any, **kwargs: Any) -> Any:
        nonlocal sdk_entries
        sdk_entries += 1
        assert kwargs["config"]["automatic_function_calling"] == {"disable": True}
        assert all(
            type(tool) is dict and set(tool) == {"function_declarations"}
            for tool in kwargs["config"]["tools"]
        )
        return await original_generate(self, **kwargs)

    monkeypatch.setattr(AsyncModels, "generate_content", observe_sdk)
    catalog = RecordingCatalog(
        (
            RuntimeToolDefinition(
                name="repo_list_files",
                description="Bounded read.",
                parameters_json_schema={
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            ),
        )
    )
    sent: list[dict[str, Any]] = []

    def respond(received: httpx2.Request) -> httpx2.Response:
        body = json.loads(received.content)
        sent.append(body)
        assert "cookie" not in received.headers
        assert len(catalog.calls) == len(sent) - 1
        if len(sent) < 3:
            parts: list[dict[str, Any]] = [
                {"functionCall": {"name": "repo_list_files", "args": {}}}
            ]
            if signature:
                parts[0]["thoughtSignature"] = "b3BhcXVl"
        else:
            assert "functionResponse" in received.content.decode()
            parts = [output_call(received, expected_output(AgentRole.ENGINEER, "engineer"))]
        return httpx2.Response(
            200, headers={"set-cookie": "unsafe=offline; Path=/; Secure"}, json=response_body(parts)
        )

    sync, clients = install_transport(monkeypatch, respond)
    with override_allow_model_requests(True):
        async with open_google_model(
            MODEL,
            KEY,
            Redactor([KEY]),
            timeout_seconds=2,
            terminal_outputs=terminals(AgentRole.ENGINEER),
        ) as model:
            result = await PydanticAIRuntimeAdapter.for_test_model(model).invoke(
                request("engineer"), RuntimeInvocationServices(configuration=CONFIG, tools=catalog)
            )
    assert (
        result.usage is not None and result.usage.requests == 3 and result.usage.total_tokens == 45
    )
    assert len({call.call_id for call in catalog.calls}) == 2
    assert sdk_entries == 3
    assert all(client.is_closed and not list(client.cookies.jar) for client in [*sync, *clients])


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_usage",
        "missing_prompt",
        "bool_prompt",
        "str_output",
        "negative_total",
        "wrong_total",
        "wrong_model",
        "missing_model",
        "two_candidates",
        "native",
        "grounding",
        "bad_index",
        "bad_finish",
        "nested_bool",
        "nested_string",
        "nested_secret",
        "null_optional",
        "unknown_usage",
        "bad_signature",
        "malformed_terminal",
        "secret_body",
        "duplicate_json",
        "nonfinite",
        "oversized",
    ],
)
async def test_raw_wire_rejection_precedes_effects_and_keeps_unknown_accounting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    ledger = _ledger(tmp_path, RunBudgetLimits())
    accounting = ledger.store.begin_attempt(ledger.request)
    catalog = RecordingCatalog(
        (
            RuntimeToolDefinition(
                name="repo_list_files",
                description="Bounded read.",
                parameters_json_schema={"type": "object", "properties": {}},
            ),
        )
    )
    sends = 0

    def respond(received: httpx2.Request) -> httpx2.Response:
        nonlocal sends
        sends += 1
        body = response_body([{"functionCall": {"name": "repo_list_files", "args": {}}}])
        usage = body["usageMetadata"]
        if mutation == "missing_usage":
            del body["usageMetadata"]
        elif mutation == "missing_prompt":
            del usage["promptTokenCount"]
        elif mutation == "bool_prompt":
            usage["promptTokenCount"] = True
        elif mutation == "str_output":
            usage["candidatesTokenCount"] = "5"
        elif mutation == "negative_total":
            usage["totalTokenCount"] = -1
        elif mutation == "wrong_total":
            usage["totalTokenCount"] = 16
        elif mutation == "wrong_model":
            body["modelVersion"] = "other-model"
        elif mutation == "missing_model":
            del body["modelVersion"]
        elif mutation == "two_candidates":
            body["candidates"] *= 2
        elif mutation == "native":
            body["candidates"][0]["content"]["parts"] = [
                {"executableCode": {"language": "PYTHON", "code": "forbidden"}}
            ]
        elif mutation == "grounding":
            body["candidates"][0]["groundingMetadata"] = {}
        elif mutation == "bad_index":
            body["candidates"][0]["index"] = False
        elif mutation == "bad_finish":
            body["candidates"][0]["finishReason"] = "MAX_TOKENS"
        elif mutation.startswith("nested_"):
            usage["promptTokensDetails"] = [
                {
                    "modality": "TEXT",
                    "tokenCount": {
                        "nested_bool": True,
                        "nested_string": "10",
                        "nested_secret": KEY,
                    }[mutation],
                }
            ]
        elif mutation == "null_optional":
            usage["thoughtsTokenCount"] = None
        elif mutation == "unknown_usage":
            usage["unsupported"] = KEY
        elif mutation == "bad_signature":
            body["candidates"][0]["content"]["parts"][0]["thoughtSignature"] = "not base64"
        elif mutation == "malformed_terminal":
            part = output_call(received, expected_output(AgentRole.COS, "cos"))
            part["functionCall"]["args"]["fleet_strategy"] = "engineer_verifier"
            part["functionCall"]["args"]["writer_assignments"] = [
                {"role": "verifier", "allowed_paths": ["src"]}
            ]
            body["candidates"][0]["content"]["parts"].append(part)
        elif mutation == "secret_body":
            body["candidates"][0]["content"]["parts"] = [{"text": KEY}]
        encoded = json.dumps(body).encode()
        if mutation == "duplicate_json":
            encoded = encoded.replace(
                b'"promptTokenCount": 10', b'"promptTokenCount": 10, "promptTokenCount": 10'
            )
        elif mutation == "nonfinite":
            encoded = encoded.replace(b'"promptTokenCount": 10', b'"promptTokenCount": 1e999')
        elif mutation == "oversized":
            encoded += b" " * (2 * 1024 * 1024)
        return httpx2.Response(200, content=encoded)

    sync, clients = install_transport(monkeypatch, respond)
    with warnings.catch_warnings(record=True) as observed, override_allow_model_requests(True):
        warnings.simplefilter("always", UserWarning)
        with pytest.raises(FleetError) as captured:
            async with open_google_model(
                MODEL,
                KEY,
                Redactor([KEY]),
                timeout_seconds=2,
                terminal_outputs=terminals(AgentRole.COS),
            ) as model:
                await PydanticAIRuntimeAdapter.for_test_model(
                    model, redactor=Redactor([KEY])
                ).invoke(
                    ledger.request,
                    RuntimeInvocationServices(
                        configuration=CONFIG, tools=catalog, accounting=accounting
                    ),
                )
    accounting.finish(RuntimeAttemptStatus.FAILED, error_code=captured.value.code)
    snapshot = ledger.reopen().snapshot(ledger.run.run_id)
    assert snapshot.model_requests == snapshot.unknown_requests == sends == 1
    assert snapshot.outstanding_requests == snapshot.reserved_tokens == snapshot.tool_calls == 0
    assert snapshot.reported_total_tokens == 0 and snapshot.unknown_tokens > 0
    assert catalog.calls == []
    assert all(client.is_closed for client in [*sync, *clients])
    assert not any(issubclass(item.category, UserWarning) for item in observed)
    assert KEY not in str(captured.value) and KEY not in str(captured.value.details)
    assert captured.value.__cause__ is captured.value.__context__ is None


@pytest.mark.parametrize("extra", [False, True])
async def test_optional_usage_formula_is_not_cache_double_counting(
    monkeypatch: pytest.MonkeyPatch, extra: bool
) -> None:
    def respond(received: httpx2.Request) -> httpx2.Response:
        body = response_body([output_call(received, expected_output(AgentRole.COS, "cos"))])
        if extra:
            body["usageMetadata"].update(
                {
                    "thoughtsTokenCount": 3,
                    "toolUsePromptTokenCount": 2,
                    "totalTokenCount": 20,
                    "cachedContentTokenCount": 4,
                    "promptTokensDetails": [{"modality": "TEXT", "tokenCount": 10}],
                    "cacheTokensDetails": [{"modality": "TEXT", "tokenCount": 4}],
                    "candidatesTokensDetails": [{"modality": "TEXT", "tokenCount": 5}],
                    "toolUsePromptTokensDetails": [{"modality": "TEXT", "tokenCount": 2}],
                }
            )
        return httpx2.Response(200, json=body)

    install_transport(monkeypatch, respond)
    with override_allow_model_requests(True):
        async with open_google_model(
            MODEL,
            KEY,
            Redactor([KEY]),
            timeout_seconds=2,
            terminal_outputs=terminals(AgentRole.COS),
        ) as model:
            result = await PydanticAIRuntimeAdapter.for_test_model(model).invoke(
                request("cos"),
                RuntimeInvocationServices(configuration=CONFIG, tools=EMPTY_RUNTIME_TOOL_CATALOG),
            )
    assert result.usage is not None
    assert result.usage.input_tokens == (12 if extra else 10)
    assert result.usage.output_tokens == (8 if extra else 5)
    assert result.usage.total_tokens == (20 if extra else 15)


@pytest.mark.parametrize("name", provider_module._ENV_DENIED)
def test_replay_and_logging_env_are_rejected_without_sdk_or_secret(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    monkeypatch.setenv(name, "synthetic-ignored")
    with pytest.raises(FleetError):
        require_google_policy()


@pytest.mark.parametrize(
    "name",
    [
        "google",
        "google.genai.models",
        "google_genai",
        "google_genai.models",
        "google_genai._api_client",
        "httpx2",
        "httpcore2.connection",
    ],
)
def test_verbose_logging_is_rejected_without_mutation(name: str) -> None:
    logger = logging.getLogger(name)
    previous = logger.level
    try:
        logger.setLevel(logging.INFO)
        with pytest.raises(FleetError):
            require_google_policy()
        assert logger.level == logging.INFO
    finally:
        logger.setLevel(previous)


async def test_explicit_sdk_clients_ignore_ambient_auth_proxy_endpoint_and_ssl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ssl

    import google.auth
    import google.genai._api_client as api_client
    import google.genai.client as sdk_client

    sends: list[httpx2.Request] = []

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("Ambient SDK client/auth/replay path was used")

    monkeypatch.setattr(google.auth, "default", forbidden)
    monkeypatch.setattr(sdk_client, "ReplayApiClient", forbidden)
    monkeypatch.setattr(api_client, "SyncHttpxClient", forbidden)
    monkeypatch.setattr(api_client, "AsyncHttpxClient", forbidden)
    for name in (
        "GOOGLE_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_CLOUD_PROJECT",
        "GOOGLE_CLOUD_LOCATION",
        "GOOGLE_GENAI_USE_ENTERPRISE",
        "GOOGLE_GENAI_USE_VERTEXAI",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "GOOGLE_GEMINI_BASE_URL",
        "GOOGLE_VERTEX_BASE_URL",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "REQUESTS_CA_BUNDLE",
        "GOOGLE_API_USE_CLIENT_CERTIFICATE",
    ):
        monkeypatch.setenv(name, "/synthetic/ambient-must-not-be-read")
    original_client = sdk_client.Client
    created: list[Any] = []

    def inspect_client(**kwargs: Any) -> Any:
        assert kwargs["api_key"] == KEY
        assert kwargs["enterprise"] is kwargs["vertexai"] is False
        assert kwargs["debug_config"].model_dump() == {
            "client_mode": None,
            "replays_directory": None,
            "replay_id": None,
        }
        options = kwargs["http_options"]
        assert options.base_url == "https://generativelanguage.googleapis.com"
        assert options.api_version == "v1beta" and options.retry_options.attempts == 1
        context = options.client_args["verify"]
        assert isinstance(context, ssl.SSLContext)
        assert options.async_client_args["verify"] is options.async_client_args["ssl"] is context
        result = original_client(**kwargs)
        created.append(result)
        return result

    monkeypatch.setattr(sdk_client, "Client", inspect_client)
    # genai re-exports the constructor; patch that reference without replacing the SDK.
    from google import genai

    monkeypatch.setattr(genai, "Client", inspect_client)

    def respond(received: httpx2.Request) -> httpx2.Response:
        sends.append(received)
        assert received.headers["x-goog-api-key"] == KEY
        assert "ambient-must-not-be-read" not in received.content.decode()
        assert "ambient-must-not-be-read" not in str(received.headers)
        return httpx2.Response(
            200, json=response_body([output_call(received, expected_output(AgentRole.COS, "cos"))])
        )

    sync, clients = install_transport(monkeypatch, respond)
    with override_allow_model_requests(True):
        async with open_google_model(
            MODEL,
            KEY,
            Redactor([KEY]),
            timeout_seconds=2,
            terminal_outputs=terminals(AgentRole.COS),
        ) as model:
            await PydanticAIRuntimeAdapter.for_test_model(model).invoke(
                request("cos"),
                RuntimeInvocationServices(configuration=CONFIG, tools=EMPTY_RUNTIME_TOOL_CATALOG),
            )
            with pytest.raises(FleetError):
                created[0].models.generate_content(model=MODEL, contents="sync denied")
    assert len(sends) == len(sync) == len(clients) == len(created) == 1
    assert all(client.is_closed for client in [*sync, *clients])


@pytest.mark.parametrize("status", [302, 401, 403, 429, 500, 503])
async def test_http_error_has_safe_status_and_no_implicit_retry(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    sends: list[httpx2.Request] = []

    def respond(received: httpx2.Request) -> httpx2.Response:
        sends.append(received)
        return httpx2.Response(
            status,
            headers={"location": "https://forbidden.invalid/"},
            json={"error": {"code": status, "message": KEY, "status": KEY}},
        )

    sync, clients = install_transport(monkeypatch, respond)
    with override_allow_model_requests(True), pytest.raises(FleetError) as captured:
        async with open_google_model(
            MODEL,
            KEY,
            Redactor([KEY]),
            timeout_seconds=2,
            terminal_outputs=terminals(AgentRole.COS),
        ) as model:
            # Exercise the public Runtime boundary too: PydanticAI's graph can
            # attach a safe ExceptionGroup even after the raw SDK error is gone.
            await PydanticAIRuntimeAdapter.for_test_model(model).invoke(
                request("cos"),
                RuntimeInvocationServices(configuration=CONFIG, tools=EMPTY_RUNTIME_TOOL_CATALOG),
            )
    assert len(sends) == 1
    assert captured.value.details["runtime_diagnostic"]["http_status"] == status
    assert captured.value.details["runtime_diagnostic"]["cause_category"] != "response_policy"
    assert captured.value.__context__ is captured.value.__cause__ is None
    assert KEY not in str(captured.value) and KEY not in str(captured.value.details)
    assert all(client.is_closed for client in [*sync, *clients])


@pytest.mark.parametrize("fault", ["missing", "wrong", "extra", "oversized"])
async def test_whole_action_batch_uses_original_gateway_validators_before_any_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    tools = make_action_tools(role=AgentRole.ENGINEER)
    store = persist_action_tools(tmp_path, tools)
    accounting = store.begin_attempt(tools.invocation)
    original_schemas = [
        definition.model_dump(mode="json") for definition in tools.catalog.definitions
    ]
    bad: dict[str, Any] = {"command_id": "python-test", "reason": "Offline verifier check."}
    if fault == "missing":
        del bad["command_id"]
    elif fault == "wrong":
        bad["command_id"] = "unreviewed-command"
    elif fault == "extra":
        bad["extra"] = "not permitted"
    else:
        bad["reason"] = "x" * 20001
    sends = 0

    def respond(received: httpx2.Request) -> httpx2.Response:
        nonlocal sends
        sends += 1
        return httpx2.Response(
            200,
            json=response_body(
                [
                    {
                        "functionCall": {
                            "name": "repo_list_files",
                            "args": {"reason": "List bounded files."},
                        }
                    },
                    {"functionCall": {"name": "run_verification", "args": bad}},
                ]
            ),
        )

    install_transport(monkeypatch, respond)
    with override_allow_model_requests(True), pytest.raises(FleetError) as captured:
        async with open_google_model(
            MODEL,
            KEY,
            Redactor([KEY]),
            timeout_seconds=2,
            terminal_outputs=terminals(AgentRole.ENGINEER),
        ) as model:
            await PydanticAIRuntimeAdapter.for_test_model(model).invoke(
                tools.invocation,
                RuntimeInvocationServices(
                    configuration=CONFIG, tools=tools.catalog, accounting=accounting
                ),
            )
    accounting.finish(RuntimeAttemptStatus.FAILED, error_code=captured.value.code)
    snapshot = store.snapshot(tools.run.run_id)
    assert sends == 1 and snapshot.model_requests == 1
    assert snapshot.reported_total_tokens == 15 and snapshot.unknown_requests == 0
    assert snapshot.outstanding_requests == snapshot.tool_calls == 0 and tools.gateway.calls == []
    assert [
        definition.model_dump(mode="json") for definition in tools.catalog.definitions
    ] == original_schemas


async def test_fleet_patch_is_typed_terminal_not_action(monkeypatch: pytest.MonkeyPatch) -> None:
    content = "Reviewed organization note.\n"
    patch = FleetPatch.model_validate(
        {
            "fleet_patch_id": "fpatch_" + "1" * 32,
            "project_id": "prj_" + "2" * 32,
            "base_fleet_spec_sha256": "3" * 64,
            "rationale": "Review this bounded change.",
            "changes": [
                {
                    "operation": "replace",
                    "path": ".fleet/README.md",
                    "before_sha256": "4" * 64,
                    "after_sha256": sha256_bytes(content.encode()),
                    "content": content,
                }
            ],
        }
    )
    invocation = request("cos")
    invocation.input["organization_context"] = {
        "proposal_id": patch.fleet_patch_id,
        "project_id": patch.project_id,
        "base_fleet_spec_sha256": patch.base_fleet_spec_sha256,
    }

    def respond(received: httpx2.Request) -> httpx2.Response:
        names = {
            d["name"]
            for t in json.loads(received.content)["tools"]
            for d in t["functionDeclarations"]
        }
        assert names == {"submit_scope_decision", "submit_fleet_patch"}
        return httpx2.Response(
            200,
            json=response_body(
                [
                    {
                        "functionCall": {
                            "name": "submit_fleet_patch",
                            "args": patch.model_dump(mode="json"),
                        }
                    }
                ]
            ),
        )

    install_transport(monkeypatch, respond)
    with override_allow_model_requests(True):
        async with open_google_model(
            MODEL,
            KEY,
            Redactor([KEY]),
            timeout_seconds=2,
            terminal_outputs=terminals(AgentRole.COS),
        ) as model:
            result = await PydanticAIRuntimeAdapter.for_test_model(model).invoke(
                invocation,
                RuntimeInvocationServices(configuration=CONFIG, tools=EMPTY_RUNTIME_TOOL_CATALOG),
            )
    assert result.output == patch and result.usage is not None and result.usage.tool_calls == 0


@pytest.mark.parametrize(
    "fault", ["cookie", "unknown-header", "duplicate-header", "auth", "host", "query", "route"]
)
async def test_final_outbound_guard_rejects_scope_changes(
    monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    sends = 0

    def respond(received: httpx2.Request) -> httpx2.Response:
        nonlocal sends
        sends += 1
        return httpx2.Response(500, json={})

    sync, clients = install_transport(monkeypatch, respond)
    original = provider_module.AsyncClient

    async def poison(received: httpx2.Request) -> None:
        if fault == "cookie":
            received.headers["Cookie"] = "unsafe=1"
        elif fault == "unknown-header":
            received.headers["X-Unknown"] = "unsafe"
        elif fault == "duplicate-header":
            received.headers = httpx2.Headers(
                [*received.headers.multi_items(), ("Accept", "application/json")]
            )
        elif fault == "auth":
            received.headers["x-goog-api-key"] = "wrong-key"
        elif fault == "host":
            received.headers["Host"] = "other.invalid"
        elif fault == "query":
            received.url = received.url.copy_with(query=b"key=forbidden")
        else:
            received.url = received.url.copy_with(path="/v1beta/models/other:generateContent")

    def create(**kwargs: Any) -> httpx2.AsyncClient:
        kwargs["event_hooks"]["request"].insert(0, poison)
        return original(**kwargs)

    monkeypatch.setattr(provider_module, "AsyncClient", create)
    with override_allow_model_requests(True), pytest.raises(FleetError) as captured:
        async with open_google_model(
            MODEL,
            KEY,
            Redactor([KEY]),
            timeout_seconds=2,
            terminal_outputs=terminals(AgentRole.COS),
        ) as model:
            await PydanticAIRuntimeAdapter.for_test_model(model).invoke(
                request("cos"),
                RuntimeInvocationServices(configuration=CONFIG, tools=EMPTY_RUNTIME_TOOL_CATALOG),
            )
    assert captured.value.details["runtime_diagnostic"]["cause_category"] == "request_policy"
    assert sends == 0 and all(client.is_closed for client in [*sync, *clients])


@pytest.mark.parametrize("fault", ["native", "callable", "mcp"])
async def test_builder_rejects_nonfunction_tools_before_high_level_sdk(
    monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    from google.genai.models import AsyncModels
    from pydantic_ai.models.google import GoogleModel

    original = GoogleModel._build_content_and_config

    async def build(self: Any, *args: Any, **kwargs: Any) -> Any:
        contents, original_config = await original(self, *args, **kwargs)
        config: Any = original_config
        config["tools"] = [{"google_search": {}}, lambda: None, {"mcp_server": "forbidden"}][
            ["native", "callable", "mcp"].index(fault)
        ]
        if fault != "callable":
            config["tools"] = [config["tools"]]
        return contents, config

    monkeypatch.setattr(GoogleModel, "_build_content_and_config", build)

    async def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("Native/callable/MCP tool reached the high-level SDK")

    monkeypatch.setattr(AsyncModels, "generate_content", forbidden)
    sync, clients = install_transport(monkeypatch, lambda received: httpx2.Response(500))
    with override_allow_model_requests(True), pytest.raises(FleetError) as captured:
        async with open_google_model(
            MODEL,
            KEY,
            Redactor([KEY]),
            timeout_seconds=2,
            terminal_outputs=terminals(AgentRole.COS),
        ) as model:
            await PydanticAIRuntimeAdapter.for_test_model(model).invoke(
                request("cos"),
                RuntimeInvocationServices(configuration=CONFIG, tools=EMPTY_RUNTIME_TOOL_CATALOG),
            )
    assert captured.value.details["runtime_diagnostic"]["cause_category"] == "request_policy"
    assert all(client.is_closed for client in [*sync, *clients])


@pytest.mark.parametrize("extra_cancels", [1, 3])
async def test_repeated_cancellation_waits_for_both_physical_clients(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    extra_cancels: int,
) -> None:
    entered, closing, release, closed = (asyncio.Event() for _ in range(4))
    ledger = _ledger(tmp_path, RunBudgetLimits())
    accounting = ledger.store.begin_attempt(ledger.request)
    starts = 0

    async def respond(received: httpx2.Request) -> httpx2.Response:
        entered.set()
        await asyncio.Event().wait()
        raise AssertionError("Cancelled response must never complete")

    class HeldTransport(httpx2.MockTransport):
        async def aclose(self) -> None:
            nonlocal starts
            starts += 1
            closing.set()
            await release.wait()
            await super().aclose()
            closed.set()

    sync, clients = install_transport(monkeypatch, respond)

    def create(**kwargs: Any) -> httpx2.AsyncClient:
        client = httpx2.AsyncClient(transport=HeldTransport(respond), **kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(provider_module, "AsyncClient", create)

    async def invoke() -> None:
        async with open_google_model(
            MODEL,
            KEY,
            Redactor([KEY]),
            timeout_seconds=2,
            terminal_outputs=terminals(AgentRole.COS),
        ) as model:
            await PydanticAIRuntimeAdapter.for_test_model(model).invoke(
                ledger.request,
                RuntimeInvocationServices(
                    configuration=CONFIG, tools=EMPTY_RUNTIME_TOOL_CATALOG, accounting=accounting
                ),
            )

    with override_allow_model_requests(True):
        execution = asyncio.create_task(invoke())
        try:
            await asyncio.wait_for(entered.wait(), 2)
            execution.cancel()
            await asyncio.wait_for(closing.wait(), 2)
            assert sync[0].is_closed and clients[0].is_closed
            for _ in range(extra_cancels):
                execution.cancel()
                await asyncio.sleep(0)
                assert not execution.done() and not closed.is_set()
        finally:
            release.set()
            await asyncio.gather(execution, return_exceptions=True)
            accounting.finish(RuntimeAttemptStatus.CANCELLED)
    snapshot = ledger.reopen().snapshot(ledger.run.run_id)
    assert execution.cancelled() and closed.is_set() and starts == 1
    assert snapshot.model_requests == snapshot.unknown_requests == 1
    assert snapshot.outstanding_requests == snapshot.reserved_tokens == 0
    assert snapshot.unknown_tokens > 0 and snapshot.reported_total_tokens == 0


@pytest.mark.parametrize(
    "stage", ["async-constructor", "sdk-constructor", "sync-close", "async-close"]
)
async def test_partial_construction_and_cleanup_failures_close_owned_resources(
    monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    from google import genai

    sync, clients = install_transport(monkeypatch, lambda received: httpx2.Response(500))

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise ValueError(KEY)

    if stage == "async-constructor":
        monkeypatch.setattr(provider_module, "AsyncClient", fail)
    elif stage == "sdk-constructor":
        monkeypatch.setattr(genai, "Client", fail)
    with pytest.raises(FleetError) as captured:
        async with open_google_model(
            MODEL,
            KEY,
            Redactor([KEY]),
            timeout_seconds=2,
            terminal_outputs=terminals(AgentRole.COS),
        ):
            if stage == "sync-close":
                original = sync[0].close

                def close() -> None:
                    original()
                    raise ValueError(KEY)

                monkeypatch.setattr(sync[0], "close", close)
            elif stage == "async-close":
                aclose = clients[0].aclose

                async def close_async() -> None:
                    await aclose()
                    raise ValueError(KEY)

                monkeypatch.setattr(clients[0], "aclose", close_async)
    assert all(client.is_closed for client in [*sync, *clients])
    assert KEY not in str(captured.value) and KEY not in str(captured.value.details)
    if stage.endswith("close"):
        assert captured.value.details["runtime_diagnostic"]["cause_category"] == "client_cleanup"


async def test_request_timeout_is_unknown_without_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = _ledger(tmp_path, RunBudgetLimits())
    accounting = ledger.store.begin_attempt(ledger.request)
    sends = 0

    def respond(received: httpx2.Request) -> httpx2.Response:
        nonlocal sends
        sends += 1
        raise httpx2.ReadTimeout(KEY, request=received)

    sync, clients = install_transport(monkeypatch, respond)
    with override_allow_model_requests(True), pytest.raises(FleetError) as captured:
        async with open_google_model(
            MODEL,
            KEY,
            Redactor([KEY]),
            timeout_seconds=2,
            terminal_outputs=terminals(AgentRole.COS),
        ) as model:
            await PydanticAIRuntimeAdapter.for_test_model(model).invoke(
                ledger.request,
                RuntimeInvocationServices(
                    configuration=CONFIG, tools=EMPTY_RUNTIME_TOOL_CATALOG, accounting=accounting
                ),
            )
    accounting.finish(RuntimeAttemptStatus.FAILED, error_code=captured.value.code)
    snapshot = ledger.reopen().snapshot(ledger.run.run_id)
    assert captured.value.code is ErrorCode.RUNTIME_TIMEOUT
    assert snapshot.model_requests == snapshot.unknown_requests == sends == 1
    assert snapshot.outstanding_requests == snapshot.reserved_tokens == 0
    assert all(client.is_closed for client in [*sync, *clients])


@pytest.mark.parametrize("fault", ["missing_usage", "http500"])
async def test_new_request_cannot_reuse_previous_usage_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    ledger = _ledger(tmp_path, RunBudgetLimits())
    accounting = ledger.store.begin_attempt(ledger.request)
    catalog = RecordingCatalog(
        (
            RuntimeToolDefinition(
                name="repo_list_files",
                description="Bounded read.",
                parameters_json_schema={"type": "object", "properties": {}},
            ),
        )
    )
    sends = 0

    def respond(received: httpx2.Request) -> httpx2.Response:
        nonlocal sends
        sends += 1
        body = response_body([{"functionCall": {"name": "repo_list_files", "args": {}}}])
        if sends == 2:
            if fault == "http500":
                return httpx2.Response(500, json={"error": {"code": 500, "message": KEY}})
            del body["usageMetadata"]
        return httpx2.Response(200, json=body)

    install_transport(monkeypatch, respond)
    with override_allow_model_requests(True), pytest.raises(FleetError) as captured:
        async with open_google_model(
            MODEL,
            KEY,
            Redactor([KEY]),
            timeout_seconds=2,
            terminal_outputs=terminals(AgentRole.COS),
        ) as model:
            await PydanticAIRuntimeAdapter.for_test_model(model).invoke(
                ledger.request,
                RuntimeInvocationServices(
                    configuration=CONFIG, tools=catalog, accounting=accounting
                ),
            )
    accounting.finish(RuntimeAttemptStatus.FAILED, error_code=captured.value.code)
    snapshot = ledger.reopen().snapshot(ledger.run.run_id)
    assert sends == snapshot.model_requests == 2 and len(catalog.calls) == 1
    assert snapshot.reported_total_tokens == 15 and snapshot.unknown_requests == 1
    assert snapshot.outstanding_requests == snapshot.reserved_tokens == 0


async def test_even_forced_sdk_retry_cannot_mint_another_send(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from google.genai import errors
    from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_none

    sends = 0

    def respond(received: httpx2.Request) -> httpx2.Response:
        nonlocal sends
        sends += 1
        return httpx2.Response(500, json={"error": {"code": 500, "message": "offline retry probe"}})

    install_transport(monkeypatch, respond)
    with override_allow_model_requests(True), pytest.raises(FleetError) as captured:
        async with open_google_model(
            MODEL,
            KEY,
            Redactor([KEY]),
            timeout_seconds=2,
            terminal_outputs=terminals(AgentRole.COS),
        ) as model:
            # Fault-inject retry behavior in the actual installed SDK. The final
            # request hook must reject send #2 even if SDK retries are changed.
            raw: Any = model
            raw.wrapped.client._api_client._async_retry = AsyncRetrying(
                stop=stop_after_attempt(2),
                retry=retry_if_exception_type(errors.ServerError),
                wait=wait_none(),
                reraise=True,
            )
            await PydanticAIRuntimeAdapter.for_test_model(model).invoke(
                request("cos"),
                RuntimeInvocationServices(configuration=CONFIG, tools=EMPTY_RUNTIME_TOOL_CATALOG),
            )
    assert sends == 1
    assert captured.value.details["runtime_diagnostic"]["cause_category"] == "request_policy"


async def test_media_is_rejected_before_pydanticai_mapping_or_sdk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pydantic_ai.messages import ImageUrl, ModelRequest, UserPromptPart
    from pydantic_ai.models import ModelRequestParameters
    from pydantic_ai.models.google import GoogleModel

    async def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("Media reached PydanticAI's URL/file mapper")

    monkeypatch.setattr(GoogleModel, "_map_messages", forbidden)
    sync, clients = install_transport(monkeypatch, lambda received: httpx2.Response(500))
    with override_allow_model_requests(True), pytest.raises(FleetError) as captured:
        async with open_google_model(
            MODEL,
            KEY,
            Redactor([KEY]),
            timeout_seconds=2,
            terminal_outputs=terminals(AgentRole.COS),
        ) as model:
            await model.request(
                [
                    ModelRequest(
                        parts=[
                            UserPromptPart(
                                content=[ImageUrl(url="https://forbidden.invalid/image.png")]
                            )
                        ]
                    )
                ],
                {"max_tokens": 100},
                ModelRequestParameters(),
            )
    assert captured.value.details["runtime_diagnostic"]["cause_category"] == "request_policy"
    assert all(client.is_closed for client in [*sync, *clients])


async def test_production_runtime_uses_explicit_selected_role_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from test_pydantic_ai_runtime import StaticSecretStore

    store = StaticSecretStore(KEY)
    sends = 0

    def respond(received: httpx2.Request) -> httpx2.Response:
        nonlocal sends
        sends += 1
        return httpx2.Response(
            200,
            json=response_body(
                [output_call(received, expected_output(AgentRole.ENGINEER, "custom-engineer"))]
            ),
        )

    install_transport(monkeypatch, respond)
    with override_allow_model_requests(True):
        result = await PydanticAIRuntimeAdapter(store, Redactor([KEY])).invoke(
            request("custom-engineer"),
            RuntimeInvocationServices(
                configuration=CONFIG,
                tools=EMPTY_RUNTIME_TOOL_CATALOG,
                execution_kind=AgentRole.ENGINEER,
            ),
        )
    assert result.output == expected_output(AgentRole.ENGINEER, "custom-engineer")
    assert store.resolve_calls == sends == 1
    assert result.provider_metadata is not None and result.provider_metadata.provider == "google"
    assert result.provider_metadata.model == f"google:{MODEL}"


@pytest.mark.parametrize(
    "field",
    [
        "cachedContentTokenCount",
        "thoughtsTokenCount",
        "toolUsePromptTokenCount",
        "promptTokensDetails",
        "cacheTokensDetails",
        "candidatesTokensDetails",
        "toolUsePromptTokensDetails",
    ],
)
@pytest.mark.parametrize("bad", [True, "untrusted-usage-marker", -1])
async def test_every_accepted_optional_usage_field_is_strict_before_sdk_warnings(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    bad: object,
) -> None:
    sends = 0

    def respond(received: httpx2.Request) -> httpx2.Response:
        nonlocal sends
        sends += 1
        body = response_body([output_call(received, expected_output(AgentRole.COS, "cos"))])
        body["usageMetadata"][field] = (
            [{"modality": "TEXT", "tokenCount": bad}] if field.endswith("Details") else bad
        )
        return httpx2.Response(200, json=body)

    install_transport(monkeypatch, respond)
    with (
        warnings.catch_warnings(record=True) as observed,
        override_allow_model_requests(True),
        pytest.raises(FleetError) as captured,
    ):
        warnings.simplefilter("always", UserWarning)
        async with open_google_model(
            MODEL,
            KEY,
            Redactor([KEY]),
            timeout_seconds=2,
            terminal_outputs=terminals(AgentRole.COS),
        ) as model:
            await PydanticAIRuntimeAdapter.for_test_model(model).invoke(
                request("cos"),
                RuntimeInvocationServices(configuration=CONFIG, tools=EMPTY_RUNTIME_TOOL_CATALOG),
            )
    assert (
        sends == 1
        and captured.value.details["runtime_diagnostic"]["cause_category"] == "response_policy"
    )
    assert not any(issubclass(item.category, UserWarning) for item in observed)
    assert "untrusted-usage-marker" not in str(captured.value)
