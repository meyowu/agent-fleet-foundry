from __future__ import annotations

import json
import runpy
from pathlib import Path

import pytest
from conftest import FleetHarness

from agent_fleet.adapters.repository.git import GitRepositoryAdapter
from agent_fleet.adapters.runtime.fake import FakeRuntimeAdapter
from agent_fleet.adapters.sandbox.fake import FakeSandboxProvider
from agent_fleet.adapters.system import SystemClock, UuidIdGenerator
from agent_fleet.application.runtime import RuntimeRegistry
from agent_fleet.bootstrap import build_container
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import (
    AgentInstance,
    AgentInvocation,
    AgentInvocationResult,
    AgentRole,
    AgentStatus,
    ArtifactKind,
    FakeScenario,
    ImplementationReport,
    RunStatus,
    SandboxCapabilities,
    SandboxSecurityLevel,
    ScopeDecision,
)
from agent_fleet.domain.offline_canary import BROKEN_CANARY, FIXED_CANARY
from agent_fleet.domain.repository_profile import (
    ProjectKnowledge,
    RepositoryProfile,
    RepositoryProfileResult,
    RepositorySignal,
)
from agent_fleet.domain.security import canonical_json_hash, sha256_bytes
from agent_fleet.ports.runtime import RuntimeInvocationServices


class MultiCriterionRuntime(FakeRuntimeAdapter):
    async def invoke(
        self,
        request: AgentInvocation,
        services: RuntimeInvocationServices,
    ) -> AgentInvocationResult:
        result = await super().invoke(request, services)
        if request.role == AgentRole.COS:
            assert isinstance(result.output, ScopeDecision)
            output_data = result.output.model_dump(mode="json")
            criteria = [item.model_dump(mode="json") for item in result.output.acceptance_criteria]
            criteria.append(
                {
                    "criterion_id": "second-behavior",
                    "description": "A second criterion needs its own structured mapping.",
                }
            )
            output_data["acceptance_criteria"] = criteria
            output = ScopeDecision.model_validate(output_data)
            return AgentInvocationResult(
                output=output,
                usage=result.usage,
                checkpoint_ref=result.checkpoint_ref,
                provider_metadata=result.provider_metadata,
            )
        return result


class InvalidResultRuntime(FakeRuntimeAdapter):
    def __init__(self, mode: str, secret: str) -> None:
        self.mode = mode
        self.secret = secret
        self.scope_output: ScopeDecision | None = None

    async def invoke(
        self,
        request: AgentInvocation,
        services: RuntimeInvocationServices,
    ) -> AgentInvocationResult:
        result = await super().invoke(request, services)
        if request.role == AgentRole.COS:
            assert isinstance(result.output, ScopeDecision)
            self.scope_output = result.output
            if self.mode == "wrong-cos-output":
                return result.model_copy(
                    update={
                        "output": ImplementationReport(
                            summary="Wrong role output.",
                            intended_changed_paths=[],
                            tests_added_or_changed=[],
                            criterion_results=[],
                            evidence_artifact_ids=[],
                            unresolved_limitations=[],
                            verifier_focus=[],
                        )
                    }
                )
        if request.role == AgentRole.ENGINEER:
            if self.mode == "wrong-engineer-output":
                assert self.scope_output is not None
                return result.model_copy(update={"output": self.scope_output})
            if self.mode == "secret-engineer-output":
                assert isinstance(result.output, ImplementationReport)
                return result.model_copy(
                    update={
                        "output": result.output.model_copy(
                            update={"summary": f"Leaked {self.secret}"}
                        )
                    }
                )
        return result


class IncoherentFakeSandbox(FakeSandboxProvider):
    @property
    def capabilities(self) -> SandboxCapabilities:
        return SandboxCapabilities.model_construct(
            provider="fake",
            security_level=SandboxSecurityLevel.ISOLATED,
            isolation_enforced=True,
            executes_code=False,
            supported_network_modes=("approved-unrestricted",),
            supports_resource_limits=True,
            supports_recovery=True,
        )


class OversizedRepositoryProfiler:
    def profile(self, root: Path) -> RepositoryProfileResult:
        del root
        profile = RepositoryProfile(
            ecosystems=["python"],
            build_systems=["uv"],
            boundaries=[],
            signals=[
                RepositorySignal(
                    ecosystem="python",
                    path="pyproject.toml",
                    signal="manifest",
                )
                for _ in range(5000)
            ],
            commands=[],
            ambiguities=[],
            files_read=[],
            bytes_read=0,
        )
        digest = canonical_json_hash(profile.model_dump(mode="json"))
        return RepositoryProfileResult(
            profile=profile,
            project_knowledge=ProjectKnowledge(
                source_profile_sha256=digest,
                summary="Oversized but valid repository profile.",
                ecosystems=["python"],
                build_systems=["uv"],
                repository_boundaries=[],
                verification_commands=[],
                ambiguities=[],
            ),
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_oversized_repository_context_fails_run_without_raw_validation_error(
    tmp_path: Path,
) -> None:
    repository = GitRepositoryAdapter(tmp_path, UuidIdGenerator()).create_canary_fixture(
        tmp_path / "target-repository"
    )
    container = build_container(tmp_path / "fleet-state")
    container.projects.profiler = OversizedRepositoryProfiler()
    container.projects.initialize(repository, runtime_name="fake", sandbox_name="fake")

    with pytest.raises(FleetError) as captured:
        await container.workflow.start(
            project_path=repository,
            goal="Inspect the oversized repository context.",
            runtime_name="fake",
            sandbox_name="fake",
            fake_scenario=FakeScenario.SUCCESS,
        )

    assert captured.value.code is ErrorCode.RUNTIME_BUDGET_EXCEEDED
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
    with container.state._connect() as connection:
        runs = connection.execute("SELECT run_id, status, stage FROM runs").fetchall()
        agents = connection.execute("SELECT agent_instance_id FROM agent_instances").fetchall()
    assert len(runs) == 1
    assert runs[0]["status"] == RunStatus.FAILED.value
    assert runs[0]["stage"] == "scoping"
    assert agents == []
    events = container.state.list_events(runs[0]["run_id"])
    assert events[-1].event_type == "run.failed"
    assert events[-1].payload["code"] == ErrorCode.RUNTIME_BUDGET_EXCEEDED.value


@pytest.mark.integration
@pytest.mark.asyncio
async def test_workflow_rejects_nonexact_fake_sandbox_descriptor(
    harness: FleetHarness,
) -> None:
    harness.container.workflow.sandbox = IncoherentFakeSandbox(SystemClock(), UuidIdGenerator())

    with pytest.raises(FleetError) as captured:
        await harness.start()

    assert captured.value.code is ErrorCode.SANDBOX_UNAVAILABLE


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "failed_role", "expected_code"),
    [
        ("wrong-cos-output", AgentRole.COS, ErrorCode.RUNTIME_OUTPUT_INVALID),
        ("wrong-engineer-output", AgentRole.ENGINEER, ErrorCode.RUNTIME_OUTPUT_INVALID),
        ("secret-engineer-output", AgentRole.ENGINEER, ErrorCode.COMMAND_DENIED),
    ],
)
async def test_invalid_runtime_result_fails_agent_and_run_without_running_leak(
    harness: FleetHarness,
    mode: str,
    failed_role: AgentRole,
    expected_code: ErrorCode,
) -> None:
    sentinel = "registered-runtime-output-secret"
    harness.container.workflow.redactor.register_secret(sentinel)
    harness.container.workflow.runtimes = RuntimeRegistry(
        {"fake": InvalidResultRuntime(mode, sentinel)}
    )

    with pytest.raises(FleetError) as captured:
        await harness.start()

    assert captured.value.code is expected_code
    with harness.container.state._connect() as connection:
        run_row = connection.execute(
            "SELECT run_id FROM runs ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        assert run_row is not None
        agent_rows = connection.execute(
            "SELECT data_json FROM agent_instances WHERE run_id = ? ORDER BY rowid",
            (str(run_row["run_id"]),),
        ).fetchall()
    run = harness.container.state.get_run(str(run_row["run_id"]))
    agents = [AgentInstance.model_validate_json(row["data_json"]) for row in agent_rows]
    assert run.status is RunStatus.FAILED
    assert all(agent.status is not AgentStatus.RUNNING for agent in agents)
    failed_agents = [agent for agent in agents if agent.status is AgentStatus.FAILED]
    assert [str(agent.role) for agent in failed_agents] == [failed_role.value]
    if failed_role is AgentRole.COS:
        assert failed_agents[0].task_id is None
    failed_events = [
        event
        for event in harness.container.state.list_events(run.run_id)
        if event.event_type == "agent.failed"
    ]
    assert failed_events[-1].payload == {
        "role": failed_role.value,
        "code": expected_code.value,
    }


@pytest.mark.integration
@pytest.mark.asyncio
async def test_successful_run_persists_ordered_evidence_and_applies_exact_patch(
    harness: FleetHarness,
) -> None:
    run = await harness.start()
    assert run.status is RunStatus.READY_FOR_REVIEW
    assert run.patch_artifact_id is not None
    patch = harness.container.patches.show(run.run_id)
    assert '+        raise ValueError("division by zero is not allowed")' in patch
    assert run.patch_sha256 == sha256_bytes(patch.encode())
    assert run.fleet_strategy == "engineer_verifier"
    assert run.evidence_bundle_artifact_id is not None
    assert run.assurance_verdict is not None
    assert run.assurance_verdict.value == "inconclusive"
    assert run.verified_complete is False
    bundle = json.loads(
        harness.container.artifacts.read_text(run.evidence_bundle_artifact_id or "")
    )
    assert bundle["changed_paths"] == ["src/canary_calc/core.py"]
    status = harness.container.inspection.status(run.run_id)
    assert status["config_snapshot_artifact_id"] == run.config_snapshot_artifact_id
    assert status["task_spec_artifact_id"] == run.task_spec_artifact_id
    evidence = status["evidence"]
    assert isinstance(evidence, dict)
    assert evidence["changed_paths"] == ["src/canary_calc/core.py"]
    assert "SIMULATED_EVIDENCE_ONLY" in evidence["completion_reason_codes"]
    assert any(
        isinstance(item, dict) and item.get("code") == "SIMULATED_EXECUTION"
        for item in evidence["proof_gaps"]
    )
    patch_metadata = harness.container.state.get_artifact(run.patch_artifact_id)
    assert patch_metadata.metadata["changed_paths"] == ["src/canary_calc/core.py"]
    assert (harness.repository_root / "src/canary_calc/core.py").read_text() == BROKEN_CANARY

    events = harness.container.state.list_events(run.run_id)
    assert [event.sequence for event in events] == list(range(1, len(events) + 1))
    assert {"task.scoped", "verification.completed", "patch.ready"} <= {
        event.event_type for event in events
    }
    artifacts = harness.container.state.list_artifacts(run.run_id)
    kinds = {artifact.kind for artifact in artifacts}
    assert {
        ArtifactKind.CONFIG_SNAPSHOT,
        ArtifactKind.TASK_SPEC,
        ArtifactKind.FLEET_PLAN,
        ArtifactKind.IMPLEMENTATION_REPORT,
        ArtifactKind.PATCH,
        ArtifactKind.COMMAND_EVIDENCE,
        ArtifactKind.VERIFIER_VERDICT,
        ArtifactKind.EVIDENCE_BUNDLE,
        ArtifactKind.RUN_SUMMARY,
    } <= kinds
    assert harness.container.state.active_leases(run.run_id) == []

    completed, result = harness.container.patches.apply(run.run_id)
    assert completed.status is RunStatus.COMPLETED
    assert result.changed_paths == ["src/canary_calc/core.py"]
    assert (harness.repository_root / "src/canary_calc/core.py").read_text() == FIXED_CANARY
    namespace = runpy.run_path(str(harness.repository_root / "src/canary_calc/core.py"))
    with pytest.raises(ValueError, match="division by zero is not allowed"):
        namespace["divide"](1, 0)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_verifier_fail_reaches_rejected_after_bound(harness: FleetHarness) -> None:
    run = await harness.start(FakeScenario.FAIL)
    assert run.status is RunStatus.REJECTED
    assert run.repair_iterations == 1
    assert run.evidence_bundle_artifact_id is not None
    assert run.assurance_verdict is not None
    assert run.assurance_verdict.value == "fail"
    assert run.verified_complete is False
    verdicts = [
        item
        for item in harness.container.state.list_artifacts(run.run_id)
        if item.kind is ArtifactKind.VERIFIER_VERDICT
    ]
    assert len(verdicts) == 2
    assert harness.container.state.active_leases(run.run_id) == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_one_repair_iteration_then_pass(harness: FleetHarness) -> None:
    run = await harness.start(FakeScenario.REPAIR)
    assert run.status is RunStatus.READY_FOR_REVIEW
    assert run.repair_iterations == 1
    assert (
        sum(
            event.event_type == "repair.requested"
            for event in harness.container.state.list_events(run.run_id)
        )
        == 1
    )
    assert harness.container.patches.show(run.run_id).count("division by zero is not allowed") >= 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_inconclusive_is_presented_with_proof_gap(harness: FleetHarness) -> None:
    run = await harness.start(FakeScenario.INCONCLUSIVE)
    assert run.status is RunStatus.READY_FOR_REVIEW
    verdicts = [
        item
        for item in harness.container.state.list_artifacts(run.run_id)
        if item.kind is ArtifactKind.VERIFIER_VERDICT
    ]
    content = harness.container.artifacts.read_text(verdicts[-1].artifact_id)
    assert '"verdict": "inconclusive"' in content
    assert "No project code was executed" in content


@pytest.mark.integration
@pytest.mark.asyncio
async def test_multiple_criteria_are_not_blanket_passed_by_one_overall_verdict(
    harness: FleetHarness,
) -> None:
    harness.container.workflow.runtimes = RuntimeRegistry({"fake": MultiCriterionRuntime()})

    run = await harness.start(FakeScenario.SUCCESS)

    assert run.status is RunStatus.READY_FOR_REVIEW
    assert run.verified_complete is False
    bundle = json.loads(
        harness.container.artifacts.read_text(run.evidence_bundle_artifact_id or "")
    )
    assert {assessment["verdict"] for assessment in bundle["criterion_assessments"]} == {
        "inconclusive"
    }
    assert {gap["code"] for gap in bundle["proof_gaps"]} >= {
        "STRUCTURED_CRITERION_MAPPING_UNAVAILABLE"
    }


@pytest.mark.integration
@pytest.mark.asyncio
async def test_verifier_mutation_is_detected_discarded_and_absent_from_patch(
    harness: FleetHarness,
) -> None:
    with pytest.raises(FleetError) as captured:
        await harness.start(FakeScenario.VERIFIER_MUTATION)
    assert captured.value.code is ErrorCode.COMMAND_DENIED
    assert str(captured.value.details["run_id"]).startswith("run_")
    with harness.container.state._connect() as connection:
        row = connection.execute("SELECT run_id FROM runs ORDER BY rowid DESC LIMIT 1").fetchone()
    assert row is not None
    run = harness.container.state.get_run(str(row["run_id"]))
    assert captured.value.details["run_id"] == run.run_id
    assert run.status is RunStatus.FAILED
    assert run.evidence_bundle_artifact_id is not None
    assert run.assurance_verdict is not None
    assert run.assurance_verdict.value == "inconclusive"
    assert run.verified_complete is False
    assert run.verifier_workspace_mutated is False
    assert "verifier-untrusted-note" not in harness.container.patches.show(run.run_id)
    assert not (harness.repository_root / "verifier-untrusted-note.txt").exists()
    decisions = [
        event
        for event in harness.container.state.list_events(run.run_id)
        if event.event_type == "permission.decision"
    ]
    assert decisions[-1].payload["decision_code"] == "PHASE1_DEFAULT_DENY"
    assert harness.container.state.active_leases(run.run_id) == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_direct_plan_creates_no_specialist_or_workspace(harness: FleetHarness) -> None:
    run = await harness.start(FakeScenario.DIRECT)
    assert run.status is RunStatus.COMPLETED
    assert run.fleet_strategy == "direct"
    assert run.patch_artifact_id is None
    assert run.evidence_bundle_artifact_id is not None
    assert run.verified_complete is False
    with harness.container.state._connect() as connection:
        rows = connection.execute(
            "SELECT role FROM agent_instances WHERE run_id = ? ORDER BY rowid", (run.run_id,)
        ).fetchall()
    assert [row["role"] for row in rows] == ["cos"]
    assert harness.container.state.active_leases(run.run_id) == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_single_engineer_plan_creates_no_verifier(harness: FleetHarness) -> None:
    run = await harness.start(FakeScenario.SINGLE_ENGINEER)
    assert run.status is RunStatus.READY_FOR_REVIEW
    assert run.fleet_strategy == "single_engineer"
    assert run.verifier_verdict_artifact_id is None
    assert run.verified_complete is False
    with harness.container.state._connect() as connection:
        rows = connection.execute(
            "SELECT role FROM agent_instances WHERE run_id = ? ORDER BY rowid", (run.run_id,)
        ).fetchall()
    assert [row["role"] for row in rows] == ["cos", "engineer"]
    bundle = harness.container.artifacts.read_text(run.evidence_bundle_artifact_id or "")
    assert "NO_INDEPENDENT_VERIFIER" in bundle


@pytest.mark.integration
@pytest.mark.asyncio
async def test_dirty_target_refuses_apply_without_losing_file(harness: FleetHarness) -> None:
    run = await harness.start()
    user_file = harness.repository_root / "user-work.txt"
    user_file.write_text("preserve me\n", encoding="utf-8")
    with pytest.raises(FleetError) as captured:
        harness.container.patches.apply(run.run_id)
    assert captured.value.code is ErrorCode.PATCH_TARGET_DIVERGED
    assert user_file.read_text(encoding="utf-8") == "preserve me\n"
    assert harness.container.state.get_run(run.run_id).status is RunStatus.READY_FOR_REVIEW


@pytest.mark.integration
@pytest.mark.asyncio
async def test_patch_application_rechecks_run_to_artifact_hash_binding(
    harness: FleetHarness,
) -> None:
    run = await harness.start()
    tampered = run.model_copy(
        update={"patch_sha256": "0" * 64, "updated_at": harness.container.state.clock.now()}
    )
    harness.container.state.save_run(
        tampered, "patch.metadata_tampered_for_test", {"test_only": True}
    )
    with pytest.raises(FleetError) as captured:
        harness.container.patches.apply(run.run_id)
    assert captured.value.code is ErrorCode.ARTIFACT_INTEGRITY_FAILED
    assert (harness.repository_root / "src/canary_calc/core.py").read_text() == BROKEN_CANARY


@pytest.mark.integration
@pytest.mark.asyncio
async def test_status_rejects_evidence_bundle_hash_mismatch(harness: FleetHarness) -> None:
    run = await harness.start()
    tampered = run.model_copy(
        update={"evidence_bundle_hash": "0" * 64, "updated_at": harness.container.state.clock.now()}
    )
    harness.container.state.save_run(
        tampered, "evidence.metadata_tampered_for_test", {"test_only": True}
    )

    with pytest.raises(FleetError) as captured:
        harness.container.inspection.status(run.run_id)

    assert captured.value.code is ErrorCode.ARTIFACT_INTEGRITY_FAILED


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("base_revision", "f" * 40),
        ("config_snapshot_artifact_id", "art_" + "1" * 32),
        ("config_snapshot_hash", "1" * 64),
        ("task_spec_artifact_id", "art_" + "2" * 32),
        ("task_spec_hash", "2" * 64),
        ("fleet_plan_artifact_id", "art_" + "3" * 32),
        ("fleet_plan_hash", "3" * 64),
        ("fleet_strategy", "single_engineer"),
        ("patch_artifact_id", "art_" + "4" * 32),
        ("patch_sha256", "4" * 64),
        ("command_evidence_artifact_ids", []),
        ("verifier_agent_instance_id", "agent_" + "5" * 32),
        ("verifier_verdict_artifact_id", "art_" + "5" * 32),
        ("verifier_workspace_mutated", True),
    ],
)
async def test_status_rejects_every_run_to_bundle_binding_mismatch(
    harness: FleetHarness, field: str, value: object
) -> None:
    run = await harness.start()
    tampered = run.model_copy(
        update={field: value, "updated_at": harness.container.state.clock.now()}
    )
    harness.container.state.save_run(
        tampered, "evidence.binding_tampered_for_test", {"field": field}
    )

    with pytest.raises(FleetError) as captured:
        harness.container.inspection.status(run.run_id)

    assert captured.value.code is ErrorCode.ARTIFACT_INTEGRITY_FAILED


@pytest.mark.integration
@pytest.mark.asyncio
async def test_status_rejects_assurance_claim_without_bundle(harness: FleetHarness) -> None:
    run = await harness.start()
    tampered = run.model_copy(
        update={
            "evidence_bundle_artifact_id": None,
            "evidence_bundle_hash": None,
            "verified_complete": True,
            "updated_at": harness.container.state.clock.now(),
        }
    )
    harness.container.state.save_run(
        tampered, "evidence.binding_removed_for_test", {"test_only": True}
    )

    with pytest.raises(FleetError) as captured:
        harness.container.inspection.status(run.run_id)

    assert captured.value.code is ErrorCode.ARTIFACT_INTEGRITY_FAILED


@pytest.mark.integration
@pytest.mark.asyncio
async def test_apply_rechecks_exact_configuration_snapshot(harness: FleetHarness) -> None:
    run = await harness.start()
    before = harness.container.repository.inspect(harness.repository_root)
    prompt = harness.repository_root / ".fleet" / "agents" / "engineer.md"
    prompt.write_text(
        prompt.read_text(encoding="utf-8") + "\nchanged after review\n", encoding="utf-8"
    )
    after = harness.container.repository.inspect(harness.repository_root)
    assert after.status_fingerprint == before.status_fingerprint

    with pytest.raises(FleetError) as captured:
        harness.container.patches.apply(run.run_id)

    assert captured.value.code is ErrorCode.PATCH_TARGET_DIVERGED
    assert (harness.repository_root / "src/canary_calc/core.py").read_text() == BROKEN_CANARY


@pytest.mark.integration
@pytest.mark.asyncio
async def test_diverged_head_refuses_apply(harness: FleetHarness) -> None:
    run = await harness.start()
    harness.git("add", ".fleet")
    harness.git(
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-m",
        "commit fleet config",
    )
    with pytest.raises(FleetError) as captured:
        harness.container.patches.apply(run.run_id)
    assert captured.value.code is ErrorCode.PATCH_TARGET_DIVERGED
    assert (harness.repository_root / "src/canary_calc/core.py").read_text() == BROKEN_CANARY


@pytest.mark.integration
@pytest.mark.asyncio
async def test_init_emits_proposal_and_exposes_disposable_canary(harness: FleetHarness) -> None:
    project = harness.container.state.get_project_by_root(str(harness.repository_root.resolve()))
    assert project is not None
    assert (harness.repository_root / ".fleet/fleet.yaml").exists()
    canary = harness.state_root / "projects" / project.project_id / "canaries" / "bootstrap"
    assert (canary / ".git").exists()
    with harness.container.state._connect() as connection:
        proposal_artifacts = connection.execute(
            "SELECT data_json FROM artifacts WHERE project_id = ? AND run_id IS NULL",
            (project.project_id,),
        ).fetchall()
    artifact_kinds = {json.loads(row["data_json"])["kind"] for row in proposal_artifacts}
    assert {
        "fleet_config_proposal",
        "repository_profile",
        "project_knowledge",
    } <= artifact_kinds
    assert project.repository_profile_artifact_id is not None
    assert project.project_knowledge_artifact_id is not None
    assert project.config_snapshot_artifact_id is not None
    assert "config_snapshot" in artifact_kinds


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "relative_path",
    ["project/verification.yaml", "agents/engineer.md"],
)
async def test_run_rejects_drift_in_every_referenced_config_file(
    harness: FleetHarness,
    relative_path: str,
) -> None:
    path = harness.repository_root / ".fleet" / relative_path
    path.write_text(path.read_text(encoding="utf-8") + "\n# content drift\n", encoding="utf-8")

    with pytest.raises(FleetError) as captured:
        await harness.start()

    assert captured.value.code is ErrorCode.CONFIG_INVALID
    with harness.container.state._connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_secret_sentinel_is_absent_from_persistent_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sentinel = "FLEET-SUPER-SECRET-SENTINEL"
    monkeypatch.setenv("AGENT_FLEET_REDACT_VALUES", sentinel)
    bootstrap = build_container(tmp_path / "fixture-tools")
    repository_root = bootstrap.repository.create_canary_fixture(
        tmp_path / "fixture-tools" / "target"
    )
    state_root = tmp_path / "redacted-state"
    container = build_container(state_root)
    container.projects.initialize(repository_root, runtime_name="fake", sandbox_name="fake")
    run = await container.workflow.start(
        project_path=repository_root,
        goal=f"Fix the canary behavior; never reveal {sentinel}",
        runtime_name="fake",
        sandbox_name="fake",
        fake_scenario=FakeScenario.SUCCESS,
    )
    assert run.status is RunStatus.READY_FOR_REVIEW
    paused = await container.workflow.start(
        project_path=repository_root,
        goal="Exercise approval redaction",
        runtime_name="fake",
        sandbox_name="fake",
        fake_scenario=FakeScenario.APPROVAL,
    )
    assert paused.pending_approval_id is not None
    container.approvals.deny(paused.pending_approval_id, f"do not expose {sentinel}")
    for path in state_root.rglob("*"):
        if path.is_file():
            assert sentinel.encode() not in path.read_bytes(), path
    assert all(not request.environment for request in container.sandbox.requests)
