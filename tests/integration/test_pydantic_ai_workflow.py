from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import cast

import pytest
from pydantic_ai import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from agent_fleet.adapters.repository.git import GitRepositoryAdapter
from agent_fleet.adapters.runtime.fake import FakeRuntimeAdapter
from agent_fleet.adapters.runtime.pydantic_ai import PydanticAIRuntimeAdapter
from agent_fleet.adapters.system import UuidIdGenerator
from agent_fleet.application.runtime import RuntimeRegistry
from agent_fleet.bootstrap import build_container
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.evidence import CommandEvidence
from agent_fleet.domain.models import (
    ArtifactKind,
    IntentStatus,
    RunStatus,
    RuntimeToolResult,
    TaskSpec,
)
from agent_fleet.domain.offline_canary import FIXED_CANARY
from agent_fleet.domain.security import sha256_bytes


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "read_probe",
    [None, "src/canary_calc/core.py", ".fleet", ".git", "tests/test_core.py"],
    ids=["original", "scoped-file", "fleet-directory", "git-directory", "out-of-scope-file"],
)
async def test_offline_pydantic_ai_roles_cross_gateway_and_preserve_fake_proof_gap(
    tmp_path: Path,
    read_probe: str | None,
) -> None:
    calls_by_output: dict[str, int] = {}
    verifier_receipt: str | None = None
    verifier_task: TaskSpec | None = None
    model_errors: list[Exception] = []
    guidance_by_output = {
        "submit_scope_decision": "Scope the goal and delegate",
        "submit_implementation_report": "Make the smallest candidate-only change",
        "submit_verifier_verdict": "Verify independently",
    }

    async def scripted_model_function(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> ModelResponse:
        nonlocal verifier_receipt, verifier_task
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
                    "repo_list_files",
                    "repo_read_file",
                    "repo_search_text",
                    "workspace_get_diff",
                    "workspace_write_file",
                    "workspace_apply_edit",
                    "workspace_delete_file",
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
                            {
                                "command_id": "python-test",
                                "reason": "Record the declared verification evidence.",
                            },
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
        assert "TaskSpec.allowed_paths and forbidden_paths constrain repository reads" in (
            info.instructions or ""
        )
        descriptions = {tool.name: tool.description or "" for tool in info.function_tools}
        assert (
            "TaskSpec.allowed_paths and forbidden_paths constrain reads too"
            in descriptions["repo_read_file"]
        )
        assert "Never pass a directory, .fleet, .git" in descriptions["repo_read_file"]
        assert (
            "Patch inspection alone is not independently executed behavioral proof"
            in (descriptions["workspace_get_diff"])
        )
        user_context = next(
            part.content
            for message in messages
            if isinstance(message, ModelRequest)
            for part in message.parts
            if isinstance(part, UserPromptPart) and isinstance(part.content, str)
        )
        context = json.loads(user_context.split("\n", 1)[1])["task_input"]
        current_task = TaskSpec.model_validate(context["task_spec"])
        assert current_task.allowed_paths == ["src/canary_calc/core.py"]
        assert {".fleet", ".git"} <= set(current_task.forbidden_paths)
        assert [command.command_id for command in current_task.verification_commands] == [
            "python-build",
            "python-test",
        ]
        assert sha256_bytes(context["patch"].encode()) == context["patch_sha256"]
        assert "src/canary_calc/core.py" in context["patch"]
        assert "Inspection alone" in context["criterion_mapping_contract"]["missing_proof"]
        if verifier_task is not None:
            assert current_task == verifier_task
        verifier_task = current_task
        if request_number == 1:
            assert [tool.name for tool in info.function_tools] == [
                "repo_list_files",
                "repo_read_file",
                "repo_search_text",
                "workspace_get_diff",
                "run_verification",
            ]
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "run_verification",
                        {
                            "command_id": "python-test",
                            "reason": "Record independent simulated verifier evidence.",
                        },
                        tool_call_id="verifier-check",
                    )
                ]
            )
        returns = {
            part.tool_call_id: RuntimeToolResult.model_validate(part.content)
            for message in messages
            if isinstance(message, ModelRequest)
            for part in message.parts
            if isinstance(part, ToolReturnPart)
        }
        receipt_id = returns["verifier-check"].content["command_evidence_artifact_id"]
        assert isinstance(receipt_id, str)
        verifier_receipt = receipt_id
        if read_probe is not None and request_number == 2:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "repo_read_file",
                        {"path": read_probe, "reason": "Probe the unchanged read boundary."},
                        tool_call_id="verifier-read",
                    )
                ]
            )
        if read_probe is not None:
            assert read_probe == "src/canary_calc/core.py", "A denied read must stop this run."
            content = returns["verifier-read"].content
            assert content == {
                "path": read_probe,
                "content": FIXED_CANARY,
                "sha256": sha256_bytes(FIXED_CANARY.encode()),
            }
            if request_number == 3:
                return ModelResponse(
                    parts=[
                        ToolCallPart(
                            "workspace_get_diff",
                            {"reason": "Inspect canonical changed paths without directory reads."},
                            tool_call_id="verifier-diff",
                        )
                    ]
                )
            diff = returns["verifier-diff"].content
            assert diff["patch"] == context["patch"]
            assert diff["patch_sha256"] == context["patch_sha256"]
            assert diff["changed_paths"] == ["src/canary_calc/core.py"]
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

    async def model_function(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        try:
            return await scripted_model_function(messages, info)
        except Exception as error:
            # The production boundary correctly hides provider exceptions. Keep
            # test assertion failures visible without changing that boundary.
            model_errors.append(error)
            raise

    repository = GitRepositoryAdapter(tmp_path, UuidIdGenerator()).create_canary_fixture(
        tmp_path / "pydantic-ai-repository"
    )
    container = build_container(tmp_path / "state")
    runtime = PydanticAIRuntimeAdapter.for_test_model(FunctionModel(model_function))
    registry = RuntimeRegistry({"fake": FakeRuntimeAdapter(), "pydantic-ai": runtime})
    container.projects.runtime_registry = registry
    container.workflow.runtimes = registry
    container.doctor.runtime_registry = registry
    container.projects._initialize_without_canary(
        repository,
        runtime_name="pydantic-ai",
        provider_model="openai:offline-test",
        credential_ref="env:FLEET_OFFLINE_TEST_KEY",
        sandbox_name="fake",
    )
    original_core = (repository / "src/canary_calc/core.py").read_bytes()

    try:
        run = await container.workflow.start(
            project_path=repository,
            goal="Fix the canary behavior",
            runtime_name=None,
            provider_model=None,
            credential_ref=None,
            sandbox_name="fake",
            fake_scenario=None,
        )
    except FleetError as error:
        if model_errors:
            raise model_errors[0] from error
        assert read_probe not in {None, "src/canary_calc/core.py"}
        assert error.code is ErrorCode.COMMAND_DENIED
        failed_run_id = error.details["run_id"]
        assert isinstance(failed_run_id, str)
        run = container.state.get_run(failed_run_id)

    assert (repository / "src/canary_calc/core.py").read_bytes() == original_core
    assert verifier_task is not None and run.task_id is not None
    assert container.state.get_task(run.task_id) == verifier_task
    assert verifier_receipt is not None
    receipt = CommandEvidence.model_validate_json(container.artifacts.read_text(verifier_receipt))
    assert receipt.run_id == run.run_id and receipt.task_id == run.task_id
    assert receipt.principal_role == "verifier"
    assert receipt.command_id == "python-test"
    assert receipt.candidate_patch_sha256 == run.patch_sha256
    assert receipt.strength.value == "simulated"
    assert container.state.active_leases(run.run_id) == []
    if read_probe not in {None, "src/canary_calc/core.py"}:
        assert run.status is RunStatus.FAILED
        assert run.verifier_verdict_artifact_id is None and not run.verified_complete
        assert calls_by_output == {
            "submit_scope_decision": 1,
            "submit_implementation_report": 2,
            "submit_verifier_verdict": 2,
        }
        events = container.state.list_events(run.run_id)
        assert any(
            event.event_type == "run.failed" and event.payload["code"] == "COMMAND_DENIED"
            for event in events
        )
        denied = [
            event
            for event in events
            if event.event_type == "permission.decision" and event.payload["outcome"] == "deny"
        ]
        assert len(denied) == 1
        decision = denied[0].payload
        assert decision["decision_code"] == "PHASE1_DEFAULT_DENY"
        assert decision["protected"] is True
        assert decision["resource"] == {"kind": "workspace_path", "identifier": read_probe}
        intent_id = decision["intent_id"]
        assert isinstance(intent_id, str)
        stored = container.state.get_intent(intent_id)
        assert stored.status is IntentStatus.DENIED and stored.result is None
        assert stored.intent.agent_instance_id == receipt.agent_instance_id
        assert stored.intent.action == "repo.read_file"
        with sqlite3.connect(container.state.database_path) as connection:
            assert (
                connection.execute(
                    "SELECT COUNT(*) FROM tool_dispatch_claims WHERE intent_id = ?", (intent_id,)
                ).fetchone()[0]
                == 0
            )
        assert [
            event.payload["action"]
            for event in events
            if event.event_type == "tool.intent_executed"
        ] == ["workspace.write_file", "command.run", "command.run"]
        return

    assert run.status is RunStatus.READY_FOR_REVIEW
    assert run.runtime_name == "pydantic-ai"
    assert run.provider_model == "openai:offline-test"
    assert run.verified_complete is False
    assert calls_by_output == {
        "submit_scope_decision": 1,
        "submit_implementation_report": 2,
        "submit_verifier_verdict": 2 if read_probe is None else 4,
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
    ] + ([] if read_probe is None else ["repo.read_file", "workspace.get_diff"])
