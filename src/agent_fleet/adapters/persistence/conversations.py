"""Atomic conversation registration, immutable bindings and explicit ownership fences."""

from __future__ import annotations

import hashlib
import re
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from typing import Literal, TypeVar

from pydantic import JsonValue, ValidationError

from agent_fleet.adapters.persistence.sqlite import SUPPORTED_SCHEMA_VERSION, SqliteStateStore
from agent_fleet.domain.budgets import RunBudgetLimits
from agent_fleet.domain.conversation import (
    Conversation,
    ConversationArtifactRef,
    ConversationClaim,
    ConversationContextEntry,
    ConversationRegistration,
    ConversationRunBinding,
    ConversationSubmission,
    ConversationSummary,
    ConversationTurn,
    ConversationTurnStatus,
)
from agent_fleet.domain.errors import ConversationOwnershipUnavailableError, ErrorCode, FleetError
from agent_fleet.domain.graph import GraphChildBinding, GraphSnapshot
from agent_fleet.domain.ids import IdPrefix
from agent_fleet.domain.models import (
    ArtifactMetadata,
    FleetEvent,
    Project,
    ResourceLease,
    Run,
    RunStatus,
    StrictModel,
)
from agent_fleet.domain.security import Redactor, canonical_json_hash
from agent_fleet.domain.workflow import is_terminal
from agent_fleet.ports.clock import Clock
from agent_fleet.ports.id_generator import IdGenerator

_Model = TypeVar("_Model", bound=StrictModel)
_ACTIVE = {
    ConversationTurnStatus.RUNNING,
    ConversationTurnStatus.WAITING,
    ConversationTurnStatus.RECOVERY_REQUIRED,
}
_SETTLED = {
    ConversationTurnStatus.DELIVERED,
    ConversationTurnStatus.FAILED,
    ConversationTurnStatus.CANCELLED,
}
_RUN_IDENTITY = (
    "run_id",
    "project_id",
    "correlation_id",
    "goal",
    "base_revision",
    "target_status_fingerprint",
    "runtime_name",
    "provider_model",
    "credential_ref",
    "sandbox_name",
    "sandbox_configuration",
    "sandbox_configuration_hash",
    "sandbox_requirements",
    "sandbox_capabilities_snapshot",
    "sandbox_capabilities_hash",
    "sandbox_image_identity",
    "sandbox_daemon_identity",
    "unsafe_local_confirmed",
    "fake_scenario",
    "max_repair_iterations",
    "created_at",
    "parent_run_id",
    "parent_plan_sha256",
    "parent_node_id",
    "parent_iteration",
)


def _invalid() -> FleetError:
    return FleetError(
        ErrorCode.RECOVERY_REQUIRED,
        "The durable conversation identity, history, or ownership is inconsistent.",
        "Inspect the exact conversation and Run; do not replay uncertain work.",
    )


def _denied() -> FleetError:
    return FleetError(
        ErrorCode.COMMAND_DENIED,
        "The conversation submission or bounded context cannot be accepted.",
        "Inspect the current turn and reuse its exact submission key "
        "or select another conversation.",
    )


def _boundary[**Params, Result](operation: Callable[Params, Result]) -> Callable[Params, Result]:
    @wraps(operation)
    def call(*args: Params.args, **kwargs: Params.kwargs) -> Result:
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
                "The durable conversation store is unavailable.",
                "Restore the selected local state before starting or resuming a turn.",
            )
        error.__context__ = None
        raise error from None

    return call


def _run_hash(run: Run) -> str:
    value = run.model_dump(mode="json", warnings=False)
    return canonical_json_hash({key: value[key] for key in _RUN_IDENTITY})


def _goal_hash(run: Run) -> str:
    return hashlib.sha256(run.goal.encode("utf-8")).hexdigest()


def _submission_hash(
    submission: ConversationSubmission, run: Run, config_hash: str, limits: RunBudgetLimits
) -> str:
    return canonical_json_hash(
        {
            "project_id": submission.project_id,
            "conversation_id": submission.conversation_id,
            "user_goal_sha256": _goal_hash(run),
            "context_sha256": submission.context.context_sha256,
            "user_summary": submission.user_summary.model_dump(mode="json"),
            "budget_limits": limits.model_dump(mode="json"),
            "config_snapshot_sha256": config_hash,
        }
    )


class SqliteConversationStore:
    def __init__(
        self,
        database_path: Path,
        clock: Clock,
        ids: IdGenerator,
        redactor: Redactor,
        state: SqliteStateStore,
    ) -> None:
        self.database_path = database_path
        self.clock = clock
        self.ids = ids
        self.redactor = redactor
        self.state = state

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        if self.database_path.absolute() != self.state.database_path.absolute():
            raise _invalid()
        connection = sqlite3.connect(f"{self.database_path.absolute().as_uri()}?mode=rw", uri=True)
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
            if (
                not versions
                or not 7 <= versions[-1] <= SUPPORTED_SCHEMA_VERSION
                or versions != list(range(1, versions[-1] + 1))
            ):
                raise _invalid()
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _clean(self, value: object) -> None:
        if self.redactor.contains_secret_data(value):
            raise _invalid()

    def _identifier(self, value: str, prefix: str) -> None:
        if not isinstance(value, str) or re.fullmatch(prefix + r"_[0-9a-f]{32}", value) is None:
            raise _invalid()
        self._clean(value)

    def _decode(self, model: type[_Model], value: str) -> _Model:
        self._clean(value)
        if not isinstance(value, str) or len(value.encode("utf-8")) > 1_048_576:
            raise _invalid()
        return model.model_validate_json(value)

    def _validated(self, model: type[_Model], value: _Model) -> _Model:
        data = value.model_dump(mode="json", warnings=False)
        self._clean(data)
        return model.model_validate(data)

    def _project(self, connection: sqlite3.Connection, project_id: str) -> Project:
        self._identifier(project_id, "prj")
        row = connection.execute(
            "SELECT * FROM projects WHERE project_id=?", (project_id,)
        ).fetchone()
        if row is None:
            raise _invalid()
        project = self._decode(Project, row["data_json"])
        if project.project_id != project_id or project.canonical_root != row["canonical_root"]:
            raise _invalid()
        return project

    def _event(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        run_id: str | None,
        event_type: str,
        record_type: str,
        record_id: str,
        value: object,
    ) -> str:
        self._clean(value)
        run = self.state._validated_run(connection, run_id) if run_id else None
        event = FleetEvent(
            event_id=self.ids.new(IdPrefix.EVENT),
            event_type=event_type,
            occurred_at=self.clock.now(),
            project_id=project_id,
            run_id=run_id,
            task_id=run.task_id if run else None,
            correlation_id=run.correlation_id if run else self.ids.new(IdPrefix.CORRELATION),
            payload={
                "record_type": record_type,
                "record_id": record_id,
                "record_sha256": canonical_json_hash(value),
            },
        )
        return self.state._insert_event(connection, event).event_id

    def _receipt(
        self,
        connection: sqlite3.Connection,
        event_id: str,
        project_id: str,
        run_id: str | None,
        record_type: str,
        record_id: str,
        value: object,
    ) -> None:
        row = connection.execute(
            "SELECT * FROM run_events WHERE event_id=?", (event_id,)
        ).fetchone()
        if row is None:
            raise _invalid()
        event = self._decode(FleetEvent, row["data_json"])
        if (
            event.project_id != project_id
            or event.run_id != run_id
            or not event.event_type.startswith("conversation.")
            or any(
                getattr(event, key) != row[key]
                for key in ("event_id", "project_id", "run_id", "sequence", "event_type")
            )
            or event.occurred_at.isoformat() != row["occurred_at"]
            or event.payload
            != {
                "record_type": record_type,
                "record_id": record_id,
                "record_sha256": canonical_json_hash(value),
            }
        ):
            raise _invalid()

    def _conversation(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        conversation_id: str,
    ) -> Conversation:
        self._identifier(conversation_id, "conv")
        project = self._project(connection, project_id)
        row = connection.execute(
            "SELECT * FROM conversations WHERE conversation_id=?", (conversation_id,)
        ).fetchone()
        if row is None:
            raise _invalid()
        value = self._decode(Conversation, row["data_json"])
        if (
            value.project_id != project_id
            or value.repository_identity != project.identity_hash
            or any(
                getattr(value, key) != row[key]
                for key in (
                    "conversation_id",
                    "project_id",
                    "repository_identity",
                    "revision",
                    "next_turn_sequence",
                    "active_turn_id",
                )
            )
            or value.created_at.isoformat() != row["created_at"]
            or value.updated_at.isoformat() != row["updated_at"]
        ):
            raise _invalid()
        self._receipt(
            connection,
            row["record_event_id"],
            project_id,
            None,
            "conversation",
            conversation_id,
            value.model_dump(mode="json"),
        )
        aggregate = connection.execute(
            "SELECT COUNT(*) AS count, COALESCE(MAX(sequence),0) AS last "
            "FROM conversation_turns WHERE conversation_id=?",
            (conversation_id,),
        ).fetchone()
        active = connection.execute(
            "SELECT turn_id FROM conversation_turns WHERE conversation_id=? "
            "AND status IN ('running','waiting','recovery_required') LIMIT 2",
            (conversation_id,),
        ).fetchall()
        if (
            aggregate["count"] != value.next_turn_sequence - 1
            or aggregate["last"] != value.next_turn_sequence - 1
            or [item["turn_id"] for item in active]
            != ([value.active_turn_id] if value.active_turn_id else [])
        ):
            raise _invalid()
        return value

    def _write_conversation(
        self,
        connection: sqlite3.Connection,
        value: Conversation,
        *,
        new: bool = False,
    ) -> None:
        value = self._validated(Conversation, value)
        event_id = self._event(
            connection,
            value.project_id,
            None,
            "conversation.created" if new else "conversation.updated",
            "conversation",
            value.conversation_id,
            value.model_dump(mode="json"),
        )
        values = (
            value.project_id,
            value.repository_identity,
            value.revision,
            value.next_turn_sequence,
            value.active_turn_id,
            value.created_at.isoformat(),
            value.updated_at.isoformat(),
            event_id,
            value.model_dump_json(),
            value.conversation_id,
        )
        if new:
            connection.execute(
                "INSERT INTO conversations(project_id,repository_identity,revision,"
                "next_turn_sequence,"
                "active_turn_id,created_at,updated_at,record_event_id,data_json,conversation_id) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                values,
            )
        else:
            connection.execute(
                "UPDATE conversations SET project_id=?,repository_identity=?,revision=?,"
                "next_turn_sequence=?,active_turn_id=?,created_at=?,updated_at=?,record_event_id=?,"
                "data_json=? WHERE conversation_id=?",
                values,
            )

    def _created_binding(
        self,
        connection: sqlite3.Connection,
        run: Run,
    ) -> dict[str, JsonValue]:
        rows = connection.execute(
            "SELECT * FROM run_events WHERE run_id=? AND event_type='run.created' LIMIT 2",
            (run.run_id,),
        ).fetchall()
        if len(rows) != 1:
            raise _invalid()
        row = rows[0]
        event = self._decode(FleetEvent, row["data_json"])
        if (
            event.run_id != run.run_id
            or event.project_id != run.project_id
            or any(
                getattr(event, key) != row[key]
                for key in ("event_id", "project_id", "run_id", "sequence", "event_type")
            )
            or event.event_type != "run.created"
        ):
            raise _invalid()
        return event.payload

    def _claim_row(self, connection: sqlite3.Connection, row: sqlite3.Row) -> ConversationClaim:
        claim = self._decode(ConversationClaim, row["data_json"])
        if (
            any(
                getattr(claim, key) != row[key]
                for key in ("claim_id", "conversation_id", "turn_id", "run_id", "generation")
            )
            or claim.claimed_at.isoformat() != row["claimed_at"]
            or row["status"] not in {"active", "released", "fenced"}
            or (row["status"] == "active") != (row["released_at"] is None)
        ):
            raise _invalid()
        self._receipt(
            connection,
            row["record_event_id"],
            claim.project_id,
            claim.run_id,
            "claim",
            claim.claim_id,
            {
                "claim": claim.model_dump(mode="json"),
                "status": row["status"],
                "released_at": row["released_at"],
            },
        )
        return claim

    def _turn(
        self, connection: sqlite3.Connection, project_id: str, turn_id: str
    ) -> ConversationTurn:
        self._identifier(turn_id, "turn")
        row = connection.execute(
            "SELECT * FROM conversation_turns WHERE turn_id=?", (turn_id,)
        ).fetchone()
        if row is None:
            raise _invalid()
        turn = self._decode(ConversationTurn, row["data_json"])
        binding = self._decode(ConversationRunBinding, row["binding_json"])
        conversation = self._conversation(connection, project_id, binding.conversation_id)
        if (
            binding != turn.binding
            or binding.project_id != project_id
            or binding.repository_identity != conversation.repository_identity
            or any(
                getattr(binding, key) != row[key]
                for key in (
                    "turn_id",
                    "conversation_id",
                    "project_id",
                    "sequence",
                    "submission_key",
                    "submission_sha256",
                    "run_id",
                )
            )
            or any(
                getattr(turn, key) != row[key]
                for key in ("revision", "status", "owner_generation", "active_claim_id")
            )
            or ((turn.status in _ACTIVE) != (conversation.active_turn_id == turn_id))
        ):
            raise _invalid()
        self._receipt(
            connection,
            row["record_event_id"],
            project_id,
            binding.run_id,
            "turn",
            turn_id,
            turn.model_dump(mode="json"),
        )
        run = self.state._validated_run(connection, binding.run_id)
        if (
            run.project_id != project_id
            or _run_hash(run) != binding.run_binding_sha256
            or _goal_hash(run) != binding.user_goal_sha256
            or (
                run.config_snapshot_hash is not None
                and run.config_snapshot_hash != binding.config_snapshot_sha256
            )
        ):
            raise _invalid()
        receipt = self._created_binding(connection, run)
        if (
            receipt.get("conversation_id") != binding.conversation_id
            or receipt.get("conversation_turn_id") != binding.turn_id
            or receipt.get("conversation_binding_sha256")
            != canonical_json_hash(binding.model_dump(mode="json"))
        ):
            raise _invalid()
        summary = connection.execute(
            "SELECT COUNT(*) AS count, MAX(generation) AS latest FROM conversation_turn_claims "
            "WHERE turn_id=?",
            (turn_id,),
        ).fetchone()
        active = connection.execute(
            "SELECT claim_id FROM conversation_turn_claims WHERE turn_id=? "
            "AND status='active' LIMIT 2",
            (turn_id,),
        ).fetchall()
        if (
            summary["count"] != turn.owner_generation
            or summary["latest"] != turn.owner_generation
            or [item["claim_id"] for item in active]
            != ([turn.active_claim_id] if turn.active_claim_id else [])
        ):
            raise _invalid()
        claim_row = connection.execute(
            "SELECT * FROM conversation_turn_claims WHERE turn_id=? AND generation=?",
            (turn_id, turn.owner_generation),
        ).fetchone()
        if claim_row is None:
            raise _invalid()
        claim = self._claim_row(connection, claim_row)
        if any(
            getattr(claim, key) != getattr(binding, key)
            for key in ("project_id", "conversation_id", "turn_id", "run_id")
        ):
            raise _invalid()
        self._validate_refs(connection, run, turn.artifact_refs)
        return turn

    def _turn_for_run(self, connection: sqlite3.Connection, run_id: str) -> ConversationTurn | None:
        self._identifier(run_id, "run")
        run = self.state._validated_run(connection, run_id)
        row = connection.execute(
            "SELECT turn_id FROM conversation_turns WHERE run_id=?", (run_id,)
        ).fetchone()
        if row is None:
            if any(
                key.startswith("conversation_") for key in self._created_binding(connection, run)
            ):
                raise _invalid()
            return None
        return self._turn(connection, run.project_id, row["turn_id"])

    def _write_turn(
        self,
        connection: sqlite3.Connection,
        turn: ConversationTurn,
        event_type: str,
        *,
        new: bool = False,
    ) -> None:
        turn = self._validated(ConversationTurn, turn)
        binding = turn.binding
        event_id = self._event(
            connection,
            binding.project_id,
            binding.run_id,
            event_type,
            "turn",
            binding.turn_id,
            turn.model_dump(mode="json"),
        )
        values = (
            binding.conversation_id,
            binding.project_id,
            binding.sequence,
            binding.submission_key,
            binding.submission_sha256,
            binding.run_id,
            turn.revision,
            turn.status.value,
            turn.owner_generation,
            turn.active_claim_id,
            binding.model_dump_json(),
            event_id,
            turn.model_dump_json(),
            binding.turn_id,
        )
        if new:
            connection.execute(
                "INSERT INTO conversation_turns(conversation_id,project_id,sequence,submission_key,"
                "submission_sha256,run_id,revision,status,owner_generation,active_claim_id,"
                "binding_json,record_event_id,data_json,turn_id) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                values,
            )
        else:
            connection.execute(
                "UPDATE conversation_turns SET conversation_id=?,project_id=?,sequence=?,"
                "submission_key=?,"
                "submission_sha256=?,run_id=?,revision=?,status=?,owner_generation=?,active_claim_id=?,"
                "binding_json=?,record_event_id=?,data_json=? WHERE turn_id=?",
                values,
            )

    def _write_claim(
        self,
        connection: sqlite3.Connection,
        claim: ConversationClaim,
        status: str,
        *,
        new: bool = False,
    ) -> None:
        claim = self._validated(ConversationClaim, claim)
        released = None if status == "active" else self.clock.now().isoformat()
        event_id = self._event(
            connection,
            claim.project_id,
            claim.run_id,
            {
                "active": "conversation.claim_issued",
                "released": "conversation.claim_released",
                "fenced": "conversation.claim_fenced",
            }[status],
            "claim",
            claim.claim_id,
            {"claim": claim.model_dump(mode="json"), "status": status, "released_at": released},
        )
        if new:
            connection.execute(
                "INSERT INTO conversation_turn_claims(claim_id,conversation_id,turn_id,run_id,"
                "generation,status,claimed_at,released_at,record_event_id,data_json) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    claim.claim_id,
                    claim.conversation_id,
                    claim.turn_id,
                    claim.run_id,
                    claim.generation,
                    status,
                    claim.claimed_at.isoformat(),
                    released,
                    event_id,
                    claim.model_dump_json(),
                ),
            )
        else:
            connection.execute(
                "UPDATE conversation_turn_claims SET status=?,released_at=?,record_event_id=? "
                "WHERE claim_id=?",
                (status, released, event_id, claim.claim_id),
            )

    def _advance(
        self, connection: sqlite3.Connection, conversation: Conversation, turn: ConversationTurn
    ) -> None:
        self._write_conversation(
            connection,
            conversation.model_copy(
                update={
                    "revision": conversation.revision + 1,
                    "active_turn_id": turn.binding.turn_id if turn.status in _ACTIVE else None,
                    "updated_at": self.clock.now(),
                }
            ),
        )

    def _owned(self, connection: sqlite3.Connection, claim: ConversationClaim) -> ConversationTurn:
        claim = self._validated(ConversationClaim, claim)
        turn = self._turn(connection, claim.project_id, claim.turn_id)
        if (
            turn.status is not ConversationTurnStatus.RUNNING
            or turn.active_claim_id != claim.claim_id
        ):
            raise ConversationOwnershipUnavailableError()
        row = connection.execute(
            "SELECT * FROM conversation_turn_claims WHERE claim_id=?", (claim.claim_id,)
        ).fetchone()
        if row is None or self._claim_row(connection, row) != claim:
            raise ConversationOwnershipUnavailableError()
        return turn

    @staticmethod
    def _revision(actual: int, expected: int) -> None:
        if type(expected) is not int or expected < 0 or expected != actual:
            raise ConversationOwnershipUnavailableError()

    def _validate_refs(
        self, connection: sqlite3.Connection, run: Run, refs: tuple[ConversationArtifactRef, ...]
    ) -> None:
        if len(refs) > 8 or len({ref.artifact_id for ref in refs}) != len(refs):
            raise _invalid()
        for value in refs:
            ref = self._validated(ConversationArtifactRef, value)
            row = connection.execute(
                "SELECT * FROM artifacts WHERE artifact_id=?", (ref.artifact_id,)
            ).fetchone()
            if row is None:
                raise _invalid()
            metadata = self._decode(ArtifactMetadata, row["data_json"])
            if (
                ref.run_id != run.run_id
                or metadata.run_id != run.run_id
                or metadata.project_id != run.project_id
                or metadata.task_id != run.task_id
                or any(
                    getattr(metadata, key) != row[key]
                    for key in ("artifact_id", "project_id", "run_id", "kind", "sha256")
                )
                or metadata.artifact_id != ref.artifact_id
                or metadata.sha256 != ref.sha256
                or metadata.kind is not ref.kind
            ):
                raise _invalid()

    def _outstanding(self, connection: sqlite3.Connection, run: Run) -> bool:
        run_ids = [run.run_id]
        outstanding = False
        graph_row = connection.execute(
            "SELECT * FROM fleet_graphs WHERE parent_run_id=?", (run.run_id,)
        ).fetchone()
        if graph_row is not None:
            graph = self._decode(GraphSnapshot, graph_row["data_json"])
            if graph.parent_run_id != run.run_id or graph.project_id != run.project_id:
                raise _invalid()
            rows = connection.execute(
                "SELECT * FROM fleet_graph_nodes WHERE parent_run_id=? LIMIT 17", (run.run_id,)
            ).fetchall()
            if len(rows) != len(graph.nodes) or len(rows) > 16:
                raise _invalid()
            expected = {node.binding.child_run_id: node.binding for node in graph.nodes}
            outstanding |= graph.driver_claim is not None
            for row in rows:
                binding = self._decode(GraphChildBinding, row["binding_json"])
                child = self.state._validated_run(connection, binding.child_run_id)
                if (
                    binding != expected.get(row["child_run_id"])
                    or binding.child_run_id != row["child_run_id"]
                    or binding.parent_run_id != run.run_id
                    or binding.project_id != run.project_id
                    or child.project_id != run.project_id
                    or child.parent_run_id != run.run_id
                    or child.parent_plan_sha256 != binding.plan_sha256
                    or child.parent_node_id != binding.node_id
                    or child.parent_iteration != binding.iteration
                ):
                    raise _invalid()
                run_ids.append(binding.child_run_id)
                outstanding |= not is_terminal(child.status)
        elif (
            connection.execute(
                "SELECT 1 FROM run_events WHERE run_id=? "
                "AND event_type='graph.initialized' LIMIT 1",
                (run.run_id,),
            ).fetchone()
            is not None
        ):
            raise _invalid()
        for run_id in run_ids:
            rows = connection.execute(
                "SELECT * FROM resource_leases WHERE run_id=? LIMIT 4097", (run_id,)
            ).fetchall()
            if len(rows) > 4096:
                raise _invalid()
            for row in rows:
                lease = self._decode(ResourceLease, row["data_json"])
                if lease.run_id != run_id or any(
                    getattr(lease, key) != row[key]
                    for key in ("lease_id", "run_id", "kind", "status", "resource_id")
                ):
                    raise _invalid()
                outstanding |= lease.status.value not in {"released", "recovered"}
        return outstanding

    @_boundary
    def create(self, project_id: str, repository_identity: str) -> Conversation:
        with self._transaction() as connection:
            self._clean(repository_identity)
            if self._project(connection, project_id).identity_hash != repository_identity:
                raise _invalid()
            now = self.clock.now()
            value = Conversation(
                conversation_id=self.ids.new(IdPrefix.CONVERSATION),
                project_id=project_id,
                repository_identity=repository_identity,
                created_at=now,
                updated_at=now,
            )
            self._write_conversation(connection, value, new=True)
            return value

    @_boundary
    def latest(self, project_id: str, repository_identity: str) -> Conversation | None:
        with self._transaction() as connection:
            self._clean(repository_identity)
            if self._project(connection, project_id).identity_hash != repository_identity:
                raise _invalid()
            row = connection.execute(
                "SELECT conversation_id FROM conversations WHERE project_id=? "
                "AND repository_identity=? "
                "ORDER BY updated_at DESC,conversation_id DESC LIMIT 1",
                (project_id, repository_identity),
            ).fetchone()
            if row is None:
                if connection.execute(
                    "SELECT 1 FROM run_events WHERE project_id=? "
                    "AND event_type='conversation.created' LIMIT 1",
                    (project_id,),
                ).fetchone():
                    raise _invalid()
                return None
            return self._conversation(connection, project_id, row["conversation_id"])

    @_boundary
    def get(self, project_id: str, conversation_id: str) -> Conversation:
        with self._transaction() as connection:
            return self._conversation(connection, project_id, conversation_id)

    @_boundary
    def list_turns(
        self,
        project_id: str,
        conversation_id: str,
        *,
        before_sequence: int | None = None,
        limit: int = 50,
    ) -> tuple[ConversationTurn, ...]:
        if (
            type(limit) is not int
            or not 1 <= limit <= 100
            or (
                before_sequence is not None
                and (type(before_sequence) is not int or not 1 <= before_sequence <= 1001)
            )
        ):
            raise _denied()
        with self._transaction() as connection:
            conversation = self._conversation(connection, project_id, conversation_id)
            rows = connection.execute(
                "SELECT turn_id FROM conversation_turns WHERE conversation_id=? "
                "AND sequence<? ORDER BY sequence DESC LIMIT ?",
                (conversation_id, before_sequence or conversation.next_turn_sequence, limit),
            ).fetchall()
            return tuple(self._turn(connection, project_id, row["turn_id"]) for row in rows)

    @_boundary
    def get_submission(
        self, project_id: str, conversation_id: str, submission_key: str
    ) -> ConversationTurn | None:
        with self._transaction() as connection:
            if (
                not isinstance(submission_key, str)
                or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", submission_key) is None
            ):
                raise _denied()
            self._clean(submission_key)
            self._conversation(connection, project_id, conversation_id)
            row = connection.execute(
                "SELECT turn_id FROM conversation_turns WHERE conversation_id=? "
                "AND submission_key=?",
                (conversation_id, submission_key),
            ).fetchone()
            return self._turn(connection, project_id, row["turn_id"]) if row else None

    @_boundary
    def get_turn(self, project_id: str, turn_id: str) -> ConversationTurn:
        with self._transaction() as connection:
            return self._turn(connection, project_id, turn_id)

    @_boundary
    def binding_for_run(self, run_id: str) -> ConversationRunBinding | None:
        with self._transaction() as connection:
            turn = self._turn_for_run(connection, run_id)
            return turn.binding if turn else None

    @_boundary
    def register_turn_run(
        self,
        submission: ConversationSubmission,
        run: Run,
        *,
        config_snapshot_sha256: str,
        budget_limits: RunBudgetLimits,
    ) -> ConversationRegistration:
        submission = self._validated(ConversationSubmission, submission)
        run = self._validated(Run, run)
        budget_limits = self._validated(RunBudgetLimits, budget_limits)
        self._clean(config_snapshot_sha256)
        if (
            not run.goal.strip()
            or len(run.goal.encode("utf-8")) > 16384
            or run.project_id != submission.project_id
        ):
            raise _denied()
        digest = _submission_hash(submission, run, config_snapshot_sha256, budget_limits)
        with self._transaction() as connection:
            conversation = self._conversation(
                connection, submission.project_id, submission.conversation_id
            )
            if conversation.repository_identity != submission.repository_identity:
                raise _invalid()
            existing = connection.execute(
                "SELECT turn_id FROM conversation_turns WHERE conversation_id=? "
                "AND submission_key=?",
                (submission.conversation_id, submission.submission_key),
            ).fetchone()
            if existing:
                turn = self._turn(connection, submission.project_id, existing["turn_id"])
                if turn.binding.submission_sha256 != digest:
                    raise _denied()
                return ConversationRegistration(turn=turn)
            self._revision(conversation.revision, submission.expected_revision)
            if conversation.active_turn_id is not None or conversation.next_turn_sequence > 1000:
                raise ConversationOwnershipUnavailableError()
            if submission.context.through_sequence != conversation.next_turn_sequence - 1:
                raise _denied()
            for entry in submission.context.entries:
                historical = self._turn(connection, submission.project_id, entry.turn_id)
                expected = ConversationContextEntry(
                    turn_id=historical.binding.turn_id,
                    sequence=historical.binding.sequence,
                    run_id=historical.binding.run_id,
                    run_status=historical.observed_run_status,
                    user_summary=historical.user_summary,
                    result_summary=historical.result_summary,
                    artifact_refs=historical.artifact_refs,
                )
                if (
                    historical.binding.conversation_id != conversation.conversation_id
                    or historical.status not in _SETTLED
                    or entry != expected
                ):
                    raise _invalid()
            if (
                run.status is not RunStatus.CREATED
                or run.stage is not None
                or run.parent_run_id is not None
                or run.task_id is not None
                or run.config_snapshot_hash not in {None, config_snapshot_sha256}
                or run.fleet_plan_hash is not None
                or run.pending_approval_id is not None
            ):
                raise _invalid()
            project = self._project(connection, run.project_id)
            if project.fleet_spec_hash != config_snapshot_sha256:
                raise _invalid()
            now = self.clock.now()
            binding = ConversationRunBinding(
                conversation_id=conversation.conversation_id,
                turn_id=self.ids.new(IdPrefix.CONVERSATION_TURN),
                project_id=run.project_id,
                repository_identity=conversation.repository_identity,
                sequence=conversation.next_turn_sequence,
                submission_key=submission.submission_key,
                submission_sha256=digest,
                user_goal_sha256=_goal_hash(run),
                run_id=run.run_id,
                run_binding_sha256=_run_hash(run),
                config_snapshot_sha256=config_snapshot_sha256,
                budget_limits=budget_limits,
                context_sha256=submission.context.context_sha256,
                created_at=now,
            )
            claim = ConversationClaim(
                claim_id=self.ids.new(IdPrefix.CORRELATION),
                conversation_id=binding.conversation_id,
                turn_id=binding.turn_id,
                project_id=binding.project_id,
                run_id=run.run_id,
                generation=1,
                claimed_at=now,
            )
            turn = ConversationTurn(
                binding=binding,
                status=ConversationTurnStatus.RUNNING,
                owner_generation=1,
                active_claim_id=claim.claim_id,
                context=submission.context,
                user_summary=submission.user_summary,
                observed_run_status=run.status,
                created_at=now,
                updated_at=now,
            )
            self.state._insert_run_in_transaction(
                connection,
                run,
                created_payload={
                    "conversation_id": binding.conversation_id,
                    "conversation_turn_id": binding.turn_id,
                    "conversation_binding_sha256": canonical_json_hash(
                        binding.model_dump(mode="json")
                    ),
                },
            )
            self._write_claim(connection, claim, "active", new=True)
            self._write_turn(connection, turn, "conversation.turn_registered", new=True)
            self._write_conversation(
                connection,
                conversation.model_copy(
                    update={
                        "revision": conversation.revision + 1,
                        "next_turn_sequence": conversation.next_turn_sequence + 1,
                        "active_turn_id": binding.turn_id,
                        "updated_at": now,
                    }
                ),
            )
            return ConversationRegistration(turn=turn, claim=claim)

    @_boundary
    def assert_claim(self, claim: ConversationClaim) -> ConversationTurn:
        with self._transaction() as connection:
            return self._owned(connection, claim)

    @_boundary
    def claim_resume(self, run_id: str, *, expected_revision: int) -> ConversationClaim:
        with self._transaction() as connection:
            turn = self._turn_for_run(connection, run_id)
            if turn is None:
                raise _invalid()
            self._revision(turn.revision, expected_revision)
            run = self.state._validated_run(connection, run_id)
            if (
                turn.status is not ConversationTurnStatus.WAITING
                or turn.active_claim_id is not None
                or run.status not in {RunStatus.PAUSED_FOR_APPROVAL, RunStatus.WAITING_FOR_CHILDREN}
            ):
                raise ConversationOwnershipUnavailableError()
            conversation = self._conversation(
                connection, turn.binding.project_id, turn.binding.conversation_id
            )
            claim = ConversationClaim(
                claim_id=self.ids.new(IdPrefix.CORRELATION),
                conversation_id=turn.binding.conversation_id,
                turn_id=turn.binding.turn_id,
                project_id=turn.binding.project_id,
                run_id=run_id,
                generation=turn.owner_generation + 1,
                claimed_at=self.clock.now(),
            )
            updated = turn.model_copy(
                update={
                    "revision": turn.revision + 1,
                    "status": ConversationTurnStatus.RUNNING,
                    "owner_generation": claim.generation,
                    "active_claim_id": claim.claim_id,
                    "updated_at": self.clock.now(),
                }
            )
            self._write_claim(connection, claim, "active", new=True)
            self._write_turn(connection, updated, "conversation.turn_claimed")
            self._advance(connection, conversation, updated)
            return claim

    def _settled_update(
        self,
        connection: sqlite3.Connection,
        turn: ConversationTurn,
        summary: ConversationSummary | None,
        refs: tuple[ConversationArtifactRef, ...],
    ) -> ConversationTurn:
        run = self.state._validated_run(connection, turn.binding.run_id)
        self._validate_refs(connection, run, refs)
        if summary is not None:
            summary = self._validated(ConversationSummary, summary)
        now = self.clock.now()
        if run.status in {RunStatus.PAUSED_FOR_APPROVAL, RunStatus.WAITING_FOR_CHILDREN}:
            status = ConversationTurnStatus.WAITING
        elif run.status is RunStatus.READY_FOR_REVIEW or is_terminal(run.status):
            if self._outstanding(connection, run):
                status = ConversationTurnStatus.RECOVERY_REQUIRED
            elif run.status in {RunStatus.READY_FOR_REVIEW, RunStatus.COMPLETED}:
                status = ConversationTurnStatus.DELIVERED
            elif run.status is RunStatus.CANCELLED:
                status = ConversationTurnStatus.CANCELLED
            else:
                status = ConversationTurnStatus.FAILED
        else:
            raise _invalid()
        return self._validated(
            ConversationTurn,
            turn.model_copy(
                update={
                    "revision": turn.revision + 1,
                    "status": status,
                    "active_claim_id": None,
                    "observed_run_status": run.status,
                    "result_summary": summary,
                    "artifact_refs": refs,
                    "updated_at": now,
                    "settled_at": now if status in _SETTLED else None,
                    "fenced_at": (turn.fenced_at or now)
                    if status is ConversationTurnStatus.RECOVERY_REQUIRED
                    else turn.fenced_at,
                }
            ),
        )

    @_boundary
    def settle(
        self,
        claim: ConversationClaim,
        *,
        expected_revision: int,
        summary: ConversationSummary | None = None,
        artifact_refs: tuple[ConversationArtifactRef, ...] = (),
    ) -> ConversationTurn:
        with self._transaction() as connection:
            turn = self._owned(connection, claim)
            self._revision(turn.revision, expected_revision)
            conversation = self._conversation(
                connection, turn.binding.project_id, turn.binding.conversation_id
            )
            updated = self._settled_update(connection, turn, summary, artifact_refs)
            self._write_claim(connection, claim, "released")
            self._write_turn(connection, updated, "conversation.turn_settled")
            self._advance(connection, conversation, updated)
            return updated

    @_boundary
    def fence(
        self,
        run_id: str,
        *,
        expected_revision: int,
        reason: Literal["cancel", "recovery"],
        claim: ConversationClaim | None = None,
    ) -> ConversationTurn:
        with self._transaction() as connection:
            if reason not in {"cancel", "recovery"}:
                raise _denied()
            turn = self._turn_for_run(connection, run_id)
            if turn is None:
                raise _invalid()
            self._revision(turn.revision, expected_revision)
            if reason == "cancel":
                if claim is not None:
                    if self._owned(connection, claim).binding.run_id != run_id:
                        raise ConversationOwnershipUnavailableError()
                elif (
                    turn.status is not ConversationTurnStatus.WAITING
                    or turn.active_claim_id is not None
                ):
                    raise ConversationOwnershipUnavailableError()
            elif claim is not None and self._owned(connection, claim).binding.run_id != run_id:
                raise ConversationOwnershipUnavailableError()
            if turn.status not in _ACTIVE:
                raise ConversationOwnershipUnavailableError()
            conversation = self._conversation(
                connection, turn.binding.project_id, turn.binding.conversation_id
            )
            run = self.state._validated_run(connection, run_id)
            if not is_terminal(run.status):
                run = run.model_copy(
                    update={
                        "status": RunStatus.CANCELLED if reason == "cancel" else RunStatus.FAILED,
                        "updated_at": self.clock.now(),
                    }
                )
                self.state._save_run_in_transaction(
                    connection,
                    run,
                    "run.cancelled" if reason == "cancel" else "run.failed",
                    {
                        "reason": "conversation_cancelled"
                        if reason == "cancel"
                        else "operator_confirmed_owner_stopped"
                    },
                )
            if turn.active_claim_id:
                row = connection.execute(
                    "SELECT * FROM conversation_turn_claims WHERE claim_id=?",
                    (turn.active_claim_id,),
                ).fetchone()
                if row is None:
                    raise _invalid()
                self._write_claim(connection, self._claim_row(connection, row), "fenced")
            now = self.clock.now()
            updated = turn.model_copy(
                update={
                    "revision": turn.revision + 1,
                    "status": ConversationTurnStatus.RECOVERY_REQUIRED,
                    "active_claim_id": None,
                    "observed_run_status": run.status,
                    "updated_at": now,
                    "fenced_at": turn.fenced_at or now,
                    "settled_at": None,
                }
            )
            self._write_turn(connection, updated, "conversation.turn_fenced")
            self._advance(connection, conversation, updated)
            return updated

    @_boundary
    def reconcile_fenced(
        self,
        run_id: str,
        *,
        expected_revision: int,
        summary: ConversationSummary | None = None,
        artifact_refs: tuple[ConversationArtifactRef, ...] = (),
    ) -> ConversationTurn:
        with self._transaction() as connection:
            turn = self._turn_for_run(connection, run_id)
            if turn is None:
                raise _invalid()
            self._revision(turn.revision, expected_revision)
            run = self.state._validated_run(connection, run_id)
            if (
                turn.status is not ConversationTurnStatus.RECOVERY_REQUIRED
                or turn.active_claim_id is not None
                or not is_terminal(run.status)
                or self._outstanding(connection, run)
            ):
                raise ConversationOwnershipUnavailableError()
            conversation = self._conversation(
                connection, turn.binding.project_id, turn.binding.conversation_id
            )
            updated = self._settled_update(connection, turn, summary, artifact_refs)
            self._write_turn(connection, updated, "conversation.turn_reconciled")
            self._advance(connection, conversation, updated)
            return updated
