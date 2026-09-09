"""Finite, provider-neutral diagnostic values safe to project into run events."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum

from pydantic import JsonValue


class RuntimeFailureCategory(StrEnum):
    CONTENT_FILTER = "content_filter"
    PROVIDER_HTTP = "provider_http"
    PROVIDER_API = "provider_api"
    PROVIDER_SDK = "provider_sdk"
    INVOCATION_TIMEOUT = "invocation_timeout"
    PROVIDER_TIMEOUT = "provider_timeout"
    USAGE_LIMIT = "usage_limit"
    STRUCTURED_OUTPUT = "structured_output"
    OUTPUT_SCHEMA = "output_schema"
    TOOL_ARGUMENTS = "tool_arguments"
    STRUCTURED_OUTPUT_AFTER_SIDE_EFFECT = "structured_output_after_side_effect"
    REQUEST_CONSTRUCTION = "request_construction"


class RuntimeFailureCause(StrEnum):
    SCHEMA_VALIDATION = "schema_validation"
    TOOL_RETRY = "tool_retry"
    INCOMPLETE_TOOL_CALL = "incomplete_tool_call"
    API_TIMEOUT = "api_timeout"
    API_CONNECTION = "api_connection"
    API_RESPONSE_VALIDATION = "api_response_validation"
    API_AUTHENTICATION = "api_authentication"
    API_PERMISSION = "api_permission"
    API_RATE_LIMIT = "api_rate_limit"
    API_STATUS = "api_status"
    REQUEST_POLICY = "request_policy"
    RESPONSE_POLICY = "response_policy"
    CLIENT_CLEANUP = "client_cleanup"
    UNKNOWN = "unknown"


def runtime_diagnostic_payload(details: Mapping[str, object]) -> dict[str, JsonValue]:
    """Copy only known literals/numeric HTTP status, never arbitrary error details."""
    value = details.get("runtime_diagnostic")
    if type(value) is not dict:
        return {}
    category = value.get("category")
    cause = value.get("cause_category")
    if type(category) is not str or category not in frozenset(RuntimeFailureCategory):
        return {}
    if type(cause) is not str or cause not in frozenset(RuntimeFailureCause):
        return {}
    diagnostic: dict[str, JsonValue] = {"category": category, "cause_category": cause}
    status = value.get("http_status")
    if type(status) is int and 100 <= status <= 599:
        diagnostic["http_status"] = status
    return {"runtime_diagnostic": diagnostic}
