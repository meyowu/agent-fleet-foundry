"""Await real provider-client closure even under repeated caller cancellation."""

import asyncio
from collections.abc import Awaitable, Callable

from agent_fleet.domain.errors import ErrorCode, FleetError


async def close_provider_clients(*closers: Callable[[], Awaitable[None]]) -> None:
    """Retain one close task; never abandon a partially closed HTTP transport.

    SDK clients may mark themselves closed before their transport has finished.
    A second close is then a no-op, so the original close must not be cancelled.
    Cleanup failures remain failures, not proof that resources were released.
    """
    cleanup = asyncio.create_task(_close_all(closers))
    cancelled = False
    while not cleanup.done():
        try:
            # Unlike awaiting the task directly, cancellation of this waiter does
            # not propagate into the task. Keep a strong reference until result().
            await asyncio.wait({cleanup})
        except asyncio.CancelledError:
            cancelled = True
    cleanup.result()
    if cancelled:
        raise asyncio.CancelledError


async def _close_all(closers: tuple[Callable[[], Awaitable[None]], ...]) -> None:
    failed = False
    for close in closers:
        try:
            await close()
        except (Exception, asyncio.CancelledError):
            # Still attempt the separately owned transport after an SDK failure.
            # Never retain or stringify an SDK exception, even for cleanup.
            failed = True
    if failed:
        raise FleetError(
            ErrorCode.PROVIDER_FAILED,
            "The provider client did not finish cleanup successfully.",
            "Do not replay the uncertain request; inspect retained usage and stop this process.",
            details={
                "runtime_diagnostic": {
                    "category": "provider_sdk",
                    "cause_category": "client_cleanup",
                }
            },
        )
