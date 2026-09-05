"""Durable exact organization versions; filesystem effects belong to another port."""

from __future__ import annotations

import base64
import json
import math
import sqlite3
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from agent_fleet.adapters.persistence.sqlite import SUPPORTED_SCHEMA_VERSION
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.evolution import (
    FleetPatchProposalRecord,
    OrganizationAdmission,
    OrganizationHead,
    OrganizationOperation,
    OrganizationVersion,
    describe_fleet_patch,
)
from agent_fleet.domain.fleet_patch import validate_fleet_patch
from agent_fleet.domain.ids import IdPrefix
from agent_fleet.domain.models import (
    ArtifactKind,
    ArtifactMetadata,
    EventId,
    FleetEvent,
    Project,
    ProjectId,
    ResourceLease,
    Run,
    Sha256,
)
from agent_fleet.domain.organization_tree import (
    OrganizationDirectory,
    OrganizationFile,
    OrganizationTree,
    PreparedPublication,
    PublicationObservation,
)
from agent_fleet.domain.repository_boundary import OrganizationRepositoryBoundary
from agent_fleet.domain.security import Redactor, canonical_json_hash, sha256_bytes
from agent_fleet.ports.clock import Clock
from agent_fleet.ports.config import ConfigurationPort
from agent_fleet.ports.id_generator import IdGenerator
from agent_fleet.ports.state_store import StateStore

_MAX_JSON_BYTES = 32_000_000


def _invalid() -> FleetError:
    return FleetError(
        ErrorCode.RECOVERY_REQUIRED,
        "The organization journal, identity or publication ownership is inconsistent.",
        "Inspect the exact project and operation; do not publish or replay until the original "
        "owner is stopped and state is reconciled.",
    )


def _boundary[**Params, Result](operation: Callable[Params, Result]) -> Callable[Params, Result]:
    @wraps(operation)
    def call(*args: Params.args, **kwargs: Params.kwargs) -> Result:
        try:
            return operation(*args, **kwargs)
        except FleetError as caught:
            error = caught
        except (
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
            RecursionError,
            OSError,
            sqlite3.Error,
        ):
            error = _invalid()
        error.__cause__ = None
        error.__context__ = None
        raise error from None

    return call


def _plain(value: object, redactor: Redactor | None) -> None:
    stack: list[tuple[object, int]] = [(value, 0)]
    count = 0
    string_bytes = 0
    while stack:
        item, depth = stack.pop()
        count += 1
        if count > 100_000 or depth > 64:
            raise _invalid()
        if type(item) is dict:
            if any(type(key) is not str for key in item):
                raise _invalid()
            stack.extend((part, depth + 1) for pair in item.items() for part in pair)
        elif type(item) is list:
            stack.extend((part, depth + 1) for part in item)
        elif type(item) is str:
            string_bytes += len(item.encode("utf-8"))
            if string_bytes > _MAX_JSON_BYTES:
                raise _invalid()
        elif (item is not None and type(item) not in {bool, int, float}) or (
            type(item) is float and not math.isfinite(item)
        ):
            raise _invalid()
    if redactor is not None and redactor.contains_secret_data(value):
        raise _invalid()


def _pairs(items: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in items:
        if key in result:
            raise _invalid()
        result[key] = value
    return result


def _decode[Model: BaseModel](model: type[Model], raw: str, redactor: Redactor | None) -> Model:
    if (
        type(raw) is not str
        or len(raw) > _MAX_JSON_BYTES
        or len(raw.encode("utf-8")) > _MAX_JSON_BYTES
    ):
        raise _invalid()
    if redactor is not None and redactor.contains_secret(raw):
        raise _invalid()
    value = json.loads(raw, object_pairs_hook=_pairs)
    _plain(value, redactor)
    return model.model_validate_json(raw)


def _validated[Model: BaseModel](
    model: type[Model], value: Model, redactor: Redactor | None
) -> Model:
    if type(value) is not model:
        raise _invalid()
    data = value.model_dump(mode="json", warnings=False)
    _plain(data, redactor)
    return _decode(model, json.dumps(data, ensure_ascii=False, separators=(",", ":")), redactor)


def _hash(value: BaseModel) -> str:
    return canonical_json_hash(value.model_dump(mode="json"))


class _Audit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    event_id: EventId
    project_id: ProjectId
    sequence: int = Field(ge=1)
    event_type: Literal[
        "organization.tree_recorded",
        "organization.version_recorded",
        "organization.head_updated",
        "organization.run_admitted",
        "fleet_patch.proposed",
        "fleet_patch.prepared",
        "fleet_patch.committed",
        "fleet_patch.aborted",
        "fleet_patch.recovery_required",
    ]
    record_kind: Literal["tree", "version", "head", "proposal", "operation", "admission"]
    record_id: str = Field(min_length=1, max_length=160)
    record_sha256: Sha256
    previous_event_sha256: Sha256 | None
    created_at: datetime


def _audit_row(
    connection: sqlite3.Connection, row: sqlite3.Row, redactor: Redactor | None
) -> _Audit:
    value = _decode(_Audit, row["data_json"], redactor)
    for key in (
        "event_id",
        "project_id",
        "sequence",
        "event_type",
        "record_kind",
        "record_id",
        "record_sha256",
        "previous_event_sha256",
    ):
        if getattr(value, key) != row[key]:
            raise _invalid()
    if value.created_at.isoformat() != row["created_at"] or _hash(value) != row["event_sha256"]:
        raise _invalid()
    previous = connection.execute(
        "SELECT * FROM organization_events WHERE project_id=? AND sequence=?",
        (value.project_id, value.sequence - 1),
    ).fetchone()
    if value.sequence == 1:
        if value.previous_event_sha256 is not None or previous is not None:
            raise _invalid()
    else:
        if previous is None:
            raise _invalid()
        prior = _decode(_Audit, previous["data_json"], redactor)
        if (
            prior.project_id != value.project_id
            or prior.sequence != value.sequence - 1
            or _hash(prior) != value.previous_event_sha256
            or previous["event_sha256"] != value.previous_event_sha256
        ):
            raise _invalid()
    return value


def _receipt(
    connection: sqlite3.Connection,
    event_id: str,
    kind: str,
    record_id: str,
    value: BaseModel,
    redactor: Redactor | None,
    *,
    project_id: str | None = None,
) -> None:
    row = connection.execute(
        "SELECT * FROM organization_events WHERE event_id=?", (event_id,)
    ).fetchone()
    if row is None:
        raise _invalid()
    event = _audit_row(connection, row, redactor)
    latest = connection.execute(
        "SELECT event_id FROM organization_events WHERE record_kind=? AND record_id=? "
        "ORDER BY sequence DESC LIMIT 1",
        (kind, record_id),
    ).fetchone()
    if (
        event.record_kind != kind
        or event.record_id != record_id
        or event.record_sha256 != _hash(value)
        or (project_id is not None and event.project_id != project_id)
        or latest is None
        or latest["event_id"] != event_id
    ):
        raise _invalid()


def _append(
    connection: sqlite3.Connection,
    *,
    event_id: str,
    project_id: str,
    event_type: str,
    kind: Literal["tree", "version", "head", "proposal", "operation", "admission"],
    record_id: str,
    value: BaseModel,
    created_at: datetime,
    redactor: Redactor | None,
) -> None:
    previous = connection.execute(
        "SELECT * FROM organization_events WHERE project_id=? ORDER BY sequence DESC LIMIT 1",
        (project_id,),
    ).fetchone()
    prior = _audit_row(connection, previous, redactor) if previous is not None else None
    event = _Audit(
        event_id=event_id,
        project_id=project_id,
        sequence=prior.sequence + 1 if prior else 1,
        event_type=event_type,  # type: ignore[arg-type]
        record_kind=kind,
        record_id=record_id,
        record_sha256=_hash(value),
        previous_event_sha256=_hash(prior) if prior else None,
        created_at=created_at,
    )
    event = _validated(_Audit, event, redactor)
    connection.execute(
        "INSERT INTO organization_events VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (
            event.event_id,
            event.project_id,
            event.sequence,
            event.event_type,
            event.record_kind,
            event.record_id,
            event.record_sha256,
            event.previous_event_sha256,
            _hash(event),
            event.created_at.isoformat(),
            event.model_dump_json(),
        ),
    )


def _project(connection: sqlite3.Connection, project_id: str, redactor: Redactor | None) -> Project:
    row = connection.execute("SELECT * FROM projects WHERE project_id=?", (project_id,)).fetchone()
    if row is None:
        raise _invalid()
    project = _decode(Project, row["data_json"], redactor)
    if project.project_id != project_id or project.canonical_root != row["canonical_root"]:
        raise _invalid()
    return project


def _version(
    connection: sqlite3.Connection, project_id: str, version: int, redactor: Redactor | None
) -> OrganizationVersion:
    row = connection.execute(
        "SELECT * FROM organization_versions WHERE project_id=? AND version=?",
        (project_id, version),
    ).fetchone()
    if row is None:
        raise _invalid()
    value = _decode(OrganizationVersion, row["data_json"], redactor)
    if any(
        getattr(value, key) != row[key]
        for key in (
            "project_id",
            "version",
            "predecessor_version",
            "tree_sha256",
            "config_snapshot_sha256",
            "operation_id",
            "audit_event_id",
        )
    ):
        raise _invalid()
    _receipt(
        connection,
        value.audit_event_id,
        "version",
        f"{project_id}:{version}",
        value,
        redactor,
        project_id=project_id,
    )
    current = value
    if version > 10_000:
        raise _invalid()
    while current.version > 0:
        row = connection.execute(
            "SELECT * FROM organization_versions WHERE project_id=? AND version=?",
            (project_id, current.version - 1),
        ).fetchone()
        if row is None:
            raise _invalid()
        previous = _decode(OrganizationVersion, row["data_json"], redactor)
        if (
            previous.project_id != project_id
            or previous.version != current.version - 1
            or _hash(previous) != current.predecessor_sha256
            or any(
                getattr(previous, key) != row[key]
                for key in (
                    "project_id",
                    "version",
                    "predecessor_version",
                    "tree_sha256",
                    "config_snapshot_sha256",
                    "operation_id",
                    "audit_event_id",
                )
            )
        ):
            raise _invalid()
        _receipt(
            connection,
            previous.audit_event_id,
            "version",
            f"{project_id}:{previous.version}",
            previous,
            redactor,
            project_id=project_id,
        )
        current = previous
    return value


def _head(
    connection: sqlite3.Connection, project_id: str, redactor: Redactor | None
) -> OrganizationHead | None:
    if (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='organization_heads'"
        ).fetchone()
        is None
    ):
        versions = [
            row[0]
            for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version")
        ]
        organization_tables = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'organization_%'"
        ).fetchall()
        if (
            not versions
            or versions[-1] >= 8
            or versions != list(range(1, versions[-1] + 1))
            or organization_tables
        ):
            raise _invalid()
        return None
    row = connection.execute(
        "SELECT * FROM organization_heads WHERE project_id=?", (project_id,)
    ).fetchone()
    if row is None:
        if (
            connection.execute(
                "SELECT 1 FROM organization_versions WHERE project_id=? LIMIT 1", (project_id,)
            ).fetchone()
            is not None
        ):
            raise _invalid()
        return None
    if redactor is None:
        raise _invalid()
    value = _decode(OrganizationHead, row["data_json"], redactor)
    if any(
        getattr(value, key) != row[key]
        for key in (
            "project_id",
            "revision",
            "tree_sha256",
            "config_snapshot_sha256",
            "project_sha256",
            "pending_operation_id",
            "audit_event_id",
        )
    ):
        raise _invalid()
    _receipt(
        connection, value.audit_event_id, "head", project_id, value, redactor, project_id=project_id
    )
    version = _version(connection, project_id, value.revision, redactor)
    latest = connection.execute(
        "SELECT MAX(version) FROM organization_versions WHERE project_id=?", (project_id,)
    ).fetchone()[0]
    project = _project(connection, project_id, redactor)
    if (
        version.admission != value.admission
        or version.project_sha256 != value.project_sha256
        or latest != value.revision
        or _hash(project) != value.project_sha256
        or project.fleet_spec_hash != value.config_snapshot_sha256
    ):
        raise _invalid()
    pending = connection.execute(
        "SELECT operation_id FROM organization_operations WHERE project_id=? "
        "AND status IN ('prepared','recovery_required')",
        (project_id,),
    ).fetchall()
    if [item["operation_id"] for item in pending] != (
        [value.pending_operation_id] if value.pending_operation_id else []
    ):
        raise _invalid()
    return value


def _run(connection: sqlite3.Connection, run_id: str, redactor: Redactor | None) -> Run:
    row = connection.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
    if row is None:
        raise _invalid()
    value = _decode(Run, row["data_json"], redactor)
    if (
        value.run_id != run_id
        or value.project_id != row["project_id"]
        or value.status.value != row["status"]
        or (value.stage.value if value.stage else None) != row["stage"]
    ):
        raise _invalid()
    return value


def _run_binding(run: Run) -> str:
    return canonical_json_hash(
        {
            "run_id": run.run_id,
            "project_id": run.project_id,
            "correlation_id": run.correlation_id,
            "config_snapshot_hash": run.config_snapshot_hash,
            "parent_run_id": run.parent_run_id,
            "parent_plan_sha256": run.parent_plan_sha256,
            "parent_node_id": run.parent_node_id,
            "parent_iteration": run.parent_iteration,
            "created_at": run.created_at.isoformat(),
        }
    )


class _RunAdmission(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    run_id: str
    admission: OrganizationAdmission
    parent_run_id: str | None
    run_binding_sha256: Sha256
    audit_event_id: EventId


def _admission(
    connection: sqlite3.Connection, run: Run, redactor: Redactor | None
) -> OrganizationAdmission | None:
    row = connection.execute(
        "SELECT * FROM organization_run_admissions WHERE run_id=?", (run.run_id,)
    ).fetchone()
    if row is None:
        if (
            connection.execute(
                "SELECT 1 FROM organization_events WHERE record_kind='admission' "
                "AND record_id=? LIMIT 1",
                (run.run_id,),
            ).fetchone()
            is not None
        ):
            raise _invalid()
        return None
    value = _decode(_RunAdmission, row["data_json"], redactor)
    if (
        value.run_id != run.run_id
        or value.admission.project_id != row["project_id"]
        or value.admission.revision != row["revision"]
        or value.parent_run_id != row["parent_run_id"]
        or value.parent_run_id != run.parent_run_id
        or value.run_binding_sha256 != row["run_binding_sha256"]
        or value.run_binding_sha256 != _run_binding(run)
        or value.audit_event_id != row["audit_event_id"]
        or value.admission.config_snapshot_sha256 != run.config_snapshot_hash
    ):
        raise _invalid()
    _receipt(
        connection,
        value.audit_event_id,
        "admission",
        run.run_id,
        value,
        redactor,
        project_id=run.project_id,
    )
    if (
        _version(connection, run.project_id, value.admission.revision, redactor).admission
        != value.admission
    ):
        raise _invalid()
    return value.admission


@_boundary
def check_organization_admission(
    connection: sqlite3.Connection,
    run: Run,
    admission: OrganizationAdmission | None,
    *,
    parent_run_id: str | None = None,
    redactor: Redactor | None = None,
) -> None:
    if not connection.in_transaction:
        raise _invalid()
    if admission is not None:
        admission = _validated(OrganizationAdmission, admission, redactor)
    head = _head(connection, run.project_id, redactor)
    if head is None:
        if admission is not None:
            raise _invalid()
        return
    run = _validated(Run, run, redactor)
    if head.pending_operation_id is not None or run.parent_run_id != parent_run_id:
        raise _invalid()
    if parent_run_id is not None:
        inherited = _admission(connection, _run(connection, parent_run_id, redactor), redactor)
        if inherited is None or (admission is not None and inherited != admission):
            raise _invalid()
        admission = inherited
    if (
        admission is None
        or admission != head.admission
        or run.config_snapshot_hash != admission.config_snapshot_sha256
        or admission.project_id != run.project_id
    ):
        raise _invalid()


@_boundary
def record_organization_admission(
    connection: sqlite3.Connection,
    run: Run,
    admission: OrganizationAdmission | None,
    *,
    parent_run_id: str | None = None,
    redactor: Redactor | None = None,
) -> None:
    check_organization_admission(
        connection, run, admission, parent_run_id=parent_run_id, redactor=redactor
    )
    head = _head(connection, run.project_id, redactor)
    if head is None:
        return
    stored_run = _run(connection, run.run_id, redactor)
    if _run_binding(stored_run) != _run_binding(run):
        raise _invalid()
    existing = _admission(connection, run, redactor)
    if existing is not None:
        if existing != head.admission:
            raise _invalid()
        return
    event_id = "evt_" + sha256_bytes(("organization-admission:" + run.run_id).encode())[:32]
    value = _RunAdmission(
        run_id=run.run_id,
        admission=head.admission,
        parent_run_id=parent_run_id,
        run_binding_sha256=_run_binding(run),
        audit_event_id=event_id,
    )
    _append(
        connection,
        event_id=event_id,
        project_id=run.project_id,
        event_type="organization.run_admitted",
        kind="admission",
        record_id=run.run_id,
        value=value,
        created_at=run.created_at,
        redactor=redactor,
    )
    connection.execute(
        "INSERT INTO organization_run_admissions VALUES(?,?,?,?,?,?,?)",
        (
            run.run_id,
            run.project_id,
            head.revision,
            parent_run_id,
            value.run_binding_sha256,
            event_id,
            value.model_dump_json(),
        ),
    )


@_boundary
def assert_organization_project_write(
    connection: sqlite3.Connection, project: Project, *, redactor: Redactor | None = None
) -> None:
    if not connection.in_transaction:
        raise _invalid()
    head = _head(connection, project.project_id, redactor)
    if head is not None and (
        head.pending_operation_id is not None
        or _hash(_validated(Project, project, redactor)) != head.project_sha256
    ):
        raise _invalid()


class SqliteOrganizationStore:
    def __init__(
        self,
        database_path: Path,
        clock: Clock,
        ids: IdGenerator,
        redactor: Redactor,
        state: StateStore,
        config: ConfigurationPort,
    ) -> None:
        self.database_path = database_path
        self.clock = clock
        self.ids = ids
        self.redactor = redactor
        self.state = state
        self.config = config

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(f"{self.database_path.absolute().as_uri()}?mode=rw", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA busy_timeout=5000")
            settings = {"foreign_keys": 1, "synchronous": 2}
            if sys.platform == "darwin":
                settings.update(fullfsync=1, checkpoint_fullfsync=1)
            if connection.execute("PRAGMA journal_mode=WAL").fetchone()[0].lower() != "wal":
                raise _invalid()
            for key, expected in settings.items():
                connection.execute(f"PRAGMA {key}={expected}")
                if connection.execute(f"PRAGMA {key}").fetchone()[0] != expected:
                    raise _invalid()
            connection.execute("BEGIN IMMEDIATE")
            versions = [
                row[0]
                for row in connection.execute(
                    "SELECT version FROM schema_migrations ORDER BY version"
                )
            ]
            if (
                versions != list(range(1, SUPPORTED_SCHEMA_VERSION + 1))
                or SUPPORTED_SCHEMA_VERSION < 8
            ):
                raise _invalid()
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _event(
        self,
        connection: sqlite3.Connection,
        value: BaseModel,
        *,
        kind: Literal["tree", "version", "head", "proposal", "operation", "admission"],
        record_id: str,
        project_id: str,
        event_type: str,
        event_id: str | None = None,
    ) -> str:
        event_id = event_id or self.ids.new(IdPrefix.EVENT)
        _append(
            connection,
            event_id=event_id,
            project_id=project_id,
            event_type=event_type,
            kind=kind,
            record_id=record_id,
            value=value,
            created_at=self.clock.now(),
            redactor=self.redactor,
        )
        return event_id

    def _tree(self, connection: sqlite3.Connection, tree_sha256: str) -> OrganizationTree:
        row = connection.execute(
            "SELECT * FROM organization_trees WHERE tree_sha256=?", (tree_sha256,)
        ).fetchone()
        if row is None:
            raise _invalid()
        tree = _decode(OrganizationTree, row["data_json"], self.redactor)
        self._tree_metadata(tree)
        if tree.sha256 != tree_sha256 or row["tree_sha256"] != tree.sha256:
            raise _invalid()
        _receipt(connection, row["audit_event_id"], "tree", tree.sha256, tree, self.redactor)
        return tree

    def _tree_metadata(self, tree: OrganizationTree) -> None:
        entries: tuple[OrganizationFile | OrganizationDirectory, ...] = (
            *tree.files,
            *tree.directories,
        )
        for item in entries:
            for attribute in item.xattrs:
                raw = base64.b64decode(attribute.value_base64, validate=True)
                # Scan valid UTF-8 subsequences without changing the exact opaque bytes stored.
                decoded = raw.decode("utf-8", errors="replace")
                if self.redactor.contains_secret(attribute.value_base64) or (
                    self.redactor.contains_secret(decoded)
                ):
                    raise _invalid()

    def _store_tree(
        self, connection: sqlite3.Connection, project_id: str, tree: OrganizationTree
    ) -> None:
        tree = _validated(OrganizationTree, tree, self.redactor)
        self._tree_metadata(tree)
        if (
            connection.execute(
                "SELECT 1 FROM organization_trees WHERE tree_sha256=?", (tree.sha256,)
            ).fetchone()
            is not None
        ):
            if self._tree(connection, tree.sha256) != tree:
                raise _invalid()
            return
        event_id = self._event(
            connection,
            tree,
            kind="tree",
            record_id=tree.sha256,
            project_id=project_id,
            event_type="organization.tree_recorded",
        )
        connection.execute(
            "INSERT INTO organization_trees VALUES(?,?,?)",
            (tree.sha256, event_id, tree.model_dump_json()),
        )

    def _configuration_hash(self, tree: OrganizationTree) -> str:
        _, snapshot = self.config.snapshot_from_files(
            {item.path: item.content for item in tree.files}
        )
        return self.config.snapshot_hash(snapshot)

    def _save_head(self, connection: sqlite3.Connection, head: OrganizationHead) -> None:
        self._event(
            connection,
            head,
            kind="head",
            record_id=head.project_id,
            project_id=head.project_id,
            event_type="organization.head_updated",
            event_id=head.audit_event_id,
        )
        connection.execute(
            "INSERT INTO organization_heads VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(project_id) "
            "DO UPDATE SET revision=excluded.revision,tree_sha256=excluded.tree_sha256,"
            "config_snapshot_sha256=excluded.config_snapshot_sha256,"
            "project_sha256=excluded.project_sha256,pending_operation_id=excluded.pending_operation_id,"
            "audit_event_id=excluded.audit_event_id,data_json=excluded.data_json",
            (
                head.project_id,
                head.revision,
                head.tree_sha256,
                head.config_snapshot_sha256,
                head.project_sha256,
                head.pending_operation_id,
                head.audit_event_id,
                head.model_dump_json(),
            ),
        )

    def _save_version(self, connection: sqlite3.Connection, value: OrganizationVersion) -> None:
        self._event(
            connection,
            value,
            kind="version",
            record_id=f"{value.project_id}:{value.version}",
            project_id=value.project_id,
            event_type="organization.version_recorded",
            event_id=value.audit_event_id,
        )
        connection.execute(
            "INSERT INTO organization_versions VALUES(?,?,?,?,?,?,?,?)",
            (
                value.project_id,
                value.version,
                value.predecessor_version,
                value.tree_sha256,
                value.config_snapshot_sha256,
                value.operation_id,
                value.audit_event_id,
                value.model_dump_json(),
            ),
        )

    @_boundary
    def get_head(self, project_id: str) -> OrganizationHead | None:
        with self._transaction() as connection:
            value = _head(connection, project_id, self.redactor)
            if value is not None:
                tree = self._tree(connection, value.tree_sha256)
                if self._configuration_hash(tree) != value.config_snapshot_sha256:
                    raise _invalid()
            return value

    @_boundary
    def register_baseline(
        self, project: Project, tree: OrganizationTree, config_snapshot_sha256: str
    ) -> OrganizationHead:
        project = _validated(Project, project, self.redactor)
        tree = _validated(OrganizationTree, tree, self.redactor)
        if (
            self._configuration_hash(tree) != config_snapshot_sha256
            or project.fleet_spec_hash != config_snapshot_sha256
        ):
            raise _invalid()
        with self._transaction() as connection:
            if _project(connection, project.project_id, self.redactor) != project:
                raise _invalid()
            existing = _head(connection, project.project_id, self.redactor)
            if existing is not None:
                if (
                    existing.pending_operation_id is not None
                    or existing.project_sha256 != _hash(project)
                    or existing.tree_sha256 != tree.sha256
                    or existing.config_snapshot_sha256 != config_snapshot_sha256
                    or self._tree(connection, tree.sha256) != tree
                ):
                    raise _invalid()
                return existing
            self._store_tree(connection, project.project_id, tree)
            version = OrganizationVersion(
                project_id=project.project_id,
                version=0,
                tree_sha256=tree.sha256,
                config_snapshot_sha256=config_snapshot_sha256,
                project_sha256=_hash(project),
                created_at=self.clock.now(),
                audit_event_id=self.ids.new(IdPrefix.EVENT),
            )
            self._save_version(connection, version)
            head = OrganizationHead(
                **version.admission.model_dump(),
                project_sha256=_hash(project),
                audit_event_id=self.ids.new(IdPrefix.EVENT),
            )
            self._save_head(connection, head)
            return head

    @_boundary
    def get_tree(self, tree_sha256: str) -> OrganizationTree:
        with self._transaction() as connection:
            return self._tree(connection, tree_sha256)

    def _proposal(
        self, connection: sqlite3.Connection, proposal_id: str
    ) -> FleetPatchProposalRecord:
        row = connection.execute(
            "SELECT * FROM organization_proposals WHERE proposal_id=?", (proposal_id,)
        ).fetchone()
        if row is None:
            raise _invalid()
        value = _decode(FleetPatchProposalRecord, row["data_json"], self.redactor)
        if (
            value.patch.fleet_patch_id != proposal_id
            or value.patch.project_id != row["project_id"]
            or value.source_run_id != row["source_run_id"]
            or value.base.revision != row["base_revision"]
            or value.proposal_sha256 != row["proposal_sha256"]
            or value.before_tree_sha256 != row["before_tree_sha256"]
            or value.after_tree_sha256 != row["after_tree_sha256"]
            or value.created_at.isoformat() != row["created_at"]
            or value.audit_event_id is None
            or value.audit_event_id != row["audit_event_id"]
        ):
            raise _invalid()
        _receipt(
            connection,
            value.audit_event_id,
            "proposal",
            proposal_id,
            value,
            self.redactor,
            project_id=value.patch.project_id,
        )
        self._validate_proposal(
            connection,
            value,
            self._tree(connection, value.before_tree_sha256),
            self._tree(connection, value.after_tree_sha256),
        )
        return value

    def _rollback_target(
        self, connection: sqlite3.Connection, record: FleetPatchProposalRecord
    ) -> OrganizationTree | None:
        if record.patch.rollback_of is None:
            return None
        version = _version(connection, record.base.project_id, record.base.revision, self.redactor)
        if version.operation_id is None:
            raise _invalid()
        operation = self._operation_record(connection, version.operation_id)
        if (
            operation.status != "committed"
            or operation.proposal_id != record.patch.rollback_of
            or operation.committed_version != version.version
        ):
            raise _invalid()
        row = connection.execute(
            "SELECT * FROM organization_proposals WHERE proposal_id=?", (record.patch.rollback_of,)
        ).fetchone()
        if row is None:
            raise _invalid()
        original = _decode(FleetPatchProposalRecord, row["data_json"], self.redactor)
        if (
            original.audit_event_id is None
            or original.source_run_id != record.source_run_id
            or original.after_tree_sha256 != record.before_tree_sha256
            or original.proposal_sha256 != operation.proposal_sha256
        ):
            raise _invalid()
        _receipt(
            connection,
            original.audit_event_id,
            "proposal",
            original.patch.fleet_patch_id,
            original,
            self.redactor,
            project_id=record.base.project_id,
        )
        return self._tree(connection, original.before_tree_sha256)

    def _validate_proposal(
        self,
        connection: sqlite3.Connection,
        record: FleetPatchProposalRecord,
        before: OrganizationTree,
        after: OrganizationTree,
    ) -> None:
        validate_fleet_patch(
            record.patch,
            current_fleet_spec_sha256=record.base.config_snapshot_sha256,
            redactor=self.redactor,
        )
        source = _run(connection, record.source_run_id, self.redactor)
        if source.project_id != record.base.project_id or (
            record.patch.rollback_of is None
            and source.config_snapshot_hash != record.base.config_snapshot_sha256
        ):
            raise _invalid()
        if (
            _version(
                connection, record.base.project_id, record.base.revision, self.redactor
            ).admission
            != record.base
            or before.sha256 != record.before_tree_sha256
            or after.sha256 != record.after_tree_sha256
            or self._configuration_hash(before) != record.before_config_snapshot_sha256
            or self._configuration_hash(after) != record.after_config_snapshot_sha256
        ):
            raise _invalid()
        text, semantics = describe_fleet_patch(
            before, after, record.patch, rollback_target=self._rollback_target(connection, record)
        )
        if text != record.text_diff or semantics != record.semantic_changes:
            raise _invalid()

    @_boundary
    def save_proposal(
        self, record: FleetPatchProposalRecord, before: OrganizationTree, after: OrganizationTree
    ) -> FleetPatchProposalRecord:
        record = _validated(FleetPatchProposalRecord, record, self.redactor)
        before = _validated(OrganizationTree, before, self.redactor)
        after = _validated(OrganizationTree, after, self.redactor)
        with self._transaction() as connection:
            if (
                connection.execute(
                    "SELECT 1 FROM organization_proposals WHERE proposal_id=?",
                    (record.patch.fleet_patch_id,),
                ).fetchone()
                is not None
            ):
                existing = self._proposal(connection, record.patch.fleet_patch_id)
                if (
                    existing.proposal_sha256 != record.proposal_sha256
                    or (
                        record.audit_event_id is not None
                        and record.audit_event_id != existing.audit_event_id
                    )
                    or self._tree(connection, existing.before_tree_sha256) != before
                    or self._tree(connection, existing.after_tree_sha256) != after
                ):
                    raise _invalid()
                return existing
            head = _head(connection, record.base.project_id, self.redactor)
            if (
                head is None
                or head.pending_operation_id is not None
                or head.admission != record.base
                or record.audit_event_id is not None
            ):
                raise _invalid()
            self._validate_proposal(connection, record, before, after)
            self._store_tree(connection, record.base.project_id, before)
            self._store_tree(connection, record.base.project_id, after)
            record = record.model_copy(update={"audit_event_id": self.ids.new(IdPrefix.EVENT)})
            self._event(
                connection,
                record,
                kind="proposal",
                record_id=record.patch.fleet_patch_id,
                project_id=record.base.project_id,
                event_type="fleet_patch.proposed",
                event_id=record.audit_event_id,
            )
            connection.execute(
                "INSERT INTO organization_proposals VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    record.patch.fleet_patch_id,
                    record.base.project_id,
                    record.source_run_id,
                    record.base.revision,
                    record.proposal_sha256,
                    record.before_tree_sha256,
                    record.after_tree_sha256,
                    record.created_at.isoformat(),
                    record.audit_event_id,
                    record.model_dump_json(),
                ),
            )
            return record

    @_boundary
    def get_proposal(self, proposal_id: str) -> FleetPatchProposalRecord:
        with self._transaction() as connection:
            return self._proposal(connection, proposal_id)

    @_boundary
    def list_proposals(
        self, project_id: str, *, limit: int = 50
    ) -> tuple[FleetPatchProposalRecord, ...]:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise _invalid()
        with self._transaction() as connection:
            _project(connection, project_id, self.redactor)
            rows = connection.execute(
                "SELECT proposal_id FROM organization_proposals WHERE project_id=? "
                "ORDER BY created_at DESC,proposal_id LIMIT ?",
                (project_id, limit),
            ).fetchall()
            return tuple(self._proposal(connection, row["proposal_id"]) for row in rows)

    @_boundary
    def get_version(self, project_id: str, version: int) -> OrganizationVersion:
        if type(version) is not int or version < 0:
            raise _invalid()
        with self._transaction() as connection:
            value = _version(connection, project_id, version, self.redactor)
            if (
                self._configuration_hash(self._tree(connection, value.tree_sha256))
                != value.config_snapshot_sha256
            ):
                raise _invalid()
            return value

    def _operation_record(
        self, connection: sqlite3.Connection, operation_id: str
    ) -> OrganizationOperation:
        row = connection.execute(
            "SELECT * FROM organization_operations WHERE operation_id=?", (operation_id,)
        ).fetchone()
        if row is None:
            raise _invalid()
        value = _decode(OrganizationOperation, row["data_json"], self.redactor)
        if (
            any(
                getattr(value, key) != row[key]
                for key in ("operation_id", "proposal_id", "status", "audit_event_id")
            )
            or value.base.project_id != row["project_id"]
            or value.base.revision != row["base_revision"]
        ):
            raise _invalid()
        _receipt(
            connection,
            value.audit_event_id,
            "operation",
            operation_id,
            value,
            self.redactor,
            project_id=value.base.project_id,
        )
        return value

    def _operation(
        self, connection: sqlite3.Connection, operation_id: str
    ) -> OrganizationOperation:
        value = self._operation_record(connection, operation_id)
        proposal = self._proposal(connection, value.proposal_id)
        if (
            proposal.proposal_sha256 != value.proposal_sha256
            or proposal.base != value.base
            or proposal.after_tree_sha256 != value.publication.after_sha256
            or (proposal.patch.rollback_of is not None) != (value.authorization == "rollback")
        ):
            raise _invalid()
        head = _head(connection, value.base.project_id, self.redactor)
        if head is None:
            raise _invalid()
        if value.status in {"prepared", "recovery_required"} and (
            head.pending_operation_id != operation_id
            or head.admission != value.base
            or head.project_sha256 != value.project_sha256
        ):
            raise _invalid()
        if value.status == "committed":
            version = _version(
                connection, value.base.project_id, value.committed_version or 0, self.redactor
            )
            if (
                version.operation_id != operation_id
                or version.tree_sha256 != proposal.after_tree_sha256
                or version.config_snapshot_sha256 != proposal.after_config_snapshot_sha256
            ):
                raise _invalid()
        return value

    @_boundary
    def get_operation(self, operation_id: str) -> OrganizationOperation:
        with self._transaction() as connection:
            return self._operation(connection, operation_id)

    @_boundary
    def operation_for_proposal(self, proposal_id: str) -> OrganizationOperation | None:
        with self._transaction() as connection:
            self._proposal(connection, proposal_id)
            row = connection.execute(
                "SELECT operation_id FROM organization_operations WHERE proposal_id=?",
                (proposal_id,),
            ).fetchone()
            return self._operation(connection, row["operation_id"]) if row else None

    def _save_operation(
        self, connection: sqlite3.Connection, value: OrganizationOperation, *, new: bool = False
    ) -> None:
        value = _validated(OrganizationOperation, value, self.redactor)
        self._event(
            connection,
            value,
            kind="operation",
            record_id=value.operation_id,
            project_id=value.base.project_id,
            event_type="fleet_patch." + value.status,
            event_id=value.audit_event_id,
        )
        if new:
            connection.execute(
                "INSERT INTO organization_operations VALUES(?,?,?,?,?,?,?)",
                (
                    value.operation_id,
                    value.proposal_id,
                    value.base.project_id,
                    value.base.revision,
                    value.status,
                    value.audit_event_id,
                    value.model_dump_json(),
                ),
            )
        else:
            connection.execute(
                "UPDATE organization_operations SET status=?,audit_event_id=?,data_json=? "
                "WHERE operation_id=?",
                (value.status, value.audit_event_id, value.model_dump_json(), value.operation_id),
            )

    def _blockers(self, connection: sqlite3.Connection, project_id: str) -> None:
        rows = connection.execute(
            "SELECT run_id FROM runs WHERE project_id=? LIMIT 10001", (project_id,)
        ).fetchall()
        if len(rows) > 10000:
            raise _invalid()
        for row in rows:
            run = _run(connection, row["run_id"], self.redactor)
            if run.status.value in {
                "created",
                "running",
                "waiting_for_children",
                "paused_for_approval",
                "applying",
            }:
                raise _invalid()
        leases = connection.execute(
            "SELECT l.* FROM resource_leases l JOIN runs r ON r.run_id=l.run_id "
            "WHERE r.project_id=? LIMIT 10001",
            (project_id,),
        ).fetchall()
        if len(leases) > 10000:
            raise _invalid()
        for row in leases:
            lease = _decode(ResourceLease, row["data_json"], self.redactor)
            if (
                lease.lease_id != row["lease_id"]
                or lease.run_id != row["run_id"]
                or lease.resource_id != row["resource_id"]
                or lease.kind.value != row["kind"]
                or lease.status.value != row["status"]
                or lease.status.value not in {"released", "recovered"}
            ):
                raise _invalid()
        self._claim_blockers(connection, project_id)

    def _claim_blockers(self, connection: sqlite3.Connection, project_id: str) -> None:
        from agent_fleet.adapters.persistence.conversations import SqliteConversationStore
        from agent_fleet.adapters.persistence.graphs import _Manifest
        from agent_fleet.adapters.persistence.sqlite import SqliteStateStore
        from agent_fleet.domain.conversation import ConversationTurnStatus
        from agent_fleet.domain.graph import GraphDriverClaim, GraphSnapshot

        rows = connection.execute(
            "SELECT c.* FROM conversation_turn_claims c JOIN runs r ON r.run_id=c.run_id "
            "WHERE r.project_id=? LIMIT 10001",
            (project_id,),
        ).fetchall()
        if len(rows) > 10000:
            raise _invalid()
        # These validators reuse this exact transaction; construction has no database effects.
        conversations = SqliteConversationStore(
            self.database_path,
            self.clock,
            self.ids,
            self.redactor,
            SqliteStateStore(self.database_path, self.clock, self.ids, self.redactor),
        )
        for row in rows:
            claim = conversations._claim_row(connection, row)
            turn = conversations._turn_for_run(connection, claim.run_id)
            if (
                claim.project_id != project_id
                or row["status"] not in {"released", "fenced"}
                or row["released_at"] is None
                or turn is None
                or turn.active_claim_id is not None
                or turn.status
                not in {
                    ConversationTurnStatus.DELIVERED,
                    ConversationTurnStatus.FAILED,
                    ConversationTurnStatus.CANCELLED,
                }
                or claim.generation > turn.owner_generation
                or any(
                    getattr(claim, key) != getattr(turn.binding, key)
                    for key in ("conversation_id", "turn_id", "project_id", "run_id")
                )
            ):
                raise _invalid()
            event_row = connection.execute(
                "SELECT * FROM run_events WHERE event_id=?", (row["record_event_id"],)
            ).fetchone()
            event = self._existing_event(event_row)
            turn_row = connection.execute(
                "SELECT record_event_id FROM conversation_turns WHERE turn_id=?", (claim.turn_id,)
            ).fetchone()
            for record_id, event_id in (
                (claim.claim_id, row["record_event_id"]),
                (claim.turn_id, turn_row["record_event_id"]),
            ):
                latest = connection.execute(
                    "SELECT * FROM run_events WHERE run_id=? AND event_type LIKE 'conversation.%' "
                    "AND json_extract(data_json,'$.payload.record_id')=? "
                    "ORDER BY sequence DESC LIMIT 1",
                    (claim.run_id, record_id),
                ).fetchone()
                if self._existing_event(latest).event_id != event_id:
                    raise _invalid()
            if (
                event.project_id != project_id
                or event.run_id != claim.run_id
                or event.event_type
                != (
                    "conversation.claim_released"
                    if row["status"] == "released"
                    else "conversation.claim_fenced"
                )
                or event.payload
                != {
                    "record_type": "claim",
                    "record_id": claim.claim_id,
                    "record_sha256": canonical_json_hash(
                        {
                            "claim": claim.model_dump(mode="json"),
                            "status": row["status"],
                            "released_at": row["released_at"],
                        }
                    ),
                }
            ):
                raise _invalid()
            if row["status"] == "fenced":
                settled_row = connection.execute(
                    "SELECT * FROM run_events WHERE event_id=?", (turn_row["record_event_id"],)
                ).fetchone()
                if (
                    self._existing_event(settled_row).event_type != "conversation.turn_reconciled"
                    or claim.generation != turn.owner_generation
                    or turn.fenced_at is None
                    or turn.settled_at is None
                    or turn.settled_at < turn.fenced_at
                ):
                    raise _invalid()
        graphs = connection.execute(
            "SELECT * FROM fleet_graphs WHERE project_id=? LIMIT 10001", (project_id,)
        ).fetchall()
        if len(graphs) > 10000:
            raise _invalid()
        if (
            connection.execute(
                "SELECT 1 FROM fleet_graph_driver_claims c JOIN runs r ON r.run_id=c.parent_run_id "
                "LEFT JOIN fleet_graphs g ON g.parent_run_id=c.parent_run_id "
                "WHERE r.project_id=? AND g.parent_run_id IS NULL LIMIT 1",
                (project_id,),
            ).fetchone()
            is not None
            or connection.execute(
                "SELECT 1 FROM run_events e LEFT JOIN fleet_graphs g ON g.parent_run_id=e.run_id "
                "WHERE e.project_id=? AND e.event_type='graph.initialized' "
                "AND g.parent_run_id IS NULL LIMIT 1",
                (project_id,),
            ).fetchone()
            is not None
        ):
            raise _invalid()
        for row in graphs:
            graph = _decode(GraphSnapshot, row["data_json"], self.redactor)
            manifest = _decode(_Manifest, row["immutable_manifest_json"], self.redactor)
            if (
                graph.project_id != project_id
                or graph.parent_run_id != row["parent_run_id"]
                or graph.revision != row["revision"]
                or graph.driver_generation != row["driver_generation"]
                or graph.status.value != row["status"]
                or graph.driver_claim is not None
                or row["driver_claim_id"] is not None
                or graph.plan_sha256 != row["plan_sha256"]
                or any(
                    getattr(graph, key) != getattr(manifest.snapshot, key)
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
            claims = connection.execute(
                "SELECT * FROM fleet_graph_driver_claims WHERE parent_run_id=? ORDER BY generation",
                (graph.parent_run_id,),
            ).fetchall()
            for claim_row in claims:
                driver = _decode(GraphDriverClaim, claim_row["data_json"], self.redactor)
                if (
                    driver.claim_id != claim_row["claim_id"]
                    or driver.parent_run_id != graph.parent_run_id
                    or driver.generation != claim_row["generation"]
                    or driver.plan_sha256 != claim_row["plan_sha256"]
                    or driver.claimed_at.isoformat() != claim_row["claimed_at"]
                    or claim_row["status"] not in {"released", "cancelled"}
                    or claim_row["released_at"] is None
                ):
                    raise _invalid()
            if len(claims) != graph.driver_generation:
                raise _invalid()
            latest = connection.execute(
                "SELECT * FROM run_events WHERE run_id=? AND event_type IN "
                "('graph.initialized','graph.driver_claimed','graph.continuation_claimed',"
                "'graph.driver_released','graph.join_prepared','graph.join_completed',"
                "'graph.cancel_requested') ORDER BY sequence DESC LIMIT 1",
                (graph.parent_run_id,),
            ).fetchone()
            event = self._existing_event(latest)
            if event.project_id != project_id:
                raise _invalid()
            if graph.revision == 0:
                if (
                    graph != manifest.snapshot
                    or event.event_type != "graph.initialized"
                    or event.payload != {"manifest_sha256": _hash(manifest)}
                ):
                    raise _invalid()
            elif (
                event.event_type
                not in {"graph.driver_released", "graph.join_completed", "graph.cancel_requested"}
                or event.payload.get("revision") != graph.revision
                or event.payload.get("snapshot_sha256") != _hash(graph)
            ):
                raise _invalid()

    def _existing_event(self, row: sqlite3.Row | None) -> FleetEvent:
        if row is None:
            raise _invalid()
        event = _decode(FleetEvent, row["data_json"], self.redactor)
        if (
            any(
                getattr(event, key) != row[key]
                for key in ("event_id", "project_id", "run_id", "sequence", "event_type")
            )
            or event.occurred_at.isoformat() != row["occurred_at"]
        ):
            raise _invalid()
        return event

    @_boundary
    def prepare_operation(
        self,
        project: Project,
        proposal_id: str,
        publication: PreparedPublication,
        *,
        authorization: Literal["apply", "rollback"],
        repository_before: OrganizationRepositoryBoundary,
    ) -> OrganizationOperation:
        project = _validated(Project, project, self.redactor)
        publication = _validated(PreparedPublication, publication, self.redactor)
        repository_before = _validated(
            OrganizationRepositoryBoundary, repository_before, self.redactor
        )
        try:
            with self._transaction() as connection:
                existing = connection.execute(
                    "SELECT operation_id FROM organization_operations "
                    "WHERE proposal_id=? OR operation_id=?",
                    (proposal_id, publication.operation_id),
                ).fetchall()
                if existing:
                    if (
                        len(existing) != 1
                        or existing[0]["operation_id"] != publication.operation_id
                    ):
                        raise _invalid()
                    operation = self._operation(connection, publication.operation_id)
                    if (
                        operation.project_before != project
                        or operation.publication != publication
                        or operation.repository_before != repository_before
                        or operation.authorization != authorization
                        or operation.proposal_id != proposal_id
                    ):
                        raise _invalid()
                    return operation
                proposal = self._proposal(connection, proposal_id)
                head = _head(connection, project.project_id, self.redactor)
                repository = repository_before.repository
                if (
                    head is None
                    or head.pending_operation_id is not None
                    or head.admission != proposal.base
                    or head.project_sha256 != _hash(project)
                    or publication.project_id != project.project_id
                    or publication.repository_identity != project.identity_hash
                    or publication.before_sha256 != proposal.before_tree_sha256
                    or publication.after_sha256 != proposal.after_tree_sha256
                    or (proposal.patch.rollback_of is not None) != (authorization == "rollback")
                    or authorization not in {"apply", "rollback"}
                    or repository.root != project.canonical_root
                    or repository.identity_hash != project.identity_hash
                    or repository_before.non_organization_status_sha256 != canonical_json_hash([])
                    or (
                        repository.status_porcelain
                        and repository.status_fingerprint != project.init_status_fingerprint
                    )
                ):
                    raise _invalid()
                self._blockers(connection, project.project_id)
                operation = OrganizationOperation(
                    operation_id=publication.operation_id,
                    proposal_id=proposal_id,
                    proposal_sha256=proposal.proposal_sha256,
                    base=proposal.base,
                    project_before=project,
                    project_sha256=_hash(project),
                    publication=publication,
                    repository_before=repository_before,
                    authorization=authorization,
                    status="prepared",
                    created_at=self.clock.now(),
                    updated_at=self.clock.now(),
                    audit_event_id=self.ids.new(IdPrefix.EVENT),
                )
                self._save_operation(connection, operation, new=True)
                self._save_head(
                    connection,
                    head.model_copy(
                        update={
                            "pending_operation_id": operation.operation_id,
                            "audit_event_id": self.ids.new(IdPrefix.EVENT),
                        }
                    ),
                )
                return operation
        except sqlite3.Error:
            pass
        # A commit may have succeeded before the driver reported an error. Never replay it.
        operation = self.get_operation(publication.operation_id)
        if (
            operation.project_before == project
            and operation.publication == publication
            and operation.repository_before == repository_before
            and operation.authorization == authorization
            and operation.proposal_id == proposal_id
        ):
            return operation
        raise _invalid()

    @_boundary
    def commit_operation(
        self, operation_id: str, project: Project, observation: PublicationObservation
    ) -> OrganizationVersion:
        project = _validated(Project, project, self.redactor)
        observation = _validated(PublicationObservation, observation, self.redactor)
        try:
            with self._transaction() as connection:
                operation = self._operation(connection, operation_id)
                if (
                    observation.prepared != operation.publication
                    or observation.state != "exchanged"
                ):
                    raise _invalid()
                if operation.status == "committed":
                    version = _version(
                        connection,
                        operation.base.project_id,
                        operation.committed_version or 0,
                        self.redactor,
                    )
                    if version.project_sha256 != _hash(project):
                        raise _invalid()
                    return version
                if operation.status not in {"prepared", "recovery_required"}:
                    raise _invalid()
                proposal = self._proposal(connection, operation.proposal_id)
                changes = {
                    key
                    for key, value in operation.project_before.model_dump(mode="json").items()
                    if project.model_dump(mode="json")[key] != value
                }
                if (
                    changes
                    - {
                        "fleet_spec_hash",
                        "config_snapshot_artifact_id",
                        "init_status_fingerprint",
                        "updated_at",
                    }
                    or project.fleet_spec_hash != proposal.after_config_snapshot_sha256
                    or project.config_snapshot_artifact_id is None
                    or project.init_status_fingerprint is None
                    or project.updated_at < operation.project_before.updated_at
                ):
                    raise _invalid()
                artifact_row = connection.execute(
                    "SELECT * FROM artifacts WHERE artifact_id=?",
                    (project.config_snapshot_artifact_id,),
                ).fetchone()
                if artifact_row is None:
                    raise _invalid()
                artifact = _decode(ArtifactMetadata, artifact_row["data_json"], self.redactor)
                if (
                    artifact.artifact_id != project.config_snapshot_artifact_id
                    or artifact.project_id != project.project_id
                    or artifact.kind is not ArtifactKind.CONFIG_SNAPSHOT
                    or artifact.sha256 != project.fleet_spec_hash
                ):
                    raise _invalid()
                if (
                    artifact_row["project_id"] != artifact.project_id
                    or artifact_row["kind"] != artifact.kind.value
                    or artifact_row["sha256"] != artifact.sha256
                ):
                    raise _invalid()
                self._blockers(connection, project.project_id)
                version = OrganizationVersion(
                    project_id=project.project_id,
                    version=operation.base.revision + 1,
                    predecessor_version=operation.base.revision,
                    predecessor_sha256=_hash(
                        _version(
                            connection, project.project_id, operation.base.revision, self.redactor
                        )
                    ),
                    tree_sha256=proposal.after_tree_sha256,
                    config_snapshot_sha256=proposal.after_config_snapshot_sha256,
                    project_sha256=_hash(project),
                    operation_id=operation_id,
                    created_at=self.clock.now(),
                    audit_event_id=self.ids.new(IdPrefix.EVENT),
                )
                self._save_version(connection, version)
                self._save_operation(
                    connection,
                    operation.model_copy(
                        update={
                            "status": "committed",
                            "committed_version": version.version,
                            "updated_at": self.clock.now(),
                            "audit_event_id": self.ids.new(IdPrefix.EVENT),
                        }
                    ),
                )
                prior_json = connection.execute(
                    "SELECT data_json FROM projects WHERE project_id=?", (project.project_id,)
                ).fetchone()[0]
                cursor = connection.execute(
                    "UPDATE projects SET data_json=? WHERE project_id=? AND data_json=?",
                    (project.model_dump_json(), project.project_id, prior_json),
                )
                if cursor.rowcount != 1:
                    raise _invalid()
                self._save_head(
                    connection,
                    OrganizationHead(
                        **version.admission.model_dump(),
                        project_sha256=version.project_sha256,
                        audit_event_id=self.ids.new(IdPrefix.EVENT),
                    ),
                )
                return version
        except sqlite3.Error:
            pass
        operation = self.get_operation(operation_id)
        if operation.status == "committed" and operation.committed_version is not None:
            version = self.get_version(operation.base.project_id, operation.committed_version)
            if (
                version.project_sha256 == _hash(project)
                and observation.prepared == operation.publication
                and observation.state == "exchanged"
            ):
                return version
        raise _invalid()

    @_boundary
    def abort_operation(
        self, operation_id: str, observation: PublicationObservation
    ) -> OrganizationOperation:
        observation = _validated(PublicationObservation, observation, self.redactor)
        with self._transaction() as connection:
            operation = self._operation(connection, operation_id)
            if (
                observation.prepared != operation.publication
                or observation.state != "prepared"
                or operation.status == "committed"
            ):
                raise _invalid()
            if operation.status == "aborted":
                return operation
            head = _head(connection, operation.base.project_id, self.redactor)
            if head is None or head.pending_operation_id != operation_id:
                raise _invalid()
            operation = operation.model_copy(
                update={
                    "status": "aborted",
                    "updated_at": self.clock.now(),
                    "audit_event_id": self.ids.new(IdPrefix.EVENT),
                }
            )
            self._save_operation(connection, operation)
            self._save_head(
                connection,
                head.model_copy(
                    update={
                        "pending_operation_id": None,
                        "audit_event_id": self.ids.new(IdPrefix.EVENT),
                    }
                ),
            )
            return operation

    @_boundary
    def require_recovery(self, operation_id: str) -> OrganizationOperation:
        with self._transaction() as connection:
            operation = self._operation(connection, operation_id)
            if operation.status == "recovery_required":
                return operation
            if operation.status != "prepared":
                raise _invalid()
            operation = operation.model_copy(
                update={
                    "status": "recovery_required",
                    "updated_at": self.clock.now(),
                    "audit_event_id": self.ids.new(IdPrefix.EVENT),
                }
            )
            self._save_operation(connection, operation)
            return operation

    @_boundary
    def admission_for_run(self, run_id: str) -> OrganizationAdmission | None:
        with self._transaction() as connection:
            run = _run(connection, run_id, self.redactor)
            return _admission(connection, run, self.redactor)

    @_boundary
    def assert_current(self, admission: OrganizationAdmission) -> OrganizationHead:
        admission = _validated(OrganizationAdmission, admission, self.redactor)
        with self._transaction() as connection:
            head = _head(connection, admission.project_id, self.redactor)
            if head is None or head.pending_operation_id is not None or head.admission != admission:
                raise _invalid()
            if (
                self._configuration_hash(self._tree(connection, head.tree_sha256))
                != head.config_snapshot_sha256
            ):
                raise _invalid()
            return head
