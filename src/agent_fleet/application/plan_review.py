"""Human plan decisions verify exact evidence without granting tool authority."""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from agent_fleet.application.artifacts import ArtifactService
from agent_fleet.application.evolution import OrganizationService
from agent_fleet.domain.config import ConfigSnapshot
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.fleet_plan import FleetPlan, validate_fleet_plan
from agent_fleet.domain.models import Run, Sha256, TaskSpec
from agent_fleet.domain.plan_review import (
    PlanReviewBinding,
    PlanReviewCheckpoint,
    plan_review_run_sha256,
)
from agent_fleet.domain.role_templates import validate_role_plan
from agent_fleet.ports.clock import Clock
from agent_fleet.ports.config import ConfigurationPort
from agent_fleet.ports.plan_review import PlanReviewStore
from agent_fleet.ports.repository import RepositoryPort
from agent_fleet.ports.state_store import StateStore


def _invalid() -> FleetError:
    return FleetError(
        ErrorCode.RECOVERY_REQUIRED,
        "The task lacks an intact exact planning checkpoint.",
        "Inspect the existing task without regenerating its plan or replaying execution.",
    )


def _boundary[**P, R](operation: Callable[P, R]) -> Callable[P, R]:
    @wraps(operation)
    def call(*args: P.args, **kwargs: P.kwargs) -> R:
        error: FleetError
        try:
            return operation(*args, **kwargs)
        except FleetError as caught:
            error = caught
        except (ValidationError, ValueError, TypeError, KeyError, UnicodeError):
            error = _invalid()
        error.__context__ = None
        raise error from None

    return call


class PlanReviewService:
    def __init__(
        self,
        *,
        store: PlanReviewStore,
        state: StateStore,
        artifacts: ArtifactService,
        repository: RepositoryPort,
        config: ConfigurationPort,
        organization: OrganizationService,
        clock: Clock,
    ) -> None:
        self.store = store
        self.state = state
        self.artifacts = artifacts
        self.repository = repository
        self.config = config
        self.organization = organization
        self.clock = clock

    def _current(self, run: Run) -> Run:
        current = self.state.get_run(run.run_id)
        if (
            not current.plan_review_required
            or current.parent_run_id is not None
            or plan_review_run_sha256(current) != plan_review_run_sha256(run)
        ):
            raise _invalid()
        # Register exact pinned secrets before reading any repository/artifact content.
        self.organization.register_run_secrets(current)
        return current

    def _evidence(self, run: Run) -> None:
        if (
            run.task_id is None
            or run.task_spec_artifact_id is None
            or run.fleet_plan_artifact_id is None
            or run.config_snapshot_artifact_id is None
        ):
            raise _invalid()
        task = TaskSpec.model_validate_json(
            self.artifacts.read_bounded_text(run.task_spec_artifact_id, max_bytes=2_000_000)
        )
        plan = FleetPlan.model_validate_json(
            self.artifacts.read_bounded_text(run.fleet_plan_artifact_id, max_bytes=2_000_000)
        )
        snapshot = ConfigSnapshot.model_validate_json(
            self.artifacts.read_bounded_text(run.config_snapshot_artifact_id, max_bytes=16_777_216)
        )
        if any(
            self.artifacts.redactor.contains_secret_data(value.model_dump(mode="json"))
            for value in (task, plan, snapshot)
        ):
            raise FleetError(
                ErrorCode.ARTIFACT_INTEGRITY_FAILED,
                "The reviewed context contains registered secret material.",
                "Preserve the task and restore its safe original artifacts before inspection.",
            )
        if (
            task != self.state.get_task(run.task_id)
            or task.original_goal != run.goal
            or task.run_id != run.run_id
            or task.task_id != run.task_id
            or task.base_revision != run.base_revision
            or task.config_snapshot_hash != run.config_snapshot_hash
            or task.max_repair_iterations != run.max_repair_iterations
            or plan.run_id != run.run_id
            or plan.task_id != run.task_id
            or plan.strategy.value != run.fleet_strategy
            or self.config.snapshot_hash(snapshot) != run.config_snapshot_hash
        ):
            raise FleetError(
                ErrorCode.ARTIFACT_INTEGRITY_FAILED,
                "The reviewed plan artifacts do not match their task and configuration.",
                "Restore the exact original artifacts; a new plan cannot replace this decision.",
            )
        spec, rebuilt = self.config.snapshot_from_files(
            {item.path: item.content for item in snapshot.files}
        )
        if rebuilt != snapshot:
            raise _invalid()
        templates = self.config.role_templates(spec, snapshot)
        validate_fleet_plan(plan, task, known_roles=set(templates))
        validate_role_plan(plan, templates)

    def _target(self, run: Run) -> None:
        project = self.state.get_project(run.project_id)
        info = self.repository.inspect(Path(project.canonical_root))
        if (
            info.root != project.canonical_root
            or info.identity_hash != project.identity_hash
            or info.head_revision != run.base_revision
            or info.status_fingerprint != run.target_status_fingerprint
        ):
            raise FleetError(
                ErrorCode.PATCH_TARGET_DIVERGED,
                "The repository target changed after this plan was scoped.",
                "Preserve this decision and start a newly scoped task for the changed target.",
            )

    @_boundary
    def create(self, run: Run) -> PlanReviewCheckpoint:
        current = self._current(run)
        with self.organization.run_guard(current):
            current = self._current(run)
            self._evidence(current)
            self._target(current)
            project = self.state.get_project(current.project_id)
            admission = self.organization.store.admission_for_run(current.run_id)
            if admission is None or any(
                value is None
                for value in (
                    current.task_id,
                    current.task_spec_artifact_id,
                    current.task_spec_hash,
                    current.fleet_plan_artifact_id,
                    current.fleet_plan_hash,
                    current.config_snapshot_artifact_id,
                    current.config_snapshot_hash,
                )
            ):
                raise _invalid()
            binding = PlanReviewBinding.model_validate(
                {
                    "root_run_id": current.run_id,
                    "project_id": current.project_id,
                    "task_id": current.task_id,
                    "run_sha256": plan_review_run_sha256(current),
                    "task_spec_artifact_id": current.task_spec_artifact_id,
                    "task_spec_sha256": current.task_spec_hash,
                    "fleet_plan_artifact_id": current.fleet_plan_artifact_id,
                    "fleet_plan_sha256": current.fleet_plan_hash,
                    "config_snapshot_artifact_id": current.config_snapshot_artifact_id,
                    "config_snapshot_sha256": current.config_snapshot_hash,
                    "repository_root": project.canonical_root,
                    "repository_identity": project.identity_hash,
                    "base_revision": current.base_revision,
                    "target_status_fingerprint": current.target_status_fingerprint,
                    "organization_admission": admission,
                    "model_bindings_sha256": current.model_bindings_sha256,
                }
            )
            now = self.clock.now()
            return self.store.create(
                current,
                PlanReviewCheckpoint(
                    binding=binding, revision=1, status="pending", created_at=now, updated_at=now
                ),
            )

    @_boundary
    def inspect(self, run: Run) -> PlanReviewCheckpoint:
        """Historical inspection validates pinned evidence, not current organization policy."""
        current = self._current(run)
        checkpoint = self.store.get(current)
        self._evidence(current)
        return checkpoint

    @_boundary
    def approve(
        self,
        run: Run,
        expected_sha256: str,
        actor: str = "user",
        *,
        validate_review: Callable[[], None] | None = None,
    ) -> PlanReviewCheckpoint:
        if actor != "user":
            raise FleetError(
                ErrorCode.APPROVAL_INVALID,
                "Only an explicit user decision can approve this plan.",
                "Review the exact planning checkpoint through the user control plane.",
            )
        TypeAdapter(Sha256).validate_python(expected_sha256)
        current = self._current(run)
        with self.organization.run_guard(current):
            current = self._current(run)
            self.inspect(current)
            self._target(current)
            if validate_review is not None:
                validate_review()
            return self.store.approve(current, expected_sha256=expected_sha256, actor=actor)

    @_boundary
    def consume(self, run: Run, expected_sha256: str) -> Run:
        TypeAdapter(Sha256).validate_python(expected_sha256)
        current = self._current(run)
        with self.organization.run_guard(current):
            current = self._current(run)
            self.inspect(current)
            self._target(current)
            return self.store.consume(current, expected_sha256=expected_sha256)
