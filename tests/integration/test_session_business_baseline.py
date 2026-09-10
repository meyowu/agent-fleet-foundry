"""Session + real Git/SQLite/Gateway; only Docker's transport is synthetic."""

from __future__ import annotations

import asyncio
import sqlite3
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest
from conftest import FleetHarness
from test_business_baseline_integration import business_fixture

import agent_fleet.bootstrap as bootstrap
from agent_fleet.application.conversations import ChatExecutionOptions, ConversationService
from agent_fleet.bootstrap import BaselineContainer, build_container
from agent_fleet.domain.baseline_resources import BaselineWorkspacePayload
from agent_fleet.domain.errors import FleetError
from agent_fleet.domain.models import FakeScenario, RunStatus

if TYPE_CHECKING:
    from test_baseline_sandbox import BaselineRecordingRunner
    from test_chat_cli import QueuedInput
else:
    from unit.test_chat_cli import QueuedInput

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def session_fixture(
    tmp_path: Path,
) -> tuple[ConversationService, BaselineContainer, Path, str, str, BaselineRecordingRunner]:
    baseline, root, command, runner = business_fixture(tmp_path)
    container = build_container(tmp_path / "state", redactor=baseline.state.redactor)
    service = container.conversations
    selected = service.select(root)
    identifier = cast(str, selected["conversation_id"])
    service._baseline_factory = lambda: baseline.service
    return service, baseline, root, identifier, command, runner


def rows(container: BaselineContainer, *tables: str) -> dict[str, list[tuple[object, ...]]]:
    with sqlite3.connect(container.state.database_path) as connection:
        return {table: connection.execute(f"SELECT * FROM {table}").fetchall() for table in tables}


def no_history(service: ConversationService, monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("baseline operation touched credentials/runtime/history")

    for name in (
        "_conversation",
        "_turn",
        "_view",
        "_require_current",
        "_review_selection",
        "_register_redaction",
        "_register_run_redaction",
        "status",
        "progress",
    ):
        monkeypatch.setattr(service, name, forbidden)
    for name in ("inspect", "resolve"):
        monkeypatch.setattr(service.secrets, name, forbidden)
    for name in ("get_turn", "list_turns", "binding_for_run"):
        monkeypatch.setattr(service.store, name, forbidden)
    for name in ("RuntimeRegistry", "EnvironmentSecretStore"):
        monkeypatch.setattr(bootstrap, name, forbidden)


async def test_session_confirm_only_then_exact_command_without_history_or_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, baseline, root, identifier, command, runner = session_fixture(tmp_path)
    before = rows(baseline, "conversations", "conversation_turns", "runs", "tasks")
    source = baseline.repository.inspect(root)
    no_history(service, monkeypatch)
    planned = await service.baseline_plan(identifier, command)
    focus = service._baseline_focus
    assert focus is not None
    code = cast(str, planned["confirmation_code"])
    confirmed = service.review(identifier, action="confirm", arguments=(code,))
    assert confirmed["authorized_once"] is True
    counts = rows(
        baseline,
        "baseline_authorizations",
        "baseline_owner_claims",
        "baseline_dispatch_claims",
        "baseline_resource_leases",
    )
    assert len(counts["baseline_authorizations"]) == 1
    assert all(not counts[key] for key in counts if key != "baseline_authorizations")
    assert not any(argv[1:3] == ("container", "create") for argv, _ in runner.calls)
    completed = await service.baseline_run(identifier)
    assert service.baseline_show(identifier) == completed
    shown = baseline.service.show(focus.review.baseline_id)
    assert shown.report is not None
    assert shown.report.cleanup_complete and shown.report.status == "observed"
    assert shown.report.completion_assurance == "baseline_observation_only"
    assert rows(baseline, *before) == before
    assert baseline.repository.inspect(root) == source
    assert runner.listed_ids == []
    assert len(rows(baseline, "baseline_owner_claims")["baseline_owner_claims"]) == 1
    assert len(rows(baseline, "baseline_dispatch_claims")["baseline_dispatch_claims"]) == 1
    assert all(
        lease.status == "released"
        for lease in baseline.store.baseline_resource_snapshot(focus.review.baseline_id).leases
    )
    count = len(runner.calls)
    with pytest.raises(FleetError):
        await service.baseline_run(identifier)
    with pytest.raises(FleetError):
        service.review(identifier, action="confirm", arguments=(code,))
    assert len(runner.calls) == count


@pytest.mark.parametrize("mutation", ["dismiss", "switch", "new-review", "restart", "local-aba"])
async def test_invalidated_focus_never_acquires_owner(tmp_path: Path, mutation: str) -> None:
    service, baseline, root, identifier, command, runner = session_fixture(tmp_path)
    planned = await service.baseline_plan(identifier, command)
    code = cast(str, planned["confirmation_code"])
    if mutation == "dismiss":
        service.review(identifier, action="dismiss")
    elif mutation == "switch":
        service.select(root, create_new=True)
        service.select(root, conversation_id=identifier)
    elif mutation == "new-review":
        await service.baseline_plan(identifier, command)
    elif mutation == "local-aba":
        service._selection_generation[identifier] += 2
    else:
        service = build_container(tmp_path / "state").conversations
        service.select(root, conversation_id=identifier)
    with pytest.raises(FleetError):
        service.review(identifier, action="confirm", arguments=(code,))
    with pytest.raises(FleetError):
        await service.baseline_run(identifier)
    assert not rows(baseline, "baseline_owner_claims")["baseline_owner_claims"]
    assert not any(argv[1:3] == ("container", "create") for argv, _ in runner.calls)


@pytest.mark.parametrize("operation", ["confirm", "run"])
@pytest.mark.parametrize("mutation", ["metadata", "local"])
async def test_transaction_admission_detects_last_moment_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    mutation: str,
) -> None:
    service, baseline, _, identifier, command, _ = session_fixture(tmp_path)
    planned = await service.baseline_plan(identifier, command)
    code = cast(str, planned["confirmation_code"])
    if operation == "run":
        service.review(identifier, action="confirm", arguments=(code,))
    original = baseline.store._session_admission

    def drift(connection: sqlite3.Connection, *args: object) -> None:
        assert connection.in_transaction
        if mutation == "metadata":
            # A same-transaction row change cannot be hidden by a prior Session read.
            connection.execute(
                "UPDATE conversations SET revision=revision+1 WHERE conversation_id=?",
                (identifier,),
            )
        else:
            service._selection_generation[identifier] += 1
        original(connection, *args)  # type: ignore[arg-type]

    monkeypatch.setattr(baseline.store, "_session_admission", drift)
    with pytest.raises(FleetError):
        if operation == "confirm":
            service.review(identifier, action="confirm", arguments=(code,))
        else:
            await service.baseline_run(identifier)
    assert not rows(baseline, "baseline_owner_claims")["baseline_owner_claims"]
    authorization_rows = rows(baseline, "baseline_authorizations")["baseline_authorizations"]
    assert len(authorization_rows) == (1 if operation == "run" else 0)


@pytest.mark.parametrize("invalid", ["absent", "wrong", "revoked"])
async def test_run_authorized_never_reissues_authority(tmp_path: Path, invalid: str) -> None:
    service, baseline, _, identifier, command, _ = session_fixture(tmp_path)
    await service.baseline_plan(identifier, command)
    focus = service._baseline_focus
    assert focus is not None
    authorization = baseline.service.authorize(
        focus.review.review_id, review_sha256=focus.review.review_sha256
    )
    if invalid == "revoked":
        baseline.service.revoke(focus.review.review_id)
    before = rows(baseline, "baseline_authorizations")
    with pytest.raises(FleetError):
        await baseline.service.run_authorized(
            focus.review.review_id,
            review_sha256=focus.review.review_sha256,
            authorization_id=(
                ""
                if invalid == "absent"
                else "bauth_" + "0" * 32
                if invalid == "wrong"
                else authorization.authorization_id
            ),
        )
    assert rows(baseline, *before) == before
    assert not rows(baseline, "baseline_owner_claims")["baseline_owner_claims"]


async def test_repeated_baseline_cancel_drains_only_captured_task(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, baseline, _, identifier, command, runner = session_fixture(tmp_path)
    planned = await service.baseline_plan(identifier, command)
    service.review(
        identifier, action="confirm", arguments=(cast(str, planned["confirmation_code"]),)
    )
    focus = service._baseline_focus
    assert focus is not None
    no_history(service, monkeypatch)
    runner.block_start = runner.block_rm = True
    task = asyncio.create_task(service.baseline_run(identifier))
    try:
        await asyncio.wait_for(runner.start_entered.wait(), 60)
        first = asyncio.create_task(service.baseline_cancel(identifier))
        await asyncio.wait_for(runner.rm_entered.wait(), 15)
        second = asyncio.create_task(service.baseline_cancel(identifier))
        first.cancel()
        first.cancel()
        with pytest.raises(FleetError):
            await service.baseline_plan(identifier, command)
        runner.rm_release.set()
        with pytest.raises(asyncio.CancelledError):
            await first
        result = await second
        assert result["cancelled_baseline_id"] == focus.review.baseline_id
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not service._baseline_tasks and not service._baseline_cancellations
        assert runner.listed_ids == []
        assert baseline.service.show(focus.review.baseline_id).report is not None
    finally:
        runner.start_release.set()
        runner.rm_release.set()
        if not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError, FleetError):
                await task


async def test_slash_text_never_becomes_model_goal(tmp_path: Path) -> None:
    service, baseline, _, identifier, _, _ = session_fixture(tmp_path)
    with pytest.raises(FleetError):
        await service.submit(
            identifier, message="/baseline run", submission_id=None, options=ChatExecutionOptions()
        )
    assert not rows(baseline, "runs")["runs"]


async def test_repeated_dismiss_and_spent_ticket_never_fall_through_to_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _, _, identifier, command, _ = session_fixture(tmp_path)
    no_history(service, monkeypatch)
    planned = await service.baseline_plan(identifier, command)
    assert service.review(identifier, action="dismiss")["dismissed"] is True
    assert service.review(identifier, action="dismiss")["dismissed"] is False
    with pytest.raises(FleetError):
        service.review(
            identifier, action="confirm", arguments=(cast(str, planned["confirmation_code"]),)
        )
    with pytest.raises(FleetError):
        service.review(identifier, action="confirm", arguments=("0" * 16,))


@pytest.mark.parametrize("fault", ["unknown-create", "cleanup-failure"])
async def test_uncertain_baseline_retains_resources_and_never_replays(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    service, baseline, _, identifier, command, runner = session_fixture(tmp_path)
    planned = await service.baseline_plan(identifier, command)
    service.review(
        identifier, action="confirm", arguments=(cast(str, planned["confirmation_code"]),)
    )
    focus = service._baseline_focus
    assert focus is not None
    if fault == "unknown-create":

        def unknown(*args: object, **kwargs: object) -> None:
            raise RuntimeError("synthetic native receipt lost")

        monkeypatch.setattr(baseline.store, "activate_baseline_execution", unknown)
    else:
        runner.rm_returncode = 1
    await service.baseline_run(identifier)
    shown = baseline.service.show(focus.review.baseline_id)
    assert shown.report is not None and shown.report.status == "recovery_required"
    assert not shown.report.cleanup_complete
    snapshot = baseline.store.baseline_resource_snapshot(focus.review.baseline_id)
    assert any(item.status == "failed" for item in snapshot.leases)
    assert any(item.status == "active" for item in snapshot.leases)
    retained = [
        Path(item.payload.workspace.path)
        for item in snapshot.leases
        if isinstance(item.payload, BaselineWorkspacePayload) and item.status == "active"
    ]
    assert retained and all(path.is_dir() for path in retained)
    before = len(runner.calls)
    with pytest.raises(FleetError):
        await service.baseline_run(identifier)
    assert len(runner.calls) == before
    assert len(rows(baseline, "baseline_owner_claims")["baseline_owner_claims"]) == 1
    assert len(rows(baseline, "baseline_dispatch_claims")["baseline_dispatch_claims"]) == 1
    # These test-owned Git workspaces deliberately remain for recovery inspection.


@pytest.mark.parametrize(
    "command", ["/baseline show", "/baseline plan python-test", "/baseline run"]
)
async def test_rejected_baseline_does_not_steal_cancellation_from_actual_waiting_run(
    harness: FleetHarness,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
) -> None:
    from agent_fleet.cli.chat import run_session

    service = harness.container.conversations
    selected = service.select(harness.repository_root)
    identifier = cast(str, selected["conversation_id"])
    waiting = await service.submit(
        identifier,
        message="Wait for the exact permission decision",
        submission_id="baseline-rejection-routing",
        options=ChatExecutionOptions(fake_scenario=FakeScenario.APPROVAL),
    )
    run_id = cast(str, waiting["run_id"])
    assert harness.container.state.get_run(run_id).status is RunStatus.PAUSED_FOR_APPROVAL
    assert not service._executions

    async def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("A rejected baseline must not receive ordinary Run cancellation")

    monkeypatch.setattr(service, "baseline_cancel", forbidden)
    reader = QueuedInput()
    rejected, cancelled = asyncio.Event(), asyncio.Event()
    errors: list[FleetError] = []

    def error(value: FleetError) -> None:
        errors.append(value)
        rejected.set()

    def emit(value: str) -> None:
        if "cancelled" in value:
            cancelled.set()

    task = asyncio.create_task(
        run_session(
            service,
            waiting,
            ChatExecutionOptions(),
            reader,
            emit=emit,
            show_error=error,
            redactor=service.redactor,
        )
    )
    try:
        reader.send(command)
        await asyncio.wait_for(rejected.wait(), 5)
        reader.send("/cancel")
        await asyncio.wait_for(cancelled.wait(), 15)
        reader.send("/exit")
        final = await asyncio.wait_for(task, 5)
        assert len(errors) == 1 and final.get("kind") != "baseline"
        assert harness.container.state.get_run(run_id).status is RunStatus.CANCELLED
        assert not harness.container.state.outstanding_leases(run_id)
        with sqlite3.connect(harness.container.state.database_path) as connection:
            for table in ("baseline_reviews", "baseline_owner_claims", "baseline_dispatch_claims"):
                assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
