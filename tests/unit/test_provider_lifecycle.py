import asyncio

import pytest

from agent_fleet.adapters.runtime.provider_lifecycle import close_provider_clients
from agent_fleet.domain.errors import FleetError


async def test_repeated_cancellation_waits_for_physical_cleanup() -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    completed: list[str] = []

    async def first() -> None:
        started.set()
        await release.wait()
        completed.append("sdk")

    async def second() -> None:
        completed.append("http")

    task = asyncio.create_task(close_provider_clients(first, second))
    try:
        await started.wait()
        for _ in range(3):
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
        assert not completed
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert completed == ["sdk", "http"]


@pytest.mark.parametrize("self_cancel", [False, True])
async def test_failed_cleanup_attempts_other_owner_and_has_no_raw_chain(self_cancel: bool) -> None:
    completed: list[str] = []

    async def first() -> None:
        if self_cancel:
            raise asyncio.CancelledError("raw-cleanup-secret")
        error = RuntimeError("raw-cleanup-secret")
        error.add_note("raw-cleanup-note")
        raise error

    async def second() -> None:
        completed.append("http")

    with pytest.raises(FleetError) as caught:
        await close_provider_clients(first, second)
    assert completed == ["http"]
    assert caught.value.__cause__ is caught.value.__context__ is None
    assert not getattr(caught.value, "__notes__", [])
    assert "raw-cleanup" not in str(caught.value)
    assert caught.value.details["runtime_diagnostic"]["cause_category"] == "client_cleanup"


async def test_normal_cleanup_completes_exactly_once_in_order() -> None:
    completed: list[str] = []

    async def first() -> None:
        completed.append("sdk")

    async def second() -> None:
        completed.append("http")

    await close_provider_clients(first, second)
    assert completed == ["sdk", "http"]
