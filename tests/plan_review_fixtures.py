"""Actual scoped artifacts and admitted runs; no runtime, workspace or tool dispatch."""

from __future__ import annotations

from dataclasses import dataclass

from conftest import FleetHarness

from agent_fleet.adapters.persistence.plan_review import SqlitePlanReviewStore
from agent_fleet.application.plan_review import PlanReviewService
from agent_fleet.domain.fleet_plan import FleetStrategy
from agent_fleet.domain.ids import IdPrefix
from agent_fleet.domain.models import (
    AcceptanceCriterion,
    ArtifactKind,
    Run,
    RunStatus,
    TaskSpec,
    WorkflowStage,
)


@dataclass
class PlanReviewHarness:
    fleet: FleetHarness
    service: PlanReviewService
    store: SqlitePlanReviewStore
    scoped: Run

    @property
    def run(self) -> Run:
        return self.fleet.container.state.get_run(self.scoped.run_id)


def make_plan_review(harness: FleetHarness) -> PlanReviewHarness:
    c = harness.container
    engine = c.workflow
    project = c.organization.project_for_path(harness.repository_root)
    info = c.repository.inspect(harness.repository_root)
    spec, snapshot = engine.config.load_snapshot(harness.repository_root / ".fleet" / "fleet.yaml")
    config_hash = engine.config.snapshot_hash(snapshot)
    now = engine.clock.now()
    run = Run(
        run_id=engine.ids.new(IdPrefix.RUN),
        project_id=project.project_id,
        correlation_id=engine.ids.new(IdPrefix.CORRELATION),
        goal="Fix the canary behavior",
        plan_review_required=True,
        base_revision=info.head_revision,
        target_status_fingerprint=info.status_fingerprint,
        config_snapshot_hash=config_hash,
        created_at=now,
        updated_at=now,
    )
    with c.organization.admission(project) as admission:
        c.state.create_run(run, organization_admission=admission)
    for stage in (WorkflowStage.INTAKE, WorkflowStage.SCOPING):
        run = c.state.save_run(
            run.model_copy(update={"status": RunStatus.RUNNING, "stage": stage}),
            "run.transitioned",
            {},
        )
    task = TaskSpec(
        task_id=engine.ids.new(IdPrefix.TASK),
        run_id=run.run_id,
        original_goal=run.goal,
        normalized_goal=run.goal,
        base_revision=run.base_revision,
        allowed_paths=["src/canary_calc/core.py"],
        forbidden_paths=[".git", ".fleet"],
        acceptance_criteria=[
            AcceptanceCriterion(
                criterion_id="canary-behavior", description="The canary behavior is fixed."
            )
        ],
        required_evidence=["canonical_patch", "command_evidence", "independent_verifier_verdict"],
        max_repair_iterations=1,
        config_snapshot_hash=config_hash,
        created_at=now,
    )
    templates = engine.config.role_templates(spec, snapshot)
    plan = engine.planner.create(
        run,
        task,
        FleetStrategy.ENGINEER_VERIFIER,
        known_roles=set(templates),
        role_templates=templates,
    )
    c.state.save_task(task)
    task_artifact = c.artifacts.create_text(
        kind=ArtifactKind.TASK_SPEC,
        project_id=run.project_id,
        run_id=run.run_id,
        task_id=task.task_id,
        content=task.model_dump_json(indent=2),
        producer="control-plane",
    )
    plan_artifact = c.artifacts.create_text(
        kind=ArtifactKind.FLEET_PLAN,
        project_id=run.project_id,
        run_id=run.run_id,
        task_id=task.task_id,
        content=plan.model_dump_json(indent=2),
        producer="control-plane",
    )
    config_artifact = c.artifacts.create_text(
        kind=ArtifactKind.CONFIG_SNAPSHOT,
        project_id=run.project_id,
        run_id=run.run_id,
        task_id=task.task_id,
        content=snapshot.model_dump_json(indent=2),
        producer="control-plane",
    )
    run = c.state.save_run(
        run.model_copy(
            update={
                "task_id": task.task_id,
                "task_spec_artifact_id": task_artifact.artifact_id,
                "task_spec_hash": task_artifact.sha256,
                "fleet_plan_artifact_id": plan_artifact.artifact_id,
                "fleet_plan_hash": plan_artifact.sha256,
                "fleet_strategy": plan.strategy.value,
                "config_snapshot_artifact_id": config_artifact.artifact_id,
            }
        ),
        "run.task_bound",
        {},
    )
    store = SqlitePlanReviewStore(c.state)
    service = PlanReviewService(
        store=store,
        state=c.state,
        artifacts=c.artifacts,
        repository=c.repository,
        config=engine.config,
        organization=c.organization,
        clock=engine.clock,
    )
    return PlanReviewHarness(harness, service, store, run)
