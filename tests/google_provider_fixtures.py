"""Synthetic responses transported through the actual Google SDK; no network."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx2
import pytest
from pydantic import BaseModel

import agent_fleet.adapters.runtime.google_provider as provider_module
from agent_fleet.domain.models import (
    AgentRole,
    FleetPatch,
    ImplementationReport,
    RuntimeConfiguration,
    ScopeDecision,
    SpecialistReport,
    VerifierVerdict,
)

KEY = "fleet-google-offline-selected-credential"
MODEL = "gemini-2.5-flash-lite"
CONFIG = RuntimeConfiguration(
    runtime_name="pydantic-ai",
    provider_model=f"google:{MODEL}",
    credential_ref="env:FLEET_GOOGLE_OFFLINE",
    max_retries=0,
    max_requests=4,
    max_total_tokens=4096,
    timeout_seconds=2,
)


def terminals(kind: AgentRole) -> dict[str, type[BaseModel]]:
    choices: dict[AgentRole, dict[str, type[BaseModel]]] = {
        AgentRole.COS: {"submit_scope_decision": ScopeDecision, "submit_fleet_patch": FleetPatch},
        AgentRole.ENGINEER: {"submit_implementation_report": ImplementationReport},
        AgentRole.VERIFIER: {"submit_verifier_verdict": VerifierVerdict},
        AgentRole.RESEARCHER: {"submit_specialist_report": SpecialistReport},
        AgentRole.ARCHITECT: {"submit_specialist_report": SpecialistReport},
    }
    return choices[kind]


def install_transport(
    monkeypatch: pytest.MonkeyPatch,
    respond: Callable[[httpx2.Request], Any],
) -> tuple[list[httpx2.Client], list[httpx2.AsyncClient]]:
    sync: list[httpx2.Client] = []
    asynchronous: list[httpx2.AsyncClient] = []

    def create_sync(**kwargs: Any) -> httpx2.Client:
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        client = httpx2.Client(transport=httpx2.MockTransport(respond), **kwargs)
        sync.append(client)
        return client

    def create_async(**kwargs: Any) -> httpx2.AsyncClient:
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        client = httpx2.AsyncClient(transport=httpx2.MockTransport(respond), **kwargs)
        asynchronous.append(client)
        return client

    monkeypatch.setattr(provider_module, "Client", create_sync)
    monkeypatch.setattr(provider_module, "AsyncClient", create_async)
    return sync, asynchronous


def response_body(parts: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "modelVersion": MODEL,
        "responseId": "offline-response",
        "candidates": [
            {"index": 0, "finishReason": "STOP", "content": {"role": "model", "parts": parts}}
        ],
        "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5, "totalTokenCount": 15},
    }


def output_call(received: httpx2.Request, output: BaseModel) -> dict[str, Any]:
    body = json.loads(received.content)
    name = next(
        declaration["name"]
        for tool in body["tools"]
        for declaration in tool["functionDeclarations"]
        if declaration["name"].startswith("submit_") and declaration["name"] != "submit_fleet_patch"
    )
    return {"functionCall": {"name": name, "args": output.model_dump(mode="json")}}
