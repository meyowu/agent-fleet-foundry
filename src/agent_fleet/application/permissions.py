"""Deterministic Phase 1.5 permission policy, independent of tool execution."""

from __future__ import annotations

from agent_fleet.domain.models import (
    CanonicalResource,
    CommandSpec,
    PermissionDecision,
    PermissionOutcome,
    SandboxCapabilities,
    SandboxSecurityLevel,
    TaskSpec,
    ToolIntent,
    WorkflowStage,
)
from agent_fleet.domain.paths import path_is_within
from agent_fleet.domain.security import canonical_json_hash


class BaselinePermissionBroker:
    """Narrow fail-closed policy for the offline Phase 1.5 vertical slice."""

    def evaluate(
        self,
        intent: ToolIntent,
        task: TaskSpec,
        sandbox: SandboxCapabilities,
    ) -> PermissionDecision:
        if (
            intent.run_id != task.run_id
            or intent.task_id != task.task_id
            or intent.workflow != task.workflow
        ):
            return self._default_deny()
        if (
            intent.action
            in {"workspace.write_file", "workspace.apply_edit", "workspace.delete_path"}
            and intent.principal_role == "engineer"
            and intent.stage in {WorkflowStage.IMPLEMENTING, WorkflowStage.REPAIRING}
            and task.change_kind == "code_change"
            and intent.resource.kind == "workspace_path"
            and _path_in_task_scope(task, intent.resource.identifier)
            and intent.side_effect
        ):
            parameters_valid = (
                (
                    intent.action == "workspace.write_file"
                    and set(intent.parameters) == {"content"}
                    and isinstance(intent.parameters.get("content"), str)
                )
                or (
                    intent.action == "workspace.apply_edit"
                    and set(intent.parameters)
                    == {"expected_sha256", "old", "new", "expected_matches"}
                    and _is_sha256(intent.parameters.get("expected_sha256"))
                    and isinstance(intent.parameters.get("old"), str)
                    and bool(intent.parameters.get("old"))
                    and isinstance(intent.parameters.get("new"), str)
                    and type(intent.parameters.get("expected_matches")) is int
                )
                or (
                    intent.action == "workspace.delete_path"
                    and set(intent.parameters) == {"expected_sha256"}
                    and _is_sha256(intent.parameters.get("expected_sha256"))
                )
            )
            if not parameters_valid:
                return self._default_deny()
            return PermissionDecision(
                outcome=PermissionOutcome.ALLOW,
                decision_code="PHASE3_BOUNDED_CANDIDATE_MUTATION",
                explanation="Bounded candidate workspace mutation is allowed.",
            )
        if (
            intent.action
            in {
                "repo.list_files",
                "repo.read_file",
                "repo.search_text",
                "workspace.get_diff",
            }
            and intent.principal_role in {"engineer", "verifier"}
            and _role_stage_allowed(intent.principal_role, intent.stage)
            and not intent.side_effect
        ):
            workspace_view = CanonicalResource(kind="workspace_view", identifier=".")
            if intent.action in {"repo.list_files", "workspace.get_diff"}:
                valid = intent.resource == workspace_view and not intent.parameters
            elif intent.action == "repo.search_text":
                query = intent.parameters.get("query")
                valid = (
                    intent.resource == workspace_view
                    and set(intent.parameters) == {"query"}
                    and isinstance(query, str)
                    and bool(query)
                )
            else:
                valid = (
                    intent.resource.kind == "workspace_path"
                    and not intent.parameters
                    and _path_in_task_scope(task, intent.resource.identifier)
                )
            if not valid:
                return self._default_deny()
            return PermissionDecision(
                outcome=PermissionOutcome.ALLOW,
                decision_code="PHASE3_BOUNDED_WORKSPACE_READ",
                explanation="Bounded workspace observation is allowed.",
            )
        if (
            intent.action == "command.run"
            and intent.principal_role in {"engineer", "verifier"}
            and intent.resource.kind == "project_command"
            and task.change_kind == "code_change"
            and intent.side_effect
            and (
                (
                    intent.principal_role == "engineer"
                    and intent.stage in {WorkflowStage.IMPLEMENTING, WorkflowStage.REPAIRING}
                )
                or (intent.principal_role == "verifier" and intent.stage is WorkflowStage.VERIFYING)
            )
        ):
            command = _task_command(task, intent.resource.identifier, sandbox.provider)
            if command is None:
                return self._default_deny()
            expected_parameters = {
                "command_id": command.command_id,
                "command_spec_sha256": canonical_json_hash(command.model_dump(mode="json")),
                "network_mode": intent.parameters.get("network_mode"),
            }
            network_mode = intent.parameters.get("network_mode")
            network_allowed = isinstance(network_mode, str) and (
                network_mode in sandbox.supported_network_modes
            )
            if network_mode != "none":
                network_allowed = (
                    network_mode == "approved-unrestricted"
                    and sandbox.security_level is SandboxSecurityLevel.UNSAFE_HOST
                    and sandbox.provider == "local-unsafe"
                )
            if (
                intent.parameters != expected_parameters
                or command.network_requirement != "none"
                or not network_allowed
            ):
                return self._default_deny()
            return PermissionDecision(
                outcome=PermissionOutcome.ALLOW,
                decision_code="PHASE3_EXACT_REVIEWED_COMMAND",
                explanation=(
                    "Exact TaskSpec-bound command is allowed through the selected sandbox."
                ),
            )
        if (
            intent.action == "fixture.record_side_effect"
            and intent.principal_role == "engineer"
            and intent.resource
            == CanonicalResource(kind="fake_side_effect", identifier="fixture://approval-proof")
            and intent.parameters == {"record": "approved-once"}
            and sandbox.provider == "fake"
            and not sandbox.executes_code
            and task.change_kind == "code_change"
            and intent.stage in {WorkflowStage.IMPLEMENTING, WorkflowStage.REPAIRING}
            and intent.side_effect
        ):
            return PermissionDecision(
                outcome=PermissionOutcome.REQUIRE_APPROVAL,
                decision_code="PHASE1_APPROVAL_PROOF",
                explanation="The scripted logical side effect requires a one-use user grant.",
            )
        return self._default_deny()

    @staticmethod
    def _default_deny() -> PermissionDecision:
        return PermissionDecision(
            outcome=PermissionOutcome.DENY,
            decision_code="PHASE1_DEFAULT_DENY",
            explanation=(
                "The action is outside the Phase 1.5 role, stage, resource, task, or "
                "sandbox boundary."
            ),
            protected=True,
        )


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


def _role_stage_allowed(role: str, stage: WorkflowStage) -> bool:
    return (
        role == "engineer" and stage in {WorkflowStage.IMPLEMENTING, WorkflowStage.REPAIRING}
    ) or (role == "verifier" and stage is WorkflowStage.VERIFYING)


def _path_in_task_scope(task: TaskSpec, logical_path: str) -> bool:
    return path_is_within(logical_path, task.allowed_paths, forbidden=task.forbidden_paths)


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )
