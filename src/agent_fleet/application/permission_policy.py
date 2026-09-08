"""Trusted policy context and user-owned exact permission lifecycle."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path, PurePosixPath
from typing import cast

from pydantic import JsonValue

from agent_fleet.application.permissions import BaselinePermissionBroker, _task_command
from agent_fleet.domain.config import FleetSpec
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.ids import IdPrefix
from agent_fleet.domain.models import (
    AgentRole,
    ApprovalChoice,
    ApprovalStatus,
    CapabilityGrant,
    FleetEvent,
    PermissionDecision,
    PermissionOutcome,
    Project,
    Run,
    RunStatus,
    SandboxCapabilities,
    TaskSpec,
    ToolIntent,
    WorkspaceKind,
)
from agent_fleet.domain.paths import path_is_within
from agent_fleet.domain.role_templates import ResolvedRoleTemplate
from agent_fleet.domain.security import Redactor, canonical_json_hash, sha256_bytes
from agent_fleet.domain.trust import (
    ExactPermissionScope,
    ProjectTrustSettings,
    TrustMode,
    UserTrustPolicy,
    UserTrustRule,
    canonical_trust_path,
    is_protected_action,
    rule_matches,
)
from agent_fleet.ports.clock import Clock
from agent_fleet.ports.config import ConfigurationPort
from agent_fleet.ports.id_generator import IdGenerator
from agent_fleet.ports.repository import RepositoryPort
from agent_fleet.ports.state_store import StateStore
from agent_fleet.ports.trust_store import TrustStore

_APPROVAL_ACTIONS = {"command.run", "fixture.record_side_effect"}
_CHOICES = [
    ApprovalChoice.DENY,
    ApprovalChoice.ALLOW_ONCE,
    ApprovalChoice.ALLOW_RUN,
    ApprovalChoice.ALLOW_ALWAYS,
]
_LEGACY_REQUESTS = {
    ("engineer", "workspace.write_file", "workspace://candidate/**"),
    ("engineer", "command.run", "command://declared-fake-command"),
    ("verifier", "command.run", "command://declared-fake-command"),
}


class PermissionPolicyService:
    """Load trusted scope and mutate only an explicit user's policy."""

    def __init__(
        self,
        state: StateStore,
        trust: TrustStore,
        config: ConfigurationPort,
        repository: RepositoryPort,
        clock: Clock,
        ids: IdGenerator,
        redactor: Redactor,
    ) -> None:
        self.state = state
        self.trust = trust
        self.config = config
        self.repository = repository
        self.clock = clock
        self.ids = ids
        self.redactor = redactor

    def project_at(self, path: Path) -> Project:
        info = self.repository.inspect(path)
        project = self.state.get_project_by_root(info.root)
        if project is None or project.identity_hash != info.identity_hash:
            raise FleetError(
                ErrorCode.PROJECT_NOT_INITIALIZED,
                "The repository has no matching Fleet-owned project identity.",
                "Initialize the repository with this Fleet state directory first.",
            )
        return project

    def settings(
        self, project: Project, policy: UserTrustPolicy | None = None
    ) -> ProjectTrustSettings:
        active = policy if policy is not None else self.trust.load()
        for item in active.projects:
            if item.project_id == project.project_id:
                if item.repository_identity != project.identity_hash:
                    raise _policy_error("Stored project trust belongs to a different repository.")
                return item
        if project.permission_scope_required:
            raise _policy_error("This project has no completed user-owned scope registration.")
        # Existing explicit registrations approved the repository-local baseline.
        # No old registration acquires a persistent rule during this compatibility path.
        return ProjectTrustSettings(
            project_id=project.project_id,
            repository_identity=project.identity_hash,
            trust_mode=TrustMode.BALANCED,
            allowed_paths=(".",),
        )

    def review_settings(self, mode: TrustMode, paths: tuple[str, ...]) -> dict[str, JsonValue]:
        if self.redactor.contains_secret_data(list(paths)):
            raise _policy_error("A registered secret is present in a proposed path ceiling.")
        try:
            for path in paths:
                canonical_trust_path(path, allow_root=True)
            if not paths or len(paths) > 128 or len({p.casefold() for p in paths}) != len(paths):
                raise ValueError("invalid path set")
        except ValueError:
            raise _policy_error(
                "Reviewed path scopes must be canonical, bounded and unique."
            ) from None
        return {
            "trust_mode": mode.value,
            "allowed_paths": list(paths),
            "protected_paths": [".git", ".fleet"],
            "ownership": "user-owned Fleet trust store outside the repository",
        }

    def review_initialization(
        self,
        path: Path,
        *,
        mode: TrustMode | None,
        allowed_paths: tuple[str, ...] | None,
    ) -> dict[str, JsonValue]:
        """Preview reviewed defaults without consulting or creating Fleet state."""
        if self.redactor.contains_secret(str(path)):
            raise _policy_error("A registered secret is present in the project path.")
        if allowed_paths is not None:
            self.review_settings(mode or TrustMode.BALANCED, allowed_paths)
        policy = self.trust.load()
        identity = self.repository.inspect(path).identity_hash
        matches = [item for item in policy.projects if item.repository_identity == identity]
        if len({(item.trust_mode, item.allowed_paths) for item in matches}) > 1:
            raise _policy_error("Multiple trust registrations disagree for this repository.")
        prior = matches[0] if matches else None
        reviewed = self.review_settings(
            mode if mode is not None else prior.trust_mode if prior else TrustMode.BALANCED,
            allowed_paths
            if allowed_paths is not None
            else prior.allowed_paths
            if prior
            else (".",),
        )
        return {**reviewed, "policy_revision": policy.revision}

    def configure(
        self,
        path: Path,
        *,
        mode: TrustMode,
        allowed_paths: tuple[str, ...] | None,
        actor: str = "user",
        expected_revision: int | None = None,
    ) -> ProjectTrustSettings:
        _require_user(actor)
        if allowed_paths is not None:
            self.review_settings(mode, allowed_paths)
        project = self.project_at(path)
        policy = self.trust.load()
        if expected_revision is not None and policy.revision != expected_revision:
            raise _policy_error("The user trust policy changed after initialization review.")
        prior = next((p for p in policy.projects if p.project_id == project.project_id), None)
        if prior is not None and prior.repository_identity != project.identity_hash:
            raise _policy_error("Stored project trust belongs to a different repository.")
        settings = ProjectTrustSettings(
            project_id=project.project_id,
            repository_identity=project.identity_hash,
            trust_mode=mode,
            allowed_paths=allowed_paths
            if allowed_paths is not None
            else self.settings(project, policy).allowed_paths,
            grants_revoked_before=prior.grants_revoked_before if prior else None,
        )
        updated = policy.model_copy(
            update={
                "projects": [p for p in policy.projects if p.project_id != project.project_id]
                + [settings]
            }
        )
        self._publish_policy_change(
            project.project_id,
            "permission.policy_updated",
            policy,
            updated,
            {"settings": settings.model_dump(mode="json")},
        )
        return settings

    def validate_task_paths(self, project: Project, paths: list[str]) -> None:
        ceiling = self.settings(project)
        if any(not _within_user_paths(path, ceiling.allowed_paths) for path in paths):
            raise _policy_error("Proposed task paths exceed the user-reviewed project scope.")

    def validate_run_target(self, run: Run) -> None:
        project = self.state.get_project(run.project_id)
        info = self.repository.inspect(Path(project.canonical_root))
        if (
            info.identity_hash != project.identity_hash
            or info.head_revision != run.base_revision
            or info.status_fingerprint != run.target_status_fingerprint
        ):
            raise _policy_error("The repository identity, base, or working tree changed.")
        _, snapshot = self.config.load_snapshot(Path(project.canonical_root) / ".fleet/fleet.yaml")
        if self.config.snapshot_hash(snapshot) != run.config_snapshot_hash:
            raise _policy_error("The reviewed run configuration changed.")

    def context(
        self, intent: ToolIntent, task: TaskSpec, sandbox: SandboxCapabilities
    ) -> tuple[Project, FleetSpec, ProjectTrustSettings, UserTrustPolicy, ExactPermissionScope]:
        run = self.state.get_run(intent.run_id)
        project = self.state.get_project(run.project_id)
        if (
            run.task_id != task.task_id
            or self.state.get_task(task.task_id) != task
            or run.stage != intent.stage
            or task.config_snapshot_hash != run.config_snapshot_hash
            or sandbox != run.sandbox_capabilities_snapshot
            or run.status not in {RunStatus.RUNNING, RunStatus.PAUSED_FOR_APPROVAL}
            or run.sandbox_configuration is None
        ):
            raise _policy_error("The tool intent no longer matches the active trusted context.")
        spec, snapshot = self.config.load_snapshot(
            Path(project.canonical_root) / ".fleet/fleet.yaml"
        )
        if self.config.snapshot_hash(snapshot) != run.config_snapshot_hash:
            raise _policy_error("The reviewed configuration changed before tool authorization.")
        role = self.config.role_templates(spec, snapshot).get(intent.principal_role)
        if role is None:
            raise _policy_error("The tool principal has no reviewed executable role template.")
        if intent.principal_role not in {item.value for item in AgentRole}:
            agent = self.state.get_agent_instance(intent.agent_instance_id)
            if (
                agent.role != intent.principal_role
                or agent.run_id != run.run_id
                or agent.task_id != task.task_id
                or agent.execution_kind is not role.execution_kind
                or not role.delegation_allowed
                or (
                    role.allowed_paths is not None
                    and any(
                        not path_is_within(path, list(role.allowed_paths))
                        for path in task.allowed_paths
                    )
                )
            ):
                raise _policy_error("The custom principal does not match its bound role ceiling.")
        policy = self.trust.load()
        settings = self.settings(project, policy)
        if any(not _within_user_paths(path, settings.allowed_paths) for path in task.allowed_paths):
            raise _policy_error("The task exceeds the current user-owned path ceiling.")
        command = (
            _task_command(task, intent.resource.identifier, sandbox.provider)
            if intent.action == "command.run"
            else None
        )
        scope = _validated_scope(
            project_id=project.project_id,
            repository_identity=project.identity_hash,
            principal_role=intent.principal_role,
            workflow=intent.workflow,
            stage=intent.stage,
            action=intent.action,
            resource=intent.resource,
            parameters={
                (
                    f"{key}_sha256"
                    if key in {"content", "old", "new"} and isinstance(value, str)
                    else key
                ): (
                    sha256_bytes(value.encode("utf-8"))
                    if key in {"content", "old", "new"} and isinstance(value, str)
                    else value
                )
                for key, value in intent.parameters.items()
            },
            command=command,
            workspace_kind=(
                WorkspaceKind.VERIFICATION
                if role.execution_kind is AgentRole.VERIFIER
                else WorkspaceKind.CANDIDATE
            ),
            sandbox_provider=run.sandbox_name,
            sandbox_security_level=sandbox.security_level,
            network_mode=run.sandbox_configuration.network_mode,
        )
        if self.redactor.contains_secret_data(scope.model_dump(mode="json")):
            raise _policy_error("A registered secret is present in the proposed permission scope.")
        return project, spec, settings, policy, scope

    def rule_is_active(self, rule: UserTrustRule) -> bool:
        if rule.revoked_at is not None or (
            rule.expires_at is not None and rule.expires_at <= self.clock.now()
        ):
            return False
        if rule.source_approval_request_id is None:
            return True
        request = self.state.get_approval(rule.source_approval_request_id)
        return (
            request.status is ApprovalStatus.APPROVED
            and request.resolution_choice is ApprovalChoice.ALLOW_ALWAYS
            and request.source_rule_id == rule.rule_id
            and request.authorization_scope == rule.scope.model_dump(mode="json")
        )

    def stage_always_rule(self, request_id: str, scope: ExactPermissionScope) -> UserTrustRule:
        """An interrupted pre-resolution write cannot authorize until SQLite agrees."""
        rule_id = "rule_" + request_id.removeprefix("perm_")
        policy = self.trust.load()
        for rule in policy.rules:
            if rule.rule_id == rule_id:
                if rule.scope != scope or rule.revoked_at is not None:
                    raise _policy_error("The approval's exact rule was changed or revoked.")
                return rule
        rule = UserTrustRule(
            rule_id=rule_id,
            scope=scope,
            effect="allow",
            created_by="user",
            created_at=self.clock.now(),
            source_approval_request_id=request_id,
        )
        self._publish_policy_change(
            scope.project_id,
            "permission.rule_staged",
            policy,
            policy.model_copy(
                update={
                    "rules": [*policy.rules, rule],
                    "projects": policy.projects
                    if any(p.project_id == scope.project_id for p in policy.projects)
                    else [
                        *policy.projects,
                        self.settings(self.state.get_project(scope.project_id), policy),
                    ],
                }
            ),
            {"rule_id": rule.rule_id, "request_id": request_id},
        )
        return rule

    def list_rules(self, path: Path) -> dict[str, JsonValue]:
        project = self.project_at(path)
        policy = self.trust.load()
        settings = self.settings(project, policy)
        return {
            "project_id": project.project_id,
            "revision": policy.revision,
            "settings": settings.model_dump(mode="json"),
            "rules": [
                {**rule.model_dump(mode="json"), "active": self.rule_is_active(rule)}
                for rule in policy.rules
                if rule.scope.project_id == project.project_id
            ],
            "grants": [
                self._describe_grant(grant, settings, policy)
                for grant in self.state.list_project_grants(project.project_id)
            ],
        }

    def _describe_grant(
        self, grant: CapabilityGrant, settings: ProjectTrustSettings, policy: UserTrustPolicy
    ) -> dict[str, JsonValue]:
        now = self.clock.now()
        run = self.state.get_run(grant.run_id)
        source = self.state.get_intent(grant.intent_id)
        cutoff_revoked = (
            settings.grants_revoked_before is not None
            and grant.issued_at <= settings.grants_revoked_before
        )
        if grant.revoked_at is not None:
            status = "revoked"
        elif cutoff_revoked:
            status = "revoked_by_project_reset"
        elif grant.expires_at is not None and grant.expires_at <= now:
            status = "expired"
        elif grant.remaining_uses == 0:
            status = "exhausted"
        elif run.status not in {RunStatus.RUNNING, RunStatus.PAUSED_FOR_APPROVAL}:
            status = "run_ended"
        elif run.stage is not source.intent.stage:
            status = "stage_changed"
        elif grant.source_rule_id is not None and not any(
            rule.rule_id == grant.source_rule_id and self.rule_is_active(rule)
            for rule in policy.rules
        ):
            status = "source_rule_inactive"
        else:
            status = "available"
        return {
            **grant.model_dump(mode="json"),
            "lifetime": grant.choice.value,
            "status": status,
            "cutoff_revoked": cutoff_revoked,
            "grants_revoked_before": (
                settings.grants_revoked_before.isoformat()
                if settings.grants_revoked_before
                else None
            ),
            "explanation": (
                "Grant lifetime only; execution rechecks current policy and exact scope."
            ),
        }

    def explain(self, identifier: str) -> dict[str, JsonValue]:
        if identifier.startswith("rule_"):
            for rule in self.trust.load().rules:
                if rule.rule_id == identifier:
                    return {
                        **rule.model_dump(mode="json"),
                        "active": self.rule_is_active(rule),
                        "explanation": (
                            "Only this exact scope can match; upper ceilings still apply."
                        ),
                    }
            raise _policy_error("The requested permission rule does not exist.")
        request = self.state.get_approval(identifier)
        run = self.state.get_run(request.run_id)
        stored = self.state.get_intent(request.intent_id)
        if (
            run.status not in {RunStatus.RUNNING, RunStatus.PAUSED_FOR_APPROVAL}
            or run.stage is not stored.intent.stage
        ):
            return {
                "request": request.model_dump(mode="json"),
                "historical": True,
                "current_decision": None,
                "recorded_decisions": [
                    event.model_dump(mode="json")
                    for event in self.state.list_events(run.run_id)
                    if event.event_type == "permission.decision"
                    and event.payload.get("intent_id") == request.intent_id
                ],
                "explanation": (
                    "Recorded authorization only; this does not establish current permission "
                    "for any action."
                ),
            }
        if run.task_id is None or run.sandbox_capabilities_snapshot is None:
            raise _policy_error("The approval has no valid task or sandbox binding.")
        # Read the canonical request through its stored idempotency record, not display text.
        decision = PolicyPermissionBroker(self).evaluate(
            stored.intent, self.state.get_task(run.task_id), run.sandbox_capabilities_snapshot
        )
        return {
            "request": request.model_dump(mode="json"),
            "historical": False,
            "current_decision": decision.model_dump(mode="json"),
        }

    def revoke(self, identifier: str, *, actor: str = "user") -> dict[str, JsonValue]:
        _require_user(actor)
        if identifier.startswith("grant_"):
            return self.state.revoke_grant(identifier).model_dump(mode="json")
        policy = self.trust.load()
        for rule in policy.rules:
            if rule.rule_id == identifier:
                if rule.revoked_at is not None:
                    return rule.model_dump(mode="json")
                revoked = rule.model_copy(update={"revoked_at": self.clock.now()})
                self._publish_policy_change(
                    rule.scope.project_id,
                    "permission.rule_revoked",
                    policy,
                    policy.model_copy(
                        update={
                            "rules": [
                                revoked if r.rule_id == identifier else r for r in policy.rules
                            ]
                        }
                    ),
                    {"rule_id": identifier},
                )
                return revoked.model_dump(mode="json")
        raise _policy_error("The requested permission rule does not exist.")

    def reset(self, path: Path, *, actor: str = "user") -> dict[str, JsonValue]:
        _require_user(actor)
        project = self.project_at(path)
        policy = self.trust.load()
        prior = self.settings(project, policy)
        grants = self.state.list_project_grants(project.project_id)
        cutoff = max([self.clock.now(), *(grant.issued_at for grant in grants)])
        if prior.grants_revoked_before is not None:
            cutoff = max(cutoff, prior.grants_revoked_before + timedelta(microseconds=1))
        settings = prior.model_copy(update={"grants_revoked_before": cutoff})
        revoked_ids = [
            r.rule_id
            for r in policy.rules
            if r.scope.project_id == project.project_id and r.revoked_at is None
        ]
        rules = [
            r.model_copy(update={"revoked_at": self.clock.now()}) if r.rule_id in revoked_ids else r
            for r in policy.rules
        ]
        # Reset grants, not the reviewed scope: deleting a narrow ceiling would broaden it.
        # The persisted cutoff invalidates grants even if subsequent SQLite
        # revocation fails. Keeping the reviewed paths avoids widening authority.
        saved = self._publish_policy_change(
            project.project_id,
            "permission.project_reset",
            policy,
            policy.model_copy(
                update={
                    "rules": rules,
                    "projects": [p for p in policy.projects if p.project_id != project.project_id]
                    + [settings],
                }
            ),
            {"rule_ids": revoked_ids, "grants_revoked_before": cutoff.isoformat()},
        )
        revoked_grants = []
        for grant in grants:
            if grant.revoked_at is None:
                self.state.revoke_grant(grant.grant_id)
                revoked_grants.append(grant.grant_id)
        return {
            "project_id": project.project_id,
            "revoked_rule_ids": cast(JsonValue, revoked_ids),
            "revoked_grant_ids": cast(JsonValue, revoked_grants),
            "revision": saved.revision,
            "grants_revoked_before": cutoff.isoformat(),
        }

    def _publish_policy_change(
        self,
        project_id: str,
        action: str,
        previous: UserTrustPolicy,
        proposed: UserTrustPolicy,
        details: dict[str, object],
    ) -> UserTrustPolicy:
        """Prepare exact durable evidence before any policy can become effective.

        If publication/completion is interrupted, compare the prepared revision
        and hash with current policy or its immutable revision backup. Never
        infer success from the absence of a completion event or undo a newer CAS.
        """
        raw = proposed.model_dump(mode="json")
        if self.redactor.contains_secret_data(raw):
            raise _policy_error("A registered secret is present in the proposed trust policy.")
        try:
            checked = UserTrustPolicy.model_validate(raw)
            if checked.revision != previous.revision:
                raise ValueError("proposed policy does not share the expected revision")
            published = UserTrustPolicy.model_validate(
                {**checked.model_dump(mode="json"), "revision": previous.revision + 1}
            )
        except ValueError:
            raise _policy_error("The complete proposed user trust policy is invalid.") from None
        mutation_id = self.ids.new(IdPrefix.CORRELATION)
        evidence: dict[str, object] = {
            "mutation_id": mutation_id,
            "action": action,
            "expected_revision": previous.revision,
            "published_revision": published.revision,
            "previous_policy_sha256": canonical_json_hash(previous.model_dump(mode="json")),
            "published_policy_sha256": canonical_json_hash(published.model_dump(mode="json")),
            "details": details,
        }
        self._audit(project_id, "permission.policy_change_prepared", evidence, mutation_id)
        saved = self.trust.save(checked, expected_revision=previous.revision)
        if saved != published:
            raise _policy_error("Published trust policy differs from its prepared audit evidence.")
        self._audit(project_id, "permission.policy_change_completed", evidence, mutation_id)
        return saved

    def _audit(
        self,
        project_id: str,
        event_type: str,
        payload: dict[str, object],
        correlation_id: str | None = None,
    ) -> None:
        cleaned, summary = self.redactor.redact_data(payload)
        self.state.append_event(
            FleetEvent(
                event_id=self.ids.new(IdPrefix.EVENT),
                event_type=event_type,
                occurred_at=self.clock.now(),
                project_id=project_id,
                correlation_id=correlation_id or self.ids.new(IdPrefix.CORRELATION),
                payload=cast(dict[str, JsonValue], cleaned),
                redaction_summary=summary,
            )
        )


class PolicyPermissionBroker:
    """Evaluate hard ceilings, exact grants/rules, then documented trust defaults."""

    def __init__(self, policy: PermissionPolicyService) -> None:
        self.policy = policy
        self.baseline = BaselinePermissionBroker()

    def evaluate(
        self, intent: ToolIntent, task: TaskSpec, sandbox: SandboxCapabilities
    ) -> PermissionDecision:
        if is_protected_action(intent.action):
            return _deny("SYSTEM_HARD_DENY", "This protected action cannot be approved.")
        if intent.principal_role in {item.value for item in AgentRole}:
            # Preserve the cheap deny for malformed built-in intents without
            # consulting mutable state. Custom kinds never come from the intent.
            ceiling = self.baseline.evaluate(intent, task, sandbox)
            if ceiling.outcome is PermissionOutcome.DENY:
                return ceiling
        _, spec, settings, trust, scope = self.policy.context(intent, task, sandbox)
        project = self.policy.state.get_project(self.policy.state.get_run(intent.run_id).project_id)
        current_spec, snapshot = self.policy.config.load_snapshot(
            Path(project.canonical_root) / ".fleet/fleet.yaml"
        )
        if (
            current_spec != spec
            or self.policy.config.snapshot_hash(snapshot) != task.config_snapshot_hash
        ):
            raise _policy_error("The role snapshot changed during permission evaluation.")
        role = self.policy.config.role_templates(spec, snapshot).get(intent.principal_role)
        if role is None:
            return _deny("ORGANIZATION_PERMISSION_CEILING", "The role is not declared.")
        ceiling = self.baseline.evaluate(intent, task, sandbox, execution_kind=role.execution_kind)
        if ceiling.outcome is PermissionOutcome.DENY:
            return ceiling
        if not _requested_by_organization(spec, intent, template=role):
            return _deny(
                "ORGANIZATION_PERMISSION_CEILING",
                "The role or workflow does not request this tool and resource.",
            )
        raw_scope = scope.model_dump(mode="json")
        matched = [
            r
            for r in trust.rules
            if self.policy.rule_is_active(r) and rule_matches(r, scope, self.policy.clock.now())
        ]
        denied = [r.rule_id for r in matched if r.effect == "deny"]
        if denied:
            return PermissionDecision(
                outcome=PermissionOutcome.DENY,
                decision_code="USER_EXACT_DENY",
                explanation="A user-owned deny rule matches.",
                protected=True,
                matched_rule_ids=denied,
                effective_scope=raw_scope,
            )
        for grant in self.policy.state.list_grants(intent.run_id):
            if self._grant_matches(grant, intent, scope, trust):
                return PermissionDecision(
                    outcome=PermissionOutcome.ALLOW,
                    decision_code="EXACT_CAPABILITY_GRANT",
                    explanation="An active exact capability matches.",
                    grant_id=grant.grant_id,
                    source_rule_id=grant.source_rule_id,
                    matched_rule_ids=[grant.grant_id],
                    effective_scope=raw_scope,
                )
        allowed = [r for r in matched if r.effect == "allow"]
        if allowed:
            return PermissionDecision(
                outcome=PermissionOutcome.ALLOW,
                decision_code="EXACT_PROJECT_TRUST",
                explanation="An active exact project rule matches.",
                source_rule_id=allowed[0].rule_id,
                matched_rule_ids=[r.rule_id for r in allowed],
                effective_scope=raw_scope,
            )
        asks = intent.action in _APPROVAL_ACTIONS and (
            settings.trust_mode is TrustMode.SAFE
            or intent.action == "fixture.record_side_effect"
            or sandbox.security_level.value == "unsafe_host"
        )
        if asks:
            return PermissionDecision(
                outcome=PermissionOutcome.REQUIRE_APPROVAL,
                decision_code="EXACT_SCOPE_APPROVAL_REQUIRED",
                explanation=(
                    "The exact command, role, stage, project and sandbox scope "
                    "requires user approval."
                ),
                effective_scope=raw_scope,
                available_choices=_CHOICES,
                risk="command_execution",
            )
        return ceiling.model_copy(
            update={
                "effective_scope": raw_scope,
                "matched_rule_ids": [f"baseline:{settings.trust_mode.value}"],
            }
        )

    def _grant_matches(
        self,
        grant: CapabilityGrant,
        intent: ToolIntent,
        scope: ExactPermissionScope,
        policy: UserTrustPolicy,
    ) -> bool:
        now = self.policy.clock.now()
        settings = next((p for p in policy.projects if p.project_id == scope.project_id), None)
        if (
            grant.revoked_at is not None
            or (grant.expires_at is not None and grant.expires_at <= now)
            or grant.remaining_uses == 0
            or grant.project_id != scope.project_id
            or grant.run_id != intent.run_id
            or grant.task_id != intent.task_id
            or grant.principal_role != intent.principal_role
            or grant.action != intent.action
            or grant.resource != intent.resource
            or (
                settings is not None
                and settings.grants_revoked_before is not None
                and grant.issued_at <= settings.grants_revoked_before
            )
        ):
            return False
        if grant.source_rule_id is not None and not any(
            r.rule_id == grant.source_rule_id
            and self.policy.rule_is_active(r)
            and rule_matches(r, scope, now)
            for r in policy.rules
        ):
            return False
        if grant.choice is ApprovalChoice.ALLOW_ONCE:
            return (
                grant.intent_id == intent.intent_id
                and grant.agent_instance_id == intent.agent_instance_id
                and grant.intent_hash == canonical_json_hash(intent.model_dump(mode="json"))
                and (grant.scope_sha256 is None or grant.scope_sha256 == scope.scope_sha256)
            )
        return grant.scope_sha256 == scope.scope_sha256


def _requested_by_organization(
    spec: FleetSpec, intent: ToolIntent, *, template: ResolvedRoleTemplate | None = None
) -> bool:
    role = template if template is not None else spec.spec.agents.get(intent.principal_role)
    workflow = spec.spec.workflows.get(intent.workflow)
    if role is None or workflow is None:
        return False
    if workflow.allowed_tools is not None and intent.action not in workflow.allowed_tools:
        return False
    requests = {(p.principal_role, p.action, p.resource) for p in spec.spec.requested_permissions}
    if intent.action == "fixture.record_side_effect":
        if spec.spec.runtime.adapter != "fake":
            return False
        if requests == _LEGACY_REQUESTS and "command.run" in role.allowed_tools:
            return True
    if intent.action not in role.allowed_tools:
        return False
    if len(requests) == len(spec.spec.requested_permissions) and requests == _LEGACY_REQUESTS:
        # Only the exact shipped legacy request set is normalized, bounded by
        # current role tools and the same TaskSpec/command ceiling as before.
        return True
    return any(
        p.principal_role
        == (template.execution_kind.value if template is not None else intent.principal_role)
        and p.action == intent.action
        and _requested_resource_matches(
            p.resource,
            intent,
            execution_kind=template.execution_kind if template is not None else None,
        )
        for p in spec.spec.requested_permissions
    )


def _requested_resource_matches(
    request: str, intent: ToolIntent, *, execution_kind: AgentRole | None = None
) -> bool:
    if intent.action == "fixture.record_side_effect":
        return request == "fixture://approval-proof"
    if intent.action == "command.run":
        return request in {
            "command://declared-project-command",
            f"command://{intent.resource.identifier}",
        }
    role = intent.principal_role if execution_kind is None else execution_kind.value
    workspace = "verification" if role == "verifier" else "candidate"
    prefixes = [f"workspace://{workspace}/"]
    if not intent.side_effect:
        prefixes.append("repo://current/")
    for prefix in prefixes:
        if not request.startswith(prefix):
            continue
        suffix = request[len(prefix) :]
        if suffix == "**":
            return True
        if intent.resource.kind != "workspace_path":
            return False
        if suffix.endswith("/**"):
            return _within_user_paths(intent.resource.identifier, (suffix[:-3],))
        return suffix == intent.resource.identifier
    return False


def _within_user_paths(path: str, scopes: tuple[str, ...]) -> bool:
    parts = tuple(p.casefold() for p in PurePosixPath(path).parts)
    if not parts or parts[0] in {".git", ".fleet"} or ".." in parts:
        return False
    return any(
        scope == "."
        or parts[: len(PurePosixPath(scope).parts)]
        == tuple(p.casefold() for p in PurePosixPath(scope).parts)
        for scope in scopes
    )


def _require_user(actor: str) -> None:
    if actor != "user":
        raise _policy_error("Only an explicit user action may change trust or approvals.")


def _policy_error(message: str) -> FleetError:
    return FleetError(
        ErrorCode.APPROVAL_INVALID,
        message,
        "Review project permissions and the exact request before retrying.",
    )


def _deny(code: str, message: str) -> PermissionDecision:
    return PermissionDecision(
        outcome=PermissionOutcome.DENY, decision_code=code, explanation=message, protected=True
    )


def _validated_scope(**values: object) -> ExactPermissionScope:
    try:
        return ExactPermissionScope.model_validate(values)
    except ValueError:
        raise FleetError(
            ErrorCode.COMMAND_DENIED,
            "The requested action has no valid exact permission scope.",
            "Use only supported bounded tools and reviewed non-privileged commands.",
        ) from None
