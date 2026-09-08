from __future__ import annotations

from datetime import UTC, datetime

import pytest
import yaml

from agent_fleet.adapters.config.yaml import YamlConfigurationAdapter
from agent_fleet.adapters.system import SystemClock, UuidIdGenerator
from agent_fleet.application.planning import FleetPlanner
from agent_fleet.domain.errors import FleetError
from agent_fleet.domain.fleet_plan import FleetPlan, FleetStrategy, validate_fleet_plan
from agent_fleet.domain.models import (
    AgentInstance,
    AgentRole,
    AgentStatus,
    Run,
    TaskSpec,
    WriterAssignment,
)
from agent_fleet.domain.role_templates import ResolvedRoleTemplate, validate_role_plan

NOW = datetime(2026, 9, 7, tzinfo=UTC)


def _inputs() -> tuple[Run, TaskSpec, dict[str, ResolvedRoleTemplate]]:
    adapter = YamlConfigurationAdapter()
    files = adapter.default_files("custom-roles")
    files["agents/roles.yaml"] = yaml.safe_dump(
        {
            "apiVersion": "agentfleet.dev/v1alpha1",
            "kind": "RoleCatalog",
            "roles": {
                name: {
                    "baseRole": kind,
                    "description": name,
                    "instructions": "agents/custom.md",
                    "maxSteps": 5,
                    "allowedPaths": ["src"],
                }
                for name, kind in {
                    "backend": "engineer",
                    "frontend": "engineer",
                    "security": "verifier",
                    "investigator": "researcher",
                    "designer": "architect",
                }.items()
            },
        }
    )
    files["agents/custom.md"] = "Keep responsibilities scoped and report remaining risks.\n"
    spec, snapshot = adapter.snapshot_from_files(files)
    roles = adapter.role_templates(spec, snapshot)
    run = Run(
        run_id="run_" + "1" * 32,
        project_id="prj_" + "2" * 32,
        correlation_id="corr_" + "3" * 32,
        goal="Fix bounded behavior",
        base_revision="base",
        target_status_fingerprint="a" * 64,
        created_at=NOW,
        updated_at=NOW,
    )
    task = TaskSpec(
        task_id="task_" + "4" * 32,
        run_id=run.run_id,
        original_goal=run.goal,
        normalized_goal=run.goal,
        base_revision=run.base_revision,
        allowed_paths=["src"],
        forbidden_paths=[".git", ".fleet"],
        acceptance_criteria=[{"criterion_id": "behavior", "description": "Tests pass"}],
        required_evidence=["canonical_patch", "command_evidence", "independent_verifier_verdict"],
        max_repair_iterations=1,
        config_snapshot_hash=adapter.snapshot_hash(snapshot),
        created_at=NOW,
    )
    return run, task, roles


def _plan(
    selections: dict[str, str],
    *,
    strategy: FleetStrategy = FleetStrategy.ENGINEER_VERIFIER,
) -> tuple[FleetPlan, TaskSpec, dict[str, ResolvedRoleTemplate]]:
    run, task, roles = _inputs()
    plan = FleetPlanner(SystemClock(), UuidIdGenerator()).create(
        run,
        task,
        strategy,
        known_roles=set(roles),
        role_templates=roles,
        role_selections=selections,
    )
    return plan, task, roles


def test_custom_writer_and_verifier_retain_distinct_principals() -> None:
    plan, task, roles = _plan({"engineer": "backend", "verifier": "security"})
    assert [(item.role_id, item.effective_kind) for item in plan.nodes] == [
        ("backend", AgentRole.ENGINEER),
        ("security", AgentRole.VERIFIER),
    ]
    assert all(item.max_steps == 5 for item in plan.nodes)
    assert plan.nodes[1].depends_on == [plan.nodes[0].node_id]
    assert plan.nodes[1].independent_verifier and not plan.nodes[1].can_write
    validate_fleet_plan(plan, task)
    validate_role_plan(plan, roles)
    assert FleetPlan.model_validate_json(plan.model_dump_json()) == plan


@pytest.mark.parametrize(
    "selections",
    [
        {"engineer": "undeclared"},
        {"engineer": "security"},
        {"verifier": "backend"},
        {"researcher": "investigator"},
        {"cos": "backend"},
    ],
)
def test_custom_selection_cannot_substitute_another_kind_or_unused_slot(
    selections: dict[str, str],
) -> None:
    with pytest.raises(FleetError):
        _plan(selections)


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_steps", 6),
        ("scope", ["tests"]),
        ("execution_kind", AgentRole.VERIFIER),
    ],
)
def test_forged_plan_binding_is_rejected_against_reviewed_template(
    field: str,
    value: object,
) -> None:
    plan, _, roles = _plan({"engineer": "backend"})
    altered = plan.model_copy(
        update={"nodes": [plan.nodes[0].model_copy(update={field: value}), plan.nodes[1]]}
    )
    with pytest.raises(FleetError):
        validate_role_plan(altered, roles)


def test_custom_specialist_chain_uses_kinds_for_order_not_principal_names() -> None:
    plan, task, roles = _plan(
        {
            "researcher": "investigator",
            "architect": "designer",
            "engineer": "backend",
            "verifier": "security",
        },
        strategy=FleetStrategy.RESEARCH_ARCHITECT_ENGINEER_VERIFIER,
    )
    assert [item.role_id for item in plan.nodes] == [
        "investigator",
        "designer",
        "backend",
        "security",
    ]
    assert [item.can_write for item in plan.nodes] == [False, False, True, False]
    validate_fleet_plan(plan, task)
    validate_role_plan(plan, roles)


def test_parallel_assignments_select_individual_writer_templates() -> None:
    run, task, roles = _inputs()
    assignments = [
        WriterAssignment(
            node_id=name, role_id=role, goal=name, scope=[f"src/{name}"], criterion_ids=["behavior"]
        )
        for name, role in [("api", "backend"), ("web", "frontend")]
    ]
    plan = FleetPlanner(SystemClock(), UuidIdGenerator()).create(
        run,
        task,
        FleetStrategy.PARALLEL_ENGINEERS,
        known_roles=set(roles),
        role_templates=roles,
        writer_assignments=assignments,
        role_selections={"verifier": "security", "engineer": "backend"},
    )
    assert [item.role_id for item in plan.nodes] == ["backend", "frontend", "security"]
    validate_role_plan(plan, roles)
    overlapping = assignments[1].model_copy(update={"scope": ["src/api/nested"]})
    with pytest.raises(FleetError, match="overlap"):
        FleetPlanner(SystemClock(), UuidIdGenerator()).create(
            run,
            task,
            FleetStrategy.PARALLEL_ENGINEERS,
            known_roles=set(roles),
            role_templates=roles,
            writer_assignments=[assignments[0], overlapping],
            role_selections={"engineer": "backend"},
        )


def test_parallel_repair_role_covers_parent_scope_before_any_dispatch() -> None:
    run, task, roles = _inputs()
    task = TaskSpec.model_validate({**task.model_dump(), "allowed_paths": ["src", "tests"]})
    assignments = [
        WriterAssignment(
            node_id=name, role_id=role, goal=name, scope=[f"src/{name}"], criterion_ids=["behavior"]
        )
        for name, role in [("api", "backend"), ("web", "frontend")]
    ]
    planner = FleetPlanner(SystemClock(), UuidIdGenerator())

    # Covering only the initial writer scopes is insufficient: joined repair
    # executes the parent task, which also permits tests. Reject before work starts.
    with pytest.raises(FleetError, match="parent repair scope"):
        planner.create(
            run,
            task,
            FleetStrategy.PARALLEL_ENGINEERS,
            known_roles=set(roles),
            role_templates=roles,
            writer_assignments=assignments,
            role_selections={"engineer": "backend"},
        )
    assert roles["backend"].allowed_paths == ("src",)

    # An explicitly selected compatible repair role works without widening the
    # custom writers or silently substituting their principal identities.
    plan = planner.create(
        run,
        task,
        FleetStrategy.PARALLEL_ENGINEERS,
        known_roles=set(roles),
        role_templates=roles,
        writer_assignments=assignments,
        role_selections={"engineer": "engineer"},
    )
    assert plan.repair_role_id == "engineer"
    assert [(node.role_id, node.scope) for node in plan.nodes if node.can_write] == [
        ("backend", ["src/api"]),
        ("frontend", ["src/web"]),
    ]
    assert plan.nodes[-1].scope == task.allowed_paths
    validate_role_plan(plan, roles)


def test_legacy_nodes_and_instances_do_not_serialize_new_optional_fields() -> None:
    plan, task, _ = _plan({})
    assert all("execution_kind" not in item.model_dump() for item in plan.nodes)
    assignment = WriterAssignment(
        node_id="writer", goal="Fix", scope=["src"], criterion_ids=["behavior"]
    )
    assert "role_id" not in assignment.model_dump()
    agent = AgentInstance(
        agent_instance_id="agent_" + "5" * 32,
        run_id=plan.run_id,
        task_id=task.task_id,
        role="engineer",
        status=AgentStatus.RUNNING,
        iteration=0,
        created_at=NOW,
    )
    assert "execution_kind" not in agent.model_dump()
    assert agent.effective_kind is AgentRole.ENGINEER
    for role, kind in [("backend", AgentRole.COS), ("engineer", AgentRole.VERIFIER)]:
        with pytest.raises(ValueError):
            AgentInstance.model_validate(
                {**agent.model_dump(), "role": role, "execution_kind": kind}
            )
