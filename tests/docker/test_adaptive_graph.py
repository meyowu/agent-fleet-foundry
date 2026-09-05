"""Offline FunctionModel graph journeys, with separately gated real Docker proof."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import pytest
from pydantic_ai import ModelMessage, ModelRequest, ModelResponse, ToolCallPart, ToolReturnPart
from pydantic_ai.messages import UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from test_phase5_evidence import (
    _COMMAND_ID,
    _CORE_PATH,
    _CREDENTIAL_REF,
    _CRITERIA,
    _MODULE_PATH,
    _MODULE_SOURCE,
    _SYNTHETIC_CREDENTIAL,
    _fixture,
    _TwoCriterionModel,
)
from test_real_docker import _cleanup_real_installation_scope

from agent_fleet.adapters.runtime.fake import FakeRuntimeAdapter
from agent_fleet.adapters.runtime.pydantic_ai import PydanticAIRuntimeAdapter
from agent_fleet.adapters.sandbox.docker import DockerSandboxProvider
from agent_fleet.application.runtime import RuntimeRegistry
from agent_fleet.application.sandboxes import requirements_for_configuration
from agent_fleet.bootstrap import ApplicationContainer, build_container
from agent_fleet.domain.evidence import EvidenceBundle, EvidenceStrength
from agent_fleet.domain.graph import GraphStatus
from agent_fleet.domain.models import RunStatus, SandboxConfiguration, SandboxPreflight, Verdict
from agent_fleet.domain.offline_canary import BROKEN_CANARY, FIXED_CANARY
from agent_fleet.domain.trust import TrustMode

pytestmark = pytest.mark.asyncio
Strategy = Literal["parallel_engineers", "research_architect_engineer_verifier"]


@dataclass
class _GraphModel:
    strategy: Strategy
    verifier: _TwoCriterionModel = field(default_factory=_TwoCriterionModel)
    calls: dict[str, int] = field(default_factory=dict)
    active_writers: set[str] = field(default_factory=set)
    writers_ready: asyncio.Event = field(default_factory=asyncio.Event)
    child_command_exit_codes: list[int] = field(default_factory=list)

    async def respond(self, messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        assert _SYNTHETIC_CREDENTIAL not in repr(messages)
        prompt = next(
            part.content
            for message in messages
            if isinstance(message, ModelRequest)
            for part in message.parts
            if isinstance(part, UserPromptPart)
        )
        assert isinstance(prompt, str)
        context = json.loads(prompt.split("\n", 1)[1])
        role = context["role"]
        output = info.output_tools[0].name
        task_input = context["task_input"]
        node_id = (task_input.get("graph_context") or {}).get("node_id", role)
        key = f"{role}:{node_id}"
        number = self.calls.get(key, 0) + 1
        self.calls[key] = number
        assert number <= 2
        reply = self.verifier._reply
        if role == "cos":
            return reply(
                [
                    ToolCallPart(
                        output,
                        {
                            "normalized_goal": "Fix division and add the tested metadata module.",
                            "workflow": "code-change",
                            "change_kind": "code_change",
                            "fleet_strategy": self.strategy,
                            "allowed_paths": ["src/canary_calc"],
                            "forbidden_paths": [".git", ".fleet", "tests"],
                            "acceptance_criteria": [
                                {"criterion_id": key, "description": value}
                                for key, value in _CRITERIA.items()
                            ],
                            "required_evidence": [
                                "canonical_patch",
                                "command_evidence",
                                "independent_verifier_verdict",
                            ],
                            "max_parallel_agents": 2,
                            "writer_assignments": [
                                {
                                    "node_id": "core",
                                    "goal": "Fix division only.",
                                    "scope": [_CORE_PATH],
                                    "criterion_ids": ["canary-zero-division"],
                                },
                                {
                                    "node_id": "metadata",
                                    "goal": "Add the metadata module only.",
                                    "scope": [_MODULE_PATH],
                                    "criterion_ids": ["new-module-message"],
                                },
                            ]
                            if self.strategy == "parallel_engineers"
                            else [],
                        },
                        tool_call_id="scope-graph",
                    )
                ]
            )
        if role == "verifier":
            return await self.verifier.respond(messages, info)
        if role in {"researcher", "architect"}:
            assert {tool.name for tool in info.function_tools} == {
                "repo_list_files",
                "repo_read_file",
                "repo_search_text",
                "workspace_get_diff",
            }
            dependencies = task_input["graph_context"]["dependencies"]
            assert len(dependencies) == (0 if role == "researcher" else 1)
            if number == 1:
                return reply(
                    [
                        ToolCallPart(
                            "repo_read_file",
                            {"path": _CORE_PATH, "reason": "Inspect the immutable base."},
                            tool_call_id=f"{role}-read",
                        )
                    ]
                )
            return reply(
                [
                    ToolCallPart(
                        output,
                        {
                            "role": role,
                            "summary": f"{role} inspected the scoped base.",
                            "findings": ["Division needs validation."],
                            "recommendations": ["Keep changes within the assigned module scope."],
                            "proof_gaps": ["This report is reasoning, not executed verification."],
                        },
                        tool_call_id=f"{role}-report",
                    )
                ]
            )
        assert role == "engineer"
        task = task_input["task_spec"]
        selected = {
            path: content
            for path, content in {_CORE_PATH: FIXED_CANARY, _MODULE_PATH: _MODULE_SOURCE}.items()
            if any(path == scope or path.startswith(scope + "/") for scope in task["allowed_paths"])
        }
        assert selected
        if self.strategy != "parallel_engineers":
            assert len(task_input["graph_context"]["dependencies"]) == 1
        if number == 1:
            if self.strategy == "parallel_engineers":
                self.active_writers.add(node_id)
                if len(self.active_writers) == 2:
                    self.writers_ready.set()
                await asyncio.wait_for(self.writers_ready.wait(), timeout=30)
            return reply(
                [
                    ToolCallPart(
                        "workspace_write_file",
                        {
                            "path": path,
                            "content": content,
                            "reason": "Implement this exact assigned file.",
                        },
                        tool_call_id=f"write-{index}",
                    )
                    for index, (path, content) in enumerate(selected.items())
                ]
                + [
                    ToolCallPart(
                        "run_verification",
                        {
                            "command_id": _COMMAND_ID,
                            "reason": "Record the child candidate result for later joined review.",
                        },
                        tool_call_id="child-test",
                    )
                ]
            )
        command = next(
            part.content
            for message in messages
            if isinstance(message, ModelRequest)
            for part in message.parts
            if isinstance(part, ToolReturnPart) and part.tool_name == "run_verification"
        )
        assert isinstance(command, dict)
        self.child_command_exit_codes.append(command["content"]["exit_code"])
        return reply(
            [
                ToolCallPart(
                    output,
                    {
                        "summary": "Produced the assigned candidate only.",
                        "intended_changed_paths": list(selected),
                        "tests_added_or_changed": [],
                        "criterion_results": [
                            item["criterion_id"] for item in task["acceptance_criteria"]
                        ],
                        "evidence_artifact_ids": [
                            command["content"]["command_evidence_artifact_id"]
                        ],
                        "unresolved_limitations": [
                            "Only a fresh parent verifier can check all joined changes."
                        ],
                        "verifier_focus": list(_CRITERIA.values()),
                    },
                    tool_call_id="child-report",
                )
            ]
        )


async def _run_graph(
    container: ApplicationContainer,
    target: Path,
    strategy: Strategy,
    *,
    sandbox: Literal["fake", "docker"],
    image: str | None = None,
    preflight: SandboxPreflight | None = None,
) -> None:
    model = _GraphModel(strategy)
    runtime = PydanticAIRuntimeAdapter.for_test_model(
        FunctionModel(model.respond), redactor=container.redactor
    )
    registry = RuntimeRegistry({"fake": FakeRuntimeAdapter(), "pydantic-ai": runtime})
    container.projects.runtime_registry = container.workflow.runtimes = registry
    container.secrets.resolve(_CREDENTIAL_REF)
    container.projects._initialize_without_canary(
        target,
        runtime_name="pydantic-ai",
        provider_model="openai:offline-test",
        credential_ref=_CREDENTIAL_REF,
        sandbox_name=sandbox,
        docker_image=image,
        trusted_canary_config=True,
        sandbox_image_identity=preflight.image_identity if preflight else None,
        sandbox_daemon_identity=preflight.daemon_identity if preflight else None,
    )
    container.permissions.configure(
        target, mode=TrustMode.BALANCED, allowed_paths=("src/canary_calc",)
    )
    before = container.repository.inspect(target)
    run = await container.workflow.start(
        project_path=target,
        goal="Fix both independently tested criteria.",
        runtime_name=None,
        sandbox_name=sandbox,
        fake_scenario=None,
    )
    isolated = sandbox == "docker"
    assert run.status is RunStatus.READY_FOR_REVIEW and run.verified_complete is isolated
    assert run.evidence_bundle_artifact_id is not None
    bundle = EvidenceBundle.model_validate_json(
        container.artifacts.read_text(run.evidence_bundle_artifact_id)
    )
    assert (
        bundle.graph_delivery is not None
        and bundle.graph_delivery.snapshot.status is GraphStatus.JOINED
    )
    assert bundle.graph_delivery.snapshot.driver_claim is None
    assert (
        bundle.completion_decision is not None
        and "GRAPH_DELIVERY_UNPROVEN" not in bundle.completion_decision.reason_codes
    )
    assert bundle.changed_paths == [_CORE_PATH, _MODULE_PATH]
    assert {item.verdict for item in bundle.criterion_assessments} == {
        Verdict.PASS if isolated else Verdict.INCONCLUSIVE
    }
    assert len(bundle.command_evidence) == 1
    command = bundle.command_evidence[0]
    assert command.run_id == run.run_id and command.principal_role == "verifier"
    assert command.candidate_patch_sha256 == run.patch_sha256 and command.exit_code == 0
    assert command.strength is (
        EvidenceStrength.INDEPENDENTLY_VERIFIED if isolated else EvidenceStrength.SIMULATED
    )
    if isolated:
        transcript = container.artifacts.read_text(command.transcript_artifact_id)
        assert "Ran 3 tests" in transcript and "\nOK" in transcript
    if strategy == "parallel_engineers":
        assert model.active_writers == {"core", "metadata"}
        if isolated:
            assert len(model.child_command_exit_codes) == 2 and all(
                code != 0 for code in model.child_command_exit_codes
            )
    assert container.repository.inspect(target).status_fingerprint == before.status_fingerprint
    assert (target / _CORE_PATH).read_text() == BROKEN_CANARY and not (
        target / _MODULE_PATH
    ).exists()
    graph = bundle.graph_delivery.snapshot
    for identity in [run.run_id, *(node.binding.child_run_id for node in graph.nodes)]:
        assert not container.state.outstanding_leases(identity)
        for artifact in container.state.list_artifacts(identity):
            assert _SYNTHETIC_CREDENTIAL not in container.artifacts.read_text(artifact.artifact_id)
    budget = container.budgets.snapshot(run.run_id)
    assert budget.agent_invocations == (4 if strategy == "parallel_engineers" else 5)
    assert budget.model_requests == (7 if strategy == "parallel_engineers" else 9)
    assert budget.unknown_requests == budget.outstanding_requests == 0
    reopened = build_container(container.state_root)
    assert reopened.inspection.status(run.run_id)["verified_complete"] is isolated
    applied, result = reopened.patches.apply(run.run_id)
    assert applied.status is RunStatus.COMPLETED and result.applied
    assert (target / _CORE_PATH).read_text() == FIXED_CANARY
    assert (target / _MODULE_PATH).read_text() == _MODULE_SOURCE


@pytest.mark.integration
@pytest.mark.parametrize("strategy", ["parallel_engineers", "research_architect_engineer_verifier"])
async def test_offline_function_model_runs_adaptive_graph(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    strategy: Strategy,
) -> None:
    target, container = _fixture(tmp_path, monkeypatch)
    await _run_graph(container, target, strategy, sandbox="fake")


@pytest.mark.docker_integration
@pytest.mark.parametrize("strategy", ["parallel_engineers", "research_architect_engineer_verifier"])
async def test_docker_function_model_independently_verifies_joined_graph(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    real_docker_image: str,
    strategy: Strategy,
) -> None:
    target, container = _fixture(tmp_path, monkeypatch)
    provider = container.sandboxes.get("docker")
    assert isinstance(provider, DockerSandboxProvider)
    configuration = SandboxConfiguration(provider="docker", image=real_docker_image)
    preflight = await provider.preflight(
        configuration, requirements_for_configuration(configuration)
    )
    assert preflight.ready
    try:
        await _run_graph(
            container,
            target,
            strategy,
            sandbox="docker",
            image=real_docker_image,
            preflight=preflight,
        )
        assert (
            await provider._list_exact(
                provider._require_executable(),
                {"agent-fleet.installation": provider.recovery_scope_id},
            )
            == []
        )
    finally:
        await _cleanup_real_installation_scope(provider, provider.recovery_scope_id)
