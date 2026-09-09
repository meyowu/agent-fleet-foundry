from __future__ import annotations

from importlib import resources

import pytest
from pydantic import ValidationError

from agent_fleet.domain.models import (
    AcceptanceCriterion,
    CriterionResult,
    ScopeDecision,
    VerifierVerdict,
)


def test_scope_descriptions_distinguish_requested_outcomes_from_delivery_types() -> None:
    properties = ScopeDecision.model_json_schema()["properties"]
    assert "Observable outcomes" in properties["acceptance_criteria"]["description"]
    assert "delivery/proof types" in properties["required_evidence"]["description"]
    assert "{} when unused, not null" in properties["role_selections"]["description"]
    assert properties["acceptance_criteria"]["minItems"] == 1
    assert properties["acceptance_criteria"]["maxItems"] == 128
    assert properties["required_evidence"]["minItems"] == 1
    assert properties["required_evidence"]["maxItems"] == 32
    assert properties["role_selections"]["type"] == "object"
    assert properties["role_selections"]["maxProperties"] == 4
    description = AcceptanceCriterion.model_json_schema()["properties"]["description"]
    assert "Observable task outcome" in description["description"]
    assert description["minLength"] == 1 and description["maxLength"] == 4096


@pytest.mark.parametrize("read_only", [False, True])
def test_guidance_does_not_ban_artifact_named_outcomes_or_change_direct_and_role_defaults(
    read_only: bool,
) -> None:
    proposal: dict[str, object] = {
        "normalized_goal": "Explain artifact behavior."
        if read_only
        else "Repair artifact behavior.",
        "change_kind": "read_only" if read_only else "code_change",
        "fleet_strategy": "direct" if read_only else "engineer_verifier",
        "allowed_paths": [] if read_only else ["src"],
        "forbidden_paths": [".git", ".fleet"],
        "acceptance_criteria": [
            {"criterion_id": "canonical_patch", "description": "The requested artifact behavior."}
        ],
        "required_evidence": ["control_plane_plan"]
        if read_only
        else ["canonical_patch", "command_evidence", "independent_verifier_verdict"],
    }
    decision = ScopeDecision.model_validate(proposal)
    assert decision.role_selections == {} and decision.writer_assignments == []
    assert decision.acceptance_criteria[0].criterion_id == "canonical_patch"
    assert ScopeDecision.model_validate({**proposal, "role_selections": {}}) == decision
    with pytest.raises(ValidationError):
        ScopeDecision.model_validate({**proposal, "role_selections": None})


def test_mapping_descriptions_preserve_schema_bounds_and_non_authoritative_empty_claims() -> None:
    properties = CriterionResult.model_json_schema()["properties"]
    receipt = properties["evidence_artifact_ids"]
    assert "content.command_evidence_artifact_id" in receipt["description"]
    assert "uniquely latest" in receipt["description"]
    assert receipt["maxItems"] == 64 and "minItems" not in receipt
    assert properties["command_ids"]["maxItems"] == 32
    assert "one-to-one" in properties["command_ids"]["description"]
    assert "relevant subset" in properties["command_ids"]["description"]
    # Existing schema admits incomplete claims; the unchanged evidence gate rejects them.
    claim = CriterionResult(
        criterion_id="behavior",
        verdict="pass",
        evidence_artifact_ids=[],
        command_ids=[],
        explanation="No proof was supplied.",
    )
    assert claim.command_ids == claim.evidence_artifact_ids == []
    verdict = VerifierVerdict.model_json_schema()["properties"]
    assert verdict["evidence_artifact_ids"]["maxItems"] == 256
    assert verdict["structured_criterion_results"]["default"] is None
    assert verdict["structured_criterion_results"]["anyOf"][0]["maxItems"] == 128


def test_packaged_prompts_explain_named_receipts_without_claiming_inspection_is_execution() -> None:
    prompts = resources.files("agent_fleet.adapters.runtime.prompts")
    cos = prompts.joinpath("cos.md").read_text()
    verifier = prompts.joinpath("verifier.md").read_text()
    assert "acceptance_criteria" in cos and "required_evidence" in cos
    assert "legitimate tasks\nabout artifact behavior" in cos
    assert "Direct read-only tasks retain" in cos
    for required in (
        "content.command_evidence_artifact_id",
        "content.transcript_artifact_id",
        "generic artifact_ids",
        "uniquely latest receipt",
        "earlier pass for a later failing or timed-out receipt",
        "same verification workspace and sandbox",
        "criterion_mapping_contract",
    ):
        assert required in verifier
