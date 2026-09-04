"""Trusted-context ToolGateway for the narrow Phase 1 fake tool surface."""

from __future__ import annotations

import os
import tempfile
from datetime import timedelta
from pathlib import Path
from typing import cast

from pydantic import JsonValue

from agent_fleet.application.artifacts import ArtifactService
from agent_fleet.domain.errors import (
    ApprovalDeniedError,
    ApprovalRequiredError,
    ErrorCode,
    FleetError,
)
from agent_fleet.domain.ids import IdPrefix
from agent_fleet.domain.models import (
    AgentInstance,
    AgentRole,
    ApprovalRequest,
    ApprovalStatus,
    ArtifactKind,
    CanonicalResource,
    ExecRequest,
    IntentStatus,
    PermissionDecision,
    PermissionOutcome,
    Run,
    SandboxHandle,
    ScriptedAction,
    TaskSpec,
    ToolIntent,
    WorkflowStage,
    Workspace,
)
from agent_fleet.domain.security import Redactor, canonical_json_hash, resolve_logical_path
from agent_fleet.ports.clock import Clock
from agent_fleet.ports.id_generator import IdGenerator
from agent_fleet.ports.sandbox import SandboxProvider
from agent_fleet.ports.state_store import StateStore


class ToolGateway:
    """Canonicalizes, authorizes, executes, redacts, and records fake tool calls."""

    def __init__(
        self,
        state: StateStore,
        artifacts: ArtifactService,
        sandbox: SandboxProvider,
        clock: Clock,
        ids: IdGenerator,
        redactor: Redactor,
    ) -> None:
        self.state = state
        self.artifacts = artifacts
        self.sandbox = sandbox
        self.clock = clock
        self.ids = ids
        self.redactor = redactor

    async def execute(
        self,
        *,
        run: Run,
        task: TaskSpec,
        agent: AgentInstance,
        workspace: Workspace,
        sandbox_handle: SandboxHandle,
        scripted: ScriptedAction,
    ) -> dict[str, JsonValue]:
        existing = self.state.find_intent(run.run_id, scripted.idempotency_key)
        intent_id = existing.intent.intent_id if existing else self.ids.new(IdPrefix.INTENT)
        agent_instance_id = (
            existing.intent.agent_instance_id if existing is not None else agent.agent_instance_id
        )
        intent = ToolIntent(
            intent_id=intent_id,
            run_id=run.run_id,
            task_id=task.task_id,
            agent_instance_id=agent_instance_id,
            principal_role=agent.role,
            workflow=task.workflow,
            stage=run.stage or WorkflowStage.IMPLEMENTING,
            action=scripted.action,
            resource=scripted.resource,
            parameters=scripted.parameters,
            reason=scripted.reason,
            side_effect=scripted.side_effect,
            idempotency_key=scripted.idempotency_key,
            requested_ttl_seconds=600 if scripted.action == "fixture.record_side_effect" else None,
            requested_uses=1 if scripted.action == "fixture.record_side_effect" else None,
        )
        intent_hash = canonical_json_hash(intent.model_dump(mode="json"))
        if existing is not None:
            if existing.intent_hash != intent_hash:
                raise FleetError(
                    ErrorCode.COMMAND_DENIED,
                    "An idempotency key was reused for a different canonical intent.",
                    "Start a new run rather than changing an already recorded logical action.",
                )
            if existing.status is IntentStatus.EXECUTED:
                return existing.result or {}
            if existing.status is IntentStatus.DENIED:
                raise ApprovalDeniedError(existing.approval_request_id or "unknown")
            if existing.status is IntentStatus.PENDING_APPROVAL:
                if existing.approval_request_id is None:
                    raise FleetError(
                        ErrorCode.INTERNAL_ERROR,
                        "Pending intent has no approval request.",
                        "Inspect the local state database and rerun from a fresh state directory.",
                    )
                request = self.state.get_approval(existing.approval_request_id)
                if request.status is ApprovalStatus.PENDING:
                    raise ApprovalRequiredError(request.request_id)
                if request.status is ApprovalStatus.DENIED:
                    raise ApprovalDeniedError(request.request_id)
                existing = self.state.consume_grant_and_reserve(
                    request.request_id, existing.intent_hash
                )
            if existing.status is not IntentStatus.RESERVED:
                raise FleetError(
                    ErrorCode.COMMAND_DENIED,
                    "The recorded tool intent is not executable.",
                    "Inspect the approval and run event history.",
                )
        else:
            decision = self._evaluate(intent, task)
            if decision.outcome is PermissionOutcome.DENY:
                raise FleetError(
                    ErrorCode.COMMAND_DENIED,
                    decision.explanation,
                    "Use only the bounded Phase 1 candidate-write and fake-command actions.",
                    details={"decision_code": decision.decision_code},
                )
            if decision.outcome is PermissionOutcome.REQUIRE_APPROVAL:
                now = self.clock.now()
                request = ApprovalRequest(
                    request_id=self.ids.new(IdPrefix.APPROVAL),
                    intent_id=intent.intent_id,
                    run_id=run.run_id,
                    intent_hash=intent_hash,
                    principal_role=intent.principal_role,
                    action=intent.action,
                    resource=intent.resource,
                    reason=intent.reason,
                    created_at=now,
                    expires_at=now + timedelta(minutes=10),
                )
                self.state.create_approval_and_pause(intent, intent_hash, request)
                raise ApprovalRequiredError(request.request_id)
            self.state.reserve_intent(intent, intent_hash)
        result = await self._execute_reserved(
            run=run,
            task=task,
            workspace=workspace,
            sandbox_handle=sandbox_handle,
            intent=intent,
        )
        completed = self.state.complete_intent(intent.intent_id, cast(dict[str, object], result))
        return completed.result or {}

    @staticmethod
    def _evaluate(intent: ToolIntent, task: TaskSpec) -> PermissionDecision:
        if (
            intent.action == "workspace.write_file"
            and intent.principal_role is AgentRole.ENGINEER
            and intent.stage in {WorkflowStage.IMPLEMENTING, WorkflowStage.REPAIRING}
            and intent.resource.kind == "workspace_path"
            and intent.resource.identifier in task.allowed_paths
        ):
            return PermissionDecision(
                outcome=PermissionOutcome.ALLOW,
                decision_code="PHASE1_CANDIDATE_WRITE",
                explanation="Bounded candidate workspace write is allowed.",
            )
        if (
            intent.action == "command.run"
            and intent.principal_role in {AgentRole.ENGINEER, AgentRole.VERIFIER}
            and intent.resource.kind == "fake_command"
            and intent.resource.identifier == "verification://offline-canary"
            and intent.parameters.get("executable") == "python"
            and intent.parameters.get("argv") == ["-m", "pytest", "-q"]
            and intent.parameters.get("cwd") == "."
        ):
            return PermissionDecision(
                outcome=PermissionOutcome.ALLOW,
                decision_code="PHASE1_FAKE_COMMAND",
                explanation="Declared fake command recording is allowed.",
            )
        if (
            intent.action == "fixture.record_side_effect"
            and intent.principal_role is AgentRole.ENGINEER
            and intent.resource
            == CanonicalResource(kind="fake_side_effect", identifier="fixture://approval-proof")
            and intent.parameters == {"record": "approved-once"}
        ):
            return PermissionDecision(
                outcome=PermissionOutcome.REQUIRE_APPROVAL,
                decision_code="PHASE1_APPROVAL_PROOF",
                explanation="The scripted logical side effect requires a one-use user grant.",
            )
        return PermissionDecision(
            outcome=PermissionOutcome.DENY,
            decision_code="PHASE1_DEFAULT_DENY",
            explanation=(
                "The action is outside the Phase 1 role, stage, resource, or task boundary."
            ),
            protected=True,
        )

    async def _execute_reserved(
        self,
        *,
        run: Run,
        task: TaskSpec,
        workspace: Workspace,
        sandbox_handle: SandboxHandle,
        intent: ToolIntent,
    ) -> dict[str, JsonValue]:
        if intent.action == "workspace.write_file":
            content = intent.parameters.get("content")
            if not isinstance(content, str):
                raise FleetError(
                    ErrorCode.COMMAND_DENIED,
                    "workspace.write_file requires string content.",
                    "Submit a validated structured write action.",
                )
            if self.redactor.contains_secret(content):
                raise FleetError(
                    ErrorCode.COMMAND_DENIED,
                    "A registered secret was detected in a candidate write.",
                    "Remove the secret; Fleet did not write or persist it.",
                )
            _atomic_workspace_write(Path(workspace.path), intent.resource.identifier, content)
            return {"path": intent.resource.identifier, "bytes_written": len(content.encode())}
        executable = intent.parameters.get("executable")
        argv = intent.parameters.get("argv")
        cwd = intent.parameters.get("cwd")
        if intent.action == "fixture.record_side_effect":
            executable = "agent-fleet-fake-side-effect"
            argv = ["record", "approved-once"]
            cwd = "."
        if (
            not isinstance(executable, str)
            or not isinstance(cwd, str)
            or not isinstance(argv, list)
        ):
            raise FleetError(
                ErrorCode.COMMAND_DENIED,
                "Fake command parameters are malformed.",
                "Use canonical executable, argv, and logical cwd fields.",
            )
        if any(not isinstance(item, str) for item in argv):
            raise FleetError(
                ErrorCode.COMMAND_DENIED,
                "Fake command argv must contain only strings.",
                "Use a structured argv list without shell syntax.",
            )
        resolve_logical_path(Path(workspace.path), cwd, allow_missing=False)
        request = ExecRequest(
            executable=executable,
            argv=cast(list[str], argv),
            cwd=cwd,
            environment={},
        )
        execution = await self.sandbox.exec(sandbox_handle, request)
        transcript = self.artifacts.create_text(
            kind=ArtifactKind.COMMAND_TRANSCRIPT,
            project_id=run.project_id,
            run_id=run.run_id,
            task_id=task.task_id,
            producer="fake-sandbox",
            content=(
                f"security_level=fake\nexecutable={request.executable}\nargv={request.argv!r}\n"
                f"exit_code={execution.exit_code}\ntimed_out={execution.timed_out}\n"
                f"stdout:\n{execution.stdout}\nstderr:\n{execution.stderr}"
            ),
        )
        return {
            "exit_code": execution.exit_code,
            "timed_out": execution.timed_out,
            "transcript_artifact_id": transcript.artifact_id,
        }


def _atomic_workspace_write(root: Path, logical_path: str, content: str) -> None:
    destination = resolve_logical_path(root, logical_path, allow_missing=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".fleet-write-", dir=destination.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
