"""Offline CoS proposals cross the real structured-output and pure-tool boundaries."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import yaml
from pydantic_ai import ModelMessage, ModelRequest, ModelResponse, ToolCallPart, ToolReturnPart
from pydantic_ai.messages import UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from agent_fleet.adapters.repository.git import GitRepositoryAdapter
from agent_fleet.adapters.runtime.fake import FakeRuntimeAdapter
from agent_fleet.adapters.runtime.pydantic_ai import PydanticAIRuntimeAdapter
from agent_fleet.adapters.system import UuidIdGenerator
from agent_fleet.application.conversations import ChatExecutionOptions
from agent_fleet.application.runtime import RuntimeRegistry
from agent_fleet.bootstrap import ApplicationContainer, build_container
from agent_fleet.domain.errors import FleetError
from agent_fleet.domain.ids import IdPrefix
from agent_fleet.domain.models import Run
from agent_fleet.domain.security import sha256_bytes


class ProposalModel:
    def __init__(self, invalid: str | None = None) -> None:
        self.invalid = invalid
        self.context: dict[str, Any] = {}
        self.contents: dict[str, str] = {}
        self.hash_results: dict[str, str] = {}

    async def __call__(self, messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        assert [item.name for item in info.output_tools] == [
            "submit_scope_decision",
            "submit_fleet_patch",
        ]
        assert [item.name for item in info.function_tools] == ["fleet_content_sha256"]
        if not self.context:
            prompt = next(
                part.content
                for message in messages
                if isinstance(message, ModelRequest)
                for part in message.parts
                if isinstance(part, UserPromptPart)
            )
            assert isinstance(prompt, str)
            self.context = json.loads(prompt.split("\n", 1)[1])["task_input"][
                "organization_context"
            ]
            visible = {item["path"]: item for item in self.context["files"]}
            assert ".fleet/fleet.yaml" not in visible
            workflow = yaml.safe_load(visible[".fleet/workflows/code-change.yaml"]["content"])
            workflow["verificationSkills"] = ["skills/backend-integration.yaml"]
            profile = yaml.safe_load(visible[".fleet/project/verification.yaml"]["content"])
            profile["commands"]["backend-integration"] = {
                "executable": "python",
                "argv": ["-m", "pytest", "tests/integration"],
                "cwd": ".",
                "timeoutSeconds": 60,
                "networkRequired": False,
            }
            skill = {
                "apiVersion": "agentfleet.dev/v1alpha1",
                "kind": "VerificationSkill",
                "metadata": {"name": "backend-integration"},
                "appliesToPaths": ["src/canary_calc"],
                "requiredCommandIds": ["backend-integration"],
            }
            self.contents = {
                path: yaml.safe_dump(value, sort_keys=False)
                for path, value in (
                    (".fleet/workflows/code-change.yaml", workflow),
                    (".fleet/project/verification.yaml", profile),
                    (".fleet/skills/backend-integration.yaml", skill),
                )
            }
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "fleet_content_sha256",
                        {
                            "operation": "replace" if path in visible else "add",
                            "path": path,
                            "content": content,
                        },
                        tool_call_id=f"hash-{index}",
                    )
                    for index, (path, content) in enumerate(self.contents.items())
                ]
            )
        returns = {
            part.tool_call_id: part.content
            for message in messages
            if isinstance(message, ModelRequest)
            for part in message.parts
            if isinstance(part, ToolReturnPart) and part.tool_name == "fleet_content_sha256"
        }
        visible = {item["path"]: item for item in self.context["files"]}
        changes = []
        for index, (path, content) in enumerate(self.contents.items()):
            result = returns[f"hash-{index}"]
            assert isinstance(result, dict)
            assert result["content"]["path"] == path
            assert result["content"]["operation"] == ("replace" if path in visible else "add")
            assert result["content"]["size_bytes"] == len(content.encode("utf-8"))
            digest = result["content"]["sha256"]
            assert digest == sha256_bytes(content.encode("utf-8"))
            self.hash_results[path] = digest
            changes.append(
                {
                    "operation": "replace" if path in visible else "add",
                    "path": path,
                    "before_sha256": visible[path]["sha256"] if path in visible else None,
                    "after_sha256": digest,
                    "content": content,
                }
            )
        payload = {
            "fleet_patch_id": self.context["proposal_id"],
            "project_id": self.context["project_id"],
            "base_fleet_spec_sha256": self.context["base_fleet_spec_sha256"],
            "changes": changes,
            "rationale": "Require independently evidenced integration tests for backend changes.",
        }
        if self.invalid == "wrong-id":
            payload["fleet_patch_id"] = "fpatch_" + "0" * 32
        elif self.invalid == "protected":
            changes[-1]["path"] = ".fleet/fleet.yaml"
        elif self.invalid == "hash":
            changes[-1]["after_sha256"] = "0" * 64
        elif self.invalid == "reference":
            payload["changes"] = changes[:2]
        return ModelResponse(
            parts=[ToolCallPart("submit_fleet_patch", payload, tool_call_id="proposal-output")]
        )


async def deliver_proposal(
    tmp_path: Path,
    invalid: str | None = None,
    *,
    conversation: bool = False,
    retain_extras: bool = False,
) -> tuple[ApplicationContainer, Path, Run, ProposalModel, str]:
    repository = GitRepositoryAdapter(tmp_path, UuidIdGenerator()).create_canary_fixture(
        tmp_path / "proposal-repository"
    )
    container = build_container(tmp_path / "state")
    model = ProposalModel(invalid)
    adapter = PydanticAIRuntimeAdapter.for_test_model(
        FunctionModel(model.__call__), redactor=container.redactor
    )
    registry = RuntimeRegistry({"fake": FakeRuntimeAdapter(), "pydantic-ai": adapter})
    container.projects.runtime_registry = registry
    container.workflow.runtimes = registry
    container.projects._initialize_without_canary(
        repository,
        runtime_name="pydantic-ai",
        provider_model="openai:offline-test",
        credential_ref="env:FLEET_OFFLINE_TEST_KEY",
        sandbox_name="fake",
    )
    project = container.state.get_project_by_root(str(repository))
    assert project is not None
    if retain_extras:
        (repository / ".fleet/retained-notes.md").write_text(
            "Local notes: preserve exact UTF-8 bytes. 保留。\n", encoding="utf-8"
        )
        (repository / ".fleet/retained-empty").mkdir(mode=0o700)
        # Seed a reviewed fixture before any generation/admission exists. This
        # does not exercise public init acceptance of an arbitrary existing tree.
        project = project.model_copy(
            update={
                "init_status_fingerprint": container.repository.inspect(
                    repository
                ).status_fingerprint
            }
        )
        container.state.save_project(project)
    with container.organization.files.session(
        project, container.organization.ids.new(IdPrefix.ORGANIZATION_OPERATION)
    ) as session:
        before = session.capture_target().sha256
    try:
        if conversation:
            selected = container.conversations.select(repository)
            view = await container.conversations.submit(
                cast(str, selected["conversation_id"]),
                message="For backend changes, always run integration tests.",
                submission_id="organization-proposal",
                options=ChatExecutionOptions(),
            )
            run = container.state.get_run(cast(str, view["run_id"]))
        else:
            run = await container.workflow.start(
                project_path=repository,
                goal="For backend changes, always run integration tests.",
                runtime_name=None,
                fake_scenario=None,
                sandbox_name="fake",
            )
    except FleetError as error:
        if invalid is None:
            raise
        run = container.state.get_run(error.details["run_id"])
    return container, repository, run, model, before
