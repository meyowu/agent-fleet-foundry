from __future__ import annotations

import copy
import json

import pytest
from conftest import FleetHarness

from agent_fleet.adapters.runtime.fake import FakeRuntimeAdapter
from agent_fleet.domain.models import AgentInvocation, AgentInvocationResult, FakeScenario, Verdict


class ContradictoryPassRuntime(FakeRuntimeAdapter):
    async def invoke(self, request: AgentInvocation) -> AgentInvocationResult:
        result = await super().invoke(request)
        if request.role != "verifier":
            return result

        output = copy.deepcopy(result.output)
        verdict = output["verdict"]
        assert isinstance(verdict, dict)
        verdict["proof_gaps"] = ["Required adversarial evidence is unavailable."]
        verdict["required_repairs"] = ["Repair the verifier-detected defect."]
        verdict["regressions"] = ["Existing behavior regressed."]
        return AgentInvocationResult(output=output)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_verifier_negative_findings_are_preserved_and_block_pass(
    harness: FleetHarness,
) -> None:
    harness.container.workflow.runtime = ContradictoryPassRuntime()

    run = await harness.start(FakeScenario.SUCCESS)

    assert run.verified_complete is False
    assert run.assurance_verdict is Verdict.INCONCLUSIVE
    bundle = json.loads(
        harness.container.artifacts.read_text(run.evidence_bundle_artifact_id or "")
    )
    assert bundle["reported_verdict"] == "pass"
    assert bundle["verifier_required_repairs"] == ["Repair the verifier-detected defect."]
    assert bundle["verifier_regressions"] == ["Existing behavior regressed."]
    assert {
        (gap["code"], gap["description"], gap["required_strength"]) for gap in bundle["proof_gaps"]
    } >= {
        (
            "VERIFIER_REPORTED_PROOF_GAP",
            "Required adversarial evidence is unavailable.",
            "independently_verified",
        )
    }
    assert set(bundle["completion_decision"]["reason_codes"]) >= {
        "PROOF_GAPS_PRESENT",
        "VERIFIER_PASS_WITH_REQUIRED_REPAIRS",
        "VERIFIER_PASS_WITH_REGRESSIONS",
    }
