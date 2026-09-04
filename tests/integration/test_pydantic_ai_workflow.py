from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest
from pydantic_ai import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from agent_fleet.adapters.repository.git import GitRepositoryAdapter
from agent_fleet.adapters.runtime.fake import FakeRuntimeAdapter
from agent_fleet.adapters.runtime.pydantic_ai import PydanticAIRuntimeAdapter
from agent_fleet.adapters.system import UuidIdGenerator
from agent_fleet.application.runtime import RuntimeRegistry
from agent_fleet.bootstrap import build_container
from agent_fleet.domain.models import ArtifactKind, RunStatus
from agent_fleet.domain.offline_canary import FIXED_CANARY


@pytest.mark.integration
@pytest.mark.asyncio
async def test_offline_pydantic_ai_roles_cross_gateway_and_preserve_fake_proof_gap(
    tmp_path: Path,
) -> None:
    calls_by_output: dict[str, int] = {}
    guidance_by_output = {
        "submit_scope_decision": "Scope the goal and delegate",
        "submit_implementation_report": "Make the smallest candidate-only change",
        "submit_verifier_verdict": "Verify independently",
    }

    async def model_function(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> ModelResponse:
        assert messages
        assert "fake_scenario" not in repr(messages)
        output_name = info.output_tools[0].name
        rendered_messages = repr(messages)
        assert "untrusted_project_guidance" in rendered_messages
        assert guidance_by_output[output_name] in rendered_messages
        request_number = calls_by_output.get(output_name, 0) + 1
        calls_by_output[output_name] = request_number

        if output_name == "submit_scope_decision":
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        output_name,
                        {
                            "normalized_goal": "Fix the canary behavior.",
                            "workflow": "code-change",
                            "change_kind": "code_change",
                            "fleet_strategy": "engineer_verifier",
                            "allowed_paths": ["src/canary_calc/core.py"],
                            "forbidden_paths": [".git", ".fleet"],
                            "acceptance_criteria": [
                                {
                                    "criterion_id": "canary-zero-division",
                                    "description": (
                                        "divide(1, 0) raises ValueError with the stable message"
                                    ),
                                }
                            ],
                            "required_evidence": [
                                "canonical_patch",
                                "command_evidence",
                                "independent_verifier_verdict",
                            ],
                        },
                        tool_call_id="scope-output",
                    )
                ]
            )

        if output_name == "submit_implementation_report":
            if request_number == 1:
                assert {tool.name for tool in info.function_tools} == {
                    "workspace_write_file",
                    "run_verification",
                }
                return ModelResponse(
                    parts=[
                        ToolCallPart(
                            "workspace_write_file",
                            {
                                "path": "src/canary_calc/core.py",
                                "content": FIXED_CANARY,
                                "reason": "Apply the smallest bounded canary repair.",
                            },
                            tool_call_id="engineer-write",
                        ),
                        ToolCallPart(
                            "run_verification",
                            {"reason": "Record the declared verification evidence."},
                            tool_call_id="engineer-check",
                        ),
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
                            "criterion_results": [
                                "canary-zero-division: candidate implementation updated"
                            ],
                            "evidence_artifact_ids": [],
                            "unresolved_limitations": ["FakeSandbox did not execute project code."],
                            "verifier_focus": ["Check the exact exception type and message."],
                        },
                        tool_call_id="engineer-output",
                    )
                ]
            )

        assert output_name == "submit_verifier_verdict"
        if request_number == 1:
            assert [tool.name for tool in info.function_tools] == ["run_verification"]
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "run_verification",
                        {"reason": "Record independent simulated verifier evidence."},
                        tool_call_id="verifier-check",
                    )
                ]
            )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    output_name,
                    {
                        "verdict": "pass",
                        "criterion_results": ["canary-zero-division: passed review"],
                        "evidence_artifact_ids": [],
                        "regressions": [],
                        "required_repairs": [],
                        "proof_gaps": ["FakeSandbox did not execute project code."],
                        "rationale": "The candidate is reviewable; execution remains simulated.",
                    },
                    tool_call_id="verifier-output",
                )
            ]
        )

    repository = GitRepositoryAdapter(tmp_path, UuidIdGenerator()).create_canary_fixture(
        tmp_path / "pydantic-ai-repository"
    )
    container = build_container(tmp_path / "state")
    runtime = PydanticAIRuntimeAdapter.for_test_model(FunctionModel(model_function))
    registry = RuntimeRegistry({"fake": FakeRuntimeAdapter(), "pydantic-ai": runtime})
    container.projects.runtime_registry = registry
    container.workflow.runtimes = registry
    container.doctor.runtime_registry = registry
    container.projects.initialize(
        repository,
        runtime_name="pydantic-ai",
        provider_model="openai:offline-test",
        credential_ref="env:FLEET_OFFLINE_TEST_KEY",
        sandbox_name="fake",
    )

    run = await container.workflow.start(
        project_path=repository,
        goal="Fix the canary behavior",
        runtime_name=None,
        provider_model=None,
        credential_ref=None,
        sandbox_name="fake",
        fake_scenario=None,
    )

    assert run.status is RunStatus.READY_FOR_REVIEW
    assert run.runtime_name == "pydantic-ai"
    assert run.provider_model == "openai:offline-test"
    assert run.verified_complete is False
    assert calls_by_output == {
        "submit_scope_decision": 1,
        "submit_implementation_report": 2,
        "submit_verifier_verdict": 2,
    }
    assert len(run.runtime_usage_artifact_ids) == 3
    artifacts = container.state.list_artifacts(run.run_id)
    usage_artifacts = [item for item in artifacts if item.kind is ArtifactKind.RUNTIME_USAGE]
    assert [item.artifact_id for item in usage_artifacts] == run.runtime_usage_artifact_ids
    provider_metadata = [
        json.loads(container.artifacts.read_text(item.artifact_id))["provider_metadata"]
        for item in usage_artifacts
    ]
    assert all(item["provider"] == "pydantic-ai-test" for item in provider_metadata)
    assert all(item["model"] == "offline:test" for item in provider_metadata)
    assert all(item["finish_reason"] is None for item in provider_metadata)
    status = container.inspection.status(run.run_id)
    assert status["runtime"] == "pydantic-ai"
    assert status["provider_model"] == "openai:offline-test"
    assert status["runtime_usage_artifact_ids"] == run.runtime_usage_artifact_ids
    evidence = cast(dict[str, object], status["evidence"])
    assert evidence["changed_paths"] == ["src/canary_calc/core.py"]
    command_results = cast(list[dict[str, object]], evidence["command_results"])
    assert {item["strength"] for item in command_results} == {"simulated"}
    assert "SIMULATED_EVIDENCE_ONLY" in cast(list[str], evidence["completion_reason_codes"])
    assert container.state.active_leases(run.run_id) == []

    events = container.state.list_events(run.run_id)
    executed_actions = [
        event.payload["action"] for event in events if event.event_type == "tool.intent_executed"
    ]
    assert executed_actions == [
        "workspace.write_file",
        "command.run",
        "command.run",
    ]
