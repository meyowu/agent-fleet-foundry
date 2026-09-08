"""SQLite state store with transactional transitions and append-only events."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from contextlib import suppress
from datetime import timedelta
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar, cast

from pydantic import JsonValue, ValidationError

from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.ids import IdPrefix
from agent_fleet.domain.models import (
    AgentInstance,
    AgentStatus,
    ApprovalChoice,
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
    SandboxExecutionRecoveryRequest,
    SandboxHandle,
    StoredToolIntent,
    StrictModel,
    TaskSpec,
    ToolIntent,
    jsonable,
)
from agent_fleet.domain.security import Redactor, canonical_json_hash
from agent_fleet.domain.workflow import validate_transition
from agent_fleet.ports.clock import Clock
from agent_fleet.ports.id_generator import IdGenerator

if TYPE_CHECKING:
    from agent_fleet.domain.evolution import OrganizationAdmission

SUPPORTED_SCHEMA_VERSION = 10

_StateModel = TypeVar("_StateModel", bound=StrictModel)


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
        from agent_fleet.adapters.persistence.evolution import assert_organization_project_write

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            assert_organization_project_write(connection, project, redactor=self.redactor)
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

    def create_run(
        self, run: Run, *, organization_admission: OrganizationAdmission | None = None
    ) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._insert_run_in_transaction(
                connection, run, organization_admission=organization_admission
            )
            connection.commit()

    def _insert_run_in_transaction(
        self,
        connection: sqlite3.Connection,
        run: Run,
        *,
        created_payload: dict[str, object] | None = None,
        organization_admission: OrganizationAdmission | None = None,
    ) -> None:
        """Reuse the canonical Run/event insertion inside an adapter-owned transaction."""
        from agent_fleet.adapters.persistence.evolution import (
            check_organization_admission,
            record_organization_admission,
        )

        run = self._decode_state_record(Run, run.model_dump_json(warnings=False))
        check_organization_admission(
            connection, run, organization_admission, redactor=self.redactor
        )
        connection.execute(
            "INSERT INTO runs(run_id, project_id, status, stage, data_json) VALUES (?, ?, ?, ?, ?)",
            (
                run.run_id,
                run.project_id,
                run.status.value,
                run.stage.value if run.stage else None,
                run.model_dump_json(),
            ),
        )
        record_organization_admission(
            connection, run, organization_admission, redactor=self.redactor
        )
        self._insert_event(
            connection,
            self._event_for_run(
                run,
                "run.created",
                {"goal": run.goal, "status": run.status.value, **(created_payload or {})},
            ),
        )

    def _decode_state_record(self, model: type[_StateModel], raw: str) -> _StateModel:
        """Bound and scan before parsing without retaining secret-bearing parse exceptions."""
        result: _StateModel | None = None
        if (
            isinstance(raw, str)
            and len(raw.encode("utf-8")) <= 1_048_576
            and not self.redactor.contains_secret_data(raw)
        ):
            with suppress(ValidationError, ValueError, TypeError):
                result = model.model_validate_json(raw)
        if result is None:
            raise FleetError(
                ErrorCode.RECOVERY_REQUIRED,
                "A durable state record is invalid or unsafe to inspect.",
                "Inspect the selected state safely before continuing its execution.",
            )
        return result

    def _validated_run(self, connection: sqlite3.Connection, run_id: str) -> Run:
        if self.redactor.contains_secret_data(run_id):
            raise FleetError(
                ErrorCode.RECOVERY_REQUIRED,
                "The durable Run identity is invalid.",
                "Use an exact recorded Run identity.",
            )
        row = connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise _not_found("run", run_id)
        run = self._decode_state_record(Run, row["data_json"])
        if (
            run.run_id != run_id
            or run.project_id != row["project_id"]
            or run.status.value != row["status"]
            or (run.stage.value if run.stage else None) != row["stage"]
        ):
            raise FleetError(
                ErrorCode.RECOVERY_REQUIRED,
                "The durable Run does not match its stored identity.",
                "Inspect its immutable registration before resuming.",
            )
        return run

    def _save_run_in_transaction(
        self,
        connection: sqlite3.Connection,
        run: Run,
        event_type: str,
        payload: dict[str, object],
    ) -> Run:
        run = self._decode_state_record(Run, run.model_dump_json(warnings=False))
        current = self._validated_run(connection, run.run_id)
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
        return run

    def get_run(self, run_id: str) -> Run:
        with self._connect() as connection:
            return self._validated_run(connection, run_id)

    def save_run(self, run: Run, event_type: str, payload: dict[str, object]) -> Run:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run = self._save_run_in_transaction(connection, run, event_type, payload)
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
                "DO UPDATE SET task_id=excluded.task_id, role=excluded.role, "
                "data_json=excluded.data_json",
                (
                    instance.agent_instance_id,
                    instance.run_id,
                    instance.task_id,
                    str(instance.role),
                    instance.model_dump_json(),
                ),
            )

    def get_agent_instance(self, agent_instance_id: str) -> AgentInstance:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM agent_instances WHERE agent_instance_id = ?", (agent_instance_id,)
            ).fetchone()
        if row is None:
            raise _not_found("agent instance", agent_instance_id)
        invalid = FleetError(
            ErrorCode.RECOVERY_REQUIRED,
            "The stored agent instance does not match its durable identity.",
            "Inspect the agent journal before resuming this run.",
        )
        try:
            agent = AgentInstance.model_validate_json(row["data_json"])
        except ValidationError:
            raise invalid from None
        if any(
            getattr(agent, field) != row[field]
            for field in ("agent_instance_id", "run_id", "task_id", "role")
        ):
            raise invalid
        return agent

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

    def list_events_after(
        self, run_id: str, *, after_sequence: int = 0, limit: int = 100
    ) -> Sequence[FleetEvent]:
        if (
            type(after_sequence) is not int
            or after_sequence < 0
            or type(limit) is not int
            or not 1 <= limit <= 100
        ):
            raise FleetError(
                ErrorCode.COMMAND_DENIED,
                "Event pagination requires a nonnegative cursor and a limit from 1 to 100.",
                "Use the last recorded sequence as the next cursor.",
            )
        with self._connect() as connection:
            run = self._validated_run(connection, run_id)
            rows = connection.execute(
                "SELECT * FROM run_events WHERE run_id = ? AND sequence > ? "
                "ORDER BY sequence LIMIT ?",
                (run_id, after_sequence, limit),
            ).fetchall()
            events: list[FleetEvent] = []
            previous = after_sequence
            for row in rows:
                event = self._decode_state_record(FleetEvent, row["data_json"])
                if (
                    event.run_id != run_id
                    or event.project_id != run.project_id
                    or event.sequence is None
                    or event.sequence <= previous
                    or any(
                        getattr(event, key) != row[key]
                        for key in ("event_id", "run_id", "project_id", "sequence", "event_type")
                    )
                    or event.occurred_at.isoformat() != row["occurred_at"]
                ):
                    raise FleetError(
                        ErrorCode.RECOVERY_REQUIRED,
                        "An event page does not match its durable Run journal.",
                        "Inspect the exact Run journal before continuing.",
                    )
                events.append(event)
                assert event.sequence is not None
                previous = event.sequence
            return events

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

    def get_intent(self, intent_id: str) -> StoredToolIntent:
        with self._connect() as connection:
            return self._get_intent_by_id(connection, intent_id)

    def claim_reserved_intent_for_dispatch(self, intent_id: str, intent_hash: str) -> bool:
        """Permanently claim one dispatch; a crash never makes its intent replayable.

        Policy validation and grant consumption belong to the caller. This final
        transactional fence only permits one caller to dispatch the exact reserved
        intent in its current active context. An existing exact claim returns False,
        even after completion or process restart; it is never a reusable lease.
        """
        invalid = FleetError(
            ErrorCode.RECOVERY_REQUIRED,
            "The dispatch claim does not match an active exact reserved intent.",
            "Inspect the persisted intent and execution journal before recovery; do not replay it.",
        )
        if self.redactor.contains_secret_data({"intent_id": intent_id, "intent_hash": intent_hash}):
            raise invalid
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM tool_intents WHERE intent_id = ?", (intent_id,)
            ).fetchone()
            if row is None:
                raise invalid
            try:
                stored = StoredToolIntent.model_validate_json(row["data_json"])
            except ValidationError:
                raise invalid from None
            intent = stored.intent
            if (
                intent.intent_id != intent_id
                or intent.run_id != row["run_id"]
                or intent.idempotency_key != row["idempotency_key"]
                or stored.intent_hash != row["intent_hash"]
                or stored.status.value != row["status"]
                or stored.approval_request_id != row["approval_request_id"]
                or stored.intent_hash != intent_hash
                or canonical_json_hash(intent.model_dump(mode="json")) != intent_hash
                or self.redactor.contains_secret_data(intent.model_dump(mode="json"))
            ):
                raise invalid
            existing = connection.execute(
                "SELECT intent_hash FROM tool_dispatch_claims WHERE intent_id = ?", (intent_id,)
            ).fetchone()
            if existing is not None:
                if existing["intent_hash"] != intent_hash:
                    raise invalid
                connection.commit()
                return False
            if stored.status is not IntentStatus.RESERVED:
                raise invalid
            run_row = connection.execute(
                "SELECT * FROM runs WHERE run_id = ?", (intent.run_id,)
            ).fetchone()
            task_row = connection.execute(
                "SELECT * FROM tasks WHERE task_id = ?", (intent.task_id,)
            ).fetchone()
            agent_row = connection.execute(
                "SELECT * FROM agent_instances WHERE agent_instance_id = ?",
                (intent.agent_instance_id,),
            ).fetchone()
            if run_row is None or task_row is None or agent_row is None:
                raise invalid
            try:
                run = Run.model_validate_json(run_row["data_json"])
                task = TaskSpec.model_validate_json(task_row["data_json"])
                agent = AgentInstance.model_validate_json(agent_row["data_json"])
            except ValidationError:
                raise invalid from None
            if (
                run.run_id != intent.run_id
                or run.project_id != run_row["project_id"]
                or run.status.value != run_row["status"]
                or run.stage is None
                or run.stage.value != run_row["stage"]
                or run.status is not RunStatus.RUNNING
                or run.pending_approval_id is not None
                or run.stage is not intent.stage
                or run.task_id != intent.task_id
                or task.task_id != intent.task_id
                or task.run_id != run.run_id
                or task_row["run_id"] != run.run_id
                or task.workflow != intent.workflow
                or agent.agent_instance_id != intent.agent_instance_id
                or agent.run_id != run.run_id
                or agent_row["run_id"] != run.run_id
                or agent.task_id != task.task_id
                or agent_row["task_id"] != task.task_id
                or agent.role != intent.principal_role
                or agent_row["role"] != intent.principal_role
                or agent.status is not AgentStatus.RUNNING
                or agent.completed_at is not None
            ):
                raise invalid
            connection.execute(
                "INSERT INTO tool_dispatch_claims(intent_id, intent_hash, claimed_at) "
                "VALUES (?, ?, ?)",
                (intent_id, intent_hash, self.clock.now().isoformat()),
            )
            self._insert_event(
                connection,
                self._event_for_intent(
                    run,
                    intent,
                    "intent.dispatch_claimed",
                    {"intent_id": intent_id, "intent_hash": intent_hash},
                ),
            )
            connection.commit()
            return True

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
        self,
        request_id: str,
        *,
        approve: bool,
        denial_reason: str | None,
        choice: ApprovalChoice = ApprovalChoice.ALLOW_ONCE,
        scope_sha256: str | None = None,
        source_rule_id: str | None = None,
    ) -> CapabilityGrant | None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            request = self._get_approval(connection, request_id)
            selected_choice = choice if approve else ApprovalChoice.DENY
            if request.status is not ApprovalStatus.PENDING:
                grant = self._get_grant_for_request(connection, request_id)
                if grant is not None:
                    self._validate_approval_binding(
                        connection,
                        request,
                        self._get_intent_by_id(connection, request.intent_id),
                        grant,
                    )
                resolved_choice = request.resolution_choice or (
                    ApprovalChoice.ALLOW_ONCE
                    if request.status is ApprovalStatus.APPROVED
                    else ApprovalChoice.DENY
                )
                if selected_choice is not resolved_choice or (
                    grant is not None
                    and (
                        grant.choice is not selected_choice
                        or grant.scope_sha256 != scope_sha256
                        or grant.source_rule_id != source_rule_id
                    )
                ):
                    raise self._invalid_approval(request_id)
                connection.commit()
                return grant
            now = self.clock.now()
            intent = self._get_intent_by_id(connection, request.intent_id)
            run = self._validate_approval_binding(connection, request, intent)
            if (
                selected_choice not in request.available_choices
                or run.status is not RunStatus.PAUSED_FOR_APPROVAL
                or run.pending_approval_id != request_id
                or run.stage is not intent.intent.stage
                or intent.status is not IntentStatus.PENDING_APPROVAL
            ):
                raise self._invalid_approval(request_id)
            if approve:
                expected_scope = (
                    canonical_json_hash(request.authorization_scope)
                    if request.authorization_scope is not None
                    else None
                )
                if (
                    request.expires_at <= now
                    or choice is ApprovalChoice.DENY
                    or expected_scope != scope_sha256
                    or (
                        choice in {ApprovalChoice.ALLOW_RUN, ApprovalChoice.ALLOW_ALWAYS}
                        and scope_sha256 is None
                    )
                    or (
                        request.source_rule_id is not None
                        and request.source_rule_id != source_rule_id
                    )
                ):
                    raise self._invalid_approval(request_id)
                resolved = request.model_copy(
                    update={
                        "status": ApprovalStatus.APPROVED,
                        "resolved_at": now,
                        "resolution_choice": choice,
                        "source_rule_id": source_rule_id,
                    }
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
                    expires_at=(
                        min(request.expires_at, now + timedelta(minutes=10))
                        if choice is ApprovalChoice.ALLOW_ONCE
                        else None
                    ),
                    choice=choice,
                    scope_sha256=scope_sha256,
                    source_rule_id=source_rule_id,
                    remaining_uses=1 if choice is ApprovalChoice.ALLOW_ONCE else None,
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
                        "resolution_choice": ApprovalChoice.DENY,
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
                    {
                        "request_id": request_id,
                        "resolution": resolved.status.value,
                        "choice": selected_choice.value,
                    },
                ),
            )
            if grant is not None:
                self._insert_event(
                    connection,
                    self._event_for_intent(
                        run,
                        intent.intent,
                        "capability.issued",
                        {
                            "grant_id": grant.grant_id,
                            "remaining_uses": grant.remaining_uses,
                            "choice": grant.choice.value,
                            "scope_sha256": grant.scope_sha256,
                            "source_rule_id": grant.source_rule_id,
                        },
                    ),
                )
            connection.commit()
            return grant

    def consume_grant_and_reserve(self, request_id: str, intent_hash: str) -> StoredToolIntent:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            request = self._get_approval(connection, request_id)
            intent = self._get_intent_by_id(connection, request.intent_id)
            grant = self._get_grant_for_request(connection, request_id)
            if grant is None:
                raise self._invalid_approval(request_id)
            run = self._validate_approval_binding(connection, request, intent, grant)
            self._validate_active_grant(run, request, grant, intent.intent)
            if (
                grant.intent_hash != intent_hash
                or request.intent_hash != intent_hash
                or intent.intent_hash != intent_hash
            ):
                raise self._invalid_approval(request_id)
            if intent.status in {IntentStatus.RESERVED, IntentStatus.EXECUTED}:
                connection.commit()
                return intent
            if intent.status is not IntentStatus.PENDING_APPROVAL:
                raise self._invalid_approval(request_id)
            reserved = intent.model_copy(update={"status": IntentStatus.RESERVED})
            self._consume_grant(connection, run, grant, intent.intent)
            self._update_intent(connection, reserved)
            connection.commit()
            return reserved

    def list_grants(self, run_id: str) -> list[CapabilityGrant]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT grant_id FROM capability_grants WHERE run_id = ? ORDER BY rowid",
                (run_id,),
            ).fetchall()
            grants = [self._get_grant(connection, row["grant_id"]) for row in rows]
            if any(grant.run_id != run_id for grant in grants):
                raise self._invalid_approval("grant-list-binding")
            return grants

    def list_project_grants(self, project_id: str) -> list[CapabilityGrant]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT g.grant_id FROM capability_grants g JOIN runs r ON r.run_id = g.run_id "
                "WHERE r.project_id = ? ORDER BY g.rowid",
                (project_id,),
            ).fetchall()
            grants = [self._get_grant(connection, row["grant_id"]) for row in rows]
            if any(grant.project_id != project_id for grant in grants):
                raise self._invalid_approval("grant-list-binding")
            return grants

    def get_grant(self, grant_id: str) -> CapabilityGrant:
        with self._connect() as connection:
            return self._get_grant(connection, grant_id)

    def revoke_grant(self, grant_id: str) -> CapabilityGrant:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            grant = self._get_grant(connection, grant_id)
            if grant.revoked_at is not None:
                connection.commit()
                return grant
            revoked = grant.model_copy(update={"revoked_at": self.clock.now()})
            self._update_grant(connection, revoked)
            run = self._get_run(connection, grant.run_id)
            self._insert_event(
                connection,
                self._event_for_run(run, "capability.revoked", {"grant_id": grant_id}),
            )
            connection.commit()
            return revoked

    def consume_matching_grant_and_reserve(
        self, grant_id: str, intent: ToolIntent, intent_hash: str, scope_sha256: str
    ) -> StoredToolIntent:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            grant = self._get_grant(connection, grant_id)
            if grant.request_id is None:
                raise self._invalid_approval(None)
            request = self._get_approval(connection, grant.request_id)
            source = self._get_intent_by_id(connection, grant.intent_id)
            run = self._validate_approval_binding(connection, request, source, grant)
            self._validate_active_grant(run, request, grant, intent)
            self._validate_intent_context(connection, run, intent)
            if (
                run.status is not RunStatus.RUNNING
                or grant.scope_sha256 != scope_sha256
                or canonical_json_hash(intent.model_dump(mode="json")) != intent_hash
                or intent.run_id != source.intent.run_id
                or intent.task_id != source.intent.task_id
                or intent.principal_role != source.intent.principal_role
                or intent.workflow != source.intent.workflow
                or intent.stage is not source.intent.stage
                or intent.action != source.intent.action
                or intent.resource != source.intent.resource
                or intent.parameters != source.intent.parameters
                or intent.side_effect != source.intent.side_effect
                or (
                    grant.choice is ApprovalChoice.ALLOW_ONCE
                    and (intent != source.intent or intent_hash != source.intent_hash)
                )
            ):
                raise self._invalid_approval(request.request_id)
            existing = self._find_intent(connection, intent.run_id, intent.idempotency_key)
            if existing is not None:
                if (
                    existing.intent != intent
                    or existing.intent_hash != intent_hash
                    or existing.approval_request_id != grant.request_id
                    or existing.status not in {IntentStatus.RESERVED, IntentStatus.EXECUTED}
                ):
                    raise self._invalid_approval(request.request_id)
                connection.commit()
                return existing
            if grant.choice is ApprovalChoice.ALLOW_ONCE:
                raise self._invalid_approval(request.request_id)
            if (
                connection.execute(
                    "SELECT 1 FROM tool_intents WHERE intent_id = ?", (intent.intent_id,)
                ).fetchone()
                is not None
            ):
                raise self._invalid_approval(request.request_id)
            reserved = StoredToolIntent(
                intent=intent,
                intent_hash=intent_hash,
                status=IntentStatus.RESERVED,
                approval_request_id=grant.request_id,
            )
            self._consume_grant(connection, run, grant, intent)
            self._insert_intent(connection, reserved)
            self._insert_event(
                connection,
                self._event_for_intent(
                    run, intent, "tool.intent_created", {"action": intent.action}
                ),
            )
            connection.commit()
            return reserved

    def reserve_trust_rule_intent(
        self,
        intent: ToolIntent,
        intent_hash: str,
        scope_sha256: str,
        source_rule_id: str,
    ) -> StoredToolIntent:
        """Record one current-policy-authorized action without inventing an approval.

        The broker must revalidate the exact user-owned rule before this call.
        This transaction records provenance and reservation; it never evaluates
        a rule, widens its scope, or issues a reusable capability.
        """
        if self.redactor.contains_secret_data(
            {
                "intent": intent.model_dump(mode="json"),
                "scope_sha256": scope_sha256,
                "source_rule_id": source_rule_id,
            }
        ):
            raise self._invalid_approval(None)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run = self._get_run(connection, intent.run_id)
            self._validate_intent_context(connection, run, intent)
            if (
                run.status is not RunStatus.RUNNING
                or run.pending_approval_id is not None
                or run.stage is not intent.stage
                or canonical_json_hash(intent.model_dump(mode="json")) != intent_hash
            ):
                raise self._invalid_approval(None)
            existing = self._find_intent(connection, intent.run_id, intent.idempotency_key)
            if existing is not None:
                row = connection.execute(
                    "SELECT grant_id FROM capability_grants WHERE intent_id = ?",
                    (existing.intent.intent_id,),
                ).fetchone()
                if row is None:
                    raise self._invalid_approval(None)
                receipt = self._get_grant(connection, row["grant_id"])
                if (
                    existing.intent != intent
                    or existing.intent_hash != intent_hash
                    or existing.approval_request_id is not None
                    or existing.status not in {IntentStatus.RESERVED, IntentStatus.EXECUTED}
                    or receipt.request_id is not None
                    or receipt.choice is not ApprovalChoice.ALLOW_ALWAYS
                    or receipt.source_rule_id != source_rule_id
                    or receipt.scope_sha256 != scope_sha256
                    or receipt.intent_id != intent.intent_id
                    or receipt.intent_hash != intent_hash
                    or receipt.project_id != run.project_id
                    or receipt.run_id != run.run_id
                    or receipt.task_id != intent.task_id
                    or receipt.agent_instance_id != intent.agent_instance_id
                    or receipt.principal_role != intent.principal_role
                    or receipt.action != intent.action
                    or receipt.resource != intent.resource
                    or receipt.remaining_uses != 0
                    or receipt.consumed_at is None
                    or receipt.revoked_at is not None
                    or (receipt.expires_at is not None and receipt.expires_at <= self.clock.now())
                ):
                    raise self._invalid_approval(None)
                connection.commit()
                return existing
            if (
                connection.execute(
                    "SELECT 1 FROM tool_intents WHERE intent_id = ?", (intent.intent_id,)
                ).fetchone()
                is not None
            ):
                raise self._invalid_approval(None)
            now = self.clock.now()
            try:
                receipt = CapabilityGrant(
                    grant_id=self.ids.new(IdPrefix.GRANT),
                    intent_id=intent.intent_id,
                    project_id=run.project_id,
                    run_id=run.run_id,
                    task_id=intent.task_id,
                    agent_instance_id=intent.agent_instance_id,
                    principal_role=intent.principal_role,
                    action=intent.action,
                    resource=intent.resource,
                    intent_hash=intent_hash,
                    issued_at=now,
                    choice=ApprovalChoice.ALLOW_ALWAYS,
                    scope_sha256=scope_sha256,
                    source_rule_id=source_rule_id,
                    remaining_uses=0,
                    consumed_at=now,
                )
            except ValidationError:
                raise self._invalid_approval(None) from None
            reserved = StoredToolIntent(
                intent=intent, intent_hash=intent_hash, status=IntentStatus.RESERVED
            )
            self._insert_intent(connection, reserved)
            connection.execute(
                "INSERT INTO capability_grants "
                "(grant_id, request_id, intent_id, run_id, remaining_uses, data_json) "
                "VALUES (?, NULL, ?, ?, 0, ?)",
                (receipt.grant_id, intent.intent_id, run.run_id, receipt.model_dump_json()),
            )
            self._insert_event(
                connection,
                self._event_for_intent(
                    run, intent, "tool.intent_created", {"action": intent.action}
                ),
            )
            for event_type in ("capability.issued", "capability.consumed"):
                self._insert_event(
                    connection,
                    self._event_for_intent(
                        run,
                        intent,
                        event_type,
                        {
                            "grant_id": receipt.grant_id,
                            "intent_id": intent.intent_id,
                            "choice": receipt.choice.value,
                            "remaining_uses": 1 if event_type == "capability.issued" else 0,
                            "source_rule_id": source_rule_id,
                            "scope_sha256": scope_sha256,
                        },
                    ),
                )
            connection.commit()
            return reserved

    def _validate_approval_binding(
        self,
        connection: sqlite3.Connection,
        request: ApprovalRequest,
        source: StoredToolIntent,
        grant: CapabilityGrant | None = None,
    ) -> Run:
        intent = source.intent
        run = self._get_run(connection, request.run_id)
        self._validate_intent_context(connection, run, intent)
        if (
            request.intent_id != intent.intent_id
            or request.run_id != intent.run_id
            or source.approval_request_id != request.request_id
            or request.intent_hash != source.intent_hash
            or source.intent_hash != canonical_json_hash(intent.model_dump(mode="json"))
            or request.principal_role != intent.principal_role
            or request.action != intent.action
            or request.resource != intent.resource
        ):
            raise self._invalid_approval(request.request_id)
        if grant is not None and (
            grant.request_id != request.request_id
            or grant.intent_id != intent.intent_id
            or grant.project_id != run.project_id
            or grant.run_id != run.run_id
            or grant.task_id != intent.task_id
            or grant.agent_instance_id != intent.agent_instance_id
            or grant.principal_role != intent.principal_role
            or grant.action != intent.action
            or grant.resource != intent.resource
            or grant.intent_hash != source.intent_hash
            or grant.source_rule_id != request.source_rule_id
            or grant.choice != (request.resolution_choice or ApprovalChoice.ALLOW_ONCE)
            or grant.scope_sha256
            != (
                canonical_json_hash(request.authorization_scope)
                if request.authorization_scope is not None
                else None
            )
        ):
            raise self._invalid_approval(request.request_id)
        return run

    @staticmethod
    def _validate_intent_context(
        connection: sqlite3.Connection, run: Run, intent: ToolIntent
    ) -> None:
        task_row = connection.execute(
            "SELECT data_json FROM tasks WHERE task_id = ?", (intent.task_id,)
        ).fetchone()
        agent_row = connection.execute(
            "SELECT data_json FROM agent_instances WHERE agent_instance_id = ?",
            (intent.agent_instance_id,),
        ).fetchone()
        if task_row is None or agent_row is None:
            raise SqliteStateStore._invalid_approval("unbound-intent")
        task = TaskSpec.model_validate_json(task_row["data_json"])
        agent = AgentInstance.model_validate_json(agent_row["data_json"])
        if (
            run.run_id != intent.run_id
            or run.task_id != intent.task_id
            or task.task_id != intent.task_id
            or task.run_id != run.run_id
            or task.workflow != intent.workflow
            or agent.agent_instance_id != intent.agent_instance_id
            or agent.run_id != run.run_id
            or agent.task_id != task.task_id
            or agent.role != intent.principal_role
        ):
            raise SqliteStateStore._invalid_approval("unbound-intent")

    def _validate_active_grant(
        self, run: Run, request: ApprovalRequest, grant: CapabilityGrant, intent: ToolIntent
    ) -> None:
        if (
            request.status is not ApprovalStatus.APPROVED
            or grant.choice not in request.available_choices
            or grant.revoked_at is not None
            or (grant.expires_at is not None and grant.expires_at <= self.clock.now())
            or run.stage is not intent.stage
            or run.status not in {RunStatus.RUNNING, RunStatus.PAUSED_FOR_APPROVAL}
            or (run.status is RunStatus.RUNNING and run.pending_approval_id is not None)
            or (
                run.status is RunStatus.PAUSED_FOR_APPROVAL
                and run.pending_approval_id != request.request_id
            )
        ):
            raise self._invalid_approval(request.request_id)

    def _consume_grant(
        self, connection: sqlite3.Connection, run: Run, grant: CapabilityGrant, intent: ToolIntent
    ) -> None:
        if grant.remaining_uses is not None and grant.remaining_uses <= 0:
            raise self._invalid_approval(grant.request_id)
        consumed = grant.model_copy(
            update={
                "remaining_uses": (
                    grant.remaining_uses - 1 if grant.remaining_uses is not None else None
                ),
                "consumed_at": self.clock.now(),
            }
        )
        self._update_grant(connection, consumed)
        self._insert_event(
            connection,
            self._event_for_intent(
                run,
                intent,
                "capability.consumed",
                {"grant_id": grant.grant_id, "intent_id": intent.intent_id},
            ),
        )

    @staticmethod
    def _get_grant(connection: sqlite3.Connection, grant_id: str) -> CapabilityGrant:
        row = connection.execute(
            "SELECT g.*, r.project_id AS owning_project_id FROM capability_grants g "
            "JOIN runs r ON r.run_id = g.run_id WHERE g.grant_id = ?",
            (grant_id,),
        ).fetchone()
        if row is None:
            raise _not_found("capability grant", grant_id)
        return SqliteStateStore._grant_from_row(row)

    @staticmethod
    def _grant_from_row(row: sqlite3.Row) -> CapabilityGrant:
        grant = CapabilityGrant.model_validate_json(row["data_json"])
        if (
            any(
                getattr(grant, field) != row[field]
                for field in ("grant_id", "request_id", "intent_id", "run_id", "remaining_uses")
            )
            or grant.project_id != row["owning_project_id"]
        ):
            raise SqliteStateStore._invalid_approval(grant.request_id)
        return grant

    @staticmethod
    def _update_grant(connection: sqlite3.Connection, grant: CapabilityGrant) -> None:
        connection.execute(
            "UPDATE capability_grants SET remaining_uses = ?, data_json = ? WHERE grant_id = ?",
            (grant.remaining_uses, grant.model_dump_json(), grant.grant_id),
        )

    @staticmethod
    def _invalid_approval(request_id: str | None) -> FleetError:
        return FleetError(
            ErrorCode.APPROVAL_INVALID,
            "The capability does not match the current exact authorization context.",
            "Inspect the request, scope, expiry, revocation, and run state before retrying.",
            details={"request_id": request_id},
        )

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
            for event_type in _lease_event_types(lease.kind, lease.status):
                self._insert_event(
                    connection,
                    self._event_for_run(
                        run,
                        event_type,
                        {"lease_id": lease.lease_id, "resource_id": lease.resource_id},
                    ),
                )
            connection.commit()

    def get_lease(self, lease_id: str) -> ResourceLease:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT data_json FROM resource_leases WHERE lease_id = ?", (lease_id,)
            ).fetchone()
        if row is None:
            raise _not_found("resource lease", lease_id)
        return ResourceLease.model_validate_json(row["data_json"])

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
            if current.status is lease_status:
                connection.commit()
                return
            _validate_lease_transition(current.status, lease_status)
            updated = current.model_copy(
                update={"status": lease_status, "updated_at": self.clock.now()}
            )
            connection.execute(
                "UPDATE resource_leases SET status = ?, data_json = ? WHERE lease_id = ?",
                (lease_status.value, updated.model_dump_json(), lease_id),
            )
            run = self._get_run(connection, current.run_id)
            for event_type in _lease_event_types(current.kind, lease_status):
                self._insert_event(
                    connection,
                    self._event_for_run(
                        run,
                        event_type,
                        {"lease_id": lease_id, "lease_status": lease_status.value},
                    ),
                )
            connection.commit()

    def mark_execution_creation_dispatched(self, lease_id: str) -> ResourceLease:
        """Persist the one-way Docker-create dispatch checkpoint before side effects."""

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT data_json FROM resource_leases WHERE lease_id = ?", (lease_id,)
            ).fetchone()
            if row is None:
                raise _not_found("resource lease", lease_id)
            current = ResourceLease.model_validate_json(row["data_json"])
            raw_sandbox = current.metadata.get("sandbox_handle")
            if (
                current.kind is not LeaseKind.EXECUTION
                or current.status is not LeaseStatus.CREATING
                or current.metadata.get("creation_dispatched") is not False
                or not isinstance(raw_sandbox, dict)
            ):
                raise FleetError(
                    ErrorCode.RECOVERY_REQUIRED,
                    "Execution creation dispatch checkpoint is not in its reserved state.",
                    "Do not dispatch or replay the execution; inspect its persisted lease.",
                    details={"lease_id": lease_id},
                )
            try:
                sandbox = SandboxHandle.model_validate(raw_sandbox)
                recovery = SandboxExecutionRecoveryRequest.model_validate(
                    {
                        "execution_id": current.resource_id,
                        "sandbox_id": sandbox.sandbox_id,
                        "run_id": current.run_id,
                        "project_id": current.metadata.get("project_id"),
                        "provider": current.metadata.get("provider"),
                        "intent_id": current.metadata.get("intent_id"),
                        "task_id": current.metadata.get("task_id"),
                        "agent_instance_id": current.metadata.get("agent_instance_id"),
                        "stage": current.metadata.get("stage"),
                        "creation_dispatched": False,
                    }
                )
            except ValueError as error:
                raise FleetError(
                    ErrorCode.RECOVERY_REQUIRED,
                    "Execution creation dispatch binding is incomplete or malformed.",
                    "Do not dispatch the execution; inspect its persisted lease.",
                    details={"lease_id": lease_id},
                ) from error
            if (
                recovery.sandbox_id != sandbox.sandbox_id
                or recovery.run_id != sandbox.run_id
                or recovery.project_id != sandbox.project_id
                or recovery.provider != sandbox.provider
            ):
                raise FleetError(
                    ErrorCode.RECOVERY_REQUIRED,
                    "Execution creation dispatch binding does not match its sandbox.",
                    "Do not dispatch the execution; inspect its persisted lease.",
                    details={"lease_id": lease_id},
                )
            metadata = dict(current.metadata)
            metadata["schema_version"] = 2
            metadata["creation_dispatched"] = True
            updated = ResourceLease.model_validate(
                current.model_copy(
                    update={
                        "metadata": metadata,
                        "updated_at": self.clock.now(),
                    }
                ).model_dump(mode="json")
            )
            connection.execute(
                "UPDATE resource_leases SET data_json = ? WHERE lease_id = ?",
                (updated.model_dump_json(), lease_id),
            )
            run = self._get_run(connection, current.run_id)
            self._insert_event(
                connection,
                self._event_for_run(
                    run,
                    "sandbox.exec_dispatch_recorded",
                    {
                        "lease_id": lease_id,
                        "execution_id": current.resource_id,
                    },
                ),
            )
            connection.commit()
            return updated

    def activate_lease(self, lease_id: str, metadata: dict[str, object]) -> ResourceLease:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT data_json FROM resource_leases WHERE lease_id = ?", (lease_id,)
            ).fetchone()
            if row is None:
                raise _not_found("resource lease", lease_id)
            current = ResourceLease.model_validate_json(row["data_json"])
            _validate_lease_transition(current.status, LeaseStatus.ACTIVE)
            cleaned, _ = self.redactor.redact_data(metadata)
            updated = current.model_copy(
                update={
                    "status": LeaseStatus.ACTIVE,
                    "metadata": cast(dict[str, JsonValue], cleaned),
                    "updated_at": self.clock.now(),
                }
            )
            # Revalidate after model_copy because Pydantic does not validate updates.
            updated = ResourceLease.model_validate(updated.model_dump(mode="json"))
            connection.execute(
                "UPDATE resource_leases SET status = ?, data_json = ? WHERE lease_id = ?",
                (LeaseStatus.ACTIVE.value, updated.model_dump_json(), lease_id),
            )
            run = self._get_run(connection, current.run_id)
            for event_type in _lease_event_types(current.kind, LeaseStatus.ACTIVE):
                self._insert_event(
                    connection,
                    self._event_for_run(
                        run,
                        event_type,
                        {
                            "lease_id": lease_id,
                            "resource_id": current.resource_id,
                        },
                    ),
                )
            connection.commit()
            return updated

    def finalize_lease(
        self,
        lease_id: str,
        status: str,
        metadata: dict[str, object],
    ) -> ResourceLease:
        lease_status = LeaseStatus(status)
        if lease_status not in {LeaseStatus.RELEASED, LeaseStatus.RECOVERED}:
            raise ValueError("lease finalization requires a successful terminal status")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT data_json FROM resource_leases WHERE lease_id = ?", (lease_id,)
            ).fetchone()
            if row is None:
                raise _not_found("resource lease", lease_id)
            current = ResourceLease.model_validate_json(row["data_json"])
            cleaned, _ = self.redactor.redact_data(metadata)
            terminal_metadata = cast(dict[str, JsonValue], cleaned)
            if current.status is lease_status:
                if current.metadata != terminal_metadata:
                    raise FleetError(
                        ErrorCode.RECOVERY_REQUIRED,
                        "A terminal resource lease was finalized with different metadata.",
                        "Inspect the lease audit trail; do not replay the resource action.",
                    )
                connection.commit()
                return current
            _validate_lease_transition(current.status, lease_status)
            updated = ResourceLease.model_validate(
                current.model_copy(
                    update={
                        "status": lease_status,
                        "metadata": terminal_metadata,
                        "updated_at": self.clock.now(),
                    }
                ).model_dump(mode="json")
            )
            connection.execute(
                "UPDATE resource_leases SET status = ?, data_json = ? WHERE lease_id = ?",
                (lease_status.value, updated.model_dump_json(), lease_id),
            )
            run = self._get_run(connection, current.run_id)
            metadata_hash = canonical_json_hash(terminal_metadata)
            for event_type in _lease_event_types(current.kind, lease_status):
                self._insert_event(
                    connection,
                    self._event_for_run(
                        run,
                        event_type,
                        {
                            "lease_id": lease_id,
                            "lease_status": lease_status.value,
                            "terminal_metadata_sha256": metadata_hash,
                        },
                    ),
                )
            connection.commit()
            return updated

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

    def list_leases(self, run_id: str) -> Sequence[ResourceLease]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT data_json FROM resource_leases WHERE run_id = ? ORDER BY rowid",
                (run_id,),
            ).fetchall()
        return [ResourceLease.model_validate_json(row["data_json"]) for row in rows]

    def outstanding_leases(self, run_id: str | None = None) -> Sequence[ResourceLease]:
        terminal = (LeaseStatus.RELEASED.value, LeaseStatus.RECOVERED.value)
        sql = "SELECT data_json FROM resource_leases WHERE status NOT IN (?, ?)"
        params: tuple[str, ...] = terminal
        if run_id is not None:
            sql += " AND run_id = ?"
            params = (*terminal, run_id)
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
            "SELECT g.*, r.project_id AS owning_project_id FROM capability_grants g "
            "JOIN runs r ON r.run_id = g.run_id WHERE g.request_id = ?",
            (request_id,),
        ).fetchone()
        return SqliteStateStore._grant_from_row(row) if row is not None else None


def _validate_lease_transition(current: LeaseStatus, target: LeaseStatus) -> None:
    allowed: dict[LeaseStatus, frozenset[LeaseStatus]] = {
        LeaseStatus.CREATING: frozenset(
            {
                LeaseStatus.ACTIVE,
                LeaseStatus.RELEASING,
                LeaseStatus.RELEASED,
                LeaseStatus.RECOVERED,
                LeaseStatus.FAILED,
            }
        ),
        LeaseStatus.ACTIVE: frozenset(
            {
                LeaseStatus.RELEASING,
                LeaseStatus.RELEASED,
                LeaseStatus.RECOVERED,
                LeaseStatus.FAILED,
            }
        ),
        LeaseStatus.RELEASING: frozenset(
            {LeaseStatus.RELEASED, LeaseStatus.RECOVERED, LeaseStatus.FAILED}
        ),
        LeaseStatus.FAILED: frozenset({LeaseStatus.RELEASING, LeaseStatus.RECOVERED}),
        LeaseStatus.RELEASED: frozenset(),
        LeaseStatus.RECOVERED: frozenset(),
    }
    if target not in allowed[current]:
        raise FleetError(
            ErrorCode.RECOVERY_REQUIRED,
            f"Invalid resource lease transition: {current.value} -> {target.value}.",
            "Inspect the resource lease and use the recovery path instead of reopening it.",
            details={"current_status": current.value, "target_status": target.value},
        )


def _lease_event_types(kind: LeaseKind, status: LeaseStatus) -> tuple[str, ...]:
    if kind is LeaseKind.EXECUTION:
        return {
            LeaseStatus.CREATING: ("sandbox.exec_started",),
            LeaseStatus.ACTIVE: ("sandbox.inspected",),
            LeaseStatus.RELEASING: ("sandbox.cleanup_started",),
            LeaseStatus.RELEASED: ("sandbox.exec_finished", "sandbox.cleaned"),
            LeaseStatus.RECOVERED: ("sandbox.recovered",),
            LeaseStatus.FAILED: ("sandbox.exec_failed",),
        }[status]
    subject = {
        LeaseKind.WORKTREE: "workspace",
        LeaseKind.SANDBOX: "sandbox",
    }[kind]
    suffix = {
        LeaseStatus.CREATING: "create_started",
        LeaseStatus.ACTIVE: "created",
        LeaseStatus.RELEASING: "cleanup_started",
        LeaseStatus.RELEASED: "cleaned",
        LeaseStatus.RECOVERED: "recovered",
        LeaseStatus.FAILED: "cleanup_failed",
    }[status]
    events = [f"{subject}.{suffix}"]
    if kind is LeaseKind.SANDBOX and status is LeaseStatus.ACTIVE:
        events.append("sandbox.inspected")
    return tuple(events)


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
