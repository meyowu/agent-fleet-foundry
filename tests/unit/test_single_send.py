"""Mutable context-local tickets do not become reusable physical-send authority."""

import asyncio
from contextvars import copy_context

import pytest
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.function import FunctionModel

from agent_fleet.adapters.runtime.single_send import SingleSendGate, SingleSendModel
from agent_fleet.domain.errors import FleetError


def test_gate_requires_active_scope_and_rejects_reuse() -> None:
    gate = SingleSendGate()
    with pytest.raises(FleetError):
        gate.consume()
    for _ in range(2):
        with gate.request():
            gate.consume()
            with pytest.raises(FleetError):
                gate.consume()
        with pytest.raises(FleetError):
            gate.consume()


def test_copied_context_shares_consumption_and_expires() -> None:
    gate = SingleSendGate()
    with gate.request():
        copied = copy_context()
        copied.run(gate.consume)
        with pytest.raises(FleetError):
            gate.consume()
    with pytest.raises(FleetError):
        copied.run(gate.consume)


def test_nested_scope_cannot_mint_another_ticket() -> None:
    gate = SingleSendGate()
    with gate.request():
        with pytest.raises(FleetError), gate.request():
            raise AssertionError("nested request must not start")
        gate.consume()


async def test_child_tasks_share_exactly_one_send() -> None:
    gate = SingleSendGate()
    with gate.request():

        async def send() -> None:
            gate.consume()

        results = await asyncio.gather(send(), send(), return_exceptions=True)
    assert sum(result is None for result in results) == 1
    assert sum(isinstance(result, FleetError) for result in results) == 1


async def test_model_wrapper_expires_even_when_cancelled() -> None:
    gate = SingleSendGate()
    entered = asyncio.Event()
    saved = []

    async def respond(messages: object, info: object) -> ModelResponse:
        saved.append(copy_context())
        gate.consume()
        entered.set()
        await asyncio.Event().wait()
        return ModelResponse(parts=[TextPart("unreachable")])

    model = SingleSendModel(FunctionModel(respond), gate)
    execution = asyncio.create_task(model.request([], None, ModelRequestParameters()))
    try:
        await asyncio.wait_for(entered.wait(), timeout=1)
        execution.cancel()
        with pytest.raises(asyncio.CancelledError):
            await execution
        with pytest.raises(FleetError):
            saved[0].run(gate.consume)
    finally:
        if not execution.done():
            execution.cancel()
        await asyncio.gather(execution, return_exceptions=True)
