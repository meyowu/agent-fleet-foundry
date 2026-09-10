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


VERIFIER_VALIDATION_FIELDS = frozenset(
    {
        "schema",
        "unknown",
        "verdict",
        "criterion_results",
        "evidence_artifact_ids",
        "regressions",
        "required_repairs",
        "proof_gaps",
        "rationale",
        "structured_criterion_results",
        "structured_criterion_results.criterion_id",
        "structured_criterion_results.verdict",
        "structured_criterion_results.evidence_artifact_ids",
        "structured_criterion_results.command_ids",
        "structured_criterion_results.explanation",
    }
)
VERIFIER_VALIDATION_ISSUES = frozenset(
    {"missing", "type", "enum", "pattern", "length", "value", "unknown"}
)


def _validation_issues(value: object) -> list[JsonValue] | None:
    if type(value) is not list or not 1 <= len(value) <= 8:
        return None
    pairs: set[tuple[str, str]] = set()
    for item in value:
        if type(item) is not dict or len(item) > 32 or any(type(key) is not str for key in item):
            return None
        field, issue = item.get("field"), item.get("issue")
        if (
            type(field) is not str
            or len(field) > 64
            or field not in VERIFIER_VALIDATION_FIELDS
            or type(issue) is not str
            or len(issue) > 16
            or issue not in VERIFIER_VALIDATION_ISSUES
        ):
            return None
        pairs.add((field, issue))
    return [{"field": field, "issue": issue} for field, issue in sorted(pairs)]


def runtime_diagnostic_payload(details: Mapping[str, object]) -> dict[str, JsonValue]:
    """Copy only known literals/numeric HTTP status, never arbitrary error details."""
    if (
        type(details) is not dict
        or len(details) > 32
        or any(type(key) is not str for key in details)
    ):
        return {}
    value = details.get("runtime_diagnostic")
    if type(value) is not dict or len(value) > 32 or any(type(key) is not str for key in value):
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
    expected = value.get("expected_output_contract")
    if type(expected) is str and expected == "verifier_verdict":
        # This is the trusted expected output, not the SDK component that failed.
        diagnostic["expected_output_contract"] = "verifier_verdict"
        issues = _validation_issues(value.get("validation_issues"))
        if issues is not None:
            diagnostic["validation_issues"] = issues
    return {"runtime_diagnostic": diagnostic}
