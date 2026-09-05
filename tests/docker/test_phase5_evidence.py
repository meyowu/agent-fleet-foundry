"""Normal typed runtime journeys: two criteria, a new module, and honest assurance.

The model is an offline FunctionModel in both cases. Only the explicitly opted-in
Docker case executes the dependency-free fixture tests; FakeSandbox never does.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import pytest
from pydantic_ai import ModelMessage, ModelRequest, ModelResponse, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
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
    calls: dict[str, int] = field(default_factory=dict)
    verifier_read_new_module: bool = False
    verifier_evidence_id: str | None = None

    @staticmethod
    def _reply(parts: list[ToolCallPart]) -> ModelResponse:
        # Explicit reported usage keeps the offline provider protocol accountable.
        return ModelResponse(parts=parts, usage=RequestUsage(input_tokens=40, output_tokens=10))

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
                        {"command_id": _COMMAND_ID, "reason": "Independently check both criteria."},
                        tool_call_id="verifier-unittest",
                    ),
                ]
            )
        returns = {
            part.tool_name: part.content
            for message in messages
            if isinstance(message, ModelRequest)
            for part in message.parts
            if isinstance(part, ToolReturnPart)
        }
        read_result = returns["repo_read_file"]
        command_result = returns["run_verification"]
        assert isinstance(read_result, dict) and isinstance(command_result, dict)
        assert read_result["content"]["content"] == _MODULE_SOURCE
        self.verifier_read_new_module = True
        command_content = command_result["content"]
        assert command_content["exit_code"] == 0
        assert command_content["timed_out"] is False
        evidence_id = command_content["command_evidence_artifact_id"]
        assert isinstance(evidence_id, str)
        self.verifier_evidence_id = evidence_id
        return self._reply(
            [
                ToolCallPart(
                    output,
                    {
                        "verdict": "pass",
                        "criterion_results": list(_CRITERIA),
                        "evidence_artifact_ids": [evidence_id],
                        "structured_criterion_results": [
                            {
                                "criterion_id": identifier,
                                "verdict": "pass",
                                "evidence_artifact_ids": [evidence_id],
                                "command_ids": [_COMMAND_ID],
                                "explanation": description,
                            }
                            for identifier, description in _CRITERIA.items()
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
) -> Run:
    model = _TwoCriterionModel()
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
    assert run.status is RunStatus.READY_FOR_REVIEW
    assert run.verified_complete is isolated
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
        Verdict.PASS if isolated else Verdict.INCONCLUSIVE
    }
    assert bundle.completion_decision is not None
    assert bundle.completion_decision.verified_complete is isolated
    assert bundle.structured_criterion_results is not None
    assert len(bundle.structured_criterion_results) == 2
    assert all(
        item.evidence_artifact_ids == [model.verifier_evidence_id]
        and item.command_ids == [_COMMAND_ID]
        for item in bundle.structured_criterion_results
    )
    assert run.verifier_verdict_artifact_id is not None
    verdict = VerifierVerdict.model_validate_json(
        container.artifacts.read_text(run.verifier_verdict_artifact_id)
    )
    assert verdict.structured_criterion_results == bundle.structured_criterion_results
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
    assert reopened.state.get_run(run.run_id).verified_complete is isolated
    assert reopened.budgets.snapshot(run.run_id) == budget
    assert reopened.patches.show(run.run_id) == patch
    applied, result = reopened.patches.apply(run.run_id)
    assert applied.status is RunStatus.COMPLETED and result.applied
    assert sorted(result.changed_paths) == [_CORE_PATH, _MODULE_PATH]
    assert (target / _CORE_PATH).read_text() == FIXED_CANARY
    assert (target / _MODULE_PATH).read_text() == _MODULE_SOURCE
    assert (target / "tests/test_metadata.py").read_text() == _METADATA_TEST
    assert reopened.state.outstanding_leases(run.run_id) == []
    return applied


@pytest.mark.integration
async def test_offline_two_criteria_and_new_module_preserve_fake_proof_gap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target, container = _fixture(tmp_path, monkeypatch)
    await _run_and_check(container, target, sandbox="fake")


@pytest.mark.docker_integration
async def test_real_docker_two_criteria_and_new_module_are_independently_verified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, real_docker_image: str
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
        )
        assert (
            await provider._list_exact(
                provider._require_executable(), {"agent-fleet.installation": installation_id}
            )
            == []
        )
    finally:
        await _cleanup_real_installation_scope(provider, installation_id)
