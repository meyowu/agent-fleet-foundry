"""Project SDK exception types, not their potentially secret-bearing contents."""

from __future__ import annotations

from openai import (
    APIConnectionError,
    APIResponseValidationError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    PermissionDeniedError,
    RateLimitError,
)
from pydantic import JsonValue, ValidationError
from pydantic_ai.exceptions import IncompleteToolCall, ModelHTTPError, ModelRetry

from agent_fleet.adapters.runtime.openai_transport_policy import (
    OpenAIRequestPolicyError,
    OpenAIResponsePolicyError,
)
from agent_fleet.domain.runtime_diagnostics import (
    RuntimeFailureCategory,
    RuntimeFailureCause,
    runtime_diagnostic_payload,
)


def runtime_failure_details(
    error: BaseException, category: RuntimeFailureCategory
) -> dict[str, JsonValue]:
    """Inspect at most eight typed causes; never stringify or retain an exception.

    No exception messages, dynamic class names, request IDs, headers, bodies or
    Pydantic error records are read. In particular, even validation field names
    and custom error types can be untrusted secret-bearing strings.
    """
    diagnostic: dict[str, JsonValue] = {
        "category": category.value,
        "cause_category": RuntimeFailureCause.UNKNOWN.value,
    }
    current: BaseException | None = error
    seen: set[int] = set()
    for _ in range(8):
        if current is None or id(current) in seen:
            break
        seen.add(id(current))
        cause = _cause_category(current)
        if cause is not RuntimeFailureCause.UNKNOWN:
            diagnostic["cause_category"] = cause.value
        if isinstance(current, (ModelHTTPError, APIStatusError)):
            status = current.status_code
            if type(status) is int and 100 <= status <= 599:
                diagnostic["http_status"] = status
        current = current.__cause__ if current.__cause__ is not None else current.__context__
    return runtime_diagnostic_payload({"runtime_diagnostic": diagnostic})


def _cause_category(error: BaseException) -> RuntimeFailureCause:
    # More specific SDK classes precede their base classes.
    for kind, category in (
        (OpenAIRequestPolicyError, RuntimeFailureCause.REQUEST_POLICY),
        (OpenAIResponsePolicyError, RuntimeFailureCause.RESPONSE_POLICY),
        (ValidationError, RuntimeFailureCause.SCHEMA_VALIDATION),
        (IncompleteToolCall, RuntimeFailureCause.INCOMPLETE_TOOL_CALL),
        (ModelRetry, RuntimeFailureCause.TOOL_RETRY),
        (APITimeoutError, RuntimeFailureCause.API_TIMEOUT),
        (APIConnectionError, RuntimeFailureCause.API_CONNECTION),
        (APIResponseValidationError, RuntimeFailureCause.API_RESPONSE_VALIDATION),
        (AuthenticationError, RuntimeFailureCause.API_AUTHENTICATION),
        (PermissionDeniedError, RuntimeFailureCause.API_PERMISSION),
        (RateLimitError, RuntimeFailureCause.API_RATE_LIMIT),
        (APIStatusError, RuntimeFailureCause.API_STATUS),
        (ModelHTTPError, RuntimeFailureCause.API_STATUS),
    ):
        if isinstance(error, kind):
            return category
    return RuntimeFailureCause.UNKNOWN
