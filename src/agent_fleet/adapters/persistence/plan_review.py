"""Atomic plan approval journal and non-replayable execution handoff."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import wraps

from pydantic import ValidationError

from agent_fleet.adapters.persistence.evolution import _admission, check_organization_admission
from agent_fleet.adapters.persistence.sqlite import SUPPORTED_SCHEMA_VERSION, SqliteStateStore
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import (
    ArtifactKind,
    ArtifactMetadata,
    FleetEvent,
    Project,
    Run,
    RunStatus,
    WorkflowStage,
)
from agent_fleet.domain.plan_review import PlanReviewCheckpoint, plan_review_run_sha256


def _invalid() -> FleetError:
    return FleetError(
        ErrorCode.RECOVERY_REQUIRED,
        "The required plan review or its durable authority is inconsistent.",
        "Preserve the task and inspect its exact decision history; "
        "do not reconstruct or replay it.",
    )


def _stale() -> FleetError:
    return FleetError(
        ErrorCode.APPROVAL_INVALID,
        "The plan review is stale, already consumed, or not available for this action.",
        "Inspect the exact task and review its current checkpoint before proceeding.",
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
        except (sqlite3.Error, OSError):
            error = FleetError(
                ErrorCode.STATE_UNAVAILABLE,
                "The plan decision store is unavailable.",
                "Restore the selected local state; uncertain execution must not be replayed.",
            )
        error.__context__ = None
        raise error from None

    return call


class SqlitePlanReviewStore:
    def __init__(self, state: SqliteStateStore) -> None:
        self.state = state

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(
            f"{self.state.database_path.absolute().as_uri()}?mode=rw", uri=True
        )
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 5000")
            connection.execute("BEGIN IMMEDIATE")
            versions = [
                row[0]
                for row in connection.execute(
                    "SELECT version FROM schema_migrations ORDER BY version LIMIT ?",
                    (SUPPORTED_SCHEMA_VERSION + 2,),
                )
            ]
            if versions != list(range(1, SUPPORTED_SCHEMA_VERSION + 1)):
                raise _invalid()
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _run(self, connection: sqlite3.Connection, expected: Run) -> Run:
        expected = self.state._decode_state_record(Run, expected.model_dump_json(warnings=False))
        run = self.state._validated_run(connection, expected.run_id)
        if (
            not run.plan_review_required
            or run.parent_run_id is not None
            or plan_review_run_sha256(run) != plan_review_run_sha256(expected)
        ):
            raise _invalid()
        return run

    def _binding(
        self, connection: sqlite3.Connection, run: Run, checkpoint: PlanReviewCheckpoint
    ) -> None:
        binding = checkpoint.binding
        row = connection.execute(
            "SELECT * FROM projects WHERE project_id=?", (run.project_id,)
        ).fetchone()
        if row is None:
            raise _invalid()
        project = self.state._decode_state_record(Project, row["data_json"])
        if (
            project.project_id != run.project_id
            or project.canonical_root != row["canonical_root"]
            or binding.root_run_id != run.run_id
            or binding.project_id != run.project_id
            or binding.task_id != run.task_id
            or binding.run_sha256 != plan_review_run_sha256(run)
            or binding.repository_root != project.canonical_root
            or binding.repository_identity != project.identity_hash
            or binding.base_revision != run.base_revision
            or binding.target_status_fingerprint != run.target_status_fingerprint
            or binding.model_bindings_sha256 != run.model_bindings_sha256
            or _admission(connection, run, self.state.redactor) != binding.organization_admission
        ):
            raise _invalid()
        for artifact_id, digest, kind, run_artifact_id, run_digest in (
            (
                binding.task_spec_artifact_id,
                binding.task_spec_sha256,
                ArtifactKind.TASK_SPEC,
                run.task_spec_artifact_id,
                run.task_spec_hash,
            ),
            (
                binding.fleet_plan_artifact_id,
                binding.fleet_plan_sha256,
                ArtifactKind.FLEET_PLAN,
                run.fleet_plan_artifact_id,
                run.fleet_plan_hash,
            ),
            (
                binding.config_snapshot_artifact_id,
                binding.config_snapshot_sha256,
                ArtifactKind.CONFIG_SNAPSHOT,
                run.config_snapshot_artifact_id,
                run.config_snapshot_hash,
            ),
        ):
            row = connection.execute(
                "SELECT * FROM artifacts WHERE artifact_id=?", (artifact_id,)
            ).fetchone()
            if row is None:
                raise _invalid()
            artifact = self.state._decode_state_record(ArtifactMetadata, row["data_json"])
            if (
                artifact.artifact_id != artifact_id
                or artifact_id != run_artifact_id
                or artifact.sha256 != digest
                or digest != run_digest
                or row["sha256"] != digest
                or artifact.kind is not kind
                or row["kind"] != kind.value
                or artifact.run_id != run.run_id
                or row["run_id"] != run.run_id
                or artifact.project_id != run.project_id
                or row["project_id"] != run.project_id
                or artifact.task_id != run.task_id
            ):
                raise _invalid()

    @staticmethod
    def _payload(checkpoint: PlanReviewCheckpoint) -> dict[str, object]:
        return {
            "checkpoint_sha256": checkpoint.checkpoint_sha256,
            "binding_sha256": checkpoint.binding_sha256,
            "revision": checkpoint.revision,
            "status": checkpoint.status,
        }

    def _get(self, connection: sqlite3.Connection, run: Run) -> PlanReviewCheckpoint:
        head = connection.execute(
            "SELECT revision FROM plan_review_heads WHERE root_run_id=?", (run.run_id,)
        ).fetchone()
        rows = connection.execute(
            "SELECT * FROM plan_review_versions WHERE root_run_id=? ORDER BY revision LIMIT 4",
            (run.run_id,),
        ).fetchall()
        if head is None or not rows or len(rows) > 3 or head[0] != len(rows):
            raise _invalid()
        previous: PlanReviewCheckpoint | None = None
        for revision, row in enumerate(rows, 1):
            item = self.state._decode_state_record(PlanReviewCheckpoint, row["data_json"])
            if (
                item.binding.root_run_id != run.run_id
                or row["root_run_id"] != run.run_id
                or item.revision != revision
                or row["revision"] != revision
                or item.status != row["status"]
                or item.checkpoint_sha256 != row["checkpoint_sha256"]
                or item.binding_sha256 != row["binding_sha256"]
                or (
                    previous is not None
                    and (
                        item.previous_sha256 != previous.checkpoint_sha256
                        or item.binding != previous.binding
                        or item.created_at != previous.created_at
                        or item.updated_at < previous.updated_at
                    )
                )
            ):
                raise _invalid()
            receipt = connection.execute(
                "SELECT * FROM run_events WHERE event_id=?", (row["audit_event_id"],)
            ).fetchone()
            if receipt is None:
                raise _invalid()
            event = self.state._decode_state_record(FleetEvent, receipt["data_json"])
            if (
                event.event_id != row["audit_event_id"]
                or event.run_id != run.run_id
                or receipt["run_id"] != run.run_id
                or event.project_id != run.project_id
                or receipt["project_id"] != run.project_id
                or event.task_id != run.task_id
                or event.correlation_id != run.correlation_id
                or event.event_type != f"plan_review.{item.status}"
                or receipt["event_type"] != event.event_type
                or event.sequence != receipt["sequence"]
                or event.occurred_at.isoformat() != receipt["occurred_at"]
                or event.payload != self._payload(item)
            ):
                raise _invalid()
            previous = item
        assert previous is not None
        receipts = connection.execute(
            "SELECT COUNT(*) FROM run_events WHERE run_id=? AND event_type IN "
            "('plan_review.pending','plan_review.approved','plan_review.consumed')",
            (run.run_id,),
        ).fetchone()[0]
        if receipts != len(rows):
            raise _invalid()
        self._binding(connection, run, previous)
        if run.status is RunStatus.PAUSED_FOR_PLAN:
            if previous.status == "consumed" or run.stage is not WorkflowStage.SCOPING:
                raise _invalid()
        elif previous.status != "consumed" and run.status not in {
            RunStatus.CANCELLED,
            RunStatus.FAILED,
            RunStatus.ABANDONED,
            RunStatus.REJECTED,
        }:
            raise _invalid()
        return previous

    @staticmethod
    def _uneffected(connection: sqlite3.Connection, run: Run) -> None:
        for sql in (
            "SELECT 1 FROM resource_leases WHERE run_id=? LIMIT 1",
            "SELECT 1 FROM tool_intents WHERE run_id=? LIMIT 1",
            "SELECT 1 FROM fleet_graphs WHERE parent_run_id=? LIMIT 1",
        ):
            if connection.execute(sql, (run.run_id,)).fetchone() is not None:
                raise _invalid()
        # Parent identity is inside the validated Run JSON in the legacy runs table.
        if (
            connection.execute(
                "SELECT 1 FROM runs WHERE json_extract(data_json, '$.parent_run_id')=? LIMIT 1",
                (run.run_id,),
            ).fetchone()
            is not None
        ):
            raise _invalid()

    def _publish(
        self,
        connection: sqlite3.Connection,
        run: Run,
        item: PlanReviewCheckpoint,
        *,
        transition: RunStatus | None = None,
    ) -> Run:
        event_type = f"plan_review.{item.status}"
        if transition is not None:
            run = run.model_copy(update={"status": transition, "updated_at": item.updated_at})
            self.state._save_run_in_transaction(connection, run, event_type, self._payload(item))
            event_id = connection.execute(
                "SELECT event_id FROM run_events WHERE run_id=? ORDER BY sequence DESC LIMIT 1",
                (run.run_id,),
            ).fetchone()[0]
        else:
            event_id = self.state._insert_event(
                connection, self.state._event_for_run(run, event_type, self._payload(item))
            ).event_id
        connection.execute(
            "INSERT INTO plan_review_versions(root_run_id,revision,status,checkpoint_sha256,"
            "binding_sha256,audit_event_id,data_json) VALUES (?,?,?,?,?,?,?)",
            (
                run.run_id,
                item.revision,
                item.status,
                item.checkpoint_sha256,
                item.binding_sha256,
                event_id,
                item.model_dump_json(),
            ),
        )
        connection.execute(
            "INSERT INTO plan_review_heads(root_run_id,revision) VALUES (?,?) "
            "ON CONFLICT(root_run_id) DO UPDATE SET revision=excluded.revision",
            (run.run_id, item.revision),
        )
        return run

    @_boundary
    def create(self, run: Run, checkpoint: PlanReviewCheckpoint) -> PlanReviewCheckpoint:
        checkpoint = self.state._decode_state_record(
            PlanReviewCheckpoint, checkpoint.model_dump_json(warnings=False)
        )
        with self._transaction() as connection:
            current = self._run(connection, run)
            if (
                current != run
                or current.status is not RunStatus.RUNNING
                or (current.stage is not WorkflowStage.SCOPING or checkpoint.status != "pending")
            ):
                raise _stale()
            self._binding(connection, current, checkpoint)
            check_organization_admission(
                connection,
                current,
                checkpoint.binding.organization_admission,
                redactor=self.state.redactor,
            )
            self._uneffected(connection, current)
            if any(
                connection.execute(sql, (run.run_id,)).fetchone() is not None
                for sql in (
                    "SELECT 1 FROM plan_review_heads WHERE root_run_id=?",
                    "SELECT 1 FROM plan_review_versions WHERE root_run_id=? LIMIT 1",
                    "SELECT 1 FROM run_events WHERE run_id=? "
                    "AND event_type LIKE 'plan_review.%' LIMIT 1",
                )
            ):
                raise _invalid()
            self._publish(connection, current, checkpoint, transition=RunStatus.PAUSED_FOR_PLAN)
            return checkpoint

    @_boundary
    def get(self, run: Run) -> PlanReviewCheckpoint:
        with self._transaction() as connection:
            return self._get(connection, self._run(connection, run))

    def _advance(
        self, connection: sqlite3.Connection, run: Run, expected_sha256: str, *, consume: bool
    ) -> tuple[Run, PlanReviewCheckpoint]:
        current = self._run(connection, run)
        item = self._get(connection, current)
        if (
            current != run
            or current.status is not RunStatus.PAUSED_FOR_PLAN
            or current.stage is not WorkflowStage.SCOPING
            or item.status != ("approved" if consume else "pending")
            or expected_sha256 != item.checkpoint_sha256
        ):
            raise _stale()
        check_organization_admission(
            connection, current, item.binding.organization_admission, redactor=self.state.redactor
        )
        self._uneffected(connection, current)
        item = PlanReviewCheckpoint.model_validate_json(
            item.model_copy(
                update={
                    "revision": item.revision + 1,
                    "status": "consumed" if consume else "approved",
                    "previous_sha256": item.checkpoint_sha256,
                    "actor": "user",
                    "updated_at": self.state.clock.now(),
                }
            ).model_dump_json()
        )
        result = self._publish(
            connection, current, item, transition=RunStatus.RUNNING if consume else None
        )
        return result, item

    @_boundary
    def approve(self, run: Run, *, expected_sha256: str, actor: str) -> PlanReviewCheckpoint:
        if actor != "user":
            raise _stale()
        with self._transaction() as connection:
            return self._advance(connection, run, expected_sha256, consume=False)[1]

    @_boundary
    def consume(self, run: Run, *, expected_sha256: str) -> Run:
        with self._transaction() as connection:
            return self._advance(connection, run, expected_sha256, consume=True)[0]
