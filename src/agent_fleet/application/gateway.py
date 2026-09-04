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
from agent_fleet.domain.evidence import CommandEvidence, EvidenceStrength
from agent_fleet.domain.ids import IdPrefix
from agent_fleet.domain.models import (
    AgentInstance,
    ApprovalRequest,
    ApprovalStatus,
    ArtifactKind,
    ExecRequest,
    FleetEvent,
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
from agent_fleet.ports.permission import PermissionBroker
from agent_fleet.ports.sandbox import SandboxProvider
from agent_fleet.ports.state_store import StateStore


class ToolGateway:
    """Canonicalizes, authorizes, executes, redacts, and records fake tool calls."""

    def __init__(
        self,
        state: StateStore,
        artifacts: ArtifactService,
        sandbox: SandboxProvider,
        permission_broker: PermissionBroker,
        clock: Clock,
        ids: IdGenerator,
        redactor: Redactor,
    ) -> None:
        self.state = state
        self.artifacts = artifacts
        self.sandbox = sandbox
        self.permission_broker = permission_broker
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
        if self.redactor.contains_secret_data(scripted.model_dump(mode="json")):
            raise FleetError(
                ErrorCode.COMMAND_DENIED,
                "A registered secret was detected in a runtime-requested tool intent.",
                "Remove the secret from the request; Fleet did not persist or execute it.",
            )
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
            decision = self.permission_broker.evaluate(intent, task, self.sandbox.capabilities)
            self._record_permission_decision(run, intent, decision)
            if decision.outcome is PermissionOutcome.DENY:
                self.state.reserve_intent(intent, intent_hash)
                self.state.deny_intent(intent.intent_id)
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
        capabilities = self.sandbox.capabilities
        transcript = self.artifacts.create_text(
            kind=ArtifactKind.COMMAND_TRANSCRIPT,
            project_id=run.project_id,
            run_id=run.run_id,
            task_id=task.task_id,
            producer=f"{capabilities.provider}-sandbox",
            content=(
                f"security_level={capabilities.security_level.value}\n"
                f"provider={capabilities.provider}\n"
                f"executes_code={str(capabilities.executes_code).lower()}\n"
                f"executable={request.executable}\nargv={request.argv!r}\n"
                f"exit_code={execution.exit_code}\ntimed_out={execution.timed_out}\n"
                f"stdout:\n{execution.stdout}\nstderr:\n{execution.stderr}"
            ),
        )
        evidence_artifact_id = self.ids.new(IdPrefix.ARTIFACT)
        evidence = CommandEvidence(
            evidence_id=evidence_artifact_id,
            run_id=run.run_id,
            task_id=task.task_id,
            agent_instance_id=intent.agent_instance_id,
            executable=request.executable,
            argv=request.argv,
            cwd=request.cwd,
            sandbox_provider=capabilities.provider,
            sandbox_security_level=capabilities.security_level,
            strength=(
                EvidenceStrength.OBSERVED
                if capabilities.executes_code
                else EvidenceStrength.SIMULATED
            ),
            exit_code=execution.exit_code,
            timed_out=execution.timed_out,
            output_truncated=execution.output_truncated,
            transcript_artifact_id=transcript.artifact_id,
            workspace_base_revision=workspace.base_revision,
            config_snapshot_sha256=task.config_snapshot_hash,
            candidate_patch_sha256=run.patch_sha256,
            started_at=execution.started_at,
            completed_at=execution.completed_at,
        )
        evidence_artifact = self.artifacts.create_text(
            kind=ArtifactKind.COMMAND_EVIDENCE,
            project_id=run.project_id,
            run_id=run.run_id,
            task_id=task.task_id,
            artifact_id=evidence_artifact_id,
            producer="tool-gateway",
            content=evidence.model_dump_json(indent=2),
            mime_type="application/json",
            metadata={
                "intent_id": intent.intent_id,
                "evidence_id": evidence.evidence_id,
                "strength": evidence.strength.value,
            },
        )
        return {
            "exit_code": execution.exit_code,
            "timed_out": execution.timed_out,
            "transcript_artifact_id": transcript.artifact_id,
            "command_evidence_artifact_id": evidence_artifact.artifact_id,
        }

    def _record_permission_decision(
        self, run: Run, intent: ToolIntent, decision: PermissionDecision
    ) -> None:
        cleaned, summary = self.redactor.redact_data(
            {
                "intent_id": intent.intent_id,
                "intent_hash": canonical_json_hash(intent.model_dump(mode="json")),
                "action": intent.action,
                "resource": intent.resource.model_dump(mode="json"),
                "outcome": decision.outcome.value,
                "decision_code": decision.decision_code,
                "explanation": decision.explanation,
            }
        )
        self.state.append_event(
            FleetEvent(
                event_id=self.ids.new(IdPrefix.EVENT),
                event_type="permission.decision",
                occurred_at=self.clock.now(),
                project_id=run.project_id,
                run_id=run.run_id,
                task_id=intent.task_id,
                agent_instance_id=intent.agent_instance_id,
                correlation_id=run.correlation_id,
                payload=cast(dict[str, JsonValue], cleaned),
                redaction_summary=summary,
            )
        )


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
