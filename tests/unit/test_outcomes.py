from __future__ import annotations

import json
from typing import Any, cast

import pytest
from pydantic import ValidationError
from test_evaluation_manifest import load_manifest

from agent_fleet.domain.evaluation import EvaluationManifest
from agent_fleet.domain.outcomes import OutcomeKind, OutcomeRecord


def outcome_for(
    manifest: EvaluationManifest,
    slot_index: int = 0,
    result: OutcomeKind = "verified_success",
) -> OutcomeRecord:
    slot = manifest.slots[slot_index]
    case = next(case for case in manifest.cases if case.case_id == slot.case_id)
    suffix = f"{slot_index + 1:032x}"
    run_id = "run_" + suffix
    executed = result != "not_run"
    return OutcomeRecord.model_validate_json(
        json.dumps(
            {
                "outcome_id": "outcome_" + suffix,
                "campaign_id": manifest.campaign_id,
                "manifest_sha256": manifest.sha256,
                "case_id": case.case_id,
                "repetition": slot.repetition,
                "attempt_id": "attempt_" + suffix,
                "root_run_id": run_id if executed else None,
                "task_id": "task_" + suffix if executed else None,
                "recorded_at": "2026-01-01T00:01:00Z",
                "configuration_sha256": case.configuration_sha256,
                "oracle_sha256": case.oracle_sha256,
                "scoring_sha256": case.scoring_sha256,
                "product_status": "ready_for_review" if executed else None,
                "product_verdict": "pass" if executed else None,
                "product_verified_complete": False if executed else None,
                "external_result": result,
                "apply_status": "not_applicable"
                if case.task_kind == "read_only"
                else "applied"
                if result == "verified_success"
                else "not_applied",
                "artifacts": [
                    {
                        "artifact_id": f"art_{slot_index * 16 + index + 1:032x}",
                        "category": category,
                        "run_id": run_id,
                        "sha256": f"{index + 1:064x}",
                    }
                    for index, category in enumerate(case.required_evidence)
                ]
                if executed
                else [],
                "usage": [
                    {
                        "segment_id": "all_roles",
                        "model_requests": 2,
                        "tool_calls": 3,
                        "input_tokens": 100,
                        "output_tokens": 20,
                        "active_milliseconds": 50,
                        "unknown_requests": 0,
                    }
                ]
                if executed
                else [],
            }
        )
    )


def test_outcome_preserves_product_external_acceptance_cost_and_usage_axes() -> None:
    outcome = outcome_for(load_manifest())
    assert outcome.product_verified_complete is False
    assert outcome.external_result == "verified_success"
    assert outcome.user_acceptance == "not_observed"
    assert outcome.reported_cost_microunits is None and outcome.currency is None
    assert OutcomeRecord.model_validate_json(outcome.model_dump_json()) == outcome
    with pytest.raises(ValidationError):
        cast(Any, outcome).external_result = "functional_failure"
    with pytest.raises(ValidationError):
        cast(Any, outcome.artifacts[0]).sha256 = "f" * 64
    with pytest.raises(ValidationError):
        cast(Any, outcome.usage[0]).model_requests = 0
    with pytest.raises(TypeError):
        cast(Any, outcome.artifacts)[0] = outcome.artifacts[1]


@pytest.mark.parametrize(
    "result", ["environment_failure", "provider_failure", "not_run", "dispatch_unknown"]
)
def test_preflight_outcome_can_exist_without_fabricated_run(result: OutcomeKind) -> None:
    value = outcome_for(load_manifest(), result="not_run").model_dump(mode="json")
    value["external_result"] = result
    outcome = OutcomeRecord.model_validate_json(json.dumps(value))
    assert outcome.root_run_id is outcome.task_id is None
    assert outcome.product_status is None and outcome.artifacts == ()


@pytest.mark.parametrize(
    "result",
    [
        "functional_failure",
        "environment_failure",
        "provider_failure",
        "budget_exhausted",
        "timeout",
        "cancelled",
        "inconclusive",
        "dispatch_unknown",
    ],
)
def test_cos_failure_retains_persisted_run_without_inventing_task(result: OutcomeKind) -> None:
    value = outcome_for(load_manifest(), result=result).model_dump(mode="json")
    value.update(task_id=None, product_status="failed", product_verdict=None)
    value["artifacts"] = [ref for ref in value["artifacts"] if ref["category"] == "cleanup"]
    value["usage"][0].update(segment_id="cos", model_requests=1, tool_calls=0)
    outcome = OutcomeRecord.model_validate_json(json.dumps(value))
    assert outcome.root_run_id is not None and outcome.task_id is None
    assert outcome.product_status is not None and outcome.product_status.value == "failed"
    assert outcome.product_verdict is None and outcome.product_verified_complete is False
    assert outcome.usage[0].segment_id == "cos" and outcome.usage[0].model_requests == 1
    assert OutcomeRecord.model_validate_json(outcome.model_dump_json()) == outcome


@pytest.mark.parametrize(
    "mutation",
    [
        "success_without_task",
        "task_without_run",
        "false_product",
        "success_without_run",
        "foreign_artifact",
        "duplicate_artifact",
        "duplicate_usage",
        "missing_oracle",
        "missing_cleanup",
        "cost_without_currency",
        "currency_without_cost",
        "boolean_usage",
        "negative_cost",
        "non_utc",
    ],
)
def test_invalid_outcome_observations_are_rejected(mutation: str) -> None:
    value = outcome_for(load_manifest()).model_dump(mode="json")
    if mutation == "success_without_task":
        value["task_id"] = None
    elif mutation == "task_without_run":
        value.update(
            root_run_id=None,
            product_status=None,
            product_verdict=None,
            product_verified_complete=None,
            external_result="provider_failure",
            artifacts=[],
        )
    elif mutation in {"false_product", "success_without_run"}:
        value.update(root_run_id=None, task_id=None, artifacts=[])
        if mutation == "success_without_run":
            value.update(product_status=None, product_verdict=None, product_verified_complete=None)
    elif mutation == "foreign_artifact":
        value["artifacts"][0]["run_id"] = "run_" + "f" * 32
    elif mutation == "duplicate_artifact":
        value["artifacts"].append(value["artifacts"][0])
    elif mutation == "duplicate_usage":
        value["usage"] *= 2
    elif mutation in {"missing_oracle", "missing_cleanup"}:
        value["artifacts"] = [
            ref
            for ref in value["artifacts"]
            if ref["category"] != mutation.removeprefix("missing_")
        ]
    elif mutation == "cost_without_currency":
        value["reported_cost_microunits"] = 0
    elif mutation == "currency_without_cost":
        value["currency"] = "USD"
    elif mutation == "boolean_usage":
        value["usage"][0]["model_requests"] = True
    elif mutation == "negative_cost":
        value.update(reported_cost_microunits=-1, currency="USD")
    elif mutation == "non_utc":
        value["recorded_at"] = "2026-01-01T01:01:00+01:00"
    with pytest.raises(ValidationError):
        OutcomeRecord.model_validate_json(json.dumps(value))


def test_reported_zero_cost_is_distinct_from_unknown_cost() -> None:
    value = outcome_for(load_manifest()).model_dump(mode="json")
    value.update(reported_cost_microunits=0, currency="USD")
    outcome = OutcomeRecord.model_validate_json(json.dumps(value))
    assert outcome.reported_cost_microunits == 0 and outcome.currency == "USD"
    value["usage"][0].update(input_tokens=None, unknown_requests=1)
    unknown = OutcomeRecord.model_validate_json(json.dumps(value))
    assert unknown.usage[0].input_tokens is None and unknown.usage[0].unknown_requests == 1


@pytest.mark.parametrize(
    "contradiction",
    [
        "model_requests",
        "tool_calls",
        "input_tokens",
        "output_tokens",
        "unknown_requests",
        "cost",
        "receipt",
    ],
)
def test_not_run_rejects_execution_observations(contradiction: str) -> None:
    value = outcome_for(load_manifest(), result="not_run").model_dump(mode="json")
    if contradiction == "cost":
        value.update(reported_cost_microunits=1, currency="USD")
    elif contradiction == "receipt":
        value["artifacts"] = [
            {
                "artifact_id": "art_" + "f" * 32,
                "category": "verification",
                "run_id": None,
                "sha256": "a" * 64,
            }
        ]
    else:
        value["usage"] = [{"segment_id": "not_run", contradiction: 1}]
    with pytest.raises(ValidationError, match="not_run"):
        OutcomeRecord.model_validate_json(json.dumps(value))
