from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from pydantic import ValidationError
from test_evidence_gate import _authoritative_artifact_ids, _bundle

from agent_fleet.domain.evidence import (
    CompletionGate,
    EvidenceBundle,
    EvidenceStrength,
    assess_criterion_results,
)
from agent_fleet.domain.models import CriterionResult, SandboxSecurityLevel, Verdict


def _mapped_bundle() -> EvidenceBundle:
    bundle = _bundle()
    first = bundle.command_evidence[0]
    second = first.model_copy(
        update={
            "evidence_id": "art_" + "a1" * 16,
            "command_id": "project-lint",
        }
    )
    results = [
        CriterionResult(
            criterion_id=criterion_id,
            verdict=Verdict.PASS,
            evidence_artifact_ids=[command.evidence_id],
            command_ids=[command.command_id],
            explanation="Bound result.",
        )
        for criterion_id, command in [("behavior", first), ("quality", second)]
    ]
    return _resolve(
        bundle.model_copy(
            update={
                "command_evidence": [first, second],
                "verification_command_hashes": {
                    first.command_id: first.command_spec_sha256,
                    second.command_id: second.command_spec_sha256,
                },
                "verifier_evidence_artifact_ids": [first.evidence_id, second.evidence_id],
                "structured_criterion_results": results,
            }
        )
    )


def _resolve(bundle: EvidenceBundle) -> EvidenceBundle:
    assert bundle.structured_criterion_results is not None
    assessments, gaps = assess_criterion_results(
        bundle.structured_criterion_results,
        expected_criteria={"behavior", "quality"},
        commands=bundle.command_evidence,
        verifier_evidence_artifact_ids=bundle.verifier_evidence_artifact_ids,
        run_id=bundle.run_id,
        task_id=bundle.task_id,
        verifier_agent_instance_id=bundle.verifier_agent_instance_id,
        base_revision=bundle.base_revision,
        config_snapshot_sha256=bundle.config_snapshot_sha256,
        patch_sha256=bundle.patch_sha256,
        command_hashes=bundle.verification_command_hashes,
    )
    return bundle.model_copy(update={"criterion_assessments": assessments, "proof_gaps": gaps})


def _evaluate(bundle: EvidenceBundle) -> bool:
    return CompletionGate.evaluate(
        bundle,
        expected_criteria={"behavior", "quality"},
        authoritative_artifact_ids=_authoritative_artifact_ids(bundle),
    ).verified_complete


def test_two_criteria_resolve_to_their_own_exact_independent_evidence() -> None:
    bundle = _mapped_bundle()
    assert _evaluate(bundle)
    assert [item.evidence_artifact_ids for item in bundle.criterion_assessments] == [
        [bundle.command_evidence[0].evidence_id],
        [bundle.command_evidence[1].evidence_id],
    ]


@pytest.mark.parametrize(
    "case",
    [
        "missing",
        "empty",
        "duplicate_criterion",
        "unknown_criterion",
        "unknown_artifact",
        "duplicate_artifact",
        "duplicate_command",
        "wrong_command",
        "missing_command",
        "not_declared",
    ],
)
def test_invalid_or_incomplete_mappings_never_pass(case: str) -> None:
    bundle = _mapped_bundle()
    assert bundle.structured_criterion_results is not None
    results = list(bundle.structured_criterion_results)
    first = results[0]
    if case == "missing":
        results.pop()
    elif case == "empty":
        results = []
    elif case == "duplicate_criterion":
        results.append(first)
    elif case == "unknown_criterion":
        results.append(first.model_copy(update={"criterion_id": "unknown"}))
    elif case == "unknown_artifact":
        results[0] = first.model_copy(update={"evidence_artifact_ids": ["art_" + "ef" * 16]})
    elif case == "duplicate_artifact":
        results[0] = first.model_copy(
            update={
                "evidence_artifact_ids": first.evidence_artifact_ids * 2,
            }
        )
    elif case == "duplicate_command":
        results[0] = first.model_copy(update={"command_ids": first.command_ids * 2})
    elif case == "wrong_command":
        results[0] = first.model_copy(update={"command_ids": ["project-lint"]})
    elif case == "missing_command":
        results[0] = first.model_copy(update={"command_ids": []})
    elif case == "not_declared":
        bundle = bundle.model_copy(update={"verifier_evidence_artifact_ids": []})
    resolved = _resolve(bundle.model_copy(update={"structured_criterion_results": results}))
    assert not _evaluate(resolved)
    assert resolved.criterion_assessments[0].verdict is Verdict.INCONCLUSIVE
    assert resolved.proof_gaps


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("run_id", "run_" + "a" * 32),
        ("task_id", "task_" + "a" * 32),
        ("agent_instance_id", "agent_" + "a" * 32),
        ("principal_role", "engineer"),
        ("workflow_stage", "implementing"),
        ("workspace_id", None),
        ("sandbox_id", None),
        ("workspace_base_revision", "stale"),
        ("config_snapshot_sha256", "1" * 64),
        ("candidate_patch_sha256", "2" * 64),
        ("command_spec_sha256", "3" * 64),
        ("strength", EvidenceStrength.SIMULATED),
        ("sandbox_security_level", SandboxSecurityLevel.UNSAFE_HOST),
        ("workspace_mutated_during_execution", True),
        ("output_truncated", True),
    ],
)
def test_foreign_stale_unproven_or_mutated_command_cannot_prove_criterion(
    field: str,
    value: Any,
) -> None:
    bundle = _mapped_bundle()
    commands = list(bundle.command_evidence)
    commands[0] = commands[0].model_copy(update={field: value})
    resolved = _resolve(bundle.model_copy(update={"command_evidence": commands}))
    assert resolved.criterion_assessments[0].verdict is Verdict.INCONCLUSIVE
    assert resolved.criterion_assessments[1].verdict is Verdict.PASS
    assert not _evaluate(resolved)


def test_failed_command_does_not_blindly_fail_unrelated_criterion() -> None:
    bundle = _mapped_bundle()
    commands = list(bundle.command_evidence)
    commands[0] = commands[0].model_copy(update={"exit_code": 1})
    resolved = _resolve(bundle.model_copy(update={"command_evidence": commands}))
    assert [item.verdict for item in resolved.criterion_assessments] == [Verdict.FAIL, Verdict.PASS]
    assert not _evaluate(resolved)


@pytest.mark.parametrize("ambiguous", [False, True])
def test_repeated_command_requires_unique_latest_artifact(ambiguous: bool) -> None:
    bundle = _mapped_bundle()
    first = bundle.command_evidence[0]
    repeated = first.model_copy(
        update={
            "evidence_id": "art_" + "b1" * 16,
            "completed_at": first.completed_at + timedelta(seconds=0 if ambiguous else 1),
        }
    )
    bundle = bundle.model_copy(
        update={
            "command_evidence": [*bundle.command_evidence, repeated],
            "verifier_evidence_artifact_ids": [
                *bundle.verifier_evidence_artifact_ids,
                repeated.evidence_id,
            ],
        }
    )
    assert not _evaluate(_resolve(bundle))
    assert bundle.structured_criterion_results is not None
    results = list(bundle.structured_criterion_results)
    results[0] = results[0].model_copy(update={"evidence_artifact_ids": [repeated.evidence_id]})
    resolved = _resolve(bundle.model_copy(update={"structured_criterion_results": results}))
    assert _evaluate(resolved) is not ambiguous


def test_gate_recomputes_mapping_instead_of_trusting_copied_pass_assessments() -> None:
    bundle = _mapped_bundle()
    assert bundle.structured_criterion_results is not None
    stale = bundle.structured_criterion_results[0].model_copy(
        update={
            "evidence_artifact_ids": ["art_" + "ef" * 16],
        }
    )
    forged = bundle.model_copy(
        update={
            "structured_criterion_results": [stale, bundle.structured_criterion_results[1]],
        }
    )
    assert all(item.verdict is Verdict.PASS for item in forged.criterion_assessments)
    assert not _evaluate(forged)
    assert not _evaluate(bundle.model_copy(update={"structured_criterion_results": None}))


def test_typed_criterion_reference_bounds() -> None:
    bundle = _mapped_bundle()
    assert bundle.structured_criterion_results is not None
    first = bundle.structured_criterion_results[0]
    with pytest.raises(ValidationError):
        CriterionResult.model_validate(
            {
                **first.model_dump(),
                "evidence_artifact_ids": first.evidence_artifact_ids * 65,
            }
        )
