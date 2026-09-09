"""Transactional user-owned profiles, review revisions and immutable run bindings."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import wraps
from typing import Literal, TypeVar

from pydantic import TypeAdapter, ValidationError

from agent_fleet.adapters.persistence.conversations import SqliteConversationStore
from agent_fleet.adapters.persistence.sqlite import SUPPORTED_SCHEMA_VERSION, SqliteStateStore
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.model_profiles import (
    ModelConfigurationAudit,
    ModelProfile,
    ProfileName,
    ProjectModelSelection,
    RunModelBindings,
)
from agent_fleet.domain.models import Project, ProjectId, RunId, StrictModel
from agent_fleet.domain.security import canonical_json_hash
from agent_fleet.domain.session_review import ModelSelectionReview

_Model = TypeVar("_Model", bound=StrictModel)
_MAX_RECORD_BYTES = 1_048_576
_MAX_CATALOG = 1024


def _invalid() -> FleetError:
    return FleetError(
        ErrorCode.RECOVERY_REQUIRED,
        "The model configuration identity, revision or audit record is inconsistent.",
        "Inspect the selected local state; do not fall back to another model configuration.",
    )


def _stale() -> FleetError:
    return FleetError(
        ErrorCode.CONFIG_INVALID,
        "The reviewed model configuration revision is stale or still referenced.",
        "Inspect current profiles and project selections, then review the exact change again.",
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
                "The model configuration store is unavailable.",
                "Restore the selected local state before changing or resolving model selections.",
            )
        error.__context__ = None
        raise error from None

    return call


class SqliteModelProfileStore:
    """All writes and their audit receipt commit together in the migrated Fleet database."""

    def __init__(self, state: SqliteStateStore) -> None:
        self.state = state
        self.redactor = state.redactor

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

    def _clean(self, value: object) -> None:
        if self.redactor.contains_secret_data(value):
            raise _invalid()

    def _name(self, name: str) -> None:
        TypeAdapter(ProfileName).validate_python(name)
        self._clean(name)

    def _decode(self, model: type[_Model], raw: str) -> _Model:
        if not isinstance(raw, str) or len(raw.encode("utf-8")) > _MAX_RECORD_BYTES:
            raise _invalid()
        self._clean(raw)
        return model.model_validate_json(raw)

    def _validated(self, model: type[_Model], value: _Model) -> _Model:
        return self._decode(model, value.model_dump_json(warnings=False))

    def _project(self, connection: sqlite3.Connection, project_id: str) -> Project:
        TypeAdapter(ProjectId).validate_python(project_id)
        self._clean(project_id)
        row = connection.execute(
            "SELECT * FROM projects WHERE project_id=?", (project_id,)
        ).fetchone()
        if row is None:
            raise _invalid()
        project = self._decode(Project, row["data_json"])
        if project.project_id != project_id or project.canonical_root != row["canonical_root"]:
            raise _invalid()
        return project

    def _audit(self, connection: sqlite3.Connection, sequence: int) -> ModelConfigurationAudit:
        row = connection.execute(
            "SELECT * FROM model_configuration_audit WHERE sequence=?", (sequence,)
        ).fetchone()
        if row is None:
            raise _invalid()
        audit = self._decode(ModelConfigurationAudit, row["data_json"])
        if audit.sequence != sequence or audit.audit_sha256 != row["audit_sha256"]:
            raise _invalid()
        if sequence == 1:
            if audit.previous_sha256 is not None:
                raise _invalid()
        else:
            prior = connection.execute(
                "SELECT * FROM model_configuration_audit WHERE sequence=?", (sequence - 1,)
            ).fetchone()
            if prior is None:
                raise _invalid()
            previous = self._decode(ModelConfigurationAudit, prior["data_json"])
            if (
                previous.sequence != sequence - 1
                or previous.audit_sha256 != prior["audit_sha256"]
                or audit.previous_sha256 != previous.audit_sha256
            ):
                raise _invalid()
        return audit

    def _receipt(
        self,
        connection: sqlite3.Connection,
        sequence: int,
        action: str,
        target: str,
        revision: int,
        record_hash: str,
    ) -> None:
        audit = self._audit(connection, sequence)
        if (audit.action, audit.target, audit.revision, audit.record_sha256) != (
            action,
            target,
            revision,
            record_hash,
        ):
            raise _invalid()

    def _append(
        self,
        connection: sqlite3.Connection,
        action: Literal["profile.set", "profile.remove", "selection.set", "run.bind"],
        target: str,
        revision: int,
        record_hash: str,
    ) -> int:
        row = connection.execute(
            "SELECT COALESCE(MAX(sequence),0) AS latest, COUNT(*) AS count "
            "FROM model_configuration_audit"
        ).fetchone()
        sequence = int(row["latest"])
        if sequence != row["count"]:
            raise _invalid()
        previous = self._audit(connection, sequence) if sequence else None
        audit = ModelConfigurationAudit(
            sequence=sequence + 1,
            action=action,
            target=target,
            revision=revision,
            record_sha256=record_hash,
            previous_sha256=previous.audit_sha256 if previous else None,
            occurred_at=self.state.clock.now(),
        )
        self._clean(audit.model_dump(mode="json"))
        connection.execute(
            "INSERT INTO model_configuration_audit VALUES (?,?,?)",
            (audit.sequence, audit.audit_sha256, audit.model_dump_json()),
        )
        return audit.sequence

    def _profile(
        self, connection: sqlite3.Connection, name: str
    ) -> tuple[ModelProfile | None, int]:
        self._name(name)
        head = connection.execute(
            "SELECT revision FROM model_profile_heads WHERE name=?", (name,)
        ).fetchone()
        latest = connection.execute(
            "SELECT COALESCE(MAX(revision),0) FROM model_profile_versions WHERE name=?", (name,)
        ).fetchone()[0]
        if head is None:
            if latest:
                raise _invalid()
            return None, 0
        if head["revision"] != latest:
            raise _invalid()
        row = connection.execute(
            "SELECT * FROM model_profile_versions WHERE name=? AND revision=?", (name, latest)
        ).fetchone()
        profile = self._decode(ModelProfile, row["data_json"])
        record_hash = canonical_json_hash(profile.model_dump(mode="json"))
        if (
            profile.name != name
            or profile.revision != latest
            or record_hash != row["record_sha256"]
            or row["removed"] not in (0, 1)
        ):
            raise _invalid()
        self._receipt(
            connection,
            row["audit_sequence"],
            "profile.remove" if row["removed"] else "profile.set",
            name,
            latest,
            record_hash,
        )
        if row["removed"] and profile.enabled:
            raise _invalid()
        return (None if row["removed"] else profile), latest

    @_boundary
    def get_profile(self, name: str) -> ModelProfile | None:
        with self._transaction() as connection:
            return self._profile(connection, name)[0]

    @_boundary
    def profile_revision(self, name: str) -> int:
        with self._transaction() as connection:
            return self._profile(connection, name)[1]

    @_boundary
    def list_profiles(self) -> tuple[ModelProfile, ...]:
        with self._transaction() as connection:
            names = connection.execute(
                "SELECT DISTINCT name FROM model_profile_versions ORDER BY name LIMIT ?",
                (_MAX_CATALOG + 1,),
            ).fetchall()
            if len(names) > _MAX_CATALOG:
                raise _invalid()
            result = [self._profile(connection, row["name"])[0] for row in names]
            return tuple(profile for profile in result if profile is not None)

    def _write_profile(
        self, connection: sqlite3.Connection, profile: ModelProfile, *, removed: bool
    ) -> None:
        record_hash = canonical_json_hash(profile.model_dump(mode="json"))
        sequence = self._append(
            connection,
            "profile.remove" if removed else "profile.set",
            profile.name,
            profile.revision,
            record_hash,
        )
        connection.execute(
            "INSERT INTO model_profile_versions VALUES (?,?,?,?,?,?)",
            (
                profile.name,
                profile.revision,
                int(removed),
                record_hash,
                profile.model_dump_json(),
                sequence,
            ),
        )
        connection.execute(
            "INSERT INTO model_profile_heads VALUES (?,?) "
            "ON CONFLICT(name) DO UPDATE SET revision=excluded.revision",
            (profile.name, profile.revision),
        )

    @_boundary
    def save_profile(self, profile: ModelProfile, *, expected_revision: int) -> None:
        profile = self._validated(ModelProfile, profile)
        with self._transaction() as connection:
            _, revision = self._profile(connection, profile.name)
            if (
                type(expected_revision) is not int
                or revision != expected_revision
                or profile.revision != revision + 1
            ):
                raise _stale()
            if (
                revision == 0
                and connection.execute("SELECT COUNT(*) FROM model_profile_heads").fetchone()[0]
                >= _MAX_CATALOG
            ):
                raise _stale()
            self._write_profile(connection, profile, removed=False)

    def _selection(
        self, connection: sqlite3.Connection, project_id: str
    ) -> ProjectModelSelection | None:
        project = self._project(connection, project_id)
        head = connection.execute(
            "SELECT revision FROM project_model_selection_heads WHERE project_id=?", (project_id,)
        ).fetchone()
        latest = connection.execute(
            "SELECT COALESCE(MAX(revision),0) FROM project_model_selection_versions "
            "WHERE project_id=?",
            (project_id,),
        ).fetchone()[0]
        if head is None:
            if latest:
                raise _invalid()
            return None
        if head["revision"] != latest:
            raise _invalid()
        row = connection.execute(
            "SELECT * FROM project_model_selection_versions WHERE project_id=? AND revision=?",
            (project_id, latest),
        ).fetchone()
        selection = self._decode(ProjectModelSelection, row["data_json"])
        record_hash = canonical_json_hash(selection.model_dump(mode="json"))
        if (
            selection.project_id != project_id
            or selection.revision != latest
            or selection.repository_identity != project.identity_hash
            or record_hash != row["record_sha256"]
        ):
            raise _invalid()
        self._receipt(
            connection, row["audit_sequence"], "selection.set", project_id, latest, record_hash
        )
        return selection

    @_boundary
    def get_selection(self, project_id: str) -> ProjectModelSelection | None:
        with self._transaction() as connection:
            return self._selection(connection, project_id)

    @_boundary
    def save_selection(
        self,
        selection: ProjectModelSelection,
        *,
        expected_revision: int,
        expected_review: ModelSelectionReview | None = None,
        validate_review: Callable[[], None] | None = None,
    ) -> None:
        selection = self._validated(ProjectModelSelection, selection)
        if (expected_review is None) != (validate_review is None):
            raise _stale()
        with self._transaction() as connection:
            current = self._selection(connection, selection.project_id)
            project = self._project(connection, selection.project_id)
            revision = current.revision if current else 0
            if (
                type(expected_revision) is not int
                or revision != expected_revision
                or selection.revision != revision + 1
                or selection.repository_identity != project.identity_hash
            ):
                raise _stale()
            for alias in selection.permitted_profiles:
                profile, _ = self._profile(connection, alias)
                if profile is None or not profile.enabled:
                    raise _stale()
            if expected_review is not None:
                expected = ModelSelectionReview.model_validate_json(
                    expected_review.model_dump_json()
                )
                reviewed_profile, _ = self._profile(connection, expected.profile_name)
                if (
                    expected.selection.project_id != selection.project_id
                    or expected.expected_selection_revision != expected_revision
                    or reviewed_profile is None
                    or not reviewed_profile.enabled
                    or reviewed_profile.revision != expected.profile_revision
                    or reviewed_profile.configuration_sha256 != expected.configuration_sha256
                    or (
                        selection.role_overrides.get(expected.role_id)
                        if expected.role_id
                        else selection.default_profile
                    )
                    != expected.profile_name
                ):
                    raise _stale()
                # Reuse receipt-validating connection-local readers, never nest a
                # ConversationStore transaction while this write lock is held.
                conversations = SqliteConversationStore(
                    self.state.database_path,
                    self.state.clock,
                    self.state.ids,
                    self.redactor,
                    self.state,
                )
                conversation = conversations._conversation(
                    connection,
                    selection.project_id,
                    expected.selection.conversation_id,
                )
                if conversation.revision != expected.selection.conversation_revision:
                    raise _stale()
                turn_id = conversation.active_turn_id
                if turn_id is None:
                    row = connection.execute(
                        "SELECT turn_id FROM conversation_turns WHERE conversation_id=? "
                        "ORDER BY sequence DESC LIMIT 1",
                        (conversation.conversation_id,),
                    ).fetchone()
                    turn_id = row["turn_id"] if row is not None else None
                run_id = None
                if turn_id is not None:
                    turn = conversations._turn(connection, selection.project_id, turn_id)
                    run = self.state._validated_run(connection, turn.binding.run_id)
                    if (
                        run.parent_run_id is not None
                        or turn.binding.conversation_id != conversation.conversation_id
                    ):
                        raise _stale()
                    run_id = run.run_id
                if run_id != expected.selection.run_id:
                    raise _stale()
                assert validate_review is not None
                validate_review()
            record_hash = canonical_json_hash(selection.model_dump(mode="json"))
            sequence = self._append(
                connection, "selection.set", selection.project_id, selection.revision, record_hash
            )
            connection.execute(
                "INSERT INTO project_model_selection_versions VALUES (?,?,?,?,?)",
                (
                    selection.project_id,
                    selection.revision,
                    record_hash,
                    selection.model_dump_json(),
                    sequence,
                ),
            )
            connection.execute(
                "INSERT INTO project_model_selection_heads VALUES (?,?) "
                "ON CONFLICT(project_id) DO UPDATE SET revision=excluded.revision",
                (selection.project_id, selection.revision),
            )

    @_boundary
    def remove_profile(self, name: str, *, expected_revision: int) -> int:
        with self._transaction() as connection:
            profile, revision = self._profile(connection, name)
            if (
                profile is None
                or type(expected_revision) is not int
                or revision != expected_revision
            ):
                raise _stale()
            # Iterate authoritative versions too: a removed head must not hide a selection.
            projects = connection.execute(
                "SELECT DISTINCT project_id FROM project_model_selection_versions"
            ).fetchall()
            for row in projects:
                selection = self._selection(connection, row["project_id"])
                if selection is not None and name in selection.permitted_profiles:
                    raise _stale()
            tombstone = ModelProfile(
                name=name, revision=revision + 1, enabled=False, configuration=profile.configuration
            )
            self._write_profile(connection, tombstone, removed=True)
            return tombstone.revision

    def _bindings(
        self, connection: sqlite3.Connection, project_id: str, root_run_id: str
    ) -> RunModelBindings | None:
        project = self._project(connection, project_id)
        TypeAdapter(RunId).validate_python(root_run_id)
        self._clean(root_run_id)
        run = self.state._validated_run(connection, root_run_id)
        if run.project_id != project_id or run.parent_run_id is not None:
            raise _invalid()
        row = connection.execute(
            "SELECT * FROM run_model_bindings WHERE root_run_id=?", (root_run_id,)
        ).fetchone()
        if row is None:
            return None
        bindings = self._decode(RunModelBindings, row["data_json"])
        if (
            bindings.root_run_id != root_run_id
            or bindings.project_id != project_id
            or row["project_id"] != project_id
            or bindings.repository_identity != project.identity_hash
            or bindings.bindings_sha256 != row["bindings_sha256"]
        ):
            raise _invalid()
        self._receipt(
            connection, row["audit_sequence"], "run.bind", root_run_id, 1, bindings.bindings_sha256
        )
        return bindings

    @_boundary
    def get_bindings(self, project_id: str, root_run_id: str) -> RunModelBindings | None:
        with self._transaction() as connection:
            return self._bindings(connection, project_id, root_run_id)

    @_boundary
    def save_bindings(self, bindings: RunModelBindings) -> None:
        bindings = self._validated(RunModelBindings, bindings)
        with self._transaction() as connection:
            self._save_bindings_in_transaction(connection, bindings)

    def _save_bindings_in_transaction(
        self, connection: sqlite3.Connection, bindings: RunModelBindings
    ) -> None:
        bindings = self._validated(RunModelBindings, bindings)
        existing = self._bindings(connection, bindings.project_id, bindings.root_run_id)
        if existing is not None:
            if existing != bindings:
                raise _stale()
            return
        project = self._project(connection, bindings.project_id)
        run = self.state._validated_run(connection, bindings.root_run_id)
        if bindings.repository_identity != project.identity_hash:
            raise _invalid()
        selection = self._selection(connection, bindings.project_id)
        if bindings.selection_revision != (selection.revision if selection else None):
            raise _stale()
        for role, binding in bindings.roles.items():
            if binding.profile_name is None:
                configuration = binding.configuration
                if (
                    configuration.runtime_name,
                    configuration.provider_model,
                    configuration.credential_ref,
                ) != (run.runtime_name, run.provider_model, run.credential_ref):
                    raise _invalid()
                continue
            profile, _ = self._profile(connection, binding.profile_name)
            if (
                selection is None
                or profile is None
                or not profile.enabled
                or profile.revision != binding.profile_revision
                or profile.configuration != binding.configuration
                or profile.name not in selection.permitted_profiles
            ):
                raise _stale()
            override = selection.role_overrides.get(role)
            if (
                (binding.source == "override" and override != profile.name)
                or (binding.source != "override" and override is not None)
                or (binding.source == "default" and selection.default_profile != profile.name)
            ):
                raise _invalid()
        sequence = self._append(
            connection, "run.bind", bindings.root_run_id, 1, bindings.bindings_sha256
        )
        connection.execute(
            "INSERT INTO run_model_bindings VALUES (?,?,?,?,?)",
            (
                bindings.root_run_id,
                bindings.project_id,
                bindings.bindings_sha256,
                bindings.model_dump_json(),
                sequence,
            ),
        )

    @_boundary
    def list_audit(
        self, *, after_sequence: int = 0, limit: int = 100
    ) -> tuple[ModelConfigurationAudit, ...]:
        if (
            type(after_sequence) is not int
            or after_sequence < 0
            or type(limit) is not int
            or not 1 <= limit <= 100
        ):
            raise _invalid()
        with self._transaction() as connection:
            rows = connection.execute(
                "SELECT sequence FROM model_configuration_audit WHERE sequence>? "
                "ORDER BY sequence LIMIT ?",
                (after_sequence, limit),
            ).fetchall()
            return tuple(self._audit(connection, row["sequence"]) for row in rows)
