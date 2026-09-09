from __future__ import annotations

import json
from copy import deepcopy
from importlib import resources
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic_ai import ModelMessage, ModelRequest, ModelResponse, ToolCallPart
from pydantic_ai.messages import UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from agent_fleet.adapters.repository.git import GitRepositoryAdapter
from agent_fleet.adapters.runtime.fake import FakeRuntimeAdapter
from agent_fleet.adapters.runtime.pydantic_ai import PydanticAIRuntimeAdapter
from agent_fleet.adapters.system import UuidIdGenerator
from agent_fleet.application.runtime import RuntimeRegistry
from agent_fleet.bootstrap import build_container
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.fleet_plan import FleetPlan
from agent_fleet.domain.models import RunStatus, ScopeDecision


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("selected_workflow", ["code-change", "engineer_verifier"])
async def test_actual_cos_prompt_receives_reviewed_workflows_and_rejects_strategy_as_workflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, selected_workflow: str
) -> None:
    captured_inputs: list[dict[str, Any]] = []
    captured_instructions: list[str | None] = []

    async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        # Exercise the packaged prompt, structured schema and real adapter, not a
        # fake CoS return. Stop at the ordinary reviewed-plan boundary after CoS.
        output = next(tool for tool in info.output_tools if tool.name == "submit_scope_decision")
        assert (
            "available_workflows"
            in output.parameters_json_schema["properties"]["workflow"]["description"]
        )
        assert [tool.name for tool in info.function_tools] == ["fleet_content_sha256"]
        helper = info.function_tools[0]
        assert helper.parameters_json_schema["required"] == ["operation", "path", "content"]
        assert helper.parameters_json_schema["additionalProperties"] is False
        prompt = next(
            part.content
            for message in messages
            if isinstance(message, ModelRequest)
            for part in message.parts
            if isinstance(part, UserPromptPart)
        )
        assert isinstance(prompt, str)
        captured_inputs.append(json.loads(prompt.split("\n", 1)[1]))
        captured_instructions.append(info.instructions)
        decision = ScopeDecision(
            normalized_goal="Fix the canary zero-division guard.",
            workflow=selected_workflow,
            change_kind="code_change",
            fleet_strategy="engineer_verifier",
            writer_assignments=[],
            allowed_paths=["src/canary_calc/core.py"],
            forbidden_paths=[".git", ".fleet"],
            acceptance_criteria=[{"criterion_id": "guard", "description": "Raise ValueError."}],
            required_evidence=[
                "canonical_patch",
                "command_evidence",
                "independent_verifier_verdict",
            ],
        )
        return ModelResponse(parts=[ToolCallPart(output.name, decision.model_dump(mode="json"))])

    repository = GitRepositoryAdapter(tmp_path, UuidIdGenerator()).create_canary_fixture(
        tmp_path / "repository"
    )
    container = build_container(tmp_path / "state")
    runtime = PydanticAIRuntimeAdapter.for_test_model(FunctionModel(respond))
    registry = RuntimeRegistry({"fake": FakeRuntimeAdapter(), "pydantic-ai": runtime})
    container.projects.runtime_registry = registry
    container.workflow.runtimes = registry

    files = container.workflow.config.default_files(
        repository.name, runtime_name="pydantic-ai", provider_model="openai:offline-test"
    )
    spec_data = yaml.safe_load(files["fleet.yaml"])
    definition = yaml.safe_load(files["workflows/code-change.yaml"])
    # Real reviewed configuration contains non-default choices in unsorted order.
    # Merely hard-coding ['code-change'] in the runtime input would fail this test.
    for name in ("zeta-review", "alpha-review"):
        workflow = deepcopy(spec_data["spec"]["workflows"]["code-change"])
        workflow["definition"] = f"workflows/{name}.yaml"
        spec_data["spec"]["workflows"][name] = workflow
        named_definition = deepcopy(definition)
        named_definition["metadata"]["name"] = name
        files[f"workflows/{name}.yaml"] = yaml.safe_dump(named_definition, sort_keys=False)
    files["fleet.yaml"] = yaml.safe_dump(spec_data, sort_keys=False)

    def default_files(*_args: object, **_kwargs: object) -> dict[str, str]:
        return files.copy()

    monkeypatch.setattr(container.projects.config, "default_files", default_files)
    container.projects._initialize_without_canary(
        repository,
        runtime_name="pydantic-ai",
        provider_model="openai:offline-test",
        credential_ref="env:OFFLINE_COS_GUIDANCE_KEY",
        sandbox_name="fake",
    )
    reviewed_spec, reviewed_snapshot = container.workflow.config.load_snapshot(
        repository / ".fleet/fleet.yaml"
    )
    goal = "Fix zero-division behavior in src/canary_calc/core.py for this task only."
    if selected_workflow == "engineer_verifier":
        with pytest.raises(FleetError, match="undeclared workflow") as caught:
            await container.workflow.start(
                project_path=repository,
                goal=goal,
                runtime_name=None,
                sandbox_name="fake",
                fake_scenario=None,
                review_plan=True,
            )
        assert caught.value.code is ErrorCode.CONFIG_INVALID
        run = container.state.get_run(caught.value.details["run_id"])
        assert run.status is RunStatus.FAILED and run.task_spec_artifact_id is None
        assert any(
            event.event_type == "run.failed" and event.payload["code"] == "CONFIG_INVALID"
            for event in container.state.list_events(run.run_id)
        )
    else:
        run = await container.workflow.start(
            project_path=repository,
            goal=goal,
            runtime_name=None,
            sandbox_name="fake",
            fake_scenario=None,
            review_plan=True,
        )
        assert run.status is RunStatus.PAUSED_FOR_PLAN
        assert run.fleet_plan_artifact_id is not None
        plan = FleetPlan.model_validate_json(
            container.artifacts.read_text(run.fleet_plan_artifact_id)
        )
        assert [(node.role_id, node.can_write) for node in plan.nodes] == [
            ("engineer", True),
            ("verifier", False),
        ]
        assert plan.nodes[-1].independent_verifier is True
        assert run.task_id is not None
        assert container.state.get_task(run.task_id).workflow == "code-change"

    assert len(captured_inputs) == 1
    assert captured_inputs[0]["role"] == "cos"
    task_input = captured_inputs[0]["task_input"]
    assert (
        task_input["available_workflows"]
        == sorted(reviewed_spec.spec.workflows)
        == ["alpha-review", "code-change", "zeta-review"]
    )
    assert task_input["available_roles"] == sorted(
        container.workflow.config.role_templates(reviewed_spec, reviewed_snapshot)
    )
    assert task_input["goal"] == goal
    assert "organization_context" in task_input
    assert (repository / "src/canary_calc/core.py").read_text() not in json.dumps(task_input)
    packaged_prompt = (
        resources.files("agent_fleet.adapters.runtime.prompts").joinpath("cos.md").read_text()
    )
    assert captured_instructions == [packaged_prompt.strip()]
    assert "writer_assignments must be []" in packaged_prompt
    assert "Ordinary code scoping\ndoes not require source file contents" in packaged_prompt
    assert "Only when the user explicitly requests a lasting organization rule" in packaged_prompt
    assert (
        "Submit ScopeDecision directly for an ordinary task; no content hash is required."
        in packaged_prompt
    )
    assert not container.state.outstanding_leases(run.run_id)
    assert not any(
        event.event_type == "tool.intent_executed"
        for event in container.state.list_events(run.run_id)
    )
    if run.status is RunStatus.PAUSED_FOR_PLAN:
        await container.cancellation.cancel(run.run_id)
