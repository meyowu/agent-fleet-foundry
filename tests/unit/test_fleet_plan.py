from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from agent_fleet.adapters.system import SystemClock, UuidIdGenerator
from agent_fleet.application.planning import FleetPlanner
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.fleet_plan import (
    FleetPlan,
    FleetPlanNode,
    FleetStrategy,
    validate_fleet_plan,
)
from agent_fleet.domain.models import AcceptanceCriterion, Run, TaskSpec, WriterAssignment

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
RUN_ID = "run_11111111111111111111111111111111"
TASK_ID = "task_22222222222222222222222222222222"
PLAN_ID = "plan_33333333333333333333333333333333"
CONFIG_HASH = "a" * 64
CODE_CHANGE_EVIDENCE = [
    "canonical_patch",
    "command_evidence",
    "independent_verifier_verdict",
]


def _task(
    *,
    change_kind: str = "code_change",
    allowed_paths: list[str] | None = None,
    required_evidence: list[str] | None = None,
) -> TaskSpec:
    return TaskSpec(
        task_id=TASK_ID,
        run_id=RUN_ID,
        original_goal="Make the requested bounded change.",
        normalized_goal="Make the requested bounded change.",
        workflow="code-change",
        change_kind=change_kind,
        base_revision="base-revision",
        allowed_paths=allowed_paths or ["src/canary_calc/core.py"],
        forbidden_paths=[".git", ".fleet"],
        acceptance_criteria=[
            AcceptanceCriterion(
                criterion_id="canary-behavior",
                description="The canary has the requested behavior.",
            )
        ],
        required_evidence=required_evidence or CODE_CHANGE_EVIDENCE,
        max_repair_iterations=1,
        config_snapshot_hash=CONFIG_HASH,
        created_at=NOW,
    )


def _plan(
    *,
    strategy: FleetStrategy,
    nodes: list[FleetPlanNode],
    required_evidence: list[str] | None = None,
) -> FleetPlan:
    return FleetPlan(
        plan_id=PLAN_ID,
        run_id=RUN_ID,
        task_id=TASK_ID,
        strategy=strategy,
        nodes=nodes,
        max_parallel_agents=max(1, sum(node.can_write for node in nodes)),
        required_evidence=required_evidence or CODE_CHANGE_EVIDENCE,
        rationale="Use the smallest topology that satisfies the task.",
        created_at=NOW,
    )


def _engineer(*, node_id: str = "engineer", scope: list[str] | None = None) -> FleetPlanNode:
    return FleetPlanNode(
        node_id=node_id,
        role_id="engineer",
        scope=scope if scope is not None else ["src/canary_calc/core.py"],
        can_write=True,
        requires_workspace=True,
    )


def _verifier(
    *,
    depends_on: list[str] | None = None,
    scope: list[str] | None = None,
    requires_workspace: bool = True,
) -> FleetPlanNode:
    return FleetPlanNode(
        node_id="verifier",
        role_id="verifier",
        depends_on=depends_on or ["engineer"],
        scope=scope or ["src/canary_calc/core.py"],
        requires_workspace=requires_workspace,
        independent_verifier=True,
    )


def test_valid_direct_plan_for_read_only_task() -> None:
    evidence = ["control_plane_plan"]
    plan = _plan(
        strategy=FleetStrategy.DIRECT,
        nodes=[],
        required_evidence=evidence,
    )

    validate_fleet_plan(
        plan,
        _task(change_kind="read_only", required_evidence=evidence),
    )


def test_valid_single_engineer_plan() -> None:
    evidence = ["canonical patch", "command evidence"]
    plan = _plan(
        strategy=FleetStrategy.SINGLE_ENGINEER,
        nodes=[_engineer()],
        required_evidence=evidence,
    )

    validate_fleet_plan(plan, _task(required_evidence=evidence))


def test_single_engineer_cannot_satisfy_independent_verification() -> None:
    plan = _plan(strategy=FleetStrategy.SINGLE_ENGINEER, nodes=[_engineer()])

    with pytest.raises(FleetError, match="requires independent verification"):
        validate_fleet_plan(plan, _task())


def test_single_engineer_strategy_rejects_a_cos_writer() -> None:
    evidence = ["canonical patch", "command evidence"]
    plan = _plan(
        strategy=FleetStrategy.SINGLE_ENGINEER,
        nodes=[_engineer().model_copy(update={"role_id": "cos"})],
        required_evidence=evidence,
    )

    with pytest.raises(FleetError, match="exactly one Engineer writer"):
        validate_fleet_plan(plan, _task(required_evidence=evidence))


def test_valid_engineer_verifier_pair() -> None:
    plan = _plan(
        strategy=FleetStrategy.ENGINEER_VERIFIER,
        nodes=[_engineer(), _verifier()],
    )

    validate_fleet_plan(plan, _task())


def test_legacy_phase1_evidence_label_normalizes_to_canonical_id() -> None:
    task = _task(
        required_evidence=[
            "canonical patch",
            "command evidence",
            "independent verification",
        ]
    )

    assert task.required_evidence == CODE_CHANGE_EVIDENCE


@pytest.mark.parametrize(
    "nodes",
    [
        [_engineer().model_copy(update={"role_id": "cos"}), _verifier()],
        [_engineer(), _verifier().model_copy(update={"role_id": "researcher"})],
    ],
    ids=["wrong-writer-role", "wrong-verifier-role"],
)
def test_engineer_verifier_strategy_rejects_wrong_roles(
    nodes: list[FleetPlanNode],
) -> None:
    plan = _plan(strategy=FleetStrategy.ENGINEER_VERIFIER, nodes=nodes)

    with pytest.raises(FleetError, match="roles must be Engineer and Verifier"):
        validate_fleet_plan(plan, _task())


def test_cycle_is_rejected_when_plan_is_constructed() -> None:
    with pytest.raises(ValidationError, match="dependency graph contains a cycle"):
        _plan(
            strategy=FleetStrategy.RESEARCH_ARCHITECT_ENGINEER_VERIFIER,
            nodes=[
                FleetPlanNode(
                    node_id="researcher",
                    role_id="researcher",
                    depends_on=["architect"],
                ),
                FleetPlanNode(
                    node_id="architect",
                    role_id="architect",
                    depends_on=["researcher"],
                ),
            ],
        )


def test_missing_dependency_is_rejected_when_plan_is_constructed() -> None:
    with pytest.raises(ValidationError, match="missing dependencies"):
        _plan(
            strategy=FleetStrategy.ENGINEER_VERIFIER,
            nodes=[_engineer(), _verifier(depends_on=["missing-writer"])],
        )


def test_overlapping_writer_scopes_are_rejected() -> None:
    evidence = ["canonical patch", "command evidence"]
    plan = _plan(
        strategy=FleetStrategy.PARALLEL_ENGINEERS,
        nodes=[
            _engineer(node_id="backend", scope=["src"]),
            _engineer(node_id="api", scope=["src/api/service.py"]),
        ],
        required_evidence=evidence,
    )

    with pytest.raises(FleetError) as captured:
        validate_fleet_plan(
            plan,
            _task(
                allowed_paths=["src", "src/api/service.py"],
                required_evidence=evidence,
            ),
        )

    assert captured.value.code is ErrorCode.CONFIG_INVALID
    assert "Writer scopes overlap" in captured.value.message


def test_casefolded_overlapping_writer_scopes_are_rejected() -> None:
    evidence = ["canonical patch", "command evidence"]
    plan = _plan(
        strategy=FleetStrategy.PARALLEL_ENGINEERS,
        nodes=[
            _engineer(node_id="backend", scope=["SRC"]),
            _engineer(node_id="api", scope=["src/api"]),
        ],
        required_evidence=evidence,
    )

    with pytest.raises(FleetError, match="Writer scopes overlap"):
        validate_fleet_plan(
            plan,
            _task(
                allowed_paths=["SRC", "src/api"],
                required_evidence=evidence,
            ),
        )


def test_plan_scope_is_canonical_and_case_insensitively_unique() -> None:
    with pytest.raises(ValidationError, match="case-insensitively unique"):
        FleetPlanNode(
            node_id="engineer",
            role_id="engineer",
            scope=["SRC/file.py", "src/file.py"],
            can_write=True,
            requires_workspace=True,
        )
    with pytest.raises(ValidationError, match="invalid repository-relative"):
        FleetPlanNode(
            node_id="engineer",
            role_id="engineer",
            scope=["src/./file.py"],
            can_write=True,
            requires_workspace=True,
        )


def test_direct_plan_cannot_claim_a_code_change() -> None:
    evidence = ["canonical_patch", "command_evidence", "control_plane_plan"]
    plan = _plan(
        strategy=FleetStrategy.DIRECT,
        nodes=[],
        required_evidence=evidence,
    )

    with pytest.raises(FleetError) as captured:
        validate_fleet_plan(
            plan,
            _task(change_kind="code_change", required_evidence=evidence),
        )

    assert captured.value.code is ErrorCode.CONFIG_INVALID
    assert "Direct plans are limited to read-only tasks" in captured.value.message


def test_direct_plan_cannot_claim_independent_verification() -> None:
    plan = _plan(strategy=FleetStrategy.DIRECT, nodes=[])

    with pytest.raises(FleetError, match="requires independent verification"):
        validate_fleet_plan(plan, _task(change_kind="read_only"))


def test_plan_cannot_add_or_remove_task_evidence_requirements() -> None:
    task_evidence = ["canonical_patch", "command_evidence"]
    plan = _plan(
        strategy=FleetStrategy.SINGLE_ENGINEER,
        nodes=[_engineer()],
        required_evidence=[*task_evidence, "independent_verifier_verdict"],
    )

    with pytest.raises(FleetError, match="must exactly match"):
        validate_fleet_plan(plan, _task(required_evidence=task_evidence))


def test_noncanonical_evidence_requirement_alias_is_rejected() -> None:
    with pytest.raises(ValidationError, match="literal_error"):
        _plan(
            strategy=FleetStrategy.SINGLE_ENGINEER,
            nodes=[_engineer()],
            required_evidence=["independent-verifier verdict"],
        )


def test_writer_scope_cannot_exceed_task_scope() -> None:
    evidence = ["canonical patch", "command evidence"]
    plan = _plan(
        strategy=FleetStrategy.SINGLE_ENGINEER,
        nodes=[_engineer(scope=["src/other.py"])],
        required_evidence=evidence,
    )
    with pytest.raises(FleetError, match="outside the TaskSpec allow-list"):
        validate_fleet_plan(plan, _task(required_evidence=evidence))


@pytest.mark.parametrize(
    "verifier",
    [
        _verifier(scope=[".git/config"]),
        _verifier(requires_workspace=False),
    ],
    ids=["protected-scope", "no-workspace"],
)
def test_parallel_verifier_requires_bounded_workspace_scope(
    verifier: FleetPlanNode,
) -> None:
    plan = _plan(
        strategy=FleetStrategy.PARALLEL_ENGINEERS,
        nodes=[
            _engineer(node_id="backend", scope=["src/backend.py"]),
            _engineer(node_id="frontend", scope=["src/frontend.py"]),
            verifier.model_copy(update={"depends_on": ["backend", "frontend"]}),
        ],
    )

    with pytest.raises(FleetError, match=r"Verifier|independent Verifier"):
        validate_fleet_plan(
            plan,
            _task(allowed_paths=["src/backend.py", "src/frontend.py"]),
        )


def test_plan_cannot_reference_an_undeclared_role() -> None:
    plan = _plan(
        strategy=FleetStrategy.SINGLE_ENGINEER,
        nodes=[
            FleetPlanNode(
                node_id="contractor",
                role_id="contractor",
                scope=["src/canary_calc/core.py"],
                can_write=True,
                requires_workspace=True,
            )
        ],
    )
    with pytest.raises(FleetError, match="undeclared roles"):
        validate_fleet_plan(plan, _task(), known_roles={"cos", "engineer", "verifier"})


def test_valid_parallel_plan_requires_disjoint_scopes_and_capacity() -> None:
    evidence = ["canonical patch", "command evidence"]
    plan = _plan(
        strategy=FleetStrategy.PARALLEL_ENGINEERS,
        nodes=[
            _engineer(node_id="backend", scope=["src/backend.py"]),
            _engineer(node_id="frontend", scope=["src/frontend.py"]),
        ],
        required_evidence=evidence,
    )
    validate_fleet_plan(
        plan,
        _task(
            allowed_paths=["src/backend.py", "src/frontend.py"],
            required_evidence=evidence,
        ),
    )


@pytest.mark.parametrize(
    "extra_node",
    [
        FleetPlanNode(
            node_id="passive",
            role_id="verifier",
            scope=["src/backend.py"],
            requires_workspace=True,
        ),
        _engineer(node_id="serial", scope=["src/serial.py"]).model_copy(
            update={"depends_on": ["backend"]}
        ),
    ],
    ids=["non-independent-verifier", "dependent-writer"],
)
def test_parallel_plan_rejects_false_parallel_topology(extra_node: FleetPlanNode) -> None:
    evidence = ["canonical_patch", "command_evidence"]
    nodes = [
        _engineer(node_id="backend", scope=["src/backend.py"]),
        _engineer(node_id="frontend", scope=["src/frontend.py"]),
        extra_node,
    ]
    plan = _plan(
        strategy=FleetStrategy.PARALLEL_ENGINEERS,
        nodes=nodes,
        required_evidence=evidence,
    )

    with pytest.raises(FleetError):
        validate_fleet_plan(
            plan,
            _task(
                allowed_paths=["src/backend.py", "src/frontend.py", "src/serial.py"],
                required_evidence=evidence,
            ),
        )


def test_plan_collections_are_bounded_and_unique() -> None:
    with pytest.raises(ValidationError, match="dependencies must be unique"):
        FleetPlanNode(
            node_id="engineer",
            role_id="engineer",
            depends_on=["same", "same"],
        )


@pytest.mark.parametrize(
    ("field", "invalid_id"),
    [
        ("plan_id", "run_" + "1" * 32),
        ("run_id", "art_" + "2" * 32),
        ("task_id", "prj_" + "3" * 32),
    ],
)
def test_fleet_plan_ids_require_dedicated_prefixes(field: str, invalid_id: str) -> None:
    values = _plan(
        strategy=FleetStrategy.ENGINEER_VERIFIER,
        nodes=[_engineer(), _verifier()],
    ).model_dump(mode="json")
    values[field] = invalid_id

    with pytest.raises(ValidationError, match="string_pattern_mismatch"):
        FleetPlan.model_validate(values)

    with pytest.raises(ValidationError, match="scope entries must be case-insensitively unique"):
        FleetPlanNode(
            node_id="engineer",
            role_id="engineer",
            scope=["src/core.py", "src/core.py"],
        )

    with pytest.raises(ValidationError, match="too_long"):
        _plan(
            strategy=FleetStrategy.PARALLEL_ENGINEERS,
            nodes=[
                FleetPlanNode(node_id=f"node-{index}", role_id="engineer") for index in range(17)
            ],
        )


def test_valid_specialist_chain_is_representable() -> None:
    plan = _plan(
        strategy=FleetStrategy.RESEARCH_ARCHITECT_ENGINEER_VERIFIER,
        nodes=[
            FleetPlanNode(
                node_id="researcher",
                role_id="researcher",
                scope=["src/canary_calc/core.py"],
                requires_workspace=True,
            ),
            FleetPlanNode(
                node_id="architect",
                role_id="architect",
                depends_on=["researcher"],
                scope=["src/canary_calc/core.py"],
                requires_workspace=True,
            ),
            FleetPlanNode(
                node_id="engineer",
                role_id="engineer",
                depends_on=["architect"],
                scope=["src/canary_calc/core.py"],
                can_write=True,
                requires_workspace=True,
            ),
            FleetPlanNode(
                node_id="verifier",
                role_id="verifier",
                depends_on=["engineer"],
                scope=["src/canary_calc/core.py"],
                requires_workspace=True,
                independent_verifier=True,
            ),
        ],
    )
    validate_fleet_plan(plan, _task())


def _planner_run() -> Run:
    return Run(
        run_id=RUN_ID,
        project_id="prj_" + "4" * 32,
        correlation_id="corr_" + "5" * 32,
        goal="Bounded graph task",
        base_revision="base-revision",
        target_status_fingerprint="6" * 64,
        task_id=TASK_ID,
        created_at=NOW,
        updated_at=NOW,
    )


def _assignments(count: int = 3) -> list[WriterAssignment]:
    return [
        WriterAssignment(
            node_id=f"writer-{index}",
            goal=f"Implement scoped component {index}.",
            scope=[f"src/component_{index}.py"],
            criterion_ids=["canary-behavior"],
        )
        for index in range(count)
    ]


def test_planner_queues_more_writers_than_capacity_in_stable_order() -> None:
    plan = FleetPlanner(SystemClock(), UuidIdGenerator()).create(
        _planner_run(),
        _task(allowed_paths=["src"]),
        FleetStrategy.PARALLEL_ENGINEERS,
        known_roles={"engineer", "verifier"},
        writer_assignments=list(reversed(_assignments())),
        max_parallel_agents=5,
        configured_max_parallel_agents=2,
        role_max_steps={"engineer": 4, "verifier": 3},
    )
    assert plan.max_parallel_agents == 2
    assert [node.node_id for node in plan.nodes] == ["writer-0", "writer-1", "writer-2", "verifier"]
    assert [node.max_steps for node in plan.nodes] == [4, 4, 4, 3]
    assert plan.nodes[-1].depends_on == ["writer-0", "writer-1", "writer-2"]
    assert plan.nodes[-1].scope == ["src"]
    assert all(node.criterion_ids == ["canary-behavior"] for node in plan.nodes)
    assert all(node.goal for node in plan.nodes)
    assert plan.nodes[-1].independent_verifier


@pytest.mark.parametrize(
    ("requested", "configured", "expected"), [(2, 8, 2), (8, 3, 3), (99, 99, 8)]
)
def test_planner_capacity_is_intersection(requested: int, configured: int, expected: int) -> None:
    plan = FleetPlanner(SystemClock(), UuidIdGenerator()).create(
        _planner_run(),
        _task(allowed_paths=["src"]),
        FleetStrategy.PARALLEL_ENGINEERS,
        known_roles={"engineer", "verifier"},
        writer_assignments=_assignments(),
        max_parallel_agents=requested,
        configured_max_parallel_agents=configured,
    )
    assert plan.max_parallel_agents == expected


@pytest.mark.parametrize(
    "variant",
    [
        "one",
        "too-many",
        "duplicate",
        "verifier",
        "foreign",
        "missing",
        "overlap",
        "casefold",
        "outside",
        "forbidden",
        "capacity",
        "no-verifier",
    ],
)
def test_planner_rejects_invalid_parallel_proposals(variant: str) -> None:
    assignments = _assignments()
    task = _task(allowed_paths=["src"])
    capacity = 2
    if variant == "one":
        assignments = assignments[:1]
    elif variant == "too-many":
        assignments = _assignments(9)
    elif variant == "duplicate":
        assignments[1] = assignments[0]
    elif variant == "verifier":
        assignments[0] = assignments[0].model_copy(update={"node_id": "verifier"})
    elif variant == "foreign":
        assignments[0] = assignments[0].model_copy(update={"criterion_ids": ["unknown"]})
    elif variant == "missing":
        task = task.model_copy(
            update={
                "acceptance_criteria": [
                    *task.acceptance_criteria,
                    AcceptanceCriterion(
                        criterion_id="second", description="A second original criterion."
                    ),
                ]
            }
        )
    elif variant in {"overlap", "casefold", "outside", "forbidden"}:
        scope = {
            "overlap": ["src"],
            "casefold": ["SRC/component_1.py"],
            "outside": ["other.py"],
            "forbidden": [".fleet/config"],
        }[variant]
        assignments[0] = assignments[0].model_copy(update={"scope": scope})
    elif variant == "capacity":
        capacity = 1
    elif variant == "no-verifier":
        task = task.model_copy(
            update={"required_evidence": ["canonical_patch", "command_evidence"]}
        )
    with pytest.raises(FleetError) as caught:
        FleetPlanner(SystemClock(), UuidIdGenerator()).create(
            _planner_run(),
            task,
            FleetStrategy.PARALLEL_ENGINEERS,
            known_roles={"engineer", "verifier"},
            writer_assignments=assignments,
            configured_max_parallel_agents=capacity,
        )
    assert caught.value.code is ErrorCode.CONFIG_INVALID


def test_planner_specialists_are_read_only_full_scope_and_serial() -> None:
    plan = FleetPlanner(SystemClock(), UuidIdGenerator()).create(
        _planner_run(),
        _task(),
        FleetStrategy.RESEARCH_ARCHITECT_ENGINEER_VERIFIER,
        known_roles={"engineer", "verifier", "researcher", "architect"},
        role_max_steps={"researcher": 3, "architect": 4, "engineer": 99, "verifier": 99},
    )
    assert plan.max_parallel_agents == 1
    assert [node.role_id for node in plan.nodes] == [
        "researcher",
        "architect",
        "engineer",
        "verifier",
    ]
    assert [node.depends_on for node in plan.nodes] == [
        [],
        ["researcher"],
        ["architect"],
        ["engineer"],
    ]
    assert [node.max_steps for node in plan.nodes] == [3, 4, 20, 10]
    assert [node.can_write for node in plan.nodes] == [False, False, True, False]
    assert all(
        node.requires_workspace and node.scope == _task().allowed_paths for node in plan.nodes
    )
    with pytest.raises(FleetError, match="undeclared roles"):
        validate_fleet_plan(plan, _task(), known_roles={"engineer", "verifier"})


def test_specialist_chain_has_exactly_one_independent_verifier() -> None:
    researcher = FleetPlanNode(
        node_id="researcher",
        role_id="researcher",
        scope=["src/canary_calc/core.py"],
        requires_workspace=True,
        independent_verifier=True,
    )
    plan = _plan(
        strategy=FleetStrategy.RESEARCH_ARCHITECT_ENGINEER_VERIFIER,
        nodes=[
            researcher,
            FleetPlanNode(
                node_id="architect",
                role_id="architect",
                depends_on=["researcher"],
            ),
            _engineer().model_copy(update={"depends_on": ["architect"]}),
            _verifier(),
        ],
    )

    with pytest.raises(FleetError, match="dependency and authority chain"):
        validate_fleet_plan(plan, _task())


def test_direct_plan_requires_exact_control_plane_evidence() -> None:
    evidence = ["control_plane_plan", "command_evidence"]
    plan = _plan(
        strategy=FleetStrategy.DIRECT,
        nodes=[],
        required_evidence=evidence,
    )

    with pytest.raises(FleetError, match="requires exactly control_plane_plan"):
        validate_fleet_plan(
            plan,
            _task(change_kind="read_only", required_evidence=evidence),
        )


def test_engineer_verifier_plan_requires_verdict_evidence() -> None:
    evidence = ["canonical_patch", "command_evidence"]
    plan = _plan(
        strategy=FleetStrategy.ENGINEER_VERIFIER,
        nodes=[_engineer(), _verifier()],
        required_evidence=evidence,
    )

    with pytest.raises(FleetError, match="requires independent_verifier_verdict"):
        validate_fleet_plan(plan, _task(required_evidence=evidence))


def test_task_spec_requires_nonempty_unique_acceptance_criteria() -> None:
    baseline = _task()
    payload = baseline.model_dump()
    payload["acceptance_criteria"] = []
    with pytest.raises(ValidationError, match="too_short"):
        TaskSpec.model_validate(payload)

    criterion = AcceptanceCriterion(
        criterion_id="duplicate",
        description="Must remain uniquely addressable.",
    )
    payload["acceptance_criteria"] = [criterion, criterion]
    with pytest.raises(ValidationError, match="criterion IDs must be unique"):
        TaskSpec.model_validate(payload)
