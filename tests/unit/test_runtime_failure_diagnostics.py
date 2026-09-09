from __future__ import annotations

import json
from itertools import pairwise
from typing import Any

import httpx2
import pytest
from openai import (
    APIConnectionError,
    APIResponseValidationError,
    APITimeoutError,
    AuthenticationError,
    OpenAIError,
    PermissionDeniedError,
    RateLimitError,
)
from pydantic import ValidationError, create_model
from pydantic_ai.exceptions import IncompleteToolCall, ModelAPIError, ModelHTTPError, ModelRetry

from agent_fleet.adapters.runtime.failure_diagnostics import runtime_failure_details
from agent_fleet.adapters.runtime.openai_transport_policy import (
    OpenAIRequestPolicyError,
    OpenAIResponsePolicyError,
)
from agent_fleet.domain.runtime_diagnostics import (
    RuntimeFailureCategory,
    runtime_diagnostic_payload,
)

SENTINEL = "private-diagnostic-sentinel+/="


def _response(status: int) -> httpx2.Response:
    return httpx2.Response(
        status,
        request=httpx2.Request("POST", f"https://example.invalid/{SENTINEL}"),
        headers={"x-request-id": SENTINEL},
        json={"private": SENTINEL},
    )


@pytest.mark.parametrize(
    ("error", "cause", "status"),
    [
        (OpenAIError(SENTINEL), "unknown", None),
        (OpenAIRequestPolicyError(), "request_policy", None),
        (OpenAIResponsePolicyError(), "response_policy", None),
        (
            APIConnectionError(message=SENTINEL, request=_response(500).request),
            "api_connection",
            None,
        ),
        (APITimeoutError(request=_response(500).request), "api_timeout", None),
        (
            AuthenticationError(SENTINEL, response=_response(401), body=SENTINEL),
            "api_authentication",
            401,
        ),
        (
            PermissionDeniedError(SENTINEL, response=_response(403), body=SENTINEL),
            "api_permission",
            403,
        ),
        (RateLimitError(SENTINEL, response=_response(429), body=SENTINEL), "api_rate_limit", 429),
        (
            APIResponseValidationError(response=_response(200), body=SENTINEL),
            "api_response_validation",
            None,
        ),
        (ModelHTTPError(503, SENTINEL, SENTINEL), "api_status", 503),
        (IncompleteToolCall(SENTINEL), "incomplete_tool_call", None),
        (ModelRetry(SENTINEL), "tool_retry", None),
    ],
)
def test_known_types_project_only_fixed_values(
    error: BaseException, cause: str, status: int | None
) -> None:
    details = runtime_failure_details(error, RuntimeFailureCategory.PROVIDER_SDK)
    expected: dict[str, Any] = {"category": "provider_sdk", "cause_category": cause}
    if status is not None:
        expected["http_status"] = status
    assert details == {"runtime_diagnostic": expected}
    assert SENTINEL not in json.dumps(details)


def test_wrapped_timeout_and_cycle_are_bounded_without_error_stringification() -> None:
    wrapped = ModelAPIError(SENTINEL, SENTINEL)
    timeout = APITimeoutError(request=_response(500).request)
    wrapped.__cause__ = timeout
    timeout.__cause__ = wrapped
    assert runtime_failure_details(wrapped, RuntimeFailureCategory.PROVIDER_API) == {
        "runtime_diagnostic": {"category": "provider_api", "cause_category": "api_timeout"}
    }


@pytest.mark.parametrize(
    ("error_type", "cause"),
    [
        (OpenAIRequestPolicyError, "request_policy"),
        (OpenAIResponsePolicyError, "response_policy"),
    ],
)
def test_transport_policy_projection_omits_untrusted_context_and_metadata(
    error_type: type[OpenAIError], cause: str
) -> None:
    error = error_type()
    error.__context__ = OpenAIError(SENTINEL)
    error.add_note(SENTINEL)
    details = runtime_failure_details(error, RuntimeFailureCategory.PROVIDER_SDK)
    assert runtime_diagnostic_payload(details) == {
        "runtime_diagnostic": {"category": "provider_sdk", "cause_category": cause}
    }
    assert SENTINEL not in json.dumps(details)


def test_cleanup_cause_survives_safe_event_projection_without_other_details() -> None:
    assert runtime_diagnostic_payload(
        {
            "runtime_diagnostic": {
                "category": "provider_sdk",
                "cause_category": "client_cleanup",
                "raw": SENTINEL,
            },
            "secret": SENTINEL,
        }
    ) == {"runtime_diagnostic": {"category": "provider_sdk", "cause_category": "client_cleanup"}}


def test_validation_fields_inputs_and_error_messages_are_not_read_or_copied() -> None:
    fields: dict[str, Any] = {SENTINEL: (int, ...)}
    model = create_model("SecretModel", **fields)
    try:
        model.model_validate({SENTINEL: SENTINEL})
    except ValidationError as error:
        details = runtime_failure_details(error, RuntimeFailureCategory.OUTPUT_SCHEMA)
    assert details == {
        "runtime_diagnostic": {"category": "output_schema", "cause_category": "schema_validation"}
    }
    assert SENTINEL not in json.dumps(details)


def test_unknown_dynamic_exception_name_and_text_are_not_accessed() -> None:
    class HostileError(Exception):
        def __str__(self) -> str:
            raise AssertionError("must never stringify provider exception")

        def __repr__(self) -> str:
            raise AssertionError("must never inspect provider repr")

    HostileError.__name__ = SENTINEL
    details = runtime_failure_details(HostileError(SENTINEL), RuntimeFailureCategory.PROVIDER_SDK)
    assert details == {
        "runtime_diagnostic": {"category": "provider_sdk", "cause_category": "unknown"}
    }


def test_chain_beyond_eight_nodes_is_not_inspected() -> None:
    errors = [ValueError(SENTINEL) for _ in range(8)]
    for first, second in pairwise(errors):
        first.__cause__ = second
    errors[-1].__cause__ = APITimeoutError(request=_response(500).request)
    details = runtime_failure_details(errors[0], RuntimeFailureCategory.REQUEST_CONSTRUCTION)
    assert details["runtime_diagnostic"] == {
        "category": "request_construction",
        "cause_category": "unknown",
    }


@pytest.mark.parametrize("status", [True, False, "401", SENTINEL, 99, 600, None])
def test_invalid_http_status_is_omitted(status: object) -> None:
    error = ModelHTTPError(400, SENTINEL, SENTINEL)
    error.status_code = status  # type: ignore[assignment]
    assert runtime_failure_details(error, RuntimeFailureCategory.PROVIDER_HTTP) == {
        "runtime_diagnostic": {"category": "provider_http", "cause_category": "api_status"}
    }


@pytest.mark.parametrize(
    "payload",
    [
        None,
        SENTINEL,
        [],
        {},
        {"category": SENTINEL, "cause_category": "unknown"},
        {"category": "provider_sdk", "cause_category": SENTINEL},
    ],
)
def test_event_projection_rejects_unknown_diagnostic_shapes(payload: object) -> None:
    assert runtime_diagnostic_payload({"runtime_diagnostic": payload, "secret": SENTINEL}) == {}


def test_event_projection_discards_unknown_fields_and_copies_values() -> None:
    original: dict[str, Any] = {
        "category": "provider_sdk",
        "cause_category": "api_status",
        "http_status": 400,
        "raw": SENTINEL,
        "request_id": SENTINEL,
        "validation_location": [SENTINEL],
    }
    projected = runtime_diagnostic_payload({"runtime_diagnostic": original, "raw": SENTINEL})
    original["category"] = SENTINEL
    assert projected == {
        "runtime_diagnostic": {
            "category": "provider_sdk",
            "cause_category": "api_status",
            "http_status": 400,
        }
    }
