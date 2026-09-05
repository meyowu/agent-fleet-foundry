from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from importlib.resources import files
from pathlib import Path

import pytest
from pydantic import JsonValue, ValidationError

from agent_fleet.adapters.persistence.sqlite import SUPPORTED_SCHEMA_VERSION, SqliteStateStore
from agent_fleet.adapters.system import UuidIdGenerator
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.ids import IdPrefix
from agent_fleet.domain.models import (
    AcceptanceCriterion,
    AgentInstance,
    AgentStatus,
    ApprovalChoice,
    ApprovalRequest,
    CanonicalResource,
    CapabilityGrant,
    FleetEvent,
    IntentStatus,
    PermissionDecision,
    PermissionOutcome,
    Project,
    Run,
    RunStatus,
    TaskSpec,
    ToolIntent,
    WorkflowStage,
)
from agent_fleet.domain.security import Redactor, canonical_json_hash


@dataclass
class GrantClock:
    current: datetime = datetime(2026, 9, 5, tzinfo=UTC)

    def now(self) -> datetime:
        return self.current


@dataclass
class GrantFixture:
    state: SqliteStateStore
    clock: GrantClock
    request: ApprovalRequest
    source: ToolIntent
    scope_sha256: str | None

    def issue(self, choice: ApprovalChoice = ApprovalChoice.ALLOW_RUN) -> CapabilityGrant:
        grant = self.state.resolve_approval(
            self.request.request_id,
            approve=True,
            denial_reason=None,
            choice=choice,
            scope_sha256=self.scope_sha256,
            source_rule_id="rule_example" if choice is ApprovalChoice.ALLOW_ALWAYS else None,
        )
        assert grant is not None
        return grant

    def resume(self) -> None:
        run = self.state.get_run(self.source.run_id)
        self.state.save_run(
            run.model_copy(update={"status": RunStatus.RUNNING, "pending_approval_id": None}),
            "run.resumed",
            {},
        )

    def next_intent(self) -> ToolIntent:
        ids = self.state.ids
        agent_id = ids.new(IdPrefix.AGENT)
        self.state.save_agent_instance(
            AgentInstance(
                agent_instance_id=agent_id,
                run_id=self.source.run_id,
                task_id=self.source.task_id,
                role=self.source.principal_role,
                status=AgentStatus.RUNNING,
                iteration=0,
                created_at=self.clock.now(),
            )
        )
        return self.source.model_copy(
            update={
                "intent_id": ids.new(IdPrefix.INTENT),
                "agent_instance_id": agent_id,
                "idempotency_key": ids.new(IdPrefix.INTENT),
                "reason": "Repeat the exact reviewed action in a fresh agent invocation.",
            }
        )


def _fixture(
    tmp_path: Path,
    *,
    legacy: bool = False,
    database_path: Path | None = None,
    project: Project | None = None,
    pause: bool = True,
) -> GrantFixture:
    clock = GrantClock()
    ids = UuidIdGenerator()
    state = SqliteStateStore(database_path or tmp_path / "grants.db", clock, ids, Redactor())
    if legacy:
        with sqlite3.connect(state.database_path) as connection:
            connection.execute(
                "CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT)"
            )
            for version in range(1, 4):
                script = (
                    files("agent_fleet.adapters.persistence.migrations")
                    .joinpath(f"{version:04d}.sql")
                    .read_text(encoding="utf-8")
                )
                connection.executescript(script)
                connection.execute(
                    "INSERT INTO schema_migrations VALUES (?, ?)",
                    (version, clock.now().isoformat()),
                )
    else:
        state.migrate()
    project = project or Project(
        project_id=ids.new(IdPrefix.PROJECT),
        canonical_root=str(tmp_path / "repository"),
        identity_hash="1" * 64,
        created_at=clock.now(),
        updated_at=clock.now(),
    )
    state.save_project(project)
    task_id = ids.new(IdPrefix.TASK)
    run = Run(
        run_id=ids.new(IdPrefix.RUN),
        project_id=project.project_id,
        correlation_id=ids.new(IdPrefix.CORRELATION),
        goal="Scoped grant behavior",
        base_revision="a" * 40,
        target_status_fingerprint="2" * 64,
        status=RunStatus.RUNNING,
        stage=WorkflowStage.IMPLEMENTING,
        task_id=task_id,
        created_at=clock.now(),
        updated_at=clock.now(),
    )
    state.create_run(run)
    state.save_task(
        TaskSpec(
            task_id=task_id,
            run_id=run.run_id,
            original_goal=run.goal,
            normalized_goal=run.goal,
            base_revision=run.base_revision,
            allowed_paths=["src/core.py"],
            forbidden_paths=[],
            acceptance_criteria=[AcceptanceCriterion(criterion_id="ac-1", description="Works")],
            required_evidence=["canonical_patch", "command_evidence"],
            max_repair_iterations=1,
            config_snapshot_hash="3" * 64,
            created_at=clock.now(),
        )
    )
    agent = AgentInstance(
        agent_instance_id=ids.new(IdPrefix.AGENT),
        run_id=run.run_id,
        task_id=task_id,
        role="engineer",
        status=AgentStatus.RUNNING,
        iteration=0,
        created_at=clock.now(),
    )
    state.save_agent_instance(agent)
    source = ToolIntent(
        intent_id=ids.new(IdPrefix.INTENT),
        run_id=run.run_id,
        task_id=task_id,
        agent_instance_id=agent.agent_instance_id,
        principal_role="engineer",
        workflow="code-change",
        stage=WorkflowStage.IMPLEMENTING,
        action="command.run",
        resource=CanonicalResource(kind="project_command", identifier="pytest"),
        parameters={"command_spec_sha256": "4" * 64, "network_mode": "none"},
        reason="Run the exact reviewed test command.",
        side_effect=True,
        idempotency_key="initial-command",
    )
    scope: dict[str, JsonValue] | None = (
        None
        if legacy
        else {
            "project_id": project.project_id,
            "role": "engineer",
            "action": source.action,
            "resource": source.resource.model_dump(mode="json"),
            "parameters": source.parameters,
            "sandbox": "isolated",
        }
    )
    request = ApprovalRequest(
        request_id=ids.new(IdPrefix.APPROVAL),
        intent_id=source.intent_id,
        run_id=run.run_id,
        intent_hash=canonical_json_hash(source.model_dump(mode="json")),
        principal_role=source.principal_role,
        action=source.action,
        resource=source.resource,
        reason=source.reason,
        authorization_scope=scope,
        available_choices=list(ApprovalChoice),
        created_at=clock.now(),
        expires_at=clock.now() + timedelta(minutes=10),
    )
    if pause:
        state.create_approval_and_pause(source, request.intent_hash, request)
    return GrantFixture(
        state, clock, request, source, canonical_json_hash(scope) if scope else None
    )


@pytest.mark.parametrize("choice", [ApprovalChoice.ALLOW_RUN, ApprovalChoice.ALLOW_ALWAYS])
def test_scoped_grant_reopens_and_reserves_fresh_intents_once(
    tmp_path: Path, choice: ApprovalChoice
) -> None:
    fixture = _fixture(tmp_path)
    grant = fixture.issue(choice)
    fixture.state.consume_grant_and_reserve(fixture.request.request_id, fixture.request.intent_hash)
    fixture.resume()
    current = fixture.next_intent()
    reopened = SqliteStateStore(
        fixture.state.database_path, fixture.clock, UuidIdGenerator(), Redactor()
    )
    digest = canonical_json_hash(current.model_dump(mode="json"))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: reopened.consume_matching_grant_and_reserve(
                    grant.grant_id, current, digest, fixture.scope_sha256 or ""
                ),
                range(2),
            )
        )
    assert results[0] == results[1]
    assert results[0].status is IntentStatus.RESERVED
    assert results[0].intent.agent_instance_id != fixture.source.agent_instance_id
    assert reopened.get_grant(grant.grant_id).remaining_uses is None
    assert reopened.get_grant(grant.grant_id).expires_at is None
    assert reopened.list_grants(current.run_id) == [reopened.get_grant(grant.grant_id)]
    assert reopened.get_intent(current.intent_id) == results[0]
    consumed = [
        event
        for event in reopened.list_events(current.run_id)
        if event.event_type == "capability.consumed"
    ]
    assert len(consumed) == 2


def test_legacy_once_grant_migrates_without_restoring_spent_use(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path, legacy=True)
    grant = fixture.issue(ApprovalChoice.ALLOW_ONCE)
    fixture.state.consume_grant_and_reserve(fixture.request.request_id, fixture.request.intent_hash)
    legacy_data = fixture.state.get_grant(grant.grant_id).model_dump(mode="json")
    for key in ("choice", "scope_sha256", "revoked_at", "source_rule_id"):
        legacy_data.pop(key)
    with sqlite3.connect(fixture.state.database_path) as connection:
        connection.execute(
            "UPDATE capability_grants SET data_json = ? WHERE grant_id = ?",
            (json.dumps(legacy_data), grant.grant_id),
        )
    assert fixture.state.migrate() == SUPPORTED_SCHEMA_VERSION
    reopened = fixture.state.get_grant(grant.grant_id)
    assert reopened.choice is ApprovalChoice.ALLOW_ONCE
    assert reopened.remaining_uses == 0
    assert reopened.consumed_at is not None
    fixture.state.consume_grant_and_reserve(fixture.request.request_id, fixture.request.intent_hash)
    assert (
        len(
            [
                event
                for event in fixture.state.list_events(fixture.source.run_id)
                if event.event_type == "capability.consumed"
            ]
        )
        == 1
    )


def test_resolution_cannot_upgrade_or_change_scope_on_retry(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    grant = fixture.issue(ApprovalChoice.ALLOW_ONCE)
    assert fixture.issue(ApprovalChoice.ALLOW_ONCE) == grant
    with pytest.raises(FleetError, match="exact authorization context"):
        fixture.issue(ApprovalChoice.ALLOW_RUN)
    with pytest.raises(FleetError):
        fixture.state.resolve_approval(
            fixture.request.request_id,
            approve=True,
            denial_reason=None,
            scope_sha256="9" * 64,
        )
    assert fixture.state.get_grant(grant.grant_id) == grant


def test_unoffered_choice_and_wrong_scope_do_not_issue_a_grant(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    request = fixture.request.model_copy(
        update={"available_choices": [ApprovalChoice.DENY, ApprovalChoice.ALLOW_ONCE]}
    )
    with fixture.state._connect() as connection:
        connection.execute("UPDATE approvals SET data_json = ?", (request.model_dump_json(),))
    with pytest.raises(FleetError):
        fixture.issue(ApprovalChoice.ALLOW_RUN)
    with pytest.raises(FleetError):
        fixture.state.resolve_approval(
            request.request_id, approve=True, denial_reason=None, scope_sha256="9" * 64
        )
    assert fixture.state.list_grants(request.run_id) == []


@pytest.mark.parametrize("condition", ["revoked", "expired", "exhausted", "terminal"])
def test_invalid_current_grants_do_not_reserve_future_side_effects(
    tmp_path: Path, condition: str
) -> None:
    fixture = _fixture(tmp_path)
    grant = fixture.issue()
    fixture.resume()
    current = fixture.next_intent()
    if condition == "revoked":
        revoked = fixture.state.revoke_grant(grant.grant_id)
        assert fixture.state.revoke_grant(grant.grant_id) == revoked
        assert (
            len(
                [
                    event
                    for event in fixture.state.list_events(current.run_id)
                    if event.event_type == "capability.revoked"
                ]
            )
            == 1
        )
    elif condition == "expired":
        with fixture.state._connect() as connection:
            expiring = grant.model_copy(
                update={"expires_at": fixture.clock.now() + timedelta(minutes=5)}
            )
            connection.execute(
                "UPDATE capability_grants SET data_json = ?", (expiring.model_dump_json(),)
            )
        fixture.clock.current += timedelta(minutes=11)
    elif condition == "exhausted":
        with fixture.state._connect() as connection:
            spent = grant.model_copy(update={"remaining_uses": 0})
            connection.execute(
                "UPDATE capability_grants SET remaining_uses=0, data_json=?",
                (spent.model_dump_json(),),
            )
    else:
        run = fixture.state.get_run(current.run_id)
        fixture.state.save_run(
            run.model_copy(update={"status": RunStatus.CANCELLED}), "run.cancelled", {}
        )
    with pytest.raises(FleetError) as captured:
        fixture.state.consume_matching_grant_and_reserve(
            grant.grant_id,
            current,
            canonical_json_hash(current.model_dump(mode="json")),
            fixture.scope_sha256 or "",
        )
    assert captured.value.code is ErrorCode.APPROVAL_INVALID
    assert fixture.state.find_intent(current.run_id, current.idempotency_key) is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("project_id", "prj_" + "9" * 32),
        ("run_id", "run_" + "9" * 32),
        ("task_id", "task_" + "9" * 32),
        ("agent_instance_id", "agent_" + "9" * 32),
        ("principal_role", "verifier"),
        ("action", "workspace.write_file"),
        ("resource", {"kind": "project_command", "identifier": "publish"}),
        ("intent_hash", "9" * 64),
        ("intent_id", "intent_" + "9" * 32),
        ("request_id", "perm_" + "9" * 32),
        ("source_rule_id", "rule_foreign"),
        ("scope_sha256", "9" * 64),
    ],
)
def test_duplicate_grant_identity_fields_are_checked_before_consumption(
    tmp_path: Path, field: str, value: JsonValue
) -> None:
    fixture = _fixture(tmp_path)
    grant = fixture.issue()
    data = grant.model_dump(mode="json")
    data[field] = value
    with fixture.state._connect() as connection:
        connection.execute("UPDATE capability_grants SET data_json = ?", (json.dumps(data),))
    with pytest.raises(FleetError):
        fixture.state.consume_grant_and_reserve(
            fixture.request.request_id, fixture.request.intent_hash
        )
    assert (
        fixture.state.get_intent(fixture.source.intent_id).status is IntentStatus.PENDING_APPROVAL
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("run_id", "run_" + "9" * 32),
        ("task_id", "task_" + "9" * 32),
        ("principal_role", "verifier"),
        ("workflow", "other-workflow"),
        ("stage", "repairing"),
        ("action", "workspace.write_file"),
        ("resource", {"kind": "project_command", "identifier": "publish"}),
        ("parameters", {"network_mode": "unrestricted"}),
    ],
)
def test_future_intent_cannot_expand_any_semantic_dimension(
    tmp_path: Path, field: str, value: JsonValue
) -> None:
    fixture = _fixture(tmp_path)
    grant = fixture.issue()
    fixture.resume()
    data = fixture.next_intent().model_dump(mode="json")
    data[field] = value
    intent = ToolIntent.model_validate(data)
    with pytest.raises(FleetError):
        fixture.state.consume_matching_grant_and_reserve(
            grant.grant_id, intent, canonical_json_hash(data), fixture.scope_sha256 or ""
        )
    assert fixture.state.find_intent(intent.run_id, intent.idempotency_key) is None


def test_reserved_intent_checks_identity_and_revocation_before_retry(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    grant = fixture.issue(ApprovalChoice.ALLOW_ONCE)
    fixture.state.consume_grant_and_reserve(fixture.request.request_id, fixture.request.intent_hash)
    with pytest.raises(FleetError):
        fixture.state.consume_grant_and_reserve(fixture.request.request_id, "9" * 64)
    fixture.state.revoke_grant(grant.grant_id)
    with pytest.raises(FleetError):
        fixture.state.consume_grant_and_reserve(
            fixture.request.request_id, fixture.request.intent_hash
        )


def test_approval_pause_does_not_authorize_new_intents_before_resume(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    grant = fixture.issue()
    current = fixture.next_intent()
    with pytest.raises(FleetError):
        fixture.state.consume_matching_grant_and_reserve(
            grant.grant_id,
            current,
            canonical_json_hash(current.model_dump(mode="json")),
            fixture.scope_sha256 or "",
        )
    assert fixture.state.find_intent(current.run_id, current.idempotency_key) is None


def test_future_reservation_cannot_adopt_an_ambiguous_existing_intent(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    grant = fixture.issue()
    fixture.resume()
    current = fixture.next_intent()
    digest = canonical_json_hash(current.model_dump(mode="json"))
    fixture.state.reserve_intent(current, digest)
    with pytest.raises(FleetError):
        fixture.state.consume_matching_grant_and_reserve(
            grant.grant_id, current, digest, fixture.scope_sha256 or ""
        )
    assert not [
        event
        for event in fixture.state.list_events(current.run_id)
        if event.event_type == "capability.consumed"
    ]


def test_once_never_becomes_unlimited_and_reusable_scope_is_required(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    data = fixture.issue(ApprovalChoice.ALLOW_ONCE).model_dump(mode="json")
    for update in (
        {"remaining_uses": None},
        {"remaining_uses": 2},
        {"choice": "deny"},
        {"choice": "allow_run", "scope_sha256": None},
        {"expires_at": None},
        {"expires_at": fixture.clock.now() + timedelta(minutes=11)},
    ):
        with pytest.raises(ValidationError):
            CapabilityGrant.model_validate(data | update)


def test_project_grant_listing_is_complete_and_cannot_cross_projects(tmp_path: Path) -> None:
    first = _fixture(tmp_path)
    once = first.issue(ApprovalChoice.ALLOW_ONCE)
    project = first.state.get_project(once.project_id)
    second = _fixture(tmp_path, database_path=first.state.database_path, project=project)
    run_grant = second.issue()
    third = _fixture(tmp_path / "other", database_path=first.state.database_path)
    other = third.issue(ApprovalChoice.ALLOW_ALWAYS)
    assert first.state.list_project_grants(project.project_id) == [once, run_grant]
    assert first.state.list_project_grants(other.project_id) == [other]
    for grant in first.state.list_project_grants(project.project_id):
        first.state.revoke_grant(grant.grant_id)
    assert all(
        grant.revoked_at is not None
        for grant in first.state.list_project_grants(project.project_id)
    )
    assert first.state.get_grant(other.grant_id).revoked_at is None


def test_run_grant_survives_request_expiration_but_not_run_completion(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    grant = fixture.issue()
    fixture.state.consume_grant_and_reserve(fixture.request.request_id, fixture.request.intent_hash)
    fixture.resume()
    fixture.clock.current += timedelta(hours=3)
    current = fixture.next_intent()
    reserved = fixture.state.consume_matching_grant_and_reserve(
        grant.grant_id,
        current,
        canonical_json_hash(current.model_dump(mode="json")),
        fixture.scope_sha256 or "",
    )
    assert reserved.status is IntentStatus.RESERVED
    run = fixture.state.get_run(current.run_id)
    fixture.state.save_run(
        run.model_copy(update={"status": RunStatus.CANCELLED}), "run.cancelled", {}
    )
    with pytest.raises(FleetError):
        fixture.state.consume_grant_and_reserve(
            fixture.request.request_id, fixture.request.intent_hash
        )


def test_scope_retains_full_reviewed_command_with_bounded_serialization(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    scope: dict[str, JsonValue] = {"argv": ["x" * 4096] * 16}
    decision = PermissionDecision(
        outcome=PermissionOutcome.REQUIRE_APPROVAL,
        decision_code="ASK_COMMAND",
        explanation="Review the exact command.",
        effective_scope=scope,
    )
    request = ApprovalRequest.model_validate(
        fixture.request.model_dump(mode="json") | {"authorization_scope": scope}
    )
    assert decision.effective_scope == scope
    assert request.authorization_scope == scope
    oversized: dict[str, JsonValue] = {"argv": ["x" * 4096] * 33}
    with pytest.raises(ValidationError):
        PermissionDecision.model_validate(
            decision.model_dump(mode="json") | {"effective_scope": oversized}
        )
    with pytest.raises(ValidationError):
        ApprovalRequest.model_validate(
            request.model_dump(mode="json") | {"authorization_scope": oversized}
        )


def test_trust_rule_receipt_is_atomic_and_idempotent_without_fake_approval(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path, pause=False)
    digest = fixture.request.intent_hash
    with ThreadPoolExecutor(max_workers=2) as pool:
        reservations = list(
            pool.map(
                lambda _: fixture.state.reserve_trust_rule_intent(
                    fixture.source, digest, fixture.scope_sha256 or "", "rule_reviewed"
                ),
                range(2),
            )
        )
    assert reservations[0] == reservations[1]
    assert reservations[0].approval_request_id is None
    assert reservations[0].status is IntentStatus.RESERVED
    grants = fixture.state.list_project_grants(
        fixture.state.get_run(fixture.source.run_id).project_id
    )
    assert len(grants) == 1
    receipt = grants[0]
    assert receipt.request_id is None
    assert receipt.remaining_uses == 0
    assert receipt.consumed_at == fixture.clock.now()
    assert receipt.source_rule_id == "rule_reviewed"
    assert receipt.scope_sha256 == fixture.scope_sha256
    with fixture.state._connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM approvals").fetchone()[0] == 0
    completed = fixture.state.complete_intent(fixture.source.intent_id, {"exit_code": 0})
    reopened = SqliteStateStore(
        fixture.state.database_path, fixture.clock, UuidIdGenerator(), Redactor()
    )
    assert (
        reopened.reserve_trust_rule_intent(
            fixture.source, digest, fixture.scope_sha256 or "", "rule_reviewed"
        )
        == completed
    )
    events = [
        event
        for event in reopened.list_events(fixture.source.run_id)
        if event.event_type.startswith("capability.")
    ]
    assert [event.event_type for event in events] == ["capability.issued", "capability.consumed"]
    assert all(event.payload["source_rule_id"] == "rule_reviewed" for event in events)
    assert all(event.payload["scope_sha256"] == fixture.scope_sha256 for event in events)
    assert [event.payload["remaining_uses"] for event in events] == [1, 0]
    with pytest.raises(FleetError):
        reopened.consume_matching_grant_and_reserve(
            receipt.grant_id, fixture.source, digest, fixture.scope_sha256 or ""
        )


def test_trust_receipt_failure_rolls_back_intent_grant_and_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path, pause=False)
    existing_events = list(fixture.state.list_events(fixture.source.run_id))
    original = fixture.state._insert_event

    def fail_consumption(connection: sqlite3.Connection, event: FleetEvent) -> FleetEvent:
        if event.event_type == "capability.consumed":
            raise RuntimeError("injected audit persistence failure")
        return original(connection, event)

    monkeypatch.setattr(fixture.state, "_insert_event", fail_consumption)
    with pytest.raises(RuntimeError, match="injected audit persistence failure"):
        fixture.state.reserve_trust_rule_intent(
            fixture.source,
            fixture.request.intent_hash,
            fixture.scope_sha256 or "",
            "rule_reviewed",
        )
    assert fixture.state.find_intent(fixture.source.run_id, fixture.source.idempotency_key) is None
    assert fixture.state.list_grants(fixture.source.run_id) == []
    assert list(fixture.state.list_events(fixture.source.run_id)) == existing_events


@pytest.mark.parametrize("change", ["rule", "scope", "intent", "revoked"])
def test_trust_receipt_retry_preserves_original_authority(tmp_path: Path, change: str) -> None:
    fixture = _fixture(tmp_path, pause=False)
    fixture.state.reserve_trust_rule_intent(
        fixture.source, fixture.request.intent_hash, fixture.scope_sha256 or "", "rule_reviewed"
    )
    intent = fixture.source
    digest = fixture.request.intent_hash
    source_rule = "rule_foreign" if change == "rule" else "rule_reviewed"
    scope = "9" * 64 if change == "scope" else fixture.scope_sha256 or ""
    if change == "intent":
        intent = intent.model_copy(update={"reason": "Changed the original logical intent."})
        digest = canonical_json_hash(intent.model_dump(mode="json"))
    if change == "revoked":
        fixture.state.revoke_grant(fixture.state.list_grants(intent.run_id)[0].grant_id)
    events_before = list(fixture.state.list_events(intent.run_id))
    with pytest.raises(FleetError):
        fixture.state.reserve_trust_rule_intent(intent, digest, scope, source_rule)
    assert list(fixture.state.list_events(intent.run_id)) == events_before


@pytest.mark.parametrize(
    "change", ["paused", "cancelled", "stage", "agent", "hash", "scope", "secret"]
)
def test_trust_receipt_rejects_invalid_current_context_before_persistence(
    tmp_path: Path, change: str
) -> None:
    fixture = _fixture(tmp_path, pause=change == "paused")
    intent = fixture.source
    digest = fixture.request.intent_hash
    scope = fixture.scope_sha256 or ""
    source_rule = "rule_reviewed"
    if change == "cancelled":
        run = fixture.state.get_run(intent.run_id)
        fixture.state.save_run(
            run.model_copy(update={"status": RunStatus.CANCELLED}), "run.cancelled", {}
        )
    elif change == "stage":
        intent = intent.model_copy(update={"stage": WorkflowStage.REPAIRING})
        digest = canonical_json_hash(intent.model_dump(mode="json"))
    elif change == "agent":
        intent = intent.model_copy(update={"agent_instance_id": "agent_" + "9" * 32})
        digest = canonical_json_hash(intent.model_dump(mode="json"))
    elif change == "hash":
        digest = "9" * 64
    elif change == "scope":
        scope = "not-a-canonical-sha256"
    elif change == "secret":
        source_rule = "registered-secret-in-rule-identity"
        fixture.state.redactor.register_secret(source_rule)
    events_before = list(fixture.state.list_events(intent.run_id))
    with pytest.raises(FleetError) as captured:
        fixture.state.reserve_trust_rule_intent(intent, digest, scope, source_rule)
    assert captured.value.code is ErrorCode.APPROVAL_INVALID
    assert "registered-secret-in-rule-identity" not in str(captured.value)
    assert fixture.state.list_grants(intent.run_id) == []
    assert list(fixture.state.list_events(intent.run_id)) == events_before


def test_trust_receipt_cannot_adopt_an_existing_unproven_reservation(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path, pause=False)
    fixture.state.reserve_intent(fixture.source, fixture.request.intent_hash)
    with pytest.raises(FleetError):
        fixture.state.reserve_trust_rule_intent(
            fixture.source,
            fixture.request.intent_hash,
            fixture.scope_sha256 or "",
            "rule_reviewed",
        )
    assert fixture.state.list_grants(fixture.source.run_id) == []


def test_request_free_grants_cannot_become_reusable_or_unattributed(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path, pause=False)
    fixture.state.reserve_trust_rule_intent(
        fixture.source, fixture.request.intent_hash, fixture.scope_sha256 or "", "rule_reviewed"
    )
    receipt = fixture.state.list_grants(fixture.source.run_id)[0]
    for change in (
        {"choice": "allow_once"},
        {"choice": "allow_run"},
        {"source_rule_id": None},
        {"remaining_uses": None},
        {"remaining_uses": 2},
        {"consumed_at": None},
    ):
        with pytest.raises(ValidationError):
            CapabilityGrant.model_validate(receipt.model_dump(mode="json") | change)
