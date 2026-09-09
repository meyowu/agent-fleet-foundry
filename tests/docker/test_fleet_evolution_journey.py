"""Public bootstrap -> chat proposal -> apply -> required Docker evidence -> rollback."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, cast

import pytest
from evolution_fixtures import ProposalModel
from pydantic_ai import ModelMessage, ModelRequest, ModelResponse, ToolCallPart, ToolReturnPart
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
from agent_fleet.domain.evidence import EvidenceBundle
from agent_fleet.domain.models import ApprovalChoice, ArtifactKind, RunStatus
from agent_fleet.domain.offline_canary import BROKEN_CANARY, FIXED_CANARY
from agent_fleet.domain.trust import TrustMode

pytestmark = [pytest.mark.asyncio, pytest.mark.docker_integration]

_INTEGRATION_TEST = """import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))


class BackendIntegration(unittest.TestCase):
    def test_backend_validation(self):
        from canary_calc.core import divide
        with self.assertRaisesRegex(ValueError, "division by zero is not allowed"):
            divide(1, 0)

    def test_backend_metadata(self):
        from canary_calc.metadata import MESSAGE
        self.assertEqual(MESSAGE, "verified new module")
"""


def register_model(
    container: ApplicationContainer, mode: Literal["proposal", "work", "probe"], roles: list[str]
) -> None:
    proposal = ProposalModel()
    work = _TwoCriterionModel(primary_verification_command_id="python-test")

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
        roles.append(request["role"])
        assert _SYNTHETIC_CREDENTIAL not in repr(messages)
        if mode == "proposal":
            assert request["role"] == "cos"
            return await proposal(messages, info)
        if mode == "probe":
            if request["role"] == "cos":
                assert request["task_input"]["organization_context"]["organization_revision"] in {
                    0,
                    2,
                }
                return await work.respond(messages, info)
            assert request["role"] == "engineer"
            return work._reply(
                [
                    ToolCallPart(
                        "run_verification",
                        {"command_id": "python-test", "reason": "Inspect the Safe approval gate."},
                        tool_call_id="baseline-requirement-probe",
                    )
                ]
            )
        if request["role"] == "cos":
            history = request["task_input"]["conversation_context"]
            assert history["through_sequence"] == 1 and len(history["entries"]) == 1
            assert "proposed and not applied" in history["entries"][0]["result_summary"]["text"]
            assert request["task_input"]["organization_context"]["organization_revision"] == 1
        result = await work.respond(messages, info)
        extra: list[ToolCallPart] = []
        for part in result.parts:
            assert isinstance(part, ToolCallPart) and isinstance(part.args, dict)
            arguments = json.loads(json.dumps(part.args).replace(_COMMAND_ID, "python-test"))
            assert isinstance(arguments, dict)
            part.args = arguments
            if part.tool_name == "run_verification":
                extra.append(
                    ToolCallPart(
                        "run_verification",
                        {
                            "command_id": "backend-integration",
                            "reason": "Execute the applied required backend integration check.",
                        },
                        tool_call_id=f"{request['role']}-integration",
                    )
                )
            elif part.tool_name == "submit_verifier_verdict":
                receipts: list[str] = []
                for message in messages:
                    if isinstance(message, ModelRequest):
                        for returned in message.parts:
                            if (
                                isinstance(returned, ToolReturnPart)
                                and returned.tool_name == "run_verification"
                            ):
                                assert isinstance(returned.content, dict)
                                content = returned.content["content"]
                                assert content["exit_code"] == 0
                                receipts.append(content["command_evidence_artifact_id"])
                assert len(set(receipts)) == 2
                arguments["evidence_artifact_ids"] = receipts
                for criterion in arguments["structured_criterion_results"]:
                    criterion["command_ids"] = ["python-test", "backend-integration"]
                    criterion["evidence_artifact_ids"] = receipts
        result.parts = [*result.parts, *extra]
        return result

    runtime = PydanticAIRuntimeAdapter.for_test_model(
        FunctionModel(respond), redactor=container.redactor
    )
    registry = RuntimeRegistry({"fake": FakeRuntimeAdapter(), "pydantic-ai": runtime})
    container.projects.runtime_registry = registry
    container.workflow.runtimes = registry
    container.bootstrap.runtimes = registry


async def assert_baseline_backend_task(
    container: ApplicationContainer, target: Path, *, revision: int
) -> None:
    """Admit a real TaskSpec, then cancel before any command authorization."""
    roles: list[str] = []
    register_model(container, "probe", roles)
    boundary = container.repository.inspect_organization_boundary(target)
    run = await container.workflow.start(
        project_path=target,
        goal=f"Check baseline backend requirements at organization revision {revision}.",
        runtime_name=None,
        sandbox_name=None,
        fake_scenario=None,
    )
    assert run.status is RunStatus.PAUSED_FOR_APPROVAL and run.task_id is not None
    assert roles == ["cos", "engineer"]
    task = container.state.get_task(run.task_id)
    assert task.required_verification_command_ids == ["python-test"]
    admission = container.organization.store.admission_for_run(run.run_id)
    assert admission is not None and admission.revision == revision
    assert not any(
        artifact.kind is ArtifactKind.COMMAND_EVIDENCE
        for artifact in container.state.list_artifacts(run.run_id)
    )
    cancelled = await container.cancellation.cancel(run.run_id)
    assert cancelled.status is RunStatus.CANCELLED
    assert not container.state.outstanding_leases()
    assert container.repository.inspect_organization_boundary(target) == boundary


def seed_real_tests(target: Path, container: ApplicationContainer) -> None:
    manifest = target / "pyproject.toml"
    manifest.write_text(
        manifest.read_text() + "\n[project.optional-dependencies]\ntest = ['pytest==9.1.1']\n"
    )
    boundary = target / "tests/test_sandbox_boundary.py"
    content = boundary.read_text()
    old_names = "'HOME', 'HOSTNAME', 'LANG', 'LC_ALL', 'PATH'"
    assert old_names in content
    boundary.write_text(
        content.replace(old_names, old_names + ", 'PYTEST_VERSION', 'PYTEST_CURRENT_TEST'")
    )
    (target / "tests/integration").mkdir()
    (target / "tests/integration/test_backend.py").write_text(_INTEGRATION_TEST, encoding="utf-8")
    container.repository._run(["git", "add", "--", "pyproject.toml", "tests"], cwd=target)
    container.repository._run(
        [
            "git",
            "commit",
            "--no-gpg-sign",
            "--no-verify",
            "-m",
            "Declare backend integration fixture",
        ],
        cwd=target,
    )


async def test_public_fleet_evolution_changes_required_independent_docker_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, real_docker_image: str
) -> None:
    target, container = _fixture(tmp_path, monkeypatch)
    seed_real_tests(target, container)
    provider = container.sandboxes.get("docker")
    assert isinstance(provider, DockerSandboxProvider)
    scope = provider.recovery_scope_id
    roles: list[str] = []
    try:
        register_model(container, "proposal", roles)
        initialized = await container.bootstrap.initialize(
            target,
            runtime_name="pydantic-ai",
            provider_model="openai:offline-test",
            credential_ref=_CREDENTIAL_REF,
            sandbox_name="docker",
            docker_image=real_docker_image,
            trust_mode=TrustMode.SAFE,
            allowed_paths=("src/canary_calc",),
        )
        assert (
            initialized["bootstrap_verified"] is True
            and initialized["bootstrap_cleanup_complete"] is True
        )
        assert roles == []
        await assert_baseline_backend_task(container, target, revision=0)
        register_model(container, "proposal", roles)
        conversation = container.conversations.select(target)
        conversation_id = cast(str, conversation["conversation_id"])
        proposed = await container.conversations.submit(
            conversation_id,
            message="For backend changes, always run integration tests.",
            submission_id="backend-rule",
            options=ChatExecutionOptions(),
        )
        proposal_run = container.state.get_run(cast(str, proposed["run_id"]))
        assert proposal_run.status is RunStatus.COMPLETED
        assert set(roles) == {"cos"} and len(roles) == 2
        proposal = container.organization.list_proposals(target)[0]
        assert not (target / ".fleet/skills").exists()
        assert container.state.list_leases(proposal_run.run_id) == []
        prior_grants = container.state.list_project_grants(proposal_run.project_id)
        applied_rule = container.organization.apply(proposal.patch.fleet_patch_id)
        assert applied_rule.changed and applied_rule.cleanup_complete is True
        assert container.state.list_project_grants(proposal_run.project_id) == prior_grants
        assert (target / _CORE_PATH).read_text() == BROKEN_CANARY
        roles.clear()
        register_model(container, "work", roles)
        view = await container.conversations.submit(
            conversation_id,
            message="Fix division validation and add the metadata module.",
            submission_id="backend-code",
            options=ChatExecutionOptions(),
        )
        run_id = cast(str, view["run_id"])
        approvals: list[str] = []
        for _ in range(16):
            run = container.state.get_run(run_id)
            if run.status is RunStatus.READY_FOR_REVIEW:
                break
            assert (
                run.status is RunStatus.PAUSED_FOR_APPROVAL and run.pending_approval_id is not None
            )
            approvals.append(run.pending_approval_id)
            prior_budget = container.budgets.snapshot(run_id)
            container = build_container(container.state_root)
            register_model(container, "work", roles)
            container.conversations.select(target, conversation_id=conversation_id)
            assert container.budgets.snapshot(run_id) == prior_budget
            container.conversations.approve(
                conversation_id, run.pending_approval_id, choice=ApprovalChoice.ALLOW_RUN
            )
            view = await container.conversations.resume(conversation_id)
        else:
            raise AssertionError("the bounded backend-rule approval journey did not settle")
        assert approvals and len(approvals) == len(set(approvals))
        assert roles.count("cos") == 1 and {"engineer", "verifier"} <= set(roles)
        assert run.verified_complete is True and run.task_id is not None
        task = container.state.get_task(run.task_id)
        assert task.required_verification_command_ids == ["backend-integration", "python-test"]
        assert run.evidence_bundle_artifact_id is not None
        bundle = EvidenceBundle.model_validate_json(
            container.artifacts.read_text(run.evidence_bundle_artifact_id)
        )
        assert bundle.proof_gaps == []
        assert len(bundle.command_evidence) == 4
        for command_id, passed in (
            ("python-test", "5 passed"),
            ("backend-integration", "2 passed"),
        ):
            commands = [item for item in bundle.command_evidence if item.command_id == command_id]
            assert len(commands) == 2 and len({item.agent_instance_id for item in commands}) == 2
            for command in commands:
                assert command.exit_code == 0
                assert passed in container.artifacts.read_text(command.transcript_artifact_id)
        assert not container.state.outstanding_leases()
        assert (target / _CORE_PATH).read_text() == BROKEN_CANARY and not (
            target / _MODULE_PATH
        ).exists()
        completed, code_patch = container.patches.apply(run_id)
        assert completed.status is RunStatus.COMPLETED and code_patch.applied
        assert (target / _CORE_PATH).read_text() == FIXED_CANARY
        assert (target / _MODULE_PATH).read_text() == _MODULE_SOURCE
        # User-owned source work is explicitly committed in this disposable fixture
        # before an organization-only rollback; the publisher never stages source.
        container.repository._run(["git", "add", "--", "src"], cwd=target)
        container.repository._run(
            [
                "git",
                "commit",
                "--no-gpg-sign",
                "--no-verify",
                "-m",
                "Accept independently verified backend fixture",
            ],
            cwd=target,
        )
        source_boundary = container.repository.inspect_organization_boundary(target)
        rolled_back = container.organization.rollback(proposal.patch.fleet_patch_id)
        assert rolled_back.cleanup_complete is True and rolled_back.version is not None
        assert (
            rolled_back.version.version == 2
            and rolled_back.version.tree_sha256 == proposal.before_tree_sha256
        )
        assert source_boundary.unchanged_outside_organization(
            container.repository.inspect_organization_boundary(target)
        )
        assert not (target / ".fleet/skills").exists()
        assert container.state.get_task(run.task_id) == task
        await assert_baseline_backend_task(container, target, revision=2)
        assert container.state.get_task(run.task_id) == task
        assert not container.state.outstanding_leases()
        assert (
            await provider._list_exact(
                provider._require_executable(), {"agent-fleet.installation": scope}
            )
            == []
        )
        for metadata in container.state.list_artifacts(run_id):
            assert _SYNTHETIC_CREDENTIAL not in container.artifacts.read_text(metadata.artifact_id)
    finally:
        await _cleanup_real_installation_scope(provider, scope)
