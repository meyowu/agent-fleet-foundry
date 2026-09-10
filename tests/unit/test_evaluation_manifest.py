from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, tzinfo
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import ValidationError

from agent_fleet.domain.evaluation import EvaluationManifest


def load_manifest() -> EvaluationManifest:
    source = Path(__file__).parents[1] / "fixtures/evaluations/domain-cohort-v1.json"
    return EvaluationManifest.model_validate_json(source.read_text())


def test_synthetic_manifest_has_fixed_24_task_36_attempt_design() -> None:
    manifest = load_manifest()
    assert len(manifest.repositories) == 6
    assert len(manifest.cases) == 28
    assert sum(case.auxiliary_purpose is None for case in manifest.cases) == 24
    assert len(manifest.slots) == manifest.budget.max_attempts == 36
    assert sum(slot.repetition > 0 for slot in manifest.slots) == 8
    assert manifest.sha256 == load_manifest().sha256
    assert "sha256" not in manifest.model_dump()
    assert EvaluationManifest.model_validate_json(manifest.model_dump_json()) == manifest


def test_manifest_nested_values_are_deeply_immutable() -> None:
    manifest = load_manifest()
    with pytest.raises(ValidationError):
        cast(Any, manifest).revision = 1
    with pytest.raises(ValidationError):
        cast(Any, manifest.cases[0].run_budget).max_total_tokens = 1
    with pytest.raises(ValidationError):
        cast(Any, manifest.cases[0].commands[0]).command_id = "replacement"
    with pytest.raises(TypeError):
        cast(Any, manifest.cases)[0] = manifest.cases[1]
    with pytest.raises(TypeError):
        cast(Any, manifest.cases[0].allowed_paths)[0] = "other"
    with pytest.raises(ValidationError):
        EvaluationManifest.model_validate(manifest.model_dump(mode="json"))


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate_repository",
        "duplicate_case",
        "unknown_repository",
        "cross_cohort_source",
        "duplicate_source_alias",
        "unknown_slot",
        "duplicate_slot",
        "missing_first",
        "missing_case_slots",
        "auxiliary_repeat",
        "attempt_ceiling",
        "case_budget",
        "boolean_budget",
        "float_budget",
        "string_budget",
        "boolean_repetition",
        "revision",
        "caller_hash",
        "naive_time",
        "non_utc",
        "path_escape",
        "path_absolute",
        "path_case",
        "blank_requirement",
        "missing_evidence",
        "readonly_patch",
        "duplicate_command",
    ],
)
def test_manifest_rejects_invalid_preregistration(mutation: str) -> None:
    value = load_manifest().model_dump(mode="json")
    if mutation == "duplicate_repository":
        value["repositories"][1] = value["repositories"][0]
    elif mutation == "duplicate_case":
        value["cases"][1] = value["cases"][0]
    elif mutation == "unknown_repository":
        value["cases"][0]["repository_id"] = "missing"
    elif mutation == "cross_cohort_source":
        value["repositories"][3]["source_sha256"] = value["repositories"][0]["source_sha256"]
    elif mutation == "duplicate_source_alias":
        value["repositories"][1].update(
            {
                key: value["repositories"][0][key]
                for key in ("source_sha256", "commit_sha", "cohort")
            }
        )
    elif mutation == "unknown_slot":
        value["slots"][0]["case_id"] = "missing"
    elif mutation == "duplicate_slot":
        value["slots"][1] = value["slots"][0]
    elif mutation == "missing_first":
        value["slots"][5]["repetition"] = 1
    elif mutation == "missing_case_slots":
        value["slots"] = [
            slot for slot in value["slots"] if slot["case_id"] != value["cases"][5]["case_id"]
        ]
    elif mutation == "auxiliary_repeat":
        value["slots"].append({"case_id": value["cases"][-1]["case_id"], "repetition": 1})
        value["budget"]["max_attempts"] += 1
    elif mutation == "attempt_ceiling":
        value["budget"]["max_attempts"] -= 1
    elif mutation == "case_budget":
        value["cases"][0]["run_budget"]["max_model_requests"] = 1000
    elif mutation in {"boolean_budget", "float_budget", "string_budget"}:
        value["budget"]["max_model_requests"] = {
            "boolean_budget": True,
            "float_budget": 1.0,
            "string_budget": "1",
        }[mutation]
    elif mutation == "boolean_repetition":
        value["slots"][0]["repetition"] = False
    elif mutation == "revision":
        value["revision"] = 1
    elif mutation == "caller_hash":
        value["sha256"] = "f" * 64
    elif mutation == "naive_time":
        value["frozen_at"] = "2026-01-01T00:00:00"
    elif mutation == "non_utc":
        value["frozen_at"] = "2026-01-01T01:00:00+01:00"
    elif mutation in {"path_escape", "path_absolute", "path_case"}:
        value["cases"][0]["allowed_paths"] = {
            "path_escape": ["../src"],
            "path_absolute": ["/src"],
            "path_case": ["src", "SRC"],
        }[mutation]
    elif mutation == "blank_requirement":
        value["cases"][0]["requirement"] = " "
    elif mutation == "missing_evidence":
        value["cases"][0]["required_evidence"].remove("post_apply")
    elif mutation == "readonly_patch":
        value["cases"][3]["required_evidence"].append("patch")
    elif mutation == "duplicate_command":
        value["cases"][0]["commands"] *= 2
    with pytest.raises(ValidationError):
        EvaluationManifest.model_validate_json(json.dumps(value))


def test_manifest_enforces_aggregate_utf8_byte_ceiling() -> None:
    value = load_manifest().model_dump(mode="json")
    for case in value["cases"][:4]:
        case["allowed_paths"] = [f"src/{index}/" + "x" * 3000 for index in range(128)]
    with pytest.raises(ValidationError, match="encoded byte limit"):
        EvaluationManifest.model_validate_json(json.dumps(value))


def test_revision_and_content_changes_have_distinct_derived_digests() -> None:
    manifest = load_manifest()
    value = manifest.model_dump(mode="json")
    value.update(revision=1, previous_sha256=manifest.sha256)
    revised = EvaluationManifest.model_validate_json(json.dumps(value))
    assert revised.sha256 != manifest.sha256
    value["cases"][0]["requirement"] += " Changed before dispatch."
    assert EvaluationManifest.model_validate_json(json.dumps(value)).sha256 != revised.sha256


def test_mutable_caller_timezone_cannot_change_frozen_manifest_hash() -> None:
    class MutableOffset(tzinfo):
        offset = timedelta(0)

        def utcoffset(self, dt: datetime | None) -> timedelta:
            return self.offset

        def dst(self, dt: datetime | None) -> timedelta:
            return timedelta(0)

        def tzname(self, dt: datetime | None) -> str:
            return "mutable"

    zone = MutableOffset()
    value = load_manifest().model_dump()
    value["frozen_at"] = datetime(2026, 1, 1, tzinfo=zone)
    manifest = EvaluationManifest.model_validate(value)
    before = manifest.sha256
    zone.offset = timedelta(hours=1)
    assert manifest.frozen_at.tzinfo is UTC
    assert manifest.sha256 == before
