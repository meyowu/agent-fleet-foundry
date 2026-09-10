from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from agent_fleet.domain.models import ScopeDecision


@pytest.mark.parametrize("workflow", ["code-change", "engineer_verifier"])
def test_observed_nonparallel_assignment_shapes_still_fail_semantic_validation(
    workflow: str,
) -> None:
    # Synthetic equivalents of the two diagnosed responses, without provider data.
    proposal: dict[str, object] = {
        "normalized_goal": "Fix zero-division handling in the canary module.",
        "workflow": workflow,
        "change_kind": "code_change",
        "fleet_strategy": "engineer_verifier",
        "allowed_paths": ["src/canary_calc/core.py"],
        "forbidden_paths": [".git", ".fleet"],
        "acceptance_criteria": [{"criterion_id": "guard", "description": "Raise ValueError."}],
        "required_evidence": [
            "canonical_patch",
            "command_evidence",
            "independent_verifier_verdict",
        ],
        "writer_assignments": [
            {
                "node_id": role,
                "role_id": role,
                "goal": "Implement the guard." if role == "engineer" else "Verify the guard.",
                "scope": ["src/canary_calc/core.py"],
                "criterion_ids": ["guard"],
            }
            for role in ("engineer", "verifier")
        ],
    }
    with pytest.raises(
        ValidationError, match="only the parallel strategy accepts writer assignments"
    ):
        ScopeDecision.model_validate(proposal)
    corrected = deepcopy(proposal)
    corrected["writer_assignments"] = []
    decision = ScopeDecision.model_validate(corrected)
    assert decision.writer_assignments == []
    assert decision.workflow == workflow
    assert decision.fleet_strategy == "engineer_verifier"
    assert proposal["writer_assignments"]  # Validation does not silently repair untrusted input.


def test_scope_schema_explains_workflow_strategy_and_fixed_node_contracts() -> None:
    properties = ScopeDecision.model_json_schema()["properties"]
    assert "available_workflows" in properties["workflow"]["description"]
    assert "not a fleet strategy" in properties["workflow"]["description"]
    assert "control plane constructs" in properties["fleet_strategy"]["description"]
    description = properties["writer_assignments"]["description"]
    assert "Must be []" in description
    for strategy in (
        "direct",
        "single_engineer",
        "engineer_verifier",
        "research_architect_engineer_verifier",
    ):
        assert strategy in description
    assert "Verifier" in description and "never a writer" in description
