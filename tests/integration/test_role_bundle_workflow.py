"""Four bundles traverse new CoS proposals, explicit publication and rollback."""

from __future__ import annotations

from typing import Any, cast

import pytest
from conftest import FleetHarness

from agent_fleet.adapters.runtime.fake import FakeRuntimeAdapter
from agent_fleet.application.runtime import RuntimeRegistry
from agent_fleet.bootstrap import build_container, build_role_bundle_service
from agent_fleet.domain.evidence import EvidenceBundle
from agent_fleet.domain.fleet_plan import FleetPlan
from agent_fleet.domain.models import (
    AgentInvocation,
    AgentInvocationResult,
    AgentRole,
    FakeScenario,
    FleetPatch,
    RunStatus,
    ScopeDecision,
)
from agent_fleet.domain.role_bundles import RoleBundlePreview
from agent_fleet.ports.runtime import RuntimeInvocationServices

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


class BundleRuntime(FakeRuntimeAdapter):
    def __init__(self, preview: RoleBundlePreview) -> None:
        self.preview = preview
        self.roles: list[str] = []

    async def invoke(
        self, request: AgentInvocation, services: RuntimeInvocationServices
    ) -> AgentInvocationResult:
        self.roles.append(str(request.role))
        if request.role == AgentRole.COS and request.input["goal"] == self.preview.adoption_brief:
            context = cast(dict[str, Any], request.input["organization_context"])
            assert context["base_fleet_spec_sha256"] == self.preview.configuration_sha256
            if services.accounting is not None:
                services.accounting.record_simulated_step()
            return AgentInvocationResult(
                output=FleetPatch(
                    fleet_patch_id=context["proposal_id"],
                    project_id=context["project_id"],
                    base_fleet_spec_sha256=context["base_fleet_spec_sha256"],
                    rationale="Adopt the reviewed responsibilities and verification commands.",
                    changes=list(self.preview.changes),
                )
            )
        result = await super().invoke(request, services)
        if isinstance(result.output, ScopeDecision) and result.output.change_kind == "code_change":
            result.output.role_selections = {
                role.execution_kind: role.role_id for role in self.preview.bundle.roles
            }
        return result


@pytest.mark.parametrize(
    "bundle_id", ["general-change", "public-interface", "stateful-change", "design-guided"]
)
async def test_bundle_new_proposal_execution_and_rollback(
    harness: FleetHarness, bundle_id: str
) -> None:
    config = harness.container.workflow.config
    path = harness.repository_root / ".fleet/fleet.yaml"
    original_spec, original_snapshot = config.load_snapshot(path)
    preview = build_role_bundle_service(state_root=harness.state_root).preview(
        bundle_id,
        harness.repository_root,
        workflow_id="code-change",
        scopes=("src/canary_calc",),
        command_ids=("python-test",),
    )
    runtime = BundleRuntime(preview)
    harness.container.workflow.runtimes = RuntimeRegistry({"fake": runtime})
    proposal_run = await harness.container.workflow.start(
        project_path=harness.repository_root,
        goal=preview.adoption_brief,
        runtime_name="fake",
        sandbox_name="fake",
        fake_scenario=FakeScenario.DIRECT,
    )
    assert proposal_run.status is RunStatus.COMPLETED
    assert config.load_snapshot(path) == (original_spec, original_snapshot)
    proposal = harness.container.organization.list_proposals(harness.repository_root)[0]
    assert proposal.patch.changes == list(preview.changes)
    review, reviewed_proposal = harness.container.organization.review(
        proposal.patch.fleet_patch_id, action="apply"
    )
    assert reviewed_proposal == proposal
    published = harness.container.organization.apply(
        proposal.patch.fleet_patch_id, expected_review=review
    )
    assert published.status == "committed" and published.cleanup_complete
    reopened = build_container(harness.state_root)
    current_spec, current_snapshot = reopened.workflow.config.load_snapshot(path)
    assert current_spec == original_spec
    assert (
        reopened.workflow.config.snapshot_hash(current_snapshot)
        == preview.proposed_configuration_sha256
    )
    roles = reopened.workflow.config.role_templates(current_spec, current_snapshot)
    assert {role.role_id for role in preview.bundle.roles} <= roles.keys()
    for role in preview.bundle.roles:
        assert roles[role.role_id].allowed_paths == ("src/canary_calc",)
        assert "workspace.delete_path" not in roles[role.role_id].allowed_tools
        assert "fixture.record_side_effect" not in roles[role.role_id].allowed_tools
    runtime.roles.clear()
    reopened.workflow.runtimes = RuntimeRegistry({"fake": runtime})
    execution = await reopened.workflow.start(
        project_path=harness.repository_root,
        goal="Fix the bounded canary behavior with the adopted roles",
        runtime_name="fake",
        sandbox_name="fake",
        fake_scenario=FakeScenario.SPECIALIST
        if bundle_id == "design-guided"
        else FakeScenario.SUCCESS,
    )
    assert execution.status is RunStatus.READY_FOR_REVIEW
    assert not execution.verified_complete
    assert set(runtime.roles) == {"cos", *(role.role_id for role in preview.bundle.roles)}
    assert execution.fleet_plan_artifact_id and execution.evidence_bundle_artifact_id
    plan = FleetPlan.model_validate_json(
        reopened.artifacts.read_text(execution.fleet_plan_artifact_id)
    )
    assert {node.role_id for node in plan.nodes} >= {role.role_id for role in preview.bundle.roles}
    evidence = EvidenceBundle.model_validate_json(
        reopened.artifacts.read_text(execution.evidence_bundle_artifact_id)
    )
    assert {item.command_id for item in evidence.command_evidence} >= {"python-test"}
    assert not reopened.state.outstanding_leases(execution.run_id)
    rollback_review, _ = reopened.organization.review(
        proposal.patch.fleet_patch_id, action="rollback"
    )
    restored = reopened.organization.rollback(
        proposal.patch.fleet_patch_id, expected_review=rollback_review
    )
    assert restored.status == "committed" and restored.cleanup_complete
    assert config.load_snapshot(path) == (original_spec, original_snapshot)
    assert all(
        not (harness.repository_root / change.path).exists()
        for change in preview.changes
        if change.before_sha256 is None
    )
