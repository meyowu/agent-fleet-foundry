"""Declarative requirements must survive scoping and independent evidence checks."""

from __future__ import annotations

import json
from typing import Literal

import pytest
import yaml
from conftest import FleetHarness

from agent_fleet.adapters.runtime.fake import FakeRuntimeAdapter
from agent_fleet.application.runtime import RuntimeRegistry
from agent_fleet.bootstrap import build_container
from agent_fleet.domain.config import ConfigSnapshot
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.evidence import EvidenceBundle
from agent_fleet.domain.models import (
    AgentInvocation,
    AgentInvocationResult,
    AgentRole,
    ArtifactKind,
    FakeScenario,
    RunStatus,
    ScopeDecision,
)
from agent_fleet.ports.runtime import RuntimeInvocationServices


def _seed_reviewed_skill(harness: FleetHarness) -> None:
    """Seed a reviewed fixture; this is not the FleetPatch publication acceptance test."""
    fleet = harness.repository_root / ".fleet"
    workflow_path = fleet / "workflows/code-change.yaml"
    workflow = yaml.safe_load(workflow_path.read_text())
    workflow["verificationSkills"] = ["skills/backend-integration.yaml"]
    workflow_path.write_text(yaml.safe_dump(workflow, sort_keys=False), encoding="utf-8")
    profile_path = fleet / "project/verification.yaml"
    profile = yaml.safe_load(profile_path.read_text())
    profile["commands"]["backend-integration"] = {
        "executable": "python",
        "argv": ["-m", "pytest", "tests/integration"],
        "cwd": ".",
        "timeoutSeconds": 60,
        "networkRequired": False,
    }
    profile_path.write_text(yaml.safe_dump(profile, sort_keys=False), encoding="utf-8")
    (fleet / "skills").mkdir()
    (fleet / "skills/backend-integration.yaml").write_text(
        yaml.safe_dump(
            {
                "apiVersion": "agentfleet.dev/v1alpha1",
                "kind": "VerificationSkill",
                "metadata": {"name": "backend-integration"},
                "appliesToPaths": ["src/canary_calc"],
                "requiredCommandIds": ["backend-integration"],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    config = harness.container.workflow.config
    _, snapshot = config.load_snapshot(fleet / "fleet.yaml")
    project = harness.container.state.get_project_by_root(str(harness.repository_root))
    assert project is not None
    info = harness.container.repository.inspect(harness.repository_root)
    harness.container.state.save_project(
        project.model_copy(
            update={
                "fleet_spec_hash": config.snapshot_hash(snapshot),
                "init_status_fingerprint": info.status_fingerprint,
            }
        )
    )
    harness.container = build_container(harness.state_root)


class _BroadScopeRuntime(FakeRuntimeAdapter):
    async def invoke(
        self, request: AgentInvocation, services: RuntimeInvocationServices
    ) -> AgentInvocationResult:
        result = await super().invoke(request, services)
        if request.role == AgentRole.COS:
            assert isinstance(result.output, ScopeDecision)
            return result.model_copy(
                update={"output": result.output.model_copy(update={"allowed_paths": ["src"]})}
            )
        return result


pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.mark.parametrize("broad_scope", [False, True])
async def test_reviewed_backend_skill_is_frozen_and_evidenced_after_reopen(
    harness: FleetHarness, broad_scope: bool
) -> None:
    _seed_reviewed_skill(harness)
    if broad_scope:
        harness.container.workflow.runtimes = RuntimeRegistry({"fake": _BroadScopeRuntime()})
    run = await harness.start()
    assert run.status is RunStatus.READY_FOR_REVIEW
    assert run.task_id is not None and run.evidence_bundle_artifact_id is not None
    task = harness.container.state.get_task(run.task_id)
    if broad_scope:
        assert task.allowed_paths == ["src"]
    assert "backend-integration" in task.required_verification_command_ids
    assert task.required_verification_command_ids == sorted(task.required_verification_command_ids)
    bundle = EvidenceBundle.model_validate_json(
        harness.container.artifacts.read_text(run.evidence_bundle_artifact_id)
    )
    assert bundle.required_verification_command_ids == task.required_verification_command_ids
    integration = [
        command
        for command in bundle.command_evidence
        if command.command_id == "backend-integration"
    ]
    assert len(integration) == 2
    assert len({command.agent_instance_id for command in integration}) == 2
    # Fake receipts prove enforcement and identity separation, not actual test execution.
    assert run.verified_complete is False
    assert harness.container.state.outstanding_leases(run.run_id) == []
    assert not (harness.repository_root / "tests/integration").exists()


async def test_read_only_task_does_not_execute_conditional_verification(
    harness: FleetHarness,
) -> None:
    _seed_reviewed_skill(harness)
    run = await harness.start(FakeScenario.DIRECT)
    assert run.task_id is not None and run.evidence_bundle_artifact_id is not None
    task = harness.container.state.get_task(run.task_id)
    assert task.required_verification_command_ids == []
    bundle = json.loads(harness.container.artifacts.read_text(run.evidence_bundle_artifact_id))
    assert bundle["command_evidence"] == []
    assert harness.container.sandbox.requests == []


@pytest.mark.parametrize("tamper", ["missing-requirement", "changed-command"])
async def test_evidence_rederives_requirement_even_with_self_consistent_task_artifact(
    harness: FleetHarness, tamper: Literal["missing-requirement", "changed-command"]
) -> None:
    _seed_reviewed_skill(harness)
    run = await harness.start()
    assert run.task_id is not None and run.config_snapshot_artifact_id is not None
    task = harness.container.state.get_task(run.task_id)
    if tamper == "missing-requirement":
        task = task.model_copy(
            update={
                "required_verification_command_ids": [
                    item
                    for item in task.required_verification_command_ids
                    if item != "backend-integration"
                ]
            }
        )
    else:
        task = task.model_copy(
            update={
                "verification_commands": [
                    item.model_copy(update={"argv": ("-m", "pytest", "tests/unit")})
                    if item.command_id == "backend-integration"
                    else item
                    for item in task.verification_commands
                ]
            }
        )
    replacement = harness.container.artifacts.create_text(
        kind=ArtifactKind.TASK_SPEC,
        project_id=run.project_id,
        run_id=run.run_id,
        task_id=task.task_id,
        producer="control-plane",
        content=task.model_dump_json(indent=2),
        mime_type="application/json",
    )
    altered = run.model_copy(
        update={
            "task_spec_artifact_id": replacement.artifact_id,
            "task_spec_hash": replacement.sha256,
        }
    )
    snapshot = ConfigSnapshot.model_validate_json(
        harness.container.artifacts.read_text(run.config_snapshot_artifact_id)
    )
    assert "skills/backend-integration.yaml" in {item.path for item in snapshot.files}
    with pytest.raises(FleetError) as caught:
        harness.container.workflow.evidence.assemble(altered, task)
    assert caught.value.code is ErrorCode.ARTIFACT_INTEGRITY_FAILED
    assert "reviewed configuration" in caught.value.message
