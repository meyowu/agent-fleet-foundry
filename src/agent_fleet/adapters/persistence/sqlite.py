"""SQLite state store with transactional transitions and append-only events."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from datetime import timedelta
from importlib.resources import files
from pathlib import Path
from typing import cast

from pydantic import JsonValue

from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.ids import IdPrefix
from agent_fleet.domain.models import (
    AgentInstance,
    ApprovalRequest,
    ApprovalStatus,
    ArtifactMetadata,
    CapabilityGrant,
    FleetEvent,
    IntentStatus,
    LeaseKind,
    LeaseStatus,
    Project,
    ResourceLease,
    Run,
    RunStatus,
    StoredToolIntent,
    TaskSpec,
    ToolIntent,
    jsonable,
)
from agent_fleet.domain.security import Redactor
from agent_fleet.domain.workflow import validate_transition
from agent_fleet.ports.clock import Clock
from agent_fleet.ports.id_generator import IdGenerator

SUPPORTED_SCHEMA_VERSION = 1


class SqliteStateStore:
    """Explicit aggregate persistence; not a generic key-value store."""

    def __init__(
        self,
        database_path: Path,
        clock: Clock,
        ids: IdGenerator,
        redactor: Redactor,
    ) -> None:
        self.database_path = database_path
        self.clock = clock
        self.ids = ids
        self.redactor = redactor

    def _connect(self) -> sqlite3.Connection:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def migrate(self) -> int:
        try:
            return self._migrate()
        except FleetError:
            raise
        except (OSError, sqlite3.Error) as error:
            raise FleetError(
                ErrorCode.STATE_UNAVAILABLE,
                "The local SQLite state store could not be opened or migrated.",
                "Check the selected state directory permissions and database integrity.",
            ) from error

    def _migrate(self) -> int:
        with self._connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations "
                "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            row = connection.execute(
                "SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations"
            ).fetchone()
            current = int(row["version"])
            if current > SUPPORTED_SCHEMA_VERSION:
                raise FleetError(
                    ErrorCode.STATE_SCHEMA_INCOMPATIBLE,
                    "State schema "
                    f"{current} is newer than supported version {SUPPORTED_SCHEMA_VERSION}.",
                    "Upgrade Agent Fleet or select a compatible state directory.",
                )
            for version in range(current + 1, SUPPORTED_SCHEMA_VERSION + 1):
                migration = (
                    files("agent_fleet.adapters.persistence.migrations")
                    .joinpath(f"{version:04d}.sql")
                    .read_text(encoding="utf-8")
                )
                try:
                    connection.execute("BEGIN IMMEDIATE")
                    for statement in _split_sql(migration):
                        connection.execute(statement)
                    connection.execute(
                        "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                        (version, self.clock.now().isoformat()),
                    )
                    connection.commit()
                except sqlite3.Error:
                    connection.rollback()
                    raise
            return SUPPORTED_SCHEMA_VERSION

    def save_project(self, project: Project) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO projects(project_id, canonical_root, data_json) VALUES (?, ?, ?) "
                "ON CONFLICT(project_id) DO UPDATE SET "
                "canonical_root=excluded.canonical_root, data_json=excluded.data_json",
                (project.project_id, project.canonical_root, project.model_dump_json()),
            )

    def get_project(self, project_id: str) -> Project:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT data_json FROM projects WHERE project_id = ?", (project_id,)
            ).fetchone()
        if row is None:
            raise _not_found("project", project_id)
        return Project.model_validate_json(row["data_json"])

    def get_project_by_root(self, canonical_root: str) -> Project | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT data_json FROM projects WHERE canonical_root = ?", (canonical_root,)
            ).fetchone()
        return Project.model_validate_json(row["data_json"]) if row is not None else None

    def create_run(self, run: Run) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO runs(run_id, project_id, status, stage, data_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    run.run_id,
                    run.project_id,
                    run.status.value,
                    run.stage.value if run.stage else None,
                    run.model_dump_json(),
                ),
            )
            self._insert_event(
                connection,
                self._event_for_run(
                    run, "run.created", {"goal": run.goal, "status": run.status.value}
                ),
            )
            connection.commit()

    def get_run(self, run_id: str) -> Run:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT data_json FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        if row is None:
            raise _not_found("run", run_id)
        return Run.model_validate_json(row["data_json"])

    def save_run(self, run: Run, event_type: str, payload: dict[str, object]) -> Run:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT data_json FROM runs WHERE run_id = ?", (run.run_id,)
            ).fetchone()
            if row is None:
                raise _not_found("run", run.run_id)
            current = Run.model_validate_json(row["data_json"])
            validate_transition(current, run.status, run.stage)
            connection.execute(
                "UPDATE runs SET status = ?, stage = ?, data_json = ? WHERE run_id = ?",
                (
                    run.status.value,
                    run.stage.value if run.stage else None,
                    run.model_dump_json(),
                    run.run_id,
                ),
            )
            self._insert_event(connection, self._event_for_run(run, event_type, payload))
            connection.commit()
        return run

    def save_task(self, task: TaskSpec) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO tasks(task_id, run_id, data_json) VALUES (?, ?, ?)",
                (task.task_id, task.run_id, task.model_dump_json()),
            )
            run = self._get_run(connection, task.run_id)
            self._insert_event(
                connection,
                self._event_for_run(
                    run,
                    "task.scoped",
                    {"task_id": task.task_id, "acceptance_criteria": len(task.acceptance_criteria)},
                    task_id=task.task_id,
                ),
            )
            connection.commit()

    def get_task(self, task_id: str) -> TaskSpec:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT data_json FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
        if row is None:
            raise _not_found("task", task_id)
        return TaskSpec.model_validate_json(row["data_json"])

    def save_agent_instance(self, instance: AgentInstance) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO agent_instances(agent_instance_id, run_id, task_id, role, data_json) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT(agent_instance_id) "
                "DO UPDATE SET data_json=excluded.data_json",
                (
                    instance.agent_instance_id,
                    instance.run_id,
                    instance.task_id,
                    instance.role.value,
                    instance.model_dump_json(),
                ),
            )

    def append_event(self, event: FleetEvent) -> FleetEvent:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            persisted = self._insert_event(connection, event)
            connection.commit()
        return persisted

    def emit(self, event: FleetEvent) -> FleetEvent:
        return self.append_event(event)

    def list_events(self, run_id: str) -> Sequence[FleetEvent]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT data_json FROM run_events WHERE run_id = ? ORDER BY sequence", (run_id,)
            ).fetchall()
        return [FleetEvent.model_validate_json(row["data_json"]) for row in rows]

    def save_artifact(self, artifact: ArtifactMetadata) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO artifacts(artifact_id, project_id, run_id, kind, sha256, data_json) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    artifact.artifact_id,
                    artifact.project_id,
                    artifact.run_id,
                    artifact.kind.value,
                    artifact.sha256,
                    artifact.model_dump_json(),
                ),
            )
            correlation_id = self.ids.new(IdPrefix.CORRELATION)
            task_id = artifact.task_id
            if artifact.run_id is not None:
                run = self._get_run(connection, artifact.run_id)
                correlation_id = run.correlation_id
                task_id = run.task_id or task_id
            self._insert_event(
                connection,
                FleetEvent(
                    event_id=self.ids.new(IdPrefix.EVENT),
                    event_type="artifact.created",
                    occurred_at=artifact.created_at,
                    project_id=artifact.project_id,
                    run_id=artifact.run_id,
                    task_id=task_id,
                    correlation_id=correlation_id,
                    payload={
                        "artifact_id": artifact.artifact_id,
                        "kind": artifact.kind.value,
                        "sha256": artifact.sha256,
                    },
                ),
            )
            connection.commit()

    def get_artifact(self, artifact_id: str) -> ArtifactMetadata:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT data_json FROM artifacts WHERE artifact_id = ?", (artifact_id,)
            ).fetchone()
        if row is None:
            raise _not_found("artifact", artifact_id)
        return ArtifactMetadata.model_validate_json(row["data_json"])

    def list_artifacts(self, run_id: str) -> Sequence[ArtifactMetadata]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT data_json FROM artifacts WHERE run_id = ? ORDER BY rowid", (run_id,)
            ).fetchall()
        return [ArtifactMetadata.model_validate_json(row["data_json"]) for row in rows]

    def find_intent(self, run_id: str, idempotency_key: str) -> StoredToolIntent | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT data_json FROM tool_intents WHERE run_id = ? AND idempotency_key = ?",
                (run_id, idempotency_key),
            ).fetchone()
        return StoredToolIntent.model_validate_json(row["data_json"]) if row is not None else None

    def reserve_intent(self, intent: ToolIntent, intent_hash: str) -> StoredToolIntent:
        stored = StoredToolIntent(
            intent=intent, intent_hash=intent_hash, status=IntentStatus.RESERVED
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._find_intent(connection, intent.run_id, intent.idempotency_key)
            if existing is not None:
                connection.commit()
                return existing
            self._insert_intent(connection, stored)
            run = self._get_run(connection, intent.run_id)
            self._insert_event(
                connection,
                self._event_for_intent(
                    run, intent, "tool.intent_created", {"action": intent.action}
                ),
            )
            connection.commit()
        return stored

    def create_approval_and_pause(
        self, intent: ToolIntent, intent_hash: str, request: ApprovalRequest
    ) -> StoredToolIntent:
        stored = StoredToolIntent(
            intent=intent,
            intent_hash=intent_hash,
            status=IntentStatus.PENDING_APPROVAL,
            approval_request_id=request.request_id,
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._find_intent(connection, intent.run_id, intent.idempotency_key)
            if existing is not None:
                connection.commit()
                return existing
            run = self._get_run(connection, intent.run_id)
            paused = run.model_copy(
                update={
                    "status": RunStatus.PAUSED_FOR_APPROVAL,
                    "pending_approval_id": request.request_id,
                    "updated_at": request.created_at,
                }
            )
            validate_transition(run, paused.status, paused.stage)
            self._insert_intent(connection, stored)
            connection.execute(
                "INSERT INTO approvals(request_id, intent_id, run_id, status, data_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    request.request_id,
                    request.intent_id,
                    request.run_id,
                    request.status.value,
                    request.model_dump_json(),
                ),
            )
            self._update_run(connection, paused)
            self._insert_event(
                connection,
                self._event_for_intent(
                    run, intent, "tool.intent_created", {"action": intent.action}
                ),
            )
            self._insert_event(
                connection,
                self._event_for_intent(
                    run,
                    intent,
                    "approval.requested",
                    {
                        "request_id": request.request_id,
                        "intent_hash": request.intent_hash,
                        "action": request.action,
                        "resource": request.resource.model_dump(mode="json"),
                    },
                ),
            )
            self._insert_event(
                connection,
                self._event_for_run(
                    paused,
                    "run.paused",
                    {
                        "request_id": request.request_id,
                        "stage": paused.stage.value if paused.stage else None,
                    },
                ),
            )
            connection.commit()
        return stored

    def get_approval(self, request_id: str) -> ApprovalRequest:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT data_json FROM approvals WHERE request_id = ?", (request_id,)
            ).fetchone()
        if row is None:
            raise _not_found("approval request", request_id)
        return ApprovalRequest.model_validate_json(row["data_json"])

    def resolve_approval(
        self, request_id: str, *, approve: bool, denial_reason: str | None
    ) -> CapabilityGrant | None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            request = self._get_approval(connection, request_id)
            if request.status is not ApprovalStatus.PENDING:
                grant = self._get_grant_for_request(connection, request_id)
                connection.commit()
                return grant
            now = self.clock.now()
            intent = self._get_intent_by_id(connection, request.intent_id)
            run = self._get_run(connection, request.run_id)
            if approve:
                if request.expires_at <= now:
                    raise FleetError(
                        ErrorCode.APPROVAL_INVALID,
                        "The approval request expired before it was resolved.",
                        "Resume or start a new run to create a fresh exact request.",
                        details={"request_id": request_id},
                    )
                resolved = request.model_copy(
                    update={"status": ApprovalStatus.APPROVED, "resolved_at": now}
                )
                grant = CapabilityGrant(
                    grant_id=self.ids.new(IdPrefix.GRANT),
                    request_id=request.request_id,
                    intent_id=request.intent_id,
                    project_id=run.project_id,
                    run_id=run.run_id,
                    task_id=intent.intent.task_id,
                    agent_instance_id=intent.intent.agent_instance_id,
                    principal_role=intent.intent.principal_role,
                    action=intent.intent.action,
                    resource=intent.intent.resource,
                    intent_hash=request.intent_hash,
                    issued_at=now,
                    expires_at=min(request.expires_at, now + timedelta(minutes=10)),
                )
                connection.execute(
                    "INSERT INTO capability_grants"
                    "(grant_id, request_id, intent_id, run_id, remaining_uses, data_json) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        grant.grant_id,
                        grant.request_id,
                        grant.intent_id,
                        grant.run_id,
                        grant.remaining_uses,
                        grant.model_dump_json(),
                    ),
                )
            else:
                safe_denial_reason = None
                if denial_reason is not None:
                    safe_denial_reason, _ = self.redactor.redact_text(denial_reason)
                resolved = request.model_copy(
                    update={
                        "status": ApprovalStatus.DENIED,
                        "resolved_at": now,
                        "denial_reason": safe_denial_reason,
                    }
                )
                grant = None
                denied = intent.model_copy(update={"status": IntentStatus.DENIED})
                self._update_intent(connection, denied)
            connection.execute(
                "UPDATE approvals SET status = ?, data_json = ? WHERE request_id = ?",
                (resolved.status.value, resolved.model_dump_json(), request_id),
            )
            self._insert_event(
                connection,
                self._event_for_intent(
                    run,
                    intent.intent,
                    "approval.resolved",
                    {"request_id": request_id, "resolution": resolved.status.value},
                ),
            )
            if grant is not None:
                self._insert_event(
                    connection,
                    self._event_for_intent(
                        run,
                        intent.intent,
                        "capability.issued",
                        {"grant_id": grant.grant_id, "remaining_uses": 1},
                    ),
                )
            connection.commit()
            return grant

    def consume_grant_and_reserve(self, request_id: str, intent_hash: str) -> StoredToolIntent:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            request = self._get_approval(connection, request_id)
            intent = self._get_intent_by_id(connection, request.intent_id)
            if intent.status in {IntentStatus.RESERVED, IntentStatus.EXECUTED}:
                connection.commit()
                return intent
            grant = self._get_grant_for_request(connection, request_id)
            now = self.clock.now()
            if (
                request.status is not ApprovalStatus.APPROVED
                or grant is None
                or grant.intent_hash != intent_hash
                or request.intent_hash != intent_hash
                or grant.expires_at <= now
                or grant.remaining_uses != 1
            ):
                raise FleetError(
                    ErrorCode.APPROVAL_INVALID,
                    "The one-use capability does not exactly match the pending intent.",
                    "Inspect the approval and start a new request if its scope or expiry changed.",
                    details={"request_id": request_id},
                )
            consumed = grant.model_copy(update={"remaining_uses": 0, "consumed_at": now})
            reserved = intent.model_copy(update={"status": IntentStatus.RESERVED})
            connection.execute(
                "UPDATE capability_grants SET remaining_uses = 0, data_json = ? WHERE grant_id = ?",
                (consumed.model_dump_json(), consumed.grant_id),
            )
            self._update_intent(connection, reserved)
            run = self._get_run(connection, intent.intent.run_id)
            self._insert_event(
                connection,
                self._event_for_intent(
                    run,
                    intent.intent,
                    "capability.consumed",
                    {"grant_id": grant.grant_id, "intent_id": intent.intent.intent_id},
                ),
            )
            connection.commit()
            return reserved

    def complete_intent(self, intent_id: str, result: dict[str, object]) -> StoredToolIntent:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = self._get_intent_by_id(connection, intent_id)
            if current.status is IntentStatus.EXECUTED:
                connection.commit()
                return current
            cleaned, _ = self.redactor.redact_data(result)
            completed = current.model_copy(
                update={
                    "status": IntentStatus.EXECUTED,
                    "result": cast(dict[str, JsonValue], cleaned),
                }
            )
            self._update_intent(connection, completed)
            run = self._get_run(connection, current.intent.run_id)
            self._insert_event(
                connection,
                self._event_for_intent(
                    run,
                    current.intent,
                    "tool.intent_executed",
                    {"intent_id": intent_id, "action": current.intent.action},
                ),
            )
            connection.commit()
            return completed

    def deny_intent(self, intent_id: str) -> None:
        with self._connect() as connection:
            current = self._get_intent_by_id(connection, intent_id)
            self._update_intent(
                connection, current.model_copy(update={"status": IntentStatus.DENIED})
            )

    def save_lease(self, lease: ResourceLease) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO resource_leases"
                "(lease_id, run_id, kind, resource_id, status, data_json) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    lease.lease_id,
                    lease.run_id,
                    lease.kind.value,
                    lease.resource_id,
                    lease.status.value,
                    lease.model_dump_json(),
                ),
            )
            run = self._get_run(connection, lease.run_id)
            event_type = (
                "workspace.created" if lease.kind is LeaseKind.WORKTREE else "sandbox.created"
            )
            self._insert_event(
                connection,
                self._event_for_run(
                    run,
                    event_type,
                    {"lease_id": lease.lease_id, "resource_id": lease.resource_id},
                ),
            )
            connection.commit()

    def update_lease_status(self, lease_id: str, status: str) -> None:
        lease_status = LeaseStatus(status)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT data_json FROM resource_leases WHERE lease_id = ?", (lease_id,)
            ).fetchone()
            if row is None:
                raise _not_found("resource lease", lease_id)
            current = ResourceLease.model_validate_json(row["data_json"])
            if current.status is not LeaseStatus.ACTIVE:
                connection.commit()
                return
            updated = current.model_copy(
                update={"status": lease_status, "updated_at": self.clock.now()}
            )
            connection.execute(
                "UPDATE resource_leases SET status = ?, data_json = ? WHERE lease_id = ?",
                (lease_status.value, updated.model_dump_json(), lease_id),
            )
            run = self._get_run(connection, current.run_id)
            self._insert_event(
                connection,
                self._event_for_run(
                    run,
                    "workspace.cleaned"
                    if current.kind is LeaseKind.WORKTREE
                    else "sandbox.terminated",
                    {"lease_id": lease_id, "lease_status": lease_status.value},
                ),
            )
            connection.commit()

    def active_leases(self, run_id: str | None = None) -> Sequence[ResourceLease]:
        sql = "SELECT data_json FROM resource_leases WHERE status = ?"
        params: tuple[str, ...] = (LeaseStatus.ACTIVE.value,)
        if run_id is not None:
            sql += " AND run_id = ?"
            params = (LeaseStatus.ACTIVE.value, run_id)
        sql += " ORDER BY rowid"
        with self._connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [ResourceLease.model_validate_json(row["data_json"]) for row in rows]

    def count_executed_intents(self, run_id: str, action: str) -> int:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT data_json FROM tool_intents WHERE run_id = ? AND status = ?",
                (run_id, IntentStatus.EXECUTED.value),
            ).fetchall()
        return sum(
            StoredToolIntent.model_validate_json(row["data_json"]).intent.action == action
            for row in rows
        )

    def _event_for_run(
        self,
        run: Run,
        event_type: str,
        payload: dict[str, object],
        *,
        task_id: str | None = None,
    ) -> FleetEvent:
        cleaned, summary = self.redactor.redact_data(payload)
        return FleetEvent(
            event_id=self.ids.new(IdPrefix.EVENT),
            event_type=event_type,
            occurred_at=self.clock.now(),
            project_id=run.project_id,
            run_id=run.run_id,
            task_id=task_id or run.task_id,
            correlation_id=run.correlation_id,
            payload=cast(dict[str, JsonValue], jsonable(cleaned)),
            redaction_summary=summary,
        )

    def _event_for_intent(
        self, run: Run, intent: ToolIntent, event_type: str, payload: dict[str, object]
    ) -> FleetEvent:
        event = self._event_for_run(run, event_type, payload, task_id=intent.task_id)
        return event.model_copy(update={"agent_instance_id": intent.agent_instance_id})

    def _insert_event(self, connection: sqlite3.Connection, event: FleetEvent) -> FleetEvent:
        cleaned, summary = self.redactor.redact_data(event.payload)
        if event.run_id is None:
            row = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) AS sequence FROM run_events "
                "WHERE run_id IS NULL AND project_id = ?",
                (event.project_id,),
            ).fetchone()
        else:
            row = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) AS sequence FROM run_events WHERE run_id = ?",
                (event.run_id,),
            ).fetchone()
        persisted = event.model_copy(
            update={
                "sequence": int(row["sequence"]) + 1,
                "payload": cast(dict[str, JsonValue], jsonable(cleaned)),
                "redaction_summary": sorted(set(event.redaction_summary + summary)),
            }
        )
        connection.execute(
            "INSERT INTO run_events"
            "(event_id, project_id, run_id, sequence, event_type, occurred_at, data_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                persisted.event_id,
                persisted.project_id,
                persisted.run_id,
                persisted.sequence,
                persisted.event_type,
                persisted.occurred_at.isoformat(),
                persisted.model_dump_json(),
            ),
        )
        return persisted

    @staticmethod
    def _get_run(connection: sqlite3.Connection, run_id: str) -> Run:
        row = connection.execute(
            "SELECT data_json FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            raise _not_found("run", run_id)
        return Run.model_validate_json(row["data_json"])

    @staticmethod
    def _update_run(connection: sqlite3.Connection, run: Run) -> None:
        connection.execute(
            "UPDATE runs SET status = ?, stage = ?, data_json = ? WHERE run_id = ?",
            (
                run.status.value,
                run.stage.value if run.stage else None,
                run.model_dump_json(),
                run.run_id,
            ),
        )

    @staticmethod
    def _find_intent(
        connection: sqlite3.Connection, run_id: str, idempotency_key: str
    ) -> StoredToolIntent | None:
        row = connection.execute(
            "SELECT data_json FROM tool_intents WHERE run_id = ? AND idempotency_key = ?",
            (run_id, idempotency_key),
        ).fetchone()
        return StoredToolIntent.model_validate_json(row["data_json"]) if row is not None else None

    @staticmethod
    def _get_intent_by_id(connection: sqlite3.Connection, intent_id: str) -> StoredToolIntent:
        row = connection.execute(
            "SELECT data_json FROM tool_intents WHERE intent_id = ?", (intent_id,)
        ).fetchone()
        if row is None:
            raise _not_found("tool intent", intent_id)
        return StoredToolIntent.model_validate_json(row["data_json"])

    @staticmethod
    def _insert_intent(connection: sqlite3.Connection, stored: StoredToolIntent) -> None:
        connection.execute(
            "INSERT INTO tool_intents(intent_id, run_id, idempotency_key, intent_hash, status, "
            "approval_request_id, data_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                stored.intent.intent_id,
                stored.intent.run_id,
                stored.intent.idempotency_key,
                stored.intent_hash,
                stored.status.value,
                stored.approval_request_id,
                stored.model_dump_json(),
            ),
        )

    @staticmethod
    def _update_intent(connection: sqlite3.Connection, stored: StoredToolIntent) -> None:
        connection.execute(
            "UPDATE tool_intents SET status = ?, approval_request_id = ?, data_json = ? "
            "WHERE intent_id = ?",
            (
                stored.status.value,
                stored.approval_request_id,
                stored.model_dump_json(),
                stored.intent.intent_id,
            ),
        )

    @staticmethod
    def _get_approval(connection: sqlite3.Connection, request_id: str) -> ApprovalRequest:
        row = connection.execute(
            "SELECT data_json FROM approvals WHERE request_id = ?", (request_id,)
        ).fetchone()
        if row is None:
            raise _not_found("approval request", request_id)
        return ApprovalRequest.model_validate_json(row["data_json"])

    @staticmethod
    def _get_grant_for_request(
        connection: sqlite3.Connection, request_id: str
    ) -> CapabilityGrant | None:
        row = connection.execute(
            "SELECT data_json FROM capability_grants WHERE request_id = ?", (request_id,)
        ).fetchone()
        return CapabilityGrant.model_validate_json(row["data_json"]) if row is not None else None


def _not_found(kind: str, identifier: str) -> FleetError:
    return FleetError(
        ErrorCode.RESOURCE_NOT_FOUND,
        f"No {kind} exists with identifier {identifier}.",
        "Check the identifier with the relevant list or status command.",
        details={"kind": kind, "identifier": identifier},
    )


def _split_sql(script: str) -> list[str]:
    """Split bundled migration statements; migration SQL contains no trigger bodies."""

    return [statement.strip() for statement in script.split(";") if statement.strip()]
