"""Query-only bounded SQLite snapshots for the local observer."""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, TypeAdapter

from agent_fleet.adapters.persistence.sqlite import SUPPORTED_SCHEMA_VERSION
from agent_fleet.domain.conversation import ConversationId
from agent_fleet.domain.dashboard import (
    MAX_DASHBOARD_AGENTS,
    MAX_DASHBOARD_CHILDREN,
    MAX_DASHBOARD_EVENTS,
    MAX_DASHBOARD_RUNS,
    DashboardCatalog,
    DashboardCursors,
    DashboardReadFrame,
    checked_cursors,
)
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import AgentInstance, FleetEvent, ProjectId, Run, RunId

_M = TypeVar("_M", bound=BaseModel)


def _unavailable() -> FleetError:
    return FleetError(
        ErrorCode.STATE_UNAVAILABLE,
        "The bounded read-only dashboard snapshot is unavailable.",
        "Inspect the selected local state; the dashboard did not change it.",
    )


class SqliteDashboardReader:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    @contextmanager
    def _snapshot(self) -> Iterator[sqlite3.Connection]:
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(
                f"{self.database_path.absolute().as_uri()}?mode=ro", uri=True, timeout=1
            )
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only=ON")
            deadline = time.monotonic() + 2
            remaining = 200

            def bounded_query() -> int:
                nonlocal remaining
                remaining -= 1
                return int(remaining < 0 or time.monotonic() >= deadline)

            connection.set_progress_handler(bounded_query, 10_000)
            connection.execute("BEGIN")
            version = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
            if type(version) is not int or not 9 <= version <= SUPPORTED_SCHEMA_VERSION:
                raise _unavailable()
            yield connection
        except FleetError:
            raise
        except (sqlite3.Error, OSError, ValueError, TypeError, KeyError, IndexError):
            raise _unavailable() from None
        finally:
            if connection is not None:
                connection.close()

    @staticmethod
    def _decode(model: type[_M], raw: object, budget: list[int]) -> _M:
        if not isinstance(raw, str):
            raise _unavailable()
        size = len(raw.encode("utf-8"))
        budget[0] -= size
        if size > 1_048_576 or budget[0] < 0:
            raise _unavailable()
        return model.model_validate_json(raw)

    def _run(self, row: sqlite3.Row, project_id: str, budget: list[int]) -> Run:
        run = self._decode(Run, row["data_json"], budget)
        if (
            run.run_id,
            run.project_id,
            run.status.value,
            run.stage.value if run.stage else None,
        ) != (row["run_id"], project_id, row["status"], row["stage"]) or row[
            "project_id"
        ] != project_id:
            raise _unavailable()
        return run

    def catalog(self, project_id: str, *, before: int | None = None) -> DashboardCatalog:
        with self._snapshot() as connection:
            TypeAdapter(ProjectId).validate_python(project_id)
            if before is not None and (type(before) is not int or not 1 <= before < 2**63):
                raise _unavailable()
            budget = [2_097_152]
            rows = connection.execute(
                "SELECT rowid AS position,* FROM runs WHERE project_id=? AND rowid<? "
                "AND json_extract(data_json,'$.parent_run_id') IS NULL ORDER BY rowid DESC LIMIT ?",
                (project_id, before or 2**63 - 1, MAX_DASHBOARD_RUNS + 1),
            )
            runs: list[Run] = []
            last_position: int | None = None
            next_before: int | None = None
            for row in rows:
                if len(runs) == MAX_DASHBOARD_RUNS:
                    next_before = last_position
                    break
                runs.append(self._run(row, project_id, budget))
                last_position = row["position"]
            conversations = tuple(
                TypeAdapter(ConversationId).validate_python(row[0])
                for row in connection.execute(
                    "SELECT conversation_id FROM conversations WHERE project_id=? "
                    "ORDER BY updated_at DESC,conversation_id DESC LIMIT 20",
                    (project_id,),
                )
            )
            return DashboardCatalog(tuple(runs), conversations, next_before)

    def frame(
        self, project_id: str, root_run_id: str, *, cursors: DashboardCursors | None = None
    ) -> DashboardReadFrame:
        with self._snapshot() as connection:
            TypeAdapter(ProjectId).validate_python(project_id)
            TypeAdapter(RunId).validate_python(root_run_id)
            if cursors is not None:
                cursors = checked_cursors(cursors)
            budget = [4_194_304]
            row = connection.execute("SELECT * FROM runs WHERE run_id=?", (root_run_id,)).fetchone()
            if row is None:
                raise _unavailable()
            root = self._run(row, project_id, budget)
            if root.parent_run_id is not None:
                raise _unavailable()
            runs = [root]
            for row in connection.execute(
                "SELECT * FROM runs WHERE project_id=? "
                "AND json_extract(data_json,'$.parent_run_id')=? "
                "ORDER BY run_id LIMIT ?",
                (project_id, root_run_id, MAX_DASHBOARD_CHILDREN + 1),
            ):
                if len(runs) > MAX_DASHBOARD_CHILDREN:
                    raise _unavailable()
                child = self._run(row, project_id, budget)
                if child.parent_run_id != root_run_id:
                    raise _unavailable()
                runs.append(child)
            agents: list[AgentInstance] = []
            events: list[FleetEvent] = []
            positions: DashboardCursors = {}
            high_watermarks: DashboardCursors = {}
            resync = bool(cursors and set(cursors) - {run.run_id for run in runs})
            for run in runs:
                high = connection.execute(
                    "SELECT COALESCE(MAX(sequence),0) FROM run_events WHERE run_id=?", (run.run_id,)
                ).fetchone()[0]
                high_watermarks[run.run_id] = high
                if cursors is not None and cursors.get(run.run_id, 0) > high:
                    resync = True
            truncated = False
            earlier = False
            for run in runs:
                for row in connection.execute(
                    "SELECT * FROM agent_instances WHERE run_id=? ORDER BY rowid DESC LIMIT ?",
                    (run.run_id, MAX_DASHBOARD_AGENTS + 1),
                ):
                    if len(agents) >= MAX_DASHBOARD_AGENTS:
                        truncated = True
                        break
                    agent = self._decode(AgentInstance, row["data_json"], budget)
                    if (agent.agent_instance_id, agent.run_id, agent.role, agent.task_id) != (
                        row["agent_instance_id"],
                        run.run_id,
                        row["role"],
                        row["task_id"],
                    ):
                        raise _unavailable()
                    agents.append(agent)
                high = high_watermarks[run.run_id]
                requested = cursors.get(run.run_id) if cursors is not None and not resync else None
                if requested is not None and requested > high:
                    resync = True
                    requested = None
                after = requested if requested is not None else max(0, high - MAX_DASHBOARD_EVENTS)
                earlier = earlier or (requested is None and after > 0)
                positions[run.run_id] = after
                for row in connection.execute(
                    "SELECT * FROM run_events WHERE run_id=? AND sequence>? "
                    "ORDER BY sequence LIMIT ?",
                    (run.run_id, after, MAX_DASHBOARD_EVENTS),
                ):
                    event = self._decode(FleetEvent, row["data_json"], budget)
                    if (
                        event.event_id,
                        event.run_id,
                        event.project_id,
                        event.sequence,
                        event.event_type,
                    ) != (
                        row["event_id"],
                        run.run_id,
                        project_id,
                        row["sequence"],
                        row["event_type"],
                    ):
                        raise _unavailable()
                    if event.sequence != positions[run.run_id] + 1:
                        # Gaps are never silently advanced over as complete history.
                        raise _unavailable()
                    positions[run.run_id] = event.sequence
                    events.append(event)
            return DashboardReadFrame(
                tuple(runs),
                tuple(agents),
                tuple(events),
                positions,
                high_watermarks,
                resync,
                truncated,
                earlier,
            )
