"""Deterministic acceptance and construction of the offline adaptive FleetPlan."""

from __future__ import annotations

from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.fleet_plan import (
    FleetPlan,
    FleetPlanNode,
    FleetStrategy,
    validate_fleet_plan,
)
from agent_fleet.domain.ids import IdPrefix
from agent_fleet.domain.models import Run, TaskSpec
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
    ) -> FleetPlan:
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
        else:
            raise FleetError(
                ErrorCode.CONFIG_INVALID,
                f"Fleet strategy {strategy.value!r} is not executable in Phase 1.5.",
                "Use direct, single_engineer, or engineer_verifier until the adaptive "
                "parallel scheduler is implemented.",
            )
        plan = FleetPlan(
            plan_id=self.ids.new(IdPrefix.FLEET_PLAN),
            run_id=run.run_id,
            task_id=task.task_id,
            strategy=strategy,
            nodes=nodes,
            max_parallel_agents=1,
            required_evidence=task.required_evidence,
            rationale=rationale,
            created_at=self.clock.now(),
        )
        validate_fleet_plan(plan, task, known_roles=known_roles)
        return plan
