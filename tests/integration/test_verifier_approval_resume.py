"""Approval resume preserves simulated verifier identity; fake is not isolation proof."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Never

import pytest
from conftest import FleetHarness

from agent_fleet.bootstrap import ApplicationContainer, build_container
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.evidence import CommandEvidence, EvidenceStrength
from agent_fleet.domain.ids import IdPrefix
from agent_fleet.domain.models import (
    AgentInstance,
    AgentStatus,
    ApprovalChoice,
    ApprovalRequest,
    ApprovalStatus,
    ArtifactKind,
    FakeScenario,
    LeaseKind,
    LeaseStatus,
    ResourceLease,
    Run,
    RunStatus,
    VerificationCheckpoint,
    WorkflowStage,
    WorkspaceKind,
)
from agent_fleet.domain.trust import TrustMode

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _verifiers(container: ApplicationContainer, run_id: str) -> list[AgentInstance]:
    with container.state._connect() as connection:
        rows = connection.execute(
            "SELECT data_json FROM agent_instances WHERE run_id = ? AND role = ?",
            (run_id, "verifier"),
        ).fetchall()
    return [AgentInstance.model_validate_json(row["data_json"]) for row in rows]


def _commands(container: ApplicationContainer, run_id: str) -> list[CommandEvidence]:
    return [
        CommandEvidence.model_validate_json(container.artifacts.read_text(artifact.artifact_id))
        for artifact in container.state.list_artifacts(run_id)
        if artifact.kind is ArtifactKind.COMMAND_EVIDENCE
    ]


def _pending(
    container: ApplicationContainer, run: Run, role: str, command_id: str
) -> ApprovalRequest:
    assert run.status is RunStatus.PAUSED_FOR_APPROVAL
    assert run.pending_approval_id is not None
    request = container.state.get_approval(run.pending_approval_id)
    assert request.status is ApprovalStatus.PENDING
    assert request.principal_role == role
    assert request.action == "command.run"
    assert request.resource.identifier == command_id
    assert request.available_choices == [
        ApprovalChoice.DENY,
        ApprovalChoice.ALLOW_ONCE,
        ApprovalChoice.ALLOW_RUN,
        ApprovalChoice.ALLOW_ALWAYS,
    ]
    return request


async def _start(harness: FleetHarness) -> Run:
    harness.container.permissions.configure(
        harness.repository_root, mode=TrustMode.SAFE, allowed_paths=(".",)
    )
    return await build_container(harness.state_root).workflow.start(
        project_path=harness.repository_root,
        goal="Fix the canary behavior",
        runtime_name="fake",
        sandbox_name="fake",
        fake_scenario=FakeScenario.SUCCESS,
    )


async def _approve_and_resume(
    harness: FleetHarness,
    run: Run,
    role: str,
    command_id: str,
    choice: ApprovalChoice = ApprovalChoice.ALLOW_ONCE,
) -> Run:
    approving = build_container(harness.state_root)
    request = _pending(approving, run, role, command_id)
    approving.approvals.approve(request.request_id, choice=choice)
    # A fresh composition root has no process-local runtime/catalog/resource context.
    return await build_container(harness.state_root).workflow.resume(run.run_id)


async def _verification_test_pause(harness: FleetHarness) -> Run:
    run = await _start(harness)
    for role, command_id in (
        ("engineer", "python-build"),
        ("engineer", "python-test"),
        ("verifier", "python-build"),
    ):
        run = await _approve_and_resume(harness, run, role, command_id)
    _pending(build_container(harness.state_root), run, "verifier", "python-test")
    assert run.verification_checkpoint is not None
    return run


@pytest.mark.parametrize(
    "choice", [ApprovalChoice.ALLOW_ONCE, ApprovalChoice.ALLOW_RUN, ApprovalChoice.ALLOW_ALWAYS]
)
async def test_safe_approvals_resume_one_verifier_and_exact_command_context(
    harness: FleetHarness, choice: ApprovalChoice
) -> None:
    run = await _start(harness)
    checkpoint: VerificationCheckpoint | None = None
    request_ids: list[str] = []
    try:
        for executed, (role, command_id) in enumerate(
            (
                ("engineer", "python-build"),
                ("engineer", "python-test"),
                ("verifier", "python-build"),
                ("verifier", "python-test"),
            )
        ):
            checking = build_container(harness.state_root)
            request = _pending(checking, run, role, command_id)
            request_ids.append(request.request_id)
            assert checking.state.count_executed_intents(run.run_id, "command.run") == executed
            assert len(_commands(checking, run.run_id)) == executed
            if role == "engineer":
                assert run.verification_checkpoint is None
                assert _verifiers(checking, run.run_id) == []
            else:
                assert run.verification_checkpoint is not None
                checkpoint = checkpoint or run.verification_checkpoint
                assert run.verification_checkpoint == checkpoint
                assert checking.state.get_run(run.run_id).verification_checkpoint == checkpoint
                assert (
                    checking.state.get_intent(request.intent_id).intent.agent_instance_id
                    == checkpoint.agent_instance_id
                )
                verifiers = _verifiers(checking, run.run_id)
                assert len(verifiers) == 1
                assert verifiers[0].agent_instance_id == checkpoint.agent_instance_id
                assert verifiers[0].status is AgentStatus.PAUSED
                assert verifiers[0].completed_at is None
                workspace = checking.workflow.resources.checkpoint_workspace(
                    run.run_id, checkpoint.workspace_id
                )
                sandbox = checking.workflow.resources.checkpoint_sandbox(
                    run.run_id, checkpoint.sandbox_id
                )
                assert workspace.kind is WorkspaceKind.VERIFICATION
                assert sandbox.workspace_host_path == workspace.path
                assert (
                    checking.repository.workspace_status_fingerprint(workspace)
                    == checkpoint.baseline_fingerprint
                )
                for evidence in _commands(checking, run.run_id):
                    if evidence.principal_role == "verifier":
                        assert evidence.agent_instance_id == checkpoint.agent_instance_id
                        assert evidence.workspace_id == checkpoint.workspace_id
                        assert evidence.sandbox_id == checkpoint.sandbox_id
            run = await _approve_and_resume(harness, run, role, command_id, choice)

        reopened = build_container(harness.state_root)
        assert checkpoint is not None
        assert run.status is RunStatus.READY_FOR_REVIEW
        assert run.verified_complete is False
        assert run.verification_checkpoint is None
        assert reopened.state.get_run(run.run_id).verification_checkpoint is None
        assert run.verifier_agent_instance_id == checkpoint.agent_instance_id
        verifiers = _verifiers(reopened, run.run_id)
        assert len(verifiers) == 1
        assert verifiers[0].agent_instance_id == checkpoint.agent_instance_id
        assert verifiers[0].created_at == checkpoint.created_at
        assert verifiers[0].status is AgentStatus.COMPLETED
        assert verifiers[0].completed_at is not None

        commands = _commands(reopened, run.run_id)
        assert reopened.state.count_executed_intents(run.run_id, "command.run") == 4
        assert len(commands) == len(run.command_evidence_artifact_ids) == 4
        assert len({evidence.evidence_id for evidence in commands}) == 4
        assert len({evidence.execution_id for evidence in commands}) == 4
        assert all(evidence.strength is EvidenceStrength.SIMULATED for evidence in commands)
        assert all(evidence.sandbox_provider == "fake" for evidence in commands)
        verifier_commands = [item for item in commands if item.principal_role == "verifier"]
        engineer_commands = [item for item in commands if item.principal_role == "engineer"]
        assert len(verifier_commands) == len(engineer_commands) == 2
        assert {item.command_id for item in verifier_commands} == {"python-build", "python-test"}
        assert {item.agent_instance_id for item in verifier_commands} == {
            checkpoint.agent_instance_id
        }
        assert {item.workspace_id for item in verifier_commands} == {checkpoint.workspace_id}
        assert {item.sandbox_id for item in verifier_commands} == {checkpoint.sandbox_id}
        assert {item.candidate_patch_sha256 for item in verifier_commands} == {
            checkpoint.patch_sha256
        }
        assert all(item.workspace_kind is WorkspaceKind.VERIFICATION for item in verifier_commands)
        assert all(item.workflow_stage is WorkflowStage.VERIFYING for item in verifier_commands)
        assert all(item.workspace_id != checkpoint.workspace_id for item in engineer_commands)
        assert all(item.sandbox_id != checkpoint.sandbox_id for item in engineer_commands)
        assert reopened.state.outstanding_leases(run.run_id) == []

        events = reopened.state.list_events(run.run_id)
        assert len({*request_ids}) == 4
        assert len([event for event in events if event.event_type == "capability.consumed"]) == 4
        assert (
            len(
                [event for event in events if event.event_type == "verification.checkpoint_created"]
            )
            == 1
        )
        lifecycle = [
            event for event in events if event.agent_instance_id == checkpoint.agent_instance_id
        ]
        assert len([event for event in lifecycle if event.event_type == "agent.started"]) == 3
        assert len([event for event in lifecycle if event.event_type == "agent.paused"]) == 2
        assert len([event for event in lifecycle if event.event_type == "agent.completed"]) == 1
        assert not [event for event in lifecycle if event.event_type == "agent.failed"]
        assert await build_container(harness.state_root).workflow.resume(run.run_id) == run
        assert reopened.state.list_events(run.run_id) == events
        assert _commands(reopened, run.run_id) == commands
    finally:
        await build_container(harness.state_root).workflow.resources.cleanup_run(
            build_container(harness.state_root).state.get_run(run.run_id)
        )


@pytest.mark.parametrize(
    "invalid_context", ["mutated_workspace", "released_worktree", "released_sandbox"]
)
async def test_verifier_resume_fails_closed_when_exact_checkpoint_context_is_lost(
    harness: FleetHarness,
    invalid_context: Literal["mutated_workspace", "released_worktree", "released_sandbox"],
) -> None:
    run = await _verification_test_pause(harness)
    container = build_container(harness.state_root)
    checkpoint = run.verification_checkpoint
    assert checkpoint is not None
    request = _pending(container, run, "verifier", "python-test")
    grant = container.approvals.approve(request.request_id, choice=ApprovalChoice.ALLOW_ONCE)
    commands = _commands(container, run.run_id)
    assert len(commands) == 3
    assert container.state.count_executed_intents(run.run_id, "command.run") == 3
    lease_ids = {lease.lease_id for lease in container.state.list_leases(run.run_id)}
    try:
        if invalid_context == "mutated_workspace":
            workspace = container.workflow.resources.checkpoint_workspace(
                run.run_id, checkpoint.workspace_id
            )
            source = Path(workspace.path) / "src" / "canary_calc" / "core.py"
            before = source.read_bytes()
            source.write_bytes(before + b"\n# changed after approval pause\n")
            assert source.read_bytes() != before
        else:
            kind = (
                LeaseKind.WORKTREE if invalid_context == "released_worktree" else LeaseKind.SANDBOX
            )
            resource_id = (
                checkpoint.workspace_id if kind is LeaseKind.WORKTREE else checkpoint.sandbox_id
            )
            lease = next(
                item
                for item in container.state.active_leases(run.run_id)
                if item.kind is kind and item.resource_id == resource_id
            )
            await container.workflow.resources.cleanup_lease(run, lease)
            assert container.state.get_lease(lease.lease_id).status is LeaseStatus.RELEASED

        resuming = build_container(harness.state_root)
        with pytest.raises(FleetError) as failure:
            await resuming.workflow.resume(run.run_id)
        assert failure.value.code is ErrorCode.RECOVERY_REQUIRED
        failed = resuming.state.get_run(run.run_id)
        # Missing workspace bindings fail during pre-resume restoration, preserving
        # the paused run for explicit recovery instead of entering RUNNING.
        assert failed.status is (
            RunStatus.PAUSED_FOR_APPROVAL
            if invalid_context == "released_worktree"
            else RunStatus.FAILED
        )
        assert failed.verified_complete is False
        assert failed.verification_checkpoint == checkpoint
        assert resuming.state.count_executed_intents(run.run_id, "command.run") == 3
        assert _commands(resuming, run.run_id) == commands
        assert resuming.state.get_grant(grant.grant_id).remaining_uses == 1
        assert {lease.lease_id for lease in resuming.state.list_leases(run.run_id)} == lease_ids
        if invalid_context != "released_worktree":
            assert resuming.state.outstanding_leases(run.run_id) == []
        verifiers = _verifiers(resuming, run.run_id)
        assert len(verifiers) == 1
        assert verifiers[0].agent_instance_id == checkpoint.agent_instance_id
        events = resuming.state.list_events(run.run_id)
        assert (
            len(
                [event for event in events if event.event_type == "verification.checkpoint_created"]
            )
            == 1
        )
        assert len([event for event in events if event.event_type == "capability.consumed"]) == 3
        if invalid_context == "released_worktree":
            with pytest.raises(FleetError) as repeated:
                await build_container(harness.state_root).workflow.resume(run.run_id)
            assert repeated.value.code is ErrorCode.RECOVERY_REQUIRED
            assert resuming.state.get_run(run.run_id) == failed
        else:
            assert await build_container(harness.state_root).workflow.resume(run.run_id) == failed
            assert resuming.state.list_events(run.run_id) == events
        assert _commands(resuming, run.run_id) == commands
    finally:
        await build_container(harness.state_root).workflow.resources.cleanup_run(
            build_container(harness.state_root).state.get_run(run.run_id)
        )


async def test_paused_verifier_with_outstanding_child_cannot_rehydrate_or_replay(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = await _verification_test_pause(harness)
    container = build_container(harness.state_root)
    checkpoint = run.verification_checkpoint
    assert checkpoint is not None
    request = _pending(container, run, "verifier", "python-test")
    grant = container.approvals.approve(request.request_id, choice=ApprovalChoice.ALLOW_ONCE)
    commands = _commands(container, run.run_id)
    sandbox = container.workflow.resources.checkpoint_sandbox(run.run_id, checkpoint.sandbox_id)
    now = container.workflow.clock.now()
    child = ResourceLease(
        lease_id=container.workflow.ids.new(IdPrefix.LEASE),
        run_id=run.run_id,
        kind=LeaseKind.EXECUTION,
        resource_id=container.workflow.ids.new(IdPrefix.EXECUTION),
        status=LeaseStatus.CREATING,
        created_at=now,
        updated_at=now,
        metadata={
            "schema_version": 2,
            "provider": "fake",
            "intent_id": request.intent_id,
            "project_id": run.project_id,
            "task_id": run.task_id,
            "agent_instance_id": checkpoint.agent_instance_id,
            "stage": WorkflowStage.VERIFYING.value,
            "creation_dispatched": False,
            "sandbox_handle": sandbox.model_dump(mode="json"),
        },
    )
    # Simulate a process interruption after journaling but before command dispatch.
    # The fake provider has no actual surviving external execution to clean up.
    container.state.save_lease(child)
    try:
        resuming = build_container(harness.state_root)

        async def deny_recreation_or_execution(*args: object, **kwargs: object) -> Never:
            raise AssertionError("An outstanding child must block all provider activity")

        monkeypatch.setattr(resuming.sandbox, "create", deny_recreation_or_execution)
        monkeypatch.setattr(resuming.sandbox, "exec", deny_recreation_or_execution)
        events = resuming.state.list_events(run.run_id)
        leases = resuming.state.list_leases(run.run_id)
        for _ in range(2):
            with pytest.raises(FleetError) as failure:
                await resuming.workflow.resume(run.run_id)
            assert failure.value.code is ErrorCode.RECOVERY_REQUIRED
            assert resuming.state.get_run(run.run_id) == run
            assert resuming.state.list_events(run.run_id) == events
            assert resuming.state.list_leases(run.run_id) == leases
            assert resuming.state.count_executed_intents(run.run_id, "command.run") == 3
            assert _commands(resuming, run.run_id) == commands
            assert resuming.state.get_grant(grant.grant_id).remaining_uses == 1
            verifiers = _verifiers(resuming, run.run_id)
            assert len(verifiers) == 1
            assert verifiers[0].agent_instance_id == checkpoint.agent_instance_id
            assert verifiers[0].status is AgentStatus.PAUSED
    finally:
        container.state.update_lease_status(child.lease_id, LeaseStatus.RELEASED.value)
        await container.workflow.resources.cleanup_run(container.state.get_run(run.run_id))
