"""Deterministic acceptance and construction of the offline adaptive FleetPlan."""

from __future__ import annotations

from collections.abc import Sequence

from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.fleet_plan import (
    FleetPlan,
    FleetPlanNode,
    FleetStrategy,
    validate_fleet_plan,
)
from agent_fleet.domain.ids import IdPrefix
from agent_fleet.domain.models import Run, TaskSpec, WriterAssignment
from agent_fleet.ports.clock import Clock
from agent_fleet.ports.id_generator import IdGenerator


class FleetPlanner:
    def __init__(self, clock: Clock, ids: IdGenerator) -> None:
        self.clock = clock
        self.ids = ids

    def create(
        self,
        run: Run,
        task: TaskSpec,
        strategy: FleetStrategy,
        *,
        known_roles: set[str],
        role_max_steps: dict[str, int] | None = None,
        writer_assignments: Sequence[WriterAssignment] = (),
        max_parallel_agents: int = 2,
        configured_max_parallel_agents: int = 2,
    ) -> FleetPlan:
        if (
            type(max_parallel_agents) is not int
            or type(configured_max_parallel_agents) is not int
            or min(max_parallel_agents, configured_max_parallel_agents) < 1
        ):
            raise self._invalid("Parallel capacity must be a positive integer.")
        capacity = min(max_parallel_agents, configured_max_parallel_agents, 8)
        criteria = [criterion.criterion_id for criterion in task.acceptance_criteria]
        if writer_assignments and strategy is not FleetStrategy.PARALLEL_ENGINEERS:
            raise self._invalid("Only parallel plans accept writer assignments.")
        if strategy is FleetStrategy.DIRECT:
            nodes: list[FleetPlanNode] = []
            rationale = "Read-only request needs no specialist workspace or side effect."
        elif strategy is FleetStrategy.SINGLE_ENGINEER:
            nodes = [
                FleetPlanNode(
                    node_id="engineer",
                    role_id="engineer",
                    scope=task.allowed_paths,
                    can_write=True,
                    requires_workspace=True,
                    max_steps=20,
                )
            ]
            rationale = "Bounded low-risk change uses one Engineer and deterministic checks."
        elif strategy is FleetStrategy.ENGINEER_VERIFIER:
            nodes = [
                FleetPlanNode(
                    node_id="engineer",
                    role_id="engineer",
                    scope=task.allowed_paths,
                    can_write=True,
                    requires_workspace=True,
                    max_steps=20,
                ),
                FleetPlanNode(
                    node_id="verifier",
                    role_id="verifier",
                    depends_on=["engineer"],
                    scope=task.allowed_paths,
                    requires_workspace=True,
                    independent_verifier=True,
                    max_steps=10,
                ),
            ]
            rationale = "Behavioral code change uses a fresh independent Verifier."
        elif strategy is FleetStrategy.PARALLEL_ENGINEERS:
            if not 2 <= len(writer_assignments) <= 8 or capacity < 2:
                raise self._invalid("Parallel plans require two to eight writers and two slots.")
            assignments = [
                WriterAssignment.model_validate(item.model_dump()) for item in writer_assignments
            ]
            node_ids = [assignment.node_id for assignment in assignments]
            if len(node_ids) != len(set(node_ids)) or "verifier" in node_ids:
                raise self._invalid("Writer node IDs must be unique and cannot replace verifier.")
            if {item for assignment in assignments for item in assignment.criterion_ids} != set(
                criteria
            ):
                raise self._invalid("Writer assignments must cover exactly the original criteria.")
            if "independent_verifier_verdict" not in task.required_evidence:
                raise self._invalid("Parallel plans require independent verification evidence.")
            nodes = [
                FleetPlanNode(
                    node_id=assignment.node_id,
                    role_id="engineer",
                    goal=assignment.goal,
                    criterion_ids=assignment.criterion_ids,
                    scope=assignment.scope,
                    can_write=True,
                    requires_workspace=True,
                    max_steps=20,
                )
                for assignment in sorted(assignments, key=lambda item: item.node_id)
            ]
            nodes.append(
                FleetPlanNode(
                    node_id="verifier",
                    role_id="verifier",
                    goal=task.normalized_goal,
                    criterion_ids=criteria,
                    depends_on=[node.node_id for node in nodes],
                    scope=task.allowed_paths,
                    requires_workspace=True,
                    independent_verifier=True,
                    max_steps=10,
                )
            )
            rationale = (
                "Disjoint bounded Engineers queue under reviewed capacity before fresh joined "
                "verification."
            )
        else:
            roles = ("researcher", "architect", "engineer", "verifier")
            nodes = [
                FleetPlanNode(
                    node_id=role,
                    role_id=role,
                    goal=task.normalized_goal,
                    criterion_ids=criteria,
                    depends_on=[] if index == 0 else [roles[index - 1]],
                    scope=task.allowed_paths,
                    requires_workspace=True,
                    can_write=role == "engineer",
                    independent_verifier=role == "verifier",
                    max_steps=20 if role == "engineer" else 10,
                )
                for index, role in enumerate(roles)
            ]
            rationale = (
                "Read-only research and architecture guide one bounded Engineer before "
                "independent verification."
            )
        if role_max_steps is not None:
            nodes = [
                FleetPlanNode.model_validate(
                    {
                        **node.model_dump(),
                        "max_steps": min(
                            node.max_steps, role_max_steps.get(node.role_id, node.max_steps)
                        ),
                    }
                )
                for node in nodes
            ]
        plan = FleetPlan(
            plan_id=self.ids.new(IdPrefix.FLEET_PLAN),
            run_id=run.run_id,
            task_id=task.task_id,
            strategy=strategy,
            nodes=nodes,
            max_parallel_agents=capacity if strategy is FleetStrategy.PARALLEL_ENGINEERS else 1,
            required_evidence=task.required_evidence,
            rationale=rationale,
            created_at=self.clock.now(),
        )
        validate_fleet_plan(plan, task, known_roles=known_roles)
        return plan

    @staticmethod
    def _invalid(message: str) -> FleetError:
        return FleetError(
            ErrorCode.CONFIG_INVALID,
            message,
            "Use bounded disjoint assignments within reviewed roles, task scope and concurrency.",
        )
