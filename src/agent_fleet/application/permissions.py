"""Deterministic Phase 1.5 permission policy, independent of tool execution."""

from __future__ import annotations

from agent_fleet.domain.models import (
    CanonicalResource,
    PermissionDecision,
    PermissionOutcome,
    SandboxCapabilities,
    TaskSpec,
    ToolIntent,
    WorkflowStage,
)


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
            intent.action == "workspace.write_file"
            and intent.principal_role == "engineer"
            and intent.stage in {WorkflowStage.IMPLEMENTING, WorkflowStage.REPAIRING}
            and task.change_kind == "code_change"
            and intent.resource.kind == "workspace_path"
            and intent.resource.identifier in task.allowed_paths
            and intent.side_effect
        ):
            return PermissionDecision(
                outcome=PermissionOutcome.ALLOW,
                decision_code="PHASE1_CANDIDATE_WRITE",
                explanation="Bounded candidate workspace write is allowed.",
            )
        if (
            intent.action == "command.run"
            and intent.principal_role in {"engineer", "verifier"}
            and intent.resource.kind == "fake_command"
            and intent.resource.identifier == "verification://offline-canary"
            and intent.parameters.get("executable") == "python"
            and intent.parameters.get("argv") == ["-m", "pytest", "-q"]
            and intent.parameters.get("cwd") == "."
            and sandbox.provider == "fake"
            and not sandbox.executes_code
            and task.change_kind == "code_change"
            and not intent.side_effect
            and (
                (
                    intent.principal_role == "engineer"
                    and intent.stage in {WorkflowStage.IMPLEMENTING, WorkflowStage.REPAIRING}
                )
                or (intent.principal_role == "verifier" and intent.stage is WorkflowStage.VERIFYING)
            )
        ):
            return PermissionDecision(
                outcome=PermissionOutcome.ALLOW,
                decision_code="PHASE1_FAKE_COMMAND",
                explanation="Exact fake command recording is allowed as simulated evidence.",
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
