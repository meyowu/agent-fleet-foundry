"""Observation candidate under repair; original-database terminal writes are disabled."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from agent_fleet.adapters.persistence.evaluation_capture import (
    capture_observation,
    capture_observation_async,
)
from agent_fleet.adapters.persistence.evaluation_execution import SqliteEvaluationExecutionStore
from agent_fleet.adapters.persistence.evaluations import SqliteEvaluationStore
from agent_fleet.adapters.persistence.runtime_budgets import SqliteRuntimeBudgetStore
from agent_fleet.adapters.persistence.sqlite import SqliteStateStore
from agent_fleet.domain.config import ConfigSnapshot
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.evaluation import CampaignId, EvaluationManifest, EvidenceCategory
from agent_fleet.domain.evaluation_execution import EvaluationExecutionRecord
from agent_fleet.domain.evaluation_observation import (
    EvaluationObservation,
    TerminalObservationResult,
)
from agent_fleet.domain.evidence import (
    CommandEvidence,
    CompletionGate,
    EvidenceBundle,
    ResourceCleanupReceipt,
)
from agent_fleet.domain.models import (
    ArtifactKind,
    ArtifactMetadata,
    FleetEvent,
    LeaseStatus,
    ResourceLease,
    Run,
    RunStatus,
    TaskSpec,
    VerifierVerdict,
)
from agent_fleet.domain.outcomes import AttemptId, OutcomeArtifactRef, OutcomeRecord, OutcomeUsage
from agent_fleet.domain.security import canonical_json_hash, sha256_bytes
from agent_fleet.ports.artifact_store import ArtifactStore

_MAX_TOTAL = 33_554_432
_TERMINAL = {RunStatus.FAILED, RunStatus.CANCELLED}
_FAILURES: dict[ErrorCode, TerminalObservationResult] = {
    ErrorCode.PROVIDER_FAILED: "provider_failure",
    ErrorCode.RUNTIME_BUDGET_EXCEEDED: "budget_exhausted",
    ErrorCode.SANDBOX_UNAVAILABLE: "environment_failure",
    ErrorCode.SANDBOX_IMAGE_UNAVAILABLE: "environment_failure",
    ErrorCode.SANDBOX_CAPABILITY_MISSING: "environment_failure",
    ErrorCode.RUNTIME_TIMEOUT: "timeout",
    ErrorCode.SANDBOX_TIMEOUT: "timeout",
}


def observation_error() -> FleetError:
    return FleetError(
        ErrorCode.RECOVERY_REQUIRED,
        "The selected evaluation evidence is unavailable, changed or inconsistent.",
        "Inspect the original attempt; no result, replay or repair was inferred.",
    )


@dataclass(frozen=True)
class _NoElapsedClock:
    def now(self) -> datetime:
        # Active attempts contribute no fabricated clock-dependent duration.
        # Finished intervals remain the durable lower bound across restarts.
        return datetime(1970, 1, 1, tzinfo=UTC)


@dataclass
class _Snapshot:
    manifest: EvaluationManifest
    execution: EvaluationExecutionRecord | None
    run: Run | None
    rows: dict[str, list[sqlite3.Row]]
    fingerprint: str


class SqliteEvaluationEvidence:
    def __init__(
        self, state: SqliteStateStore, artifacts: ArtifactStore, artifact_root: Path
    ) -> None:
        self.state, self.artifacts, self.artifact_root = state, artifacts, artifact_root
        self.ledger = SqliteEvaluationStore(state)
        self.executions = SqliteEvaluationExecutionStore(state)
        # Populated only by the fixed clean child over its retained source descriptors.
        self._source_identity: tuple[int, int] | None = None
        self._captured_artifact: Callable[[str], bytes | None] | None = None

    def _database(
        self, connection: sqlite3.Connection, campaign_id: str, attempt_id: str
    ) -> _Snapshot:
        rows: dict[str, list[sqlite3.Row]] = {}
        total = 0

        def select(table: str, where: str, parameters: tuple[Any, ...], limit: int = 4096) -> None:
            nonlocal total
            selected: list[sqlite3.Row] = []
            for row in connection.execute(
                f"SELECT * FROM {table} WHERE {where} ORDER BY rowid LIMIT ?",
                (*parameters, limit + 1),
            ):
                if len(selected) == limit:
                    raise observation_error()
                data = dict(row)
                if any(isinstance(value, bytes) for value in data.values()):
                    raise observation_error()
                encoded = json.dumps(data, sort_keys=True, ensure_ascii=False)
                total += len(encoded.encode())
                if total > _MAX_TOTAL or self.state.redactor.contains_secret(encoded):
                    raise observation_error()
                selected.append(row)
            rows[table] = selected

        for table in ("evaluation_campaigns", "evaluation_slots", "evaluation_reservations"):
            select(table, "campaign_id=?", (campaign_id,), 256)
        select("evaluation_executions", "attempt_id=?", (attempt_id,), 1)
        # Bound outcomes before the canonical ledger revalidator reads them.
        select("evaluation_outcomes", "campaign_id=?", (campaign_id,), 256)
        ledger = self.ledger._snapshot(connection, campaign_id)
        if not any(item.attempt_id == attempt_id for item in ledger.reservations):
            raise observation_error()
        execution_rows = rows["evaluation_executions"]
        if not execution_rows:
            reservation = next(
                item for item in ledger.reservations if item.attempt_id == attempt_id
            )
            from agent_fleet.domain.evaluation_execution import EvaluationSubmission

            self.executions._assert_no_orphan_claim(
                connection,
                EvaluationSubmission(
                    campaign_id=campaign_id,
                    manifest_sha256=ledger.registration.manifest.sha256,
                    case_id=reservation.case_id,
                    repetition=reservation.repetition,
                    attempt_id=attempt_id,
                ),
            )
            return _Snapshot(
                ledger.registration.manifest, None, None, rows, self._fingerprint(rows)
            )
        root = execution_rows[0]["root_run_id"]
        select("fleet_graph_nodes", "parent_run_id=?", (root,), 64)
        run_ids = (root, *(row["child_run_id"] for row in rows["fleet_graph_nodes"]))
        in_runs = "run_id IN (" + ",".join("?" for _ in run_ids) + ")"
        for table, limit in (
            ("runs", 65),
            ("tasks", 65),
            ("run_events", 100_000),
            ("artifacts", 256),
            ("resource_leases", 4096),
            ("agent_instances", 10_000),
            ("runtime_budget_runs", 65),
        ):
            select(table, in_runs, run_ids, limit)
        if len(rows["runs"]) != len(run_ids):
            raise observation_error()
        project_ids = {row["project_id"] for row in rows["runs"]}
        if len(project_ids) != 1:
            raise observation_error()
        project = next(iter(project_ids))
        select("projects", "project_id=?", (project,), 1)
        select("fleet_graphs", "parent_run_id=?", (root,), 1)
        select("runtime_budget_owners", "owner_run_id=?", (root,), 1)
        select("runtime_attempts", "owner_run_id=?", (root,), 10_000)
        attempt_query = (
            "attempt_id IN (SELECT attempt_id FROM runtime_attempts WHERE owner_run_id=?)"
        )
        for table in ("runtime_model_requests", "runtime_tool_batches", "runtime_simulated_steps"):
            select(table, attempt_query, (root,), 100_000)
        select("run_model_bindings", "root_run_id=?", (root,), 1)
        select(
            "model_configuration_audit",
            "sequence IN (SELECT audit_sequence FROM run_model_bindings WHERE root_run_id=?)",
            (root,),
            1,
        )
        execution = self.executions._record(connection, root)
        if execution is None or execution.binding.submission.attempt_id != attempt_id:
            raise observation_error()
        run = self.state._validated_run(connection, root)
        budgets = self._budgets()
        for run_id in run_ids:
            if budgets._owner(connection, run_id) != (root, execution.binding.limits):
                raise observation_error()
        return _Snapshot(
            ledger.registration.manifest, execution, run, rows, self._fingerprint(rows)
        )

    def _fingerprint(self, rows: dict[str, list[sqlite3.Row]]) -> str:
        if self._source_identity is None:
            raise observation_error()
        # The immutable outcome receipt itself is excluded, making exact retries stable.
        return canonical_json_hash(
            {
                "database_identity": list(self._source_identity),
                "rows": {
                    table: [
                        sha256_bytes(json.dumps(dict(row), sort_keys=True).encode())
                        for row in values
                    ]
                    for table, values in sorted(rows.items())
                    if table != "evaluation_outcomes"
                },
            }
        )

    def _budgets(self) -> SqliteRuntimeBudgetStore:
        return SqliteRuntimeBudgetStore(
            self.state.database_path,
            _NoElapsedClock(),
            self.state.ids,
            self.state.redactor,
            self.state,
        )

    def _artifact(self, metadata: ArtifactMetadata) -> str:
        digest = metadata.sha256
        expected = f"sha256/{digest[:2]}/{digest}"
        if metadata.content_ref != expected or not 0 <= metadata.byte_size <= 16_777_216:
            raise observation_error()
        if self._captured_artifact is None:
            raise observation_error()
        content = self._captured_artifact(expected)
        if content is None or len(content) != metadata.byte_size or sha256_bytes(content) != digest:
            raise observation_error()
        value = content.decode("utf-8")
        if self.state.redactor.contains_secret(value):
            raise observation_error()
        return value

    def _observe(
        self, connection: sqlite3.Connection, snapshot: _Snapshot, attempt_id: str
    ) -> EvaluationObservation:
        manifest, execution, run = snapshot.manifest, snapshot.execution, snapshot.run
        if execution is None or run is None:
            return EvaluationObservation(
                campaign_id=manifest.campaign_id,
                attempt_id=attempt_id,
                state="reserved",
                manifest_sha256=manifest.sha256,
                persisted_sha256=snapshot.fingerprint,
            )
        case = next(
            item for item in manifest.cases if item.case_id == execution.binding.submission.case_id
        )
        tasks = {
            row["task_id"]: TaskSpec.model_validate_json(row["data_json"])
            for row in snapshot.rows["tasks"]
        }
        if any(
            task.task_id != row["task_id"] or task.run_id != row["run_id"]
            for row in snapshot.rows["tasks"]
            for task in (tasks[row["task_id"]],)
        ):
            raise observation_error()
        if run.task_id is not None and (
            run.task_id not in tasks or tasks[run.task_id].run_id != run.run_id
        ):
            raise observation_error()
        events = []
        run_lookup = {
            row["run_id"]: Run.model_validate_json(row["data_json"])
            for row in snapshot.rows["runs"]
        }
        for row in snapshot.rows["run_events"]:
            event = FleetEvent.model_validate_json(row["data_json"])
            owner = run_lookup.get(event.run_id or "")
            if (
                owner is None
                or event.correlation_id != owner.correlation_id
                or any(
                    getattr(event, field) != row[field]
                    for field in ("event_id", "project_id", "run_id", "sequence", "event_type")
                )
                or event.occurred_at.isoformat() != row["occurred_at"]
            ):
                raise observation_error()
            if event.run_id == run.run_id:
                events.append(event)
        metadata_by_id = {}
        content_by_id = {}
        total = 0
        for row in snapshot.rows["artifacts"]:
            metadata = ArtifactMetadata.model_validate_json(row["data_json"])
            owner = run_lookup.get(metadata.run_id or "")
            if (
                owner is None
                or metadata.project_id != owner.project_id
                or any(
                    getattr(metadata, field) != row[field]
                    for field in ("artifact_id", "project_id", "run_id", "kind", "sha256")
                )
                or (metadata.task_id is not None and metadata.task_id != owner.task_id)
            ):
                raise observation_error()
            total += metadata.byte_size
            if total > _MAX_TOTAL:
                raise observation_error()
            metadata_by_id[metadata.artifact_id] = metadata
            content_by_id[metadata.artifact_id] = self._artifact(metadata)
        refs = []

        def bound(
            artifact_id: str | None,
            kind: ArtifactKind,
            digest: str | None,
            category: EvidenceCategory | None = None,
        ) -> str | None:
            if artifact_id is None:
                if digest is not None:
                    raise observation_error()
                return None
            metadata = metadata_by_id.get(artifact_id)
            if (
                metadata is None
                or metadata.run_id != run.run_id
                or metadata.kind is not kind
                or (kind is not ArtifactKind.CONFIG_SNAPSHOT and metadata.task_id != run.task_id)
                or (digest is not None and metadata.sha256 != digest)
            ):
                raise observation_error()
            if category is not None:
                refs.append(
                    OutcomeArtifactRef(
                        artifact_id=artifact_id,
                        category=category,
                        run_id=run.run_id,
                        sha256=metadata.sha256,
                    )
                )
            return content_by_id[artifact_id]

        config = bound(
            run.config_snapshot_artifact_id,
            ArtifactKind.CONFIG_SNAPSHOT,
            run.config_snapshot_hash if run.config_snapshot_artifact_id is not None else None,
        )
        if config is None and run.task_id is not None:
            raise observation_error()
        if config is not None:
            ConfigSnapshot.model_validate_json(config)
        task_content = bound(run.task_spec_artifact_id, ArtifactKind.TASK_SPEC, run.task_spec_hash)
        if run.task_id is not None and (
            task_content is None or TaskSpec.model_validate_json(task_content) != tasks[run.task_id]
        ):
            raise observation_error()
        bound(run.fleet_plan_artifact_id, ArtifactKind.FLEET_PLAN, run.fleet_plan_hash)
        bound(run.patch_artifact_id, ArtifactKind.PATCH, run.patch_sha256, "patch")
        commands = []
        for artifact_id in run.runtime_usage_artifact_ids:
            bound(artifact_id, ArtifactKind.RUNTIME_USAGE, None)
        for artifact_id in run.command_evidence_artifact_ids:
            content = bound(artifact_id, ArtifactKind.COMMAND_EVIDENCE, None, "verification")
            assert content is not None
            command = CommandEvidence.model_validate_json(content)
            commands.append(command)
            if (
                command.evidence_id != artifact_id
                or command.run_id != run.run_id
                or command.task_id != run.task_id
            ):
                raise observation_error()
            bound(command.transcript_artifact_id, ArtifactKind.COMMAND_TRANSCRIPT, None)
            bound(
                command.sandbox_inspection_artifact_id,
                ArtifactKind.SANDBOX_INSPECTION,
                command.sandbox_inspection_sha256,
            )
        verdict_content = bound(
            run.verifier_verdict_artifact_id, ArtifactKind.VERIFIER_VERDICT, None
        )
        if verdict_content is not None:
            VerifierVerdict.model_validate_json(verdict_content)
        bundle_content = bound(
            run.evidence_bundle_artifact_id, ArtifactKind.EVIDENCE_BUNDLE, run.evidence_bundle_hash
        )
        if bundle_content is not None:
            bundle = EvidenceBundle.model_validate_json(bundle_content)
            if (
                bundle.run_id != run.run_id
                or bundle.task_id != run.task_id
                or bundle.project_id != run.project_id
                or bundle.config_snapshot_sha256 != run.config_snapshot_hash
                or bundle.task_spec_sha256 != run.task_spec_hash
                or bundle.fleet_plan_sha256 != run.fleet_plan_hash
                or bundle.patch_sha256 != run.patch_sha256
                or bundle.command_evidence != commands
                or bundle.completion_decision is None
                or bundle.completion_decision.verified_complete != run.verified_complete
                or bundle.completion_decision.effective_verdict != run.assurance_verdict
            ):
                raise observation_error()
            if (
                run.task_id is None
                or CompletionGate.evaluate(
                    bundle,
                    expected_criteria={
                        item.criterion_id for item in tasks[run.task_id].acceptance_criteria
                    },
                    authoritative_artifact_ids=set(metadata_by_id),
                )
                != bundle.completion_decision
            ):
                raise observation_error()
        elif run.verified_complete or run.assurance_verdict is not None:
            raise observation_error()
        leases = []
        for row in snapshot.rows["resource_leases"]:
            lease = ResourceLease.model_validate_json(row["data_json"])
            if any(
                getattr(lease, field) != row[field]
                for field in ("lease_id", "run_id", "kind", "resource_id", "status")
            ):
                raise observation_error()
            leases.append(lease)
        cleanup = bound(
            run.cleanup_receipt_artifact_id,
            ArtifactKind.RESOURCE_CLEANUP,
            run.cleanup_receipt_sha256,
            "cleanup",
        )
        if cleanup is not None:
            receipt = ResourceCleanupReceipt.model_validate_json(cleanup)
            actual = {
                (lease.lease_id, lease.kind, lease.resource_id, lease.status)
                for lease in leases
                if lease.run_id == run.run_id
            }
            observed = {
                (item.lease_id, item.kind, item.resource_id, item.status) for item in receipt.leases
            }
            if receipt.run_id != run.run_id or actual != observed:
                raise observation_error()
        budget = self._budgets()._snapshot(connection, run.run_id)
        attempts = self._budgets()._attempts(connection, run.run_id)
        # Explicit outstanding reservations remain unknown once an execution has ended.
        unknown = budget.unknown_requests + budget.outstanding_requests
        failure = None
        for event in sorted(events, key=lambda item: item.sequence or 0):
            if event.event_type == "run.failed":
                value = event.payload.get("code")
                failure = ErrorCode(value) if isinstance(value, str) else None
        state: Any = "active"
        result: TerminalObservationResult | None = None
        if run.status in _TERMINAL and execution.status != "active":
            if unknown:
                state, result = "dispatch_unknown", "dispatch_unknown"
            elif run.status is RunStatus.CANCELLED:
                state, result = "cancelled", "cancelled"
            else:
                state, result = (
                    "failed",
                    _FAILURES.get(failure, "inconclusive") if failure else "inconclusive",
                )
        elif run.status is RunStatus.READY_FOR_REVIEW:
            state = "awaiting_apply" if case.task_kind == "code_change" else "awaiting_oracle"
        elif run.status is RunStatus.COMPLETED:
            state = "awaiting_oracle"
        return EvaluationObservation(
            campaign_id=manifest.campaign_id,
            attempt_id=attempt_id,
            state=state,
            manifest_sha256=manifest.sha256,
            case_id=case.case_id,
            repetition=execution.binding.submission.repetition,
            root_run_id=run.run_id,
            task_id=run.task_id,
            configuration_sha256=case.configuration_sha256,
            oracle_sha256=case.oracle_sha256,
            scoring_sha256=case.scoring_sha256,
            persisted_sha256=snapshot.fingerprint,
            product_status=run.status,
            product_verdict=run.assurance_verdict,
            product_verified_complete=run.verified_complete,
            failure_code=failure,
            terminal_result=result,
            apply_status="not_applicable"
            if case.task_kind == "read_only"
            else "not_applied"
            if run.applied_revision is None
            else "unknown",
            artifacts=tuple(refs),
            verified_artifact_count=len(metadata_by_id),
            usage=(
                OutcomeUsage(
                    segment_id="root",
                    model_requests=budget.model_requests,
                    tool_calls=budget.tool_calls,
                    input_tokens=budget.reported_input_tokens,
                    output_tokens=budget.reported_output_tokens,
                    active_milliseconds=int(budget.active_seconds * 1000)
                    if all(item.finished_at is not None for item in attempts)
                    else None,
                    unknown_requests=unknown,
                ),
            ),
            durable_released_leases=sum(
                lease.status in {LeaseStatus.RELEASED, LeaseStatus.RECOVERED} for lease in leases
            ),
            durable_outstanding_leases=sum(
                lease.status not in {LeaseStatus.RELEASED, LeaseStatus.RECOVERED}
                for lease in leases
            ),
        )

    def inspect_attempt(self, campaign_id: str, attempt_id: str) -> EvaluationObservation:
        return self._inspect_attempt(campaign_id, attempt_id)

    async def inspect_attempt_async(
        self, campaign_id: str, attempt_id: str
    ) -> EvaluationObservation:
        result: EvaluationObservation = await capture_observation_async(
            lambda cancelled: self._inspect_attempt(campaign_id, attempt_id, cancelled)
        )
        return result

    def _inspect_attempt(
        self, campaign_id: str, attempt_id: str, cancelled: threading.Event | None = None
    ) -> EvaluationObservation:
        valid = False
        try:
            TypeAdapter(CampaignId).validate_python(campaign_id, strict=True)
            TypeAdapter(AttemptId).validate_python(attempt_id, strict=True)
            valid = not self.state.redactor.contains_secret_data((campaign_id, attempt_id))
        except (ValueError, TypeError):
            pass
        if not valid:
            raise observation_error()
        result = None
        try:
            # Never send registered values, representations, hashes or lengths to a child.
            if not self.state.redactor.has_registered_secrets():
                raw = capture_observation(
                    self.state.database_path, self.artifact_root, campaign_id, attempt_id, cancelled
                )
                if raw is not None:
                    candidate = EvaluationObservation.model_validate_json(raw)
                    if (
                        candidate.campaign_id == campaign_id
                        and candidate.attempt_id == attempt_id
                        and not self.state.redactor.has_registered_secrets()
                        and not self.state.redactor.contains_secret(raw)
                    ):
                        result = candidate
        except (
            FleetError,
            sqlite3.Error,
            OSError,
            ValueError,
            TypeError,
            KeyError,
            OverflowError,
            subprocess.SubprocessError,
        ):
            pass
        if result is None:
            return EvaluationObservation(
                campaign_id=campaign_id,
                attempt_id=attempt_id,
                state="corrupt",
                evidence_issue="evidence_invalid",
            )
        return result

    def record_terminal(
        self, observation: EvaluationObservation, record: OutcomeRecord
    ) -> OutcomeRecord:
        # The same denial applies to direct adapter callers, before any state access.
        raise FleetError(
            ErrorCode.STATE_UNAVAILABLE,
            "Evaluation terminal recording is disabled: its write boundary is unqualified.",
            "Preserve the original attempt and evidence. "
            "No result, refund or replay is authorized.",
            details={
                "feature": "evaluation_terminal_recording",
                "reason": "write_boundary_unqualified",
            },
        )
