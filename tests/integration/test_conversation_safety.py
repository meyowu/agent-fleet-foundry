"""Independent chat authority tests through normal offline workflow execution."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Literal

import pytest
from conftest import FleetHarness
from pydantic import JsonValue

from agent_fleet.adapters.artifacts.local import LocalArtifactStore
from agent_fleet.adapters.repository.git import GitRepositoryAdapter
from agent_fleet.adapters.runtime.fake import FakeRuntimeAdapter
from agent_fleet.adapters.system import UuidIdGenerator
from agent_fleet.application import conversations as conversation_module
from agent_fleet.application.conversations import ChatExecutionOptions
from agent_fleet.application.runtime import RuntimeRegistry
from agent_fleet.bootstrap import ApplicationContainer, build_container
from agent_fleet.domain.budgets import RunBudgetLimits
from agent_fleet.domain.conversation import (
    ConversationArtifactRef,
    ConversationClaim,
    ConversationContext,
    ConversationSummary,
    ConversationTurn,
)
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import (
    AgentInvocation,
    AgentInvocationResult,
    AgentRole,
    ApprovalChoice,
    ApprovalStatus,
    FakeScenario,
    Run,
    RunStatus,
)
from agent_fleet.domain.trust import TrustMode
from agent_fleet.ports.runtime import RuntimeInvocationServices

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


class RecordingRuntime(FakeRuntimeAdapter):
    def __init__(self, *, block_engineer: bool = False) -> None:
        self.requests: list[AgentInvocation] = []
        self.block_engineer = block_engineer
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def invoke(
        self, request: AgentInvocation, services: RuntimeInvocationServices
    ) -> AgentInvocationResult:
        self.requests.append(request.model_copy(deep=True))
        if self.block_engineer and request.role == AgentRole.ENGINEER:
            assert services.accounting is not None
            services.accounting.record_simulated_step()
            self.entered.set()
            await self.release.wait()
        return await super().invoke(request, services)


def _record(container: ApplicationContainer, *, block: bool = False) -> RecordingRuntime:
    runtime = RecordingRuntime(block_engineer=block)
    container.workflow.runtimes = RuntimeRegistry({"fake": runtime})
    return runtime


def _id(view: dict[str, JsonValue], key: str = "conversation_id") -> str:
    value = view[key]
    assert isinstance(value, str)
    return value


def _select(container: ApplicationContainer, path: Path, existing: str | None = None) -> str:
    return _id(container.conversations.select(path, conversation_id=existing))


def _turn(container: ApplicationContainer, run_id: str) -> ConversationTurn:
    binding = container.conversation_store.binding_for_run(run_id)
    assert binding is not None
    return container.conversation_store.get_turn(binding.project_id, binding.turn_id)


async def _submit(
    container: ApplicationContainer,
    conversation_id: str,
    key: str,
    *,
    message: str = "Fix the canary behavior",
    scenario: FakeScenario = FakeScenario.DIRECT,
) -> dict[str, JsonValue]:
    return await container.conversations.submit(
        conversation_id,
        message=message,
        submission_id=key,
        options=ChatExecutionOptions(fake_scenario=scenario),
    )


def _clean(container: ApplicationContainer, run_id: str) -> None:
    assert not container.state.outstanding_leases(run_id)
    assert all(
        not container.state.outstanding_leases(item.child_run_id)
        for item in container.graphs.descendants(run_id)
    )


async def test_duplicate_old_submission_returns_its_original_run_without_replaying_budget(
    harness: FleetHarness,
) -> None:
    container = harness.container
    runtime = _record(container)
    conversation_id = _select(container, harness.repository_root)
    first = await _submit(container, conversation_id, "original", message="Explain division.")
    first_id = _id(first, "run_id")
    before = container.budgets.snapshot(first_id)
    original_turn = _turn(container, first_id)
    second = await _submit(container, conversation_id, "later", message="Explain validation.")
    assert _id(second, "run_id") != first_id
    calls = len(runtime.requests)
    reopened = build_container(harness.state_root)
    replacement = _record(reopened)
    _select(reopened, harness.repository_root, conversation_id)
    retried = await _submit(reopened, conversation_id, "original", message="Explain division.")
    assert _id(retried, "run_id") == first_id
    assert _turn(reopened, first_id) == original_turn
    assert reopened.budgets.snapshot(first_id) == before
    assert not replacement.requests and len(runtime.requests) == calls
    assert (
        len(
            reopened.conversation_store.list_turns(
                original_turn.binding.project_id, conversation_id
            )
        )
        == 2
    )
    with pytest.raises(FleetError):
        await _submit(reopened, conversation_id, "original", message="A different goal.")
    assert not replacement.requests


async def test_shared_resume_cancel_and_new_submission_cannot_steal_active_chat_owner(
    harness: FleetHarness,
) -> None:
    container = harness.container
    runtime = _record(container, block=True)
    conversation_id = _select(container, harness.repository_root)
    execution = asyncio.create_task(
        _submit(container, conversation_id, "active", scenario=FakeScenario.SUCCESS)
    )
    try:
        await asyncio.wait_for(runtime.entered.wait(), 10)
        run_id = runtime.requests[-1].run_id
        turn = _turn(container, run_id)
        assert turn.active_claim_id is not None
        leases = container.state.outstanding_leases(run_id)
        assert leases
        before = container.budgets.snapshot(run_id)
        reopened = build_container(harness.state_root)
        other_runtime = _record(reopened)
        _select(reopened, harness.repository_root, conversation_id)
        for operation in (
            reopened.workflow.resume(run_id),
            reopened.cancellation.cancel(run_id),
            _submit(reopened, conversation_id, "not-the-active-key"),
        ):
            with pytest.raises(FleetError) as caught:
                await operation
            assert caught.value.code is ErrorCode.RECOVERY_REQUIRED
        duplicate = await _submit(
            reopened, conversation_id, "active", scenario=FakeScenario.SUCCESS
        )
        assert _id(duplicate, "run_id") == run_id
        assert _turn(reopened, run_id) == turn
        assert reopened.state.outstanding_leases(run_id) == leases
        assert reopened.budgets.snapshot(run_id).agent_invocations == before.agent_invocations
        assert not other_runtime.requests
        assert reopened.state.count_executed_intents(run_id, "workspace.write_file") == 0
        assert reopened.state.get_run(run_id).status is RunStatus.RUNNING
    finally:
        await container.conversations.cancel(conversation_id)
        with suppress(asyncio.CancelledError):
            await execution
    _clean(container, run_id)


async def test_approved_resume_has_one_owner_before_rehydration_or_grant_consumption(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    container = harness.container
    conversation_id = _select(container, harness.repository_root)
    paused = await _submit(container, conversation_id, "approval", scenario=FakeScenario.APPROVAL)
    run_id = _id(paused, "run_id")
    run = container.state.get_run(run_id)
    assert run.pending_approval_id is not None
    grant = container.approvals.approve(run.pending_approval_id, choice=ApprovalChoice.ALLOW_ONCE)
    resuming = build_container(harness.state_root)
    entered, release = asyncio.Event(), asyncio.Event()
    original = resuming.workflow.resources.rehydrate_paused_sandboxes

    async def delayed_rehydrate(current: Run) -> None:
        entered.set()
        await release.wait()
        await original(current)

    monkeypatch.setattr(
        resuming.workflow.resources, "rehydrate_paused_sandboxes", delayed_rehydrate
    )
    execution = asyncio.create_task(resuming.workflow.resume(run_id))
    try:
        await asyncio.wait_for(entered.wait(), 10)
        active = _turn(resuming, run_id)
        assert active.active_claim_id is not None
        reopened = build_container(harness.state_root)
        with pytest.raises(FleetError) as caught:
            await reopened.workflow.resume(run_id)
        assert caught.value.code is ErrorCode.RECOVERY_REQUIRED
        assert _turn(reopened, run_id) == active
        assert reopened.state.get_grant(grant.grant_id).remaining_uses == 1
        assert reopened.state.count_executed_intents(run_id, "fixture.record_side_effect") == 0
    finally:
        release.set()
        result = await execution
    assert result.status is RunStatus.READY_FOR_REVIEW
    assert container.state.count_executed_intents(run_id, "fixture.record_side_effect") == 1
    assert container.state.get_grant(grant.grant_id).remaining_uses == 0
    assert _turn(container, run_id).active_claim_id is None
    _clean(container, run_id)


async def test_uncertain_paused_persistence_retains_claim_until_explicit_recovery(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    container = harness.container
    conversation_id = _select(container, harness.repository_root)
    paused = await _submit(container, conversation_id, "uncertain", scenario=FakeScenario.APPROVAL)
    run_id = _id(paused, "run_id")
    run = container.state.get_run(run_id)
    assert run.pending_approval_id is not None
    grant = container.approvals.approve(run.pending_approval_id, choice=ApprovalChoice.ALLOW_ONCE)
    resuming = build_container(harness.state_root)
    original = resuming.state.save_run

    def fail_resume(current: Run, event_type: str, payload: dict[str, object]) -> Run:
        if current.run_id == run_id and event_type == "run.resumed":
            raise FleetError(ErrorCode.STATE_UNAVAILABLE, "Uncertain resume write.", "Recover.")
        return original(current, event_type, payload)

    monkeypatch.setattr(resuming.state, "save_run", fail_resume)
    with pytest.raises(FleetError) as caught:
        await resuming.workflow.resume(run_id)
    assert caught.value.code is ErrorCode.STATE_UNAVAILABLE
    assert _turn(resuming, run_id).active_claim_id is not None
    reopened = build_container(harness.state_root)
    with pytest.raises(FleetError):
        await reopened.workflow.resume(run_id)
    assert reopened.state.get_grant(grant.grant_id).remaining_uses == 1
    assert reopened.state.count_executed_intents(run_id, "fixture.record_side_effect") == 0
    recovered = await reopened.recovery.recover_run(run_id)
    assert recovered.status is RunStatus.FAILED
    assert _turn(reopened, run_id).active_claim_id is None
    assert _turn(reopened, run_id).settled_at is not None
    _clean(reopened, run_id)


class StoppedProcess(BaseException):
    """An ended owner, not an ordinary adapter error or an automatically retried call."""


async def test_stopped_owner_between_registration_and_budget_cannot_replay_created_run(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    container = harness.container
    conversation_id = _select(container, harness.repository_root)
    observed: list[str] = []

    def stopped(run_id: str, limits: RunBudgetLimits) -> None:
        del limits
        observed.append(run_id)
        raise StoppedProcess()

    monkeypatch.setattr(container.budgets, "initialize_run", stopped)
    with pytest.raises(StoppedProcess):
        await _submit(container, conversation_id, "before-budget")
    assert len(observed) == 1
    run_id = observed[0]
    assert container.state.get_run(run_id).status is RunStatus.CREATED
    assert _turn(container, run_id).active_claim_id is not None
    reopened = build_container(harness.state_root)
    runtime = _record(reopened)
    _select(reopened, harness.repository_root, conversation_id)
    duplicate = await _submit(reopened, conversation_id, "before-budget")
    assert _id(duplicate, "run_id") == run_id and not runtime.requests
    with pytest.raises(FleetError):
        await reopened.workflow.resume(run_id)
    recovered = await reopened.recovery.recover_run(run_id)
    assert recovered.status is RunStatus.FAILED
    assert _turn(reopened, run_id).settled_at is not None
    assert not runtime.requests
    _clean(reopened, run_id)


async def test_context_is_frozen_bounded_history_without_changing_executed_goal(
    harness: FleetHarness,
) -> None:
    container = harness.container
    runtime = _record(container)
    conversation_id = _select(container, harness.repository_root)
    message = "Explain this Unicode input: " + "界" * 1000
    first = await _submit(container, conversation_id, "history-0", message=message)
    assert first["summary_truncated"] is True
    first_run = container.state.get_run(_id(first, "run_id"))
    assert first_run.goal == message
    first_turn = _turn(container, first_run.run_id)
    assert len(first_turn.user_summary.text.encode("utf-8")) <= 2048
    for index in range(1, 10):
        await _submit(container, conversation_id, f"history-{index}", message=f"Explain {index}.")
    last = runtime.requests[-1]
    assert last.role == AgentRole.COS
    context = ConversationContext.model_validate(last.input["conversation_context"])
    assert context.through_sequence == 9 and context.omitted_turn_count >= 1
    assert len(context.entries) <= 8
    assert len(context.model_dump_json().encode("utf-8")) <= 32768
    turn = _turn(container, last.run_id)
    assert turn.context == context and turn.binding.context_sha256 == context.context_sha256
    assert str(harness.root) not in context.model_dump_json()
    before = len(runtime.requests)
    with pytest.raises(FleetError):
        await _submit(container, conversation_id, "too-big", message="界" * 5462)
    assert len(runtime.requests) == before
    reopened = build_container(harness.state_root)
    assert _turn(reopened, last.run_id).context == context


async def test_missing_history_artifact_blocks_new_turn_before_model_or_budget(
    harness: FleetHarness,
) -> None:
    container = harness.container
    conversation_id = _select(container, harness.repository_root)
    view = await _submit(container, conversation_id, "history")
    turn = _turn(container, _id(view, "run_id"))
    assert turn.artifact_refs
    metadata = container.state.get_artifact(turn.artifact_refs[0].artifact_id)
    store = container.artifacts.store
    assert isinstance(store, LocalArtifactStore)
    path = store.root / metadata.content_ref
    missing = path.with_suffix(".missing-conversation-fixture")
    path.rename(missing)
    runtime = _record(container)
    try:
        with pytest.raises(FleetError) as caught:
            await _submit(container, conversation_id, "after-damage")
        assert caught.value.code is ErrorCode.ARTIFACT_INTEGRITY_FAILED
        assert caught.value.__context__ is None
        assert not runtime.requests
        assert (
            container.conversation_store.get_submission(
                turn.binding.project_id, conversation_id, "after-damage"
            )
            is None
        )
    finally:
        missing.rename(path)


@pytest.mark.parametrize("cancel_method", ["service", "caller"])
async def test_cancellation_waits_for_cleanup_before_releasing_turn(
    harness: FleetHarness,
    monkeypatch: pytest.MonkeyPatch,
    cancel_method: Literal["service", "caller"],
) -> None:
    container = harness.container
    runtime = _record(container, block=True)
    conversation_id = _select(container, harness.repository_root)
    execution = asyncio.create_task(
        _submit(container, conversation_id, "cancel", scenario=FakeScenario.SUCCESS)
    )
    await asyncio.wait_for(runtime.entered.wait(), 10)
    run_id = runtime.requests[-1].run_id
    cleaning, release = asyncio.Event(), asyncio.Event()
    original = container.workflow.resources.cleanup_run

    async def delayed_cleanup(run: Run, *, recovered: bool = False) -> None:
        if run.run_id == run_id:
            cleaning.set()
            await release.wait()
        await original(run, recovered=recovered)

    monkeypatch.setattr(container.workflow.resources, "cleanup_run", delayed_cleanup)
    cancellation: asyncio.Task[dict[str, JsonValue]] | None = None
    if cancel_method == "service":
        cancellation = asyncio.create_task(container.conversations.cancel(conversation_id))
    else:
        execution.cancel()
    try:
        await asyncio.wait_for(cleaning.wait(), 10)
        assert container.state.outstanding_leases(run_id)
        assert not execution.done()
        if cancellation is not None:
            cancellation.cancel()
            await asyncio.sleep(0)
            assert not cancellation.done()
        else:
            execution.cancel()
        reopened = build_container(harness.state_root)
        _select(reopened, harness.repository_root, conversation_id)
        with pytest.raises(FleetError):
            await _submit(reopened, conversation_id, "during-cleanup")
    finally:
        release.set()
        with suppress(asyncio.CancelledError):
            await execution
        if cancellation is not None:
            with suppress(asyncio.CancelledError):
                await cancellation
    _clean(container, run_id)
    turn = _turn(container, run_id)
    assert turn.settled_at is not None and turn.active_claim_id is None
    assert container.state.get_run(run_id).status is RunStatus.CANCELLED


@pytest.mark.parametrize("scenario", [FakeScenario.APPROVAL, FakeScenario.SUCCESS])
async def test_foreign_project_approval_and_progress_cursor_never_cross_selected_chat(
    harness: FleetHarness, scenario: FakeScenario
) -> None:
    container = harness.container
    first = _select(container, harness.repository_root)
    repository = GitRepositoryAdapter(harness.root, UuidIdGenerator()).create_canary_fixture(
        harness.root / "unrelated-repository"
    )
    container.projects._initialize_without_canary(
        repository, runtime_name="fake", sandbox_name="fake"
    )
    second = _select(container, repository)
    if scenario is FakeScenario.SUCCESS:
        for root in (harness.repository_root, repository):
            container.permissions.configure(root, mode=TrustMode.SAFE, allowed_paths=(".",))
    one = await _submit(container, first, "first", scenario=scenario)
    two = await _submit(container, second, "second", scenario=scenario)
    first_run = container.state.get_run(_id(one, "run_id"))
    foreign = container.state.get_run(_id(two, "run_id"))
    assert first_run.pending_approval_id is not None and foreign.pending_approval_id is not None
    foreign_leases = container.state.outstanding_leases(foreign.run_id)
    try:
        operations: tuple[Callable[[], object], ...] = (
            lambda: container.conversations.approve(
                first, foreign.pending_approval_id or "", choice=ApprovalChoice.ALLOW_ONCE
            ),
            lambda: container.conversations.deny(first, foreign.pending_approval_id or ""),
            lambda: container.conversations.permissions(
                first, identifier=foreign.pending_approval_id
            ),
            lambda: container.conversations.select(repository, conversation_id=first),
        )
        for operation in operations:
            with pytest.raises(FleetError):
                operation()
        cursor = container.conversations.progress(second)["cursor"]
        assert isinstance(cursor, str)
        with pytest.raises(FleetError):
            container.conversations.progress(first, cursor=cursor)
        assert (
            container.state.get_approval(foreign.pending_approval_id).status
            is ApprovalStatus.PENDING
        )
        assert container.state.outstanding_leases(foreign.run_id) == foreign_leases
        assert (
            container.state.count_executed_intents(foreign.run_id, "fixture.record_side_effect")
            == 0
        )
        await container.conversations.cancel(first)
        assert container.state.get_run(foreign.run_id).status is RunStatus.PAUSED_FOR_APPROVAL
        assert container.state.outstanding_leases(foreign.run_id) == foreign_leases
    finally:
        await container.conversations.cancel(first)
        await container.conversations.cancel(second)
    _clean(container, first_run.run_id)
    _clean(container, foreign.run_id)


async def test_fenced_owner_cannot_settle_or_resume_and_recovery_preserves_budget(
    harness: FleetHarness,
) -> None:
    container = harness.container
    conversation_id = _select(container, harness.repository_root)
    view = await _submit(container, conversation_id, "fence", scenario=FakeScenario.APPROVAL)
    run_id = _id(view, "run_id")
    paused = _turn(container, run_id)
    before = container.budgets.snapshot(run_id)
    claim = container.conversation_store.claim_resume(run_id, expected_revision=paused.revision)
    owned = container.conversation_store.assert_claim(claim)
    fenced = container.conversation_store.fence(
        run_id, expected_revision=owned.revision, reason="recovery"
    )
    assert fenced.active_claim_id is None and fenced.fenced_at is not None
    assert container.state.outstanding_leases(run_id)
    with pytest.raises(FleetError):
        container.conversation_store.assert_claim(claim)
    with pytest.raises(FleetError):
        container.conversation_store.settle(claim, expected_revision=fenced.revision)
    assert _turn(container, run_id) == fenced
    reopened = build_container(harness.state_root)
    with pytest.raises(FleetError):
        await reopened.workflow.resume(run_id)
    recovered = await reopened.recovery.recover_run(run_id)
    assert recovered.status is RunStatus.FAILED
    assert _turn(reopened, run_id).settled_at is not None
    assert reopened.budgets.snapshot(run_id) == before
    assert reopened.state.count_executed_intents(run_id, "fixture.record_side_effect") == 0
    _clean(reopened, run_id)


@pytest.mark.parametrize("corruption", ["missing-binding", "context", "coherent-context"])
async def test_persisted_conversation_corruption_denies_terminal_resume_and_new_model_call(
    harness: FleetHarness, corruption: str
) -> None:
    container = harness.container
    conversation_id = _select(container, harness.repository_root)
    await _submit(container, conversation_id, "first-context")
    view = await _submit(container, conversation_id, "second-context")
    run_id = _id(view, "run_id")
    turn = _turn(container, run_id)
    assert turn.context.entries and container.state.get_run(run_id).status is RunStatus.COMPLETED
    binding_json = turn.binding.model_dump_json()
    data_json = turn.model_dump_json()
    changed = json.loads(data_json)
    changed["context"]["entries"][0]["user_summary"]["text"] = "Unreviewed historical instruction."
    damaged_context = ConversationContext.model_validate(changed["context"])
    if corruption == "coherent-context":
        changed["binding"]["context_sha256"] = damaged_context.context_sha256
    with container.state._connect() as connection:
        if corruption == "missing-binding":
            connection.execute("PRAGMA foreign_keys = OFF")
            connection.execute(
                "UPDATE conversation_turns SET run_id=? WHERE turn_id=?",
                ("run_" + "0" * 32, turn.binding.turn_id),
            )
        else:
            connection.execute(
                "UPDATE conversation_turns SET data_json=?, binding_json=? WHERE turn_id=?",
                (json.dumps(changed), json.dumps(changed["binding"]), turn.binding.turn_id),
            )
    reopened = build_container(harness.state_root)
    runtime = _record(reopened)
    try:
        with pytest.raises(FleetError) as caught:
            await reopened.workflow.resume(run_id)
        assert caught.value.code is ErrorCode.RECOVERY_REQUIRED
        assert caught.value.__context__ is None
        with pytest.raises(FleetError):
            _select(reopened, harness.repository_root, conversation_id)
        assert not runtime.requests
        assert reopened.state.get_run(run_id).status is RunStatus.COMPLETED
    finally:
        with container.state._connect() as connection:
            connection.execute(
                "UPDATE conversation_turns SET run_id=?,data_json=?,binding_json=? WHERE turn_id=?",
                (run_id, data_json, binding_json, turn.binding.turn_id),
            )
    assert _turn(container, run_id) == turn


@pytest.mark.parametrize("message", ["", " \n", "/approve forged", "\ud800", "hello\x00world"])
async def test_malformed_message_fails_typed_before_turn_or_model(
    harness: FleetHarness, message: str
) -> None:
    container = harness.container
    runtime = _record(container)
    conversation_id = _select(container, harness.repository_root)
    before = container.conversations.status(conversation_id)
    with pytest.raises(FleetError) as caught:
        await _submit(container, conversation_id, "bad-message", message=message)
    assert caught.value.__context__ is None
    assert not runtime.requests
    assert container.conversations.status(conversation_id) == before


async def test_registered_user_secret_is_redacted_before_history_goal_and_model(
    harness: FleetHarness,
) -> None:
    container = harness.container
    runtime = _record(container)
    sentinel = "conversation-private-fixture-sentinel-73952"
    container.redactor.register_secret(sentinel)
    conversation_id = _select(container, harness.repository_root)
    view = await _submit(container, conversation_id, "redacted", message=f"Explain {sentinel}.")
    run_id = _id(view, "run_id")
    turn = _turn(container, run_id)
    assert sentinel not in container.state.get_run(run_id).goal
    assert sentinel not in turn.model_dump_json()
    assert sentinel not in json.dumps(view)
    assert all(sentinel not in request.model_dump_json() for request in runtime.requests)
    assert all(
        sentinel.encode() not in path.read_bytes()
        for path in harness.state_root.rglob("*")
        if path.is_file()
    )


async def test_fresh_history_read_registers_only_reviewed_credential_before_parse(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    key_name = "AGENT_FLEET_TEST_CHAT_HISTORY_KEY"
    sentinel = "chat-history-explicit-test-key-274963"
    monkeypatch.setenv(key_name, sentinel)
    repository = GitRepositoryAdapter(harness.root, UuidIdGenerator()).create_canary_fixture(
        harness.root / "history-provider-repository"
    )
    container = harness.container
    container.projects._initialize_without_canary(
        repository,
        runtime_name="pydantic-ai",
        provider_model="openai:gpt-5-mini",
        credential_ref=f"env:{key_name}",
        sandbox_name="fake",
    )
    conversation_id = _select(container, repository)
    with container.state._connect() as connection:
        original = connection.execute(
            "SELECT data_json FROM conversations WHERE conversation_id=?", (conversation_id,)
        ).fetchone()[0]
        connection.execute(
            "UPDATE conversations SET data_json=? WHERE conversation_id=?",
            (json.dumps({"kind": sentinel}), conversation_id),
        )
    reopened = build_container(harness.state_root)
    assert not reopened.redactor.contains_secret(sentinel)
    try:
        with pytest.raises(FleetError) as caught:
            _select(reopened, repository, conversation_id)
        assert reopened.redactor.contains_secret(sentinel)
        assert caught.value.__context__ is None and caught.value.__cause__ is None
        assert sentinel not in str(caught.value)
        assert sentinel not in str(caught.value.details)
    finally:
        with container.state._connect() as connection:
            connection.execute(
                "UPDATE conversations SET data_json=? WHERE conversation_id=?",
                (original, conversation_id),
            )


async def test_missing_reviewed_credential_allows_readonly_chat_without_ambient_fallback(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    key_name = "AGENT_FLEET_TEST_CHAT_INSPECTION_KEY"
    monkeypatch.setenv(key_name, "chat-history-inspection-test-key-582916")
    repository = GitRepositoryAdapter(harness.root, UuidIdGenerator()).create_canary_fixture(
        harness.root / "inspection-provider-repository"
    )
    harness.container.projects._initialize_without_canary(
        repository,
        runtime_name="pydantic-ai",
        provider_model="openai:gpt-5-mini",
        credential_ref=f"env:{key_name}",
        sandbox_name="fake",
    )
    conversation_id = _select(harness.container, repository)
    monkeypatch.delenv(key_name)
    ambient = "unreviewed-ambient-chat-fixture-key-843576"
    monkeypatch.setenv("OPENAI_API_KEY", ambient)
    reopened = build_container(harness.state_root)
    assert _select(reopened, repository, conversation_id) == conversation_id
    assert reopened.conversations.status(conversation_id)["run_id"] is None
    assert not reopened.redactor.contains_secret(ambient)
    assert reopened.conversations.artifacts(conversation_id)["artifacts"] == []


async def test_malformed_progress_cursor_is_typed_and_does_not_advance_history(
    harness: FleetHarness,
) -> None:
    container = harness.container
    conversation_id = _select(container, harness.repository_root)
    view = await _submit(container, conversation_id, "cursor")
    before = _turn(container, _id(view, "run_id"))
    with pytest.raises(FleetError) as caught:
        container.conversations.progress(conversation_id, cursor="\ud800")
    assert caught.value.__context__ is None
    assert _turn(container, before.binding.run_id) == before


async def test_cancel_remains_bound_to_original_turn_after_new_process_submits(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    container = harness.container
    runtime = _record(container, block=True)
    conversation_id = _select(container, harness.repository_root)
    original_execution = asyncio.create_task(
        _submit(container, conversation_id, "original-cancel", scenario=FakeScenario.SUCCESS)
    )
    await asyncio.wait_for(runtime.entered.wait(), 10)
    original_run_id = runtime.requests[-1].run_id
    stopped, release = asyncio.Event(), asyncio.Event()
    original_wait = conversation_module._await_stopped

    async def delayed_return(execution: asyncio.Task[Run]) -> None:
        await original_wait(execution)
        if asyncio.current_task() is container.conversations._cancellations.get(conversation_id):
            stopped.set()
            await release.wait()

    monkeypatch.setattr(conversation_module, "_await_stopped", delayed_return)
    cancellation = asyncio.create_task(container.conversations.cancel(conversation_id))
    reopened = build_container(harness.state_root)
    next_run_id: str | None = None
    try:
        await asyncio.wait_for(stopped.wait(), 10)
        assert container.state.get_run(original_run_id).status is RunStatus.CANCELLED
        _clean(container, original_run_id)
        assert _turn(container, original_run_id).settled_at is not None
        _select(reopened, harness.repository_root, conversation_id)
        next_view = await _submit(
            reopened, conversation_id, "next-process", scenario=FakeScenario.APPROVAL
        )
        next_run_id = _id(next_view, "run_id")
        before = reopened.state.get_run(next_run_id)
        next_turn = _turn(reopened, next_run_id)
        leases = reopened.state.outstanding_leases(next_run_id)
        assert before.status is RunStatus.PAUSED_FOR_APPROVAL and leases
        release.set()
        await asyncio.wait_for(cancellation, 10)
        assert reopened.state.get_run(next_run_id) == before
        assert _turn(reopened, next_run_id) == next_turn
        assert reopened.state.outstanding_leases(next_run_id) == leases
    finally:
        release.set()
        with suppress(asyncio.CancelledError, FleetError):
            await original_execution
        with suppress(asyncio.CancelledError, FleetError):
            await cancellation
        if next_run_id is not None:
            await reopened.conversations.cancel(conversation_id)
            _clean(reopened, next_run_id)


@pytest.mark.parametrize("published", [False, True])
async def test_uncertain_terminal_settlement_never_replays_completed_model_work(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch, published: bool
) -> None:
    container = harness.container
    runtime = _record(container)
    conversation_id = _select(container, harness.repository_root)
    original_settle = container.conversation_store.settle

    def interrupted_settle(
        claim: ConversationClaim,
        *,
        expected_revision: int,
        summary: ConversationSummary | None = None,
        artifact_refs: tuple[ConversationArtifactRef, ...] = (),
    ) -> ConversationTurn:
        if published:
            original_settle(
                claim,
                expected_revision=expected_revision,
                summary=summary,
                artifact_refs=artifact_refs,
            )
        raise FleetError(
            ErrorCode.STATE_UNAVAILABLE,
            "Injected uncertain terminal settlement.",
            "Inspect the exact recorded turn before retrying.",
        )

    monkeypatch.setattr(container.conversation_store, "settle", interrupted_settle)
    with pytest.raises(FleetError) as caught:
        await _submit(container, conversation_id, "uncertain-terminal")
    assert caught.value.code is ErrorCode.STATE_UNAVAILABLE
    assert len(runtime.requests) == 1
    run_id = runtime.requests[0].run_id
    assert container.state.get_run(run_id).status is RunStatus.COMPLETED
    _clean(container, run_id)
    budget = container.budgets.snapshot(run_id)
    turn = _turn(container, run_id)
    assert bool(turn.settled_at) is published
    assert bool(turn.active_claim_id) is not published
    reopened = build_container(harness.state_root)
    other_runtime = _record(reopened)
    _select(reopened, harness.repository_root, conversation_id)
    duplicate = await _submit(reopened, conversation_id, "uncertain-terminal")
    assert _id(duplicate, "run_id") == run_id
    assert _turn(reopened, run_id) == turn
    if published:
        assert (await reopened.workflow.resume(run_id)).status is RunStatus.COMPLETED
    else:
        with pytest.raises(FleetError) as resume_error:
            await reopened.workflow.resume(run_id)
        assert resume_error.value.code is ErrorCode.RECOVERY_REQUIRED
        recovered = await reopened.recovery.recover_run(run_id)
        assert recovered.status is RunStatus.COMPLETED
        final = _turn(reopened, run_id)
        assert final.settled_at is not None and final.active_claim_id is None
    assert reopened.budgets.snapshot(run_id) == budget
    assert not other_runtime.requests
    _clean(reopened, run_id)


async def test_cancel_after_rejected_cleanup_reconciles_terminal_fence(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    container = harness.container
    conversation_id = _select(container, harness.repository_root)
    cleaned, release = asyncio.Event(), asyncio.Event()
    original_cleanup = container.workflow.resources.cleanup_run
    terminal_run_id: str | None = None

    async def delayed_terminal_cleanup(run: Run, *, recovered: bool = False) -> None:
        nonlocal terminal_run_id
        await original_cleanup(run, recovered=recovered)
        if run.status is RunStatus.REJECTED:
            terminal_run_id = run.run_id
            cleaned.set()
            await release.wait()

    monkeypatch.setattr(container.workflow.resources, "cleanup_run", delayed_terminal_cleanup)
    execution = asyncio.create_task(
        _submit(container, conversation_id, "terminal-cancel", scenario=FakeScenario.FAIL)
    )
    try:
        await asyncio.wait_for(cleaned.wait(), 15)
        assert terminal_run_id is not None
        _clean(container, terminal_run_id)
        assert container.state.get_run(terminal_run_id).status is RunStatus.REJECTED
        execution.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(execution, 10)
        turn = _turn(container, terminal_run_id)
        assert turn.active_claim_id is None
        assert turn.settled_at is not None
        assert container.conversations.status(conversation_id)["recovery_required"] is False
    finally:
        release.set()
        with suppress(asyncio.CancelledError, FleetError):
            await execution
        if terminal_run_id is not None:
            await container.recovery.recover_run(terminal_run_id)
            _clean(container, terminal_run_id)


async def test_empty_cancel_does_not_capture_turn_created_after_scheduling(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    container = harness.container
    conversation_id = _select(container, harness.repository_root)
    scheduled, release = asyncio.Event(), asyncio.Event()
    original_cancel = container.conversations._cancel

    async def delayed_start(run_id: str | None, execution: asyncio.Task[Run] | None) -> None:
        assert run_id is None and execution is None
        scheduled.set()
        await release.wait()
        await original_cancel(run_id, execution)

    monkeypatch.setattr(container.conversations, "_cancel", delayed_start)
    cancellation = asyncio.create_task(container.conversations.cancel(conversation_id))
    reopened = build_container(harness.state_root)
    next_run_id: str | None = None
    try:
        await asyncio.wait_for(scheduled.wait(), 10)
        _select(reopened, harness.repository_root, conversation_id)
        next_view = await _submit(
            reopened, conversation_id, "after-empty-cancel", scenario=FakeScenario.APPROVAL
        )
        next_run_id = _id(next_view, "run_id")
        turn = _turn(reopened, next_run_id)
        leases = reopened.state.outstanding_leases(next_run_id)
        release.set()
        await asyncio.wait_for(cancellation, 10)
        assert _turn(reopened, next_run_id) == turn
        assert reopened.state.get_run(next_run_id).status is RunStatus.PAUSED_FOR_APPROVAL
        assert reopened.state.outstanding_leases(next_run_id) == leases
    finally:
        release.set()
        await cancellation
        if next_run_id is not None:
            await reopened.conversations.cancel(conversation_id)
            _clean(reopened, next_run_id)
