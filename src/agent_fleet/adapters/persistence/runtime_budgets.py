"""Transactional runtime ledger; unknown dispatched requests never become free."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from decimal import Decimal
from functools import wraps
from pathlib import Path
from typing import TypeVar

from pydantic import ValidationError

from agent_fleet.adapters.persistence.model_profiles import SqliteModelProfileStore
from agent_fleet.adapters.persistence.sqlite import SqliteStateStore
from agent_fleet.domain.budgets import (
    ModelRequestAccounting,
    ModelRequestReservation,
    RunBudgetLimits,
    RunBudgetSnapshot,
    RuntimeAttempt,
    RuntimeAttemptStatus,
)
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.ids import IdPrefix
from agent_fleet.domain.models import (
    AgentInstance,
    AgentInvocation,
    AgentStatus,
    FleetEvent,
    FrozenStrictModel,
    Run,
    RunStatus,
    TaskSpec,
    UsageRecord,
)
from agent_fleet.domain.security import Redactor, canonical_json_hash
from agent_fleet.ports.clock import Clock
from agent_fleet.ports.id_generator import IdGenerator
from agent_fleet.ports.state_store import StateStore

_Model = TypeVar("_Model", bound=FrozenStrictModel)


def _safe_boundary[**Params, Result](
    operation: Callable[Params, Result],
) -> Callable[Params, Result]:
    @wraps(operation)
    def call(*args: Params.args, **kwargs: Params.kwargs) -> Result:
        mapped: FleetError
        try:
            return operation(*args, **kwargs)
        except FleetError as error:
            mapped = error
        except (ValidationError, ValueError, TypeError, KeyError):
            mapped = _invalid()
        # contextlib propagates the exception injected at a yield as __context__
        # even when the generator raises outside its handler. Clear it only after
        # leaving that context manager and the outer exception handler.
        mapped.__context__ = None
        raise mapped from None

    return call


def _invalid() -> FleetError:
    return FleetError(
        ErrorCode.RECOVERY_REQUIRED,
        "Runtime accounting is missing, incomplete, or inconsistent with its trusted binding.",
        "Inspect the accounting journal; do not reset or silently refund an uncertain attempt.",
    )


def _exhausted() -> FleetError:
    return FleetError(
        ErrorCode.RUNTIME_BUDGET_EXCEEDED,
        "The immutable runtime or logical-agent budget is exhausted.",
        "Review preserved usage and artifacts; approval cannot raise or reset this budget.",
    )


class SqliteRuntimeBudgetStore:
    def __init__(
        self,
        database_path: Path,
        clock: Clock,
        ids: IdGenerator,
        redactor: Redactor,
        state: StateStore,
    ) -> None:
        self.database_path = database_path
        self.clock = clock
        self.ids = ids
        self.redactor = redactor
        self.state = state

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        mapped_error: FleetError | None = None
        try:
            # Accounting never creates an uninitialized database or migrates implicitly.
            connection = sqlite3.connect(
                f"{self.database_path.absolute().as_uri()}?mode=rw", uri=True
            )
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 5000")
            try:
                connection.execute("BEGIN IMMEDIATE")
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
            finally:
                connection.close()
        except (sqlite3.Error, OSError):
            mapped_error = FleetError(
                ErrorCode.STATE_UNAVAILABLE,
                "The durable runtime accounting store is unavailable.",
                "Restore the selected state database; no unrecorded dispatch is permitted.",
            )
        except (ValidationError, ValueError, TypeError, KeyError):
            mapped_error = _invalid()
        if mapped_error is not None:
            raise mapped_error from None

    def _clean(self, value: object) -> None:
        if self.redactor.contains_secret_data(value):
            raise _invalid()

    def _decode(self, model: type[_Model], raw: str) -> _Model:
        if len(raw) > 32_768:
            raise _invalid()
        self._clean(raw)
        return model.model_validate_json(raw)

    def _run(self, connection: sqlite3.Connection, run_id: str) -> Run:
        row = connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise _invalid()
        self._clean(row["data_json"])
        run = Run.model_validate_json(row["data_json"])
        if (
            run.run_id != run_id
            or run.project_id != row["project_id"]
            or run.status.value != row["status"]
            or (run.stage.value if run.stage is not None else None) != row["stage"]
        ):
            raise _invalid()
        return run

    def _agent(self, connection: sqlite3.Connection, agent_id: str) -> AgentInstance:
        row = connection.execute(
            "SELECT * FROM agent_instances WHERE agent_instance_id = ?", (agent_id,)
        ).fetchone()
        if row is None:
            raise _invalid()
        self._clean(row["data_json"])
        agent = AgentInstance.model_validate_json(row["data_json"])
        if (
            agent.agent_instance_id != agent_id
            or agent.run_id != row["run_id"]
            or agent.task_id != row["task_id"]
            or agent.role != row["role"]
        ):
            raise _invalid()
        return agent

    def _task(self, connection: sqlite3.Connection, task_id: str) -> TaskSpec:
        row = connection.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        if row is None:
            raise _invalid()
        self._clean(row["data_json"])
        task = TaskSpec.model_validate_json(row["data_json"])
        if task.task_id != task_id or task.run_id != row["run_id"]:
            raise _invalid()
        return task

    def _owner(
        self, connection: sqlite3.Connection, run_id: str, *, visited: frozenset[str] = frozenset()
    ) -> tuple[str, RunBudgetLimits] | None:
        if run_id in visited or len(visited) >= 64:
            raise _invalid()
        row = connection.execute(
            "SELECT owner_run_id FROM runtime_budget_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            return None
        owner_id = str(row["owner_run_id"])
        owner = connection.execute(
            "SELECT limits_json FROM runtime_budget_owners WHERE owner_run_id = ?", (owner_id,)
        ).fetchone()
        run = self._run(connection, run_id)
        if owner is None or self._run(connection, owner_id).project_id != run.project_id:
            raise _invalid()
        limits = self._decode(RunBudgetLimits, owner["limits_json"])
        events = connection.execute(
            "SELECT * FROM run_events WHERE run_id = ? "
            "AND event_type = 'runtime.budget_initialized' LIMIT 2",
            (run_id,),
        ).fetchall()
        if len(events) != 1:
            raise _invalid()
        event_row = events[0]
        self._clean(event_row["data_json"])
        event = FleetEvent.model_validate_json(event_row["data_json"])
        if (
            event.event_id != event_row["event_id"]
            or event.event_type != event_row["event_type"]
            or event.run_id != run_id
            or event.project_id != run.project_id
            or event.project_id != event_row["project_id"]
            or event.correlation_id != run.correlation_id
            or event.sequence != event_row["sequence"]
            or event.occurred_at.isoformat() != event_row["occurred_at"]
            or event.payload.get("owner_run_id") != owner_id
            or event.payload.get("limits") != limits.model_dump(mode="json")
        ):
            raise _invalid()
        parent_id = event.payload.get("parent_run_id")
        if parent_id != run.parent_run_id:
            raise _invalid()
        if parent_id is None:
            if owner_id != run_id:
                raise _invalid()
        elif not isinstance(parent_id, str) or self._owner(
            connection, parent_id, visited=visited | {run_id}
        ) != (owner_id, limits):
            raise _invalid()
        if parent_id is not None:
            self._graph_parent(connection, run, parent_id)
        return owner_id, limits

    def _graph_parent(self, connection: sqlite3.Connection, run: Run, parent_id: str) -> None:
        from agent_fleet.adapters.persistence.graphs import _Manifest, _run_hash
        from agent_fleet.domain.graph import GraphChildBinding

        row = connection.execute(
            "SELECT * FROM fleet_graph_nodes WHERE child_run_id=?", (run.run_id,)
        ).fetchone()
        graph = connection.execute(
            "SELECT immutable_manifest_json FROM fleet_graphs WHERE parent_run_id=?", (parent_id,)
        ).fetchone()
        if row is None or graph is None:
            raise _invalid()
        binding = self._decode(GraphChildBinding, row["binding_json"])
        raw = graph[0]
        if len(raw.encode()) > 1_048_576:
            raise _invalid()
        self._clean(raw)
        manifest = _Manifest.model_validate_json(raw)
        if (
            binding.parent_run_id != parent_id
            or binding.child_run_id != run.run_id
            or binding.project_id != run.project_id
            or binding.run_binding_sha256 != _run_hash(run)
            or binding.node_id != run.parent_node_id
            or binding.plan_sha256 != run.parent_plan_sha256
            or binding.iteration != run.parent_iteration
            or binding.child_task_id != run.task_id
            or row["parent_run_id"] != parent_id
            or row["node_id"] != binding.node_id
            or row["iteration"] != binding.iteration
            or not any(node.binding == binding for node in manifest.snapshot.nodes)
        ):
            raise _invalid()
        events = connection.execute(
            "SELECT data_json FROM run_events WHERE run_id=? "
            "AND event_type='graph.initialized' LIMIT 2",
            (parent_id,),
        ).fetchall()
        if len(events) != 1:
            raise _invalid()
        self._clean(events[0][0])
        event = FleetEvent.model_validate_json(events[0][0])
        if (
            event.run_id != parent_id
            or event.project_id != run.project_id
            or event.payload
            != {"manifest_sha256": canonical_json_hash(manifest.model_dump(mode="json"))}
        ):
            raise _invalid()

    @_safe_boundary
    def initialize_run(
        self, run_id: str, limits: RunBudgetLimits, *, parent_run_id: str | None = None
    ) -> RunBudgetSnapshot:
        self._clean({"run_id": run_id, "parent_run_id": parent_run_id})
        payload = limits.model_dump(mode="json", warnings=False)
        self._clean(payload)
        limits = RunBudgetLimits.model_validate(payload)
        with self._transaction() as connection:
            return self._initialize_run_in_transaction(
                connection, run_id, limits, parent_run_id=parent_run_id
            )

    def _initialize_run_in_transaction(
        self,
        connection: sqlite3.Connection,
        run_id: str,
        limits: RunBudgetLimits,
        *,
        parent_run_id: str | None = None,
    ) -> RunBudgetSnapshot:
        limits = RunBudgetLimits.model_validate_json(limits.model_dump_json())
        run = self._run(connection, run_id)
        if run.parent_run_id != parent_run_id:
            raise _invalid()
        if parent_run_id is not None:
            self._graph_parent(connection, run, parent_run_id)
        parent = self._owner(connection, parent_run_id) if parent_run_id is not None else None
        if parent_run_id is not None and (parent is None or parent_run_id == run_id):
            raise _invalid()
        owner_id = parent[0] if parent is not None else run_id
        if parent is not None and parent[1] != limits:
            raise _invalid()
        existing = self._owner(connection, run_id)
        if existing is not None:
            if existing != (owner_id, limits):
                raise _invalid()
            return self._snapshot(connection, run_id)
        if run.status is not RunStatus.CREATED or run.stage is not None:
            raise _invalid()
        if parent is None:
            connection.execute(
                "INSERT INTO runtime_budget_owners VALUES (?, ?, ?)",
                (owner_id, limits.model_dump_json(), self.clock.now().isoformat()),
            )
        elif self._run(connection, owner_id).project_id != run.project_id:
            raise _invalid()
        connection.execute("INSERT INTO runtime_budget_runs VALUES (?, ?)", (run_id, owner_id))
        self._event(
            connection,
            run,
            "runtime.budget_initialized",
            {
                "owner_run_id": owner_id,
                "parent_run_id": parent_run_id,
                "limits": limits.model_dump(mode="json"),
            },
        )
        return self._snapshot(connection, run_id)

    def _campaign_admission(self, connection: sqlite3.Connection, run_id: str) -> None:
        from agent_fleet.adapters.persistence.evaluation_execution import (
            SqliteEvaluationExecutionStore,
        )

        state = SqliteStateStore(self.database_path, self.clock, self.ids, self.redactor)
        store = SqliteEvaluationExecutionStore(state)
        record = store._for_run(connection, run_id)
        if record is not None:
            if record.status != "active":
                raise _invalid()
            store._admit_campaign(connection, record.binding.submission.campaign_id, self)

    def _attempt(self, connection: sqlite3.Connection, attempt_id: str) -> RuntimeAttempt:
        row = connection.execute(
            "SELECT * FROM runtime_attempts WHERE attempt_id = ?", (attempt_id,)
        ).fetchone()
        if row is None:
            raise _invalid()
        attempt = self._decode(RuntimeAttempt, row["data_json"])
        if any(
            getattr(attempt, key) != row[key]
            for key in ("attempt_id", "owner_run_id", "run_id", "agent_instance_id", "status")
        ):
            raise _invalid()
        owner = self._owner(connection, attempt.run_id)
        if owner is None or owner[0] != attempt.owner_run_id:
            raise _invalid()
        if attempt.runtime_name != self._runtime_name(
            connection, self._run(connection, attempt.run_id), attempt.role
        ):
            raise _invalid()
        return attempt

    def _runtime_name(self, connection: sqlite3.Connection, run: Run, role: str) -> str:
        root = self._run(connection, run.parent_run_id) if run.parent_run_id else run
        if (
            root.parent_run_id is not None
            or root.project_id != run.project_id
            or root.model_bindings_sha256 != run.model_bindings_sha256
        ):
            raise _invalid()
        if run.model_bindings_sha256 is None:
            return run.runtime_name
        # Reuse the profile adapter's full identity/hash/audit checks within
        # this existing transaction; never open a second connection or infer
        # a model from current mutable selections.
        state = SqliteStateStore(self.database_path, self.clock, self.ids, self.redactor)
        bindings = SqliteModelProfileStore(state)._bindings(connection, run.project_id, root.run_id)
        if (
            bindings is None
            or bindings.bindings_sha256 != run.model_bindings_sha256
            or role not in bindings.roles
        ):
            raise _invalid()
        return bindings.roles[role].configuration.runtime_name

    def _active(self, connection: sqlite3.Connection, attempt_id: str) -> RuntimeAttempt:
        attempt = self._attempt(connection, attempt_id)
        run = self._run(connection, attempt.run_id)
        if (
            attempt.status is not RuntimeAttemptStatus.RUNNING
            or run.status is not RunStatus.RUNNING
            or run.stage is not attempt.stage
        ):
            raise _invalid()
        agent = self._agent(connection, attempt.agent_instance_id)
        if (
            agent.status is not AgentStatus.RUNNING
            or agent.run_id != attempt.run_id
            or agent.role != attempt.role
            or agent.iteration != attempt.iteration
            or agent.completed_at is not None
            or (agent.task_id is not None and agent.task_id != attempt.task_id)
        ):
            raise _invalid()
        if attempt.role != "cos":
            task = self._task(connection, attempt.task_id)
            if run.task_id != task.task_id or task.run_id != run.run_id:
                raise _invalid()
        return attempt

    @_safe_boundary
    def begin_attempt(
        self, request: AgentInvocation, *, attempt_id: str | None = None
    ) -> SqliteRuntimeAccounting:
        self._clean(request.model_dump(mode="json", warnings=False))
        selected_id = attempt_id or self.ids.new(IdPrefix.CORRELATION)
        self._clean(selected_id)
        with self._transaction() as connection:
            run = self._run(connection, request.run_id)
            owner = self._owner(connection, run.run_id)
            if owner is None:
                raise _invalid()
            self._campaign_admission(connection, run.run_id)
            agent = self._agent(connection, request.agent_instance_id)
            if (
                run.status is not RunStatus.RUNNING
                or run.stage is not request.stage
                or agent.agent_instance_id != request.agent_instance_id
                or agent.run_id != request.run_id
                or agent.role != request.role
                or agent.iteration != request.iteration
                or agent.status is not AgentStatus.RUNNING
                or agent.completed_at is not None
            ):
                raise _invalid()
            if request.role != "cos":
                task = self._task(connection, request.task_id)
                if (
                    run.task_id != request.task_id
                    or task.run_id != run.run_id
                    or agent.task_id != request.task_id
                ):
                    raise _invalid()
            candidate = RuntimeAttempt(
                attempt_id=selected_id,
                owner_run_id=owner[0],
                run_id=run.run_id,
                agent_instance_id=agent.agent_instance_id,
                task_id=request.task_id,
                role=request.role,
                stage=request.stage,
                iteration=request.iteration,
                max_steps=request.max_steps,
                runtime_name=self._runtime_name(connection, run, request.role),
                started_at=self.clock.now(),
            )
            previous = connection.execute(
                "SELECT attempt_id FROM runtime_attempts WHERE attempt_id = ?", (selected_id,)
            ).fetchone()
            if previous is not None:
                existing = self._active(connection, selected_id)
                if existing.model_copy(update={"started_at": candidate.started_at}) != candidate:
                    raise _invalid()
                return SqliteRuntimeAccounting(self, selected_id)
            attempts = self._attempts(connection, owner[0])
            same_agent = [
                item for item in attempts if item.agent_instance_id == agent.agent_instance_id
            ]
            if any(
                item.status is RuntimeAttemptStatus.RUNNING
                or item.max_steps != candidate.max_steps
                or item.run_id != candidate.run_id
                or item.task_id != candidate.task_id
                or item.stage is not candidate.stage
                or item.iteration != candidate.iteration
                for item in same_agent
            ):
                raise _invalid()
            snapshot = self._snapshot(connection, run.run_id)
            self._operational(snapshot)
            if snapshot.agent_invocations >= owner[1].max_agent_invocations:
                raise _exhausted()
            if self._steps(connection, agent.agent_instance_id) >= candidate.max_steps:
                raise _exhausted()
            connection.execute(
                "INSERT INTO runtime_attempts VALUES (?, ?, ?, ?, ?, ?)",
                (
                    selected_id,
                    owner[0],
                    run.run_id,
                    agent.agent_instance_id,
                    candidate.status.value,
                    candidate.model_dump_json(),
                ),
            )
            self._event(
                connection,
                run,
                "runtime.attempt_started",
                {
                    "attempt_id": selected_id,
                    "agent_instance_id": agent.agent_instance_id,
                    "max_steps": candidate.max_steps,
                },
            )
        return SqliteRuntimeAccounting(self, selected_id)

    def _attempts(self, connection: sqlite3.Connection, owner_id: str) -> list[RuntimeAttempt]:
        rows = connection.execute(
            "SELECT attempt_id FROM runtime_attempts WHERE owner_run_id = ? LIMIT 10001",
            (owner_id,),
        ).fetchall()
        if len(rows) > 10_000:
            raise _invalid()
        return [self._attempt(connection, row["attempt_id"]) for row in rows]

    def _steps(self, connection: sqlite3.Connection, agent_id: str) -> int:
        model = connection.execute(
            "SELECT COUNT(*) FROM runtime_model_requests r JOIN runtime_attempts a "
            "ON a.attempt_id = r.attempt_id WHERE a.agent_instance_id = ?",
            (agent_id,),
        ).fetchone()[0]
        simulated = connection.execute(
            "SELECT COUNT(*) FROM runtime_simulated_steps s JOIN runtime_attempts a "
            "ON a.attempt_id = s.attempt_id WHERE a.agent_instance_id = ?",
            (agent_id,),
        ).fetchone()[0]
        return int(model) + int(simulated)

    @_safe_boundary
    def snapshot(self, run_id: str) -> RunBudgetSnapshot:
        self._clean(run_id)
        with self._transaction() as connection:
            self._run(connection, run_id)
            return self._snapshot(connection, run_id)

    def _snapshot(self, connection: sqlite3.Connection, run_id: str) -> RunBudgetSnapshot:
        owner = self._owner(connection, run_id)
        if owner is None:
            return RunBudgetSnapshot(run_id=run_id, completeness="legacy_unknown")
        owner_id, limits = owner
        attempts = self._attempts(connection, owner_id)
        rows = connection.execute(
            "SELECT r.* FROM runtime_model_requests r JOIN runtime_attempts a "
            "ON r.attempt_id = a.attempt_id WHERE a.owner_run_id = ? LIMIT 100001",
            (owner_id,),
        ).fetchall()
        if len(rows) > 100_000:
            raise _invalid()
        requests: list[ModelRequestAccounting] = []
        for row in rows:
            item = self._decode(ModelRequestAccounting, row["data_json"])
            if (
                item.reservation.attempt_id != row["attempt_id"]
                or item.reservation.request_sequence != row["request_sequence"]
            ):
                raise _invalid()
            requests.append(item)
        usages = [item.usage for item in requests if item.usage is not None]
        costs: dict[str, Decimal] = {}
        for usage in usages:
            if usage.provider_currency is not None and usage.provider_cost is not None:
                costs[usage.provider_currency] = (
                    costs.get(usage.provider_currency, Decimal(0)) + usage.provider_cost
                )
        tools = connection.execute(
            "SELECT COALESCE(SUM(b.tool_calls), 0) FROM runtime_tool_batches b "
            "JOIN runtime_attempts a ON a.attempt_id = b.attempt_id WHERE a.owner_run_id = ?",
            (owner_id,),
        ).fetchone()[0]
        simulated = connection.execute(
            "SELECT COUNT(*) FROM runtime_simulated_steps s JOIN runtime_attempts a "
            "ON a.attempt_id = s.attempt_id WHERE a.owner_run_id = ?",
            (owner_id,),
        ).fetchone()[0]
        now = self.clock.now()
        active_seconds = sum(
            max(((item.finished_at or now) - item.started_at).total_seconds(), 0)
            for item in attempts
        )
        unknown = [item for item in requests if item.outcome == "unknown"]
        reserved = [item for item in requests if item.outcome == "reserved"]
        total = sum(item.total_tokens or 0 for item in usages)
        return RunBudgetSnapshot(
            run_id=run_id,
            owner_run_id=owner_id,
            limits=limits,
            completeness="unknown_requests" if unknown else "complete",
            agent_invocations=len(attempts),
            model_requests=len(requests),
            simulated_steps=int(simulated),
            tool_calls=int(tools),
            reported_input_tokens=sum(item.input_tokens or 0 for item in usages),
            reported_output_tokens=sum(item.output_tokens or 0 for item in usages),
            reported_total_tokens=total,
            reserved_tokens=sum(item.reservation.token_allowance for item in reserved),
            unknown_tokens=sum(item.reservation.token_allowance for item in unknown),
            outstanding_requests=len(reserved),
            unknown_requests=len(unknown),
            active_seconds=active_seconds,
            reported_costs={key: str(value) for key, value in costs.items()},
            exhausted=(
                len(attempts) >= limits.max_agent_invocations
                or len(requests) >= limits.max_model_requests
                or int(tools) >= limits.max_tool_calls
                or total >= limits.max_total_tokens
                or active_seconds >= limits.max_active_seconds
            ),
        )

    @staticmethod
    def _operational(snapshot: RunBudgetSnapshot) -> None:
        if snapshot.limits is None or snapshot.completeness != "complete":
            raise _invalid()
        if snapshot.active_seconds >= snapshot.limits.max_active_seconds:
            raise _exhausted()

    def _event(
        self, connection: sqlite3.Connection, run: Run, event_type: str, payload: dict[str, object]
    ) -> None:
        cleaned, redactions = self.redactor.redact_data(payload)
        event = FleetEvent(
            event_id=self.ids.new(IdPrefix.EVENT),
            event_type=event_type,
            occurred_at=self.clock.now(),
            project_id=run.project_id,
            run_id=run.run_id,
            correlation_id=run.correlation_id,
            payload=cleaned,
            redaction_summary=redactions,
            sequence=connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 FROM run_events WHERE run_id = ?",
                (run.run_id,),
            ).fetchone()[0],
        )
        connection.execute(
            "INSERT INTO run_events VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                event.event_id,
                event.project_id,
                event.run_id,
                event.sequence,
                event.event_type,
                event.occurred_at.isoformat(),
                event.model_dump_json(),
            ),
        )


class SqliteRuntimeAccounting:
    def __init__(self, store: SqliteRuntimeBudgetStore, attempt_id: str) -> None:
        self.store = store
        self._attempt_id = attempt_id

    @property
    def attempt_id(self) -> str:
        return self._attempt_id

    @_safe_boundary
    def reserve_request(
        self, request_sequence: int, *, requested_tokens: int
    ) -> ModelRequestReservation:
        if type(request_sequence) is not int or not 1 <= request_sequence <= 100_000:
            raise _invalid()
        if type(requested_tokens) is not int or not 1 <= requested_tokens <= 100_000_000:
            raise _invalid()
        with self.store._transaction() as connection:
            attempt = self.store._active(connection, self.attempt_id)
            self.store._campaign_admission(connection, attempt.run_id)
            previous = connection.execute(
                "SELECT data_json FROM runtime_model_requests WHERE attempt_id = ? "
                "AND request_sequence = ?",
                (self.attempt_id, request_sequence),
            ).fetchone()
            if previous is not None:
                item = self.store._decode(ModelRequestAccounting, previous["data_json"])
                if item.reservation.requested_tokens != requested_tokens:
                    raise _invalid()
                # A stored reservation is an accounting identity, never replay authority.
                raise _invalid()
            snapshot = self.store._snapshot(connection, attempt.run_id)
            self.store._operational(snapshot)
            assert snapshot.limits is not None
            allowance = min(
                requested_tokens,
                snapshot.limits.max_total_tokens
                - snapshot.reported_total_tokens
                - snapshot.reserved_tokens
                - snapshot.unknown_tokens,
            )
            if (
                allowance <= 0
                or snapshot.model_requests >= snapshot.limits.max_model_requests
                or self.store._steps(connection, attempt.agent_instance_id) >= attempt.max_steps
            ):
                raise _exhausted()
            reservation = ModelRequestReservation(
                attempt_id=self.attempt_id,
                request_sequence=request_sequence,
                requested_tokens=requested_tokens,
                token_allowance=allowance,
                reserved_at=self.store.clock.now(),
            )
            item = ModelRequestAccounting(reservation=reservation)
            connection.execute(
                "INSERT INTO runtime_model_requests VALUES (?, ?, ?)",
                (self.attempt_id, request_sequence, item.model_dump_json()),
            )
            self.store._event(
                connection,
                self.store._run(connection, attempt.run_id),
                "runtime.request_reserved",
                reservation.model_dump(mode="json"),
            )
            return reservation

    def _request(
        self, connection: sqlite3.Connection, reservation: ModelRequestReservation
    ) -> ModelRequestAccounting:
        if reservation.attempt_id != self.attempt_id:
            raise _invalid()
        row = connection.execute(
            "SELECT data_json FROM runtime_model_requests "
            "WHERE attempt_id = ? AND request_sequence = ?",
            (self.attempt_id, reservation.request_sequence),
        ).fetchone()
        if row is None:
            raise _invalid()
        item = self.store._decode(ModelRequestAccounting, row["data_json"])
        if item.reservation != reservation:
            raise _invalid()
        return item

    def _save_request(self, connection: sqlite3.Connection, item: ModelRequestAccounting) -> None:
        connection.execute(
            "UPDATE runtime_model_requests SET data_json = ? "
            "WHERE attempt_id = ? AND request_sequence = ?",
            (item.model_dump_json(), self.attempt_id, item.reservation.request_sequence),
        )

    @_safe_boundary
    def record_response(
        self, reservation: ModelRequestReservation, usage: UsageRecord
    ) -> RunBudgetSnapshot:
        payload = usage.model_dump(mode="json", warnings=False)
        self.store._clean(payload)
        usage = UsageRecord.model_validate(payload)
        if usage.requests != 1:
            raise _invalid()
        with self.store._transaction() as connection:
            attempt = self.store._attempt(connection, self.attempt_id)
            item = self._request(connection, reservation)
            if item.outcome in {"reported", "unknown"}:
                if item.usage != usage:
                    raise _invalid()
                return self.store._snapshot(connection, attempt.run_id)
            if item.outcome != "reserved" or attempt.status is not RuntimeAttemptStatus.RUNNING:
                raise _invalid()
            updated = ModelRequestAccounting(
                reservation=reservation,
                outcome="reported" if usage.total_tokens is not None else "unknown",
                usage=usage,
            )
            self._save_request(connection, updated)
            self.store._event(
                connection,
                self.store._run(connection, attempt.run_id),
                "runtime.response_recorded",
                updated.model_dump(mode="json"),
            )
            snapshot = self.store._snapshot(connection, attempt.run_id)
        if usage.total_tokens is None:
            raise _invalid()
        # Preserve observed overshoot durably even when denying the response's continuation.
        if (
            snapshot.limits is not None
            and snapshot.reported_total_tokens > snapshot.limits.max_total_tokens
        ):
            raise _exhausted()
        return snapshot

    @_safe_boundary
    def record_unknown(self, reservation: ModelRequestReservation) -> None:
        with self.store._transaction() as connection:
            attempt = self.store._attempt(connection, self.attempt_id)
            item = self._request(connection, reservation)
            if item.outcome != "reserved":
                return
            self._save_request(
                connection, ModelRequestAccounting(reservation=reservation, outcome="unknown")
            )
            self.store._event(
                connection,
                self.store._run(connection, attempt.run_id),
                "runtime.request_unknown",
                reservation.model_dump(mode="json"),
            )

    @_safe_boundary
    def reserve_tool_batch(self, batch_sequence: int, call_ids: tuple[str, ...]) -> None:
        self.store._clean(call_ids)
        if (
            type(batch_sequence) is not int
            or not 1 <= batch_sequence <= 100_000
            or not call_ids
            or len(call_ids) > 256
            or len(set(call_ids)) != len(call_ids)
            or any(not isinstance(value, str) or not 1 <= len(value) <= 128 for value in call_ids)
        ):
            raise _invalid()
        digest = canonical_json_hash(list(call_ids))
        with self.store._transaction() as connection:
            attempt = self.store._active(connection, self.attempt_id)
            self.store._campaign_admission(connection, attempt.run_id)
            prior = connection.execute(
                "SELECT calls_sha256, tool_calls FROM runtime_tool_batches "
                "WHERE attempt_id = ? AND batch_sequence = ?",
                (self.attempt_id, batch_sequence),
            ).fetchone()
            if prior is not None:
                # Like request claims, accounting idempotence must not authorize redispatch.
                raise _invalid()
            snapshot = self.store._snapshot(connection, attempt.run_id)
            self.store._operational(snapshot)
            assert snapshot.limits is not None
            if (
                snapshot.tool_calls + len(call_ids) > snapshot.limits.max_tool_calls
                or snapshot.reported_total_tokens >= snapshot.limits.max_total_tokens
            ):
                raise _exhausted()
            connection.execute(
                "INSERT INTO runtime_tool_batches VALUES (?, ?, ?, ?)",
                (self.attempt_id, batch_sequence, digest, len(call_ids)),
            )
            self.store._event(
                connection,
                self.store._run(connection, attempt.run_id),
                "runtime.tool_batch_reserved",
                {
                    "attempt_id": self.attempt_id,
                    "batch_sequence": batch_sequence,
                    "calls_sha256": digest,
                    "tool_calls": len(call_ids),
                },
            )

    @_safe_boundary
    def record_simulated_step(self) -> None:
        with self.store._transaction() as connection:
            attempt = self.store._active(connection, self.attempt_id)
            if attempt.runtime_name != "fake":
                raise _invalid()
            prior = connection.execute(
                "SELECT 1 FROM runtime_simulated_steps WHERE attempt_id = ?", (self.attempt_id,)
            ).fetchone()
            if prior is not None:
                raise _invalid()
            snapshot = self.store._snapshot(connection, attempt.run_id)
            self.store._operational(snapshot)
            if self.store._steps(connection, attempt.agent_instance_id) >= attempt.max_steps:
                raise _exhausted()
            connection.execute("INSERT INTO runtime_simulated_steps VALUES (?)", (self.attempt_id,))
            self.store._event(
                connection,
                self.store._run(connection, attempt.run_id),
                "runtime.simulated_step_recorded",
                {"attempt_id": self.attempt_id},
            )

    @_safe_boundary
    def remaining_active_seconds(self) -> float:
        with self.store._transaction() as connection:
            attempt = self.store._active(connection, self.attempt_id)
            snapshot = self.store._snapshot(connection, attempt.run_id)
            self.store._operational(snapshot)
            assert snapshot.limits is not None
            return snapshot.limits.max_active_seconds - snapshot.active_seconds

    @_safe_boundary
    def finish(
        self, status: RuntimeAttemptStatus, *, error_code: ErrorCode | None = None
    ) -> RunBudgetSnapshot:
        if not isinstance(status, RuntimeAttemptStatus) or status is RuntimeAttemptStatus.RUNNING:
            raise _invalid()
        if error_code is not None and not isinstance(error_code, ErrorCode):
            raise _invalid()
        with self.store._transaction() as connection:
            attempt = self.store._attempt(connection, self.attempt_id)
            if attempt.status is not RuntimeAttemptStatus.RUNNING:
                if attempt.status is not status or attempt.error_code is not error_code:
                    raise _invalid()
                return self.store._snapshot(connection, attempt.run_id)
            rows = connection.execute(
                "SELECT data_json FROM runtime_model_requests WHERE attempt_id = ?",
                (self.attempt_id,),
            ).fetchall()
            for row in rows:
                item = self.store._decode(ModelRequestAccounting, row["data_json"])
                if item.outcome == "reserved":
                    self._save_request(
                        connection,
                        ModelRequestAccounting(reservation=item.reservation, outcome="unknown"),
                    )
            updated = RuntimeAttempt.model_validate(
                {
                    **attempt.model_dump(mode="json"),
                    "status": status.value,
                    "finished_at": self.store.clock.now().isoformat(),
                    "error_code": error_code.value if error_code is not None else None,
                }
            )
            connection.execute(
                "UPDATE runtime_attempts SET status = ?, data_json = ? WHERE attempt_id = ?",
                (status.value, updated.model_dump_json(), self.attempt_id),
            )
            self.store._event(
                connection,
                self.store._run(connection, attempt.run_id),
                "runtime.attempt_finished",
                updated.model_dump(mode="json"),
            )
            return self.store._snapshot(connection, attempt.run_id)
