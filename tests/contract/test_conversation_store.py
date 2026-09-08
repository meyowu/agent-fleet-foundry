"""Conversation transactions use real SQLite and never invoke a provider or sandbox."""

from __future__ import annotations

import json
import multiprocessing
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from multiprocessing.connection import Connection
from multiprocessing.synchronize import Barrier as ProcessBarrier
from pathlib import Path
from threading import Barrier

import pytest

from agent_fleet.adapters.persistence.conversations import SqliteConversationStore
from agent_fleet.adapters.persistence.sqlite import SUPPORTED_SCHEMA_VERSION, SqliteStateStore
from agent_fleet.adapters.system import SystemClock, UuidIdGenerator
from agent_fleet.domain.budgets import RunBudgetLimits
from agent_fleet.domain.conversation import (
    Conversation,
    ConversationArtifactRef,
    ConversationClaim,
    ConversationContext,
    ConversationContextEntry,
    ConversationRegistration,
    ConversationSubmission,
    ConversationSummary,
    ConversationTurnStatus,
)
from agent_fleet.domain.errors import ConversationOwnershipUnavailableError, ErrorCode, FleetError
from agent_fleet.domain.ids import IdPrefix
from agent_fleet.domain.models import (
    ArtifactKind,
    ArtifactMetadata,
    FleetEvent,
    LeaseKind,
    LeaseStatus,
    Project,
    ResourceLease,
    Run,
    RunStatus,
    WorkflowStage,
)
from agent_fleet.domain.security import Redactor


@dataclass
class TickingClock:
    value: datetime = datetime(2026, 9, 5, tzinfo=UTC)

    def now(self) -> datetime:
        self.value += timedelta(microseconds=1)
        return self.value


@dataclass
class ConversationHarness:
    state: SqliteStateStore
    store: SqliteConversationStore
    project: Project
    conversation: Conversation

    def reopen(self) -> SqliteConversationStore:
        return SqliteConversationStore(
            self.state.database_path,
            self.state.clock,
            self.state.ids,
            self.state.redactor,
            self.state,
        )

    def run(self, goal: str = "Explain the reviewed repository") -> Run:
        now = self.state.clock.now()
        return Run(
            run_id=self.state.ids.new(IdPrefix.RUN),
            project_id=self.project.project_id,
            correlation_id=self.state.ids.new(IdPrefix.CORRELATION),
            goal=goal,
            base_revision="a" * 40,
            target_status_fingerprint="3" * 64,
            created_at=now,
            updated_at=now,
        )

    def submission(self, key: str = "first") -> ConversationSubmission:
        conversation = self.store.get(self.project.project_id, self.conversation.conversation_id)
        entries = tuple(
            ConversationContextEntry(
                turn_id=turn.binding.turn_id,
                sequence=turn.binding.sequence,
                run_id=turn.binding.run_id,
                run_status=turn.observed_run_status,
                user_summary=turn.user_summary,
                result_summary=turn.result_summary,
                artifact_refs=turn.artifact_refs,
            )
            for turn in reversed(
                self.store.list_turns(
                    self.project.project_id, conversation.conversation_id, limit=8
                )
            )
        )
        return ConversationSubmission(
            conversation_id=conversation.conversation_id,
            project_id=self.project.project_id,
            repository_identity=self.project.identity_hash,
            submission_key=key,
            expected_revision=conversation.revision,
            context=ConversationContext(
                conversation_id=conversation.conversation_id,
                project_id=self.project.project_id,
                through_sequence=conversation.next_turn_sequence - 1,
                entries=entries,
            ),
            user_summary=ConversationSummary(text="Explain the reviewed repository"),
        )

    def register(
        self, submission: ConversationSubmission | None = None, run: Run | None = None
    ) -> ConversationRegistration:
        return self.store.register_turn_run(
            submission or self.submission(),
            run or self.run(),
            config_snapshot_sha256="2" * 64,
            budget_limits=RunBudgetLimits(),
        )

    def move(self, run_id: str, *, pause: bool = False, ready: bool = False) -> Run:
        run = self.state.get_run(run_id)
        for stage in (
            WorkflowStage.INTAKE,
            WorkflowStage.SCOPING,
            WorkflowStage.WORKSPACE_PREPARATION,
            WorkflowStage.IMPLEMENTING,
        ):
            run = self.state.save_run(
                run.model_copy(update={"status": RunStatus.RUNNING, "stage": stage}),
                "run.transitioned",
                {},
            )
        if pause:
            return self.state.save_run(
                run.model_copy(update={"status": RunStatus.PAUSED_FOR_APPROVAL}), "run.paused", {}
            )
        run = self.state.save_run(
            run.model_copy(update={"stage": WorkflowStage.PRESENTING}), "run.presenting", {}
        )
        return self.state.save_run(
            run.model_copy(
                update={"status": RunStatus.READY_FOR_REVIEW if ready else RunStatus.COMPLETED}
            ),
            "run.delivered",
            {},
        )


@pytest.fixture
def conversation_harness(tmp_path: Path) -> ConversationHarness:
    clock = TickingClock()
    state = SqliteStateStore(tmp_path / "state.db", clock, UuidIdGenerator(), Redactor())
    assert state.migrate() == SUPPORTED_SCHEMA_VERSION
    now = clock.now()
    project = Project(
        project_id=state.ids.new(IdPrefix.PROJECT),
        canonical_root=str(tmp_path / "repository"),
        identity_hash="1" * 64,
        fleet_spec_hash="2" * 64,
        created_at=now,
        updated_at=now,
    )
    state.save_project(project)
    store = SqliteConversationStore(state.database_path, clock, state.ids, state.redactor, state)
    assert store.latest(project.project_id, project.identity_hash) is None
    conversation = store.create(project.project_id, project.identity_hash)
    return ConversationHarness(state, store, project, conversation)


def _claim(registration: ConversationRegistration) -> ConversationClaim:
    assert registration.claim is not None
    return registration.claim


def test_registration_creates_exact_run_binding_claim_and_audit_before_dispatch(
    conversation_harness: ConversationHarness,
) -> None:
    h = conversation_harness
    run = h.run()
    registration = h.register(run=run)
    turn = registration.turn
    assert h.state.get_run(run.run_id) == run
    assert h.reopen().binding_for_run(run.run_id) == turn.binding
    assert h.reopen().assert_claim(_claim(registration)) == turn
    latest = h.store.latest(h.project.project_id, h.project.identity_hash)
    assert latest is not None and latest.active_turn_id == turn.binding.turn_id
    events = h.state.list_events(run.run_id)
    assert [event.event_type for event in events] == [
        "run.created",
        "conversation.claim_issued",
        "conversation.turn_registered",
    ]
    assert events[0].payload["conversation_turn_id"] == turn.binding.turn_id
    with h.state._connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM runtime_budget_runs").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM agent_instances").fetchone()[0] == 0


def test_duplicate_submission_returns_original_without_owner_even_with_stale_revision(
    conversation_harness: ConversationHarness,
) -> None:
    h = conversation_harness
    submission = h.submission()
    first = h.register(submission)
    fresh = h.run().model_copy(update={"base_revision": "b" * 40})
    duplicate = h.register(submission, fresh)
    assert duplicate.turn == first.turn and duplicate.claim is None
    assert (
        h.reopen().get_submission(h.project.project_id, h.conversation.conversation_id, "first")
        == first.turn
    )
    with h.state._connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1
        assert (
            connection.execute("SELECT COUNT(*) FROM conversation_turn_claims").fetchone()[0] == 1
        )


@pytest.mark.parametrize("change", ["goal", "summary", "config", "budget"])
def test_same_key_changed_submission_is_rejected(
    conversation_harness: ConversationHarness, change: str
) -> None:
    h = conversation_harness
    submission = h.submission()
    h.register(submission)
    run = h.run("Different goal" if change == "goal" else "Explain the reviewed repository")
    if change == "summary":
        submission = submission.model_copy(
            update={"user_summary": ConversationSummary(text="Different")}
        )
    with pytest.raises(FleetError) as error:
        h.store.register_turn_run(
            submission,
            run,
            config_snapshot_sha256=("4" if change == "config" else "2") * 64,
            budget_limits=RunBudgetLimits(max_tool_calls=1)
            if change == "budget"
            else RunBudgetLimits(),
        )
    assert error.value.code is ErrorCode.COMMAND_DENIED
    assert error.value.__context__ is None


def test_atomic_registration_rolls_back_run_claim_turn_and_events(
    conversation_harness: ConversationHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = conversation_harness
    original = h.state._insert_event

    def fail(connection: sqlite3.Connection, event: FleetEvent) -> FleetEvent:
        if event.event_type == "conversation.turn_registered":
            raise sqlite3.OperationalError("injected transaction fault")
        return original(connection, event)

    monkeypatch.setattr(h.state, "_insert_event", fail)
    with pytest.raises(FleetError) as error:
        h.register()
    assert error.value.code is ErrorCode.STATE_UNAVAILABLE
    with h.state._connect() as connection:
        for table in ("runs", "conversation_turns", "conversation_turn_claims"):
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM run_events").fetchone()[0] == 1
    assert h.store.get(h.project.project_id, h.conversation.conversation_id) == h.conversation


def test_waiting_resume_is_cas_owned_and_retains_exact_context_and_budget(
    conversation_harness: ConversationHarness,
) -> None:
    h = conversation_harness
    first = h.register()
    h.move(first.turn.binding.run_id, pause=True)
    waiting = h.store.settle(_claim(first), expected_revision=0)
    assert waiting.status is ConversationTurnStatus.WAITING
    assert waiting.active_claim_id is None
    barrier = Barrier(2, timeout=10)

    def claim(_: int) -> ConversationClaim | None:
        store = h.reopen()
        barrier.wait()
        try:
            return store.claim_resume(first.turn.binding.run_id, expected_revision=waiting.revision)
        except ConversationOwnershipUnavailableError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(claim, range(2)))
    winners = [claim for claim in claims if claim is not None]
    assert len(winners) == 1
    owned = h.store.assert_claim(winners[0])
    assert owned.binding == waiting.binding and owned.context == waiting.context
    assert winners[0].generation == 2
    again = h.store.settle(winners[0], expected_revision=owned.revision)
    assert again.status is ConversationTurnStatus.WAITING
    with pytest.raises(ConversationOwnershipUnavailableError):
        h.store.assert_claim(_claim(first))


def test_cancel_and_recovery_fences_keep_turn_active_until_clean(
    conversation_harness: ConversationHarness,
) -> None:
    h = conversation_harness
    first = h.register()
    run_id = first.turn.binding.run_id
    with pytest.raises(ConversationOwnershipUnavailableError):
        h.store.fence(run_id, expected_revision=0, reason="cancel")
    fenced = h.store.fence(run_id, expected_revision=0, reason="cancel", claim=_claim(first))
    assert fenced.updated_at == fenced.fenced_at
    assert h.state.get_run(run_id).status is RunStatus.CANCELLED
    assert (
        h.store.get(h.project.project_id, h.conversation.conversation_id).active_turn_id is not None
    )
    with pytest.raises(ConversationOwnershipUnavailableError):
        h.store.assert_claim(_claim(first))
    lease = ResourceLease(
        lease_id=h.state.ids.new(IdPrefix.LEASE),
        run_id=run_id,
        kind=LeaseKind.WORKTREE,
        resource_id=h.state.ids.new(IdPrefix.WORKSPACE),
        status=LeaseStatus.ACTIVE,
        created_at=h.state.clock.now(),
        updated_at=h.state.clock.now(),
    )
    h.state.save_lease(lease)
    with pytest.raises(ConversationOwnershipUnavailableError):
        h.store.reconcile_fenced(run_id, expected_revision=fenced.revision)
    h.state.update_lease_status(lease.lease_id, "recovered")
    final = h.store.reconcile_fenced(run_id, expected_revision=fenced.revision)
    assert final.status is ConversationTurnStatus.CANCELLED
    assert h.store.get(h.project.project_id, h.conversation.conversation_id).active_turn_id is None


def test_claimed_created_run_never_replays_and_explicit_recovery_does_not_invent_budget(
    conversation_harness: ConversationHarness,
) -> None:
    h = conversation_harness
    first = h.register()
    with pytest.raises(ConversationOwnershipUnavailableError):
        h.reopen().claim_resume(first.turn.binding.run_id, expected_revision=0)
    fenced = h.reopen().fence(first.turn.binding.run_id, expected_revision=0, reason="recovery")
    assert h.state.get_run(first.turn.binding.run_id).status is RunStatus.FAILED
    final = h.store.reconcile_fenced(first.turn.binding.run_id, expected_revision=fenced.revision)
    assert final.status is ConversationTurnStatus.FAILED
    with h.state._connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM runtime_budget_runs").fetchone()[0] == 0


def test_history_survives_later_apply_and_original_duplicate_after_new_turn(
    conversation_harness: ConversationHarness,
) -> None:
    h = conversation_harness
    original = h.submission()
    first = h.register(original)
    run = h.move(first.turn.binding.run_id, ready=True)
    delivered = h.store.settle(
        _claim(first), expected_revision=0, summary=ConversationSummary(text="Review the patch")
    )
    run = h.state.save_run(
        run.model_copy(update={"status": RunStatus.APPLYING, "stage": WorkflowStage.APPLYING}),
        "patch.applying",
        {},
    )
    run = h.state.save_run(
        run.model_copy(update={"status": RunStatus.RUNNING, "stage": WorkflowStage.CLEANUP}),
        "patch.applied",
        {},
    )
    h.state.save_run(run.model_copy(update={"status": RunStatus.COMPLETED}), "run.completed", {})
    second = h.register(h.submission("second"))
    assert second.turn.context.entries[0].run_status is RunStatus.READY_FOR_REVIEW
    assert h.register(original).turn == delivered
    assert h.register(original).claim is None
    assert [
        turn.binding.sequence
        for turn in h.store.list_turns(
            h.project.project_id, h.conversation.conversation_id, limit=1
        )
    ] == [2]
    assert [
        turn.binding.sequence
        for turn in h.store.list_turns(
            h.project.project_id, h.conversation.conversation_id, before_sequence=2
        )
    ] == [1]


@pytest.mark.parametrize(
    "corruption", ["run_sql", "run_json", "turn_sql", "binding", "owner", "context", "missing"]
)
def test_corrupt_identity_or_coherent_owner_clear_never_grants_replay(
    conversation_harness: ConversationHarness, corruption: str
) -> None:
    h = conversation_harness
    first = h.register()
    run_id = first.turn.binding.run_id
    with h.state._connect() as connection:
        if corruption == "run_sql":
            connection.execute("UPDATE runs SET status='failed' WHERE run_id=?", (run_id,))
        elif corruption == "run_json":
            run = h.state.get_run(run_id).model_copy(update={"goal": "tampered"})
            connection.execute(
                "UPDATE runs SET data_json=? WHERE run_id=?", (run.model_dump_json(), run_id)
            )
        elif corruption == "turn_sql":
            connection.execute(
                "UPDATE conversation_turns SET sequence=99 WHERE run_id=?", (run_id,)
            )
        elif corruption == "binding":
            binding = first.turn.binding.model_copy(update={"user_goal_sha256": "9" * 64})
            connection.execute(
                "UPDATE conversation_turns SET binding_json=? WHERE run_id=?",
                (binding.model_dump_json(), run_id),
            )
        elif corruption == "owner":
            turn = first.turn.model_copy(
                update={"active_claim_id": None, "status": ConversationTurnStatus.WAITING}
            )
            connection.execute(
                "UPDATE conversation_turns SET active_claim_id=NULL,status='waiting',data_json=? "
                "WHERE run_id=?",
                (turn.model_dump_json(), run_id),
            )
            connection.execute(
                "UPDATE conversation_turn_claims SET status='released',released_at=? "
                "WHERE run_id=?",
                (h.state.clock.now().isoformat(), run_id),
            )
        elif corruption == "context":
            data = json.loads(first.turn.model_dump_json())
            data["context"]["through_sequence"] = 1
            connection.execute(
                "UPDATE conversation_turns SET data_json=? WHERE run_id=?",
                (json.dumps(data), run_id),
            )
        else:
            connection.execute("PRAGMA foreign_keys=OFF")
            # Detect a binding removed outside the trusted APIs.
            connection.execute("UPDATE conversations SET active_turn_id=NULL")
            connection.execute("DELETE FROM conversation_turn_claims")
            connection.execute("DELETE FROM conversation_turns")
    with pytest.raises(FleetError) as error:
        h.reopen().binding_for_run(run_id)
    assert error.value.code is ErrorCode.RECOVERY_REQUIRED
    assert error.value.__context__ is None


def test_secret_corruption_is_cause_free_and_new_secret_submission_never_persists(
    conversation_harness: ConversationHarness,
) -> None:
    h = conversation_harness
    sentinel = "chat-persistence-private-token-987654"
    h.state.redactor.register_secret(sentinel)
    with pytest.raises(FleetError) as error:
        h.register(run=h.run(sentinel))
    assert sentinel not in str(error.value) and error.value.__context__ is None
    first = h.register()
    with h.state._connect() as connection:
        data = json.loads(first.turn.model_dump_json())
        data["unknown"] = sentinel
        connection.execute(
            "UPDATE conversation_turns SET data_json=? WHERE run_id=?",
            (json.dumps(data), first.turn.binding.run_id),
        )
    with pytest.raises(FleetError) as error:
        h.store.get_turn(h.project.project_id, first.turn.binding.turn_id)
    assert sentinel not in str(error.value) and error.value.__context__ is None


def test_project_isolation_and_context_tampering_are_rejected(
    conversation_harness: ConversationHarness,
) -> None:
    h = conversation_harness
    other = h.project.model_copy(
        update={
            "project_id": h.state.ids.new(IdPrefix.PROJECT),
            "canonical_root": "/separate-fixture",
        }
    )
    h.state.save_project(other)
    with pytest.raises(FleetError):
        h.store.get(other.project_id, h.conversation.conversation_id)
    first = h.register()
    h.move(first.turn.binding.run_id)
    h.store.settle(_claim(first), expected_revision=0)
    submission = h.submission("second")
    entry = submission.context.entries[0].model_copy(
        update={"result_summary": ConversationSummary(text="invented")}
    )
    tampered = submission.model_copy(
        update={"context": submission.context.model_copy(update={"entries": (entry,)})}
    )
    with pytest.raises(FleetError):
        h.register(tampered)


def _register_process(
    path: Path, submission_json: str, run_json: str, barrier: ProcessBarrier, result: Connection
) -> None:
    state = SqliteStateStore(path, SystemClock(), UuidIdGenerator(), Redactor())
    store = SqliteConversationStore(path, state.clock, state.ids, state.redactor, state)
    barrier.wait(timeout=15)
    try:
        registration = store.register_turn_run(
            ConversationSubmission.model_validate_json(submission_json),
            Run.model_validate_json(run_json),
            config_snapshot_sha256="2" * 64,
            budget_limits=RunBudgetLimits(),
        )
        result.send((registration.turn.binding.run_id, registration.claim is not None))
    finally:
        result.close()


def test_two_process_registration_has_exactly_one_run_and_one_owner(
    conversation_harness: ConversationHarness,
) -> None:
    h = conversation_harness
    submission = h.submission()
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(2)
    connections = [context.Pipe(duplex=False) for _ in range(2)]
    processes = [
        context.Process(
            target=_register_process,
            args=(
                h.state.database_path,
                submission.model_dump_json(),
                h.run().model_dump_json(),
                barrier,
                send,
            ),
        )
        for _, send in connections
    ]
    for process in processes:
        process.start()
    results = []
    for receive, send in connections:
        send.close()
        assert receive.poll(20)
        results.append(receive.recv())
        receive.close()
    for process in processes:
        process.join(timeout=20)
        assert process.exitcode == 0
    assert len({result[0] for result in results}) == 1
    assert sum(result[1] for result in results) == 1
    with h.state._connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1
        assert (
            connection.execute("SELECT COUNT(*) FROM conversation_turn_claims").fetchone()[0] == 1
        )


def test_new_key_while_owned_and_premature_settlement_cannot_release_owner(
    conversation_harness: ConversationHarness,
) -> None:
    h = conversation_harness
    submission = h.submission()
    first = h.register(submission)
    current = h.store.get(h.project.project_id, h.conversation.conversation_id)
    second = submission.model_copy(
        update={"submission_key": "second", "expected_revision": current.revision}
    )
    with pytest.raises(ConversationOwnershipUnavailableError):
        h.register(second)
    with pytest.raises(FleetError):
        h.store.settle(_claim(first), expected_revision=0)
    assert h.reopen().assert_claim(_claim(first)) == first.turn
    with h.state._connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1


def test_ref_metadata_hash_and_exact_root_owner_are_required(
    conversation_harness: ConversationHarness,
) -> None:
    h = conversation_harness
    first = h.register()
    run = h.move(first.turn.binding.run_id)
    artifact = ArtifactMetadata(
        artifact_id=h.state.ids.new(IdPrefix.ARTIFACT),
        project_id=h.project.project_id,
        run_id=run.run_id,
        task_id=None,
        kind=ArtifactKind.RUN_SUMMARY,
        producer="control-plane",
        mime_type="text/plain",
        sha256="a" * 64,
        byte_size=12,
        content_ref="sha256:" + "a" * 64,
        redacted=False,
        created_at=h.state.clock.now(),
    )
    h.state.save_artifact(artifact)
    reference = ConversationArtifactRef(
        artifact_id=artifact.artifact_id,
        sha256=artifact.sha256,
        run_id=run.run_id,
        kind=artifact.kind,
    )
    for invalid in (
        reference.model_copy(update={"sha256": "b" * 64}),
        reference.model_copy(update={"run_id": "run_" + "f" * 32}),
        reference.model_copy(update={"kind": ArtifactKind.COS_RESPONSE}),
    ):
        with pytest.raises(FleetError):
            h.store.settle(_claim(first), expected_revision=0, artifact_refs=(invalid,))
    final = h.store.settle(_claim(first), expected_revision=0, artifact_refs=(reference,))
    assert final.artifact_refs == (reference,)
    with h.state._connect() as connection:
        connection.execute(
            "UPDATE artifacts SET sha256=? WHERE artifact_id=?", ("b" * 64, artifact.artifact_id)
        )
    with pytest.raises(FleetError):
        h.reopen().get_turn(h.project.project_id, first.turn.binding.turn_id)


def test_terminal_run_with_unresolved_resource_keeps_conversation_blocked(
    conversation_harness: ConversationHarness,
) -> None:
    h = conversation_harness
    first = h.register()
    run = h.move(first.turn.binding.run_id)
    lease = ResourceLease(
        lease_id=h.state.ids.new(IdPrefix.LEASE),
        run_id=run.run_id,
        resource_id=h.state.ids.new(IdPrefix.WORKSPACE),
        kind=LeaseKind.WORKTREE,
        status=LeaseStatus.FAILED,
        created_at=h.state.clock.now(),
        updated_at=h.state.clock.now(),
    )
    h.state.save_lease(lease)
    blocked = h.store.settle(_claim(first), expected_revision=0)
    assert blocked.status is ConversationTurnStatus.RECOVERY_REQUIRED
    assert blocked.active_claim_id is None
    with pytest.raises(ConversationOwnershipUnavailableError):
        h.store.claim_resume(run.run_id, expected_revision=blocked.revision)
    h.state.update_lease_status(lease.lease_id, "recovered")
    settled = h.store.reconcile_fenced(run.run_id, expected_revision=blocked.revision)
    assert settled.status is ConversationTurnStatus.DELIVERED


@pytest.mark.parametrize("version", [6, SUPPORTED_SCHEMA_VERSION + 1])
def test_missing_or_future_schema_history_fails_closed(
    conversation_harness: ConversationHarness,
    version: int,
) -> None:
    h = conversation_harness
    with h.state._connect() as connection:
        if version == 6:
            connection.execute("DELETE FROM schema_migrations WHERE version=6")
        else:
            connection.execute(
                "INSERT INTO schema_migrations(version,applied_at) VALUES (?,?)",
                (version, h.state.clock.now().isoformat()),
            )
    with pytest.raises(FleetError) as error:
        h.store.get(h.project.project_id, h.conversation.conversation_id)
    assert error.value.code is ErrorCode.RECOVERY_REQUIRED


def test_injected_fence_audit_failure_rolls_back_run_and_claim(
    conversation_harness: ConversationHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = conversation_harness
    first = h.register()
    original = h.state._insert_event

    def fail(connection: sqlite3.Connection, event: FleetEvent) -> FleetEvent:
        if event.event_type == "conversation.turn_fenced":
            raise sqlite3.OperationalError("injected fence event failure")
        return original(connection, event)

    monkeypatch.setattr(h.state, "_insert_event", fail)
    with pytest.raises(FleetError):
        h.store.fence(first.turn.binding.run_id, expected_revision=0, reason="recovery")
    assert h.state.get_run(first.turn.binding.run_id).status is RunStatus.CREATED
    assert h.reopen().assert_claim(_claim(first)) == first.turn
