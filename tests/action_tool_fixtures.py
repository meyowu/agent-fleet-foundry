"""Real SDK/catalog fixtures with offline transport and a recording gateway."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import httpx2
import pytest
from openai import DefaultAsyncHttpxClient

import agent_fleet.adapters.runtime.pydantic_ai as runtime_module
from agent_fleet.adapters.persistence.runtime_budgets import SqliteRuntimeBudgetStore
from agent_fleet.adapters.persistence.sqlite import SqliteStateStore
from agent_fleet.adapters.runtime.pydantic_ai import PydanticAIRuntimeAdapter
from agent_fleet.adapters.secrets.environment import EnvironmentSecretStore
from agent_fleet.adapters.system import SystemClock, UuidIdGenerator
from agent_fleet.application.gateway import ToolGateway
from agent_fleet.application.runtime_tools import GatewayRuntimeToolCatalog
from agent_fleet.domain.budgets import RunBudgetLimits
from agent_fleet.domain.models import (
    AgentInstance,
    AgentInvocation,
    AgentRole,
    CommandSpec,
    FakeScenario,
    Project,
    Run,
    RunStatus,
    RuntimeConfiguration,
    SandboxCapabilities,
    SandboxConfiguration,
    SandboxHandle,
    SandboxName,
    SandboxRequirements,
    TaskSpec,
    WorkflowStage,
    Workspace,
    WorkspaceKind,
)
from agent_fleet.domain.security import Redactor

SENTINEL = "offline-action-tool-credential"


class RecordingGateway:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def execute(self, **kwargs: Any) -> dict[str, object]:
        self.calls.append(kwargs)
        return {"files": []}


@dataclass
class ActionTools:
    catalog: GatewayRuntimeToolCatalog
    gateway: RecordingGateway
    run: Run
    task: TaskSpec
    agent: AgentInstance
    invocation: AgentInvocation


def make_action_tools(
    *,
    role: AgentRole = AgentRole.ENGINEER,
    sandbox: SandboxName = "fake",
    with_commands: bool = True,
) -> ActionTools:
    now = datetime.now(UTC)
    stage = WorkflowStage.IMPLEMENTING if role is AgentRole.ENGINEER else WorkflowStage.VERIFYING
    assert sandbox in {"fake", "docker"}
    # A metadata-only Docker descriptor exercises catalog omission, never a provider.
    capabilities = (
        SandboxCapabilities.phase1_fake()
        if sandbox == "fake"
        else SandboxCapabilities(
            provider="docker",
            security_level="isolated",
            isolation_enforced=True,
            executes_code=True,
            supported_network_modes=("none",),
            supports_resource_limits=True,
            supports_recovery=True,
            supports_non_root=True,
            supports_read_only_root=True,
            supports_no_new_privileges=True,
            supports_capability_drop=True,
        )
    )
    run = Run(
        run_id="run_" + "1" * 32,
        project_id="prj_" + "2" * 32,
        correlation_id="corr_" + "3" * 32,
        goal="bounded offline schema check",
        base_revision="a" * 40,
        target_status_fingerprint="4" * 64,
        runtime_name="pydantic-ai",
        provider_model="openai:gpt-test",
        credential_ref="env:FLEET_ACTION_TEST_KEY",
        sandbox_name=sandbox,
        sandbox_configuration=SandboxConfiguration(
            provider=sandbox, image="offline:fixture" if sandbox == "docker" else None
        ),
        sandbox_requirements=SandboxRequirements(),
        sandbox_capabilities_snapshot=capabilities,
        sandbox_image_identity="sha256:" + "a" * 64 if sandbox == "docker" else None,
        sandbox_daemon_identity="b" * 64 if sandbox == "docker" else None,
        fake_scenario=FakeScenario.APPROVAL,
        status="running",
        stage=stage,
        task_id="task_" + "5" * 32,
        created_at=now,
        updated_at=now,
    )
    task = TaskSpec(
        task_id=run.task_id,
        run_id=run.run_id,
        original_goal=run.goal,
        normalized_goal=run.goal,
        base_revision=run.base_revision,
        allowed_paths=["src/canary_calc/core.py"],
        forbidden_paths=[".git", ".fleet"],
        acceptance_criteria=[{"criterion_id": "canary", "description": "Check the canary."}],
        required_evidence=["canonical_patch", "command_evidence"],
        max_repair_iterations=1,
        config_snapshot_hash="6" * 64,
        created_at=now,
        verification_commands=[
            CommandSpec(command_id="python-test", executable="python", argv=("-m", "pytest"))
        ]
        if with_commands
        else [],
    )
    agent = AgentInstance(
        agent_instance_id="agent_" + "7" * 32,
        run_id=run.run_id,
        task_id=task.task_id,
        role=role,
        status="running",
        iteration=0,
        created_at=now,
    )
    workspace = Workspace(
        workspace_id="ws_" + "8" * 32,
        run_id=run.run_id,
        kind=WorkspaceKind.CANDIDATE if role is AgentRole.ENGINEER else WorkspaceKind.VERIFICATION,
        path="/trusted/offline-fixture",
        base_revision=run.base_revision,
    )
    handle = SandboxHandle(
        sandbox_id="sandbox_" + "9" * 32, run_id=run.run_id, workspace_host_path=workspace.path
    )
    gateway = RecordingGateway()
    catalog = GatewayRuntimeToolCatalog(
        gateway=cast(ToolGateway, gateway),
        redactor=Redactor([SENTINEL]),
        run=run,
        task=task,
        agent=agent,
        workspace=workspace,
        sandbox_handle=handle,
        max_calls=12,
    )
    invocation = AgentInvocation(
        run_id=run.run_id,
        task_id=task.task_id,
        agent_instance_id=agent.agent_instance_id,
        role=role,
        stage=stage,
        iteration=0,
        max_steps=8,
        input={"task": task.model_dump(mode="json")},
    )
    return ActionTools(catalog, gateway, run, task, agent, invocation)


def persist_action_tools(tmp_path: Path, tools: ActionTools) -> SqliteRuntimeBudgetStore:
    clock, ids, redactor = SystemClock(), UuidIdGenerator(), Redactor([SENTINEL])
    state = SqliteStateStore(tmp_path / "state.db", clock, ids, redactor)
    state.migrate()
    state.save_project(
        Project(
            project_id=tools.run.project_id,
            canonical_root=str(tmp_path),
            identity_hash="a" * 64,
            created_at=clock.now(),
            updated_at=clock.now(),
        )
    )
    run = tools.run.model_copy(update={"status": RunStatus.CREATED, "stage": None})
    run = Run.model_validate(run.model_dump())
    state.create_run(run)
    budget = SqliteRuntimeBudgetStore(state.database_path, clock, ids, redactor, state)
    budget.initialize_run(
        run.run_id, RunBudgetLimits(max_model_requests=8, max_tool_calls=12, max_total_tokens=65536)
    )
    state.save_task(tools.task)
    for stage in (
        WorkflowStage.INTAKE,
        WorkflowStage.SCOPING,
        WorkflowStage.WORKSPACE_PREPARATION,
        WorkflowStage.IMPLEMENTING,
        WorkflowStage.VERIFYING,
    ):
        run = Run.model_validate(
            run.model_copy(update={"status": RunStatus.RUNNING, "stage": stage}).model_dump()
        )
        state.save_run(run, "test.stage", {})
        if stage == tools.invocation.stage:
            break
    state.save_agent_instance(tools.agent)
    return budget


def configuration(provider: str) -> RuntimeConfiguration:
    return RuntimeConfiguration(
        runtime_name="pydantic-ai",
        provider_model=f"{provider}:gpt-test",
        credential_ref="env:FLEET_ACTION_TEST_KEY",
        max_requests=8,
        max_tool_calls=12,
        max_total_tokens=32768,
        timeout_seconds=10,
        max_retries=1,
    )


def sdk_adapter(
    monkeypatch: pytest.MonkeyPatch, handler: Callable[[httpx2.Request], httpx2.Response]
) -> tuple[PydanticAIRuntimeAdapter, list[DefaultAsyncHttpxClient]]:
    clients: list[DefaultAsyncHttpxClient] = []

    def transport(**kwargs: Any) -> DefaultAsyncHttpxClient:
        client = DefaultAsyncHttpxClient(transport=httpx2.MockTransport(handler), **kwargs)
        clients.append(client)
        return client

    monkeypatch.delenv("OPENAI_CUSTOM_HEADERS", raising=False)
    monkeypatch.setattr(runtime_module, "DefaultAsyncHttpxClient", transport)
    redactor = Redactor([SENTINEL])
    store = EnvironmentSecretStore(redactor, {"FLEET_ACTION_TEST_KEY": SENTINEL})
    return PydanticAIRuntimeAdapter(store, redactor), clients


def tool_response(
    request: httpx2.Request, calls: list[tuple[str, dict[str, object]]], index: int = 1
) -> httpx2.Response:
    if request.url.path == "/v1/responses":
        payload = {
            "id": f"resp-{index}",
            "object": "response",
            "created_at": 0,
            "status": "completed",
            "model": "gpt-test",
            "output": [
                {
                    "type": "function_call",
                    "id": f"fc-{index}-{i}",
                    "call_id": f"call-{index}-{i}",
                    "name": name,
                    "arguments": json.dumps(args),
                }
                for i, (name, args) in enumerate(calls)
            ],
            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        }
    else:
        assert request.url.path == "/v1/chat/completions"
        payload = {
            "id": f"chat-{index}",
            "object": "chat.completion",
            "created": 0,
            "model": "gpt-test",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "tool_calls",
                    "message": {
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "id": f"call-{index}-{i}",
                                "type": "function",
                                "function": {"name": name, "arguments": json.dumps(args)},
                            }
                            for i, (name, args) in enumerate(calls)
                        ],
                    },
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
    return httpx2.Response(200, json=payload, request=request)


def wire_tools(request: httpx2.Request) -> dict[str, dict[str, Any]]:
    body = json.loads(request.content)
    return {tool["name"]: tool for raw in body["tools"] if (tool := raw.get("function", raw))}
