from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_fleet.bootstrap import build_container
from agent_fleet.domain.bootstrap import BootstrapPolicyMode, BootstrapReport
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import ArtifactMetadata


@pytest.mark.asyncio
async def test_degraded_bootstrap_persists_valid_report_but_never_publishes_target(
    tmp_path: Path,
) -> None:
    fixture = build_container(tmp_path / "fixture-state")
    target = fixture.repository.create_canary_fixture(tmp_path / "fixture-state" / "target")
    state_root = tmp_path / "fleet-state"
    container = build_container(state_root)

    with pytest.raises(FleetError) as captured:
        await container.bootstrap.initialize(
            target,
            runtime_name="fake",
            sandbox_name="fake",
        )

    assert captured.value.code is ErrorCode.BOOTSTRAP_CANARY_FAILED
    report_id = captured.value.details["report_artifact_id"]
    assert isinstance(report_id, str)
    report_artifact = container.state.get_artifact(report_id)
    report = container.bootstrap._read_and_validate_report(report_artifact)
    assert report.policy_mode is BootstrapPolicyMode.DEGRADED_SIMULATION
    assert report.publish_allowed is False
    assert report.completion_decision.verified_complete is False
    assert report.proof_gaps
    assert report.cleanup_complete is True
    assert report.outstanding_lease_count == 0
    assert container.state.outstanding_leases(report.canary_run_id) == []
    assert container.state.get_project_by_root(str(target.resolve())) is None
    assert not (target / ".fleet").exists()

    invalid = report.model_dump(mode="json")
    invalid["publish_allowed"] = True
    with pytest.raises(ValueError, match="publication policy"):
        BootstrapReport.model_validate(invalid)


@pytest.mark.asyncio
async def test_bootstrap_report_rejects_coherently_rewritten_reference_hash(
    tmp_path: Path,
) -> None:
    fixture = build_container(tmp_path / "fixture-state")
    target = fixture.repository.create_canary_fixture(tmp_path / "fixture-state" / "target")
    state_root = tmp_path / "fleet-state"
    container = build_container(state_root)

    with pytest.raises(FleetError) as captured:
        await container.bootstrap.initialize(target, runtime_name="fake", sandbox_name="fake")

    report_id = captured.value.details["report_artifact_id"]
    assert isinstance(report_id, str)
    original_metadata = container.state.get_artifact(report_id)
    document = json.loads(container.artifacts.read_text(report_id))
    assert isinstance(document, dict)
    patch_reference = document["patch"]
    assert isinstance(patch_reference, dict)
    patch_reference["sha256"] = "f" * 64
    mutated_content = json.dumps(document, sort_keys=True, indent=2) + "\n"
    content_ref, digest, byte_size = container.artifacts.store.put(mutated_content.encode("utf-8"))
    mutated_metadata = ArtifactMetadata.model_validate(
        {
            **original_metadata.model_dump(mode="json"),
            "content_ref": content_ref,
            "sha256": digest,
            "byte_size": byte_size,
        }
    )
    with container.state._connect() as connection:
        connection.execute(
            "UPDATE artifacts SET sha256 = ?, data_json = ? WHERE artifact_id = ?",
            (digest, mutated_metadata.model_dump_json(), report_id),
        )

    with pytest.raises(FleetError) as invalid:
        container.bootstrap._read_and_validate_report(mutated_metadata)

    assert invalid.value.code is ErrorCode.BOOTSTRAP_REPORT_INVALID
    assert container.state.get_project_by_root(str(target.resolve())) is None
    assert not (target / ".fleet").exists()
