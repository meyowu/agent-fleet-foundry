from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from agent_fleet.domain.evidence import (
    CommandEvidence,
    CompletionDecision,
    CompletionGate,
    CriterionAssessment,
    EvidenceBundle,
    EvidenceStrength,
    ProofGap,
)
from agent_fleet.domain.fleet_plan import FleetStrategy
from agent_fleet.domain.models import (
    SandboxCapabilities,
    SandboxRequirements,
    SandboxSecurityLevel,
    Verdict,
    WorkspaceKind,
)
from agent_fleet.domain.security import canonical_json_hash

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
RUN_ID = "run_11111111111111111111111111111111"
PROJECT_ID = "prj_22222222222222222222222222222222"
TASK_ID = "task_33333333333333333333333333333333"
AGENT_ID = "agent_44444444444444444444444444444444"
VERIFIER_ID = "agent_55555555555555555555555555555555"
PLAN_ARTIFACT_ID = "art_66666666666666666666666666666666"
VERDICT_ARTIFACT_ID = "art_77777777777777777777777777777777"
TRANSCRIPT_ARTIFACT_ID = "art_88888888888888888888888888888888"
EVIDENCE_ID = "art_99999999999999999999999999999999"
INSPECTION_ARTIFACT_ID = "art_12121212121212121212121212121212"
CLEANUP_ARTIFACT_ID = "art_13131313131313131313131313131313"
PATCH_ARTIFACT_ID = "art_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
TASK_SPEC_ARTIFACT_ID = "art_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
CONFIG_ARTIFACT_ID = "art_cccccccccccccccccccccccccccccccc"
CONFIG_HASH = "a" * 64
PLAN_HASH = "b" * 64
PATCH_HASH = "c" * 64
TASK_SPEC_HASH = "d" * 64
COMMAND_SPEC_HASH = "e" * 64
SANDBOX_CONFIG_HASH = "f" * 64
INSPECTION_HASH = "1" * 64
EXECUTION_ID = "exec_" + "2" * 32
IMAGE_ID = "sha256:" + "3" * 64
DAEMON_IDENTITY = "5" * 64
ISOLATED_CAPABILITIES = SandboxCapabilities(
    provider="docker",
    security_level=SandboxSecurityLevel.ISOLATED,
    isolation_enforced=True,
    executes_code=True,
    supported_network_modes=("none",),
    supports_resource_limits=True,
    supports_recovery=True,
    supports_non_root=True,
    supports_read_only_root=True,
    supports_no_new_privileges=True,
    supports_capability_drop=True,
)


def _command_evidence(
    *,
    strength: EvidenceStrength = EvidenceStrength.INDEPENDENTLY_VERIFIED,
    security_level: SandboxSecurityLevel = SandboxSecurityLevel.ISOLATED,
) -> CommandEvidence:
    capabilities = (
        ISOLATED_CAPABILITIES
        if security_level is SandboxSecurityLevel.ISOLATED
        else SandboxCapabilities.phase1_fake()
    )
    requirements = (
        SandboxRequirements(
            isolation_required=True,
            code_execution_required=True,
            resource_limits_required=True,
            non_root_required=True,
            read_only_root_required=True,
            no_new_privileges_required=True,
            capability_drop_required=True,
        )
        if security_level is SandboxSecurityLevel.ISOLATED
        else SandboxRequirements()
    )
    return CommandEvidence(
        evidence_id=EVIDENCE_ID,
        run_id=RUN_ID,
        task_id=TASK_ID,
        agent_instance_id=VERIFIER_ID,
        principal_role="verifier",
        workflow_stage="verifying",
        workspace_id="ws_" + "5" * 32,
        sandbox_id="sandbox_" + "6" * 32,
        command_id="project-test",
        command_spec_sha256=COMMAND_SPEC_HASH,
        executable="python",
        argv=["-m", "pytest", "-q"],
        cwd=".",
        sandbox_provider="docker" if security_level is SandboxSecurityLevel.ISOLATED else "fake",
        sandbox_security_level=security_level,
        sandbox_capabilities_sha256=canonical_json_hash(capabilities.model_dump(mode="json")),
        sandbox_configuration_sha256=SANDBOX_CONFIG_HASH,
        sandbox_requirements_sha256=canonical_json_hash(requirements.model_dump(mode="json")),
        sandbox_image_identity=(
            IMAGE_ID if security_level is SandboxSecurityLevel.ISOLATED else None
        ),
        sandbox_daemon_identity=(
            DAEMON_IDENTITY if security_level is SandboxSecurityLevel.ISOLATED else None
        ),
        strength=strength,
        exit_code=0,
        timed_out=False,
        output_truncated=False,
        transcript_artifact_id=TRANSCRIPT_ARTIFACT_ID,
        workspace_base_revision="base-revision",
        config_snapshot_sha256=CONFIG_HASH,
        candidate_patch_sha256=PATCH_HASH,
        workspace_kind=WorkspaceKind.VERIFICATION,
        execution_id=(EXECUTION_ID if security_level is SandboxSecurityLevel.ISOLATED else None),
        sandbox_inspection_artifact_id=(
            INSPECTION_ARTIFACT_ID if security_level is SandboxSecurityLevel.ISOLATED else None
        ),
        sandbox_inspection_sha256=(
            INSPECTION_HASH if security_level is SandboxSecurityLevel.ISOLATED else None
        ),
        started_at=NOW,
        completed_at=NOW,
    )


def _bundle(
    *,
    command_evidence: list[CommandEvidence] | None = None,
    criterion_assessments: list[CriterionAssessment] | None = None,
    proof_gaps: list[ProofGap] | None = None,
    verifier_agent_instance_id: str | None = VERIFIER_ID,
    verifier_verdict_artifact_id: str | None = VERDICT_ARTIFACT_ID,
    verifier_evidence_artifact_ids: list[str] | None = None,
    verifier_workspace_mutated: bool = False,
    verifier_required_repairs: list[str] | None = None,
    verifier_regressions: list[str] | None = None,
) -> EvidenceBundle:
    commands = command_evidence if command_evidence is not None else [_command_evidence()]
    capabilities = (
        SandboxCapabilities.phase1_fake()
        if commands and commands[0].sandbox_security_level is SandboxSecurityLevel.FAKE
        else ISOLATED_CAPABILITIES
    )
    requirements = (
        SandboxRequirements()
        if capabilities.security_level is SandboxSecurityLevel.FAKE
        else SandboxRequirements(
            isolation_required=True,
            code_execution_required=True,
            resource_limits_required=True,
            non_root_required=True,
            read_only_root_required=True,
            no_new_privileges_required=True,
            capability_drop_required=True,
        )
    )
    return EvidenceBundle(
        run_id=RUN_ID,
        project_id=PROJECT_ID,
        task_id=TASK_ID,
        base_revision="base-revision",
        config_snapshot_artifact_id=CONFIG_ARTIFACT_ID,
        config_snapshot_sha256=CONFIG_HASH,
        task_spec_artifact_id=TASK_SPEC_ARTIFACT_ID,
        task_spec_sha256=TASK_SPEC_HASH,
        fleet_plan_artifact_id=PLAN_ARTIFACT_ID,
        fleet_plan_sha256=PLAN_HASH,
        fleet_strategy=FleetStrategy.ENGINEER_VERIFIER,
        required_evidence=[
            "canonical_patch",
            "command_evidence",
            "independent_verifier_verdict",
        ],
        sandbox_provider=capabilities.provider,
        sandbox_security_level=capabilities.security_level,
        sandbox_configuration_sha256=SANDBOX_CONFIG_HASH,
        sandbox_requirements=requirements,
        sandbox_requirements_sha256=canonical_json_hash(requirements.model_dump(mode="json")),
        sandbox_image_identity=(
            IMAGE_ID if capabilities.security_level is SandboxSecurityLevel.ISOLATED else None
        ),
        sandbox_daemon_identity=(
            DAEMON_IDENTITY
            if capabilities.security_level is SandboxSecurityLevel.ISOLATED
            else None
        ),
        sandbox_capabilities=capabilities,
        sandbox_capabilities_sha256=canonical_json_hash(capabilities.model_dump(mode="json")),
        verification_command_hashes={"project-test": COMMAND_SPEC_HASH},
        required_verification_command_ids=["project-test"],
        patch_artifact_id=PATCH_ARTIFACT_ID,
        patch_sha256=PATCH_HASH,
        changed_paths=["src/canary_calc/core.py"],
        command_evidence=commands,
        verifier_agent_instance_id=verifier_agent_instance_id,
        verifier_verdict_artifact_id=verifier_verdict_artifact_id,
        verifier_evidence_artifact_ids=(
            verifier_evidence_artifact_ids
            if verifier_evidence_artifact_ids is not None
            else [EVIDENCE_ID]
        ),
        verifier_workspace_mutated=verifier_workspace_mutated,
        reported_verdict=Verdict.PASS,
        verifier_required_repairs=verifier_required_repairs or [],
        verifier_regressions=verifier_regressions or [],
        cleanup_receipt_artifact_id=CLEANUP_ARTIFACT_ID,
        cleanup_receipt_sha256="4" * 64,
        cleanup_complete=True,
        criterion_assessments=criterion_assessments
        if criterion_assessments is not None
        else [
            CriterionAssessment(
                criterion_id="canary-behavior",
                verdict=Verdict.PASS,
                evidence_artifact_ids=[EVIDENCE_ID],
                explanation="Independent evidence satisfies the criterion.",
            )
        ],
        proof_gaps=proof_gaps or [],
        assembled_at=NOW,
    )


def _authoritative_artifact_ids(bundle: EvidenceBundle) -> set[str]:
    result = {
        bundle.config_snapshot_artifact_id,
        bundle.task_spec_artifact_id,
        bundle.fleet_plan_artifact_id,
        *(item.evidence_id for item in bundle.command_evidence),
        *(item.transcript_artifact_id for item in bundle.command_evidence),
        *(
            item.sandbox_inspection_artifact_id
            for item in bundle.command_evidence
            if item.sandbox_inspection_artifact_id is not None
        ),
    }
    if bundle.verifier_verdict_artifact_id is not None:
        result.add(bundle.verifier_verdict_artifact_id)
    if bundle.patch_artifact_id is not None:
        result.add(bundle.patch_artifact_id)
    if bundle.cleanup_receipt_artifact_id is not None:
        result.add(bundle.cleanup_receipt_artifact_id)
    return result


def _evaluate(bundle: EvidenceBundle) -> CompletionDecision:
    return CompletionGate.evaluate(
        bundle,
        expected_criteria={"canary-behavior"},
        authoritative_artifact_ids=_authoritative_artifact_ids(bundle),
    )


@pytest.mark.parametrize(
    ("field", "wrong_id"),
    [
        ("run_id", "task_" + "1" * 32),
        ("project_id", "art_" + "2" * 32),
        ("task_id", "run_" + "3" * 32),
        ("config_snapshot_artifact_id", "plan_" + "4" * 32),
        ("verifier_agent_instance_id", "art_" + "5" * 32),
    ],
)
def test_evidence_bundle_rejects_cross_type_id_prefixes(field: str, wrong_id: str) -> None:
    payload = _bundle().model_dump()
    payload[field] = wrong_id

    with pytest.raises(ValidationError, match="string_pattern_mismatch"):
        EvidenceBundle.model_validate(payload)


def test_complete_independent_evidence_can_pass_the_gate() -> None:
    decision = _evaluate(_bundle())

    assert decision.verified_complete is True
    assert decision.effective_verdict is Verdict.PASS
    assert decision.reason_codes == []


def test_task_spec_reference_must_be_authoritative() -> None:
    bundle = _bundle()

    decision = CompletionGate.evaluate(
        bundle,
        expected_criteria={"canary-behavior"},
        authoritative_artifact_ids=(
            _authoritative_artifact_ids(bundle) - {bundle.task_spec_artifact_id}
        ),
    )

    assert decision.verified_complete is False
    assert decision.effective_verdict is Verdict.INCONCLUSIVE
    assert "ARTIFACT_REFERENCE_MISSING" in decision.reason_codes


def test_fake_simulated_evidence_can_never_be_verified_complete() -> None:
    simulated = _command_evidence(
        strength=EvidenceStrength.SIMULATED,
        security_level=SandboxSecurityLevel.FAKE,
    )

    decision = _evaluate(_bundle(command_evidence=[simulated]))

    assert decision.verified_complete is False
    assert decision.effective_verdict is Verdict.INCONCLUSIVE
    assert "SIMULATED_EVIDENCE_ONLY" in decision.reason_codes


def test_fake_provider_cannot_forge_independently_verified_strength() -> None:
    forged = _command_evidence(
        strength=EvidenceStrength.INDEPENDENTLY_VERIFIED,
        security_level=SandboxSecurityLevel.FAKE,
    )
    decision = _evaluate(_bundle(command_evidence=[forged]))
    assert decision.verified_complete is False
    assert "SIMULATED_EVIDENCE_ONLY" in decision.reason_codes
    assert "EVIDENCE_STRENGTH_INVALID" in decision.reason_codes


def test_patch_and_configuration_evidence_must_be_fresh_and_bound() -> None:
    stale = _command_evidence().model_copy(update={"config_snapshot_sha256": "c" * 64})
    bundle = _bundle(command_evidence=[stale]).model_copy(
        update={
            "patch_artifact_id": "art_" + "9" * 32,
            "patch_sha256": "d" * 64,
        }
    )
    decision = _evaluate(bundle)
    assert decision.verified_complete is False
    assert "CONFIG_EVIDENCE_STALE" in decision.reason_codes
    assert "PATCH_EVIDENCE_UNBOUND" in decision.reason_codes


def test_sandbox_capability_and_command_spec_tampering_fail_closed() -> None:
    command = _command_evidence().model_copy(update={"command_spec_sha256": "9" * 64})
    bundle = _bundle(command_evidence=[command]).model_copy(
        update={"sandbox_capabilities_sha256": "8" * 64}
    )

    decision = _evaluate(bundle)

    assert decision.verified_complete is False
    assert "SANDBOX_CAPABILITY_BINDING_INVALID" in decision.reason_codes
    assert "COMMAND_SPEC_BINDING_INVALID" in decision.reason_codes
    assert "SANDBOX_EVIDENCE_BINDING_INVALID" in decision.reason_codes


def test_required_verifier_command_and_inspection_identity_are_mandatory() -> None:
    command = _command_evidence().model_copy(
        update={
            "command_id": "optional-check",
            "command_spec_sha256": "7" * 64,
            "execution_id": None,
            "sandbox_inspection_sha256": None,
        }
    )
    bundle = _bundle(command_evidence=[command]).model_copy(
        update={
            "verification_command_hashes": {
                "project-test": COMMAND_SPEC_HASH,
                "optional-check": "7" * 64,
            }
        }
    )

    decision = _evaluate(bundle)

    assert decision.verified_complete is False
    assert "REQUIRED_COMMAND_EVIDENCE_MISSING" in decision.reason_codes
    assert "VERIFIER_REQUIRED_COMMAND_EVIDENCE_MISSING" in decision.reason_codes
    assert "SANDBOX_INSPECTION_EVIDENCE_MISSING" in decision.reason_codes
    assert "EXECUTION_IDENTITY_MISSING" in decision.reason_codes


def test_missing_and_nonpassing_criteria_block_verified_completion() -> None:
    missing_bundle = _bundle().model_copy(update={"criterion_assessments": []})
    missing = CompletionGate.evaluate(
        missing_bundle,
        expected_criteria={"canary-behavior"},
        authoritative_artifact_ids=_authoritative_artifact_ids(missing_bundle),
    )
    nonpassing_bundle = _bundle(
        criterion_assessments=[
            CriterionAssessment(
                criterion_id="canary-behavior",
                verdict=Verdict.INCONCLUSIVE,
                explanation="Required behavior was not executed.",
            )
        ]
    )
    nonpassing = _evaluate(nonpassing_bundle)

    assert missing.verified_complete is False
    assert "CRITERIA_EVIDENCE_INCOMPLETE" in missing.reason_codes
    assert nonpassing.verified_complete is False
    assert "CRITERION_NOT_PASSING" in nonpassing.reason_codes


def test_proof_gap_blocks_verified_completion() -> None:
    decision = _evaluate(
        _bundle(
            proof_gaps=[
                ProofGap(
                    code="PROJECT_TESTS_NOT_EXECUTED",
                    description="The fake sandbox did not execute project tests.",
                    required_strength=EvidenceStrength.INDEPENDENTLY_VERIFIED,
                )
            ]
        )
    )

    assert decision.verified_complete is False
    assert decision.effective_verdict is Verdict.INCONCLUSIVE
    assert "PROOF_GAPS_PRESENT" in decision.reason_codes


def test_engineer_verifier_plan_requires_verifier_identity_and_verdict_artifact() -> None:
    decision = _evaluate(
        _bundle(
            verifier_agent_instance_id=None,
            verifier_verdict_artifact_id=None,
        )
    )

    assert decision.verified_complete is False
    assert decision.effective_verdict is Verdict.INCONCLUSIVE
    assert "INDEPENDENT_VERIFIER_MISSING" in decision.reason_codes


def test_foreign_failed_command_and_nonexistent_criterion_reference_cannot_pass() -> None:
    foreign = _command_evidence().model_copy(
        update={
            "run_id": "run_" + "a" * 32,
            "task_id": "task_" + "b" * 32,
            "exit_code": 17,
            "timed_out": True,
        }
    )
    missing_reference = "art_" + "c" * 32
    bundle = _bundle(
        command_evidence=[foreign],
        criterion_assessments=[
            CriterionAssessment(
                criterion_id="canary-behavior",
                verdict=Verdict.PASS,
                evidence_artifact_ids=[missing_reference],
                explanation="This unbound claim must not pass.",
            )
        ],
    )
    authoritative = _authoritative_artifact_ids(bundle)

    decision = CompletionGate.evaluate(
        bundle,
        expected_criteria={"canary-behavior"},
        authoritative_artifact_ids=authoritative,
    )

    assert decision.verified_complete is False
    assert decision.effective_verdict is Verdict.FAIL
    assert "COMMAND_EVIDENCE_IDENTITY_MISMATCH" in decision.reason_codes
    assert "COMMAND_EXECUTION_FAILED" in decision.reason_codes
    assert "CRITERION_EVIDENCE_UNBOUND" in decision.reason_codes


def test_missing_authoritative_artifact_and_forged_verifier_identity_are_rejected() -> None:
    command = _command_evidence().model_copy(update={"agent_instance_id": AGENT_ID})
    bundle = _bundle(command_evidence=[command])
    authoritative = _authoritative_artifact_ids(bundle) - {command.transcript_artifact_id}

    decision = CompletionGate.evaluate(
        bundle,
        expected_criteria={"canary-behavior"},
        authoritative_artifact_ids=authoritative,
    )

    assert decision.verified_complete is False
    assert "ARTIFACT_REFERENCE_MISSING" in decision.reason_codes
    assert "EVIDENCE_STRENGTH_INVALID" in decision.reason_codes


def test_empty_expected_criteria_can_never_verify_complete() -> None:
    bundle = _bundle()
    decision = CompletionGate.evaluate(
        bundle,
        expected_criteria=set(),
        authoritative_artifact_ids=_authoritative_artifact_ids(bundle),
    )

    assert decision.verified_complete is False
    assert decision.effective_verdict is Verdict.INCONCLUSIVE
    assert "CRITERIA_NOT_DEFINED" in decision.reason_codes


def test_required_evidence_is_enforced_and_unknown_ids_are_rejected() -> None:
    missing_patch = _bundle().model_copy(
        update={
            "patch_artifact_id": None,
            "patch_sha256": None,
            "changed_paths": [],
        }
    )
    decision = _evaluate(missing_patch)
    assert decision.verified_complete is False
    assert "REQUIRED_EVIDENCE_MISSING" in decision.reason_codes

    payload = _bundle().model_dump()
    payload["required_evidence"] = ["security_audit"]
    with pytest.raises(ValidationError, match="literal_error"):
        EvidenceBundle.model_validate(payload)


def test_engineer_command_cannot_impersonate_independent_verifier_evidence() -> None:
    engineer_command = _command_evidence().model_copy(
        update={
            "agent_instance_id": AGENT_ID,
            "strength": EvidenceStrength.OBSERVED,
        }
    )
    decision = _evaluate(_bundle(command_evidence=[engineer_command]))

    assert decision.verified_complete is False
    assert "INDEPENDENT_VERIFIER_EVIDENCE_MISSING" in decision.reason_codes
    assert "VERIFIER_EVIDENCE_BINDING_INVALID" in decision.reason_codes


def test_verifier_evidence_must_bind_the_final_patch() -> None:
    verifier_evidence_id = "art_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    verifier_transcript_id = "art_cccccccccccccccccccccccccccccccc"
    engineer_command = _command_evidence().model_copy(
        update={
            "agent_instance_id": AGENT_ID,
            "strength": EvidenceStrength.OBSERVED,
        }
    )
    verifier_command = _command_evidence().model_copy(
        update={
            "evidence_id": verifier_evidence_id,
            "transcript_artifact_id": verifier_transcript_id,
            "candidate_patch_sha256": None,
        }
    )
    bundle = _bundle(
        command_evidence=[engineer_command, verifier_command],
        verifier_evidence_artifact_ids=[verifier_evidence_id],
        criterion_assessments=[
            CriterionAssessment(
                criterion_id="canary-behavior",
                verdict=Verdict.PASS,
                evidence_artifact_ids=[verifier_evidence_id],
                explanation="Verifier evidence must identify the final patch.",
            )
        ],
    )

    decision = _evaluate(bundle)

    assert decision.verified_complete is False
    assert "VERIFIER_PATCH_EVIDENCE_UNBOUND" in decision.reason_codes


def test_verifier_workspace_mutation_fails_closed_with_stable_reason() -> None:
    decision = _evaluate(_bundle(verifier_workspace_mutated=True))

    assert decision.verified_complete is False
    assert decision.effective_verdict is Verdict.INCONCLUSIVE
    assert "VERIFIER_WORKSPACE_MUTATED" in decision.reason_codes


@pytest.mark.parametrize(
    ("required_repairs", "regressions", "reason_code"),
    [
        (
            ["Repair the verifier-detected defect."],
            [],
            "VERIFIER_PASS_WITH_REQUIRED_REPAIRS",
        ),
        (
            [],
            ["Existing behavior regressed."],
            "VERIFIER_PASS_WITH_REGRESSIONS",
        ),
    ],
)
def test_verifier_pass_with_negative_findings_fails_closed(
    required_repairs: list[str],
    regressions: list[str],
    reason_code: str,
) -> None:
    decision = _evaluate(
        _bundle(
            verifier_required_repairs=required_repairs,
            verifier_regressions=regressions,
        )
    )

    assert decision.verified_complete is False
    assert decision.effective_verdict is Verdict.INCONCLUSIVE
    assert reason_code in decision.reason_codes
