from __future__ import annotations

import json
from collections.abc import Mapping
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
from pydantic_core import PydanticCustomError

from agent_fleet.adapters.runtime.failure_diagnostics import (
    _verifier_field,
    runtime_failure_details,
)
from agent_fleet.adapters.runtime.openai_transport_policy import (
    OpenAIRequestPolicyError,
    OpenAIResponsePolicyError,
)
from agent_fleet.domain.models import VerifierVerdict
from agent_fleet.domain.runtime_diagnostics import (
    VERIFIER_VALIDATION_FIELDS,
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


def _validation_error(*locations: tuple[str | int, ...]) -> ValidationError:
    return ValidationError.from_exception_data(
        SENTINEL,
        [{"type": "missing", "loc": location, "input": SENTINEL} for location in locations],
    )


def _verifier_diagnostic(error: BaseException) -> dict[str, Any]:
    details = runtime_failure_details(
        error,
        RuntimeFailureCategory.STRUCTURED_OUTPUT_AFTER_SIDE_EFFECT,
        output_model=VerifierVerdict,
    )["runtime_diagnostic"]
    assert isinstance(details, dict)
    return details


@pytest.mark.parametrize(
    ("location", "field"),
    [
        ((), "schema"),
        (("verdict",), "verdict"),
        (("rationale",), "rationale"),
        (("criterion_results", 0), "criterion_results"),
        (("evidence_artifact_ids", 100), "evidence_artifact_ids"),
        (("structured_criterion_results", 4), "structured_criterion_results"),
        (("structured_criterion_results", 4, "verdict"), "structured_criterion_results.verdict"),
        (
            ("structured_criterion_results", 4, "criterion_id"),
            "structured_criterion_results.criterion_id",
        ),
        (
            ("structured_criterion_results", 4, "evidence_artifact_ids", 6),
            "structured_criterion_results.evidence_artifact_ids",
        ),
        (
            ("structured_criterion_results", 4, "command_ids", 6),
            "structured_criterion_results.command_ids",
        ),
        (
            ("structured_criterion_results", 4, "explanation"),
            "structured_criterion_results.explanation",
        ),
        ((SENTINEL,), "unknown"),
        (("criterion_results", SENTINEL), "unknown"),
        (("criterion_results", True), "unknown"),
        (("criterion_results", -1), "unknown"),
        (("verdict", 0), "unknown"),
        (("criterion_results", 0, "verdict"), "unknown"),
        (("structured_criterion_results", 0, SENTINEL), "unknown"),
        (("structured_criterion_results", 0, "verdict", 1), "unknown"),
        (("structured_criterion_results", 0, "command_ids", False), "unknown"),
        (("structured_criterion_results", 0, "command_ids", -1), "unknown"),
        (("structured_criterion_results", 0, "command_ids", 1, SENTINEL), "unknown"),
        (["verdict"], "unknown"),
    ],
)
def test_verifier_locations_emit_only_finite_labels_without_indices(
    location: object, field: str
) -> None:
    assert _verifier_field(location) == field


def test_verifier_projection_discards_unknown_keys_messages_inputs_and_custom_error_types() -> None:
    error = ValidationError.from_exception_data(
        SENTINEL,
        [
            {
                "type": PydanticCustomError(SENTINEL, "{private}", {"private": SENTINEL}),
                "loc": (SENTINEL,),
                "input": SENTINEL,
            }
        ],
    )
    error.add_note(SENTINEL)
    diagnostic = _verifier_diagnostic(error)
    assert diagnostic["expected_output_contract"] == "verifier_verdict"
    assert diagnostic["validation_issues"] == [{"field": "unknown", "issue": "unknown"}]
    assert SENTINEL not in json.dumps(diagnostic)


def test_custom_error_with_known_token_is_not_claimed_to_have_builtin_provenance() -> None:
    error = ValidationError.from_exception_data(
        SENTINEL,
        [
            {
                "type": PydanticCustomError("enum", "{private}", {"private": SENTINEL}),
                "loc": ("verdict",),
                "input": SENTINEL,
            }
        ],
    )
    diagnostic = _verifier_diagnostic(error)
    assert diagnostic["validation_issues"] == [{"field": "verdict", "issue": "enum"}]
    assert SENTINEL not in json.dumps(diagnostic)


def test_generic_and_nonidentical_output_bindings_never_materialize_validation_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class DifferentVerdict(VerifierVerdict):
        pass

    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("generic diagnostics must never inspect validation records")

    error = _validation_error(("rationale",))
    monkeypatch.setattr(ValidationError, "error_count", forbidden)
    monkeypatch.setattr(ValidationError, "errors", forbidden)
    for model in (None, DifferentVerdict, "verifier_verdict"):
        assert runtime_failure_details(
            error, RuntimeFailureCategory.OUTPUT_SCHEMA, output_model=model
        ) == {
            "runtime_diagnostic": {
                "category": "output_schema",
                "cause_category": "schema_validation",
            }
        }


def test_validation_error_subclass_is_not_inspected() -> None:
    class HostileValidationError(ValidationError):
        def error_count(self) -> int:
            raise AssertionError("subclass count must not be inspected")

        def errors(self, **kwargs: Any) -> Any:
            raise AssertionError("subclass records must not be inspected")

    error = HostileValidationError.from_exception_data(SENTINEL, [])
    assert type(error) is HostileValidationError
    assert _verifier_diagnostic(error) == {
        "category": "structured_output_after_side_effect",
        "cause_category": "schema_validation",
        "expected_output_contract": "verifier_verdict",
    }


@pytest.mark.parametrize("count", [33, 1000, 0, -1, True, "1"])
def test_error_count_bound_precedes_record_materialization(
    monkeypatch: pytest.MonkeyPatch, count: object
) -> None:
    error = _validation_error(("rationale",))
    calls: list[object] = []

    def records(*args: object, **kwargs: object) -> object:
        calls.append("unexpected")
        raise AssertionError("records must not be materialized")

    monkeypatch.setattr(ValidationError, "error_count", lambda self: count)
    monkeypatch.setattr(ValidationError, "errors", records)
    assert _verifier_diagnostic(error)["validation_issues"] == [
        {"field": "unknown", "issue": "unknown"}
    ]
    assert calls == []


def test_safe_extraction_flags_and_failure_do_not_expose_a_new_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = _validation_error(("rationale",))
    calls: list[dict[str, object]] = []

    def broken(self: ValidationError, **kwargs: object) -> Any:
        calls.append(kwargs)
        raise RuntimeError(SENTINEL)

    monkeypatch.setattr(ValidationError, "errors", broken)
    diagnostic = _verifier_diagnostic(error)
    assert calls == [{"include_input": False, "include_context": False, "include_url": False}]
    assert diagnostic["validation_issues"] == [{"field": "unknown", "issue": "unknown"}]
    assert SENTINEL not in json.dumps(diagnostic)


@pytest.mark.parametrize(
    ("kind", "issue"),
    [
        ("missing", "missing"),
        ("string_type", "type"),
        ("list_type", "type"),
        ("dict_type", "type"),
        ("model_type", "type"),
        ("model_attributes_type", "type"),
        ("enum", "enum"),
        ("literal_error", "enum"),
        ("string_pattern_mismatch", "pattern"),
        ("string_too_short", "length"),
        ("string_too_long", "length"),
        ("too_short", "length"),
        ("too_long", "length"),
        ("value_error", "value"),
        (SENTINEL, "unknown"),
        (None, "unknown"),
    ],
)
def test_only_reviewed_error_type_literals_are_projected(
    monkeypatch: pytest.MonkeyPatch, kind: object, issue: str
) -> None:
    class Unreadable:
        def __str__(self) -> str:
            raise AssertionError("message must not be read")

    record = {
        "loc": ("rationale",),
        "type": kind,
        "msg": Unreadable(),
        "input": Unreadable(),
        "ctx": Unreadable(),
        "url": Unreadable(),
    }
    monkeypatch.setattr(ValidationError, "errors", lambda self, **kwargs: [record])
    assert _verifier_diagnostic(_validation_error(("rationale",)))["validation_issues"] == [
        {"field": "rationale", "issue": issue}
    ]


def test_issues_are_deduplicated_sorted_bounded_across_eight_causes() -> None:
    locations: list[tuple[str | int, ...]] = [
        (name,)
        for name in sorted(VERIFIER_VALIDATION_FIELDS)
        if "." not in name and name not in {"unknown", "schema"}
    ]
    locations.extend(
        ("structured_criterion_results", 0, name)
        for name in ("criterion_id", "verdict", "command_ids")
    )
    error = _validation_error(*locations, *locations)
    issues = _verifier_diagnostic(error)["validation_issues"]
    assert len(issues) == 8
    assert issues == sorted(issues, key=lambda item: (item["field"], item["issue"]))
    assert len({(item["field"], item["issue"]) for item in issues}) == 8
    wrappers = [ValueError(SENTINEL) for _ in range(8)]
    for first, second in pairwise(wrappers):
        first.__cause__ = second
    wrappers[-1].__cause__ = error
    assert "validation_issues" not in _verifier_diagnostic(wrappers[0])
    wrappers[-2].__cause__ = error
    assert _verifier_diagnostic(wrappers[0])["validation_issues"] == issues


class _HostileString(str):
    def __eq__(self, other: object) -> bool:
        raise AssertionError("string subclasses must not be compared")

    def __hash__(self) -> int:
        return str.__hash__(self)


def test_location_subclasses_are_rejected_without_invoking_comparisons() -> None:
    class HostileIndex(int):
        def __lt__(self, other: object) -> bool:
            raise AssertionError("index subclasses must not be compared")

    class HostileTuple(tuple[object, ...]):
        def __len__(self) -> int:
            raise AssertionError("tuple subclasses must not be inspected")

    for location in (
        (_HostileString("verdict"),),
        ("criterion_results", HostileIndex(0)),
        ("structured_criterion_results", 0, _HostileString("verdict")),
        ("structured_criterion_results", 0, "command_ids", HostileIndex(0)),
        HostileTuple(("verdict",)),
    ):
        assert _verifier_field(location) == "unknown"


def test_real_error_count_above_bound_never_materializes_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = _validation_error(*[("rationale",)] * 33)
    assert error.error_count() == 33
    calls: list[bool] = []

    def forbidden(*args: object, **kwargs: object) -> Any:
        calls.append(True)
        raise AssertionError("records must not be materialized")

    monkeypatch.setattr(ValidationError, "errors", forbidden)
    assert _verifier_diagnostic(error)["validation_issues"] == [
        {"field": "unknown", "issue": "unknown"}
    ]
    assert calls == []


@pytest.mark.parametrize(
    "records",
    [
        None,
        (),
        [],
        [{"loc": ("verdict",), "type": "enum"}] * 2,
        [{_HostileString("loc"): ("verdict",), "type": "enum"}],
        [{"loc": ("verdict",), "type": "enum", **{str(index): None for index in range(33)}}],
    ],
)
def test_malformed_validation_records_fail_closed(
    monkeypatch: pytest.MonkeyPatch, records: object
) -> None:
    monkeypatch.setattr(ValidationError, "errors", lambda self, **kwargs: records)
    assert _verifier_diagnostic(_validation_error(("rationale",)))["validation_issues"] == [
        {"field": "unknown", "issue": "unknown"}
    ]


def test_error_type_subclass_is_not_compared(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        ValidationError,
        "errors",
        lambda self, **kwargs: [{"loc": ("verdict",), "type": _HostileString("enum")}],
    )
    assert _verifier_diagnostic(_validation_error(("verdict",)))["validation_issues"] == [
        {"field": "verdict", "issue": "unknown"}
    ]


def test_event_projection_rejects_hostile_envelopes_before_field_lookup() -> None:
    class HostileDict(dict[str, object]):
        def get(self, key: str, default: object = None) -> Any:
            raise AssertionError("mapping subclasses must not be queried")

        def __iter__(self) -> Any:
            raise AssertionError("mapping subclasses must not be iterated")

    valid = {"category": "output_schema", "cause_category": "schema_validation"}
    envelopes: tuple[Mapping[str, object], ...] = (
        HostileDict(runtime_diagnostic=valid),
        {_HostileString("runtime_diagnostic"): valid},
        {"runtime_diagnostic": HostileDict(valid)},
        {"runtime_diagnostic": {_HostileString("category"): "output_schema"}},
        {"runtime_diagnostic": {**valid, **{str(index): None for index in range(33)}}},
        {"runtime_diagnostic": valid, **{str(index): None for index in range(33)}},
    )
    for envelope in envelopes:
        assert runtime_diagnostic_payload(envelope) == {}


@pytest.mark.parametrize(
    "value",
    [
        None,
        {},
        [],
        [{"field": SENTINEL, "issue": "missing"}],
        [{"field": "verdict", "issue": SENTINEL}],
        [{"field": _HostileString("verdict"), "issue": "enum"}],
        [{"field": "verdict", "issue": _HostileString("enum")}],
        [{"field": "verdict", "issue": "enum"}] * 9,
    ],
)
def test_event_projection_rejects_malformed_optional_issues_without_replacing_failure(
    value: object,
) -> None:
    payload = {
        "category": "structured_output_after_side_effect",
        "cause_category": "schema_validation",
        "expected_output_contract": "verifier_verdict",
        "validation_issues": value,
    }
    projected = runtime_diagnostic_payload({"runtime_diagnostic": payload})
    assert projected == {
        "runtime_diagnostic": {
            key: val for key, val in payload.items() if key != "validation_issues"
        }
    }


def test_optional_event_projection_strips_extras_and_copies_only_known_pairs() -> None:
    issue: dict[str, Any] = {
        "field": "verdict",
        "issue": "enum",
        "msg": SENTINEL,
        "input": SENTINEL,
        SENTINEL: SENTINEL,
    }
    original: dict[str, Any] = {
        "category": "structured_output_after_side_effect",
        "cause_category": "schema_validation",
        "expected_output_contract": "verifier_verdict",
        "validation_issues": [issue, issue],
        "count": 999,
        "raw": SENTINEL,
    }
    projected = runtime_diagnostic_payload({"runtime_diagnostic": original})
    issue["field"] = SENTINEL
    assert projected["runtime_diagnostic"] == {
        "category": "structured_output_after_side_effect",
        "cause_category": "schema_validation",
        "expected_output_contract": "verifier_verdict",
        "validation_issues": [{"field": "verdict", "issue": "enum"}],
    }
    assert SENTINEL not in json.dumps(projected)
    for binding in (None, SENTINEL, _HostileString("verifier_verdict")):
        original["expected_output_contract"] = binding
        assert runtime_diagnostic_payload({"runtime_diagnostic": original}) == {
            "runtime_diagnostic": {
                "category": "structured_output_after_side_effect",
                "cause_category": "schema_validation",
            }
        }
