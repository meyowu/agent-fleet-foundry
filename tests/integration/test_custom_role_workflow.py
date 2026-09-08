"""Custom principals cross real planning, stores, gateway and evolution offline."""

from __future__ import annotations

from typing import Any, cast

import pytest
import yaml
from conftest import FleetHarness

from agent_fleet.adapters.runtime.fake import FakeRuntimeAdapter
from agent_fleet.application.runtime import RuntimeRegistry
from agent_fleet.bootstrap import build_container
from agent_fleet.domain.errors import FleetError
from agent_fleet.domain.evidence import EvidenceBundle
from agent_fleet.domain.fleet_plan import FleetPlan
from agent_fleet.domain.models import (
    AgentInvocation,
    AgentInvocationResult,
    AgentRole,
    ApprovalChoice,
    FakeScenario,
    FleetPatch,
    RunStatus,
    RuntimeToolCall,
    ScopeDecision,
)
from agent_fleet.domain.security import sha256_bytes
from agent_fleet.domain.trust import TrustMode
from agent_fleet.ports.runtime import RuntimeInvocationServices

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


class CustomRuntime(FakeRuntimeAdapter):
    def __init__(self, *, attack: bool = False) -> None:
        self.invocations: list[AgentInvocation] = []
        self.kinds: list[AgentRole | None] = []
        self.attack = attack

    async def invoke(
        self, request: AgentInvocation, services: RuntimeInvocationServices
    ) -> AgentInvocationResult:
        self.invocations.append(request)
        self.kinds.append(services.execution_kind)
        if request.role == "cos" and str(request.input["goal"]).startswith("Install roles"):
            context = cast(dict[str, Any], request.input["organization_context"])
            catalog = {
                "apiVersion": "agentfleet.dev/v1alpha1",
                "kind": "RoleCatalog",
                "roles": {
                    role: {
                        "baseRole": kind,
                        "description": f"Bounded {role} responsibility",
                        "instructions": "agents/custom.md",
                        "maxSteps": 8,
                        "allowedPaths": ["src/canary_calc"],
                    }
                    for role, kind in {
                        "backend": "engineer",
                        "metadata_writer": "engineer",
                        "security": "verifier",
                        "investigator": "researcher",
                        "designer": "architect",
                    }.items()
                },
            }
            files = {
                ".fleet/agents/roles.yaml": yaml.safe_dump(catalog),
                ".fleet/agents/custom.md": "Custom guidance: preserve transaction boundaries.\n",
            }
            return AgentInvocationResult(
                output=FleetPatch.model_validate(
                    {
                        "fleet_patch_id": context["proposal_id"],
                        "project_id": context["project_id"],
                        "base_fleet_spec_sha256": context["base_fleet_spec_sha256"],
                        "rationale": "Create bounded project-specific responsibilities.",
                        "changes": [
                            {
                                "operation": "add",
                                "path": path,
                                "before_sha256": None,
                                "after_sha256": sha256_bytes(body.encode()),
                                "content": body,
                            }
                            for path, body in files.items()
                        ],
                    }
                )
            )
        if self.attack and request.role == "investigator":
            await services.tools.execute(
                RuntimeToolCall(
                    call_id="forbidden-write",
                    name="workspace_write_file",
                    arguments={
                        "path": "src/canary_calc/core.py",
                        "content": "unsafe",
                        "reason": "This custom name must not confer write authority.",
                    },
                )
            )
        result = await super().invoke(request, services)
        if isinstance(result.output, ScopeDecision) and result.output.change_kind == "code_change":
            decision = result.output
            roles = {"engineer": "backend"}
            if decision.fleet_strategy != "single_engineer":
                roles["verifier"] = "security"
            if decision.fleet_strategy == "research_architect_engineer_verifier":
                roles.update(researcher="investigator", architect="designer")
            decision = decision.model_copy(
                update={
                    "role_selections": roles,
                    "writer_assignments": [
                        item.model_copy(
                            update={
                                "role_id": "backend"
                                if item.node_id == "core"
                                else "metadata_writer"
                            }
                        )
                        for item in decision.writer_assignments
                    ],
                }
            )
            return result.model_copy(update={"output": decision})
        return result


async def _install(harness: FleetHarness, *, attack: bool = False) -> tuple[CustomRuntime, str]:
    runtime = CustomRuntime(attack=attack)
    harness.container.workflow.runtimes = RuntimeRegistry({"fake": runtime})
    run = await harness.container.workflow.start(
        project_path=harness.repository_root,
        goal="Install roles for this project",
        runtime_name="fake",
        sandbox_name="fake",
        fake_scenario=FakeScenario.DIRECT,
    )
    assert run.status is RunStatus.COMPLETED
    proposal = harness.container.organization.list_proposals(harness.repository_root)[0]
    assert not (harness.repository_root / ".fleet/agents/roles.yaml").exists()
    applied = harness.container.organization.apply(proposal.patch.fleet_patch_id)
    assert applied.status == "committed" and applied.cleanup_complete
    return runtime, proposal.patch.fleet_patch_id


@pytest.mark.parametrize(
    "scenario",
    [
        FakeScenario.SUCCESS,
        FakeScenario.REPAIR,
        FakeScenario.SINGLE_ENGINEER,
        FakeScenario.PARALLEL_ENGINEERS,
        FakeScenario.SPECIALIST,
    ],
)
async def test_custom_roles_execute_and_produce_bound_evidence(
    harness: FleetHarness,
    scenario: FakeScenario,
) -> None:
    runtime, _ = await _install(harness)
    runtime.invocations.clear()
    runtime.kinds.clear()
    run = await harness.start(scenario)
    assert run.status is RunStatus.READY_FOR_REVIEW
    assert not run.verified_complete  # Fake execution never proves real code correctness.
    assert run.fleet_plan_artifact_id is not None and run.evidence_bundle_artifact_id is not None
    plan = FleetPlan.model_validate_json(
        harness.container.artifacts.read_text(run.fleet_plan_artifact_id)
    )
    expected = {"cos", "backend"}
    if scenario is not FakeScenario.SINGLE_ENGINEER:
        expected.add("security")
    if scenario is FakeScenario.PARALLEL_ENGINEERS:
        expected.add("metadata_writer")
        assert plan.repair_role_id == "backend"
    if scenario is FakeScenario.SPECIALIST:
        expected.update({"investigator", "designer"})
    assert {item.role for item in runtime.invocations} == expected
    for request, kind in zip(runtime.invocations, runtime.kinds, strict=True):
        if request.role == "cos":
            assert expected - {"cos"} <= set(cast(list[str], request.input["available_roles"]))
            continue
        agent = harness.container.state.get_agent_instance(request.agent_instance_id)
        assert agent.role == request.role and agent.effective_kind is kind
        assert request.max_steps <= 8
        assert "Custom guidance: preserve transaction boundaries." in (request.instructions or "")
    if scenario is FakeScenario.REPAIR:
        assert run.repair_iterations == 1
        assert [item.role for item in runtime.invocations].count("backend") == 2
        assert [item.role for item in runtime.invocations].count("security") == 2
    bundle = EvidenceBundle.model_validate_json(
        harness.container.artifacts.read_text(run.evidence_bundle_artifact_id)
    )
    if scenario is not FakeScenario.SINGLE_ENGINEER:
        assert bundle.verifier_role == "security"
        assert run.verifier_agent_instance_id is not None
        verifier_commands = [
            item
            for item in bundle.command_evidence
            if item.agent_instance_id == run.verifier_agent_instance_id
        ]
        assert verifier_commands and all(
            item.principal_role == "security" for item in verifier_commands
        )
    assert all(item.execution_kind is not None for item in plan.nodes)
    all_ids = [
        run.run_id,
        *(item.child_run_id for item in harness.container.graphs.descendants(run.run_id)),
    ]
    assert not any(harness.container.state.outstanding_leases(item) for item in all_ids)
    assert build_container(harness.state_root).inspection.status(run.run_id)["run_id"] == run.run_id


async def test_custom_approval_keeps_exact_principal_across_restart(harness: FleetHarness) -> None:
    runtime, _ = await _install(harness)
    harness.container.permissions.configure(
        harness.repository_root, mode=TrustMode.SAFE, allowed_paths=(".",)
    )
    run = await harness.start()
    roles: list[str] = []
    for _ in range(4):
        assert run.status is RunStatus.PAUSED_FOR_APPROVAL and run.pending_approval_id is not None
        container = build_container(harness.state_root)
        container.workflow.runtimes = RuntimeRegistry({"fake": runtime})
        approval = container.state.get_approval(run.pending_approval_id)
        roles.append(approval.principal_role)
        assert approval.authorization_scope is not None
        assert approval.authorization_scope["principal_role"] == approval.principal_role
        container.approvals.approve(approval.request_id, choice=ApprovalChoice.ALLOW_ONCE)
        run = await container.workflow.resume(run.run_id)
    assert roles == ["backend", "backend", "security", "security"]
    assert run.status is RunStatus.READY_FOR_REVIEW


async def test_read_only_custom_role_cannot_gain_writer_tools(harness: FleetHarness) -> None:
    runtime, _ = await _install(harness, attack=True)
    with pytest.raises(FleetError):
        await harness.start(FakeScenario.SPECIALIST)
    assert "investigator" in {item.role for item in runtime.invocations}
    assert "backend" not in {item.role for item in runtime.invocations}
    assert harness.git("diff", "--", "src/canary_calc/core.py") == ""


async def test_catalog_evolves_and_rolls_back_with_exact_snapshot_hash(
    harness: FleetHarness,
) -> None:
    project = harness.container.state.get_project_by_root(str(harness.repository_root))
    assert project is not None
    old_hash = project.fleet_spec_hash
    _, proposal_id = await _install(harness)
    reopened = build_container(harness.state_root)
    active = reopened.state.get_project(project.project_id)
    assert active.fleet_spec_hash != old_hash
    spec, snapshot = reopened.workflow.config.load_snapshot(
        harness.repository_root / ".fleet/fleet.yaml"
    )
    assert "backend" in reopened.workflow.config.role_templates(spec, snapshot)
    result = reopened.organization.rollback(proposal_id)
    assert result.status == "committed" and result.changed
    restored = reopened.state.get_project(project.project_id)
    assert restored.fleet_spec_hash == old_hash
    assert not (harness.repository_root / ".fleet/agents/roles.yaml").exists()
    head = reopened.organization.store.get_head(project.project_id)
    assert head is not None and head.revision == 2
