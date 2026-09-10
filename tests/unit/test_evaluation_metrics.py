from __future__ import annotations

import json
from typing import Any, cast

import pytest
from pydantic import ValidationError
from test_evaluation_manifest import load_manifest
from test_outcomes import outcome_for

from agent_fleet.domain.evaluation_metrics import EvaluationReport, evaluate_records
from agent_fleet.domain.outcomes import OutcomeKind, OutcomeRecord


def test_no_records_preserves_fixed_denominators_without_inventing_zero_success_rate() -> None:
    report = evaluate_records(load_manifest(), ())
    assert report.first_round.planned == 24 and report.first_round.observed == 0
    assert report.first_round.success_percentage is None
    assert report.development.planned == report.sealed_holdout.planned == 12
    assert report.repeats.planned == 8 and report.auxiliary.planned == 4
    assert sum(item.first_round.planned for item in report.repositories) == 24
    assert len(report.slots) == 36 and {item.result for item in report.slots} == {"missing"}
    assert report.assurance == "structural_only" and report.kr_status == "not_evaluated"
    assert report.costs == ()
    assert report.coverage.planned_slots == report.coverage.missing_outcomes == 36
    assert report.coverage.recorded_outcomes == 0
    assert not report.coverage.usage_complete and not report.coverage.cost_complete


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
def test_failed_or_unknown_observation_keeps_full_denominator(result: OutcomeKind) -> None:
    manifest = load_manifest()
    report = evaluate_records(manifest, (outcome_for(manifest, result=result),))
    assert report.first_round.observed == 1 and report.first_round.successful == 0
    assert report.first_round.success_percentage == 0.0
    assert {item.result: item.count for item in report.first_round.outcomes} == {
        result: 1,
        "missing": 23,
    }


def test_repeated_success_cannot_replace_failed_first_round_or_raise_sample_size() -> None:
    manifest = load_manifest()
    first = outcome_for(manifest, result="functional_failure")
    repeat = outcome_for(manifest, 24)
    auxiliary = outcome_for(manifest, 32)
    report = evaluate_records(manifest, (repeat, auxiliary, first))
    assert report.first_round.planned == 24 and report.first_round.successful == 0
    assert report.repeats.planned == 8 and report.repeats.successful == 1
    assert report.auxiliary.planned == 4 and report.auxiliary.successful == 1
    assert report.usage.input_tokens_lower_bound == 300
    assert (
        report.model_dump_json()
        == evaluate_records(manifest, (first, repeat, auxiliary)).model_dump_json()
    )


def test_explicit_not_run_differs_from_missing_and_does_not_become_measured() -> None:
    manifest = load_manifest()
    report = evaluate_records(manifest, (outcome_for(manifest, result="not_run"),))
    assert report.first_round.observed == 0 and report.first_round.success_percentage is None
    assert {item.result: item.count for item in report.first_round.outcomes} == {
        "not_run": 1,
        "missing": 23,
    }


def test_cos_failure_with_run_but_no_task_stays_in_denominator_and_usage() -> None:
    manifest = load_manifest()
    value = outcome_for(manifest, result="provider_failure").model_dump(mode="json")
    value.update(task_id=None, product_status="failed", product_verdict=None, artifacts=[])
    value["usage"][0].update(segment_id="cos", model_requests=1, tool_calls=0)
    record = OutcomeRecord.model_validate_json(json.dumps(value))
    report = evaluate_records(manifest, (record,))
    assert record.task_id is None and record.root_run_id is not None
    assert report.first_round.planned == 24 and report.first_round.observed == 1
    assert report.first_round.successful == 0 and report.first_round.success_percentage == 0.0
    assert report.usage.model_requests_lower_bound == 1
    assert report.usage.input_tokens_lower_bound == 100
    assert {item.result: item.count for item in report.first_round.outcomes} == {
        "provider_failure": 1,
        "missing": 23,
    }


def test_readonly_success_and_product_disagreement_do_not_fabricate_patch_or_kr_pass() -> None:
    manifest = load_manifest()
    record = outcome_for(manifest, 3)
    assert record.apply_status == "not_applicable" and record.product_verified_complete is False
    report = evaluate_records(manifest, (record,))
    assert report.first_round.successful == 1
    assert report.first_round.success_percentage == 4.166667
    assert report.kr_status == "not_evaluated" and report.assurance == "structural_only"


@pytest.mark.parametrize(
    "field",
    [
        "manifest_sha256",
        "campaign_id",
        "case_id",
        "repetition",
        "configuration_sha256",
        "oracle_sha256",
        "scoring_sha256",
    ],
)
def test_cross_contract_or_unregistered_record_is_rejected(field: str) -> None:
    manifest = load_manifest()
    value = outcome_for(manifest, 5).model_dump(mode="json")
    value[field] = (
        "campaign_" + "f" * 32
        if field == "campaign_id"
        else "missing"
        if field == "case_id"
        else 1
        if field == "repetition"
        else "f" * 64
    )
    with pytest.raises(ValueError):
        evaluate_records(manifest, (OutcomeRecord.model_validate_json(json.dumps(value)),))


@pytest.mark.parametrize(
    "collision", ["slot", "outcome_id", "attempt_id", "root_run_id", "task_id"]
)
def test_duplicates_cannot_increase_reported_success(collision: str) -> None:
    manifest = load_manifest()
    first = outcome_for(manifest)
    value = outcome_for(manifest, 1).model_dump(mode="json")
    if collision == "slot":
        value.update(case_id=first.case_id, repetition=first.repetition)
    else:
        value[collision] = getattr(first, collision)
        if collision == "root_run_id":
            for ref in value["artifacts"]:
                ref["run_id"] = first.root_run_id
    with pytest.raises(ValueError):
        evaluate_records(manifest, (first, OutcomeRecord.model_validate_json(json.dumps(value))))


@pytest.mark.parametrize(
    "category", ["source_baseline", "patch", "verification", "apply", "post_apply"]
)
def test_success_without_frozen_required_evidence_is_rejected(category: str) -> None:
    manifest = load_manifest()
    value = outcome_for(manifest).model_dump(mode="json")
    value["artifacts"] = [ref for ref in value["artifacts"] if ref["category"] != category]
    record = OutcomeRecord.model_validate_json(json.dumps(value))
    with pytest.raises(ValueError, match="required evidence"):
        evaluate_records(manifest, (record,))


def test_success_without_explicit_application_is_not_promoted() -> None:
    manifest = load_manifest()
    record = outcome_for(manifest).model_copy(update={"apply_status": "not_applied"})
    with pytest.raises(ValueError, match="explicit application"):
        evaluate_records(manifest, (record,))


def test_public_boundary_revalidates_copy_and_construct_bypasses() -> None:
    manifest = load_manifest()
    record = outcome_for(manifest)
    with pytest.raises(ValidationError):
        evaluate_records(
            manifest.model_copy(update={"slots": (*manifest.slots, manifest.slots[0])}), ()
        )
    with pytest.raises(ValidationError):
        evaluate_records(manifest, (record.model_copy(update={"repetition": True}),))
    with pytest.raises(ValidationError):
        evaluate_records(manifest, (record.model_copy(update={"unexpected": "not admitted"}),))
    with pytest.raises(ValidationError):
        evaluate_records(
            manifest.model_copy(
                update={"budget": manifest.budget.model_copy(update={"max_model_requests": True})}
            ),
            (),
        )
    forged = OutcomeRecord.model_construct(
        **{**record.model_dump(), "unexpected": "not admitted", "artifacts": ()}
    )
    with pytest.raises(ValidationError):
        evaluate_records(manifest, (forged,))


def test_outcome_before_preregistration_is_rejected() -> None:
    manifest = load_manifest()
    value = outcome_for(manifest).model_dump(mode="json")
    value["recorded_at"] = "2025-12-31T23:59:59Z"
    with pytest.raises(ValueError, match="predate"):
        evaluate_records(manifest, (OutcomeRecord.model_validate_json(json.dumps(value)),))


def test_artifact_identity_cannot_change_between_outcomes() -> None:
    manifest = load_manifest()
    first = outcome_for(manifest)
    value = outcome_for(manifest, 1).model_dump(mode="json")
    value["artifacts"][0]["artifact_id"] = first.artifacts[0].artifact_id
    with pytest.raises(ValueError, match="artifact identity"):
        evaluate_records(manifest, (first, OutcomeRecord.model_validate_json(json.dumps(value))))


def test_exact_shared_nonrun_diagnostic_is_not_counted_as_execution() -> None:
    manifest = load_manifest()
    records = []
    for index in range(2):
        value = outcome_for(manifest, index, result="not_run").model_dump(mode="json")
        value["artifacts"] = [
            {
                "artifact_id": "art_" + "f" * 32,
                "category": "diagnostic",
                "run_id": None,
                "sha256": "a" * 64,
            }
        ]
        records.append(OutcomeRecord.model_validate_json(json.dumps(value)))
    report = evaluate_records(manifest, tuple(records))
    assert report.first_round.observed == 0 and report.first_round.successful == 0
    changed = records[1].model_dump(mode="json")
    changed["artifacts"][0]["sha256"] = "b" * 64
    with pytest.raises(ValueError, match="artifact identity"):
        evaluate_records(
            manifest, (records[0], OutcomeRecord.model_validate_json(json.dumps(changed)))
        )


def test_partial_usage_cost_currencies_and_unknowns_remain_separate() -> None:
    manifest = load_manifest()
    first = outcome_for(manifest)
    second = outcome_for(manifest, 1)
    third = outcome_for(manifest, 2)
    value = second.model_dump(mode="json")
    value.update(reported_cost_microunits=0, currency="USD")
    value["usage"][0].update(input_tokens=None, unknown_requests=1)
    second = OutcomeRecord.model_validate_json(json.dumps(value))
    value = third.model_dump(mode="json")
    value.update(reported_cost_microunits=7, currency="EUR", usage=[])
    third = OutcomeRecord.model_validate_json(json.dumps(value))
    report = evaluate_records(manifest, (first, second, third))
    assert report.usage.input_tokens_lower_bound == 100
    assert report.usage.unknown_requests == report.usage.unreported_segments == 1
    assert report.usage.records_without_usage == 1
    assert report.records_without_cost == 1
    assert report.coverage.recorded_outcomes == 3 and report.coverage.missing_outcomes == 33
    assert not report.coverage.usage_complete and not report.coverage.cost_complete
    assert [(cost.currency, cost.microunits_lower_bound) for cost in report.costs] == [
        ("EUR", 7),
        ("USD", 0),
    ]


def test_reports_remain_frozen_and_recomputation_byte_stable() -> None:
    manifest = load_manifest()
    records = tuple(outcome_for(manifest, index) for index in range(36))
    report = evaluate_records(manifest, records)
    assert report.first_round.successful == 24 and report.first_round.success_percentage == 100.0
    assert (
        report.model_dump_json()
        == evaluate_records(manifest, tuple(reversed(records))).model_dump_json()
    )
    assert report.kr_status == "not_evaluated"
    assert report.coverage.usage_complete and not report.coverage.cost_complete
    with pytest.raises(ValidationError):
        cast(Any, report.first_round).successful = 0


def test_report_aggregate_can_represent_every_valid_large_observation_without_overflow() -> None:
    manifest = load_manifest()
    records = []
    for index in range(2):
        value = outcome_for(manifest, index).model_dump(mode="json")
        value["usage"][0]["input_tokens"] = 2**63 - 1
        value.update(reported_cost_microunits=2**63 - 1, currency="USD")
        records.append(OutcomeRecord.model_validate_json(json.dumps(value)))
    report = evaluate_records(manifest, tuple(records))
    assert report.usage.input_tokens_lower_bound == 2 * (2**63 - 1)
    assert report.costs[0].microunits_lower_bound == 2 * (2**63 - 1)


@pytest.mark.parametrize(
    "mutation",
    [
        "success_over_planned",
        "unobserved_percentage",
        "duplicate_bin",
        "duplicate_slot",
        "duplicate_repository",
        "duplicate_currency",
        "missing_coverage",
        "false_complete",
        "wrong_group",
        "wrong_cohort",
        "first_as_repeat",
        "repeat_without_first",
    ],
)
def test_public_report_rejects_incoherent_or_duplicate_statistics(mutation: str) -> None:
    manifest = load_manifest()
    report = evaluate_records(manifest, ())
    value = report.model_dump(mode="json")
    if mutation == "success_over_planned":
        value["first_round"]["successful"] = 25
    elif mutation == "unobserved_percentage":
        value["first_round"]["success_percentage"] = 100.0
    elif mutation == "duplicate_bin":
        value["first_round"]["outcomes"] *= 2
    elif mutation == "duplicate_slot":
        value["slots"][1] = value["slots"][0]
    elif mutation == "duplicate_repository":
        value["repositories"][1] = value["repositories"][0]
    elif mutation == "duplicate_currency":
        value["costs"] = [
            {"currency": "USD", "microunits_lower_bound": 0, "reported_records": 1}
        ] * 2
    elif mutation == "missing_coverage":
        value["coverage"]["missing_outcomes"] = 0
    elif mutation == "false_complete":
        value["coverage"]["cost_complete"] = True
    elif mutation == "wrong_group":
        value["slots"][0]["group"] = "repeat"
    elif mutation == "wrong_cohort":
        value["sealed_holdout"] = value["repeats"]
    elif mutation == "first_as_repeat":
        value["slots"][0]["repetition"] = 2
    elif mutation == "repeat_without_first":
        next(slot for slot in value["slots"] if slot["repetition"] == 2)["case_id"] = (
            "missing_first"
        )
    with pytest.raises(ValidationError):
        EvaluationReport.model_validate_json(json.dumps(value))
