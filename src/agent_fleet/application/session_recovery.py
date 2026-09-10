"""One-use stopped-owner review for the current Session, never model replay."""

from __future__ import annotations

import asyncio
import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from threading import Lock

from pydantic import JsonValue

from agent_fleet.application.resources import RecoveryService
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import LeaseStatus, Run, jsonable
from agent_fleet.domain.recovery_binding import RecoveryBinding
from agent_fleet.domain.session_review import SessionSelection
from agent_fleet.ports.clock import Clock
from agent_fleet.ports.conversation import ConversationStore


def recovery_review_error() -> FleetError:
    return FleetError(
        ErrorCode.RECOVERY_REQUIRED,
        "The stopped-owner recovery review is absent, stale or not applicable.",
        "Use /tasks current and /recover. Confirm the previous Fleet process stopped, "
        "then use /recover --confirm-owner-stopped with the new recovery code. "
        "Recovery cleans the old run; it does not replay the model.",
    )


@dataclass(frozen=True)
class _RecoveryTicket:
    selection: SessionSelection
    snapshot_sha256: str
    expires_at: datetime
    binding: RecoveryBinding


class SessionRecoveryService:
    def __init__(
        self,
        recovery: RecoveryService,
        conversations: ConversationStore,
        clock: Clock,
        *,
        code_factory: Callable[[], str] = lambda: secrets.token_hex(8),
    ) -> None:
        self.recovery = recovery
        self.conversations = conversations
        self.clock = clock
        self.code_factory = code_factory
        self._tickets: dict[str, _RecoveryTicket] = {}
        self._issued: set[str] = set()
        self._active: dict[str, asyncio.Task[Run]] = {}
        self._lock = Lock()

    def active(self, conversation_id: str) -> bool:
        return conversation_id in self._active

    def _snapshot(
        self, selection: SessionSelection
    ) -> tuple[Run, RecoveryBinding, dict[str, JsonValue]]:
        binding = self.conversations.capture_recovery(selection)
        snapshot = binding.snapshot()
        run = snapshot.runs[0]
        leases = [
            lease
            for lease in snapshot.leases
            if lease.status not in {LeaseStatus.RELEASED, LeaseStatus.RECOVERED}
        ]
        view: dict[str, JsonValue] = {
            "run_id": run.run_id,
            "status": run.status.value,
            "child_run_ids": [child.run_id for child in snapshot.runs[1:]],
            "outstanding_lease_ids": [lease.lease_id for lease in leases],
            "execution_authorized": False,
            "notice": "Confirm the prior owner has stopped before recovery. This only fences "
            "and cleans the old run; no model/tool continuation is authorized.",
        }
        return run, binding, view

    def prepare(self, selection: SessionSelection) -> dict[str, JsonValue]:
        if self.active(selection.conversation_id):
            raise recovery_review_error()
        _, binding, view = self._snapshot(selection)
        now = self.clock.now()
        with self._lock:
            self._tickets = {
                code: ticket
                for code, ticket in self._tickets.items()
                if ticket.expires_at > now
                and ticket.selection.conversation_id != selection.conversation_id
            }
            if len(self._tickets) >= 32 or len(self._issued) >= 4096:
                raise recovery_review_error()
            code = self.code_factory()
            if not re.fullmatch(r"[0-9a-f]{16}", code) or code in self._issued:
                raise recovery_review_error()
            expires = now + timedelta(minutes=5)
            self._tickets[code] = _RecoveryTicket(selection, binding.sha256, expires, binding)
            self._issued.add(code)
        return view | {"recovery_code": code, "expires_at": expires.isoformat()}

    async def confirm(
        self,
        selection: SessionSelection,
        code: str,
        *,
        owner_stopped: bool,
        current_selection: Callable[[], SessionSelection],
        locally_busy: Callable[[], bool],
    ) -> dict[str, JsonValue]:
        if type(code) is not str or not re.fullmatch(r"[0-9a-f]{16}", code):
            raise recovery_review_error()
        with self._lock:
            ticket = self._tickets.pop(code, None)
        if (
            owner_stopped is not True
            or ticket is None
            or ticket.selection != selection
            or ticket.expires_at <= self.clock.now()
            or self.active(selection.conversation_id)
            or locally_busy()
        ):
            raise recovery_review_error()

        async def recover_exact() -> Run:
            if current_selection() != ticket.selection or locally_busy():
                raise recovery_review_error()
            run, binding, _ = self._snapshot(selection)
            if binding.sha256 != ticket.snapshot_sha256:
                raise recovery_review_error()
            # This is an early diagnostic only. The *original* immutable review
            # is compared again with fencing in one durable transaction.
            return await self.recovery.recover_run(run.run_id, reviewed_binding=ticket.binding)

        task = asyncio.create_task(recover_exact())
        self._active[selection.conversation_id] = task
        cancellation: asyncio.CancelledError | None = None
        try:
            while not task.done():
                try:
                    await asyncio.wait({task})
                except asyncio.CancelledError as error:
                    cancellation = cancellation or error
            run = task.result()
        finally:
            if task.done() and self._active.get(selection.conversation_id) is task:
                self._active.pop(selection.conversation_id, None)
        if cancellation is not None:
            raise cancellation
        remaining = [
            lease.lease_id
            for identifier in self.recovery.owned_run_ids(run.run_id)
            for lease in self.recovery.state.outstanding_leases(identifier)
        ]
        return {
            "recovered_run_id": run.run_id,
            "status": run.status.value,
            "outstanding_lease_ids": jsonable(remaining),
            "replayed": False,
        }
