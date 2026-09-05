"""Persisted permission behavior with simulated commands, never execution/isolation proof."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Never

import pytest
import yaml
from conftest import FleetHarness

from agent_fleet.adapters.repository.git import GitRepositoryAdapter
from agent_fleet.adapters.system import UuidIdGenerator
from agent_fleet.bootstrap import ApplicationContainer, build_container
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.evidence import CommandEvidence, EvidenceStrength
from agent_fleet.domain.models import (
    ApprovalChoice,
    ApprovalRequest,
    ApprovalStatus,
    CapabilityGrant,
    FakeScenario,
    IntentStatus,
    Run,
    RunStatus,
    SandboxConfiguration,
    WorkflowStage,
)
from agent_fleet.domain.repository_profile import RepositoryProfile
from agent_fleet.domain.trust import ExactPermissionScope, TrustMode, UserTrustRule

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]
_COMMAND_IDS = ("python-build", "python-test")


def _request(container: ApplicationContainer, run: Run, role: str) -> ApprovalRequest:
    assert run.status is RunStatus.PAUSED_FOR_APPROVAL
    assert run.pending_approval_id is not None
    request = container.state.get_approval(run.pending_approval_id)
    assert request.status is ApprovalStatus.PENDING
    assert request.principal_role == role
    assert request.action == "command.run"
    scope = ExactPermissionScope.model_validate(request.authorization_scope)
    assert scope.principal_role == role
    assert scope.sandbox_provider == "fake"
    assert scope.network_mode == "none"
    assert scope.command is not None
    assert scope.resource.identifier == scope.command.command_id
    assert scope.stage is (
        WorkflowStage.IMPLEMENTING if role == "engineer" else WorkflowStage.VERIFYING
    )
    return request


async def _start(container: ApplicationContainer, repository: Path) -> Run:
    return await container.workflow.start(
        project_path=repository,
        goal="Fix the canary behavior",
        runtime_name="fake",
        sandbox_name="fake",
        fake_scenario=FakeScenario.SUCCESS,
    )


async def _safe_start(harness: FleetHarness) -> Run:
    harness.container.permissions.configure(
        harness.repository_root, mode=TrustMode.SAFE, allowed_paths=(".",)
    )
    return await _start(build_container(harness.state_root), harness.repository_root)


async def _approve_pair(
    harness: FleetHarness, run: Run, choice: ApprovalChoice
) -> tuple[ApplicationContainer, Run, list[CapabilityGrant]]:
    grants: list[CapabilityGrant] = []
    for role in ("engineer", "verifier"):
        for command_id in _COMMAND_IDS:
            approving = build_container(harness.state_root)
            request = _request(approving, run, role)
            assert request.resource.identifier == command_id
            grants.append(approving.approvals.approve(request.request_id, choice=choice))
            resuming = build_container(harness.state_root)
            run = await resuming.workflow.resume(run.run_id)
    assert run.status is RunStatus.READY_FOR_REVIEW
    assert run.verified_complete is False
    return resuming, run, grants


def _rules(container: ApplicationContainer, project_id: str) -> list[UserTrustRule]:
    return [
        rule
        for rule in container.permissions.trust.load().rules
        if rule.scope.project_id == project_id
    ]


def _assert_four_simulated_commands(container: ApplicationContainer, run: Run) -> None:
    assert container.state.count_executed_intents(run.run_id, "command.run") == 4
    assert len(run.command_evidence_artifact_ids) == 4
    for artifact_id in run.command_evidence_artifact_ids:
        evidence = CommandEvidence.model_validate_json(container.artifacts.read_text(artifact_id))
        assert evidence.strength is EvidenceStrength.SIMULATED
        assert evidence.sandbox_provider == "fake"
    assert run.verified_complete is False


@pytest.mark.parametrize(
    "choice", [ApprovalChoice.ALLOW_ONCE, ApprovalChoice.ALLOW_RUN, ApprovalChoice.ALLOW_ALWAYS]
)
async def test_safe_command_choices_survive_reconstruction_without_role_scope_expansion(
    harness: FleetHarness, choice: ApprovalChoice
) -> None:
    paused = await _safe_start(harness)
    assert harness.container.state.count_executed_intents(paused.run_id, "command.run") == 0
    container, ready, grants = await _approve_pair(harness, paused, choice)
    _assert_four_simulated_commands(container, ready)
    assert {grant.principal_role for grant in grants} == {"engineer", "verifier"}
    assert all(grant.choice is choice for grant in grants)
    assert len({grant.scope_sha256 for grant in grants}) == 4
    assert all(
        container.state.get_grant(grant.grant_id).remaining_uses
        == (0 if choice is ApprovalChoice.ALLOW_ONCE else None)
        for grant in grants
    )
    events = container.state.list_events(ready.run_id)
    assert len([event for event in events if event.event_type == "approval.requested"]) == 4
    assert len([event for event in events if event.event_type == "approval.resolved"]) == 4
    assert len([event for event in events if event.event_type == "capability.consumed"]) == 4
    assert [event.sequence for event in events] == list(range(1, len(events) + 1))

    reopened = build_container(harness.state_root)
    repeated = await reopened.workflow.resume(ready.run_id)
    assert repeated == ready
    assert reopened.state.list_events(ready.run_id) == events
    _assert_four_simulated_commands(reopened, repeated)

    next_run = await _start(reopened, harness.repository_root)
    if choice is ApprovalChoice.ALLOW_ALWAYS:
        assert next_run.status is RunStatus.READY_FOR_REVIEW
        _assert_four_simulated_commands(reopened, next_run)
        receipts = reopened.state.list_grants(next_run.run_id)
        assert len(receipts) == 4
        original_rules = {rule.rule_id: rule for rule in _rules(reopened, ready.project_id)}
        next_events = reopened.state.list_events(next_run.run_id)
        assert not [event for event in next_events if event.event_type.startswith("approval.")]
        with reopened.state._connect() as connection:
            assert (
                connection.execute(
                    "SELECT COUNT(*) FROM approvals WHERE run_id = ?", (next_run.run_id,)
                ).fetchone()[0]
                == 0
            )
        for receipt in receipts:
            assert receipt.request_id is None
            assert receipt.choice is ApprovalChoice.ALLOW_ALWAYS
            assert receipt.remaining_uses == 0
            assert receipt.consumed_at is not None
            assert receipt.source_rule_id is not None
            rule = original_rules[receipt.source_rule_id]
            assert receipt.scope_sha256 == rule.scope.scope_sha256
            assert receipt.project_id == rule.scope.project_id == ready.project_id
            assert receipt.run_id == next_run.run_id
            assert receipt.principal_role == rule.scope.principal_role
            assert receipt.resource == rule.scope.resource
            stored = reopened.state.get_intent(receipt.intent_id)
            assert stored.status is IntentStatus.EXECUTED
            assert stored.approval_request_id is None
            assert stored.intent_hash == receipt.intent_hash
            assert stored.intent.agent_instance_id == receipt.agent_instance_id
            assert stored.intent.parameters == rule.scope.parameters
            lifecycle = [
                event
                for event in next_events
                if event.event_type in {"capability.issued", "capability.consumed"}
                and event.payload.get("grant_id") == receipt.grant_id
            ]
            assert [event.event_type for event in lifecycle] == [
                "capability.issued",
                "capability.consumed",
            ]
            assert all(
                event.payload.get("source_rule_id") == receipt.source_rule_id
                and event.payload.get("scope_sha256") == receipt.scope_sha256
                and event.payload.get("intent_id") == receipt.intent_id
                for event in lifecycle
            )
            assert [event.payload.get("remaining_uses") for event in lifecycle] == [1, 0]
        assert len([event for event in next_events if event.event_type == "capability.issued"]) == 4
        assert (
            len([event for event in next_events if event.event_type == "capability.consumed"]) == 4
        )
        matching = [
            event
            for event in next_events
            if event.event_type == "permission.decision"
            and event.payload.get("decision_code") == "EXACT_PROJECT_TRUST"
        ]
        assert len(matching) == 4
        assert {event.payload.get("source_rule_id") for event in matching} == {
            grant.source_rule_id for grant in grants
        }
        once_more = build_container(harness.state_root)
        assert await once_more.workflow.resume(next_run.run_id) == next_run
        assert once_more.state.list_grants(next_run.run_id) == receipts
        assert once_more.state.list_events(next_run.run_id) == next_events
    else:
        _request(reopened, next_run, "engineer")
        assert reopened.state.count_executed_intents(next_run.run_id, "command.run") == 0
        assert _rules(reopened, next_run.project_id) == []
        await reopened.cancellation.cancel(next_run.run_id)


@pytest.mark.parametrize(
    "choice", [ApprovalChoice.ALLOW_ONCE, ApprovalChoice.ALLOW_RUN, ApprovalChoice.ALLOW_ALWAYS]
)
async def test_repeating_exact_approval_after_reconstruction_is_idempotent(
    harness: FleetHarness, choice: ApprovalChoice
) -> None:
    paused = await _safe_start(harness)
    request = _request(harness.container, paused, "engineer")
    issued = build_container(harness.state_root).approvals.approve(
        request.request_id, choice=choice
    )
    reopened = build_container(harness.state_root)
    assert reopened.approvals.approve(request.request_id, choice=choice) == issued
    assert reopened.state.list_grants(paused.run_id) == [issued]
    assert (
        len(
            [
                event
                for event in reopened.state.list_events(paused.run_id)
                if event.event_type == "approval.resolved"
            ]
        )
        == 1
    )
    await reopened.cancellation.cancel(paused.run_id)


async def test_exact_project_rules_explain_revoke_and_reset_across_reconstruction(
    harness: FleetHarness,
) -> None:
    paused = await _safe_start(harness)
    container, ready, _ = await _approve_pair(harness, paused, ApprovalChoice.ALLOW_ALWAYS)
    rules = _rules(container, ready.project_id)
    assert len(rules) == 4
    engineer = next(
        rule
        for rule in rules
        if rule.scope.principal_role == "engineer"
        and rule.scope.resource.identifier == "python-build"
    )
    explanation = container.permissions.explain(engineer.rule_id)
    assert explanation["active"] is True
    assert explanation["scope"] == engineer.scope.model_dump(mode="json")
    assert "exact scope" in str(explanation["explanation"])
    listing = container.permissions.list_rules(harness.repository_root)
    assert listing["project_id"] == ready.project_id
    listed_rules = listing["rules"]
    assert isinstance(listed_rules, list) and len(listed_rules) == 4

    other_repository = GitRepositoryAdapter(harness.root, UuidIdGenerator()).create_canary_fixture(
        harness.root / "other-repository"
    )
    container.projects._initialize_without_canary(
        other_repository, runtime_name="fake", sandbox_name="fake"
    )
    container.permissions.configure(other_repository, mode=TrustMode.SAFE, allowed_paths=(".",))
    other_run = await _start(build_container(harness.state_root), other_repository)
    other_request = _request(container, other_run, "engineer")
    other_grant = container.approvals.approve(
        other_request.request_id, choice=ApprovalChoice.ALLOW_ALWAYS
    )
    assert other_grant.source_rule_id is not None
    assert other_run.project_id != ready.project_id
    assert container.state.count_executed_intents(other_run.run_id, "command.run") == 0

    container.permissions.revoke(engineer.rule_id)
    reopened = build_container(harness.state_root)
    assert reopened.permissions.explain(engineer.rule_id)["active"] is False
    next_run = await _start(reopened, harness.repository_root)
    _request(reopened, next_run, "engineer")
    assert reopened.state.count_executed_intents(next_run.run_id, "command.run") == 0
    await reopened.cancellation.cancel(next_run.run_id)

    reset = reopened.permissions.reset(harness.repository_root)
    assert reset["project_id"] == ready.project_id
    after_reset = build_container(harness.state_root)
    assert all(
        not after_reset.permissions.rule_is_active(rule)
        for rule in _rules(after_reset, ready.project_id)
    )
    assert after_reset.permissions.explain(other_grant.source_rule_id)["active"] is True
    settings = after_reset.permissions.list_rules(harness.repository_root)["settings"]
    assert isinstance(settings, dict)
    assert settings["trust_mode"] == TrustMode.SAFE.value
    assert settings["allowed_paths"] == ["."]
    await after_reset.cancellation.cancel(other_run.run_id)


async def test_revoked_always_rule_invalidates_an_approved_but_unconsumed_command(
    harness: FleetHarness,
) -> None:
    paused = await _safe_start(harness)
    request = _request(harness.container, paused, "engineer")
    approving = build_container(harness.state_root)
    grant = approving.approvals.approve(request.request_id, choice=ApprovalChoice.ALLOW_ALWAYS)
    assert grant.source_rule_id is not None
    approving.permissions.revoke(grant.source_rule_id)
    reopened = build_container(harness.state_root)
    with pytest.raises(FleetError) as denied:
        await reopened.workflow.resume(paused.run_id)
    assert denied.value.code is ErrorCode.APPROVAL_INVALID
    assert "current policy" in denied.value.message
    assert reopened.state.count_executed_intents(paused.run_id, "command.run") == 0
    assert reopened.state.get_intent(request.intent_id).status is IntentStatus.PENDING_APPROVAL
    assert not [
        event
        for event in reopened.state.list_events(paused.run_id)
        if event.event_type == "capability.consumed"
    ]
    assert reopened.state.get_run(paused.run_id).status is RunStatus.FAILED
    assert reopened.state.outstanding_leases(paused.run_id) == []


async def test_narrowed_user_scope_blocks_approved_resume_without_command_consumption(
    harness: FleetHarness,
) -> None:
    paused = await _safe_start(harness)
    request = _request(harness.container, paused, "engineer")
    harness.container.approvals.approve(request.request_id, choice=ApprovalChoice.ALLOW_RUN)
    harness.container.permissions.configure(
        harness.repository_root, mode=TrustMode.SAFE, allowed_paths=("tests",)
    )
    reopened = build_container(harness.state_root)
    with pytest.raises(FleetError) as denied:
        await reopened.workflow.resume(paused.run_id)
    assert denied.value.code is ErrorCode.APPROVAL_INVALID
    assert "path ceiling" in denied.value.message
    assert reopened.state.count_executed_intents(paused.run_id, "command.run") == 0
    assert not [
        event
        for event in reopened.state.list_events(paused.run_id)
        if event.event_type == "capability.consumed"
    ]
    assert reopened.state.outstanding_leases(paused.run_id) == []


async def test_failed_approval_activation_leaves_dormant_rule_and_retry_reuses_it(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    paused = await _safe_start(harness)
    request = _request(harness.container, paused, "engineer")
    approving = build_container(harness.state_root)

    def failed_resolution(*args: object, **kwargs: object) -> Never:
        raise RuntimeError("injected SQLite approval activation failure")

    with monkeypatch.context() as patch:
        patch.setattr(approving.state, "resolve_approval", failed_resolution)
        with pytest.raises(RuntimeError, match="approval activation failure"):
            approving.approvals.approve(request.request_id, choice=ApprovalChoice.ALLOW_ALWAYS)
    reopened = build_container(harness.state_root)
    staged = _rules(reopened, paused.project_id)
    assert len(staged) == 1
    assert reopened.permissions.rule_is_active(staged[0]) is False
    assert reopened.permissions.explain(staged[0].rule_id)["active"] is False
    assert reopened.state.get_approval(request.request_id).status is ApprovalStatus.PENDING
    assert reopened.state.list_grants(paused.run_id) == []
    assert reopened.state.count_executed_intents(paused.run_id, "command.run") == 0
    explanation = reopened.permissions.explain(request.request_id)["current_decision"]
    assert isinstance(explanation, dict)
    assert explanation["outcome"] == "require_approval"

    issued = reopened.approvals.approve(request.request_id, choice=ApprovalChoice.ALLOW_ALWAYS)
    assert issued.source_rule_id == staged[0].rule_id
    activated = build_container(harness.state_root)
    assert len(_rules(activated, paused.project_id)) == 1
    assert activated.permissions.rule_is_active(_rules(activated, paused.project_id)[0]) is True
    next_command_pause = await activated.workflow.resume(paused.run_id)
    next_request = _request(activated, next_command_pause, "engineer")
    assert next_request.resource.identifier == "python-test"
    assert next_request.resource != request.resource
    assert activated.state.count_executed_intents(paused.run_id, "command.run") == 1
    await activated.cancellation.cancel(paused.run_id)


@pytest.mark.parametrize("ceiling", ["role", "requested_permission", "workflow"])
async def test_registered_organization_can_remove_command_authority_without_self_granting(
    harness: FleetHarness,
    monkeypatch: pytest.MonkeyPatch,
    ceiling: Literal["role", "requested_permission", "workflow"],
) -> None:
    container = harness.container
    repository = GitRepositoryAdapter(harness.root, UuidIdGenerator()).create_canary_fixture(
        harness.root / "narrow-organization"
    )
    config = container.projects.config
    original_defaults = config.default_files

    def narrowed_defaults(
        repository_name: str,
        profile: RepositoryProfile | None = None,
        *,
        runtime_name: str = "fake",
        provider_model: str | None = None,
        sandbox_configuration: SandboxConfiguration | None = None,
        trusted_canary: bool = False,
    ) -> dict[str, str]:
        files = original_defaults(
            repository_name,
            profile,
            runtime_name=runtime_name,
            provider_model=provider_model,
            sandbox_configuration=sandbox_configuration,
            trusted_canary=trusted_canary,
        )
        spec = config.validate_files(files)
        if ceiling == "role":
            spec.spec.agents["engineer"].allowed_tools.remove("command.run")
        elif ceiling == "requested_permission":
            spec.spec.requested_permissions = [
                item
                for item in spec.spec.requested_permissions
                if not (item.principal_role == "engineer" and item.action == "command.run")
            ]
        else:
            spec.spec.workflows["code-change"].allowed_tools = ["workspace.write_file"]
        files["fleet.yaml"] = yaml.safe_dump(spec.model_dump(mode="json", by_alias=True))
        config.validate_files(files)
        return files

    with monkeypatch.context() as patch:
        patch.setattr(config, "default_files", narrowed_defaults)
        container.projects._initialize_without_canary(
            repository, runtime_name="fake", sandbox_name="fake"
        )
    container.permissions.configure(repository, mode=TrustMode.SAFE, allowed_paths=(".",))
    reopened = build_container(harness.state_root)
    with pytest.raises(FleetError) as denied:
        await _start(reopened, repository)
    assert denied.value.code is ErrorCode.COMMAND_DENIED
    assert denied.value.details["decision_code"] == "ORGANIZATION_PERMISSION_CEILING"
    run_id = str(denied.value.details["run_id"])
    assert reopened.state.get_run(run_id).status is RunStatus.FAILED
    assert reopened.state.count_executed_intents(run_id, "command.run") == 0
    assert reopened.state.list_grants(run_id) == []
    assert not [
        event
        for event in reopened.state.list_events(run_id)
        if event.event_type == "approval.requested"
    ]
    assert reopened.state.outstanding_leases(run_id) == []
