from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import FleetHarness

from agent_fleet.domain.models import RunStatus, Workspace


@pytest.mark.integration
@pytest.mark.asyncio
async def test_detected_verifier_workspace_mutation_is_bound_into_completion_evidence(
    harness: FleetHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_fingerprint = harness.container.repository.workspace_status_fingerprint
    fingerprint_calls = 0

    def mutate_before_final_fingerprint(workspace: Workspace) -> str:
        nonlocal fingerprint_calls
        fingerprint_calls += 1
        if fingerprint_calls == 2:
            (Path(workspace.path) / "verifier-untrusted-note.txt").write_text(
                "This verifier mutation must never support completion.\n",
                encoding="utf-8",
            )
        return original_fingerprint(workspace)

    monkeypatch.setattr(
        harness.container.repository,
        "workspace_status_fingerprint",
        mutate_before_final_fingerprint,
    )

    run = await harness.start()

    assert fingerprint_calls == 2
    assert run.status is RunStatus.READY_FOR_REVIEW
    assert run.verifier_workspace_mutated is True
    assert run.verified_complete is False
    persisted = harness.container.state.get_run(run.run_id)
    assert persisted.verifier_workspace_mutated is True
    assert persisted.evidence_bundle_artifact_id is not None
    bundle = json.loads(
        harness.container.artifacts.read_text(persisted.evidence_bundle_artifact_id)
    )
    assert bundle["verifier_workspace_mutated"] is True
    assert bundle["completion_decision"]["verified_complete"] is False
    assert "VERIFIER_WORKSPACE_MUTATED" in bundle["completion_decision"]["reason_codes"]
    assert "VERIFIER_WORKSPACE_MUTATED" in {gap["code"] for gap in bundle["proof_gaps"]}
    assert "verifier-untrusted-note" not in harness.container.patches.show(run.run_id)
    assert not (harness.repository_root / "verifier-untrusted-note.txt").exists()
