"""Actual pinned SDK client with offline HTTP; no harness-loop substitution."""

import asyncio
import json
import logging
from typing import Any

import httpx2
import pytest
from openai import OpenAIError

import agent_fleet.adapters.runtime.openai_client as client_module
from agent_fleet.adapters.runtime.openai_client import (
    open_openai_client,
    reject_unsafe_openai_environment,
)
from agent_fleet.adapters.runtime.single_send import SingleSendGate
from agent_fleet.domain.errors import FleetError
from agent_fleet.domain.security import Redactor

_KEY = "shared-openai-offline-selected-key"


@pytest.fixture(autouse=True)
def clean_ambient(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_CUSTOM_HEADERS", raising=False)
    monkeypatch.delenv("OPENAI_LOG", raising=False)


async def test_actual_client_single_send_and_closed_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[httpx2.Request] = []
    clients: list[httpx2.AsyncClient] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        sent.append(request)
        assert str(request.url) == "https://api.openai.com/v1/responses"
        assert request.headers["authorization"] == f"Bearer {_KEY}"
        assert _KEY not in request.content.decode()
        assert json.loads(request.content)["model"] == "offline-exact"
        return httpx2.Response(
            200,
            request=request,
            headers={"set-cookie": "unexpected=cookie; Path=/"},
            json={
                "id": "resp_offline",
                "object": "response",
                "created_at": 1,
                "status": "completed",
                "model": "offline-exact",
                "output": [],
                "usage": {"input_tokens": 2, "output_tokens": 1, "total_tokens": 3},
            },
        )

    def transport(**kwargs: Any) -> httpx2.AsyncClient:
        assert kwargs["trust_env"] is kwargs["follow_redirects"] is False
        client = httpx2.AsyncClient(transport=httpx2.MockTransport(respond), **kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(client_module, "DefaultAsyncHttpxClient", transport)
    monkeypatch.setenv("OPENAI_API_KEY", "unselected-ambient-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://unselected.invalid")
    monkeypatch.setenv("HTTPS_PROXY", "https://unselected.invalid")
    gate = SingleSendGate()
    async with open_openai_client(
        raw_credential=_KEY, redactor=Redactor([_KEY]), timeout_seconds=2, gate=gate
    ) as client:
        with gate.request():
            response = await client.responses.create(model="offline-exact", input="fixture")
            assert response.model == "offline-exact"
            with pytest.raises(OpenAIError):
                await client.responses.create(model="offline-exact", input="second send denied")
        assert list(clients[0].cookies.jar) == []
    assert len(sent) == len(clients) == 1 and clients[0].is_closed


async def test_opt_in_actual_raw_responses_preserves_uncoerced_wire_and_single_send(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[httpx2.Request] = []
    clients: list[httpx2.AsyncClient] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        sent.append(request)
        assert request.headers.get_list("x-stainless-raw-response") == ["true"]
        assert str(request.url) == "https://api.openai.com/v1/responses"
        return httpx2.Response(
            200,
            request=request,
            json={"usage": {"input_tokens": True}, "model": "offline-exact"},
        )

    def transport(**kwargs: Any) -> httpx2.AsyncClient:
        client = httpx2.AsyncClient(transport=httpx2.MockTransport(respond), **kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(client_module, "DefaultAsyncHttpxClient", transport)
    gate = SingleSendGate()
    async with open_openai_client(
        raw_credential=_KEY,
        redactor=Redactor([_KEY]),
        timeout_seconds=2,
        gate=gate,
        raw_responses=True,
    ) as client:
        with gate.request():
            response = await client.responses.with_raw_response.create(
                model="offline-exact", input="fixture"
            )
            assert json.loads(response.http_response.content)["usage"]["input_tokens"] is True
            with pytest.raises(OpenAIError):
                await client.responses.with_raw_response.create(
                    model="offline-exact", input="no second send"
                )
    assert len(sent) == len(clients) == 1 and clients[0].is_closed


@pytest.mark.parametrize(
    ("raw_mode", "value", "path"),
    [
        (False, "true", "responses"),
        (True, None, "responses"),
        (True, "false", "responses"),
        (True, "stream", "responses"),
        (True, "TRUE", "responses"),
        (True, "true, true", "responses"),
        (True, "true", "chat/completions"),
        (True, "true", "responses?unexpected=1"),
    ],
)
async def test_raw_mode_header_and_endpoint_mismatches_never_send(
    monkeypatch: pytest.MonkeyPatch, raw_mode: bool, value: str | None, path: str
) -> None:
    sent: list[httpx2.Request] = []
    clients: list[httpx2.AsyncClient] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        sent.append(request)
        raise AssertionError("raw response policy must reject before send")

    def transport(**kwargs: Any) -> httpx2.AsyncClient:
        client = httpx2.AsyncClient(transport=httpx2.MockTransport(respond), **kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(client_module, "DefaultAsyncHttpxClient", transport)
    gate = SingleSendGate()
    async with open_openai_client(
        raw_credential=_KEY,
        redactor=Redactor([_KEY]),
        timeout_seconds=2,
        gate=gate,
        raw_responses=raw_mode,
    ) as client:
        with gate.request(), pytest.raises(OpenAIError):
            await client.post(
                "/" + path,
                cast_to=object,
                body={"model": "offline-exact", "input": "fixture"},
                options={
                    "headers": {"x-stainless-raw-response": value} if value is not None else {}
                },
            )
    assert not sent and clients[0].is_closed


@pytest.mark.parametrize("raw_mode", [True, 1, "true", None])
async def test_raw_mode_requires_exact_boolean_and_ticket_before_construction(
    monkeypatch: pytest.MonkeyPatch, raw_mode: Any
) -> None:
    def forbidden(**kwargs: Any) -> httpx2.AsyncClient:
        raise AssertionError("invalid raw-mode configuration must not construct clients")

    monkeypatch.setattr(client_module, "DefaultAsyncHttpxClient", forbidden)
    with pytest.raises(OpenAIError):
        async with open_openai_client(
            raw_credential=_KEY,
            redactor=Redactor([_KEY]),
            timeout_seconds=2,
            raw_responses=raw_mode,
        ):
            raise AssertionError("invalid factory scope must not open")


async def test_shared_factory_retains_sdk_exit_under_repeated_cancel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered = asyncio.Event()
    closing = asyncio.Event()
    release = asyncio.Event()
    closed = asyncio.Event()
    starts = 0

    class Physical(httpx2.MockTransport):
        async def aclose(self) -> None:
            nonlocal starts
            starts += 1
            closing.set()
            await release.wait()
            closed.set()

    def forbidden(request: httpx2.Request) -> httpx2.Response:
        raise AssertionError("This client lifecycle test must not send a request")

    def transport(**kwargs: Any) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(transport=Physical(forbidden), **kwargs)

    monkeypatch.setattr(client_module, "DefaultAsyncHttpxClient", transport)

    async def invoke() -> None:
        async with open_openai_client(
            raw_credential=_KEY, redactor=Redactor([_KEY]), timeout_seconds=2
        ):
            entered.set()
            await asyncio.Event().wait()

    execution = asyncio.create_task(invoke())
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        execution.cancel()
        await asyncio.wait_for(closing.wait(), timeout=2)
        for _ in range(3):
            execution.cancel()
            await asyncio.sleep(0)
            assert not execution.done() and not closed.is_set()
    finally:
        release.set()
        if not entered.is_set():
            execution.cancel()
        await asyncio.gather(execution, return_exceptions=True)
    assert execution.cancelled() and closed.is_set() and starts == 1


async def test_response_observer_sees_raw_wire_types_after_header_sanitization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[object] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            request=request,
            headers={"x-untrusted-header": "must-be-cleared"},
            json={
                "id": "resp_offline",
                "object": "response",
                "created_at": 1,
                "status": "completed",
                "model": "offline-exact",
                "output": [],
                "usage": {"input_tokens": True, "output_tokens": 1, "total_tokens": 2},
            },
        )

    def transport(**kwargs: Any) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(transport=httpx2.MockTransport(respond), **kwargs)

    async def observer(response: httpx2.Response) -> None:
        assert "x-untrusted-header" not in response.headers
        observed.append(json.loads(await response.aread())["usage"]["input_tokens"])

    monkeypatch.setattr(client_module, "DefaultAsyncHttpxClient", transport)
    async with open_openai_client(
        raw_credential=_KEY,
        redactor=Redactor([_KEY]),
        timeout_seconds=2,
        response_observer=observer,
    ) as client:
        await client.responses.create(model="offline-exact", input="fixture")
    assert len(observed) == 1 and observed[0] is True


@pytest.mark.parametrize("name", ["openai", "openai._base_client", "httpx2", "httpcore2.http11"])
@pytest.mark.parametrize("level", [logging.INFO, logging.DEBUG])
def test_ticketed_sdk_logging_policy_checks_child_namespaces(name: str, level: int) -> None:
    logger = logging.getLogger(name)
    original = logger.level
    logger.setLevel(level)
    try:
        with pytest.raises(FleetError):
            reject_unsafe_openai_environment()
    finally:
        logger.setLevel(original)


@pytest.mark.parametrize("variable", ["OPENAI_LOG", "OPENAI_CUSTOM_HEADERS"])
def test_ticketed_sdk_policy_rejects_even_empty_ambient_setting(
    monkeypatch: pytest.MonkeyPatch, variable: str
) -> None:
    monkeypatch.setenv(variable, "")
    with pytest.raises(FleetError):
        reject_unsafe_openai_environment()
