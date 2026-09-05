from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from conftest import FleetHarness
from pydantic import ValidationError

from agent_fleet.application.permission_policy import (
    PolicyPermissionBroker,
    _requested_by_organization,
    _validated_scope,
)
from agent_fleet.bootstrap import build_container
from agent_fleet.domain.config import FleetSpec
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import (
    ApprovalChoice,
    ApprovalStatus,
    FakeScenario,
    FleetEvent,
    IntentStatus,
    PermissionOutcome,
    RunStatus,
)
from agent_fleet.domain.security import Redactor, canonical_json_hash
from agent_fleet.domain.trust import (
    ExactPermissionScope,
    ProjectTrustSettings,
    TrustMode,
    UserTrustPolicy,
)


@pytest.mark.parametrize(
    "paths",
    [
        ("AUDIT-REGISTERED-SECRET/../outside",),
        ("src/AUDIT-REGISTERED-SECRET.py",),
        ("src/../outside",),
        ("src/*",),
        (),
    ],
)
def test_invalid_reviewed_paths_are_rejected_before_repository_or_state_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, paths: tuple[str, ...]
) -> None:
    sentinel = "AUDIT-REGISTERED-SECRET"
    state_root = tmp_path / "uncreated-state"
    container = build_container(state_root, migrate=False, redactor=Redactor([sentinel]))

    def reject_repository_access(path: Path) -> None:
        raise AssertionError("invalid settings reached repository inspection")

    monkeypatch.setattr(container.permissions, "project_at", reject_repository_access)
    with pytest.raises(FleetError) as captured:
        container.permissions.configure(
            tmp_path / "uninspected-repository", mode=TrustMode.SAFE, allowed_paths=paths
        )
    assert captured.value.code is ErrorCode.APPROVAL_INVALID
    assert sentinel not in str(captured.value)
    assert captured.value.__cause__ is None
    assert not state_root.exists()


def test_invalid_scope_boundary_hides_untrusted_validation_values() -> None:
    sentinel = "AUDIT-SCOPE-SECRET"
    with pytest.raises(FleetError) as captured:
        _validated_scope(action="command.run", parameters={"bad": sentinel})
    assert captured.value.code is ErrorCode.COMMAND_DENIED
    assert sentinel not in str(captured.value)
    assert captured.value.__cause__ is None


@pytest.mark.asyncio
async def test_revoked_consumed_reservation_cannot_execute_approval_fixture(
    harness: FleetHarness,
) -> None:
    paused = await harness.start(FakeScenario.APPROVAL)
    assert paused.pending_approval_id is not None
    request = harness.container.state.get_approval(paused.pending_approval_id)
    grant = harness.container.approvals.approve_once(request.request_id)
    reserved = harness.container.state.consume_grant_and_reserve(
        request.request_id, request.intent_hash
    )
    assert reserved.status is IntentStatus.RESERVED
    harness.container.permissions.revoke(grant.grant_id)

    with pytest.raises(FleetError) as captured:
        await harness.container.workflow.resume(paused.run_id)
    assert captured.value.code is ErrorCode.APPROVAL_INVALID
    assert (
        harness.container.state.count_executed_intents(paused.run_id, "fixture.record_side_effect")
        == 0
    )
    assert harness.container.state.get_run(paused.run_id).status is RunStatus.FAILED


@pytest.mark.parametrize("choice", [ApprovalChoice.ALLOW_ONCE, ApprovalChoice.ALLOW_RUN])
@pytest.mark.asyncio
async def test_project_reset_invalidates_active_once_and_run_grants(
    harness: FleetHarness, choice: ApprovalChoice
) -> None:
    paused = await harness.start(FakeScenario.APPROVAL)
    assert paused.pending_approval_id is not None
    assert paused.task_id is not None
    assert paused.sandbox_capabilities_snapshot is not None
    grant = harness.container.approvals.approve(paused.pending_approval_id, choice=choice)
    request = harness.container.state.get_approval(paused.pending_approval_id)
    stored = harness.container.state.get_intent(request.intent_id)
    task = harness.container.state.get_task(paused.task_id)
    broker = PolicyPermissionBroker(harness.container.permissions)
    before = broker.evaluate(stored.intent, task, paused.sandbox_capabilities_snapshot)
    assert before.outcome is PermissionOutcome.ALLOW
    assert before.grant_id == grant.grant_id
    if choice is ApprovalChoice.ALLOW_RUN:
        assert grant.expires_at is None and grant.remaining_uses is None

    harness.container.permissions.reset(harness.repository_root)
    grants = harness.container.state.list_grants(paused.run_id)
    assert next(item for item in grants if item.grant_id == grant.grant_id).revoked_at is not None
    after = broker.evaluate(stored.intent, task, paused.sandbox_capabilities_snapshot)
    assert after.outcome is PermissionOutcome.REQUIRE_APPROVAL


@pytest.mark.asyncio
async def test_staged_always_rule_needs_committed_matching_approval_and_respects_revoke(
    harness: FleetHarness,
) -> None:
    paused = await harness.start(FakeScenario.APPROVAL)
    assert paused.pending_approval_id is not None
    assert paused.task_id is not None
    assert paused.sandbox_capabilities_snapshot is not None
    request = harness.container.state.get_approval(paused.pending_approval_id)
    assert request.authorization_scope is not None
    scope = ExactPermissionScope.model_validate(request.authorization_scope)
    rule = harness.container.permissions.stage_always_rule(request.request_id, scope)
    broker = PolicyPermissionBroker(harness.container.permissions)
    stored = harness.container.state.get_intent(request.intent_id)
    task = harness.container.state.get_task(paused.task_id)
    assert harness.container.state.get_approval(request.request_id).status is ApprovalStatus.PENDING
    assert not harness.container.permissions.rule_is_active(rule)
    assert (
        broker.evaluate(stored.intent, task, paused.sandbox_capabilities_snapshot).outcome
        is PermissionOutcome.REQUIRE_APPROVAL
    )

    harness.container.approvals.approve(request.request_id, choice=ApprovalChoice.ALLOW_ALWAYS)
    assert harness.container.permissions.rule_is_active(rule)
    assert (
        broker.evaluate(stored.intent, task, paused.sandbox_capabilities_snapshot).outcome
        is PermissionOutcome.ALLOW
    )
    harness.container.permissions.revoke(rule.rule_id)
    assert (
        broker.evaluate(stored.intent, task, paused.sandbox_capabilities_snapshot).outcome
        is PermissionOutcome.REQUIRE_APPROVAL
    )


def _project_policy_events(harness: FleetHarness) -> list[FleetEvent]:
    with sqlite3.connect(harness.container.state.database_path) as connection:
        rows = connection.execute(
            "SELECT data_json FROM run_events WHERE run_id IS NULL "
            "AND event_type LIKE 'permission.%' ORDER BY sequence"
        ).fetchall()
    return [FleetEvent.model_validate_json(row[0]) for row in rows]


def _state_failure() -> FleetError:
    return FleetError(
        ErrorCode.STATE_UNAVAILABLE, "Injected storage failure.", "Retry after recovery."
    )


def test_prepared_audit_failure_prevents_effective_policy_change(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = harness.container.permissions.trust.load()
    append = harness.container.state.append_event

    def fail_preparation(event: FleetEvent) -> FleetEvent:
        if event.event_type == "permission.policy_change_prepared":
            raise _state_failure()
        return append(event)

    monkeypatch.setattr(harness.container.state, "append_event", fail_preparation)
    with pytest.raises(FleetError):
        harness.container.permissions.configure(
            harness.repository_root, mode=TrustMode.SAFE, allowed_paths=("src",)
        )
    assert harness.container.permissions.trust.load() == before
    assert not _project_policy_events(harness)


def test_publication_failure_retains_prepared_exact_revision_evidence(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = harness.container.permissions.trust.load()

    def fail_publish(policy: UserTrustPolicy, *, expected_revision: int) -> UserTrustPolicy:
        raise _state_failure()

    monkeypatch.setattr(harness.container.permissions.trust, "save", fail_publish)
    with pytest.raises(FleetError):
        harness.container.permissions.configure(
            harness.repository_root, mode=TrustMode.SAFE, allowed_paths=("src",)
        )
    assert harness.container.permissions.trust.load() == before
    events = _project_policy_events(harness)
    assert [event.event_type for event in events] == ["permission.policy_change_prepared"]
    assert events[0].payload["expected_revision"] == before.revision
    assert events[0].payload["published_revision"] == before.revision + 1
    assert events[0].payload["previous_policy_sha256"] == canonical_json_hash(
        before.model_dump(mode="json")
    )


def test_failed_completion_has_prepared_proof_of_exact_published_policy_and_safe_retry(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    append = harness.container.state.append_event

    def fail_completion(event: FleetEvent) -> FleetEvent:
        if event.event_type == "permission.policy_change_completed":
            raise _state_failure()
        return append(event)

    with monkeypatch.context() as patch:
        patch.setattr(harness.container.state, "append_event", fail_completion)
        with pytest.raises(FleetError):
            harness.container.permissions.configure(
                harness.repository_root, mode=TrustMode.SAFE, allowed_paths=("src",)
            )
    published = harness.container.permissions.trust.load()
    prepared = _project_policy_events(harness)[0]
    assert prepared.event_type == "permission.policy_change_prepared"
    assert prepared.payload["published_revision"] == published.revision
    assert prepared.payload["published_policy_sha256"] == canonical_json_hash(
        published.model_dump(mode="json")
    )
    assert published.projects[0].trust_mode is TrustMode.SAFE
    assert published.projects[0].allowed_paths == ("src",)
    harness.container.permissions.configure(
        harness.repository_root,
        mode=TrustMode.SAFE,
        allowed_paths=None,
        expected_revision=published.revision,
    )
    events = _project_policy_events(harness)
    assert [event.event_type for event in events] == [
        "permission.policy_change_prepared",
        "permission.policy_change_prepared",
        "permission.policy_change_completed",
    ]
    assert events[-1].payload == events[-2].payload
    assert events[-1].correlation_id == events[-2].correlation_id
    assert (
        events[-1].payload["previous_policy_sha256"] == prepared.payload["published_policy_sha256"]
    )


@pytest.mark.parametrize("choice", [ApprovalChoice.ALLOW_ONCE, ApprovalChoice.ALLOW_RUN])
@pytest.mark.asyncio
async def test_reset_cutoff_blocks_grants_when_sql_revoke_fails_and_survives_configure(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch, choice: ApprovalChoice
) -> None:
    paused = await harness.start(FakeScenario.APPROVAL)
    assert paused.pending_approval_id is not None
    assert paused.task_id is not None
    assert paused.sandbox_capabilities_snapshot is not None
    grant = harness.container.approvals.approve(paused.pending_approval_id, choice=choice)
    request = harness.container.state.get_approval(paused.pending_approval_id)
    stored = harness.container.state.get_intent(request.intent_id)
    task = harness.container.state.get_task(paused.task_id)
    project = harness.container.state.get_project(paused.project_id)

    def fail_revoke(identifier: str) -> None:
        raise _state_failure()

    with monkeypatch.context() as patch:
        patch.setattr(harness.container.state, "revoke_grant", fail_revoke)
        with pytest.raises(FleetError):
            harness.container.permissions.reset(harness.repository_root)
    assert harness.container.state.get_grant(grant.grant_id).revoked_at is None
    settings = harness.container.permissions.settings(project)
    assert settings.grants_revoked_before is not None
    assert settings.grants_revoked_before >= grant.issued_at
    assert settings.allowed_paths == (".",)
    broker = PolicyPermissionBroker(harness.container.permissions)
    assert (
        broker.evaluate(stored.intent, task, paused.sandbox_capabilities_snapshot).outcome
        is PermissionOutcome.REQUIRE_APPROVAL
    )
    prepared = [
        event
        for event in _project_policy_events(harness)
        if event.event_type == "permission.policy_change_prepared"
    ]
    assert prepared[-1].payload["action"] == "permission.project_reset"
    assert prepared[-1].payload["published_policy_sha256"] == canonical_json_hash(
        harness.container.permissions.trust.load().model_dump(mode="json")
    )
    harness.container.permissions.configure(
        harness.repository_root, mode=TrustMode.SAFE, allowed_paths=("src",)
    )
    assert (
        harness.container.permissions.settings(project).grants_revoked_before
        == settings.grants_revoked_before
    )
    harness.container.permissions.reset(harness.repository_root)
    later = harness.container.permissions.settings(project)
    assert later.grants_revoked_before is not None
    assert later.grants_revoked_before > settings.grants_revoked_before
    assert later.allowed_paths == ("src",)


@pytest.mark.parametrize("boundary", ["role", "workflow", "request"])
@pytest.mark.asyncio
async def test_modern_fixture_cannot_bypass_organization_ceiling(
    harness: FleetHarness, boundary: str
) -> None:
    paused = await harness.start(FakeScenario.APPROVAL)
    assert paused.pending_approval_id is not None
    request = harness.container.state.get_approval(paused.pending_approval_id)
    stored = harness.container.state.get_intent(request.intent_id)
    spec, _ = harness.container.permissions.config.load_snapshot(
        harness.repository_root / ".fleet" / "fleet.yaml"
    )
    assert _requested_by_organization(spec, stored.intent)
    raw = spec.model_dump(mode="json", by_alias=True)
    if boundary == "role":
        raw["spec"]["agents"]["engineer"]["allowedTools"] = []
    elif boundary == "workflow":
        raw["spec"]["workflows"][stored.intent.workflow]["allowedTools"] = []
    else:
        raw["spec"]["requestedPermissions"] = [
            item
            for item in raw["spec"]["requestedPermissions"]
            if item["action"] != "fixture.record_side_effect"
        ]
    changed = FleetSpec.model_validate(raw)
    assert not _requested_by_organization(changed, stored.intent)
    assert harness.container.state.count_executed_intents(paused.run_id, stored.intent.action) == 0


def test_initialization_review_preserves_explicit_scope_without_state_access(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness.container.permissions.configure(
        harness.repository_root, mode=TrustMode.SAFE, allowed_paths=("src",)
    )
    before = harness.container.permissions.trust.load()

    def forbid_state_access() -> None:
        raise AssertionError("initialization review accessed SQLite")

    monkeypatch.setattr(harness.container.state, "_connect", forbid_state_access)
    reviewed = harness.container.permissions.review_initialization(
        harness.repository_root, mode=None, allowed_paths=None
    )
    assert reviewed["trust_mode"] == "safe"
    assert reviewed["allowed_paths"] == ["src"]
    assert reviewed["policy_revision"] == before.revision
    assert harness.container.permissions.trust.load() == before


def test_reviewed_revision_conflict_changes_neither_policy_nor_audit(harness: FleetHarness) -> None:
    reviewed = harness.container.permissions.review_initialization(
        harness.repository_root, mode=None, allowed_paths=None
    )
    harness.container.permissions.configure(
        harness.repository_root, mode=TrustMode.SAFE, allowed_paths=("src",)
    )
    current = harness.container.permissions.trust.load()
    events = _project_policy_events(harness)
    revision = reviewed["policy_revision"]
    assert isinstance(revision, int)
    with pytest.raises(FleetError):
        harness.container.permissions.configure(
            harness.repository_root,
            mode=TrustMode.BALANCED,
            allowed_paths=(".",),
            expected_revision=revision,
        )
    assert harness.container.permissions.trust.load() == current
    assert _project_policy_events(harness) == events


def test_initialization_review_rejects_conflicting_same_repository_registrations(
    harness: FleetHarness,
) -> None:
    project = harness.container.permissions.project_at(harness.repository_root)
    policies = UserTrustPolicy(
        projects=[
            ProjectTrustSettings(
                project_id=project.project_id,
                repository_identity=project.identity_hash,
                trust_mode=TrustMode.SAFE,
                allowed_paths=("src",),
            ),
            ProjectTrustSettings(
                project_id="prj_" + "f" * 32,
                repository_identity=project.identity_hash,
                trust_mode=TrustMode.BALANCED,
                allowed_paths=(".",),
            ),
        ]
    )
    harness.container.permissions.trust.save(policies, expected_revision=0)
    with pytest.raises(FleetError):
        harness.container.permissions.review_initialization(
            harness.repository_root, mode=None, allowed_paths=None
        )


@pytest.mark.parametrize(
    "timestamp", [datetime(2026, 9, 5), datetime(2026, 9, 5, tzinfo=timezone(timedelta(hours=1)))]
)
def test_project_grant_cutoff_requires_explicit_utc(timestamp: datetime) -> None:
    with pytest.raises(ValidationError):
        ProjectTrustSettings(
            project_id="prj_" + "1" * 32,
            repository_identity="a" * 64,
            grants_revoked_before=timestamp,
        )


def test_project_grant_cutoff_defaults_compatibly_and_round_trips() -> None:
    settings = ProjectTrustSettings(project_id="prj_" + "1" * 32, repository_identity="a" * 64)
    assert settings.grants_revoked_before is None
    updated = settings.model_copy(
        update={"grants_revoked_before": datetime(2026, 9, 5, tzinfo=UTC)}
    )
    assert ProjectTrustSettings.model_validate_json(updated.model_dump_json()) == updated


@pytest.mark.asyncio
async def test_project_reset_cutoff_does_not_revoke_another_projects_grant(
    harness: FleetHarness,
) -> None:
    paused = await harness.start(FakeScenario.APPROVAL)
    assert paused.pending_approval_id is not None
    grant = harness.container.approvals.approve(
        paused.pending_approval_id, choice=ApprovalChoice.ALLOW_RUN
    )
    request = harness.container.state.get_approval(paused.pending_approval_id)
    assert request.authorization_scope is not None
    scope = ExactPermissionScope.model_validate(request.authorization_scope)
    stored = harness.container.state.get_intent(request.intent_id)
    unrelated = ProjectTrustSettings(
        project_id="prj_" + "f" * 32,
        repository_identity="f" * 64,
        grants_revoked_before=grant.issued_at + timedelta(days=1),
    )
    broker = PolicyPermissionBroker(harness.container.permissions)
    assert broker._grant_matches(grant, stored.intent, scope, UserTrustPolicy(projects=[unrelated]))
    matching = unrelated.model_copy(
        update={"project_id": scope.project_id, "repository_identity": scope.repository_identity}
    )
    assert not broker._grant_matches(
        grant, stored.intent, scope, UserTrustPolicy(projects=[matching])
    )


def test_invalid_full_policy_never_writes_prepared_audit(harness: FleetHarness) -> None:
    project = harness.container.permissions.project_at(harness.repository_root)
    previous = harness.container.permissions.trust.load()
    invalid = ProjectTrustSettings(
        project_id=project.project_id, repository_identity=project.identity_hash
    ).model_copy(update={"repository_identity": "invalid"})
    proposed = previous.model_copy(update={"projects": [invalid]})
    with pytest.raises(FleetError):
        harness.container.permissions._publish_policy_change(
            project.project_id, "permission.policy_updated", previous, proposed, {}
        )
    assert not _project_policy_events(harness)
    assert harness.container.permissions.trust.load() == previous


def test_prepared_and_completed_audit_redact_diagnostics(harness: FleetHarness) -> None:
    sentinel = "AUDIT-DIAGNOSTIC-REGISTERED-SECRET"
    service = harness.container.permissions
    service.redactor.register_secret(sentinel)
    project = service.project_at(harness.repository_root)
    previous = service.trust.load()
    service._publish_policy_change(
        project.project_id,
        "permission.policy_updated",
        previous,
        previous,
        {"operator_note": sentinel},
    )
    events = _project_policy_events(harness)
    assert len(events) == 2
    assert all(
        sentinel not in event.model_dump_json() and event.redaction_summary for event in events
    )
    assert events[0].payload == events[1].payload


@pytest.mark.parametrize("resolution", ["approve", "deny"])
@pytest.mark.asyncio
async def test_terminal_request_explain_returns_historical_decisions(
    harness: FleetHarness, resolution: str
) -> None:
    paused = await harness.start(FakeScenario.APPROVAL)
    assert paused.pending_approval_id is not None
    active = harness.container.permissions.explain(paused.pending_approval_id)
    assert active["historical"] is False
    assert active["current_decision"] is not None
    if resolution == "approve":
        harness.container.approvals.approve_once(paused.pending_approval_id)
    else:
        harness.container.approvals.deny(paused.pending_approval_id)
    completed = await harness.container.workflow.resume(paused.run_id)
    assert completed.status in {RunStatus.READY_FOR_REVIEW, RunStatus.REJECTED}
    historical = harness.container.permissions.explain(paused.pending_approval_id)
    assert historical["historical"] is True
    assert historical["current_decision"] is None
    records = historical["recorded_decisions"]
    assert isinstance(records, list) and records
    assert all(
        isinstance(record, dict) and record["event_type"] == "permission.decision"
        for record in records
    )


@pytest.mark.parametrize(
    "choice", [ApprovalChoice.ALLOW_ONCE, ApprovalChoice.ALLOW_RUN, ApprovalChoice.ALLOW_ALWAYS]
)
@pytest.mark.asyncio
async def test_permission_list_exposes_grant_ids_lifetime_and_revocation_status(
    harness: FleetHarness, choice: ApprovalChoice
) -> None:
    paused = await harness.start(FakeScenario.APPROVAL)
    assert paused.pending_approval_id is not None
    grant = harness.container.approvals.approve(paused.pending_approval_id, choice=choice)
    listing = harness.container.permissions.list_rules(harness.repository_root)
    records = listing["grants"]
    assert isinstance(records, list)
    row = next(
        item for item in records if isinstance(item, dict) and item["grant_id"] == grant.grant_id
    )
    assert isinstance(row, dict)
    assert row["lifetime"] == choice.value
    assert row["status"] == "available" and row["cutoff_revoked"] is False
    harness.container.permissions.revoke(grant.grant_id)
    after = harness.container.permissions.list_rules(harness.repository_root)["grants"]
    assert isinstance(after, list)
    row = next(
        item for item in after if isinstance(item, dict) and item["grant_id"] == grant.grant_id
    )
    assert isinstance(row, dict) and row["status"] == "revoked"
