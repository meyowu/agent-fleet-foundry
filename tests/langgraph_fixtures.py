"""Synthetic Responses data for the actual LangGraph/SDK path, never live evidence."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx2
import pytest
from test_pydantic_ai_runtime import StaticSecretStore
from test_runtime_conformance import expected_output

import agent_fleet.adapters.runtime.openai_client as transport_module
from agent_fleet.adapters.runtime.langgraph import LangGraphRuntimeAdapter
from agent_fleet.domain.models import AgentRole, RuntimeConfiguration
from agent_fleet.domain.security import Redactor

KEY = "offline-langgraph-selected-credential"
MODEL = "gpt-test"
CONFIG = RuntimeConfiguration(
    runtime_name="langgraph",
    provider_model=f"openai:{MODEL}",
    credential_ref="env:FLEET_LANGGRAPH_OFFLINE",
    max_retries=0,
    max_requests=4,
    max_total_tokens=4096,
    timeout_seconds=3,
)


def adapter() -> LangGraphRuntimeAdapter:
    return LangGraphRuntimeAdapter(StaticSecretStore(KEY), Redactor([KEY]))


def configure_transport(
    monkeypatch: pytest.MonkeyPatch, respond: Callable[[httpx2.Request], Any]
) -> list[httpx2.AsyncClient]:
    clients: list[httpx2.AsyncClient] = []

    def create(**kwargs: Any) -> httpx2.AsyncClient:
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        client = httpx2.AsyncClient(transport=httpx2.MockTransport(respond), **kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(transport_module, "DefaultAsyncHttpxClient", create)
    return clients


def call(name: str, arguments: object, call_id: str = "output-final") -> dict[str, Any]:
    return {
        "type": "function_call",
        "id": "item-" + call_id,
        "call_id": call_id,
        "name": name,
        "arguments": json.dumps(arguments),
        "status": "completed",
    }


def payload(calls: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": "response-offline",
        "object": "response",
        "created_at": 0,
        "status": "completed",
        "model": MODEL,
        "output": calls,
        "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
    }


def output(received: httpx2.Request, calls: list[dict[str, Any]]) -> httpx2.Response:
    return httpx2.Response(200, request=received, json=payload(calls))


def final_call(
    body: dict[str, Any], kind: AgentRole = AgentRole.COS, role: str = "cos"
) -> dict[str, Any]:
    name = next(tool["name"] for tool in body["tools"] if tool["name"].startswith("submit_"))
    return call(name, expected_output(kind, role).model_dump(mode="json"))
