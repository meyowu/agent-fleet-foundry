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
from agent_fleet.domain.models import VerifierVerdict
from agent_fleet.domain.runtime_diagnostics import (
    RuntimeFailureCategory,
    RuntimeFailureCause,
    runtime_diagnostic_payload,
)

_VERIFIER_LIST_FIELDS = frozenset(
    {
        "criterion_results",
        "evidence_artifact_ids",
        "regressions",
        "required_repairs",
        "proof_gaps",
        "structured_criterion_results",
    }
)
_VERIFIER_FIELDS = _VERIFIER_LIST_FIELDS | {"verdict", "rationale"}
_CRITERION_FIELDS = frozenset(
    {"criterion_id", "verdict", "evidence_artifact_ids", "command_ids", "explanation"}
)
_ISSUE_TYPES = {
    "missing": "missing",
    "string_type": "type",
    "list_type": "type",
    "dict_type": "type",
    "model_type": "type",
    "model_attributes_type": "type",
    "enum": "enum",
    "literal_error": "enum",
    "string_pattern_mismatch": "pattern",
    "string_too_short": "length",
    "string_too_long": "length",
    "too_short": "length",
    "too_long": "length",
    "value_error": "value",
}
# These are diagnostic tokens, not proof of a builtin error's provenance:
# PydanticCustomError can reuse a recognized token without identifying that fact.
_UNKNOWN_ISSUE = ("unknown", "unknown")


def _verifier_field(location: object) -> str:
    if type(location) is not tuple or len(location) > 4:
        return "unknown"
    if not location:
        return "schema"
    head = location[0]
    if type(head) is not str or len(head) > 32 or head not in _VERIFIER_FIELDS:
        return "unknown"
    if len(location) == 1:
        return head
    if head not in _VERIFIER_LIST_FIELDS or type(location[1]) is not int or location[1] < 0:
        return "unknown"
    if len(location) == 2:
        return head
    if head != "structured_criterion_results":
        return "unknown"
    child = location[2]
    if type(child) is not str or len(child) > 32 or child not in _CRITERION_FIELDS:
        return "unknown"
    if len(location) == 4 and (
        child not in {"evidence_artifact_ids", "command_ids"}
        or type(location[3]) is not int
        or location[3] < 0
    ):
        return "unknown"
    return "structured_criterion_results." + child


def _verifier_issues(error: ValidationError) -> set[tuple[str, str]]:
    try:
        count = error.error_count()
        if type(count) is not int or not 1 <= count <= 32:
            return {_UNKNOWN_ISSUE}
        # Pydantic still builds msg internally. Never access/copy it, title,
        # input, ctx or URL; only map locations/types to the finite vocabulary.
        records = error.errors(include_input=False, include_context=False, include_url=False)
        if type(records) is not list or len(records) != count:
            return {_UNKNOWN_ISSUE}
        issues: set[tuple[str, str]] = set()
        for record in records:
            if (
                type(record) is not dict
                or len(record) > 32
                or any(type(key) is not str for key in record)
            ):
                return {_UNKNOWN_ISSUE}
            raw_type = record.get("type")
            issue = (
                _ISSUE_TYPES.get(raw_type, "unknown")
                if type(raw_type) is str and len(raw_type) <= 32
                else "unknown"
            )
            issues.add((_verifier_field(record.get("loc")), issue))
        return issues
    except Exception:
        # Diagnostic extraction must not replace the original failed result,
        # leak its chain or turn that failure into an accepted output.
        return {_UNKNOWN_ISSUE}


def runtime_failure_details(
    error: BaseException,
    category: RuntimeFailureCategory,
    *,
    output_model: object = None,
) -> dict[str, JsonValue]:
    """Inspect at most eight typed causes; never stringify or retain an exception.

    No exception messages, dynamic class names, request IDs, headers, bodies or
    generic Pydantic error records are read. Only the exact trusted VerifierVerdict
    binding permits finite location/type projection; unknown keys/types are never
    emitted. This cannot recover a previously discarded invalid response.
    """
    diagnostic: dict[str, JsonValue] = {
        "category": category.value,
        "cause_category": RuntimeFailureCause.UNKNOWN.value,
    }
    current: BaseException | None = error
    seen: set[int] = set()
    verifier_bound = output_model is VerifierVerdict
    issues: set[tuple[str, str]] = set()
    if verifier_bound:
        diagnostic["expected_output_contract"] = "verifier_verdict"
    for _ in range(8):
        if current is None or id(current) in seen:
            break
        seen.add(id(current))
        cause = _cause_category(current)
        if cause is not RuntimeFailureCause.UNKNOWN:
            diagnostic["cause_category"] = cause.value
        if verifier_bound and type(current) is ValidationError:
            issues.update(_verifier_issues(current))
        if isinstance(current, (ModelHTTPError, APIStatusError)):
            status = current.status_code
            if type(status) is int and 100 <= status <= 599:
                diagnostic["http_status"] = status
        current = current.__cause__ if current.__cause__ is not None else current.__context__
    if issues:
        diagnostic["validation_issues"] = [
            {"field": field, "issue": issue} for field, issue in sorted(issues)[:8]
        ]
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
