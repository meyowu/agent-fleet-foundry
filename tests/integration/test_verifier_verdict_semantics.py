from __future__ import annotations

import json

import pytest
from conftest import FleetHarness

from agent_fleet.adapters.runtime.fake import FakeRuntimeAdapter
from agent_fleet.application.runtime import RuntimeRegistry
from agent_fleet.domain.models import (
    AgentInvocation,
    AgentInvocationResult,
    AgentRole,
    FakeScenario,
    Verdict,
    VerifierVerdict,
)
from agent_fleet.ports.runtime import RuntimeInvocationServices


class ContradictoryPassRuntime(FakeRuntimeAdapter):
    async def invoke(
        self,
        request: AgentInvocation,
        services: RuntimeInvocationServices,
    ) -> AgentInvocationResult:
        result = await super().invoke(request, services)
        if request.role != AgentRole.VERIFIER:
            return result

        assert isinstance(result.output, VerifierVerdict)
        output = VerifierVerdict.model_validate(
            {
                **result.output.model_dump(mode="json"),
                "proof_gaps": ["Required adversarial evidence is unavailable."],
                "required_repairs": ["Repair the verifier-detected defect."],
                "regressions": ["Existing behavior regressed."],
            }
        )
        return AgentInvocationResult(
            output=output,
            usage=result.usage,
            checkpoint_ref=result.checkpoint_ref,
            provider_metadata=result.provider_metadata,
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_verifier_negative_findings_are_preserved_and_block_pass(
    harness: FleetHarness,
) -> None:
    harness.container.workflow.runtimes = RuntimeRegistry({"fake": ContradictoryPassRuntime()})

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
