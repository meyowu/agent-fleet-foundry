"""Offline model retries retain exact authority, not transient wording or call IDs."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import pytest
from pydantic import JsonValue
from pydantic_ai import ModelMessage, ModelRequest, ModelResponse, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from agent_fleet.adapters.repository.git import GitRepositoryAdapter
from agent_fleet.adapters.runtime.fake import FakeRuntimeAdapter
from agent_fleet.adapters.runtime.pydantic_ai import PydanticAIRuntimeAdapter
from agent_fleet.adapters.system import UuidIdGenerator
from agent_fleet.application.runtime import RuntimeRegistry
from agent_fleet.bootstrap import ApplicationContainer, build_container
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import (
    AgentInstance,
    ApprovalChoice,
    CanonicalResource,
    IntentStatus,
    Run,
    RunStatus,
    SandboxHandle,
    ScriptedAction,
    TaskSpec,
    Workspace,
)
from agent_fleet.domain.offline_canary import FIXED_CANARY
from agent_fleet.domain.trust import TrustMode

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]
_CHOICES = [ApprovalChoice.ALLOW_ONCE, ApprovalChoice.ALLOW_RUN, ApprovalChoice.ALLOW_ALWAYS]


@dataclass
class _ApprovalModel:
    calls: int = 0
    verification_requests: list[tuple[str, str, str]] = field(default_factory=list)
    change_command_after_pause: bool = False

    async def respond(self, messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        self.calls += 1
        call_id = f"model-call-{self.calls}"
        output_name = info.output_tools[0].name
        if output_name == "submit_scope_decision":
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        output_name,
                        {
                            "normalized_goal": "Fix the bounded canary behavior.",
                            "workflow": "code-change",
                            "change_kind": "code_change",
                            "fleet_strategy": "single_engineer",
                            "allowed_paths": ["src/canary_calc/core.py"],
                            "forbidden_paths": [".git", ".fleet"],
                            "acceptance_criteria": [
                                {
                                    "criterion_id": "canary-zero-division",
                                    "description": "Division by zero raises the reviewed error.",
                                }
                            ],
                            "required_evidence": ["canonical_patch", "command_evidence"],
                        },
                        tool_call_id=call_id,
                    )
                ]
            )
        assert output_name == "submit_implementation_report"
        completed_tools = {
            part.tool_name
            for message in messages
            if isinstance(message, ModelRequest)
            for part in message.parts
            if isinstance(part, ToolReturnPart)
        }
        if "workspace_write_file" not in completed_tools:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "workspace_write_file",
                        {
                            "path": "src/canary_calc/core.py",
                            "content": FIXED_CANARY,
                            "reason": "Apply the bounded canary repair.",
                        },
                        tool_call_id=call_id,
                    )
                ]
            )
        if "run_verification" not in completed_tools:
            command_id = (
                "python-build"
                if self.change_command_after_pause and self.verification_requests
                else "python-test"
            )
            reason = f"Review this exact command, model invocation {self.calls}."
            self.verification_requests.append((call_id, reason, command_id))
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "run_verification",
                        {"command_id": command_id, "reason": reason},
                        tool_call_id=call_id,
                    )
                ]
            )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    output_name,
                    {
                        "summary": "Applied the bounded canary repair.",
                        "intended_changed_paths": ["src/canary_calc/core.py"],
                        "tests_added_or_changed": [],
                        "criterion_results": ["canary-zero-division: candidate updated"],
                        "evidence_artifact_ids": [],
                        "unresolved_limitations": ["Execution was simulated by FakeSandbox."],
                        "verifier_focus": ["Review the exact exception behavior."],
                    },
                    tool_call_id=call_id,
                )
            ]
        )


def _rebuild(state_root: Path, model: _ApprovalModel) -> ApplicationContainer:
    container = build_container(state_root)
    runtime = PydanticAIRuntimeAdapter.for_test_model(FunctionModel(model.respond))
    registry = RuntimeRegistry({"fake": FakeRuntimeAdapter(), "pydantic-ai": runtime})
    container.projects.runtime_registry = registry
    container.workflow.runtimes = registry
    container.doctor.runtime_registry = registry
    return container


async def _start(
    tmp_path: Path,
) -> tuple[ApplicationContainer, _ApprovalModel, Run]:
    repository = GitRepositoryAdapter(tmp_path, UuidIdGenerator()).create_canary_fixture(
        tmp_path / "offline-approval-repository"
    )
    model = _ApprovalModel()
    container = _rebuild(tmp_path / "state", model)
    container.projects._initialize_without_canary(
        repository,
        runtime_name="pydantic-ai",
        provider_model="openai:offline-test",
        credential_ref="env:FLEET_OFFLINE_TEST_KEY",
        sandbox_name="fake",
    )
    container.permissions.configure(repository, mode=TrustMode.SAFE, allowed_paths=(".",))
    paused = await container.workflow.start(
        project_path=repository,
        goal="Fix the canary behavior",
        runtime_name=None,
        sandbox_name="fake",
        fake_scenario=None,
    )
    assert paused.status is RunStatus.PAUSED_FOR_APPROVAL
    assert paused.pending_approval_id is not None
    request = container.state.get_approval(paused.pending_approval_id)
    assert request.action == "command.run" and request.resource.identifier == "python-test"
    assert len(model.verification_requests) == 1
    return container, model, paused


@pytest.mark.parametrize("choice", _CHOICES)
async def test_offline_model_approval_resume_ignores_changed_call_id_and_display_reason(
    tmp_path: Path, choice: ApprovalChoice
) -> None:
    container, model, paused = await _start(tmp_path)
    assert paused.pending_approval_id is not None
    request = container.state.get_approval(paused.pending_approval_id)
    original = container.state.get_intent(request.intent_id)
    _rebuild(container.state_root, model).approvals.approve(request.request_id, choice=choice)

    reopened = _rebuild(container.state_root, model)
    completed = await reopened.workflow.resume(paused.run_id)
    assert completed.status is RunStatus.READY_FOR_REVIEW
    assert completed.verified_complete is False
    assert len(model.verification_requests) == 2
    first_call, first_reason, first_command = model.verification_requests[0]
    next_call, next_reason, next_command = model.verification_requests[1]
    assert first_call != next_call and first_reason != next_reason
    assert first_command == next_command == "python-test"
    stored = reopened.state.get_intent(request.intent_id)
    assert stored.status is IntentStatus.EXECUTED
    assert stored.intent == original.intent
    assert stored.intent_hash == original.intent_hash
    assert stored.intent.reason == first_reason
    assert reopened.state.count_executed_intents(paused.run_id, "command.run") == 1
    assert reopened.state.count_executed_intents(paused.run_id, "workspace.write_file") == 1
    events = reopened.state.list_events(paused.run_id)
    requested = [event for event in events if event.event_type == "approval.requested"]
    assert len(requested) == 1
    assert requested[0].payload["request_id"] == request.request_id
    for event_type in ("capability.consumed", "intent.dispatch_claimed"):
        assert (
            len(
                [
                    event
                    for event in events
                    if event.event_type == event_type
                    and event.payload.get("intent_id") == request.intent_id
                ]
            )
            == 1
        )


@pytest.mark.parametrize("choice", _CHOICES)
async def test_changed_model_command_requires_its_own_exact_approval(
    tmp_path: Path, choice: ApprovalChoice
) -> None:
    container, model, paused = await _start(tmp_path)
    assert paused.pending_approval_id is not None
    original = container.state.get_approval(paused.pending_approval_id)
    grant = container.approvals.approve(original.request_id, choice=choice)
    model.change_command_after_pause = True
    reopened = _rebuild(container.state_root, model)
    still_paused = await reopened.workflow.resume(paused.run_id)
    assert still_paused.status is RunStatus.PAUSED_FOR_APPROVAL
    assert still_paused.pending_approval_id is not None
    changed = reopened.state.get_approval(still_paused.pending_approval_id)
    assert changed.request_id != original.request_id
    assert changed.resource.identifier == "python-build"
    assert changed.intent_hash != original.intent_hash
    assert reopened.state.count_executed_intents(paused.run_id, "command.run") == 0
    assert (
        next(
            item
            for item in reopened.state.list_grants(paused.run_id)
            if item.grant_id == grant.grant_id
        ).remaining_uses
        == grant.remaining_uses
    )
    assert not [
        event
        for event in reopened.state.list_events(paused.run_id)
        if event.event_type == "capability.consumed"
    ]


@pytest.mark.parametrize("choice", _CHOICES)
@pytest.mark.parametrize("drift", ["resource", "parameters"])
async def test_same_logical_model_retry_cannot_change_execution_bearing_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    choice: ApprovalChoice,
    drift: Literal["resource", "parameters"],
) -> None:
    container, model, paused = await _start(tmp_path)
    assert paused.pending_approval_id is not None
    request = container.state.get_approval(paused.pending_approval_id)
    original = container.state.get_intent(request.intent_id)
    container.approvals.approve(request.request_id, choice=choice)
    reopened = _rebuild(container.state_root, model)
    execute = reopened.workflow.gateway.execute

    async def inject_boundary_drift(
        *,
        run: Run,
        task: TaskSpec,
        agent: AgentInstance,
        workspace: Workspace,
        sandbox_handle: SandboxHandle,
        scripted: ScriptedAction,
    ) -> dict[str, JsonValue]:
        if scripted.action == "command.run":
            if drift == "resource":
                scripted = scripted.model_copy(
                    update={
                        "resource": CanonicalResource(
                            kind="project_command", identifier="python-build"
                        )
                    }
                )
            else:
                scripted = scripted.model_copy(
                    update={"parameters": {**scripted.parameters, "command_spec_sha256": "0" * 64}}
                )
        return await execute(
            run=run,
            task=task,
            agent=agent,
            workspace=workspace,
            sandbox_handle=sandbox_handle,
            scripted=scripted,
        )

    monkeypatch.setattr(reopened.workflow.gateway, "execute", inject_boundary_drift)
    with pytest.raises(FleetError) as captured:
        await reopened.workflow.resume(paused.run_id)
    assert captured.value.code is ErrorCode.COMMAND_DENIED
    assert len(model.verification_requests) == 2
    assert model.verification_requests[0][:2] != model.verification_requests[1][:2]
    assert reopened.state.count_executed_intents(paused.run_id, "command.run") == 0
    assert reopened.state.get_intent(request.intent_id) == original
    assert not [
        event
        for event in reopened.state.list_events(paused.run_id)
        if event.event_type == "capability.consumed"
    ]
