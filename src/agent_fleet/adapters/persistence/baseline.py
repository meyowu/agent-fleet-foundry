"""Exact-once baseline owners and immutable facts in ten separate SQLite tables."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import timedelta
from functools import wraps
from typing import Literal

from pydantic import TypeAdapter, ValidationError

from agent_fleet.adapters.persistence.sqlite import SUPPORTED_SCHEMA_VERSION, SqliteStateStore
from agent_fleet.domain.baseline import (
    MAX_OBSERVATION_BYTES,
    BaselineAuthorization,
    BaselineCommandObservation,
    BaselineExecution,
    BaselineModel,
    BaselineObservationRef,
    BaselineReport,
    BaselineReportRef,
    BaselineReview,
    InstallationId,
    baseline_id,
    canonical,
    reconstruct_sandbox,
    sandbox_policy,
    snapshot_model,
)
from agent_fleet.domain.baseline_resources import (
    BaselineCleanupClaim,
    BaselineCleanupReceipt,
    BaselineCommandPayload,
    BaselineControlInspection,
    BaselineDispatchClaim,
    BaselineExecRequest,
    BaselineExecutionHandle,
    BaselineOwnerClaim,
    BaselineResourceLease,
    BaselineResourceOwner,
    BaselineResourceSnapshot,
    BaselineSandboxHandle,
    BaselineSandboxInspection,
    BaselineSandboxPayload,
    BaselineShow,
    BaselineStoppedOwnerReview,
    BaselineWorkspace,
    BaselineWorkspacePayload,
    baseline_sandbox_handle,
)
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import SandboxCleanupResult
from agent_fleet.domain.security import sha256_bytes

_TABLES = frozenset(
    {
        "baseline_executions",
        "baseline_reviews",
        "baseline_authorizations",
        "baseline_owner_claims",
        "baseline_dispatch_claims",
        "baseline_resource_leases",
        "baseline_command_observations",
        "baseline_reports",
        "baseline_cleanup_receipts",
    }
)


def unavailable() -> FleetError:
    return FleetError(
        ErrorCode.RECOVERY_REQUIRED,
        "The exact baseline ownership or retained evidence is unavailable.",
        "Inspect the original baseline; do not replay or replace its permanent claims.",
    )


def _boundary[**P, R](operation: Callable[P, R]) -> Callable[P, R]:
    @wraps(operation)
    def call(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return operation(*args, **kwargs)
        except FleetError as caught:
            error = caught
        except (ValidationError, ValueError, TypeError, KeyError, UnicodeError, OverflowError):
            error = unavailable()
        except (sqlite3.Error, OSError):
            error = FleetError(
                ErrorCode.STATE_UNAVAILABLE,
                "The migrated baseline store is unavailable.",
                "Restore the selected local state before using baseline commands.",
            )
        error.__context__ = None
        raise error from None

    return call


def _replace[T: BaselineModel](value: T, **changes: object) -> T:
    data = value.model_dump(mode="json", by_alias=True)
    data.update(changes)
    return type(value).model_validate_json(canonical(data))


def _pid_absent(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except OSError:
        return False
    return False


class SqliteBaselineStore:
    def __init__(self, state: SqliteStateStore, *, installation_id: str) -> None:
        self.state = state
        self.installation_id = TypeAdapter(InstallationId).validate_python(
            installation_id, strict=True
        )

    @contextmanager
    def _transaction(self, *, write: bool) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(
            f"{self.state.database_path.absolute().as_uri()}?mode=rw", uri=True
        )
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=5000")
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            versions = [
                row[0]
                for row in connection.execute(
                    "SELECT version FROM schema_migrations ORDER BY version LIMIT ?",
                    (SUPPORTED_SCHEMA_VERSION + 2,),
                )
            ]
            if versions != list(range(1, SUPPORTED_SCHEMA_VERSION + 1)):
                raise FleetError(
                    ErrorCode.STATE_SCHEMA_INCOMPATIBLE,
                    "The baseline store requires the complete current migrated schema.",
                    "Explicitly migrate a compatible local database first.",
                )
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _encode(self, value: BaselineModel) -> bytes:
        raw = value.canonical_bytes()
        value = type(value).from_canonical(raw)
        if self.state.redactor.contains_secret_data(value.model_dump(mode="json", by_alias=True)):
            raise unavailable()
        return raw

    def _identity(self, value: BaselineModel) -> tuple[str, str, int]:
        if isinstance(value, BaselineReview):
            return value.review_id, value.baseline_id, 0
        if isinstance(value, BaselineExecution):
            return value.baseline_id, value.baseline_id, value.revision
        if isinstance(value, BaselineAuthorization):
            return value.authorization_id, value.baseline_id, value.revision
        if isinstance(value, BaselineOwnerClaim):
            return value.claim_id, value.owner.baseline_id, 0
        if isinstance(value, BaselineDispatchClaim):
            return value.request.execution_id, value.owner.baseline_id, 0
        if isinstance(value, BaselineResourceLease):
            return value.lease_id, value.owner.baseline_id, value.revision
        if isinstance(value, BaselineCommandObservation):
            return f"bobs_{value.digest}", value.baseline_id, 0
        if isinstance(value, BaselineReport):
            return f"brpt_{value.digest}", value.baseline_id, 0
        if isinstance(value, BaselineCleanupReceipt):
            return value.digest, value.owner.baseline_id, 0
        raise unavailable()

    def _rows(
        self, connection: sqlite3.Connection, table: str, key: str, value: str, *, limit: int = 2
    ) -> list[sqlite3.Row]:
        if table not in _TABLES or key not in {"record_id", "baseline_id"}:
            raise unavailable()
        extra = (
            ",kind"
            if table == "baseline_resource_leases"
            else (",execution_id" if table == "baseline_command_observations" else "")
        )
        return connection.execute(
            "SELECT CASE WHEN length(CAST(record_id AS BLOB))<=80 THEN record_id END AS record_id,"
            "CASE WHEN length(CAST(baseline_id AS BLOB))<=80 THEN baseline_id END AS baseline_id,"
            "revision,CASE WHEN length(CAST(record_sha256 AS BLOB))=64 "
            "THEN record_sha256 END AS record_sha256,"
            "CASE WHEN typeof(payload)='blob' AND length(payload)<=262144 "
            "THEN payload END AS payload"
            f"{extra} FROM {table} WHERE {key}=? ORDER BY record_id LIMIT ?",
            (value, limit),
        ).fetchall()

    def _decode[T: BaselineModel](self, row: sqlite3.Row, model: type[T]) -> T:
        raw = row["payload"]
        if type(raw) is not bytes:
            raise unavailable()
        value = model.from_canonical(raw)
        identity = self._identity(value)
        if (
            tuple(row[key] for key in ("record_id", "baseline_id", "revision")) != identity
            or type(row["revision"]) is not int
            or row["record_sha256"] != sha256_bytes(raw)
            or (isinstance(value, BaselineResourceLease) and row["kind"] != value.kind)
            or (
                isinstance(value, BaselineCommandObservation)
                and row["execution_id"] != value.execution_id
            )
        ):
            raise unavailable()
        self._encode(value)
        return value

    def _one[T: BaselineModel](
        self, connection: sqlite3.Connection, table: str, key: str, value: str, model: type[T]
    ) -> T:
        rows = self._rows(connection, table, key, value)
        if len(rows) != 1:
            raise unavailable()
        return self._decode(rows[0], model)

    def _insert(self, connection: sqlite3.Connection, table: str, value: BaselineModel) -> None:
        if table not in _TABLES:
            raise unavailable()
        record_id, owner_id, revision = self._identity(value)
        raw = self._encode(value)
        fields = "record_id,baseline_id,revision,record_sha256,payload"
        values: tuple[object, ...] = (record_id, owner_id, revision, sha256_bytes(raw), raw)
        if isinstance(value, BaselineResourceLease):
            fields += ",kind"
            values += (value.kind,)
        if isinstance(value, BaselineCommandObservation):
            fields += ",execution_id"
            values += (value.execution_id,)
        connection.execute(
            f"INSERT INTO {table} ({fields}) VALUES ({','.join('?' for _ in values)})", values
        )

    def _update(
        self,
        connection: sqlite3.Connection,
        table: str,
        original: BaselineModel,
        replacement: BaselineModel,
    ) -> None:
        if table not in {
            "baseline_executions",
            "baseline_authorizations",
            "baseline_resource_leases",
        }:
            raise unavailable()
        before, after = self._identity(original), self._identity(replacement)
        if before[:2] != after[:2] or after[2] != before[2] + 1:
            raise unavailable()
        raw = self._encode(replacement)
        count = connection.execute(
            f"UPDATE {table} SET revision=?,record_sha256=?,payload=? "
            "WHERE record_id=? AND baseline_id=? AND revision=? AND record_sha256=? AND payload=?",
            (after[2], sha256_bytes(raw), raw, *before, original.digest, self._encode(original)),
        ).rowcount
        if count != 1:
            raise unavailable()

    def _execution(self, connection: sqlite3.Connection, identity: str) -> BaselineExecution:
        return self._one(
            connection, "baseline_executions", "record_id", identity, BaselineExecution
        )

    def _review(self, connection: sqlite3.Connection, identity: str) -> BaselineReview:
        review = self._one(connection, "baseline_reviews", "record_id", identity, BaselineReview)
        execution = self._execution(connection, review.baseline_id)
        if (
            execution.review_id != review.review_id
            or execution.review_sha256 != review.digest
            or execution.project_id != review.project_id
        ):
            raise unavailable()
        return review

    def _owner(self, connection: sqlite3.Connection, identity: str) -> BaselineOwnerClaim:
        claim = self._one(
            connection, "baseline_owner_claims", "baseline_id", identity, BaselineOwnerClaim
        )
        execution = self._execution(connection, identity)
        review = self._review(connection, execution.review_id)
        authorization = self._one(
            connection,
            "baseline_authorizations",
            "record_id",
            claim.authorization_id,
            BaselineAuthorization,
        )
        if (
            execution.owner_claim_id != claim.claim_id
            or claim.owner.project_id != review.project_id
            or claim.owner.review_sha256 != review.digest
            or claim.installation_id != self.installation_id
            or authorization.baseline_id != identity
            or authorization.review_id != review.review_id
            or authorization.review_sha256 != review.digest
            or authorization.status != "consumed"
            or authorization.consumed_at != claim.claimed_at
        ):
            raise unavailable()
        return claim

    def _require_claim(
        self, connection: sqlite3.Connection, claim: BaselineOwnerClaim, *, active: bool = True
    ) -> BaselineExecution:
        fresh = BaselineOwnerClaim.from_canonical(self._encode(claim))
        if self._owner(connection, fresh.owner.baseline_id) != fresh:
            raise unavailable()
        execution = self._execution(connection, fresh.owner.baseline_id)
        if active and (
            execution.status not in {"owned", "executing"} or claim.controller_pid != os.getpid()
        ):
            raise unavailable()
        return execution

    def _bump(
        self, connection: sqlite3.Connection, original: BaselineExecution, **changes: object
    ) -> BaselineExecution:
        replacement = _replace(
            original,
            revision=original.revision + 1,
            updated_at=self.state.clock.now().isoformat(),
            **changes,
        )
        self._update(connection, "baseline_executions", original, replacement)
        return replacement

    @_boundary
    def create_review(self, review: BaselineReview) -> BaselineExecution:
        review = BaselineReview.from_canonical(self._encode(review))
        now = self.state.clock.now()
        if (
            review.installation_id != self.installation_id
            or review.created_at > now
            or review.expires_at <= now
        ):
            raise unavailable()
        execution = BaselineExecution(
            baseline_id=review.baseline_id,
            review_id=review.review_id,
            review_sha256=review.digest,
            project_id=review.project_id,
            revision=0,
            status="planned",
            created_at=now,
            updated_at=now,
        )
        with self._transaction(write=True) as connection:
            # Validate actual registered Project existence; this path never invents one.
            if (
                connection.execute(
                    "SELECT 1 FROM projects WHERE project_id=?", (review.project_id,)
                ).fetchone()
                is None
            ):
                raise unavailable()
            self._insert(connection, "baseline_executions", execution)
            self._insert(connection, "baseline_reviews", review)
        return execution

    @_boundary
    def review(self, review_id: str) -> BaselineReview:
        with self._transaction(write=False) as connection:
            return self._review(connection, review_id)

    @_boundary
    def authorize(self, review_id: str, review_sha256: str) -> BaselineAuthorization:
        with self._transaction(write=True) as connection:
            review = self._review(connection, review_id)
            execution = self._execution(connection, review.baseline_id)
            now = self.state.clock.now()
            if (
                review.digest != review_sha256
                or review.status != "ready"
                or not review.created_at <= now < review.expires_at
                or execution.status != "planned"
            ):
                raise unavailable()
            rows = self._rows(
                connection, "baseline_authorizations", "baseline_id", review.baseline_id
            )
            if rows:
                authorization = self._decode(rows[0], BaselineAuthorization)
                if (
                    len(rows) != 1
                    or authorization.review_sha256 != review.digest
                    or authorization.status != "available"
                ):
                    raise unavailable()
                return authorization
            authorization = BaselineAuthorization(
                authorization_id=baseline_id("bauth"),
                review_id=review_id,
                baseline_id=review.baseline_id,
                review_sha256=review.digest,
                revision=0,
                status="available",
                created_at=now,
                expires_at=review.expires_at,
            )
            self._insert(connection, "baseline_authorizations", authorization)
            return authorization

    @_boundary
    def revoke(self, review_id: str) -> BaselineExecution:
        with self._transaction(write=True) as connection:
            review = self._review(connection, review_id)
            execution = self._execution(connection, review.baseline_id)
            if execution.status == "revoked":
                return execution
            if execution.status != "planned":
                raise unavailable()
            rows = self._rows(
                connection, "baseline_authorizations", "baseline_id", review.baseline_id
            )
            if rows:
                authorization = self._decode(rows[0], BaselineAuthorization)
                if len(rows) != 1 or authorization.status != "available":
                    raise unavailable()
                self._update(
                    connection,
                    "baseline_authorizations",
                    authorization,
                    _replace(
                        authorization,
                        revision=authorization.revision + 1,
                        status="revoked",
                        revoked_at=self.state.clock.now().isoformat(),
                    ),
                )
            return self._bump(connection, execution, status="revoked")

    @_boundary
    def claim_baseline(
        self, review_id: str, review_sha256: str, authorization_id: str, expected_revision: int
    ) -> BaselineOwnerClaim:
        with self._transaction(write=True) as connection:
            review = self._review(connection, review_id)
            execution = self._execution(connection, review.baseline_id)
            authorization = self._one(
                connection,
                "baseline_authorizations",
                "record_id",
                authorization_id,
                BaselineAuthorization,
            )
            now = self.state.clock.now()
            if (
                execution.revision != expected_revision
                or execution.status != "planned"
                or review.status != "ready"
                or review.digest != review_sha256
                or not review.created_at <= now < review.expires_at
                or authorization.baseline_id != review.baseline_id
                or authorization.review_id != review_id
                or authorization.review_sha256 != review.digest
                or authorization.status != "available"
                or not authorization.created_at <= now < authorization.expires_at
            ):
                raise unavailable()
            claim = BaselineOwnerClaim(
                owner=BaselineResourceOwner(
                    baseline_id=review.baseline_id,
                    project_id=review.project_id,
                    review_sha256=review.digest,
                ),
                claim_id=baseline_id("bclaim"),
                authorization_id=authorization_id,
                controller_pid=os.getpid(),
                installation_id=self.installation_id,
                claimed_at=now,
            )
            self._update(
                connection,
                "baseline_authorizations",
                authorization,
                _replace(
                    authorization,
                    revision=authorization.revision + 1,
                    status="consumed",
                    consumed_at=now.isoformat(),
                ),
            )
            self._insert(connection, "baseline_owner_claims", claim)
            self._bump(connection, execution, status="owned", owner_claim_id=claim.claim_id)
            return claim

    @_boundary
    def owner_claim(self, baseline_id: str) -> BaselineOwnerClaim:
        with self._transaction(write=False) as connection:
            return self._owner(connection, baseline_id)

    def _snapshot(self, connection: sqlite3.Connection, identity: str) -> BaselineResourceSnapshot:
        execution = self._execution(connection, identity)
        claim = self._owner(connection, identity)
        review = self._review(connection, execution.review_id)
        rows = self._rows(connection, "baseline_resource_leases", "baseline_id", identity, limit=4)
        leases = tuple(self._decode(row, BaselineResourceLease) for row in rows)
        dispatches = self._rows(connection, "baseline_dispatch_claims", "baseline_id", identity)
        if len(dispatches) > 1:
            raise unavailable()
        dispatch = self._decode(dispatches[0], BaselineDispatchClaim) if dispatches else None
        snapshot = BaselineResourceSnapshot(
            execution=execution, claim=claim, dispatch=dispatch, leases=leases
        )
        commands = [lease for lease in leases if isinstance(lease.payload, BaselineCommandPayload)]
        if (dispatch is None) != (not commands):
            raise unavailable()
        if dispatch is not None:
            command = commands[0]
            assert isinstance(command.payload, BaselineCommandPayload)
            if (
                dispatch.lease_id != command.lease_id
                or dispatch.request != command.payload.request
                or dispatch.sandbox_spec_sha256 != command.payload.sandbox.sandbox_spec_sha256
            ):
                raise unavailable()
        workspaces = [
            item.payload.workspace
            for item in leases
            if isinstance(item.payload, BaselineWorkspacePayload)
        ]
        sandboxes = [
            item.payload for item in leases if isinstance(item.payload, BaselineSandboxPayload)
        ]
        if any(
            workspace.base_revision != review.base_revision
            or workspace.approved_source_sha256 != review.approved_source_sha256
            for workspace in workspaces
        ):
            raise unavailable()
        if sandboxes and (
            len(workspaces) != 1
            or sandboxes[0].spec.workspace != workspaces[0]
            or sandbox_policy(sandboxes[0].spec.sandbox) != review.sandbox_policy
        ):
            raise unavailable()
        if commands and (
            len(sandboxes) != 1
            or not isinstance(commands[0].payload, BaselineCommandPayload)
            or commands[0].payload.sandbox != sandboxes[0].handle
            or commands[0].payload.request.command != review.command
        ):
            raise unavailable()
        for lease in leases:
            if (
                isinstance(lease.payload, BaselineSandboxPayload)
                and lease.payload.handle is not None
                and lease.payload.handle
                != baseline_sandbox_handle(lease.payload.spec, lease.payload.sandbox_id, review)
            ):
                raise unavailable()
            if lease.receipt_sha256 is not None:
                receipt = self._one(
                    connection,
                    "baseline_cleanup_receipts",
                    "record_id",
                    lease.receipt_sha256,
                    BaselineCleanupReceipt,
                )
                if (
                    receipt.owner != claim.owner
                    or receipt.lease_id != lease.lease_id
                    or receipt.kind != lease.kind
                    or receipt.complete != (lease.status == "released")
                ):
                    raise unavailable()
                self._receipt_state(connection, receipt, expected=lease)
        return snapshot

    @_boundary
    def baseline_resource_snapshot(self, baseline_id: str) -> BaselineResourceSnapshot:
        with self._transaction(write=False) as connection:
            return self._snapshot(connection, baseline_id)

    @_boundary
    def reserve_baseline_lease(
        self, claim: BaselineOwnerClaim, lease: BaselineResourceLease
    ) -> BaselineResourceLease:
        lease = BaselineResourceLease.from_canonical(self._encode(lease))
        with self._transaction(write=True) as connection:
            execution = self._require_claim(connection, claim)
            review = self._review(connection, execution.review_id)
            snapshot = self._snapshot(connection, execution.baseline_id)
            if (
                lease.owner != claim.owner
                or lease.status != "creating"
                or lease.revision != 0
                or lease.kind == "execution"
                or any(item.kind == lease.kind for item in snapshot.leases)
            ):
                raise unavailable()
            if isinstance(lease.payload, BaselineWorkspacePayload):
                workspace = lease.payload.workspace
                if (
                    snapshot.leases
                    or workspace.approved_source_sha256 != review.approved_source_sha256
                    or workspace.base_revision != review.base_revision
                    or workspace.materialized_source_sha256 is not None
                ):
                    raise unavailable()
            elif isinstance(lease.payload, BaselineSandboxPayload):
                from agent_fleet.domain.baseline import sandbox_policy

                workspaces = [
                    item.payload.workspace
                    for item in snapshot.leases
                    if isinstance(item.payload, BaselineWorkspacePayload)
                    and item.status == "active"
                ]
                if (
                    len(workspaces) != 1
                    or lease.payload.spec.workspace != workspaces[0]
                    or sandbox_policy(lease.payload.spec.sandbox) != review.sandbox_policy
                    or lease.payload.handle is not None
                ):
                    raise unavailable()
            self._insert(connection, "baseline_resource_leases", lease)
            self._bump(connection, execution)
            return lease

    @_boundary
    def activate_baseline_lease(
        self,
        claim: BaselineOwnerClaim,
        lease_id: str,
        expected_revision: int,
        resource: BaselineWorkspace | BaselineSandboxHandle,
    ) -> BaselineResourceLease:
        with self._transaction(write=True) as connection:
            execution = self._require_claim(connection, claim)
            lease = self._one(
                connection, "baseline_resource_leases", "record_id", lease_id, BaselineResourceLease
            )
            if (
                lease.owner != claim.owner
                or lease.revision != expected_revision
                or lease.status != "creating"
            ):
                raise unavailable()
            payload = lease.payload
            if isinstance(payload, BaselineWorkspacePayload) and isinstance(
                resource, BaselineWorkspace
            ):
                expected = _replace(
                    payload.workspace,
                    materialized_source_sha256=payload.workspace.approved_source_sha256,
                )
                if resource != expected:
                    raise unavailable()
                replacement_payload: BaselineModel = BaselineWorkspacePayload(workspace=resource)
            elif isinstance(payload, BaselineSandboxPayload) and isinstance(
                resource, BaselineSandboxHandle
            ):
                review = self._review(connection, execution.review_id)
                if resource != baseline_sandbox_handle(payload.spec, payload.sandbox_id, review):
                    raise unavailable()
                replacement_payload = _replace(
                    payload, handle=resource.model_dump(mode="json", by_alias=True)
                )
            else:
                raise unavailable()
            replacement = _replace(
                lease,
                revision=lease.revision + 1,
                status="active",
                updated_at=self.state.clock.now().isoformat(),
                payload=replacement_payload.model_dump(mode="json", by_alias=True),
            )
            self._update(connection, "baseline_resource_leases", lease, replacement)
            self._bump(connection, execution)
            return replacement

    @_boundary
    def claim_baseline_dispatch(
        self,
        claim: BaselineOwnerClaim,
        expected_snapshot_sha256: str,
        request: BaselineExecRequest,
        lease: BaselineResourceLease,
    ) -> BaselineDispatchClaim:
        with self._transaction(write=True) as connection:
            execution = self._require_claim(connection, claim)
            snapshot = self._snapshot(connection, execution.baseline_id)
            review = self._review(connection, execution.review_id)
            sandboxes = [
                item.payload
                for item in snapshot.leases
                if item.kind == "sandbox" and item.status == "active"
            ]
            if (
                snapshot.digest != expected_snapshot_sha256
                or snapshot.dispatch is not None
                or len(snapshot.leases) != 2
                or any(item.status != "active" for item in snapshot.leases)
                or len(sandboxes) != 1
                or not isinstance(sandboxes[0], BaselineSandboxPayload)
                or not isinstance(lease.payload, BaselineCommandPayload)
                or lease.payload.handle is not None
                or lease.payload.creation_dispatched
                or lease.status != "creating"
                or lease.revision != 0
                or lease.owner != claim.owner
                or lease.payload.request != request
                or lease.payload.sandbox != sandboxes[0].handle
                or request.owner != claim.owner
                or request.claim_id != claim.claim_id
                or request.command != review.command
            ):
                raise unavailable()
            dispatch = BaselineDispatchClaim(
                owner=claim.owner,
                owner_claim=claim,
                request=request,
                lease_id=lease.lease_id,
                sandbox_spec_sha256=lease.payload.sandbox.sandbox_spec_sha256,
                resource_snapshot_sha256=snapshot.digest,
                claimed_at=self.state.clock.now(),
            )
            self._insert(connection, "baseline_resource_leases", lease)
            self._insert(connection, "baseline_dispatch_claims", dispatch)
            self._bump(connection, execution, status="executing")
            return dispatch

    def _execution_lease(
        self,
        connection: sqlite3.Connection,
        claim: BaselineOwnerClaim,
        lease_id: str,
        revision: int,
    ) -> tuple[BaselineExecution, BaselineResourceLease, BaselineCommandPayload]:
        execution = self._require_claim(connection, claim)
        snapshot = self._snapshot(connection, execution.baseline_id)
        matches = [item for item in snapshot.leases if item.lease_id == lease_id]
        if (
            len(matches) != 1
            or matches[0].revision != revision
            or matches[0].status != "creating"
            or not isinstance(matches[0].payload, BaselineCommandPayload)
        ):
            raise unavailable()
        return execution, matches[0], matches[0].payload

    @_boundary
    def mark_baseline_creation_dispatched(
        self, claim: BaselineOwnerClaim, lease_id: str, expected_revision: int
    ) -> BaselineResourceLease:
        with self._transaction(write=True) as connection:
            execution, lease, payload = self._execution_lease(
                connection, claim, lease_id, expected_revision
            )
            if payload.creation_dispatched:
                raise unavailable()
            replacement_payload = _replace(payload, creation_dispatched=True)
            replacement = _replace(
                lease,
                revision=lease.revision + 1,
                updated_at=self.state.clock.now().isoformat(),
                payload=replacement_payload.model_dump(mode="json", by_alias=True),
            )
            self._update(connection, "baseline_resource_leases", lease, replacement)
            self._bump(connection, execution)
            return replacement

    @_boundary
    def activate_baseline_execution(
        self,
        claim: BaselineOwnerClaim,
        lease_id: str,
        expected_revision: int,
        handle: BaselineExecutionHandle,
    ) -> BaselineResourceLease:
        with self._transaction(write=True) as connection:
            execution, lease, payload = self._execution_lease(
                connection, claim, lease_id, expected_revision
            )
            if not payload.creation_dispatched or payload.handle is not None:
                raise unavailable()
            replacement_payload = _replace(
                payload, handle=handle.model_dump(mode="json", by_alias=True)
            )
            replacement = _replace(
                lease,
                revision=lease.revision + 1,
                status="active",
                updated_at=self.state.clock.now().isoformat(),
                payload=replacement_payload.model_dump(mode="json", by_alias=True),
            )
            self._update(connection, "baseline_resource_leases", lease, replacement)
            self._bump(connection, execution)
            return replacement

    def _cleanup_event(
        self, connection: sqlite3.Connection, identity: str, *, scope_sha256: str | None = None
    ) -> BaselineCleanupClaim | None:
        selected = "" if scope_sha256 is None else " AND scope_sha256=?"
        parameters = (identity,) if scope_sha256 is None else (identity, scope_sha256)
        rows = connection.execute(
            "SELECT sequence,kind,scope_sha256,record_sha256,CASE WHEN typeof(payload)='blob' "
            "AND length(payload)<=262144 THEN payload END AS payload "
            f"FROM baseline_events WHERE baseline_id=?{selected} ORDER BY sequence DESC LIMIT 2",
            parameters,
        ).fetchall()
        if not rows:
            return None
        if scope_sha256 is not None and len(rows) != 1:
            raise unavailable()
        row = rows[0]
        claim = BaselineCleanupClaim.from_canonical(row["payload"])
        if (
            claim.owner.baseline_id != identity
            or claim.digest != row["record_sha256"]
            or claim.scope_sha256 != row["scope_sha256"]
            or row["kind"] != "cleanup_claimed"
            or type(row["sequence"]) is not int
        ):
            raise unavailable()
        owner = self._owner(connection, identity)
        execution = self._execution(connection, identity)
        if (
            claim.snapshot.claim != owner
            or claim.owner != owner.owner
            or claim.snapshot.execution.review_id != execution.review_id
            or claim.snapshot.execution.review_sha256 != execution.review_sha256
            or claim.snapshot.execution.owner_claim_id != owner.claim_id
            or claim.snapshot.execution.revision >= execution.revision
        ):
            raise unavailable()
        # Historical scope lookup cannot omit current permanent facts. Read the
        # bounded records directly: `_snapshot` would recurse through receipts.
        dispatch_rows = self._rows(
            connection, "baseline_dispatch_claims", "baseline_id", identity, limit=2
        )
        if len(dispatch_rows) > 1:
            raise unavailable()
        dispatch = self._decode(dispatch_rows[0], BaselineDispatchClaim) if dispatch_rows else None
        current_leases = tuple(
            self._decode(item, BaselineResourceLease)
            for item in self._rows(
                connection, "baseline_resource_leases", "baseline_id", identity, limit=4
            )
        )
        if claim.snapshot.dispatch != dispatch or (
            tuple(item.lease_id for item in claim.snapshot.leases)
            != tuple(item.lease_id for item in current_leases)
        ):
            raise unavailable()
        for original, current in zip(claim.snapshot.leases, current_leases, strict=True):
            if (
                original.owner != current.owner
                or original.payload != current.payload
                or original.created_at != current.created_at
                or original.revision > current.revision
                or original.updated_at > current.updated_at
                or (original.status == "released" and original != current)
                or (original.revision == current.revision and original != current)
                or (
                    original.revision < current.revision
                    and (
                        current.status not in {"failed", "released"}
                        or current.receipt_sha256 is None
                    )
                )
            ):
                raise unavailable()
        return claim

    def _fence(
        self,
        connection: sqlite3.Connection,
        expected: BaselineResourceSnapshot,
        reason: Literal["owner_drain", "stopped_owner"],
    ) -> BaselineCleanupClaim:
        current = self._snapshot(connection, expected.execution.baseline_id)
        if current != expected:
            raise unavailable()
        claim = BaselineCleanupClaim(
            owner=expected.claim.owner,
            claim_id=baseline_id("bclaim"),
            snapshot=expected,
            scope_sha256=expected.digest,
            reason=reason,
            created_at=self.state.clock.now(),
        )
        sequence = connection.execute(
            "SELECT COALESCE(MAX(sequence),-1)+1 FROM baseline_events WHERE baseline_id=?",
            (expected.execution.baseline_id,),
        ).fetchone()[0]
        raw = self._encode(claim)
        connection.execute(
            "INSERT INTO baseline_events VALUES (?,?,?,?,?,?)",
            (
                expected.execution.baseline_id,
                sequence,
                "cleanup_claimed",
                expected.digest,
                sha256_bytes(raw),
                raw,
            ),
        )
        self._bump(connection, current.execution, status="cleaning")
        return claim

    @_boundary
    def begin_baseline_cleanup(
        self, claim: BaselineOwnerClaim, expected: BaselineResourceSnapshot
    ) -> BaselineCleanupClaim:
        with self._transaction(write=True) as connection:
            self._require_claim(connection, claim)
            if claim.controller_pid != os.getpid() or expected.claim != claim:
                raise unavailable()
            return self._fence(connection, expected, "owner_drain")

    @_boundary
    def claim_baseline_cleanup(
        self, expected: BaselineResourceSnapshot, stopped_owner: BaselineStoppedOwnerReview
    ) -> BaselineCleanupClaim:
        with self._transaction(write=True) as connection:
            now = self.state.clock.now()
            if (
                stopped_owner.owner != expected.claim.owner
                or stopped_owner.owner_claim_sha256 != expected.claim.digest
                or stopped_owner.snapshot_sha256 != expected.digest
                or stopped_owner.controller_pid != expected.claim.controller_pid
                or stopped_owner.installation_id != self.installation_id
                or not now - timedelta(seconds=5) <= stopped_owner.checked_at <= now
                or not _pid_absent(expected.claim.controller_pid)
            ):
                raise unavailable()
            return self._fence(connection, expected, "stopped_owner")

    def _validate_cleanup(
        self, connection: sqlite3.Connection, claim: BaselineCleanupClaim
    ) -> BaselineResourceSnapshot:
        if self._cleanup_event(connection, claim.owner.baseline_id) != claim:
            raise unavailable()
        current = self._snapshot(connection, claim.owner.baseline_id)
        original = claim.snapshot
        if (
            current.claim != original.claim
            or current.dispatch != original.dispatch
            or len(current.leases) != len(original.leases)
        ):
            raise unavailable()
        changed = 0
        for before, after in zip(original.leases, current.leases, strict=True):
            if before == after:
                continue
            if after.receipt_sha256 is None:
                raise unavailable()
            receipt = self._one(
                connection,
                "baseline_cleanup_receipts",
                "record_id",
                after.receipt_sha256,
                BaselineCleanupReceipt,
            )
            if (
                receipt.cleanup_scope_sha256 != claim.scope_sha256
                or receipt.lease_sha256 != before.digest
            ):
                raise unavailable()
            expected = _replace(
                before,
                revision=before.revision + 1,
                status="released" if receipt.complete else "failed",
                receipt_sha256=receipt.digest,
                updated_at=receipt.completed_at.isoformat(),
            )
            if expected != after:
                raise unavailable()
            changed += 1
        expected_execution = _replace(
            original.execution,
            revision=original.execution.revision + changed + 1,
            status="cleaning",
            updated_at=current.execution.updated_at.isoformat(),
        )
        if current.execution != expected_execution:
            raise unavailable()
        return current

    @staticmethod
    def _validate_receipt_binding(
        lease: BaselineResourceLease, receipt: BaselineCleanupReceipt, scope_sha256: str
    ) -> None:
        if (
            receipt.owner != lease.owner
            or receipt.lease_id != lease.lease_id
            or receipt.kind != lease.kind
            or receipt.lease_sha256 != lease.digest
            or receipt.cleanup_scope_sha256 != scope_sha256
            or receipt.completed_at < lease.updated_at
        ):
            raise unavailable()
        payload = lease.payload
        if isinstance(payload, BaselineWorkspacePayload):
            if receipt.result is not None:
                raise unavailable()
            return
        if receipt.result is None:
            raise unavailable()
        result = snapshot_model(receipt.result, "cleanup-v1", SandboxCleanupResult)
        if isinstance(payload, BaselineSandboxPayload):
            if (
                result.resource_id != payload.sandbox_id
                or result.resources_found != 0
                or result.resources_removed != 0
            ):
                raise unavailable()
            return
        expected_id = (
            payload.handle.native_resource_id
            if payload.handle is not None
            else payload.request.execution_id
        )
        if result.resource_id != expected_id and not (
            payload.handle is None
            and result.resources_found == 1
            and len(result.resource_id) == 64
            and all(char in "0123456789abcdef" for char in result.resource_id)
        ):
            raise unavailable()
        if result.resources_found > 1 or (
            payload.creation_dispatched
            and payload.handle is None
            and result.resources_found == 0
            and result.complete
        ):
            raise unavailable()

    def _receipt_state(
        self,
        connection: sqlite3.Connection,
        receipt: BaselineCleanupReceipt,
        *,
        expected: BaselineResourceLease | None = None,
    ) -> BaselineResourceLease:
        scope = self._cleanup_event(
            connection, receipt.owner.baseline_id, scope_sha256=receipt.cleanup_scope_sha256
        )
        if scope is None:
            raise unavailable()
        original = [item for item in scope.snapshot.leases if item.lease_id == receipt.lease_id]
        if len(original) != 1:
            raise unavailable()
        self._validate_receipt_binding(original[0], receipt, scope.scope_sha256)
        transformed = _replace(
            original[0],
            revision=original[0].revision + 1,
            status="released" if receipt.complete else "failed",
            receipt_sha256=receipt.digest,
            updated_at=receipt.completed_at.isoformat(),
        )
        if expected is not None and transformed != expected:
            raise unavailable()
        return transformed

    @_boundary
    def validate_cleanup(self, claim: BaselineCleanupClaim) -> BaselineResourceSnapshot:
        with self._transaction(write=False) as connection:
            return self._validate_cleanup(connection, claim)

    @_boundary
    def finalize_baseline_lease(
        self,
        cleanup_claim: BaselineCleanupClaim,
        lease_id: str,
        expected_revision: int,
        receipt: BaselineCleanupReceipt,
    ) -> BaselineResourceLease:
        with self._transaction(write=True) as connection:
            current = self._validate_cleanup(connection, cleanup_claim)
            matches = [item for item in current.leases if item.lease_id == lease_id]
            original = [item for item in cleanup_claim.snapshot.leases if item.lease_id == lease_id]
            if (
                len(matches) != 1
                or len(original) != 1
                or matches[0] != original[0]
                or matches[0].revision != expected_revision
                or matches[0].status == "released"
            ):
                raise unavailable()
            lease = matches[0]
            tiers = {"execution": 0, "sandbox": 1, "workspace": 2}
            if any(
                tiers[item.kind] < tiers[lease.kind] and item.status != "released"
                for item in current.leases
            ):
                raise unavailable()
            self._validate_receipt_binding(lease, receipt, cleanup_claim.scope_sha256)
            self._insert(connection, "baseline_cleanup_receipts", receipt)
            replacement = _replace(
                lease,
                revision=lease.revision + 1,
                status="released" if receipt.complete else "failed",
                receipt_sha256=receipt.digest,
                updated_at=receipt.completed_at.isoformat(),
            )
            self._update(connection, "baseline_resource_leases", lease, replacement)
            self._bump(connection, current.execution)
            return replacement

    def _observation(
        self, connection: sqlite3.Connection, identity: str
    ) -> BaselineCommandObservation | None:
        rows = self._rows(connection, "baseline_command_observations", "baseline_id", identity)
        if len(rows) > 1:
            raise unavailable()
        if not rows:
            return None
        observation = self._decode(rows[0], BaselineCommandObservation)
        snapshot = self._snapshot(connection, identity)
        review = self._review(connection, snapshot.execution.review_id)
        commands = [
            item.payload
            for item in snapshot.leases
            if isinstance(item.payload, BaselineCommandPayload)
        ]
        if len(commands) != 1 or snapshot.dispatch is None:
            raise unavailable()
        payload = commands[0]
        native = snapshot_model(
            observation.native_handle, "native-handle-v1", BaselineExecutionHandle
        )
        inspection = snapshot_model(
            observation.inspection, "sandbox-inspection-v1", BaselineSandboxInspection
        )
        controls = snapshot_model(
            inspection.legacy_control_inspection, "sandbox-inspection-v1", BaselineControlInspection
        )
        sandbox_payloads = [
            item.payload
            for item in snapshot.leases
            if isinstance(item.payload, BaselineSandboxPayload)
        ]
        if len(sandbox_payloads) != 1:
            raise unavailable()
        configuration = reconstruct_sandbox(sandbox_payloads[0].spec.sandbox).configuration
        if (
            native != payload.handle
            or inspection.owner != snapshot.claim.owner
            or inspection.native_resource_id != native.native_resource_id
            or inspection.execution_id != native.execution_id
            or inspection.sandbox_id != native.sandbox_id
            or controls.capabilities != payload.sandbox.capabilities
            or controls.configuration_sha256 != payload.sandbox.configuration_sha256
            or controls.image_identity != payload.sandbox.image_identity
            or controls.daemon_identity != payload.sandbox.daemon_identity
            or inspection.tmp_scratch_mb != configuration.tmpfs_mb
            or inspection.cache_scratch_mb != configuration.tmpfs_mb
            or inspection.shm_scratch_mb != configuration.shm_mb
            or not snapshot.claim.claimed_at <= controls.inspected_at <= observation.started_at
            or observation.project_id != review.project_id
            or observation.review_id != review.review_id
            or observation.review_sha256 != review.digest
            or observation.authorization_id != snapshot.claim.authorization_id
            or observation.claim_id != snapshot.claim.claim_id
            or observation.execution_id != payload.request.execution_id
            or observation.workspace_id != payload.request.workspace_id
            or observation.sandbox_id != payload.sandbox.sandbox_id
            or observation.command_sha256 != review.command.sha256
            or observation.request_sha256 != payload.request.digest
            or observation.sandbox_spec_sha256 != payload.sandbox.sandbox_spec_sha256
            or observation.sandbox_policy_sha256 != payload.sandbox.sandbox_policy_sha256
            or observation.approved_source_sha256 != review.approved_source_sha256
            or observation.materialized_source_sha256 != payload.sandbox.materialized_source_sha256
        ):
            raise unavailable()
        return observation

    @_boundary
    def record_command_observation(
        self, claim: BaselineOwnerClaim, expected_revision: int, canonical_utf8: bytes
    ) -> BaselineObservationRef:
        observation = BaselineCommandObservation.from_canonical(
            canonical_utf8, limit=MAX_OBSERVATION_BYTES
        )
        with self._transaction(write=True) as connection:
            execution = self._require_claim(connection, claim)
            existing = self._observation(connection, claim.owner.baseline_id)
            if existing is not None:
                if existing != observation:
                    raise unavailable()
            else:
                if (
                    execution.revision != expected_revision
                    or observation.baseline_id != execution.baseline_id
                ):
                    raise unavailable()
                self._insert(connection, "baseline_command_observations", observation)
                self._observation(connection, claim.owner.baseline_id)
                self._bump(connection, execution)
            return BaselineObservationRef(
                observation_id=f"bobs_{observation.digest}",
                baseline_id=observation.baseline_id,
                execution_id=observation.execution_id,
                record_sha256=observation.digest,
            )

    @_boundary
    def observation(self, baseline_id: str) -> BaselineCommandObservation | None:
        with self._transaction(write=False) as connection:
            return self._observation(connection, baseline_id)

    def _report(
        self, connection: sqlite3.Connection, execution: BaselineExecution
    ) -> BaselineReport | None:
        if execution.current_report_sha256 is None:
            return None
        report = self._one(
            connection,
            "baseline_reports",
            "record_id",
            f"brpt_{execution.current_report_sha256}",
            BaselineReport,
        )
        self._validate_report_facts(connection, report, execution)
        return report

    def _validate_report_facts(
        self, connection: sqlite3.Connection, report: BaselineReport, execution: BaselineExecution
    ) -> None:
        review = self._review(connection, execution.review_id)
        owner = self._owner(connection, execution.baseline_id)
        scope = self._cleanup_event(
            connection, execution.baseline_id, scope_sha256=report.cleanup_scope_sha256
        )
        if scope is None or (
            report.baseline_id != execution.baseline_id
            or report.review_id != review.review_id
            or report.review_sha256 != review.digest
            or report.project_id != review.project_id
            or report.authorization_id != owner.authorization_id
            or report.claim_id != owner.claim_id
            or report.command_sha256 != review.command.sha256
            or report.approved_source_sha256 != review.approved_source_sha256
            or report.predecessor_report_sha256 != scope.snapshot.execution.current_report_sha256
            or report.predecessor_report_sha256 == report.digest
            or report.completed_at < scope.created_at
        ):
            raise unavailable()
        observation = self._observation(connection, execution.baseline_id)
        if (
            report.observation != self._observation_ref(observation)
            or report.observed_exit_code != (None if observation is None else observation.exit_code)
            or (observation is not None and report.completed_at < observation.completed_at)
            or (report.status == "observed" and (observation is None or not observation.conclusive))
        ):
            raise unavailable()
        receipts: dict[str, BaselineCleanupReceipt] = {}
        if report.cleanup_receipt_sha256s != tuple(sorted(set(report.cleanup_receipt_sha256s))):
            raise unavailable()
        for digest in report.cleanup_receipt_sha256s:
            receipt = self._one(
                connection, "baseline_cleanup_receipts", "record_id", digest, BaselineCleanupReceipt
            )
            if (
                receipt.owner != owner.owner
                or receipt.lease_id in receipts
                or report.completed_at < receipt.completed_at
            ):
                raise unavailable()
            receipts[receipt.lease_id] = receipt
        if not set(receipts).issubset({lease.lease_id for lease in scope.snapshot.leases}):
            raise unavailable()
        states: list[BaselineResourceLease] = []
        for original in scope.snapshot.leases:
            selected_receipt = receipts.get(original.lease_id)
            if selected_receipt is None:
                if original.receipt_sha256 is not None:
                    raise unavailable()
                states.append(original)
            elif selected_receipt.digest == original.receipt_sha256:
                states.append(self._receipt_state(connection, selected_receipt, expected=original))
            else:
                self._validate_receipt_binding(original, selected_receipt, scope.scope_sha256)
                states.append(self._receipt_state(connection, selected_receipt))
        if report.cleanup_complete != all(item.status == "released" for item in states):
            raise unavailable()
        if report.predecessor_report_sha256 is not None:
            predecessor = self._one(
                connection,
                "baseline_reports",
                "record_id",
                f"brpt_{report.predecessor_report_sha256}",
                BaselineReport,
            )
            # Immediate immutable predecessor only: no recursive unbounded history scan.
            # Its earlier timestamp/scope/revision must precede the current fence.
            predecessor_scope = self._cleanup_event(
                connection, execution.baseline_id, scope_sha256=predecessor.cleanup_scope_sha256
            )
            if (
                predecessor.baseline_id != report.baseline_id
                or predecessor.claim_id != report.claim_id
                or predecessor.review_sha256 != report.review_sha256
                or predecessor.completed_at > scope.created_at
                or predecessor_scope is None
                or predecessor_scope.snapshot.execution.revision
                >= scope.snapshot.execution.revision
            ):
                raise unavailable()

    @staticmethod
    def _observation_ref(
        observation: BaselineCommandObservation | None,
    ) -> BaselineObservationRef | None:
        if observation is None:
            return None
        return BaselineObservationRef(
            observation_id=f"bobs_{observation.digest}",
            baseline_id=observation.baseline_id,
            execution_id=observation.execution_id,
            record_sha256=observation.digest,
        )

    @_boundary
    def publish_baseline_report(
        self, cleanup_claim: BaselineCleanupClaim, expected_revision: int, canonical_utf8: bytes
    ) -> BaselineReportRef:
        report = BaselineReport.from_canonical(canonical_utf8)
        with self._transaction(write=True) as connection:
            snapshot = self._validate_cleanup(connection, cleanup_claim)
            execution = snapshot.execution
            review = self._review(connection, execution.review_id)
            observation = self._observation(connection, execution.baseline_id)
            receipts = tuple(
                sorted(
                    item.receipt_sha256
                    for item in snapshot.leases
                    if item.receipt_sha256 is not None
                )
            )
            complete = all(item.status == "released" for item in snapshot.leases)
            if (
                execution.revision != expected_revision
                or report.baseline_id != execution.baseline_id
                or report.project_id != review.project_id
                or report.review_id != review.review_id
                or report.review_sha256 != review.digest
                or report.authorization_id != snapshot.claim.authorization_id
                or report.claim_id != snapshot.claim.claim_id
                or report.command_sha256 != review.command.sha256
                or report.approved_source_sha256 != review.approved_source_sha256
                or report.cleanup_scope_sha256 != cleanup_claim.scope_sha256
                or report.cleanup_receipt_sha256s != receipts
                or report.cleanup_complete != complete
                or report.predecessor_report_sha256 != execution.current_report_sha256
                or (report.observation is None) != (observation is None)
                or (
                    observation is not None
                    and (
                        report.observation is None
                        or report.observation != self._observation_ref(observation)
                        or report.observed_exit_code != observation.exit_code
                    )
                )
                or (
                    report.status == "observed"
                    and (observation is None or not observation.conclusive)
                )
            ):
                raise unavailable()
            self._validate_report_facts(connection, report, execution)
            self._insert(connection, "baseline_reports", report)
            self._bump(
                connection, execution, status=report.status, current_report_sha256=report.digest
            )
            return BaselineReportRef(
                report_id=f"brpt_{report.digest}",
                baseline_id=report.baseline_id,
                record_sha256=report.digest,
            )

    @_boundary
    def show(self, identity: str) -> BaselineShow:
        with self._transaction(write=False) as connection:
            if type(identity) is not str:
                raise unavailable()
            if identity.startswith("breview_"):
                review = self._review(connection, identity)
                execution = self._execution(connection, review.baseline_id)
            else:
                execution = self._execution(connection, identity)
                review = self._review(connection, execution.review_id)
            report = self._report(connection, execution)
            recovery = (
                self._snapshot(connection, execution.baseline_id).digest
                if execution.owner_claim_id is not None
                else None
            )
            return BaselineShow(
                review=review, execution=execution, report=report, recovery_scope_sha256=recovery
            )
