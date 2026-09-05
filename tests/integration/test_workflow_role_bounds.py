"""Independent role/delegation/feedback checks through the ordinary fake workflow.

Fake commands remain simulated. These tests do not prove provider execution,
Docker isolation, or the unfinished graph/chat milestones.
"""

from __future__ import annotations

import json
from typing import Literal

import pytest
import yaml
from conftest import FleetHarness

from agent_fleet.adapters.runtime.fake import FakeRuntimeAdapter
from agent_fleet.application.runtime import RuntimeRegistry
from agent_fleet.domain.config import FleetSpec
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.fleet_plan import FleetPlan
from agent_fleet.domain.models import (
    AgentInvocation,
    AgentInvocationResult,
    AgentRole,
    ArtifactKind,
    FakeScenario,
    Run,
    RunStatus,
    ScopeDecision,
    VerifierVerdict,
    WorkflowStage,
)
from agent_fleet.ports.runtime import RuntimeInvocationServices

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_DIRECT_RESPONSE = (
    "The repository contains the bounded canary project. No source changes or tests "
    "were executed for this read-only answer; inspect the project artifacts for context."
)
_SECRET = "ROLE-BOUNDS-REGISTERED-SECRET-7c8b9d"


class RecordingRuntime(FakeRuntimeAdapter):
    def __init__(self, *, direct_response: str | None = _DIRECT_RESPONSE) -> None:
        self.requests: list[AgentInvocation] = []
        self.direct_response = direct_response

    async def invoke(
        self, request: AgentInvocation, services: RuntimeInvocationServices
    ) -> AgentInvocationResult:
        self.requests.append(request.model_copy(deep=True))
        result = await super().invoke(request, services)
        if request.role == AgentRole.COS:
            assert isinstance(result.output, ScopeDecision)
            if result.output.fleet_strategy == "direct":
                data = result.output.model_dump(mode="json")
                data["response"] = self.direct_response
                return result.model_copy(update={"output": ScopeDecision.model_validate(data)})
        return result


def _recording_runtime(
    harness: FleetHarness, *, direct_response: str | None = _DIRECT_RESPONSE
) -> RecordingRuntime:
    runtime = RecordingRuntime(direct_response=direct_response)
    harness.container.workflow.runtimes = RuntimeRegistry({"fake": runtime})
    return runtime


def _review_fixture_configuration(
    harness: FleetHarness,
    *,
    steps: dict[str, int] | None = None,
    delegates: tuple[str, ...] | None = None,
) -> None:
    """Republish reviewed fixture configuration, never mutate a live Run snapshot."""
    path = harness.repository_root / ".fleet" / "fleet.yaml"
    config = harness.container.workflow.config
    original, _ = config.load_snapshot(path)
    data = original.model_dump(mode="json", by_alias=True)
    for role, maximum in (steps or {}).items():
        data["spec"]["agents"][role]["maxSteps"] = maximum
    if delegates is not None:
        data["spec"]["agents"]["cos"]["mayDelegateTo"] = list(delegates)
    reviewed = FleetSpec.model_validate(data)
    path.write_text(yaml.safe_dump(reviewed.model_dump(mode="json", by_alias=True)))
    _, snapshot = config.load_snapshot(path)
    project = harness.container.permissions.project_at(harness.repository_root)
    artifact = harness.container.artifacts.create_text(
        kind=ArtifactKind.CONFIG_SNAPSHOT,
        project_id=project.project_id,
        producer="test-reviewed-configuration",
        content=snapshot.model_dump_json(),
        mime_type="application/json",
        redact=False,
        reject_secret=True,
    )
    harness.container.state.save_project(
        project.model_copy(
            update={
                "fleet_spec_hash": config.snapshot_hash(snapshot),
                "config_snapshot_artifact_id": artifact.artifact_id,
                "init_status_fingerprint": harness.container.repository.inspect(
                    harness.repository_root
                ).status_fingerprint,
            }
        )
    )


def _assert_only_cos_without_resources(harness: FleetHarness, run_id: str) -> None:
    with harness.container.state._connect() as connection:
        roles = connection.execute(
            "SELECT role FROM agent_instances WHERE run_id = ? ORDER BY rowid", (run_id,)
        ).fetchall()
        leases = connection.execute(
            "SELECT COUNT(*) FROM resource_leases WHERE run_id = ?", (run_id,)
        ).fetchone()
    assert [row["role"] for row in roles] == ["cos"]
    assert leases is not None and leases[0] == 0
    assert harness.container.state.count_executed_intents(run_id, "command.run") == 0


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        ({"cos": 3, "engineer": 7, "verifier": 4}, {"cos": 3, "engineer": 7, "verifier": 4}),
        (
            {"cos": 100, "engineer": 100, "verifier": 100},
            {"cos": 10, "engineer": 20, "verifier": 10},
        ),
    ],
)
async def test_reviewed_role_steps_bound_invocations_and_frozen_plan(
    harness: FleetHarness, configured: dict[str, int], expected: dict[str, int]
) -> None:
    _review_fixture_configuration(harness, steps=configured)
    runtime = _recording_runtime(harness)

    run = await harness.start()

    assert run.status is RunStatus.READY_FOR_REVIEW
    assert {str(request.role): request.max_steps for request in runtime.requests} == expected
    assert len(runtime.requests) == 3
    assert run.fleet_plan_artifact_id is not None
    plan = FleetPlan.model_validate_json(
        harness.container.artifacts.read_text(run.fleet_plan_artifact_id)
    )
    assert {node.role_id: node.max_steps for node in plan.nodes} == {
        "engineer": expected["engineer"],
        "verifier": expected["verifier"],
    }
    assert run.verified_complete is False


@pytest.mark.parametrize("delegates", [(), ("engineer",), ("verifier",)])
async def test_missing_actual_delegate_fails_before_workers_or_workspaces(
    harness: FleetHarness, delegates: tuple[str, ...]
) -> None:
    _review_fixture_configuration(harness, delegates=delegates)
    runtime = _recording_runtime(harness)

    with pytest.raises(FleetError) as captured:
        await harness.start()

    assert captured.value.code is ErrorCode.COMMAND_DENIED
    assert "delegation ceiling" in captured.value.message
    assert [request.role for request in runtime.requests] == [AgentRole.COS]
    run_id = str(captured.value.details["run_id"])
    assert harness.container.state.get_run(run_id).status is RunStatus.FAILED
    _assert_only_cos_without_resources(harness, run_id)


async def test_unused_declared_verifier_does_not_require_delegation(
    harness: FleetHarness,
) -> None:
    _review_fixture_configuration(harness, delegates=("engineer",))
    runtime = _recording_runtime(harness)

    run = await harness.start(FakeScenario.SINGLE_ENGINEER)

    assert run.status is RunStatus.READY_FOR_REVIEW
    assert [request.role for request in runtime.requests] == [AgentRole.COS, AgentRole.ENGINEER]
    assert run.verifier_agent_instance_id is None
    assert run.verified_complete is False


async def test_repair_receives_exact_prior_verdict_and_fresh_role_identity(
    harness: FleetHarness,
) -> None:
    runtime = _recording_runtime(harness)

    run = await harness.start(FakeScenario.REPAIR)

    assert run.status is RunStatus.READY_FOR_REVIEW
    engineers = [request for request in runtime.requests if request.role == AgentRole.ENGINEER]
    verifiers = [request for request in runtime.requests if request.role == AgentRole.VERIFIER]
    assert len(engineers) == len(verifiers) == 2
    assert engineers[0].agent_instance_id != engineers[1].agent_instance_id
    assert verifiers[0].agent_instance_id != verifiers[1].agent_instance_id
    assert engineers[0].input["previous_verifier_feedback"] is None
    assert engineers[1].stage is WorkflowStage.REPAIRING
    assert engineers[1].iteration == 1
    verdicts = [
        artifact
        for artifact in harness.container.state.list_artifacts(run.run_id)
        if artifact.kind is ArtifactKind.VERIFIER_VERDICT
    ]
    assert len(verdicts) == 2
    prior = VerifierVerdict.model_validate_json(
        harness.container.artifacts.read_text(verdicts[0].artifact_id)
    )
    assert prior.required_repairs == ["Use the required stable ValueError message."]
    assert engineers[1].input["previous_verifier_feedback"] == prior.model_dump(mode="json")
    assert verdicts[0].artifact_id in engineers[1].context_artifact_ids
    assert verdicts[1].artifact_id not in engineers[1].context_artifact_ids
    assert run.engineer_checkpoint is None
    assert run.verification_checkpoint is None
    assert run.verified_complete is False


async def test_direct_without_response_fails_without_worker_or_response_artifact(
    harness: FleetHarness,
) -> None:
    runtime = _recording_runtime(harness, direct_response=None)

    with pytest.raises(FleetError) as captured:
        await harness.start(FakeScenario.DIRECT)

    assert captured.value.code is ErrorCode.RUNTIME_OUTPUT_INVALID
    run_id = str(captured.value.details["run_id"])
    assert len(runtime.requests) == 1
    _assert_only_cos_without_resources(harness, run_id)
    assert not [
        item
        for item in harness.container.state.list_artifacts(run_id)
        if item.kind is ArtifactKind.COS_RESPONSE
    ]


async def test_direct_response_is_substantive_but_never_command_evidence(
    harness: FleetHarness,
) -> None:
    _review_fixture_configuration(harness, delegates=())
    runtime = _recording_runtime(harness)

    run = await harness.start(FakeScenario.DIRECT)

    assert run.status is RunStatus.COMPLETED
    assert len(runtime.requests) == 1
    _assert_only_cos_without_resources(harness, run.run_id)
    artifacts = harness.container.state.list_artifacts(run.run_id)
    responses = [item for item in artifacts if item.kind is ArtifactKind.COS_RESPONSE]
    assert len(responses) == 1
    response = responses[0]
    assert response.run_id == run.run_id and response.task_id == run.task_id
    assert response.project_id == run.project_id
    assert response.producer == "fake-runtime:cos"
    assert response.metadata["assurance"] == "model_response_not_execution_evidence"
    assert harness.container.artifacts.read_text(response.artifact_id) == _DIRECT_RESPONSE
    assert not [item for item in artifacts if item.kind is ArtifactKind.COMMAND_EVIDENCE]
    assert run.command_evidence_artifact_ids == []
    assert run.patch_artifact_id is None
    assert run.verified_complete is False


async def test_direct_response_registered_secret_is_rejected_before_publication(
    harness: FleetHarness,
) -> None:
    harness.container.redactor.register_secrets([_SECRET])
    _recording_runtime(harness, direct_response=f"Unsafe response {_SECRET}")

    with pytest.raises(FleetError) as captured:
        await harness.start(FakeScenario.DIRECT)

    assert captured.value.code is ErrorCode.COMMAND_DENIED
    assert _SECRET not in str(captured.value)
    run_id = str(captured.value.details["run_id"])
    _assert_only_cos_without_resources(harness, run_id)
    assert not [
        item
        for item in harness.container.state.list_artifacts(run_id)
        if item.kind is ArtifactKind.COS_RESPONSE
    ]


@pytest.mark.parametrize("fault", ["malformed", "foreign-task", "wrong-kind", "secret"])
async def test_repair_rejects_untrusted_feedback_before_next_engineer(
    harness: FleetHarness,
    monkeypatch: pytest.MonkeyPatch,
    fault: Literal["malformed", "foreign-task", "wrong-kind", "secret"],
) -> None:
    runtime = _recording_runtime(harness)
    workflow = harness.container.workflow
    original_verify = workflow._verify

    async def replace_persisted_feedback(run: Run) -> VerifierVerdict:
        verdict = await original_verify(run)
        current = harness.container.state.get_run(run.run_id)
        assert current.task_id is not None
        payload = verdict.model_dump(mode="json")
        if fault == "secret":
            payload["required_repairs"] = [f"Untrusted repair {_SECRET}"]
        artifact = harness.container.artifacts.create_text(
            kind=ArtifactKind.IMPLEMENTATION_REPORT
            if fault == "wrong-kind"
            else ArtifactKind.VERIFIER_VERDICT,
            project_id=current.project_id,
            run_id=current.run_id,
            task_id="task_" + "a" * 32 if fault == "foreign-task" else current.task_id,
            producer="test-corrupt-feedback",
            content="{broken-json" if fault == "malformed" else json.dumps(payload),
            mime_type="application/json",
        )
        # Model a previously stored artifact whose value becomes a registered
        # secret before it is next consumed, rather than bypassing publication redaction.
        if fault == "secret":
            harness.container.redactor.register_secrets([_SECRET])
        harness.container.state.save_run(
            current.model_copy(update={"verifier_verdict_artifact_id": artifact.artifact_id}),
            "test.feedback_substituted",
            {"fault": fault},
        )
        return verdict

    monkeypatch.setattr(workflow, "_verify", replace_persisted_feedback)

    with pytest.raises(FleetError) as captured:
        await harness.start(FakeScenario.REPAIR)

    assert captured.value.code is (
        ErrorCode.COMMAND_DENIED if fault == "secret" else ErrorCode.ARTIFACT_INTEGRITY_FAILED
    )
    assert _SECRET not in str(captured.value)
    assert not [request for request in runtime.requests if request.stage is WorkflowStage.REPAIRING]
    run_id = runtime.requests[0].run_id
    assert harness.container.state.get_run(run_id).status is RunStatus.FAILED
    assert harness.container.state.outstanding_leases(run_id) == []
    assert all(_SECRET not in request.model_dump_json() for request in runtime.requests)
