"""Transactional graph identities and non-reclaimable execution ownership."""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from typing import TypeVar

from pydantic import ValidationError

from agent_fleet.adapters.persistence.sqlite import SUPPORTED_SCHEMA_VERSION
from agent_fleet.domain.config import ConfigSnapshot
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.evidence import CleanupLeaseRecord, ResourceCleanupReceipt
from agent_fleet.domain.fleet_plan import (
    FleetPlan,
    FleetPlanNode,
    FleetStrategy,
    validate_fleet_plan,
)
from agent_fleet.domain.graph import (
    GraphArtifactRef,
    GraphChildBinding,
    GraphChildSeed,
    GraphDriverClaim,
    GraphJoinCompletion,
    GraphJoinPreparation,
    GraphNodeRecord,
    GraphNodeStatus,
    GraphSnapshot,
    GraphStatus,
)
from agent_fleet.domain.ids import IdPrefix
from agent_fleet.domain.models import (
    ApprovalRequest,
    ApprovalStatus,
    ArtifactKind,
    ArtifactMetadata,
    FleetEvent,
    FrozenStrictModel,
    ImplementationReport,
    LeaseStatus,
    ResourceLease,
    Run,
    RunStatus,
    Sha256,
    SpecialistReport,
    StrictModel,
    TaskSpec,
    WorkflowStage,
)
from agent_fleet.domain.paths import path_is_within
from agent_fleet.domain.role_templates import validate_role_plan
from agent_fleet.domain.security import Redactor, canonical_json_hash
from agent_fleet.ports.artifact_store import ArtifactStore
from agent_fleet.ports.clock import Clock
from agent_fleet.ports.config import ConfigurationPort
from agent_fleet.ports.id_generator import IdGenerator

_Model = TypeVar("_Model", bound=StrictModel)
_ADVANCED = {FleetStrategy.PARALLEL_ENGINEERS, FleetStrategy.RESEARCH_ARCHITECT_ENGINEER_VERIFIER}
_TERMINAL_RUNS = {
    RunStatus.COMPLETED,
    RunStatus.FAILED,
    RunStatus.CANCELLED,
    RunStatus.REJECTED,
    RunStatus.ABANDONED,
}
_TERMINAL_NODES = {
    GraphNodeStatus.SUCCEEDED,
    GraphNodeStatus.FAILED,
    GraphNodeStatus.BLOCKED,
    GraphNodeStatus.CANCELLED,
}
_INHERITED_RUN_FIELDS = (
    "model_bindings_sha256",
    "project_id",
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
    "config_snapshot_hash",
)
_IDENTITY_RUN_FIELDS = (
    *_INHERITED_RUN_FIELDS,
    "run_id",
    "correlation_id",
    "goal",
    "task_id",
    "parent_run_id",
    "parent_plan_sha256",
    "parent_node_id",
    "parent_iteration",
    "created_at",
    "max_repair_iterations",
)


class _Manifest(FrozenStrictModel):
    snapshot: GraphSnapshot
    parent_binding_sha256: Sha256
    parent_task_sha256: Sha256


def _invalid() -> FleetError:
    return FleetError(
        ErrorCode.RECOVERY_REQUIRED,
        "The durable graph identity, ownership, or transition is incomplete or inconsistent.",
        "Inspect the exact parent and child records; do not replay an interrupted graph driver.",
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
                "The durable graph store is unavailable.",
                "Restore the selected state and artifacts; unrecorded graph dispatch is forbidden.",
            )
        error.__context__ = None
        raise error from None

    return call


def _run_hash(run: Run) -> str:
    payload = run.model_dump(mode="json", warnings=False)
    identity = {key: payload[key] for key in _IDENTITY_RUN_FIELDS if key in payload}
    if run.plan_review_required:
        identity["plan_review_required"] = True
    return canonical_json_hash(identity)


class SqliteGraphStore:
    def __init__(
        self,
        database_path: Path,
        clock: Clock,
        ids: IdGenerator,
        redactor: Redactor,
        artifact_store: ArtifactStore,
        *,
        config: ConfigurationPort | None = None,
    ) -> None:
        self.database_path = database_path
        self.clock = clock
        self.ids = ids
        self.redactor = redactor
        self.artifact_store = artifact_store
        self.config = config

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(f"{self.database_path.absolute().as_uri()}?mode=rw", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 5000")
            connection.execute("BEGIN IMMEDIATE")
            version = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
            if not 6 <= version <= SUPPORTED_SCHEMA_VERSION:
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

    def _decode(self, model: type[_Model], raw: str) -> _Model:
        if not isinstance(raw, str) or len(raw.encode()) > 1_048_576:
            raise _invalid()
        self._clean(raw)
        return model.model_validate_json(raw)

    def _validated(self, model: type[_Model], value: _Model) -> _Model:
        data = value.model_dump(mode="json", warnings=False)
        self._clean(data)
        result = model.model_validate(data)
        if len(result.model_dump_json().encode()) > 1_048_576:
            raise _invalid()
        return result

    def _run(self, connection: sqlite3.Connection, run_id: str) -> Run:
        self._clean(run_id)
        row = connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise _invalid()
        run = self._decode(Run, row["data_json"])
        if (
            run.run_id != run_id
            or run.project_id != row["project_id"]
            or run.status.value != row["status"]
            or (run.stage.value if run.stage else None) != row["stage"]
        ):
            raise _invalid()
        return run

    def _task(self, connection: sqlite3.Connection, task_id: str) -> TaskSpec:
        row = connection.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        if row is None:
            raise _invalid()
        task = self._decode(TaskSpec, row["data_json"])
        if task.task_id != task_id or task.run_id != row["run_id"]:
            raise _invalid()
        return task

    def _artifact(
        self,
        connection: sqlite3.Connection,
        ref: GraphArtifactRef,
        *,
        project_id: str,
        task_id: str,
    ) -> bytes:
        ref = self._validated(GraphArtifactRef, ref)
        row = connection.execute(
            "SELECT * FROM artifacts WHERE artifact_id = ?", (ref.artifact_id,)
        ).fetchone()
        if row is None:
            raise _invalid()
        metadata = self._decode(ArtifactMetadata, row["data_json"])
        if (
            metadata.artifact_id != ref.artifact_id
            or metadata.sha256 != ref.sha256
            or metadata.run_id != ref.run_id
            or metadata.project_id != project_id
            or metadata.task_id != task_id
            or metadata.kind is not ref.kind
            or metadata.project_id != row["project_id"]
            or metadata.run_id != row["run_id"]
            or metadata.kind.value != row["kind"]
            or metadata.sha256 != row["sha256"]
            or metadata.byte_size > 2_097_152
        ):
            raise _invalid()
        content = self.artifact_store.get(metadata.content_ref, metadata.sha256)
        if len(content) != metadata.byte_size or hashlib.sha256(content).hexdigest() != ref.sha256:
            raise _invalid()
        self._clean(content.decode("utf-8"))
        return content

    def _plan(self, connection: sqlite3.Connection, parent: Run) -> FleetPlan:
        if (
            parent.task_id is None
            or parent.fleet_plan_artifact_id is None
            or parent.fleet_plan_hash is None
            or parent.parent_run_id is not None
        ):
            raise _invalid()
        raw = self._artifact(
            connection,
            GraphArtifactRef(
                artifact_id=parent.fleet_plan_artifact_id,
                sha256=parent.fleet_plan_hash,
                run_id=parent.run_id,
                kind=ArtifactKind.FLEET_PLAN,
            ),
            project_id=parent.project_id,
            task_id=parent.task_id,
        )
        plan = self._decode(FleetPlan, raw.decode())
        validate_fleet_plan(plan, self._task(connection, parent.task_id))
        if (
            any(node.execution_kind is not None for node in plan.nodes)
            or plan.repair_role_id is not None
        ):
            if (
                self.config is None
                or parent.config_snapshot_artifact_id is None
                or parent.config_snapshot_hash is None
            ):
                raise _invalid()
            snapshot = ConfigSnapshot.model_validate_json(
                self._artifact(
                    connection,
                    GraphArtifactRef(
                        artifact_id=parent.config_snapshot_artifact_id,
                        sha256=parent.config_snapshot_hash,
                        run_id=parent.run_id,
                        kind=ArtifactKind.CONFIG_SNAPSHOT,
                    ),
                    project_id=parent.project_id,
                    task_id=parent.task_id,
                ).decode(),
            )
            spec, rebuilt = self.config.snapshot_from_files(
                {item.path: item.content for item in snapshot.files}
            )
            if rebuilt != snapshot:
                raise _invalid()
            validate_role_plan(plan, self.config.role_templates(spec, snapshot))
        if plan.strategy not in _ADVANCED or parent.fleet_strategy != plan.strategy.value:
            raise _invalid()
        return plan

    def _event(
        self,
        connection: sqlite3.Connection,
        run: Run,
        kind: str,
        payload: dict[str, object],
    ) -> None:
        cleaned, summary = self.redactor.redact_data(payload)
        event = FleetEvent(
            event_id=self.ids.new(IdPrefix.EVENT),
            project_id=run.project_id,
            run_id=run.run_id,
            correlation_id=run.correlation_id,
            event_type=kind,
            occurred_at=self.clock.now(),
            payload=cleaned,
            redaction_summary=summary,
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

    def _initialization_event(
        self,
        connection: sqlite3.Connection,
        parent: Run,
        manifest: _Manifest,
    ) -> None:
        rows = connection.execute(
            "SELECT * FROM run_events WHERE run_id = ? "
            "AND event_type = 'graph.initialized' LIMIT 2",
            (parent.run_id,),
        ).fetchall()
        if len(rows) != 1:
            raise _invalid()
        row = rows[0]
        event = self._decode(FleetEvent, row["data_json"])
        if (
            event.event_id != row["event_id"]
            or event.run_id != parent.run_id
            or event.project_id != parent.project_id
            or event.project_id != row["project_id"]
            or event.correlation_id != parent.correlation_id
            or event.sequence != row["sequence"]
            or event.event_type != row["event_type"]
            or event.occurred_at.isoformat() != row["occurred_at"]
            or event.payload
            != {"manifest_sha256": canonical_json_hash(manifest.model_dump(mode="json"))}
        ):
            raise _invalid()

    def _child(
        self,
        connection: sqlite3.Connection,
        binding: GraphChildBinding,
        parent: Run,
    ) -> tuple[Run, TaskSpec]:
        child = self._run(connection, binding.child_run_id)
        task = self._task(connection, binding.child_task_id)
        if (
            child.project_id != parent.project_id
            or child.task_id != binding.child_task_id
            or task.run_id != child.run_id
            or _run_hash(child) != binding.run_binding_sha256
            or canonical_json_hash(task.model_dump(mode="json")) != binding.task_sha256
            or (
                child.parent_run_id,
                child.parent_plan_sha256,
                child.parent_node_id,
                child.parent_iteration,
            )
            != (parent.run_id, binding.plan_sha256, binding.node_id, binding.iteration)
            or any(getattr(child, key) != getattr(parent, key) for key in _INHERITED_RUN_FIELDS)
        ):
            raise _invalid()
        return child, task

    def _get(self, connection: sqlite3.Connection, parent_run_id: str) -> GraphSnapshot | None:
        parent = self._run(connection, parent_run_id)
        row = connection.execute(
            "SELECT * FROM fleet_graphs WHERE parent_run_id = ?", (parent_run_id,)
        ).fetchone()
        if row is None:
            if (
                connection.execute(
                    "SELECT 1 FROM run_events WHERE run_id = ? "
                    "AND event_type = 'graph.initialized'",
                    (parent_run_id,),
                ).fetchone()
                is not None
            ):
                raise _invalid()
            return None
        graph = self._decode(GraphSnapshot, row["data_json"])
        manifest = self._decode(_Manifest, row["immutable_manifest_json"])
        original = manifest.snapshot
        if (
            graph.parent_run_id != parent_run_id
            or graph.project_id != parent.project_id
            or graph.project_id != row["project_id"]
            or graph.plan_sha256 != row["plan_sha256"]
            or graph.revision != row["revision"]
            or graph.status.value != row["status"]
            or graph.driver_generation != row["driver_generation"]
            or (graph.driver_claim.claim_id if graph.driver_claim else None)
            != row["driver_claim_id"]
            or _run_hash(parent) != manifest.parent_binding_sha256
            or canonical_json_hash(
                self._task(connection, graph.parent_task_id).model_dump(mode="json")
            )
            != manifest.parent_task_sha256
            or graph.plan != self._plan(connection, parent)
            or graph.plan_sha256 != parent.fleet_plan_hash
            or any(
                getattr(graph, key) != getattr(original, key)
                for key in (
                    "project_id",
                    "parent_run_id",
                    "parent_task_id",
                    "plan_id",
                    "plan_artifact_id",
                    "plan_sha256",
                    "plan",
                    "created_at",
                )
            )
        ):
            raise _invalid()
        self._initialization_event(connection, parent, manifest)
        if graph.revision == 0:
            if graph != original:
                raise _invalid()
        else:
            self._revision_event(
                connection,
                parent,
                graph.revision,
                canonical_json_hash(graph.model_dump(mode="json")),
            )
        rows = connection.execute(
            "SELECT * FROM fleet_graph_nodes WHERE parent_run_id = ? ORDER BY node_id LIMIT 17",
            (parent_run_id,),
        ).fetchall()
        if len(rows) != len(original.nodes):
            raise _invalid()
        original_nodes = {node.binding.node_id: node for node in original.nodes}
        nodes: list[GraphNodeRecord] = []
        for node_row in rows:
            record = self._decode(GraphNodeRecord, node_row["data_json"])
            binding = self._decode(GraphChildBinding, node_row["binding_json"])
            if (
                binding != record.binding
                or binding.node_id not in original_nodes
                or binding != original_nodes[binding.node_id].binding
                or record.node != original_nodes[binding.node_id].node
                or binding.parent_run_id != parent_run_id
                or binding.node_id != node_row["node_id"]
                or binding.iteration != node_row["iteration"]
                or binding.child_run_id != node_row["child_run_id"]
                or binding.child_task_id != node_row["child_task_id"]
                or record.status.value != node_row["status"]
                or record.revision != node_row["revision"]
            ):
                raise _invalid()
            self._child(connection, binding, parent)
            if record.revision == 0:
                if record != original_nodes[binding.node_id]:
                    raise _invalid()
            else:
                self._revision_event(
                    connection,
                    parent,
                    record.revision,
                    canonical_json_hash(record.model_dump(mode="json")),
                    node_id=binding.node_id,
                )
            nodes.append(record)
        claims = connection.execute(
            "SELECT claim_id,status,generation FROM fleet_graph_driver_claims "
            "WHERE parent_run_id=? ORDER BY generation DESC",
            (parent_run_id,),
        ).fetchall()
        active = [item for item in claims if item["status"] == "active"]
        if (
            (claims[0]["generation"] if claims else 0) != graph.driver_generation
            or len(active) != (1 if graph.driver_claim is not None else 0)
            or (
                graph.driver_claim is not None
                and active[0]["claim_id"] != graph.driver_claim.claim_id
            )
        ):
            raise _invalid()
        if graph.driver_claim is not None:
            self._claim_record(connection, graph.driver_claim)
        return self._validated(GraphSnapshot, graph.model_copy(update={"nodes": tuple(nodes)}))

    def _revision_event(
        self,
        connection: sqlite3.Connection,
        parent: Run,
        revision: int,
        digest: str,
        *,
        node_id: str | None = None,
    ) -> None:
        kinds = (
            ("graph.node_transitioned", "graph.node_cancelled")
            if node_id is not None
            else (
                "graph.driver_claimed",
                "graph.continuation_claimed",
                "graph.driver_released",
                "graph.join_prepared",
                "graph.join_completed",
                "graph.cancel_requested",
            )
        )
        placeholders = ",".join("?" for _ in kinds)
        rows = connection.execute(
            f"SELECT * FROM run_events WHERE run_id=? AND event_type IN ({placeholders}) "
            "AND json_extract(data_json, '$.payload.revision')=? "
            "AND json_extract(data_json, '$.payload.node_id') IS ? LIMIT 2",
            (parent.run_id, *kinds, revision, node_id),
        ).fetchall()
        if len(rows) != 1:
            raise _invalid()
        row = rows[0]
        event = self._decode(FleetEvent, row["data_json"])
        key = "record_sha256" if node_id is not None else "snapshot_sha256"
        if (
            event.event_id != row["event_id"]
            or event.event_type != row["event_type"]
            or event.run_id != parent.run_id
            or event.project_id != parent.project_id
            or event.project_id != row["project_id"]
            or event.sequence != row["sequence"]
            or event.correlation_id != parent.correlation_id
            or event.occurred_at.isoformat() != row["occurred_at"]
            or event.payload.get(key) != digest
        ):
            raise _invalid()

    def _claim_record(self, connection: sqlite3.Connection, claim: GraphDriverClaim) -> None:
        row = connection.execute(
            "SELECT * FROM fleet_graph_driver_claims WHERE claim_id = ?", (claim.claim_id,)
        ).fetchone()
        if (
            row is None
            or self._decode(GraphDriverClaim, row["data_json"]) != claim
            or (
                row["parent_run_id"] != claim.parent_run_id
                or row["generation"] != claim.generation
                or row["plan_sha256"] != claim.plan_sha256
                or row["status"] != "active"
                or row["claimed_at"] != claim.claimed_at.isoformat()
                or row["released_at"] is not None
            )
        ):
            raise _invalid()

    def _owned(self, connection: sqlite3.Connection, claim: GraphDriverClaim) -> GraphSnapshot:
        claim = self._validated(GraphDriverClaim, claim)
        graph = self._get(connection, claim.parent_run_id)
        if graph is None or graph.driver_claim != claim or graph.cancel_requested_at is not None:
            raise _invalid()
        parent = self._run(connection, graph.parent_run_id)
        if parent.status in _TERMINAL_RUNS or graph.status in {
            GraphStatus.FAILED,
            GraphStatus.CANCELLED,
        }:
            raise _invalid()
        return graph

    @staticmethod
    def _revision(actual: int, expected: int) -> None:
        if type(expected) is not int or expected != actual:
            raise _invalid()

    def _save_graph(self, connection: sqlite3.Connection, graph: GraphSnapshot, kind: str) -> None:
        graph = self._validated(GraphSnapshot, graph)
        connection.execute(
            "UPDATE fleet_graphs SET revision=?,status=?,driver_generation=?,driver_claim_id=?,"
            "data_json=? WHERE parent_run_id=?",
            (
                graph.revision,
                graph.status.value,
                graph.driver_generation,
                graph.driver_claim.claim_id if graph.driver_claim else None,
                graph.model_dump_json(),
                graph.parent_run_id,
            ),
        )
        self._event(
            connection,
            self._run(connection, graph.parent_run_id),
            kind,
            {
                "revision": graph.revision,
                "status": graph.status.value,
                "snapshot_sha256": canonical_json_hash(graph.model_dump(mode="json")),
            },
        )

    def _save_node(self, connection: sqlite3.Connection, node: GraphNodeRecord, kind: str) -> None:
        node = self._validated(GraphNodeRecord, node)
        connection.execute(
            "UPDATE fleet_graph_nodes SET revision=?,status=?,data_json=? "
            "WHERE parent_run_id=? AND node_id=? AND iteration=?",
            (
                node.revision,
                node.status.value,
                node.model_dump_json(),
                node.binding.parent_run_id,
                node.binding.node_id,
                node.binding.iteration,
            ),
        )
        self._event(
            connection,
            self._run(connection, node.binding.parent_run_id),
            kind,
            {
                "node_id": node.binding.node_id,
                "child_run_id": node.binding.child_run_id,
                "revision": node.revision,
                "status": node.status.value,
                "record_sha256": canonical_json_hash(node.model_dump(mode="json")),
            },
        )

    @_boundary
    def initialize(
        self,
        parent_run_id: str,
        plan: FleetPlan,
        children: tuple[GraphChildSeed, ...],
    ) -> GraphSnapshot:
        from agent_fleet.adapters.persistence.evolution import (
            check_organization_admission,
            record_organization_admission,
        )

        plan = self._validated(FleetPlan, plan)
        with self._transaction() as connection:
            parent = self._run(connection, parent_run_id)
            if (
                connection.execute(
                    "SELECT 1 FROM fleet_graph_nodes WHERE child_run_id=?", (parent_run_id,)
                ).fetchone()
                is not None
            ):
                raise _invalid()
            actual = self._plan(connection, parent)
            if actual != plan:
                raise _invalid()
            existing = self._get(connection, parent_run_id)
            if existing is not None:
                # A retried planning step cannot substitute newly allocated child IDs.
                return existing
            if parent.status is not RunStatus.RUNNING or parent.task_id is None:
                raise _invalid()
            task = self._task(connection, parent.task_id)
            nodes = {node.node_id: node for node in plan.nodes if not node.independent_verifier}
            if len(children) != len(nodes) or {item.node_id for item in children} != set(nodes):
                raise _invalid()
            seeds = tuple(self._validated(GraphChildSeed, item) for item in children)
            records: list[GraphNodeRecord] = []
            for seed in sorted(seeds, key=lambda value: value.node_id):
                node = nodes[seed.node_id]
                self._validate_seed(parent, task, plan, node, seed)
                child = seed.run
                check_organization_admission(
                    connection, child, None, parent_run_id=parent_run_id, redactor=self.redactor
                )
                connection.execute(
                    "INSERT INTO runs VALUES (?, ?, ?, ?, ?)",
                    (
                        child.run_id,
                        child.project_id,
                        child.status.value,
                        None,
                        child.model_dump_json(),
                    ),
                )
                record_organization_admission(
                    connection, child, None, parent_run_id=parent_run_id, redactor=self.redactor
                )
                connection.execute(
                    "INSERT INTO tasks VALUES (?, ?, ?)",
                    (
                        seed.task.task_id,
                        child.run_id,
                        seed.task.model_dump_json(),
                    ),
                )
                self._event(
                    connection,
                    child,
                    "run.created",
                    {
                        "internal_child": True,
                        "parent_run_id": parent_run_id,
                        "node_id": seed.node_id,
                        "status": child.status.value,
                    },
                )
                self._event(connection, child, "task.scoped", {"task_id": seed.task.task_id})
                binding = GraphChildBinding(
                    project_id=parent.project_id,
                    parent_run_id=parent_run_id,
                    plan_sha256=parent.fleet_plan_hash,
                    node_id=seed.node_id,
                    child_run_id=child.run_id,
                    child_task_id=seed.task.task_id,
                    node_sha256=canonical_json_hash(node.model_dump(mode="json")),
                    task_sha256=canonical_json_hash(seed.task.model_dump(mode="json")),
                    run_binding_sha256=_run_hash(child),
                    created_at=self.clock.now(),
                )
                records.append(
                    GraphNodeRecord(binding=binding, node=node, updated_at=self.clock.now())
                )
            graph = GraphSnapshot(
                project_id=parent.project_id,
                parent_run_id=parent_run_id,
                parent_task_id=task.task_id,
                plan_id=plan.plan_id,
                plan_artifact_id=parent.fleet_plan_artifact_id,
                plan_sha256=parent.fleet_plan_hash,
                plan=plan,
                nodes=tuple(records),
                created_at=self.clock.now(),
                updated_at=self.clock.now(),
            )
            manifest = _Manifest(
                snapshot=graph,
                parent_binding_sha256=_run_hash(parent),
                parent_task_sha256=canonical_json_hash(task.model_dump(mode="json")),
            )
            self._validated(_Manifest, manifest)
            connection.execute(
                "INSERT INTO fleet_graphs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    parent_run_id,
                    parent.project_id,
                    graph.plan_sha256,
                    0,
                    graph.status.value,
                    0,
                    None,
                    manifest.model_dump_json(),
                    graph.model_dump_json(),
                ),
            )
            for record in records:
                binding = record.binding
                connection.execute(
                    "INSERT INTO fleet_graph_nodes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        parent_run_id,
                        binding.node_id,
                        binding.iteration,
                        binding.child_run_id,
                        binding.child_task_id,
                        0,
                        record.status.value,
                        binding.model_dump_json(),
                        record.model_dump_json(),
                    ),
                )
            self._event(
                connection,
                parent,
                "graph.initialized",
                {
                    "manifest_sha256": canonical_json_hash(manifest.model_dump(mode="json")),
                },
            )
            return graph

    def _validate_seed(
        self,
        parent: Run,
        task: TaskSpec,
        plan: FleetPlan,
        node: FleetPlanNode,
        seed: GraphChildSeed,
    ) -> None:
        child, child_task = seed.run, seed.task
        if (
            child.run_id == parent.run_id
            or child.status is not RunStatus.CREATED
            or child.stage is not None
            or child.task_id != child_task.task_id
            or child_task.run_id != child.run_id
            or (
                child.parent_run_id,
                child.parent_plan_sha256,
                child.parent_node_id,
                child.parent_iteration,
            )
            != (parent.run_id, parent.fleet_plan_hash, node.node_id, 0)
            or any(getattr(child, key) != getattr(parent, key) for key in _INHERITED_RUN_FIELDS)
            or child.pending_approval_id is not None
            or child.patch_artifact_id is not None
            or child.patch_sha256 is not None
            or child.applied_revision is not None
            or child.engineer_checkpoint is not None
            or child.verification_checkpoint is not None
            or child.specialist_checkpoint is not None
            or child.repair_iterations != 0
            or child.verified_complete
            or child.command_evidence_artifact_ids
            or child.runtime_usage_artifact_ids
            or child_task.base_revision != task.base_revision
            or child_task.config_snapshot_hash != task.config_snapshot_hash
            or child_task.workflow != task.workflow
            or child_task.forbidden_paths != task.forbidden_paths
            or set(child_task.allowed_paths) != set(node.scope)
            or any(
                not path_is_within(path, task.allowed_paths, forbidden=task.forbidden_paths)
                for path in child_task.allowed_paths
            )
            or child_task.max_repair_iterations > task.max_repair_iterations
            or child.max_repair_iterations > parent.max_repair_iterations
            or not {item.criterion_id for item in child_task.acceptance_criteria}.issubset(
                item.criterion_id for item in task.acceptance_criteria
            )
        ):
            raise _invalid()
        parent_criteria = {item.criterion_id: item for item in task.acceptance_criteria}
        if any(
            item != parent_criteria[item.criterion_id] for item in child_task.acceptance_criteria
        ):
            raise _invalid()
        if (
            child.goal != child_task.normalized_goal
            or (node.goal is not None and child_task.normalized_goal != node.goal)
            or (
                node.criterion_ids
                and set(node.criterion_ids)
                != {item.criterion_id for item in child_task.acceptance_criteria}
            )
            or child.fleet_plan_artifact_id is not None
            or child.fleet_plan_hash is not None
            or child.fleet_strategy is not None
        ):
            raise _invalid()
        if node.can_write:
            if (
                node.effective_kind != "engineer"
                or child_task.change_kind != "code_change"
                or set(child_task.required_evidence) != {"canonical_patch", "command_evidence"}
            ):
                raise _invalid()
            parent_commands = {item.command_id: item for item in task.verification_commands}
            if any(
                item != parent_commands.get(item.command_id)
                for item in child_task.verification_commands
            ):
                raise _invalid()
        elif (
            node.effective_kind not in {"researcher", "architect"}
            or child_task.change_kind != "read_only"
            or child_task.required_evidence != ["control_plane_plan"]
            or child_task.verification_commands
            or child_task.required_verification_command_ids
        ):
            raise _invalid()

    @_boundary
    def get(self, parent_run_id: str) -> GraphSnapshot | None:
        with self._transaction() as connection:
            return self._get(connection, parent_run_id)

    @_boundary
    def child_binding(self, child_run_id: str) -> GraphChildBinding | None:
        with self._transaction() as connection:
            child = self._run(connection, child_run_id)
            row = connection.execute(
                "SELECT parent_run_id FROM fleet_graph_nodes WHERE child_run_id=?",
                (child_run_id,),
            ).fetchone()
            if row is None:
                if (
                    child.parent_run_id is not None
                    or connection.execute(
                        "SELECT 1 FROM run_events WHERE run_id=? AND event_type='run.created' "
                        "AND json_extract(data_json, '$.payload.internal_child') = 1",
                        (child_run_id,),
                    ).fetchone()
                    is not None
                ):
                    raise _invalid()
                return None
            graph = self._get(connection, row["parent_run_id"])
            if graph is None:
                raise _invalid()
            matches = [
                node.binding for node in graph.nodes if node.binding.child_run_id == child_run_id
            ]
            if len(matches) != 1:
                raise _invalid()
            return matches[0]

    @_boundary
    def descendants(self, parent_run_id: str) -> tuple[GraphChildBinding, ...]:
        with self._transaction() as connection:
            graph = self._get(connection, parent_run_id)
            return tuple(node.binding for node in graph.nodes) if graph is not None else ()

    @_boundary
    def claim_driver(self, parent_run_id: str, *, expected_revision: int) -> GraphDriverClaim:
        with self._transaction() as connection:
            graph = self._get(connection, parent_run_id)
            if graph is None:
                raise _invalid()
            self._revision(graph.revision, expected_revision)
            parent = self._run(connection, parent_run_id)
            if (
                graph.driver_claim is not None
                or graph.cancel_requested_at is not None
                or graph.status not in {GraphStatus.READY, GraphStatus.PAUSED}
                or parent.status in _TERMINAL_RUNS
                or any(node.status is GraphNodeStatus.RUNNING for node in graph.nodes)
            ):
                raise _invalid()
            claim = GraphDriverClaim(
                parent_run_id=parent_run_id,
                plan_sha256=graph.plan_sha256,
                claim_id=self.ids.new(IdPrefix.CORRELATION),
                generation=graph.driver_generation + 1,
                claimed_at=self.clock.now(),
            )
            connection.execute(
                "INSERT INTO fleet_graph_driver_claims VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    claim.claim_id,
                    parent_run_id,
                    claim.generation,
                    claim.plan_sha256,
                    "active",
                    claim.claimed_at.isoformat(),
                    None,
                    claim.model_dump_json(),
                ),
            )
            self._save_graph(
                connection,
                graph.model_copy(
                    update={
                        "driver_claim": claim,
                        "driver_generation": claim.generation,
                        "revision": graph.revision + 1,
                        "updated_at": self.clock.now(),
                        "status": GraphStatus.RUNNING,
                    }
                ),
                "graph.driver_claimed",
            )
            return claim

    @_boundary
    def claim_continuation(self, parent_run_id: str, *, expected_revision: int) -> GraphDriverClaim:
        """Fence one parent verification/repair continuation of an already joined graph."""
        with self._transaction() as connection:
            graph = self._get(connection, parent_run_id)
            if graph is None:
                raise _invalid()
            self._revision(graph.revision, expected_revision)
            parent = self._run(connection, parent_run_id)
            if (
                graph.status is not GraphStatus.JOINED
                or graph.join_completion is None
                or graph.driver_claim is not None
                or graph.cancel_requested_at is not None
                or parent.status not in {RunStatus.RUNNING, RunStatus.PAUSED_FOR_APPROVAL}
                or parent.stage
                not in {WorkflowStage.VERIFYING, WorkflowStage.REPAIRING, WorkflowStage.PRESENTING}
                or any(node.status is not GraphNodeStatus.SUCCEEDED for node in graph.nodes)
            ):
                raise _invalid()
            if parent.status is RunStatus.PAUSED_FOR_APPROVAL:
                self._approval(connection, parent, approved=True)
            elif parent.pending_approval_id is not None:
                raise _invalid()
            claim = GraphDriverClaim(
                parent_run_id=parent_run_id,
                plan_sha256=graph.plan_sha256,
                claim_id=self.ids.new(IdPrefix.CORRELATION),
                generation=graph.driver_generation + 1,
                claimed_at=self.clock.now(),
            )
            connection.execute(
                "INSERT INTO fleet_graph_driver_claims VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    claim.claim_id,
                    parent_run_id,
                    claim.generation,
                    claim.plan_sha256,
                    "active",
                    claim.claimed_at.isoformat(),
                    None,
                    claim.model_dump_json(),
                ),
            )
            self._save_graph(
                connection,
                graph.model_copy(
                    update={
                        "driver_claim": claim,
                        "driver_generation": claim.generation,
                        "revision": graph.revision + 1,
                        "updated_at": self.clock.now(),
                        "status": GraphStatus.RUNNING,
                    }
                ),
                "graph.continuation_claimed",
            )
            return claim

    @_boundary
    def transition_node(
        self,
        claim: GraphDriverClaim,
        node_id: str,
        iteration: int,
        *,
        expected_revision: int,
        target: GraphNodeStatus,
        input_artifacts: tuple[GraphArtifactRef, ...] = (),
        output_artifacts: tuple[GraphArtifactRef, ...] = (),
        error_code: ErrorCode | None = None,
    ) -> GraphNodeRecord:
        if not isinstance(target, GraphNodeStatus) or type(iteration) is not int or iteration != 0:
            raise _invalid()
        self._clean({"node_id": node_id, "error_code": error_code})
        with self._transaction() as connection:
            graph = self._owned(connection, claim)
            matches = [item for item in graph.nodes if item.binding.node_id == node_id]
            if len(matches) != 1:
                raise _invalid()
            node = matches[0]
            self._revision(node.revision, expected_revision)
            transitions = {
                GraphNodeStatus.PENDING: {
                    GraphNodeStatus.RUNNING,
                    GraphNodeStatus.BLOCKED,
                    GraphNodeStatus.CANCELLED,
                },
                GraphNodeStatus.RUNNING: {
                    GraphNodeStatus.WAITING_APPROVAL,
                    GraphNodeStatus.SUCCEEDED,
                    GraphNodeStatus.FAILED,
                    GraphNodeStatus.CANCELLED,
                },
                GraphNodeStatus.WAITING_APPROVAL: {
                    GraphNodeStatus.RUNNING,
                    GraphNodeStatus.FAILED,
                    GraphNodeStatus.BLOCKED,
                    GraphNodeStatus.CANCELLED,
                },
            }
            if target not in transitions.get(node.status, set()):
                raise _invalid()
            parent = self._run(connection, graph.parent_run_id)
            child, task = self._child(connection, node.binding, parent)
            inputs = tuple(self._validated(GraphArtifactRef, ref) for ref in input_artifacts)
            outputs = tuple(self._validated(GraphArtifactRef, ref) for ref in output_artifacts)
            if target is GraphNodeStatus.RUNNING:
                if output_artifacts or graph.join_preparation is not None:
                    raise _invalid()
                dependencies = [
                    item for item in graph.nodes if item.binding.node_id in node.node.depends_on
                ]
                if len(dependencies) != len(node.node.depends_on) or any(
                    item.status is not GraphNodeStatus.SUCCEEDED for item in dependencies
                ):
                    raise _invalid()
                expected_inputs = tuple(
                    ref for item in dependencies for ref in item.output_artifacts
                )
                if inputs != expected_inputs or (
                    node.started_at is not None and inputs != node.input_artifacts
                ):
                    raise _invalid()
                if (
                    sum(item.status is GraphNodeStatus.RUNNING for item in graph.nodes)
                    >= graph.plan.max_parallel_agents
                ):
                    raise _invalid()
                for dependency in dependencies:
                    for ref in dependency.output_artifacts:
                        self._artifact(
                            connection,
                            ref,
                            project_id=graph.project_id,
                            task_id=dependency.binding.child_task_id,
                        )
                if node.status is GraphNodeStatus.WAITING_APPROVAL:
                    self._approval(connection, child, approved=True)
                elif child.status not in {RunStatus.CREATED, RunStatus.RUNNING}:
                    raise _invalid()
                self._prepared_child(connection, child, task, graph)
            elif inputs and inputs != node.input_artifacts:
                raise _invalid()
            if target is GraphNodeStatus.WAITING_APPROVAL:
                self._approval(connection, child, approved=False)
            if target is GraphNodeStatus.SUCCEEDED:
                self._successful_outputs(connection, graph, node, child, outputs)
            elif outputs:
                raise _invalid()
            now = self.clock.now()
            updated = self._validated(
                GraphNodeRecord,
                node.model_copy(
                    update={
                        "status": target,
                        "revision": node.revision + 1,
                        "input_artifacts": inputs
                        if target is GraphNodeStatus.RUNNING
                        else node.input_artifacts,
                        "output_artifacts": outputs,
                        "error_code": error_code,
                        "started_at": node.started_at
                        or (now if target is GraphNodeStatus.RUNNING else None),
                        "finished_at": now if target in _TERMINAL_NODES else None,
                        "updated_at": now,
                    }
                ),
            )
            self._save_node(connection, updated, "graph.node_transitioned")
            return updated

    def _approval(self, connection: sqlite3.Connection, child: Run, *, approved: bool) -> None:
        if child.status is not RunStatus.PAUSED_FOR_APPROVAL or child.pending_approval_id is None:
            raise _invalid()
        row = connection.execute(
            "SELECT * FROM approvals WHERE request_id=?", (child.pending_approval_id,)
        ).fetchone()
        if row is None:
            raise _invalid()
        request = self._decode(ApprovalRequest, row["data_json"])
        if (
            request.request_id != child.pending_approval_id
            or request.run_id != child.run_id
            or row["run_id"] != child.run_id
            or request.status.value != row["status"]
            or request.intent_id != row["intent_id"]
            or (approved and request.status is not ApprovalStatus.APPROVED)
        ):
            raise _invalid()

    def _prepared_child(
        self,
        connection: sqlite3.Connection,
        child: Run,
        task: TaskSpec,
        graph: GraphSnapshot,
    ) -> None:
        if child.task_spec_artifact_id is None or child.task_spec_hash is None:
            raise _invalid()
        raw = self._artifact(
            connection,
            GraphArtifactRef(
                artifact_id=child.task_spec_artifact_id,
                sha256=child.task_spec_hash,
                run_id=child.run_id,
                kind=ArtifactKind.TASK_SPEC,
            ),
            project_id=graph.project_id,
            task_id=task.task_id,
        )
        if self._decode(TaskSpec, raw.decode()) != task:
            raise _invalid()
        if child.config_snapshot_artifact_id is None or child.config_snapshot_hash is None:
            raise _invalid()
        self._artifact(
            connection,
            GraphArtifactRef(
                artifact_id=child.config_snapshot_artifact_id,
                sha256=child.config_snapshot_hash,
                run_id=child.run_id,
                kind=ArtifactKind.CONFIG_SNAPSHOT,
            ),
            project_id=graph.project_id,
            task_id=task.task_id,
        )
        owner = connection.execute(
            "SELECT owner_run_id FROM runtime_budget_runs WHERE run_id=?", (child.run_id,)
        ).fetchone()
        if owner is None or owner["owner_run_id"] != graph.parent_run_id:
            raise _invalid()
        events = connection.execute(
            "SELECT data_json FROM run_events WHERE run_id=? "
            "AND event_type='runtime.budget_initialized' LIMIT 2",
            (child.run_id,),
        ).fetchall()
        if len(events) != 1:
            raise _invalid()
        event = self._decode(FleetEvent, events[0]["data_json"])
        if (
            event.payload.get("owner_run_id") != graph.parent_run_id
            or event.payload.get("parent_run_id") != graph.parent_run_id
        ):
            raise _invalid()

    def _successful_outputs(
        self,
        connection: sqlite3.Connection,
        graph: GraphSnapshot,
        node: GraphNodeRecord,
        child: Run,
        outputs: tuple[GraphArtifactRef, ...],
    ) -> None:
        expected = (
            {ArtifactKind.PATCH, ArtifactKind.IMPLEMENTATION_REPORT, ArtifactKind.RESOURCE_CLEANUP}
            if node.node.can_write
            else {ArtifactKind.SPECIALIST_REPORT, ArtifactKind.RESOURCE_CLEANUP}
        )
        if (
            child.status is not RunStatus.COMPLETED
            or child.stage is not WorkflowStage.PRESENTING
            or child.verified_complete
            or child.evidence_bundle_artifact_id is not None
            or {item.kind for item in outputs} != expected
            or len(outputs) != len(expected)
            or any(item.run_id != child.run_id for item in outputs)
            or connection.execute(
                "SELECT 1 FROM resource_leases WHERE run_id=? "
                "AND status NOT IN ('released','recovered')",
                (child.run_id,),
            ).fetchone()
            is not None
        ):
            raise _invalid()
        for ref in outputs:
            raw = self._artifact(
                connection, ref, project_id=graph.project_id, task_id=node.binding.child_task_id
            )
            if ref.kind is ArtifactKind.IMPLEMENTATION_REPORT:
                self._decode(ImplementationReport, raw.decode())
            if ref.kind is ArtifactKind.SPECIALIST_REPORT:
                report = self._decode(SpecialistReport, raw.decode())
                if report.role != node.node.role_id:
                    raise _invalid()
            if ref.kind is ArtifactKind.PATCH and (
                ref.artifact_id != child.patch_artifact_id or ref.sha256 != child.patch_sha256
            ):
                raise _invalid()
            if ref.kind is ArtifactKind.RESOURCE_CLEANUP:
                if (ref.artifact_id, ref.sha256) != (
                    child.cleanup_receipt_artifact_id,
                    child.cleanup_receipt_sha256,
                ):
                    raise _invalid()
                receipt = self._decode(ResourceCleanupReceipt, raw.decode())
                rows = connection.execute(
                    "SELECT * FROM resource_leases WHERE run_id=?", (child.run_id,)
                ).fetchall()
                leases = []
                for row in rows:
                    lease = self._decode(ResourceLease, row["data_json"])
                    if (
                        lease.lease_id != row["lease_id"]
                        or lease.run_id != child.run_id
                        or lease.kind.value != row["kind"]
                        or lease.resource_id != row["resource_id"]
                        or lease.status.value != row["status"]
                    ):
                        raise _invalid()
                    leases.append(
                        CleanupLeaseRecord(
                            lease_id=lease.lease_id,
                            kind=lease.kind,
                            resource_id=lease.resource_id,
                            status=lease.status,
                        )
                    )
                if (
                    receipt.run_id != child.run_id
                    or not receipt.complete
                    or sorted(receipt.leases, key=lambda item: item.lease_id)
                    != sorted(leases, key=lambda item: item.lease_id)
                ):
                    raise _invalid()

    @_boundary
    def release_driver(
        self,
        claim: GraphDriverClaim,
        *,
        expected_revision: int,
        status: GraphStatus,
    ) -> GraphSnapshot:
        with self._transaction() as connection:
            graph = self._owned(connection, claim)
            self._revision(graph.revision, expected_revision)
            if (
                status
                not in {
                    GraphStatus.READY,
                    GraphStatus.PAUSED,
                    GraphStatus.JOINED,
                    GraphStatus.FAILED,
                }
                or any(node.status is GraphNodeStatus.RUNNING for node in graph.nodes)
                or (graph.join_preparation is not None and graph.join_completion is None)
                or (status is GraphStatus.JOINED and graph.join_completion is None)
                or (status is not GraphStatus.JOINED and graph.join_completion is not None)
            ):
                raise _invalid()
            connection.execute(
                "UPDATE fleet_graph_driver_claims SET status='released',released_at=? "
                "WHERE claim_id=?",
                (self.clock.now().isoformat(), claim.claim_id),
            )
            updated = self._validated(
                GraphSnapshot,
                graph.model_copy(
                    update={
                        "driver_claim": None,
                        "status": status,
                        "revision": graph.revision + 1,
                        "updated_at": self.clock.now(),
                    }
                ),
            )
            self._save_graph(connection, updated, "graph.driver_released")
            return updated

    @_boundary
    def mark_join_prepared(
        self,
        claim: GraphDriverClaim,
        receipt: GraphJoinPreparation,
        *,
        expected_revision: int,
    ) -> GraphSnapshot:
        receipt = self._validated(GraphJoinPreparation, receipt)
        with self._transaction() as connection:
            graph = self._owned(connection, claim)
            self._revision(graph.revision, expected_revision)
            parent = self._run(connection, graph.parent_run_id)
            if graph.join_preparation is not None:
                if graph.join_preparation != receipt:
                    raise _invalid()
                return graph
            if any(node.status is not GraphNodeStatus.SUCCEEDED for node in graph.nodes) or (
                receipt.parent_run_id,
                receipt.parent_task_id,
                receipt.plan_sha256,
                receipt.config_snapshot_sha256,
                receipt.base_revision,
            ) != (
                graph.parent_run_id,
                graph.parent_task_id,
                graph.plan_sha256,
                parent.config_snapshot_hash,
                parent.base_revision,
            ):
                raise _invalid()
            writers = [node for node in graph.nodes if node.node.can_write]
            if [item.node_id for item in receipt.ordered_inputs] != [
                item.binding.node_id for item in writers
            ]:
                raise _invalid()
            for node, item in zip(writers, receipt.ordered_inputs, strict=True):
                child, _ = self._child(connection, node.binding, parent)
                self._successful_outputs(connection, graph, node, child, node.output_artifacts)
                by_kind = {ref.kind: ref for ref in node.output_artifacts}
                patch, report = (
                    by_kind[ArtifactKind.PATCH],
                    by_kind[ArtifactKind.IMPLEMENTATION_REPORT],
                )
                if (
                    item.child_run_id,
                    item.child_task_id,
                    item.patch_artifact_id,
                    item.patch_sha256,
                    item.report_artifact_id,
                    item.report_sha256,
                ) != (
                    child.run_id,
                    node.binding.child_task_id,
                    patch.artifact_id,
                    patch.sha256,
                    report.artifact_id,
                    report.sha256,
                ):
                    raise _invalid()
            updated = self._validated(
                GraphSnapshot,
                graph.model_copy(
                    update={
                        "join_preparation": receipt,
                        "revision": graph.revision + 1,
                        "updated_at": self.clock.now(),
                    }
                ),
            )
            self._save_graph(connection, updated, "graph.join_prepared")
            return updated

    @_boundary
    def mark_join_complete(
        self,
        claim: GraphDriverClaim,
        result: GraphJoinCompletion,
        *,
        expected_revision: int,
    ) -> GraphSnapshot:
        result = self._validated(GraphJoinCompletion, result)
        with self._transaction() as connection:
            graph = self._owned(connection, claim)
            self._revision(graph.revision, expected_revision)
            if graph.join_completion is not None:
                if graph.join_completion != result:
                    raise _invalid()
                return graph
            parent = self._run(connection, graph.parent_run_id)
            if (
                graph.join_preparation is None
                or result.preparation_sha256 != graph.join_preparation.preparation_sha256
                or (result.parent_patch_artifact_id, result.parent_patch_sha256)
                != (parent.patch_artifact_id, parent.patch_sha256)
            ):
                raise _invalid()
            self._artifact(
                connection,
                GraphArtifactRef(
                    artifact_id=result.parent_patch_artifact_id,
                    sha256=result.parent_patch_sha256,
                    run_id=parent.run_id,
                    kind=ArtifactKind.PATCH,
                ),
                project_id=graph.project_id,
                task_id=graph.parent_task_id,
            )
            rows = connection.execute(
                "SELECT * FROM resource_leases WHERE run_id=? AND resource_id=?",
                (parent.run_id, result.workspace_id),
            ).fetchall()
            if len(rows) != 1:
                raise _invalid()
            lease = self._decode(ResourceLease, rows[0]["data_json"])
            if (
                lease.run_id != parent.run_id
                or lease.lease_id != rows[0]["lease_id"]
                or lease.resource_id != result.workspace_id
                or lease.resource_id != rows[0]["resource_id"]
                or lease.status is not LeaseStatus.ACTIVE
                or lease.status.value != rows[0]["status"]
                or lease.kind.value != "worktree"
                or lease.kind.value != rows[0]["kind"]
                or lease.metadata.get("workspace_kind") != "candidate"
                or lease.metadata.get("base_revision") != parent.base_revision
            ):
                raise _invalid()
            updated = self._validated(
                GraphSnapshot,
                graph.model_copy(
                    update={
                        "join_completion": result,
                        "status": GraphStatus.JOINED,
                        "revision": graph.revision + 1,
                        "updated_at": self.clock.now(),
                    }
                ),
            )
            self._save_graph(connection, updated, "graph.join_completed")
            return updated

    @_boundary
    def request_cancel(self, parent_run_id: str, *, expected_revision: int) -> GraphSnapshot:
        with self._transaction() as connection:
            graph = self._get(connection, parent_run_id)
            if graph is None:
                raise _invalid()
            self._revision(graph.revision, expected_revision)
            if graph.cancel_requested_at is not None:
                return graph
            now = self.clock.now()
            nodes: list[GraphNodeRecord] = []
            for node in graph.nodes:
                child = self._run(connection, node.binding.child_run_id)
                if child.status not in _TERMINAL_RUNS:
                    cancelled = child.model_copy(
                        update={"status": RunStatus.CANCELLED, "updated_at": now}
                    )
                    connection.execute(
                        "UPDATE runs SET status=?,data_json=? WHERE run_id=?",
                        (
                            cancelled.status.value,
                            cancelled.model_dump_json(),
                            child.run_id,
                        ),
                    )
                    self._event(
                        connection, cancelled, "run.cancelled", {"parent_run_id": parent_run_id}
                    )
                if node.status not in _TERMINAL_NODES:
                    node = self._validated(
                        GraphNodeRecord,
                        node.model_copy(
                            update={
                                "status": GraphNodeStatus.CANCELLED,
                                "revision": node.revision + 1,
                                "finished_at": now,
                                "updated_at": now,
                            }
                        ),
                    )
                    self._save_node(connection, node, "graph.node_cancelled")
                nodes.append(node)
            if graph.driver_claim is not None:
                connection.execute(
                    "UPDATE fleet_graph_driver_claims SET status='cancelled',released_at=? "
                    "WHERE claim_id=?",
                    (now.isoformat(), graph.driver_claim.claim_id),
                )
            updated = self._validated(
                GraphSnapshot,
                graph.model_copy(
                    update={
                        "nodes": tuple(nodes),
                        "driver_claim": None,
                        "cancel_requested_at": now,
                        "status": GraphStatus.CANCELLED,
                        "revision": graph.revision + 1,
                        "updated_at": now,
                    }
                ),
            )
            self._save_graph(connection, updated, "graph.cancel_requested")
            return updated
