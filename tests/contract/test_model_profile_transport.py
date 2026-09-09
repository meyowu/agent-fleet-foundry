"""Real SDK request serialization for different role models and exact keys, offline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx2
import pytest
from google_provider_fixtures import install_transport
from model_profiles_fixtures import make_profile_harness, model_configuration
from openai import DefaultAsyncHttpxClient
from pydantic_ai.models import override_allow_model_requests

import agent_fleet.adapters.runtime.anthropic_provider as anthropic_module
import agent_fleet.adapters.runtime.pydantic_ai as runtime_module
from agent_fleet.domain.ids import IdPrefix
from agent_fleet.domain.models import (
    AgentInvocation,
    AgentRole,
    RuntimeConfiguration,
    WorkflowStage,
)
from agent_fleet.ports.runtime import EMPTY_RUNTIME_TOOL_CATALOG, RuntimeInvocationServices


@pytest.mark.asyncio
@pytest.mark.parametrize("anthropic_role", [None, "cos", "engineer", "verifier"])
@pytest.mark.parametrize("alternate_provider", ["anthropic", "google"])
async def test_profile_routing_reaches_serialized_sdk_model_and_only_selected_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    anthropic_role: str | None,
    alternate_provider: str,
) -> None:
    harness = make_profile_harness(tmp_path)
    payloads: dict[str, dict[str, object]] = {
        "submit_scope_decision": {
            "normalized_goal": "Explain the bounded fixture",
            "workflow": "code-change",
            "change_kind": "read_only",
            "fleet_strategy": "direct",
            "allowed_paths": [],
            "forbidden_paths": [".git", ".fleet"],
            "acceptance_criteria": [
                {"criterion_id": "explain", "description": "Explain the fixture"}
            ],
            "required_evidence": ["control_plane_plan"],
        },
        "submit_implementation_report": {
            "summary": "No mutation needed for this transport contract",
            "intended_changed_paths": [],
            "tests_added_or_changed": [],
            "criterion_results": ["Transport is exercised offline"],
            "evidence_artifact_ids": [],
            "unresolved_limitations": ["No live provider called"],
            "verifier_focus": ["Inspect exact model and key"],
        },
        "submit_verifier_verdict": {
            "verdict": "pass",
            "criterion_results": ["Transport scope is bounded"],
            "evidence_artifact_ids": [],
            "regressions": [],
            "required_repairs": [],
            "proof_gaps": ["No code execution"],
            "rationale": "Only mocked transport is validated",
        },
    }
    sends: list[tuple[str, str, str, str]] = []

    async def respond(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        selected_model = (
            request.url.path.split("/")[-1].removesuffix(":generateContent")
            if request.url.host == "generativelanguage.googleapis.com"
            else body["model"]
        )
        api_key = request.headers.get("x-api-key", request.headers.get("x-goog-api-key"))
        sends.append(
            (
                str(request.url),
                selected_model,
                request.headers.get("authorization", f"Bearer {api_key}"),
                request.content.decode(),
            )
        )
        if request.url.host == "generativelanguage.googleapis.com":
            output = next(
                declaration["name"]
                for tool in body["tools"]
                for declaration in tool["functionDeclarations"]
                if declaration["name"] in payloads
            )
            return httpx2.Response(
                200,
                request=request,
                json={
                    "modelVersion": selected_model,
                    "candidates": [
                        {
                            "index": 0,
                            "finishReason": "STOP",
                            "content": {
                                "role": "model",
                                "parts": [
                                    {"functionCall": {"name": output, "args": payloads[output]}}
                                ],
                            },
                        }
                    ],
                    "usageMetadata": {
                        "promptTokenCount": 10,
                        "candidatesTokenCount": 10,
                        "totalTokenCount": 20,
                    },
                },
            )
        if request.url.host == "api.anthropic.com":
            output = next(tool["name"] for tool in body["tools"] if tool["name"] in payloads)
            return httpx2.Response(
                200,
                request=request,
                json={
                    "id": "msg_fixture",
                    "type": "message",
                    "role": "assistant",
                    "model": body["model"],
                    "content": [
                        {
                            "id": "output-fixture",
                            "type": "tool_use",
                            "name": output,
                            "input": payloads[output],
                        }
                    ],
                    "stop_reason": "tool_use",
                    "stop_sequence": None,
                    "usage": {"input_tokens": 10, "output_tokens": 10},
                },
            )
        output = next(
            tool["function"]["name"]
            for tool in body["tools"]
            if tool["function"]["name"] in payloads
        )
        return httpx2.Response(
            200,
            request=request,
            json={
                "id": "chatcmpl-fixture",
                "object": "chat.completion",
                "created": 1,
                "model": body["model"],
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "output-fixture",
                                    "type": "function",
                                    "function": {
                                        "name": output,
                                        "arguments": json.dumps(payloads[output]),
                                    },
                                }
                            ],
                        },
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
            },
        )

    original = DefaultAsyncHttpxClient

    def transport(**arguments: Any) -> httpx2.AsyncClient:
        return original(transport=httpx2.MockTransport(respond), **arguments)

    monkeypatch.setattr(runtime_module, "DefaultAsyncHttpxClient", transport)
    monkeypatch.setattr(anthropic_module, "AsyncClient", transport)
    install_transport(monkeypatch, respond)
    monkeypatch.setenv("OPENAI_API_KEY", "ambient-must-not-be-used")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://untrusted.invalid/v1")
    monkeypatch.delenv("OPENAI_CUSTOM_HEADERS", raising=False)
    monkeypatch.delenv("ANTHROPIC_CUSTOM_HEADERS", raising=False)
    monkeypatch.delenv("ANTHROPIC_LOG", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ambient-anthropic-must-not-be-used")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://untrusted.invalid")
    monkeypatch.setenv("GOOGLE_API_KEY", "ambient-google-must-not-be-used")
    monkeypatch.setenv("GEMINI_API_KEY", "ambient-gemini-must-not-be-used")
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "1")
    expected_urls: dict[str, str] = {}
    for name, role in (("planning", "cos"), ("coding", "engineer"), ("reviewing", "verifier")):
        provider = alternate_provider if role == anthropic_role else "openai-chat"
        expected_urls[name] = (
            "https://api.anthropic.com/v1/messages?beta=true"
            if provider == "anthropic"
            else f"https://generativelanguage.googleapis.com/v1beta/models/{name}:generateContent"
            if provider == "google"
            else "https://api.openai.com/v1/chat/completions"
        )
        harness.environment[f"{name.upper()}_KEY"] = f"fixture-{name}-exact-key"
        harness.service.set(
            name,
            configuration=model_configuration(f"{provider}:{name}", f"env:{name.upper()}_KEY"),
        )
    harness.service.bind(harness.project, profile="planning", default=True, expected_revision=0)
    harness.service.bind(harness.project, profile="coding", role="engineer", expected_revision=1)
    harness.service.bind(harness.project, profile="reviewing", role="verifier", expected_revision=2)
    snapshot = harness.resolve()
    harness.service.save_bindings(snapshot)
    for role, stage in (
        (AgentRole.COS, WorkflowStage.SCOPING),
        (AgentRole.ENGINEER, WorkflowStage.IMPLEMENTING),
        (AgentRole.VERIFIER, WorkflowStage.VERIFYING),
    ):
        binding = snapshot.roles[role]
        request = AgentInvocation(
            run_id=snapshot.root_run_id,
            task_id=harness.state.ids.new(IdPrefix.TASK),
            agent_instance_id=harness.state.ids.new(IdPrefix.AGENT),
            role=role,
            stage=stage,
            iteration=0,
            max_steps=1,
            instructions="Perform only the bounded transport contract.",
            input={"goal": "Validate exact routing without network"},
        )
        with override_allow_model_requests(True):
            result = await harness.service.runtimes.get("pydantic-ai").invoke(
                request,
                RuntimeInvocationServices(
                    configuration=binding.configuration, tools=EMPTY_RUNTIME_TOOL_CATALOG
                ),
            )
        assert result.usage is not None and result.usage.total_tokens == 20
    assert [(model, key) for _, model, key, _ in sends] == [
        ("planning", "Bearer fixture-planning-exact-key"),
        ("coding", "Bearer fixture-coding-exact-key"),
        ("reviewing", "Bearer fixture-reviewing-exact-key"),
    ]
    assert len(sends) == 3
    for url, model, _, body in sends:
        assert url == expected_urls[model]
        assert "ambient-must-not-be-used" not in body
        assert "ambient-anthropic-must-not-be-used" not in body
        assert "ambient-google-must-not-be-used" not in body
        assert "ambient-gemini-must-not-be-used" not in body
        assert "env:" not in body
        for key in harness.environment.values():
            assert key not in body
    assert snapshot.roles["cos"].configuration != RuntimeConfiguration()
