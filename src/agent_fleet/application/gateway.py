"""Trusted-context ToolGateway for the narrow Phase 1 fake tool surface."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path
from typing import cast

from pydantic import JsonValue

from agent_fleet.application.artifacts import ArtifactService
from agent_fleet.application.resources import (
    execution_lease_binding_is_valid,
    execution_recovery_request_from_lease,
)
from agent_fleet.application.sandboxes import SandboxRegistry
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
    ApprovalChoice,
    ApprovalRequest,
    ApprovalStatus,
    ArtifactKind,
    CommandSpec,
    ExecRequest,
    FleetEvent,
    IntentStatus,
    LeaseKind,
    LeaseStatus,
    PermissionDecision,
    PermissionOutcome,
    ResourceLease,
    Run,
    SandboxCleanupResult,
    SandboxExecutionHandle,
    SandboxHandle,
    SandboxNetworkMode,
    SandboxSecurityLevel,
    ScriptedAction,
    TaskSpec,
    ToolIntent,
    WorkflowStage,
    Workspace,
    WorkspaceKind,
)
from agent_fleet.domain.paths import path_is_within
from agent_fleet.domain.security import Redactor, canonical_json_hash, sha256_bytes
from agent_fleet.ports.clock import Clock
from agent_fleet.ports.id_generator import IdGenerator
from agent_fleet.ports.permission import PermissionBroker
from agent_fleet.ports.repository import RepositoryPort
from agent_fleet.ports.sandbox import SandboxProvider
from agent_fleet.ports.state_store import StateStore
from agent_fleet.ports.workspace_files import WorkspaceFileSystem


class ToolGateway:
    """Canonicalizes, authorizes, executes, redacts, and records fake tool calls."""

    def __init__(
        self,
        state: StateStore,
        artifacts: ArtifactService,
        sandbox: SandboxProvider | SandboxRegistry,
        permission_broker: PermissionBroker,
        clock: Clock,
        ids: IdGenerator,
        redactor: Redactor,
        workspace_files: WorkspaceFileSystem,
        repository: RepositoryPort | None = None,
    ) -> None:
        self.state = state
        self.artifacts = artifacts
        self.sandboxes = (
            sandbox
            if isinstance(sandbox, SandboxRegistry)
            else SandboxRegistry({sandbox.capabilities.provider: sandbox})
        )
        self.permission_broker = permission_broker
        self.clock = clock
        self.ids = ids
        self.redactor = redactor
        self.repository = repository
        self.workspace_files = workspace_files

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
        self._validate_context(run, task, agent, workspace, sandbox_handle)
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
            # Display prose may change when a model reconstructs a paused call.
            # Preserve the originally reviewed explanation; every execution-bearing
            # field still participates in the exact immutable intent hash below.
            reason=existing.intent.reason if existing is not None else scripted.reason,
            side_effect=scripted.side_effect,
            idempotency_key=scripted.idempotency_key,
            requested_ttl_seconds=600 if scripted.action == "fixture.record_side_effect" else None,
            requested_uses=1 if scripted.action == "fixture.record_side_effect" else None,
        )
        intent_hash = canonical_json_hash(intent.model_dump(mode="json"))
        resumed_reserved_command = (
            existing is not None
            and existing.status is IntentStatus.RESERVED
            and existing.intent.action == "command.run"
        )
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
        provider = self.sandboxes.get(sandbox_handle.provider)
        decision = self.permission_broker.evaluate(intent, task, provider.capabilities)
        self._record_permission_decision(run, intent, decision)
        if decision.outcome is PermissionOutcome.DENY:
            if existing is None:
                self.state.reserve_intent(intent, intent_hash)
            self.state.deny_intent(intent.intent_id)
            raise FleetError(
                ErrorCode.COMMAND_DENIED,
                decision.explanation,
                "Review the exact role, task, command, and user policy scope.",
                details={"decision_code": decision.decision_code},
            )
        if existing is not None:
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
                if decision.outcome is not PermissionOutcome.ALLOW:
                    raise FleetError(
                        ErrorCode.APPROVAL_INVALID,
                        "The earlier approval is no longer authorized by current policy.",
                        "Review revoked or expired grants, then start a new run if needed.",
                    )
                existing = self.state.consume_grant_and_reserve(
                    request.request_id, existing.intent_hash
                )
            if existing.status is not IntentStatus.RESERVED:
                raise FleetError(
                    ErrorCode.COMMAND_DENIED,
                    "The recorded tool intent is not executable.",
                    "Inspect the approval and run event history.",
                )
            if decision.outcome is not PermissionOutcome.ALLOW:
                raise FleetError(
                    ErrorCode.APPROVAL_INVALID,
                    "The reserved operation is not authorized by current policy.",
                    "Inspect the interrupted operation and start a fresh run after review.",
                )
            if resumed_reserved_command:
                raise FleetError(
                    ErrorCode.COMMAND_OUTCOME_AMBIGUOUS,
                    "A prior command intent has no authoritative terminal outcome.",
                    "Recover its sandbox resources and start a fresh run; "
                    "Fleet will not replay it.",
                    details={"intent_id": existing.intent.intent_id},
                )
        else:
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
                    authorization_scope=decision.effective_scope,
                    available_choices=decision.available_choices
                    or [ApprovalChoice.DENY, ApprovalChoice.ALLOW_ONCE],
                    created_at=now,
                    expires_at=now + timedelta(minutes=10),
                )
                self.state.create_approval_and_pause(intent, intent_hash, request)
                raise ApprovalRequiredError(request.request_id)
            if decision.grant_id is not None:
                if decision.effective_scope is None:
                    raise FleetError(
                        ErrorCode.APPROVAL_INVALID,
                        "A reusable grant has no exact authorization scope.",
                        "Inspect the stored grant before retrying.",
                    )
                self.state.consume_matching_grant_and_reserve(
                    decision.grant_id,
                    intent,
                    intent_hash,
                    canonical_json_hash(decision.effective_scope),
                )
            elif decision.source_rule_id is not None:
                if decision.effective_scope is None:
                    raise FleetError(
                        ErrorCode.APPROVAL_INVALID,
                        "A persistent rule has no exact authorization scope.",
                        "Inspect the stored rule before retrying.",
                    )
                self.state.reserve_trust_rule_intent(
                    intent,
                    intent_hash,
                    canonical_json_hash(decision.effective_scope),
                    decision.source_rule_id,
                )
            else:
                self.state.reserve_intent(intent, intent_hash)
        if not self.state.claim_reserved_intent_for_dispatch(intent.intent_id, intent_hash):
            authoritative = self.state.get_intent(intent.intent_id)
            if (
                authoritative.intent_hash == intent_hash
                and authoritative.status is IntentStatus.EXECUTED
            ):
                return authoritative.result or {}
            raise FleetError(
                ErrorCode.COMMAND_OUTCOME_AMBIGUOUS,
                "This tool intent already has an execution owner without a terminal result.",
                "Inspect or recover the existing operation; Fleet will not dispatch it twice.",
                details={"intent_id": intent.intent_id},
            )
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
            bytes_written = self.workspace_files.write_text(
                Path(workspace.path), intent.resource.identifier, content
            )
            return {"path": intent.resource.identifier, "bytes_written": bytes_written}
        if intent.action == "repo.list_files":
            paths = [
                path
                for path in self.workspace_files.list_files(Path(workspace.path))
                if _path_in_task_scope(task, path)
            ]
            return {"paths": cast(JsonValue, paths)}
        if intent.action == "repo.read_file":
            path = intent.resource.identifier
            if not _path_in_task_scope(task, path):
                raise FleetError(
                    ErrorCode.PATH_OUTSIDE_SCOPE,
                    "Read path is outside the TaskSpec scope.",
                    "Read only a path in the bounded task scope.",
                )
            content = self.workspace_files.read_text(Path(workspace.path), path)
            if self.redactor.contains_secret(content):
                raise FleetError(
                    ErrorCode.COMMAND_DENIED,
                    "A registered secret was detected in a workspace read.",
                    "Remove the secret from the candidate workspace before retrying.",
                )
            return {"path": path, "content": content, "sha256": sha256_bytes(content.encode())}
        if intent.action == "repo.search_text":
            query = intent.parameters.get("query")
            if not isinstance(query, str):
                raise FleetError(
                    ErrorCode.COMMAND_DENIED,
                    "repo.search_text requires a literal string query.",
                    "Use the bounded literal search tool schema.",
                )
            visible_paths = [
                path
                for path in self.workspace_files.list_files(Path(workspace.path))
                if _path_in_task_scope(task, path)
            ]
            results = self.workspace_files.search_text(
                Path(workspace.path), query, logical_paths=visible_paths
            )
            if self.redactor.contains_secret_data(results):
                raise FleetError(
                    ErrorCode.COMMAND_DENIED,
                    "A registered secret was detected in workspace search results.",
                    "Remove the secret from the candidate workspace before retrying.",
                )
            return {"results": cast(JsonValue, results)}
        if intent.action == "workspace.apply_edit":
            expected_sha256 = intent.parameters.get("expected_sha256")
            old = intent.parameters.get("old")
            new = intent.parameters.get("new")
            expected_matches = intent.parameters.get("expected_matches")
            if (
                not isinstance(expected_sha256, str)
                or not isinstance(old, str)
                or not isinstance(new, str)
                or type(expected_matches) is not int
            ):
                raise FleetError(
                    ErrorCode.COMMAND_DENIED,
                    "workspace.apply_edit parameters are malformed.",
                    "Use the exact structured edit schema.",
                )
            bytes_written = self.workspace_files.apply_edit(
                Path(workspace.path),
                intent.resource.identifier,
                expected_sha256=expected_sha256,
                old=old,
                new=new,
                expected_matches=expected_matches,
            )
            return {"path": intent.resource.identifier, "bytes_written": bytes_written}
        if intent.action == "workspace.delete_path":
            expected_sha256 = intent.parameters.get("expected_sha256")
            if not isinstance(expected_sha256, str):
                raise FleetError(
                    ErrorCode.COMMAND_DENIED,
                    "workspace.delete_path requires an exact expected file hash.",
                    "Read the file and request deletion against its current hash.",
                )
            self.workspace_files.delete_file(
                Path(workspace.path),
                intent.resource.identifier,
                expected_sha256=expected_sha256,
            )
            return {"path": intent.resource.identifier, "deleted": True}
        if intent.action == "workspace.get_diff":
            if self.repository is None:
                raise FleetError(
                    ErrorCode.INTERNAL_ERROR,
                    "Repository diff service is not configured.",
                    "Run through the Agent Fleet composition root.",
                )
            patch = self.repository.compute_patch(workspace)
            return {
                "patch": patch.content,
                "patch_sha256": patch.sha256,
                "changed_paths": cast(JsonValue, patch.changed_paths),
            }
        if intent.action == "fixture.record_side_effect":
            execution_network_mode: SandboxNetworkMode = "none"
            command = CommandSpec(
                command_id="approval-proof",
                executable="agent-fleet-fake-side-effect",
                argv=("record", "approved-once"),
            )
        elif intent.action == "command.run":
            command_id = intent.parameters.get("command_id")
            command_hash = intent.parameters.get("command_spec_sha256")
            raw_network_mode = intent.parameters.get("network_mode")
            if (
                not isinstance(command_id, str)
                or not isinstance(command_hash, str)
                or raw_network_mode not in {"none", "approved-unrestricted"}
            ):
                raise FleetError(
                    ErrorCode.COMMAND_DENIED,
                    "command.run requires a TaskSpec command identity and hash.",
                    "Use the exact control-plane-provided verification command ID.",
                )
            execution_network_mode = cast(SandboxNetworkMode, raw_network_mode)
            resolved_command = _task_command(task, command_id, sandbox_handle.provider)
            if (
                resolved_command is None
                or canonical_json_hash(resolved_command.model_dump(mode="json")) != command_hash
                or run.sandbox_configuration is None
                or run.sandbox_configuration.network_mode != execution_network_mode
                or execution_network_mode not in sandbox_handle.capabilities.supported_network_modes
            ):
                raise FleetError(
                    ErrorCode.COMMAND_NOT_REVIEWED,
                    "The command is not exactly bound to the immutable TaskSpec.",
                    "Use one of the exact reviewed verification command IDs.",
                    details={"command_id": command_id},
                )
            command = resolved_command
        else:
            raise FleetError(
                ErrorCode.COMMAND_DENIED,
                f"Gateway action {intent.action!r} is not implemented.",
                "Use only the bounded registered tool surface.",
            )
        if command.network_requirement != "none":
            raise FleetError(
                ErrorCode.COMMAND_DENIED,
                "The reviewed command requires network access that Phase 3 has not approved.",
                "Use a network-free command or wait for exact network approval support.",
            )
        before_patch_sha = self._workspace_patch_sha(run, workspace)
        execution_id = self.ids.new(IdPrefix.EXECUTION)
        provider = self.sandboxes.get(sandbox_handle.provider)
        request = ExecRequest(
            execution_id=execution_id,
            intent_id=intent.intent_id,
            task_id=task.task_id,
            agent_instance_id=intent.agent_instance_id,
            stage=intent.stage,
            executable=command.executable,
            argv=list(command.argv),
            cwd=command.logical_cwd,
            environment=command.environment,
            timeout_seconds=command.timeout_seconds,
            max_output_bytes=command.max_output_bytes,
            network_mode=execution_network_mode,
            command_spec_hash=canonical_json_hash(command.model_dump(mode="json")),
        )
        now = self.clock.now()
        execution_lease = ResourceLease(
            lease_id=self.ids.new(IdPrefix.LEASE),
            run_id=run.run_id,
            kind=LeaseKind.EXECUTION,
            resource_id=execution_id,
            status=LeaseStatus.CREATING,
            created_at=now,
            updated_at=now,
            metadata={
                "schema_version": 2,
                "provider": provider.capabilities.provider,
                "intent_id": intent.intent_id,
                "project_id": run.project_id,
                "task_id": task.task_id,
                "agent_instance_id": intent.agent_instance_id,
                "stage": intent.stage.value,
                "creation_dispatched": False,
                "sandbox_handle": sandbox_handle.model_dump(mode="json"),
            },
        )
        self.state.save_lease(execution_lease)
        created_resource: SandboxExecutionHandle | None = None

        def record_creation_dispatch() -> None:
            nonlocal execution_lease
            execution_lease = self.state.mark_execution_creation_dispatched(
                execution_lease.lease_id
            )

        def bind_created_resource(resource: SandboxExecutionHandle) -> None:
            nonlocal created_resource
            if created_resource is not None or not execution_lease_binding_is_valid(
                execution_lease,
                resource,
                sandbox_handle,
            ):
                raise FleetError(
                    ErrorCode.SANDBOX_CREATION_FAILED,
                    "The sandbox returned an execution resource outside its full persisted "
                    "lease binding.",
                    "Treat the outcome as ambiguous and run Fleet recovery.",
                )
            created_resource = resource
            self.state.activate_lease(
                execution_lease.lease_id,
                {
                    "schema_version": 2,
                    "provider": provider.capabilities.provider,
                    "intent_id": intent.intent_id,
                    "project_id": run.project_id,
                    "task_id": task.task_id,
                    "agent_instance_id": intent.agent_instance_id,
                    "stage": intent.stage.value,
                    "creation_dispatched": True,
                    "sandbox_handle": sandbox_handle.model_dump(mode="json"),
                    "execution_handle": resource.model_dump(mode="json"),
                },
            )

        try:
            execution = await provider.exec(
                sandbox_handle,
                request,
                on_creation_dispatched=record_creation_dispatch,
                on_resource_created=bind_created_resource,
            )
            execution_metadata = execution.execution
            if execution_metadata is None or execution_metadata.inspection is None:
                raise FleetError(
                    ErrorCode.SANDBOX_INSPECTION_FAILED,
                    "The sandbox execution returned no structured effective inspection.",
                    "Recover the execution lease and retry with a conforming sandbox provider.",
                )
            inspection = execution_metadata.inspection
            capabilities_hash = canonical_json_hash(provider.capabilities.model_dump(mode="json"))
            if run.sandbox_requirements is None:
                raise FleetError(
                    ErrorCode.SANDBOX_INSPECTION_FAILED,
                    "The Run has no immutable sandbox requirement binding.",
                    "Recreate the Run from a validated project configuration.",
                )
            requirements_hash = canonical_json_hash(
                run.sandbox_requirements.model_dump(mode="json")
            )
            if (
                execution_metadata.execution_id != execution_id
                or execution_metadata.provider != provider.capabilities.provider
                or execution_metadata.configuration_hash != sandbox_handle.configuration_hash
                or execution_metadata.capabilities_hash != capabilities_hash
                or execution_metadata.inspection_hash
                != canonical_json_hash(inspection.model_dump(mode="json"))
                or inspection.sandbox_id != sandbox_handle.sandbox_id
                or inspection.provider != sandbox_handle.provider
                or not inspection.ready
                or inspection.capabilities != sandbox_handle.capabilities
                or inspection.configuration_hash != sandbox_handle.configuration_hash
                or inspection.image_identity != sandbox_handle.image_identity
                or inspection.image_identity != run.sandbox_image_identity
                or inspection.daemon_identity != sandbox_handle.daemon_identity
                or inspection.daemon_identity != run.sandbox_daemon_identity
                or inspection.effective_network_mode != execution_network_mode
                or inspection.missing_requirements(run.sandbox_requirements)
                or created_resource is None
                or execution_metadata.resource_handle != created_resource
                or not execution_metadata.cleanup_result.complete
            ):
                raise FleetError(
                    ErrorCode.SANDBOX_INSPECTION_FAILED,
                    "The sandbox execution metadata does not match its trusted Run binding.",
                    "Treat this command result as untrusted and recover the execution lease.",
                )
            if created_resource is None:
                raise RuntimeError("validated execution resource unexpectedly missing")
            terminal_metadata: dict[str, object] = {
                "schema_version": 3,
                "provider": provider.capabilities.provider,
                "intent_id": intent.intent_id,
                "project_id": run.project_id,
                "task_id": task.task_id,
                "agent_instance_id": intent.agent_instance_id,
                "stage": intent.stage.value,
                "creation_dispatched": True,
                "sandbox_handle": sandbox_handle.model_dump(mode="json"),
                "execution_handle": created_resource.model_dump(mode="json"),
                "execution_metadata_sha256": canonical_json_hash(
                    execution_metadata.model_dump(mode="json")
                ),
                "inspection_sha256": execution_metadata.inspection_hash,
                "cleanup_sha256": canonical_json_hash(
                    execution_metadata.cleanup_result.model_dump(mode="json")
                ),
                "inspection": inspection.model_dump(mode="json"),
                "cleanup_result": execution_metadata.cleanup_result.model_dump(mode="json"),
                "terminal_result": {
                    "exit_code": execution.exit_code,
                    "timed_out": execution.timed_out,
                    "output_truncated": execution.output_truncated,
                    "started_at": execution.started_at.isoformat(),
                    "completed_at": execution.completed_at.isoformat(),
                },
                "result_sha256": canonical_json_hash(
                    execution.model_dump(
                        mode="json",
                        exclude={"stdout", "stderr", "execution"},
                    )
                ),
            }
            self.state.finalize_lease(
                execution_lease.lease_id,
                LeaseStatus.RELEASED.value,
                terminal_metadata,
            )
        except BaseException as execution_error:
            await self._recover_failed_execution_lease(
                provider=provider,
                lease_id=execution_lease.lease_id,
                execution_error=execution_error,
            )
            raise
        inspection_artifact = self.artifacts.create_text(
            kind=ArtifactKind.SANDBOX_INSPECTION,
            project_id=run.project_id,
            run_id=run.run_id,
            task_id=task.task_id,
            producer=f"{provider.capabilities.provider}-sandbox",
            content=inspection.model_dump_json(indent=2),
            mime_type="application/json",
            metadata={
                "execution_id": execution_id,
                "canonical_sha256": execution_metadata.inspection_hash,
            },
        )
        after_patch_sha = self._workspace_patch_sha(run, workspace)
        workspace_mutated = before_patch_sha != after_patch_sha
        capabilities = provider.capabilities
        independently_verified = (
            capabilities.security_level is SandboxSecurityLevel.ISOLATED
            and capabilities.executes_code
            and intent.principal_role == "verifier"
            and intent.stage is WorkflowStage.VERIFYING
            and workspace.kind is WorkspaceKind.VERIFICATION
            and run.patch_sha256 is not None
            and before_patch_sha == run.patch_sha256
            and after_patch_sha == run.patch_sha256
            and not workspace_mutated
        )
        strength = (
            EvidenceStrength.SIMULATED
            if not capabilities.executes_code
            else EvidenceStrength.INDEPENDENTLY_VERIFIED
            if independently_verified
            else EvidenceStrength.OBSERVED
        )
        stdout, stdout_redactions = self.redactor.redact_text(execution.stdout)
        stderr, stderr_redactions = self.redactor.redact_text(execution.stderr)
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
                f"command_id={command.command_id}\n"
                f"command_spec_sha256={request.command_spec_hash}\n"
                f"executable={request.executable}\nargv={request.argv!r}\n"
                f"cwd={request.cwd}\nnetwork_mode={request.network_mode}\n"
                f"environment_names={sorted(request.environment)}\n"
                f"execution_id={execution_id}\n"
                f"sandbox_inspection_artifact_id={inspection_artifact.artifact_id}\n"
                f"exit_code={execution.exit_code}\ntimed_out={execution.timed_out}\n"
                f"output_truncated={execution.output_truncated}\n"
                f"workspace_mutated={str(workspace_mutated).lower()}\n"
                f"stdout:\n{stdout}\nstderr:\n{stderr}"
            ),
            metadata={
                "redaction_summary": cast(
                    JsonValue, sorted(set(stdout_redactions + stderr_redactions))
                )
            },
        )
        evidence_artifact_id = self.ids.new(IdPrefix.ARTIFACT)
        evidence = CommandEvidence(
            evidence_id=evidence_artifact_id,
            run_id=run.run_id,
            task_id=task.task_id,
            agent_instance_id=intent.agent_instance_id,
            principal_role=intent.principal_role,
            workflow_stage=intent.stage,
            workspace_id=workspace.workspace_id,
            sandbox_id=sandbox_handle.sandbox_id,
            command_id=command.command_id,
            command_spec_sha256=request.command_spec_hash,
            executable=request.executable,
            argv=request.argv,
            cwd=request.cwd,
            sandbox_provider=capabilities.provider,
            sandbox_security_level=capabilities.security_level,
            sandbox_capabilities_sha256=canonical_json_hash(capabilities.model_dump(mode="json")),
            sandbox_configuration_sha256=run.sandbox_configuration_hash,
            sandbox_requirements_sha256=requirements_hash,
            sandbox_image_identity=run.sandbox_image_identity,
            sandbox_daemon_identity=run.sandbox_daemon_identity,
            strength=strength,
            exit_code=execution.exit_code,
            timed_out=execution.timed_out,
            output_truncated=execution.output_truncated,
            transcript_artifact_id=transcript.artifact_id,
            workspace_base_revision=workspace.base_revision,
            config_snapshot_sha256=task.config_snapshot_hash,
            candidate_patch_sha256=after_patch_sha,
            workspace_kind=workspace.kind,
            network_mode=request.network_mode,
            workspace_mutated_during_execution=workspace_mutated,
            execution_id=execution_id,
            sandbox_inspection_artifact_id=inspection_artifact.artifact_id,
            sandbox_inspection_sha256=inspection_artifact.sha256,
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

    async def _recover_failed_execution_lease(
        self,
        *,
        provider: SandboxProvider,
        lease_id: str,
        execution_error: BaseException,
    ) -> None:
        lease = self.state.get_lease(lease_id)
        if lease.status in {LeaseStatus.RELEASED, LeaseStatus.RECOVERED}:
            return
        try:
            cleanup_proof: SandboxCleanupResult | None = None
            raw_cleanup_proof = getattr(
                execution_error,
                "_agent_fleet_cleanup_result",
                None,
            )
            if isinstance(raw_cleanup_proof, dict):
                try:
                    candidate_cleanup = SandboxCleanupResult.model_validate(raw_cleanup_proof)
                except ValueError:
                    candidate_cleanup = None
                if (
                    candidate_cleanup is not None
                    and candidate_cleanup.provider == provider.capabilities.provider
                    and candidate_cleanup.complete
                    and candidate_cleanup.reconciled
                ):
                    cleanup_proof = candidate_cleanup
            raw_cleanup_binding = getattr(
                execution_error,
                "_agent_fleet_cleanup_binding",
                None,
            )
            if lease.status is LeaseStatus.ACTIVE:
                raw_handle = lease.metadata.get("execution_handle")
                if not isinstance(raw_handle, dict):
                    raise FleetError(
                        ErrorCode.RECOVERY_REQUIRED,
                        "An active execution lease has no exact resource handle.",
                        "Inspect the lease manually; do not replay the command.",
                    )
                handle = SandboxExecutionHandle.model_validate(raw_handle)
                raw_sandbox = lease.metadata.get("sandbox_handle")
                if not isinstance(raw_sandbox, dict):
                    raise FleetError(
                        ErrorCode.RECOVERY_REQUIRED,
                        "An active execution lease has no parent sandbox identity.",
                        "Inspect the lease manually; do not replay the command.",
                    )
                sandbox = SandboxHandle.model_validate(raw_sandbox)
                if not execution_lease_binding_is_valid(lease, handle, sandbox):
                    raise FleetError(
                        ErrorCode.RECOVERY_REQUIRED,
                        "The active execution lease identity binding is invalid.",
                        "Inspect the lease manually; Fleet did not delete any resource.",
                    )
                cleanup_task = asyncio.create_task(provider.cleanup_execution(handle))
                cleanup = await _await_sandbox_cleanup_task(cleanup_task)
                if not cleanup.complete:
                    raise FleetError(
                        ErrorCode.SANDBOX_CLEANUP_FAILED,
                        "Sandbox execution cleanup could not prove the resource absent.",
                        "Inspect the persisted execution lease before continuing.",
                    )
            elif lease.status is LeaseStatus.CREATING:
                raw_sandbox = lease.metadata.get("sandbox_handle")
                if not isinstance(raw_sandbox, dict):
                    raise FleetError(
                        ErrorCode.RECOVERY_REQUIRED,
                        "A creating execution lease has no sandbox identity.",
                        "Inspect the lease manually; do not replay the command.",
                    )
                sandbox = SandboxHandle.model_validate(raw_sandbox)
                if not _cleanup_proof_binding_is_valid(
                    lease,
                    sandbox,
                    raw_cleanup_binding,
                ):
                    cleanup_proof = None
                if cleanup_proof is not None:
                    cleanup = cleanup_proof
                else:
                    cleanup_task = asyncio.create_task(
                        provider.reconcile_execution(
                            sandbox,
                            execution_recovery_request_from_lease(lease, sandbox),
                        )
                    )
                    cleanup = await _await_sandbox_cleanup_task(cleanup_task)
                if not cleanup.complete:
                    raise FleetError(
                        ErrorCode.SANDBOX_CLEANUP_FAILED,
                        "Creating execution reconciliation could not prove absence.",
                        "Inspect the persisted execution lease before continuing.",
                    )
            error_code = (
                execution_error.code.value if isinstance(execution_error, FleetError) else None
            )
            terminal_metadata: dict[str, object] = {
                **lease.metadata,
                "schema_version": 3,
                "recovery": {
                    "original_error_type": type(execution_error).__name__,
                    "original_error_code": error_code,
                    "cleanup_result": cleanup.model_dump(mode="json"),
                    "cleanup_sha256": canonical_json_hash(cleanup.model_dump(mode="json")),
                },
            }
            self.state.finalize_lease(
                lease_id,
                LeaseStatus.RECOVERED.value,
                terminal_metadata,
            )
        except BaseException as cleanup_error:
            current = self.state.get_lease(lease_id)
            if current.status not in {
                LeaseStatus.FAILED,
                LeaseStatus.RELEASED,
                LeaseStatus.RECOVERED,
            }:
                self.state.update_lease_status(lease_id, LeaseStatus.FAILED.value)
            if isinstance(cleanup_error, asyncio.CancelledError):
                raise
            raise FleetError(
                ErrorCode.SANDBOX_CLEANUP_FAILED,
                "Sandbox execution failed and exact cleanup could not be proven.",
                "Run Fleet recovery before starting another command.",
                details={"original_error_type": type(execution_error).__name__},
            ) from cleanup_error

    def _workspace_patch_sha(self, run: Run, workspace: Workspace) -> str | None:
        if self.repository is None:
            return run.patch_sha256
        return self.repository.compute_patch(workspace).sha256

    def _validate_context(
        self,
        run: Run,
        task: TaskSpec,
        agent: AgentInstance,
        workspace: Workspace,
        sandbox_handle: SandboxHandle,
    ) -> None:
        if (
            task.run_id != run.run_id
            or run.task_id != task.task_id
            or agent.run_id != run.run_id
            or agent.task_id != task.task_id
            or workspace.run_id != run.run_id
            or sandbox_handle.run_id != run.run_id
            or sandbox_handle.project_id != run.project_id
            or sandbox_handle.workspace_host_path != workspace.path
            or sandbox_handle.provider != run.sandbox_name
            or sandbox_handle.capabilities != run.sandbox_capabilities_snapshot
            or sandbox_handle.configuration_hash != run.sandbox_configuration_hash
            or sandbox_handle.image_identity != run.sandbox_image_identity
            or sandbox_handle.daemon_identity != run.sandbox_daemon_identity
        ):
            raise FleetError(
                ErrorCode.COMMAND_DENIED,
                "Trusted gateway identities or sandbox bindings do not match.",
                "Recover the Run from its persisted Project and TaskSpec bindings.",
            )
        active_leases = self.state.active_leases(run.run_id)
        if not any(
            lease.kind is LeaseKind.WORKTREE
            and lease.resource_id == workspace.workspace_id
            and lease.path == workspace.path
            for lease in active_leases
        ) or not any(
            lease.kind is LeaseKind.SANDBOX and lease.resource_id == sandbox_handle.sandbox_id
            for lease in active_leases
        ):
            raise FleetError(
                ErrorCode.RECOVERY_REQUIRED,
                "Trusted gateway workspace or sandbox has no active persisted lease.",
                "Recover the Run resources before executing another tool.",
            )
        if agent.role == "engineer" and workspace.kind is not WorkspaceKind.CANDIDATE:
            raise FleetError(
                ErrorCode.COMMAND_DENIED,
                "Engineer actions require the bound candidate workspace.",
                "Use the WorkflowEngine-managed Engineer context.",
            )
        if agent.role == "verifier" and workspace.kind is not WorkspaceKind.VERIFICATION:
            raise FleetError(
                ErrorCode.COMMAND_DENIED,
                "Verifier actions require a fresh verification workspace.",
                "Use the WorkflowEngine-managed Verifier context.",
            )

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
                "protected": decision.protected,
                "matched_rule_ids": decision.matched_rule_ids,
                "effective_scope": decision.effective_scope,
                "risk": decision.risk,
                "grant_id": decision.grant_id,
                "source_rule_id": decision.source_rule_id,
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


def _cleanup_proof_binding_is_valid(
    lease: ResourceLease,
    sandbox: SandboxHandle,
    raw_binding: object,
) -> bool:
    if sandbox.provider != "docker" or not isinstance(raw_binding, dict):
        return False
    intent_id = lease.metadata.get("intent_id")
    project_id = lease.metadata.get("project_id")
    task_id = lease.metadata.get("task_id")
    agent_instance_id = lease.metadata.get("agent_instance_id")
    stage = lease.metadata.get("stage")
    if (
        not all(
            isinstance(value, str)
            for value in (intent_id, project_id, task_id, agent_instance_id, stage)
        )
        or sandbox.project_id != project_id
        or sandbox.daemon_identity is None
        or sandbox.recovery_scope_id is None
    ):
        return False
    return raw_binding == {
        "agent-fleet.agent": agent_instance_id,
        "agent-fleet.daemon": sandbox.daemon_identity,
        "agent-fleet.execution": lease.resource_id,
        "agent-fleet.installation": sandbox.recovery_scope_id,
        "agent-fleet.intent": intent_id,
        "agent-fleet.managed": "true",
        "agent-fleet.project": project_id,
        "agent-fleet.run": lease.run_id,
        "agent-fleet.sandbox": sandbox.sandbox_id,
        "agent-fleet.stage": stage,
        "agent-fleet.task": task_id,
    }


async def _await_sandbox_cleanup_task(
    cleanup_task: asyncio.Task[SandboxCleanupResult],
) -> SandboxCleanupResult:
    """Finish bounded lease recovery despite repeated caller cancellation."""

    while not cleanup_task.done():
        try:
            await asyncio.wait({cleanup_task})
        except asyncio.CancelledError:
            continue
    return cleanup_task.result()


def _task_command(
    task: TaskSpec,
    command_id: str,
    sandbox_provider: str,
) -> CommandSpec | None:
    for command in task.verification_commands:
        if command.command_id == command_id:
            return command
    if (
        sandbox_provider == "fake"
        and not task.verification_commands
        and command_id == "offline-canary"
    ):
        return CommandSpec(
            command_id="offline-canary",
            executable="python",
            argv=("-m", "pytest", "-q"),
        )
    return None


def _path_in_task_scope(task: TaskSpec, logical_path: str) -> bool:
    return path_is_within(logical_path, task.allowed_paths, forbidden=task.forbidden_paths)
