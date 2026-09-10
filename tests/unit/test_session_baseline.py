"""Exact metadata/one-use ticket controls; no Docker or model runtime."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest
from business_baseline_fixtures import BaselineFixture, baseline_fixture
from pydantic import JsonValue

from agent_fleet.adapters.persistence.conversations import SqliteConversationStore
from agent_fleet.application.session_review import SessionReviewService
from agent_fleet.domain.baseline import BaselineAuthorization
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.session_review import BaselineSessionBinding, BaselineSessionReview
from agent_fleet.ports.baseline import BaselineSessionAdmission

if TYPE_CHECKING:
    from test_chat_cli import QueuedInput, StrictService
else:
    from unit.test_chat_cli import QueuedInput, StrictService


def authorizations(fixture: BaselineFixture) -> tuple[BaselineAuthorization, ...]:
    with fixture.store._transaction(write=False) as connection:
        rows = fixture.store._rows(
            connection, "baseline_authorizations", "baseline_id", fixture.review.baseline_id
        )
        return tuple(fixture.store._decode(row, BaselineAuthorization) for row in rows)


def bound(fixture: BaselineFixture) -> tuple[SqliteConversationStore, BaselineSessionBinding]:
    state = fixture.state
    store = SqliteConversationStore(
        state.database_path, state.clock, state.ids, state.redactor, state
    )
    conversation = store.create(fixture.project.project_id, fixture.project.identity_hash)
    return store, BaselineSessionBinding(
        project_id=conversation.project_id,
        repository_identity=conversation.repository_identity,
        conversation_id=conversation.conversation_id,
        conversation_revision=conversation.revision,
        selection_generation=1,
    )


def test_confirmation_writes_only_authorization_then_exact_claim_once(tmp_path: Path) -> None:
    fixture = baseline_fixture(tmp_path)
    conversations, binding = bound(fixture)
    original = conversations.get(binding.project_id, binding.conversation_id)
    checks: list[str] = []
    session = BaselineSessionAdmission(binding, lambda: checks.append("RAM check"))
    authorization = fixture.store.authorize(
        fixture.review.review_id, fixture.review.digest, session=session
    )
    view = fixture.store.show(fixture.review.baseline_id)
    assert view.execution.owner_claim_id is None
    with fixture.store._transaction(write=False) as connection:
        for table in (
            "baseline_owner_claims",
            "baseline_dispatch_claims",
            "baseline_resource_leases",
        ):
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    assert authorization.status == "available"
    claim = fixture.store.claim_baseline(
        fixture.review.review_id,
        fixture.review.digest,
        authorization.authorization_id,
        0,
        session=session,
    )
    assert checks == ["RAM check", "RAM check"]
    assert claim.authorization_id == authorization.authorization_id
    assert conversations.get(binding.project_id, binding.conversation_id) == original
    with pytest.raises(FleetError):
        fixture.store.claim_baseline(
            fixture.review.review_id,
            fixture.review.digest,
            authorization.authorization_id,
            0,
            session=session,
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("conversation_revision", 1),
        ("repository_identity", "0" * 64),
        ("conversation_id", "conv_" + "0" * 32),
        ("project_id", "prj_" + "0" * 32),
    ],
)
@pytest.mark.parametrize("operation", ["authorize", "claim"])
def test_metadata_mismatch_never_grants_or_consumes(
    tmp_path: Path,
    field: str,
    value: object,
    operation: str,
) -> None:
    fixture = baseline_fixture(tmp_path)
    _, binding = bound(fixture)
    values = binding.model_dump()
    values[field] = value
    wrong = BaselineSessionBinding.model_validate(values)
    session = BaselineSessionAdmission(wrong, lambda: None)
    authorization = fixture.store.authorize(fixture.review.review_id, fixture.review.digest)
    with pytest.raises(FleetError):
        if operation == "authorize":
            fixture.store.authorize(
                fixture.review.review_id, fixture.review.digest, session=session
            )
        else:
            fixture.store.claim_baseline(
                fixture.review.review_id,
                fixture.review.digest,
                authorization.authorization_id,
                0,
                session=session,
            )
    view = fixture.store.show(fixture.review.baseline_id)
    assert view.execution.owner_claim_id is None
    assert authorizations(fixture) == (authorization,)


@pytest.mark.parametrize("swallow", [False, True])
def test_pure_callback_reentry_rejects_before_second_connection(
    tmp_path: Path,
    swallow: bool,
) -> None:
    fixture = baseline_fixture(tmp_path)
    _, binding = bound(fixture)

    def reenter() -> None:
        try:
            fixture.store.show(fixture.review.baseline_id)
        except FleetError:
            if not swallow:
                raise

    with pytest.raises(FleetError):
        fixture.store.authorize(
            fixture.review.review_id,
            fixture.review.digest,
            session=BaselineSessionAdmission(binding, reenter),
        )
    view = fixture.store.show(fixture.review.baseline_id)
    assert not authorizations(fixture) and view.execution.owner_claim_id is None


@dataclass
class MutableClock:
    value: datetime

    def now(self) -> datetime:
        return self.value


def reviews(fixture: BaselineFixture, clock: MutableClock) -> SessionReviewService:
    # These dependencies cannot be used by the typed model-free ticket branch.
    from typing import Any

    forbidden = cast(Any, object())
    return SessionReviewService(fixture.state, forbidden, forbidden, forbidden, forbidden, clock)


@pytest.mark.parametrize("invalidate", ["expire", "backwards", "dismiss", "switch", "restart"])
def test_baseline_ticket_original_expiry_nonreuse_and_family(
    tmp_path: Path,
    invalidate: str,
) -> None:
    fixture = baseline_fixture(tmp_path)
    _, binding = bound(fixture)
    clock = MutableClock(fixture.review.created_at + timedelta(minutes=4))
    service = reviews(fixture, clock)
    expected = BaselineSessionReview(
        binding=binding,
        baseline_id=fixture.review.baseline_id,
        review_id=fixture.review.review_id,
        review_sha256=fixture.review.digest,
        expires_at=fixture.review.expires_at,
    )
    ticket = service.prepare_baseline(expected)
    code = cast(str, ticket["confirmation_code"])
    assert ticket["expires_at"] == fixture.review.expires_at.isoformat()
    assert service.confirmation_family(code) == "baseline"
    if invalidate == "expire":
        clock.value = fixture.review.expires_at
    elif invalidate == "backwards":
        clock.value = fixture.review.created_at
    elif invalidate == "dismiss":
        service.dismiss(binding)
    elif invalidate == "switch":
        service.invalidate_selection()
    else:
        service = reviews(fixture, clock)
    called: list[object] = []

    def authorize(*args: object) -> dict[str, JsonValue]:
        called.append(args)
        return {}

    with pytest.raises(FleetError):
        service.confirm_baseline(
            code,
            authorize=authorize,
            validate_selection=lambda _: None,
        )
    assert not called
    assert service.confirmation_family(code) == (
        "unknown" if invalidate == "restart" else "baseline"
    )


def test_ticket_registry_capacity_and_nonce_collision(tmp_path: Path) -> None:
    fixture = baseline_fixture(tmp_path)
    _, binding = bound(fixture)
    service = reviews(fixture, MutableClock(fixture.review.created_at))
    expected = BaselineSessionReview(
        binding=binding,
        baseline_id=fixture.review.baseline_id,
        review_id=fixture.review.review_id,
        review_sha256=fixture.review.digest,
        expires_at=fixture.review.expires_at,
    )
    service.code_factory = lambda: "a" * 16
    service.prepare_baseline(expected)
    service.invalidate_selection()
    with pytest.raises(FleetError):
        service.prepare_baseline(expected)
    assert len(service._issued_codes) == 1


def test_ticket_registry_keeps_exact_32_pending_and_4096_issued_bound(tmp_path: Path) -> None:
    fixture = baseline_fixture(tmp_path)
    _, binding = bound(fixture)
    service = reviews(fixture, MutableClock(fixture.review.created_at))
    for index in range(32):
        expected = BaselineSessionReview(
            binding=binding.model_copy(update={"conversation_id": f"conv_{index:032x}"}),
            baseline_id=fixture.review.baseline_id,
            review_id=fixture.review.review_id,
            review_sha256=fixture.review.digest,
            expires_at=fixture.review.expires_at,
        )
        service.prepare_baseline(expected)
    with pytest.raises(FleetError):
        service.prepare_baseline(
            expected.model_copy(
                update={
                    "binding": binding.model_copy(update={"conversation_id": "conv_" + "f" * 32})
                }
            )
        )
    assert len(service._tickets) == 32
    service.invalidate_selection()
    service._issued_codes = {f"{index:016x}" for index in range(4096)}
    with pytest.raises(FleetError):
        service.prepare_baseline(expected)


@pytest.mark.asyncio
async def test_baseline_cli_escapes_output_and_does_not_poll_or_finish_with_run_status() -> None:
    from agent_fleet.application.conversations import ChatExecutionOptions
    from agent_fleet.cli.chat import View, run_session
    from agent_fleet.domain.security import Redactor

    class Client(StrictService):
        focused = False

        async def baseline_plan(
            self,
            conversation_id: str,
            command_id: str,
            *,
            on_admitted: Callable[[], None] | None = None,
        ) -> View:
            assert command_id == "python-test"
            assert on_admitted is not None
            on_admitted()
            self.focused = True
            return {"kind": "baseline", "notice": "\x1b[31m SECRET baseline-ready"}

        def status(self, conversation_id: str) -> View:
            assert not self.focused, "ordinary completion status is forbidden during baseline focus"
            return super().status(conversation_id)

        def progress(
            self, conversation_id: str, *, cursor: str | None = None, limit: int = 50
        ) -> View:
            assert not self.focused, "ordinary progress is forbidden during baseline focus"
            return super().progress(conversation_id, cursor=cursor, limit=limit)

    service = Client()
    reader = QueuedInput()
    output: list[str] = []
    errors: list[FleetError] = []
    ready = asyncio.Event()

    def emit(value: str) -> None:
        output.append(value)
        if "baseline-ready" in value:
            ready.set()

    task = asyncio.create_task(
        run_session(
            service,
            service.select(Path(".")),
            ChatExecutionOptions(),
            reader,
            emit=emit,
            show_error=errors.append,
            redactor=Redactor(["SECRET"]),
        )
    )
    try:
        reader.send("/baseline plan python-test")
        await asyncio.wait_for(ready.wait(), 5)
        reader.send("/exit")
        result = await asyncio.wait_for(task, 5)
        assert result["kind"] == "baseline"
        text = "\n".join(output)
        assert "\x1b" not in text and "SECRET" not in text and "\\u001b" in text
        assert not errors
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "command,admitted",
    [
        ("/baseline show", False),
        ("/baseline plan python-test", False),
        ("/baseline run", False),
        ("/baseline plan python-test", True),
        ("/baseline run", True),
    ],
)
async def test_rejected_baseline_entry_restores_exact_cancel_and_progress_owner(
    command: str,
    admitted: bool,
) -> None:
    from agent_fleet.application.conversations import ChatExecutionOptions
    from agent_fleet.cli.chat import View, run_session
    from agent_fleet.domain.security import Redactor

    error_seen, cancelled, progress_resumed = asyncio.Event(), asyncio.Event(), asyncio.Event()

    class Client(StrictService):
        baseline_cancelled = 0

        def reject(self, on_admitted: Callable[[], None] | None) -> View:
            if admitted:
                assert on_admitted is not None
                on_admitted()
            raise FleetError(ErrorCode.COMMAND_DENIED, "baseline-entry-denied", "No new authority.")

        async def baseline_plan(
            self,
            conversation_id: str,
            command_id: str,
            *,
            on_admitted: Callable[[], None] | None = None,
        ) -> View:
            return self.reject(on_admitted)

        async def baseline_run(
            self,
            conversation_id: str,
            *,
            on_admitted: Callable[[], None] | None = None,
        ) -> View:
            return self.reject(on_admitted)

        def baseline_show(self, conversation_id: str) -> View:
            return self.reject(None)

        async def baseline_cancel(self, conversation_id: str) -> View:
            self.baseline_cancelled += 1
            cancelled.set()
            return {"kind": "baseline", "conversation_id": conversation_id}

        async def cancel(self, conversation_id: str) -> View:
            result = await super().cancel(conversation_id)
            cancelled.set()
            return result

        def progress(
            self,
            conversation_id: str,
            *,
            cursor: str | None = None,
            limit: int = 50,
        ) -> View:
            if error_seen.is_set():
                progress_resumed.set()
            return super().progress(conversation_id, cursor=cursor, limit=limit)

    service, reader = Client(), QueuedInput()
    service.run_status = "waiting"
    errors: list[FleetError] = []

    def show_error(error: FleetError) -> None:
        errors.append(error)
        error_seen.set()

    task = asyncio.create_task(
        run_session(
            service,
            service.select(Path(".")),
            ChatExecutionOptions(),
            reader,
            emit=lambda _: None,
            show_error=show_error,
            redactor=Redactor(),
        )
    )
    try:
        reader.send(command)
        await asyncio.wait_for(error_seen.wait(), 3)
        if not admitted:
            await asyncio.wait_for(progress_resumed.wait(), 3)
        reader.send("/cancel")
        await asyncio.wait_for(cancelled.wait(), 3)
        reader.send("/exit")
        result = await asyncio.wait_for(task, 3)
        assert len(errors) == 1
        assert service.baseline_cancelled == int(admitted)
        assert service.cancelled == int(not admitted)
        assert (result.get("kind") == "baseline") is admitted
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
