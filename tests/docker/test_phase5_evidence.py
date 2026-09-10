"""Normal typed runtime journeys: two criteria, a new module, and honest assurance.

The model is an offline FunctionModel in both cases. Only the explicitly opted-in
Docker case executes the dependency-free fixture tests; FakeSandbox never does.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Literal

import pytest
from pydantic_ai import ModelMessage, ModelRequest, ModelResponse, ToolCallPart, ToolReturnPart
from pydantic_ai.messages import UserPromptPart
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.usage import RequestUsage
from test_real_docker import _cleanup_real_installation_scope

from agent_fleet.adapters.runtime.fake import FakeRuntimeAdapter
from agent_fleet.adapters.runtime.pydantic_ai import PydanticAIRuntimeAdapter
from agent_fleet.adapters.sandbox.docker import DockerSandboxProvider
from agent_fleet.application.runtime import RuntimeRegistry
from agent_fleet.application.sandboxes import requirements_for_configuration
from agent_fleet.bootstrap import ApplicationContainer, build_container
from agent_fleet.domain.evidence import CommandEvidence, EvidenceBundle, EvidenceStrength
from agent_fleet.domain.models import (
    ArtifactKind,
    Run,
    RunStatus,
    SandboxConfiguration,
    SandboxPreflight,
    TaskSpec,
    Verdict,
    VerifierVerdict,
    WorkflowStage,
    WorkspaceKind,
)
from agent_fleet.domain.offline_canary import (
    BOOTSTRAP_SANDBOX_PROBE_MARKER,
    BROKEN_CANARY,
    FIXED_CANARY,
)
from agent_fleet.domain.trust import TrustMode

pytestmark = pytest.mark.asyncio

_CREDENTIAL_VARIABLE = "FLEET_PHASE5_OFFLINE_MODEL_KEY"
_CREDENTIAL_REF = f"env:{_CREDENTIAL_VARIABLE}"
_SYNTHETIC_CREDENTIAL = "phase5-offline-only-credential-7f9218"
_CORE_PATH = "src/canary_calc/core.py"
_MODULE_PATH = "src/canary_calc/metadata.py"
_MODULE_SOURCE = (
    '"""Independently checked module added by the candidate."""\n\n'
    'MESSAGE = "verified new module"\n'
)
_COMMAND_ID = "bootstrap-unittest"
_CRITERIA = {
    "canary-zero-division": "divide(1, 0) raises ValueError with the stable message.",
    "new-module-message": "The new metadata module exports MESSAGE='verified new module'.",
}
_MappingCase = Literal["valid", "empty", "command-plus-transcript"]
_METADATA_TEST = """import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


class MetadataTests(unittest.TestCase):
    def test_new_module_exports_reviewed_message(self) -> None:
        from canary_calc.metadata import MESSAGE

        self.assertEqual(MESSAGE, "verified new module")
"""


@dataclass
class _TwoCriterionModel:
    mapping: _MappingCase = "valid"
    primary_verification_command_id: str | None = None
    calls: dict[str, int] = field(default_factory=dict)
    verifier_read_new_module: bool = False
    verifier_evidence_id: str | None = None
    verifier_transcript_id: str | None = None
    verifier_task: TaskSpec | None = None
    verifier_command_id: str | None = None

    @staticmethod
    def _reply(parts: list[ToolCallPart]) -> ModelResponse:
        # Explicit reported usage keeps the offline provider protocol accountable.
        return ModelResponse(parts=parts, usage=RequestUsage(input_tokens=40, output_tokens=10))

    @staticmethod
    def _input(messages: list[ModelMessage]) -> dict[str, object]:
        prompt = next(
            part.content
            for message in messages
            if isinstance(message, ModelRequest)
            for part in message.parts
            if isinstance(part, UserPromptPart)
        )
        assert isinstance(prompt, str)
        payload = json.loads(prompt.split("\n", 1)[1])
        task_input = payload["task_input"]
        assert isinstance(task_input, dict)
        return task_input

    async def respond(self, messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        assert _SYNTHETIC_CREDENTIAL not in repr(messages)
        assert "untrusted_project_guidance" in repr(messages)
        output = info.output_tools[0].name
        number = self.calls.get(output, 0) + 1
        self.calls[output] = number
        assert number <= 2
        if output == "submit_scope_decision":
            assert number == 1
            return self._reply(
                [
                    ToolCallPart(
                        output,
                        {
                            "normalized_goal": "Fix division behavior and add the metadata module.",
                            "workflow": "code-change",
                            "change_kind": "code_change",
                            "fleet_strategy": "engineer_verifier",
                            "allowed_paths": ["src/canary_calc"],
                            "forbidden_paths": [".git", ".fleet", "tests"],
                            "acceptance_criteria": [
                                {"criterion_id": identifier, "description": description}
                                for identifier, description in _CRITERIA.items()
                            ],
                            "required_evidence": [
                                "canonical_patch",
                                "command_evidence",
                                "independent_verifier_verdict",
                            ],
                        },
                        tool_call_id="scope-two-criteria",
                    )
                ]
            )
        if output == "submit_implementation_report":
            if number == 1:
                return self._reply(
                    [
                        ToolCallPart(
                            "workspace_write_file",
                            {
                                "path": path,
                                "content": content,
                                "reason": "Implement the reviewed criterion in the candidate.",
                            },
                            tool_call_id=f"engineer-write-{index}",
                        )
                        for index, (path, content) in enumerate(
                            ((_CORE_PATH, FIXED_CANARY), (_MODULE_PATH, _MODULE_SOURCE))
                        )
                    ]
                    + [
                        ToolCallPart(
                            "run_verification",
                            {"command_id": _COMMAND_ID, "reason": "Check both fixture criteria."},
                            tool_call_id="engineer-unittest",
                        )
                    ]
                )
            return self._reply(
                [
                    ToolCallPart(
                        output,
                        {
                            "summary": "Repaired division and added the metadata module.",
                            "intended_changed_paths": [_CORE_PATH, _MODULE_PATH],
                            "tests_added_or_changed": [],
                            "criterion_results": list(_CRITERIA),
                            "evidence_artifact_ids": [],
                            "unresolved_limitations": [],
                            "verifier_focus": list(_CRITERIA.values()),
                        },
                        tool_call_id="engineer-report",
                    )
                ]
            )
        assert output == "submit_verifier_verdict"
        task_input = self._input(messages)
        task = TaskSpec.model_validate(task_input["task_spec"])
        self.verifier_task = task
        # Discover exact values from the real invocation, not module constants.
        commands = {command.command_id: command for command in task.verification_commands}
        if self.primary_verification_command_id is None:
            assert len(task.required_verification_command_ids) == 1
            command_id = task.required_verification_command_ids[0]
        else:
            command_id = self.primary_verification_command_id
        assert command_id in commands
        assert command_id in task.required_verification_command_ids
        self.verifier_command_id = command_id
        contract = task_input["criterion_mapping_contract"]
        assert isinstance(contract, dict)
        assert len(json.dumps(contract).encode()) <= 1600
        assert "content.command_evidence_artifact_id" in contract["receipt_field"]
        assert "content.transcript_artifact_id" in contract["excluded"]
        assert "one current independent receipt" in contract["pairing"]
        assert isinstance(info.instructions, str)
        assert "criterion_mapping_contract" in info.instructions
        assert "content.command_evidence_artifact_id" in info.instructions
        assert "content.command_evidence_artifact_id" in json.dumps(
            info.output_tools[0].parameters_json_schema
        )
        verification_tool = next(
            tool for tool in info.function_tools if tool.name == "run_verification"
        )
        assert isinstance(verification_tool.description, str)
        assert "content.command_evidence_artifact_id" in verification_tool.description
        assert "content.transcript_artifact_id" in verification_tool.description
        if number == 1:
            return self._reply(
                [
                    ToolCallPart(
                        "repo_read_file",
                        {"path": _MODULE_PATH, "reason": "Inspect the reconstructed new module."},
                        tool_call_id="verifier-read-new-module",
                    ),
                    ToolCallPart(
                        "run_verification",
                        {"command_id": command_id, "reason": "Independently check both criteria."},
                        tool_call_id="verifier-unittest",
                    ),
                ]
            )
        returns = {
            part.tool_call_id: part.content
            for message in messages
            if isinstance(message, ModelRequest)
            for part in message.parts
            if isinstance(part, ToolReturnPart)
        }
        read_result = returns["verifier-read-new-module"]
        command_result = returns["verifier-unittest"]
        assert isinstance(read_result, dict) and isinstance(command_result, dict)
        assert read_result["content"]["content"] == _MODULE_SOURCE
        self.verifier_read_new_module = True
        command_content = command_result["content"]
        assert command_content["exit_code"] == 0
        assert command_content["timed_out"] is False
        evidence_id = command_content["command_evidence_artifact_id"]
        transcript_id = command_content["transcript_artifact_id"]
        assert isinstance(evidence_id, str)
        assert isinstance(transcript_id, str) and transcript_id != evidence_id
        # Preserve the gateway result: generic references intentionally include
        # auxiliary artifacts and must not become a CommandEvidence-only contract.
        assert set(command_result["artifact_ids"]) == {evidence_id, transcript_id}
        self.verifier_evidence_id = evidence_id
        self.verifier_transcript_id = transcript_id
        mapped_receipts = (
            []
            if self.mapping == "empty"
            else [evidence_id, transcript_id]
            if self.mapping == "command-plus-transcript"
            else [evidence_id]
        )
        return self._reply(
            [
                ToolCallPart(
                    output,
                    {
                        "verdict": "pass",
                        "criterion_results": [
                            item.criterion_id for item in task.acceptance_criteria
                        ],
                        "evidence_artifact_ids": [evidence_id],
                        "structured_criterion_results": [
                            {
                                "criterion_id": criterion.criterion_id,
                                "verdict": "pass",
                                "evidence_artifact_ids": mapped_receipts,
                                "command_ids": [] if self.mapping == "empty" else [command_id],
                                "explanation": criterion.description,
                            }
                            for criterion in task.acceptance_criteria
                        ],
                        "regressions": [],
                        "required_repairs": [],
                        "proof_gaps": [],
                        "rationale": "Map each criterion to this verifier's exact command receipt.",
                    },
                    tool_call_id="verifier-mapped-verdict",
                )
            ]
        )


@pytest.mark.parametrize(
    "primary_command", [None, "python-test", "missing-command", "optional-check"]
)
async def test_shared_model_selects_exact_primary_command_and_its_receipt(
    primary_command: str | None,
) -> None:
    # Exercise only shared test-model bookkeeping. Real Gateway execution and
    # independent evidence remain assertions of the existing runtime journeys.
    task = TaskSpec.model_validate(
        {
            "task_id": "task_" + "a" * 32,
            "run_id": "run_" + "b" * 32,
            "original_goal": "Fix division behavior and add the metadata module.",
            "normalized_goal": "Fix division behavior and add the metadata module.",
            "base_revision": "c" * 40,
            "allowed_paths": ["src/canary_calc"],
            "forbidden_paths": ["tests"],
            "acceptance_criteria": [
                {"criterion_id": identifier, "description": description}
                for identifier, description in _CRITERIA.items()
            ],
            "required_evidence": ["canonical_patch", "command_evidence"],
            "max_repair_iterations": 1,
            "config_snapshot_hash": "d" * 64,
            "verification_commands": [
                {"command_id": identifier, "executable": "python", "argv": ["-m", "pytest"]}
                for identifier in ("backend-integration", "python-test", "optional-check")
            ],
            "required_verification_command_ids": ["backend-integration", "python-test"],
            "created_at": "2026-01-01T00:00:00Z",
        }
    )
    info = AgentInfo(
        function_tools=[
            ToolDefinition(
                name="run_verification",
                description="content.command_evidence_artifact_id; content.transcript_artifact_id",
            )
        ],
        allow_text_output=False,
        output_tools=[
            ToolDefinition(
                name="submit_verifier_verdict",
                parameters_json_schema=VerifierVerdict.model_json_schema(),
            )
        ],
        model_settings=None,
        model_request_parameters=ModelRequestParameters(),
        instructions=resources.files("agent_fleet.adapters.runtime.prompts")
        .joinpath("verifier.md")
        .read_text(),
    )
    messages: list[ModelMessage] = [
        ModelRequest(
            parts=[
                UserPromptPart(
                    "Task:\n"
                    + json.dumps(
                        {
                            "untrusted_project_guidance": [],
                            "task_input": {
                                "task_spec": task.model_dump(mode="json"),
                                "criterion_mapping_contract": {
                                    "receipt_field": "content.command_evidence_artifact_id",
                                    "excluded": "content.transcript_artifact_id",
                                    "pairing": "one current independent receipt",
                                },
                            },
                        }
                    )
                )
            ]
        )
    ]
    model = _TwoCriterionModel(primary_verification_command_id=primary_command)
    if primary_command != "python-test":
        with pytest.raises(AssertionError):
            await model.respond(messages, info)
        assert model.verifier_command_id is None
        return
    request = await model.respond(messages, info)
    primary_call = next(
        part
        for part in request.parts
        if isinstance(part, ToolCallPart) and part.tool_call_id == "verifier-unittest"
    )
    assert isinstance(primary_call, ToolCallPart) and isinstance(primary_call.args, dict)
    assert primary_call.args["command_id"] == "python-test"
    request.parts = [
        *request.parts,
        ToolCallPart(
            "run_verification",
            {"command_id": "backend-integration", "reason": "Check the additional requirement."},
            tool_call_id="verifier-integration",
        ),
    ]
    # The second return has the same tool name, but belongs to another command.
    returns = [
        ToolReturnPart(
            "repo_read_file",
            {"content": {"content": _MODULE_SOURCE}},
            tool_call_id="verifier-read-new-module",
        )
    ]
    for call_id, evidence_id, transcript_id in (
        ("verifier-unittest", "art_" + "1" * 32, "art_" + "2" * 32),
        ("verifier-integration", "art_" + "3" * 32, "art_" + "4" * 32),
    ):
        returns.append(
            ToolReturnPart(
                "run_verification",
                {
                    "content": {
                        "exit_code": 0,
                        "timed_out": False,
                        "command_evidence_artifact_id": evidence_id,
                        "transcript_artifact_id": transcript_id,
                    },
                    "artifact_ids": [evidence_id, transcript_id],
                },
                tool_call_id=call_id,
            )
        )
    messages.extend([request, ModelRequest(parts=returns)])
    response = await model.respond(messages, info)
    verdict_call = response.parts[0]
    assert isinstance(verdict_call, ToolCallPart)
    verdict = VerifierVerdict.model_validate(verdict_call.args)
    assert model.verifier_task == task
    assert model.verifier_command_id == "python-test"
    assert model.verifier_evidence_id == "art_" + "1" * 32
    assert model.verifier_transcript_id == "art_" + "2" * 32
    assert verdict.evidence_artifact_ids == [model.verifier_evidence_id]
    assert verdict.structured_criterion_results is not None
    for criterion in verdict.structured_criterion_results:
        assert criterion.command_ids == ["python-test"]
        assert criterion.evidence_artifact_ids == [model.verifier_evidence_id]


def _fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, ApplicationContainer]:
    monkeypatch.setenv(_CREDENTIAL_VARIABLE, _SYNTHETIC_CREDENTIAL)
    fixture = build_container(tmp_path / "fixture-state")
    target = fixture.repository.create_bootstrap_canary_fixture(
        tmp_path / "fixture-state" / "target"
    )
    # Seed a tracked, independent test before registration. The model cannot edit it.
    (target / "tests/test_metadata.py").write_text(_METADATA_TEST, encoding="utf-8")
    fixture.repository._run(["git", "add", "--", "tests/test_metadata.py"], cwd=target)
    fixture.repository._run(
        [
            "git",
            "commit",
            "--no-gpg-sign",
            "--no-verify",
            "--no-status",
            "-m",
            "metadata criterion",
        ],
        cwd=target,
    )
    assert not (target / _MODULE_PATH).exists()
    assert (target / _CORE_PATH).read_text() == BROKEN_CANARY
    return target, build_container(tmp_path / "fleet-state")


async def _run_and_check(
    container: ApplicationContainer,
    target: Path,
    *,
    sandbox: Literal["fake", "docker"],
    docker_image: str | None = None,
    preflight: SandboxPreflight | None = None,
    mapping: _MappingCase = "valid",
) -> Run:
    model = _TwoCriterionModel(mapping=mapping)
    runtime = PydanticAIRuntimeAdapter.for_test_model(
        FunctionModel(model.respond), redactor=container.redactor
    )
    registry = RuntimeRegistry({"fake": FakeRuntimeAdapter(), "pydantic-ai": runtime})
    container.projects.runtime_registry = registry
    container.workflow.runtimes = registry
    container.doctor.runtime_registry = registry
    container.secrets.resolve(_CREDENTIAL_REF)
    container.projects._initialize_without_canary(
        target,
        runtime_name="pydantic-ai",
        provider_model="openai:offline-test",
        credential_ref=_CREDENTIAL_REF,
        sandbox_name=sandbox,
        docker_image=docker_image,
        trusted_canary_config=True,
        sandbox_image_identity=preflight.image_identity if preflight is not None else None,
        sandbox_daemon_identity=preflight.daemon_identity if preflight is not None else None,
    )
    container.permissions.configure(
        target, mode=TrustMode.BALANCED, allowed_paths=("src/canary_calc",)
    )
    target_before = container.repository.inspect(target)
    run = await container.workflow.start(
        project_path=target,
        goal="Fix division by zero and add the metadata module with its reviewed message.",
        runtime_name=None,
        sandbox_name=sandbox,
        fake_scenario=None,
    )
    isolated = sandbox == "docker"
    verified = isolated and mapping == "valid"
    assert run.status is RunStatus.READY_FOR_REVIEW
    assert run.verified_complete is verified
    assert run.verifier_agent_instance_id is not None
    assert run.verification_checkpoint is None
    assert model.verifier_read_new_module
    assert model.calls == {
        "submit_scope_decision": 1,
        "submit_implementation_report": 2,
        "submit_verifier_verdict": 2,
    }
    assert run.evidence_bundle_artifact_id is not None
    bundle = EvidenceBundle.model_validate_json(
        container.artifacts.read_text(run.evidence_bundle_artifact_id)
    )
    assert bundle.changed_paths == [_CORE_PATH, _MODULE_PATH]
    assert {item.criterion_id for item in bundle.criterion_assessments} == set(_CRITERIA)
    assert {item.verdict for item in bundle.criterion_assessments} == {
        Verdict.PASS if verified else Verdict.INCONCLUSIVE
    }
    assert bundle.completion_decision is not None
    assert bundle.completion_decision.verified_complete is verified
    assert bundle.structured_criterion_results is not None
    assert len(bundle.structured_criterion_results) == 2
    assert model.verifier_task is not None and run.task_spec_artifact_id is not None
    persisted_task = TaskSpec.model_validate_json(
        container.artifacts.read_text(run.task_spec_artifact_id)
    )
    assert persisted_task == model.verifier_task
    assert model.verifier_command_id in persisted_task.required_verification_command_ids
    expected_receipts = (
        []
        if mapping == "empty"
        else [model.verifier_evidence_id, model.verifier_transcript_id]
        if mapping == "command-plus-transcript"
        else [model.verifier_evidence_id]
    )
    for mapped in bundle.structured_criterion_results:
        assert mapped.evidence_artifact_ids == expected_receipts
        assert mapped.command_ids == ([] if mapping == "empty" else [model.verifier_command_id])
    if mapping != "valid":
        assert "STRUCTURED_CRITERION_MAPPING_INVALID" in bundle.completion_decision.reason_codes
        assert "STRUCTURED_CRITERION_MAPPING_INVALID" in {gap.code for gap in bundle.proof_gaps}
    assert run.verifier_verdict_artifact_id is not None
    verdict = VerifierVerdict.model_validate_json(
        container.artifacts.read_text(run.verifier_verdict_artifact_id)
    )
    assert verdict.structured_criterion_results == bundle.structured_criterion_results
    # Existing workflow observation binding remains authoritative and does not
    # silently rewrite malformed per-criterion claims.
    assert verdict.evidence_artifact_ids == [model.verifier_evidence_id]
    evidence = [
        CommandEvidence.model_validate_json(container.artifacts.read_text(identifier))
        for identifier in run.command_evidence_artifact_ids
    ]
    assert len(evidence) == 2
    engineer = next(item for item in evidence if item.principal_role == "engineer")
    verifier = next(item for item in evidence if item.principal_role == "verifier")
    assert engineer.agent_instance_id != verifier.agent_instance_id
    assert engineer.workspace_id != verifier.workspace_id
    assert engineer.sandbox_id != verifier.sandbox_id
    assert verifier.agent_instance_id == run.verifier_agent_instance_id
    assert verifier.evidence_id == model.verifier_evidence_id
    assert verifier.workflow_stage is WorkflowStage.VERIFYING
    assert verifier.workspace_kind is WorkspaceKind.VERIFICATION
    assert verifier.candidate_patch_sha256 == engineer.candidate_patch_sha256 == run.patch_sha256
    assert all(item.command_id == _COMMAND_ID and item.exit_code == 0 for item in evidence)
    assert all(
        not item.timed_out and not item.workspace_mutated_during_execution for item in evidence
    )
    assert verifier.strength is (
        EvidenceStrength.INDEPENDENTLY_VERIFIED if isolated else EvidenceStrength.SIMULATED
    )
    assert engineer.strength is (
        EvidenceStrength.OBSERVED if isolated else EvidenceStrength.SIMULATED
    )
    if isolated:
        for item in evidence:
            transcript = container.artifacts.read_text(item.transcript_artifact_id)
            assert "Ran 3 tests" in transcript and "\nOK" in transcript
            assert BOOTSTRAP_SANDBOX_PROBE_MARKER in transcript
    else:
        assert "SIMULATED_EXECUTION" in {item.code for item in bundle.proof_gaps}
    patch = container.patches.show(run.run_id)
    assert f"diff --git a/{_MODULE_PATH} b/{_MODULE_PATH}" in patch
    assert "new file mode 100644" in patch
    assert '+MESSAGE = "verified new module"' in patch
    assert f"diff --git a/{_CORE_PATH} b/{_CORE_PATH}" in patch
    assert (
        container.repository.inspect(target).status_fingerprint == target_before.status_fingerprint
    )
    assert (target / _CORE_PATH).read_text() == BROKEN_CANARY
    assert not (target / _MODULE_PATH).exists()
    assert (target / "tests/test_metadata.py").read_text() == _METADATA_TEST
    assert container.state.count_executed_intents(run.run_id, "command.run") == 2
    assert container.state.outstanding_leases(run.run_id) == []
    budget = container.budgets.snapshot(run.run_id)
    assert budget.completeness == "complete"
    assert budget.agent_invocations == 3 and budget.model_requests == 5
    assert budget.reported_total_tokens == 250
    assert budget.simulated_steps == 0
    assert budget.tool_calls == 5
    assert budget.outstanding_requests == budget.unknown_requests == 0
    for artifact in container.state.list_artifacts(run.run_id):
        assert _SYNTHETIC_CREDENTIAL not in container.artifacts.read_text(artifact.artifact_id)
    assert (
        len(
            [
                artifact
                for artifact in container.state.list_artifacts(run.run_id)
                if artifact.kind is ArtifactKind.COMMAND_EVIDENCE
            ]
        )
        == 2
    )
    # Reconstruct the control plane before inspection and explicit target application.
    reopened = build_container(container.state_root)
    assert reopened.state.get_run(run.run_id).verified_complete is verified
    assert reopened.budgets.snapshot(run.run_id) == budget
    assert reopened.patches.show(run.run_id) == patch
    assert (
        TaskSpec.model_validate_json(reopened.artifacts.read_text(run.task_spec_artifact_id))
        == persisted_task
    )
    assert (
        VerifierVerdict.model_validate_json(
            reopened.artifacts.read_text(run.verifier_verdict_artifact_id)
        )
        == verdict
    )
    assert (
        EvidenceBundle.model_validate_json(
            reopened.artifacts.read_text(run.evidence_bundle_artifact_id)
        )
        == bundle
    )
    if mapping != "valid":
        # Preserve the unverified review artifact; do not apply these negative cases.
        return run
    applied, result = reopened.patches.apply(run.run_id)
    assert applied.status is RunStatus.COMPLETED and result.applied
    assert sorted(result.changed_paths) == [_CORE_PATH, _MODULE_PATH]
    assert (target / _CORE_PATH).read_text() == FIXED_CANARY
    assert (target / _MODULE_PATH).read_text() == _MODULE_SOURCE
    assert (target / "tests/test_metadata.py").read_text() == _METADATA_TEST
    assert reopened.state.outstanding_leases(run.run_id) == []
    return applied


@pytest.mark.integration
@pytest.mark.parametrize("mapping", ["valid", "empty", "command-plus-transcript"])
async def test_offline_two_criteria_and_new_module_preserve_fake_proof_gap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mapping: _MappingCase
) -> None:
    target, container = _fixture(tmp_path, monkeypatch)
    await _run_and_check(container, target, sandbox="fake", mapping=mapping)


@pytest.mark.docker_integration
@pytest.mark.parametrize("mapping", ["valid", "empty", "command-plus-transcript"])
async def test_real_docker_two_criteria_and_new_module_are_independently_verified(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    real_docker_image: str,
    mapping: _MappingCase,
) -> None:
    target, container = _fixture(tmp_path, monkeypatch)
    provider = container.sandboxes.get("docker")
    assert isinstance(provider, DockerSandboxProvider)
    configuration = SandboxConfiguration(provider="docker", image=real_docker_image)
    preflight = await provider.preflight(
        configuration, requirements_for_configuration(configuration)
    )
    assert preflight.ready
    installation_id = provider.recovery_scope_id
    try:
        await _run_and_check(
            container,
            target,
            sandbox="docker",
            docker_image=real_docker_image,
            preflight=preflight,
            mapping=mapping,
        )
        assert (
            await provider._list_exact(
                provider._require_executable(), {"agent-fleet.installation": installation_id}
            )
            == []
        )
    finally:
        await _cleanup_real_installation_scope(provider, installation_id)
