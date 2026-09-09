"""At-most-once reserved execution and bounded, conservative campaign admission."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from pydantic import TypeAdapter

from agent_fleet.adapters.persistence.evaluations import SqliteEvaluationStore, _boundary
from agent_fleet.adapters.persistence.model_profiles import SqliteModelProfileStore
from agent_fleet.adapters.persistence.sqlite import SqliteStateStore
from agent_fleet.domain.budgets import RunBudgetLimits
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.evaluation import EvaluationManifest
from agent_fleet.domain.evaluation_campaign import IdempotencyKey, validate_terminal_outcome
from agent_fleet.domain.evaluation_execution import (
    EvaluationAdmission,
    EvaluationClaim,
    EvaluationExecutionBinding,
    EvaluationExecutionRecord,
    EvaluationRegistration,
    EvaluationSubmission,
    run_execution_hash,
)
from agent_fleet.domain.evolution import OrganizationAdmission
from agent_fleet.domain.ids import IdPrefix
from agent_fleet.domain.model_profiles import RunModelBindings
from agent_fleet.domain.models import FleetEvent, Run, RunStatus
from agent_fleet.domain.security import canonical_json_hash, sha256_bytes

if TYPE_CHECKING:
    from agent_fleet.adapters.persistence.runtime_budgets import SqliteRuntimeBudgetStore


def _denied() -> FleetError:
    return FleetError(
        ErrorCode.RECOVERY_REQUIRED,
        "The reserved execution identity or ownership is unavailable.",
        "Inspect the original attempt; do not replay, replace or refund it.",
    )


class SqliteEvaluationExecutionStore:
    def __init__(self, state: SqliteStateStore) -> None:
        self.state = state
        self.ledger = SqliteEvaluationStore(state)

    def _budgets(self) -> SqliteRuntimeBudgetStore:
        from agent_fleet.adapters.persistence.runtime_budgets import SqliteRuntimeBudgetStore

        return SqliteRuntimeBudgetStore(
            self.state.database_path,
            self.state.clock,
            self.state.ids,
            self.state.redactor,
            self.state,
        )

    def _clean(self, value: object) -> None:
        if self.state.redactor.contains_secret_data(value):
            raise _denied()

    def _manifest(
        self, connection: sqlite3.Connection, submission: EvaluationSubmission
    ) -> EvaluationManifest:
        submission = EvaluationSubmission.model_validate_json(submission.model_dump_json())
        self._clean(submission.model_dump(mode="json"))
        snapshot = self.ledger._snapshot(connection, submission.campaign_id)
        manifest = snapshot.registration.manifest
        if manifest.sha256 != submission.manifest_sha256 or not any(
            item.attempt_id == submission.attempt_id
            and item.case_id == submission.case_id
            and item.repetition == submission.repetition
            for item in snapshot.reservations
        ):
            raise _denied()
        return manifest

    @_boundary
    def submission(
        self,
        campaign_id: str,
        expected_manifest_sha256: str,
        case_id: str,
        repetition: int,
        idempotency_key: str,
    ) -> EvaluationSubmission:
        key = TypeAdapter(IdempotencyKey).validate_python(idempotency_key, strict=True)
        self._clean(key)
        self._clean((campaign_id, expected_manifest_sha256, case_id, repetition))
        if type(repetition) is not int:
            raise _denied()
        with self.ledger._transaction(write=False) as connection:
            snapshot = self.ledger._snapshot(connection, campaign_id)
            matches = [
                item
                for item in snapshot.reservations
                if item.case_id == case_id
                and item.repetition == repetition
                and item.idempotency_sha256 == sha256_bytes(key.encode())
            ]
            if (
                snapshot.registration.manifest.sha256 != expected_manifest_sha256
                or len(matches) != 1
            ):
                raise _denied()
            result = EvaluationSubmission(
                campaign_id=campaign_id,
                manifest_sha256=expected_manifest_sha256,
                case_id=case_id,
                repetition=repetition,
                attempt_id=matches[0].attempt_id,
            )
            self._manifest(connection, result)
            return result

    @_boundary
    def manifest(self, submission: EvaluationSubmission) -> EvaluationManifest:
        with self.ledger._transaction(write=False) as connection:
            return self._manifest(connection, submission)

    def _record(
        self, connection: sqlite3.Connection, root_run_id: str
    ) -> EvaluationExecutionRecord | None:
        row = connection.execute(
            "SELECT * FROM evaluation_executions WHERE root_run_id=?", (root_run_id,)
        ).fetchone()
        if row is None:
            # A deleted binding cannot silently turn a campaign Run into an ordinary Run.
            if connection.execute(
                "SELECT 1 FROM run_events WHERE run_id=? "
                "AND event_type='evaluation.execution_registered'",
                (root_run_id,),
            ).fetchone():
                raise _denied()
            return None
        raw = row["data_json"]
        if not isinstance(raw, str) or len(raw.encode()) > 65_536:
            raise _denied()
        self._clean(raw)
        record = EvaluationExecutionRecord.model_validate_json(raw)
        binding = record.binding
        if (
            sha256_bytes(raw.encode()) != row["record_sha256"]
            or binding.root_run_id != row["root_run_id"]
            or binding.submission.campaign_id != row["campaign_id"]
            or binding.submission.attempt_id != row["attempt_id"]
        ):
            raise _denied()
        manifest = self._manifest(connection, binding.submission)
        case = next(item for item in manifest.cases if item.case_id == binding.submission.case_id)
        repo = next(
            item for item in manifest.repositories if item.repository_id == case.repository_id
        )
        run = self.state._validated_run(connection, root_run_id)
        for outcome in self.ledger._snapshot(connection, binding.submission.campaign_id).outcomes:
            if outcome.attempt_id == binding.submission.attempt_id:
                validate_terminal_outcome(outcome)
                if (
                    outcome.root_run_id != root_run_id
                    or outcome.task_id != run.task_id
                    or outcome.product_status != run.status
                    or record.status == "active"
                ):
                    raise _denied()
        if (
            run.parent_run_id is not None
            or run_execution_hash(run) != binding.run_binding_sha256
            or run.project_id != binding.project_id
            or run.model_bindings_sha256 != binding.model_bindings_sha256
            or run.config_snapshot_hash != binding.configuration_sha256
            or run.sandbox_image_identity != binding.image_identity
            or binding.case_sha256 != canonical_json_hash(case.model_dump(mode="json"))
            or binding.limits.model_dump() != case.run_budget.model_dump()
            or binding.source_sha256 != repo.source_sha256
            or binding.commit_sha != repo.commit_sha
            or binding.configuration_sha256 != case.configuration_sha256
            or binding.dependencies_sha256 != case.dependencies_sha256
            or binding.image_identity != case.image_identity
            or binding.commands != case.commands
        ):
            raise _denied()
        profiles = SqliteModelProfileStore(self.state)._bindings(
            connection, binding.project_id, root_run_id
        )
        if (
            profiles is None
            or profiles.bindings_sha256 != binding.model_bindings_sha256
            or profiles.repository_identity != binding.repository_identity
        ):
            raise _denied()
        owner = self._budgets()._owner(connection, root_run_id)
        if owner != (root_run_id, binding.limits):
            raise _denied()
        events = connection.execute(
            "SELECT * FROM run_events WHERE run_id=? AND event_type IN "
            "('evaluation.execution_registered','evaluation.execution_settled',"
            "'evaluation.execution_fenced') ORDER BY sequence LIMIT 4",
            (root_run_id,),
        ).fetchall()
        if len(events) != record.revision:
            raise _denied()
        for index, event_row in enumerate(events):
            self._clean(event_row["data_json"])
            event = FleetEvent.model_validate_json(event_row["data_json"])
            expected_kind = (
                "evaluation.execution_registered"
                if index == 0
                else f"evaluation.execution_{record.status}"
            )
            expected = {
                "binding_sha256": binding.sha256,
                "claim_id": record.claim.claim_id,
                "revision": index + 1,
                "attempt_id": binding.submission.attempt_id,
                "campaign_id": binding.submission.campaign_id,
                "manifest_sha256": binding.submission.manifest_sha256,
            }
            if (
                event.event_type != expected_kind
                or event.payload != expected
                or event.run_id != root_run_id
                or event.project_id != binding.project_id
                or event.correlation_id != run.correlation_id
                or any(
                    getattr(event, field) != event_row[field]
                    for field in ("event_id", "sequence", "event_type", "project_id", "run_id")
                )
                or event.occurred_at.isoformat() != event_row["occurred_at"]
            ):
                raise _denied()
        if record.updated_at != FleetEvent.model_validate_json(events[-1]["data_json"]).occurred_at:
            raise _denied()
        return record

    def _for_run(
        self, connection: sqlite3.Connection, run_id: str
    ) -> EvaluationExecutionRecord | None:
        run = self.state._validated_run(connection, run_id)
        root = (
            self.state._validated_run(connection, run.parent_run_id) if run.parent_run_id else run
        )
        if root.parent_run_id is not None or root.project_id != run.project_id:
            raise _denied()
        return self._record(connection, root.run_id)

    @_boundary
    def for_run(self, run_id: str) -> EvaluationExecutionRecord | None:
        self._clean(run_id)
        with self.ledger._transaction(write=False) as connection:
            return self._for_run(connection, run_id)

    @_boundary
    def for_attempt(self, submission: EvaluationSubmission) -> EvaluationExecutionRecord | None:
        with self.ledger._transaction(write=False) as connection:
            self._manifest(connection, submission)
            row = connection.execute(
                "SELECT root_run_id FROM evaluation_executions WHERE attempt_id=?",
                (submission.attempt_id,),
            ).fetchone()
            if row is None:
                self._assert_no_orphan_claim(connection, submission)
                return None
            return self._record(connection, row[0])

    def _assert_no_orphan_claim(
        self, connection: sqlite3.Connection, submission: EvaluationSubmission
    ) -> None:
        # This is an index lookup only, never acceptance of the unvalidated JSON.
        # A retained dispatch receipt must not be mistaken for permission to replay.
        if connection.execute(
            "SELECT 1 FROM run_events WHERE event_type='evaluation.execution_registered' "
            "AND json_extract(data_json, '$.payload.attempt_id')=? LIMIT 1",
            (submission.attempt_id,),
        ).fetchone():
            raise _denied()

    def _admit_campaign(
        self, connection: sqlite3.Connection, campaign_id: str, budgets: SqliteRuntimeBudgetStore
    ) -> None:
        snapshot = self.ledger._snapshot(connection, campaign_id)
        rows = connection.execute(
            "SELECT root_run_id FROM evaluation_executions WHERE campaign_id=? LIMIT 257",
            (campaign_id,),
        ).fetchall()
        if len(rows) > 256:
            raise _denied()
        events = connection.execute(
            "SELECT run_id FROM run_events WHERE event_type='evaluation.execution_registered' "
            "AND json_extract(data_json, '$.payload.campaign_id')=? LIMIT 257",
            (campaign_id,),
        ).fetchall()
        if sorted(row[0] for row in rows) != sorted(row[0] for row in events):
            raise _denied()
        token_overrun = 0
        time_overrun = 0.0
        for row in rows:
            record = self._record(connection, row[0])
            if record is None:
                raise _denied()
            usage = budgets._snapshot(connection, row[0])
            if usage.completeness != "complete" or usage.unknown_requests:
                raise _denied()
            token_overrun += max(
                0, usage.reported_total_tokens - record.binding.limits.max_total_tokens
            )
            time_overrun += max(
                0.0, usage.active_seconds - record.binding.limits.max_active_seconds
            )
        if (
            snapshot.committed.total_tokens + token_overrun
            > snapshot.registration.manifest.budget.max_total_tokens
            or snapshot.committed.active_seconds + time_overrun
            > snapshot.registration.manifest.budget.max_active_seconds
        ):
            raise FleetError(
                ErrorCode.RUNTIME_BUDGET_EXCEEDED,
                "The campaign's retained commitment and observed overruns exhaust admission.",
                "Keep actual usage and unknown requests; do not refund or replay this campaign.",
            )

    def _write(
        self, connection: sqlite3.Connection, record: EvaluationExecutionRecord, *, new: bool
    ) -> None:
        raw = record.model_dump_json()
        if len(raw.encode()) > 65_536:
            raise _denied()
        self._clean(raw)
        binding = record.binding
        if new:
            connection.execute(
                "INSERT INTO evaluation_executions VALUES (?,?,?,?,?)",
                (
                    binding.submission.attempt_id,
                    binding.submission.campaign_id,
                    binding.root_run_id,
                    sha256_bytes(raw.encode()),
                    raw,
                ),
            )
        else:
            connection.execute(
                "UPDATE evaluation_executions SET record_sha256=?, data_json=? WHERE root_run_id=?",
                (sha256_bytes(raw.encode()), raw, binding.root_run_id),
            )
        kind = "registered" if new else record.status
        run = self.state._validated_run(connection, binding.root_run_id)
        event = self.state._event_for_run(
            run,
            f"evaluation.execution_{kind}",
            {
                "binding_sha256": binding.sha256,
                "claim_id": record.claim.claim_id,
                "revision": record.revision,
                "attempt_id": binding.submission.attempt_id,
                "campaign_id": binding.submission.campaign_id,
                "manifest_sha256": binding.submission.manifest_sha256,
            },
        )
        self.state._insert_event(
            connection, event.model_copy(update={"occurred_at": record.updated_at})
        )

    @_boundary
    def register(
        self,
        submission: EvaluationSubmission,
        run: Run,
        admission: EvaluationAdmission,
        bindings: RunModelBindings,
        *,
        organization_admission: OrganizationAdmission,
    ) -> EvaluationRegistration:
        admission = EvaluationAdmission.model_validate_json(admission.model_dump_json())
        run = Run.model_validate_json(run.model_dump_json())
        bindings = RunModelBindings.model_validate_json(bindings.model_dump_json())
        self._clean(
            (
                admission.model_dump(mode="json"),
                run.model_dump(mode="json"),
                bindings.model_dump(mode="json"),
            )
        )
        with self.ledger._transaction(write=True) as connection:
            manifest = self._manifest(connection, submission)
            row = connection.execute(
                "SELECT root_run_id FROM evaluation_executions WHERE attempt_id=?",
                (submission.attempt_id,),
            ).fetchone()
            if row:
                existing = self._record(connection, row[0])
                if existing is None or existing.binding.project_id != run.project_id:
                    raise _denied()
                return EvaluationRegistration(record=existing)
            self._assert_no_orphan_claim(connection, submission)
            if connection.execute(
                "SELECT 1 FROM evaluation_outcomes WHERE attempt_id=?", (submission.attempt_id,)
            ).fetchone():
                raise _denied()
            case = next(item for item in manifest.cases if item.case_id == submission.case_id)
            repo = next(
                item for item in manifest.repositories if item.repository_id == case.repository_id
            )
            if (
                run.parent_run_id is not None
                or run.sandbox_name not in {"fake", "docker"}
                or (run.sandbox_name == "fake" and case.image_identity is not None)
                or (run.sandbox_name == "docker" and case.image_identity is None)
                or run.status is not RunStatus.CREATED
                or run.stage is not None
                or run.task_id is not None
                or run.plan_review_required
                or run.goal != case.requirement
                or run.base_revision != repo.commit_sha
                or run.config_snapshot_hash != case.configuration_sha256
                or run.sandbox_image_identity != case.image_identity
                or admission.configuration_sha256 != case.configuration_sha256
                or admission.source.commit_sha != repo.commit_sha
                or admission.source.source_sha256 != repo.source_sha256
                or admission.source.dependencies_sha256 != case.dependencies_sha256
                or admission.commands != case.commands
                or bindings.root_run_id != run.run_id
                or bindings.project_id != run.project_id
                or bindings.bindings_sha256 != run.model_bindings_sha256
            ):
                raise _denied()
            profile_store = SqliteModelProfileStore(self.state)
            for binding in bindings.roles.values():
                profile, _ = profile_store._profile(connection, case.profile_id)
                if (
                    profile is None
                    or profile.name != binding.profile_name
                    or profile.revision != binding.profile_revision
                    or profile.revision != case.profile_revision
                    or canonical_json_hash(profile.model_dump(mode="json")) != case.profile_sha256
                    or profile.configuration != binding.configuration
                ):
                    raise _denied()
            budgets = self._budgets()
            self._admit_campaign(connection, submission.campaign_id, budgets)
            limits = RunBudgetLimits.model_validate(case.run_budget.model_dump())
            self.state._insert_run_in_transaction(
                connection, run, organization_admission=organization_admission
            )
            profile_store._save_bindings_in_transaction(connection, bindings)
            budgets._initialize_run_in_transaction(connection, run.run_id, limits)
            now = self.state.clock.now()
            reservation = next(
                item
                for item in self.ledger._snapshot(connection, submission.campaign_id).reservations
                if item.attempt_id == submission.attempt_id
            )
            if now < reservation.reserved_at:
                raise _denied()
            execution = EvaluationExecutionBinding(
                submission=submission,
                project_id=run.project_id,
                repository_identity=bindings.repository_identity,
                root_run_id=run.run_id,
                run_binding_sha256=run_execution_hash(run),
                case_sha256=canonical_json_hash(case.model_dump(mode="json")),
                source_sha256=repo.source_sha256,
                commit_sha=repo.commit_sha,
                configuration_sha256=case.configuration_sha256,
                model_bindings_sha256=bindings.bindings_sha256,
                image_identity=case.image_identity,
                dependencies_sha256=case.dependencies_sha256,
                commands=case.commands,
                limits=limits,
                admitted_at=now,
            )
            claim = EvaluationClaim(
                root_run_id=run.run_id,
                binding_sha256=execution.sha256,
                claim_id=self.state.ids.new(IdPrefix.CORRELATION),
            )
            record = EvaluationExecutionRecord(binding=execution, claim=claim, updated_at=now)
            self._write(connection, record, new=True)
            checked = self._record(connection, run.run_id)
            if checked is None:
                raise _denied()
            return EvaluationRegistration(record=checked, claim=claim)

    @_boundary
    def assert_claim(self, claim: EvaluationClaim) -> EvaluationExecutionRecord:
        with self.ledger._transaction(write=False) as connection:
            record = self._record(connection, claim.root_run_id)
            if record is None or record.claim != claim or record.status != "active":
                raise _denied()
            return record

    @_boundary
    def settle(self, claim: EvaluationClaim) -> EvaluationExecutionRecord:
        with self.ledger._transaction(write=True) as connection:
            record = self._record(connection, claim.root_run_id)
            if record is None or record.claim != claim:
                raise _denied()
            if record.status != "active":
                return record
            run = self.state._validated_run(connection, claim.root_run_id)
            if run.status in {RunStatus.CREATED, RunStatus.RUNNING}:
                raise _denied()
            updated = EvaluationExecutionRecord(
                binding=record.binding,
                claim=claim,
                status="settled",
                revision=2,
                updated_at=self.state.clock.now(),
            )
            self._write(connection, updated, new=False)
            return updated

    @_boundary
    def fence(self, root_run_id: str) -> EvaluationExecutionRecord:
        """Fence only; explicit resource recovery remains a separate trusted operation."""
        with self.ledger._transaction(write=True) as connection:
            record = self._record(connection, root_run_id)
            if record is None:
                raise _denied()
            if record.status != "active":
                return record
            updated = EvaluationExecutionRecord(
                binding=record.binding,
                claim=record.claim,
                status="fenced",
                revision=2,
                updated_at=self.state.clock.now(),
            )
            self._write(connection, updated, new=False)
            return updated
