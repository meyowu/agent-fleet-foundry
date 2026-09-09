from __future__ import annotations

from http.cookiejar import CookieJar
from urllib.request import Request

import httpx2
import pytest
from openai import AsyncOpenAI, DefaultAsyncHttpxClient

from agent_fleet.adapters.runtime.openai_transport_policy import (
    OpenAIRequestPolicyError,
    OpenAIResponsePolicyError,
    new_stateless_cookie_jar,
)
from agent_fleet.adapters.runtime.pydantic_ai import (
    _openai_request_guard,
    _openai_response_guard,
)
from agent_fleet.domain.security import Redactor

_SENTINEL = "offline-cookie-transport-credential"
_ENDPOINTS = ("responses", "chat/completions")
_COOKIE_HEADERS = (
    (),
    (("Set-Cookie", "host_only=offline; Path=/; Secure; HttpOnly"),),
    (("Set-Cookie", "domain_cookie=offline; Domain=api.openai.com; Path=/v1; Secure"),),
    (("Set-Cookie", "parent_cookie=offline; Domain=.openai.com; Path=/; Secure"),),
    (
        ("Set-Cookie", "first=offline; Path=/; Secure"),
        ("Set-Cookie", "second=offline; Domain=.openai.com; Path=/v1; HttpOnly"),
    ),
)


@pytest.fixture(autouse=True)
def isolated_sdk_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", _SENTINEL)
    monkeypatch.delenv("OPENAI_CUSTOM_HEADERS", raising=False)


def _client(http_client: DefaultAsyncHttpxClient) -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=_SENTINEL,
        admin_api_key="",
        organization="",
        project="",
        webhook_secret="",
        base_url="https://api.openai.com/v1",
        default_headers={"Authorization": f"Bearer {_SENTINEL}", "Host": "api.openai.com"},
        http_client=http_client,
        max_retries=0,
        timeout=5.0,
    )


async def _request(
    client: AsyncOpenAI, endpoint: str, *, headers: dict[str, str] | None = None
) -> str:
    if endpoint == "responses":
        response = await client.responses.create(
            model="gpt-test", input="bounded offline input", extra_headers=headers
        )
        return response.id
    assert endpoint == "chat/completions"
    completion = await client.chat.completions.create(
        model="gpt-test",
        messages=[{"role": "user", "content": "bounded offline input"}],
        extra_headers=headers,
    )
    return completion.id


def _payload(endpoint: str, index: int) -> dict[str, object]:
    if endpoint == "responses":
        return {
            "id": f"response-{index}",
            "object": "response",
            "created_at": 0,
            "status": "completed",
            "model": "gpt-test",
            "output": [],
            "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
        }
    assert endpoint == "chat/completions"
    return {
        "id": f"response-{index}",
        "object": "chat.completion",
        "created": 0,
        "model": "gpt-test",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "OK"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


@pytest.mark.parametrize("endpoint", _ENDPOINTS)
@pytest.mark.parametrize(
    "cookie_headers", _COOKIE_HEADERS, ids=("control", "host", "domain", "parent", "multiple")
)
async def test_actual_sdk_continuations_never_store_or_send_response_cookies(
    endpoint: str, cookie_headers: tuple[tuple[str, str], ...]
) -> None:
    sends: list[httpx2.Request] = []
    jars_before_response_guard: list[int] = []
    headers_before_response_guard: list[list[str]] = []
    redactor = Redactor([_SENTINEL])
    response_guard = _openai_response_guard(redactor)
    jar = new_stateless_cookie_jar()

    async def handler(request: httpx2.Request) -> httpx2.Response:
        sends.append(request)
        return httpx2.Response(
            200, headers=cookie_headers, json=_payload(endpoint, len(sends)), request=request
        )

    async def inspect_then_guard(response: httpx2.Response) -> None:
        # HTTPX has already attempted extraction when a response hook runs.
        jars_before_response_guard.append(len(http_client.cookies.jar))
        headers_before_response_guard.append(response.headers.get_list("set-cookie"))
        await response_guard(response)
        assert set(response.headers) == {"content-type"}

    http_client = DefaultAsyncHttpxClient(
        transport=httpx2.MockTransport(handler),
        trust_env=False,
        follow_redirects=False,
        cookies=jar,
        event_hooks={
            "request": [_openai_request_guard(_SENTINEL, redactor)],
            "response": [inspect_then_guard],
        },
    )
    assert http_client.cookies.jar is jar
    async with _client(http_client) as client:
        assert client.max_retries == 0
        for index in range(1, 4):
            assert await _request(client, endpoint) == f"response-{index}"
            assert len(jar) == 0

    assert http_client.is_closed
    assert len(sends) == 3
    assert jars_before_response_guard == [0, 0, 0]
    assert headers_before_response_guard == [[value for _, value in cookie_headers]] * 3
    for request in sends:
        assert request.url.path == f"/v1/{endpoint}"
        assert "cookie" not in request.headers
        assert set(request.headers) == {
            "accept",
            "authorization",
            "content-length",
            "content-type",
            "host",
            "user-agent",
        }
        assert request.headers["authorization"] == f"Bearer {_SENTINEL}"
        assert request.headers["host"] == "api.openai.com"
        assert request.headers["content-length"] == str(len(request.content))


@pytest.mark.parametrize("endpoint", _ENDPOINTS)
@pytest.mark.parametrize("header_name", ("Cookie", "X-Unreviewed-Header"))
async def test_explicit_headers_still_fail_closed_after_a_cookie_response(
    endpoint: str, header_name: str
) -> None:
    sends: list[httpx2.Request] = []
    redactor = Redactor([_SENTINEL])

    async def handler(request: httpx2.Request) -> httpx2.Response:
        sends.append(request)
        return httpx2.Response(
            200,
            headers={"Set-Cookie": "provider_session=offline; Path=/; Secure"},
            json=_payload(endpoint, len(sends)),
            request=request,
        )

    http_client = DefaultAsyncHttpxClient(
        transport=httpx2.MockTransport(handler),
        trust_env=False,
        follow_redirects=False,
        cookies=new_stateless_cookie_jar(),
        event_hooks={
            "request": [_openai_request_guard(_SENTINEL, redactor)],
            "response": [_openai_response_guard(redactor)],
        },
    )
    async with _client(http_client) as client:
        assert await _request(client, endpoint) == "response-1"
        with pytest.raises(OpenAIRequestPolicyError) as caught:
            await _request(client, endpoint, headers={header_name: "untrusted=offline"})

    assert type(caught.value) is OpenAIRequestPolicyError
    assert str(caught.value) == "The provider request failed the pinned transport policy."
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert len(sends) == 1
    assert len(http_client.cookies.jar) == 0
    assert "cookie" not in sends[0].headers
    assert http_client.is_closed


@pytest.mark.parametrize("endpoint", _ENDPOINTS)
async def test_secret_bearing_response_cookies_raise_only_fixed_policy_error(endpoint: str) -> None:
    sends: list[httpx2.Request] = []
    redactor = Redactor([_SENTINEL])

    async def handler(request: httpx2.Request) -> httpx2.Response:
        sends.append(request)
        return httpx2.Response(
            200,
            headers={"Set-Cookie": f"secret={_SENTINEL}; Path=/; Secure"},
            json=_payload(endpoint, 1),
            request=request,
        )

    http_client = DefaultAsyncHttpxClient(
        transport=httpx2.MockTransport(handler),
        trust_env=False,
        follow_redirects=False,
        cookies=new_stateless_cookie_jar(),
        event_hooks={
            "request": [_openai_request_guard(_SENTINEL, redactor)],
            "response": [_openai_response_guard(redactor)],
        },
    )
    async with _client(http_client) as client:
        with pytest.raises(OpenAIResponsePolicyError) as caught:
            await _request(client, endpoint)

    assert type(caught.value) is OpenAIResponsePolicyError
    assert str(caught.value) == "The provider response failed the pinned transport policy."
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert len(sends) == 1
    assert len(http_client.cookies.jar) == 0
    assert http_client.is_closed


def test_stateless_cookie_jars_are_fresh_and_reject_even_manually_seeded_cookies() -> None:
    first = new_stateless_cookie_jar()
    second = new_stateless_cookie_jar()
    assert isinstance(first, CookieJar)
    assert first is not second
    seed = httpx2.Cookies({"manual": "offline"})
    for cookie in seed.jar:
        first.set_cookie(cookie)
    assert len(first) == 1
    assert len(second) == 0
    request = Request("https://api.openai.com/v1/responses")
    first.add_cookie_header(request)
    assert request.get_header("Cookie") is None
