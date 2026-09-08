"""Real SDK request serialization for different role models and exact keys, offline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx2
import pytest
from model_profiles_fixtures import make_profile_harness, model_configuration
from openai import DefaultAsyncHttpxClient
from pydantic_ai.models import override_allow_model_requests

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
async def test_profile_routing_reaches_serialized_sdk_model_and_only_selected_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
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
        sends.append(
            (
                str(request.url),
                body["model"],
                request.headers["authorization"],
                request.content.decode(),
            )
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
    monkeypatch.setenv("OPENAI_API_KEY", "ambient-must-not-be-used")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://untrusted.invalid/v1")
    monkeypatch.delenv("OPENAI_CUSTOM_HEADERS", raising=False)
    for name in ("planning", "coding", "reviewing"):
        harness.environment[f"{name.upper()}_KEY"] = f"fixture-{name}-exact-key"
        harness.service.set(
            name,
            configuration=model_configuration(f"openai-chat:{name}", f"env:{name.upper()}_KEY"),
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
    for url, _, _, body in sends:
        assert url == "https://api.openai.com/v1/chat/completions"
        assert "ambient-must-not-be-used" not in body
        assert "env:" not in body
        for key in harness.environment.values():
            assert key not in body
    assert snapshot.roles["cos"].configuration != RuntimeConfiguration()
