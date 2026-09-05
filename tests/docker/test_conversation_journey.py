"""Public bootstrap/chat/approval/apply journey with offline model responses."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, cast

import pytest
from pydantic_ai import ModelMessage, ModelRequest, ModelResponse, ToolCallPart
from pydantic_ai.messages import UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from test_phase5_evidence import (
    _COMMAND_ID,
    _CORE_PATH,
    _CREDENTIAL_REF,
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
from agent_fleet.application.conversations import ChatExecutionOptions
from agent_fleet.application.runtime import RuntimeRegistry
from agent_fleet.bootstrap import ApplicationContainer, build_container
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import ApprovalChoice, RunStatus
from agent_fleet.domain.offline_canary import BROKEN_CANARY, FIXED_CANARY
from agent_fleet.domain.trust import TrustMode

pytestmark = pytest.mark.asyncio


def _registered_test_model(container: ApplicationContainer, roles: list[str]) -> None:
    model = _TwoCriterionModel()

    async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        prompt = next(
            part.content
            for message in messages
            if isinstance(message, ModelRequest)
            for part in message.parts
            if isinstance(part, UserPromptPart)
        )
        assert isinstance(prompt, str)
        request = json.loads(prompt.split("\n", 1)[1])
        role = request["role"]
        roles.append(role)
        assert _SYNTHETIC_CREDENTIAL not in repr(messages)
        if role == "cos":
            assert request["task_input"]["conversation_context"]["through_sequence"] == 0
            assert request["task_input"]["conversation_context"]["entries"] == []
        result = await model.respond(messages, info)
        # The actual public profiler discovers python-test from the fixture's
        # declared real pytest dependency. The model must request that reviewed
        # command, not the private bootstrap-only unittest command.
        for part in result.parts:
            if isinstance(part, ToolCallPart):
                assert isinstance(part.args, dict)
                part.args = json.loads(json.dumps(part.args).replace(_COMMAND_ID, "python-test"))
        return result

    runtime = PydanticAIRuntimeAdapter.for_test_model(
        FunctionModel(respond), redactor=container.redactor
    )
    registry = RuntimeRegistry({"fake": FakeRuntimeAdapter(), "pydantic-ai": runtime})
    container.projects.runtime_registry = registry
    container.workflow.runtimes = registry
    container.bootstrap.runtimes = registry


async def _public_journey(
    target: Path,
    container: ApplicationContainer,
    *,
    sandbox: Literal["fake", "docker"],
    image: str | None = None,
) -> None:
    manifest = target / "pyproject.toml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8")
        + "\n[project.optional-dependencies]\ntest = ['pytest==9.1.1']\n",
        encoding="utf-8",
    )
    boundary_test = target / "tests/test_sandbox_boundary.py"
    boundary_source = boundary_test.read_text(encoding="utf-8")
    original_names = "'HOME', 'HOSTNAME', 'LANG', 'LC_ALL', 'PATH'"
    assert original_names in boundary_source
    # Genuine pytest adds these two variables inside its own test process.
    # Keep the host sentinel and sensitive-name assertions unchanged; this is
    # seeded fixture content before registration, never a candidate test edit.
    boundary_test.write_text(
        boundary_source.replace(
            original_names, original_names + ", 'PYTEST_VERSION', 'PYTEST_CURRENT_TEST'"
        ),
        encoding="utf-8",
    )
    container.repository._run(
        ["git", "add", "--", "pyproject.toml", "tests/test_sandbox_boundary.py"], cwd=target
    )
    container.repository._run(
        ["git", "commit", "--no-gpg-sign", "--no-verify", "-m", "Declare real pytest tests"],
        cwd=target,
    )
    roles: list[str] = []
    _registered_test_model(container, roles)
    preview = container.projects.preview(
        target,
        runtime_name="pydantic-ai",
        provider_model="openai:offline-test",
        credential_ref=_CREDENTIAL_REF,
        sandbox_name=sandbox,
        docker_image=image,
    )
    assert preview and not (target / ".fleet").exists()
    initialize = container.bootstrap.initialize(
        target,
        runtime_name="pydantic-ai",
        provider_model="openai:offline-test",
        credential_ref=_CREDENTIAL_REF,
        sandbox_name=sandbox,
        docker_image=image,
        trust_mode=TrustMode.SAFE,
        allowed_paths=("src/canary_calc",),
    )
    if sandbox == "fake":
        with pytest.raises(FleetError) as captured:
            await initialize
        assert captured.value.code is ErrorCode.BOOTSTRAP_CANARY_FAILED
        assert captured.value.details["proof_gaps"]
        assert not (target / ".fleet").exists()
        assert not roles and not container.state.outstanding_leases()
        return
    initialized = await initialize
    assert initialized["bootstrap_verified"] is True
    assert initialized["bootstrap_cleanup_complete"] is True
    assert not roles  # Bootstrap's trusted canary does not call a provider.
    before = container.repository.inspect(target).status_fingerprint
    view = container.conversations.select(target)
    conversation_id = cast(str, view["conversation_id"])
    view = await container.conversations.submit(
        conversation_id,
        message="Fix division validation and add the independently tested metadata module.",
        submission_id="public-docker-chat",
        options=ChatExecutionOptions(),
    )
    run_id = cast(str, view["run_id"])
    binding = container.conversation_store.binding_for_run(run_id)
    assert binding is not None
    initial_binding = binding
    approvals: list[str] = []
    for _ in range(12):
        run = container.state.get_run(run_id)
        if run.status is RunStatus.READY_FOR_REVIEW:
            break
        assert run.status is RunStatus.PAUSED_FOR_APPROVAL and run.pending_approval_id is not None
        approvals.append(run.pending_approval_id)
        prior_budget = container.budgets.snapshot(run_id)
        container = build_container(container.state_root)
        _registered_test_model(container, roles)
        restored = container.conversations.select(target, conversation_id=conversation_id)
        assert restored["run_id"] == run_id and restored["turn_id"] == binding.turn_id
        assert container.budgets.snapshot(run_id) == prior_budget
        container.conversations.approve(
            conversation_id, run.pending_approval_id, choice=ApprovalChoice.ALLOW_RUN
        )
        view = await container.conversations.resume(conversation_id)
        assert view["run_id"] == run_id
    else:
        raise AssertionError("The bounded public approval journey did not settle")
    assert approvals and len(approvals) == len(set(approvals))
    assert roles.count("cos") == 1
    assert "engineer" in roles and "verifier" in roles
    run = container.state.get_run(run_id)
    assert run.status is RunStatus.READY_FOR_REVIEW
    assert run.verified_complete is (sandbox == "docker")
    assert view["turn_status"] == "delivered" and view["active_turn_id"] is None
    assert container.conversation_store.binding_for_run(run_id) == initial_binding
    status = container.inspection.status(run_id)
    evidence = status["evidence"]
    assert isinstance(evidence, dict)
    commands = evidence["command_results"]
    assert isinstance(commands, list) and len(commands) == 2
    assert len({command["agent_instance_id"] for command in commands}) == 2
    for command in commands:
        assert command["command_id"] == "python-test" and command["exit_code"] == 0
    if sandbox == "docker":
        for command in commands:
            transcript = container.artifacts.read_text(command["transcript_artifact_id"])
            assert "3 passed" in transcript
        assert evidence["proof_gaps"] == []
    assert (target / _CORE_PATH).read_text() == BROKEN_CANARY
    assert not (target / _MODULE_PATH).exists()
    assert container.repository.inspect(target).status_fingerprint == before
    assert not container.state.outstanding_leases()
    usage = container.budgets.snapshot(run_id)
    assert usage.unknown_requests == usage.outstanding_requests == 0
    assert usage.agent_invocations >= 3
    for metadata in container.state.list_artifacts(run_id):
        assert _SYNTHETIC_CREDENTIAL not in container.artifacts.read_text(metadata.artifact_id)
    assert _SYNTHETIC_CREDENTIAL not in json.dumps(view)
    reopened = build_container(container.state_root)
    reopened.conversations.select(target, conversation_id=conversation_id)
    applied, result = reopened.patches.apply(run_id)
    assert applied.status is RunStatus.COMPLETED and result.applied
    assert (target / _CORE_PATH).read_text() == FIXED_CANARY
    assert (target / _MODULE_PATH).read_text() == _MODULE_SOURCE
    assert reopened.conversation_store.binding_for_run(run_id) == initial_binding
    assert not reopened.state.outstanding_leases()


@pytest.mark.integration
async def test_offline_public_bootstrap_does_not_publish_simulated_proof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target, container = _fixture(tmp_path, monkeypatch)
    await _public_journey(target, container, sandbox="fake")


@pytest.mark.docker_integration
async def test_public_docker_chat_verifies_real_pytest_after_approval_and_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, real_docker_image: str
) -> None:
    target, container = _fixture(tmp_path, monkeypatch)
    provider = container.sandboxes.get("docker")
    assert isinstance(provider, DockerSandboxProvider)
    scope = provider.recovery_scope_id
    try:
        await _public_journey(target, container, sandbox="docker", image=real_docker_image)
        assert (
            await provider._list_exact(
                provider._require_executable(), {"agent-fleet.installation": scope}
            )
            == []
        )
    finally:
        await _cleanup_real_installation_scope(provider, scope)
