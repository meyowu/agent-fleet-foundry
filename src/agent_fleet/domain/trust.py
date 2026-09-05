"""User-owned, exact permission scopes; repository requests never create these rules."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import Field, JsonValue, StringConstraints, field_validator, model_validator

from agent_fleet.domain.models import (
    ActionId,
    ApprovalRequestId,
    CanonicalResource,
    CommandSpec,
    FrozenStrictModel,
    ProjectId,
    RoleId,
    SandboxName,
    SandboxNetworkMode,
    SandboxSecurityLevel,
    Sha256,
    WorkflowId,
    WorkflowStage,
    WorkspaceKind,
)
from agent_fleet.domain.security import canonical_json_hash

RuleId = Annotated[str, StringConstraints(pattern=r"^rule_[0-9a-f]{32}$")]


class TrustMode(StrEnum):
    SAFE = "safe"
    BALANCED = "balanced"
    AUTONOMOUS_SANDBOX = "autonomous-sandbox"


PROTECTED_ACTIONS = frozenset(
    {
        "host.sudo",
        "host.root",
        "sandbox.disable",
        "sandbox.privileged",
        "sandbox.mount-docker-socket",
        "sandbox.mount-host-root",
        "sandbox.mount-home",
        "sandbox.mount-credentials",
        "secret.read-raw",
        "secret.policy-change",
        "audit.delete",
        "audit.rewrite",
        "policy.hard-deny-edit",
        "policy.change-approver",
        "policy.self-approve",
        "policy.disable-redaction",
        "policy.raise-global-budget",
        "production.deploy",
        "production.database-destructive",
    }
)
_WORKSPACE_ACTIONS = frozenset(
    {"repo.read_file", "workspace.write_file", "workspace.apply_edit", "workspace.delete_path"}
)
_VIEW_ACTIONS = frozenset({"repo.list_files", "repo.search_text", "workspace.get_diff"})
_SUPPORTED_ACTIONS = (
    _WORKSPACE_ACTIONS
    | _VIEW_ACTIONS
    | {
        "command.run",
        "fixture.record_side_effect",
    }
)


def is_protected_action(action: str) -> bool:
    """Protected families cannot acquire ordinary conversational trust."""

    return action in PROTECTED_ACTIONS or action.startswith(
        ("host.", "sandbox.", "secret.", "audit.", "policy.", "production.")
    )


def canonical_trust_path(path: str, *, allow_root: bool = False) -> str:
    """Require canonical logical paths without expanding globs or protected directories."""

    if path == "." and allow_root:
        return path
    parts = PurePosixPath(path).parts
    if (
        not path
        or len(path) > 4096
        or not parts
        or path.startswith("/")
        or any(char in path for char in "\\\x00*?[]{}")
        or any(ord(char) < 32 or ord(char) == 127 for char in path)
        or any(part in {".", ".."} for part in parts)
        or ":" in path
        or PurePosixPath(path).as_posix() != path
        or any(part.casefold() in {".git", ".fleet"} for part in parts)
    ):
        raise ValueError("trust paths must be exact canonical unprotected repository paths")
    return path


def _utc(value: datetime) -> datetime:
    if value.utcoffset() != timedelta(0):
        raise ValueError("trust timestamps must use timezone-aware UTC")
    return value


class ExactPermissionScope(FrozenStrictModel):
    project_id: ProjectId
    repository_identity: Sha256
    principal_role: RoleId
    workflow: WorkflowId
    stage: WorkflowStage
    action: ActionId
    resource: CanonicalResource
    parameters: dict[str, JsonValue] = Field(default_factory=dict, max_length=32)
    command: CommandSpec | None = None
    workspace_kind: WorkspaceKind
    sandbox_provider: SandboxName
    sandbox_security_level: SandboxSecurityLevel
    network_mode: SandboxNetworkMode
    source_checkout_read_only: Literal[True] = True

    @model_validator(mode="after")
    def validate_scope(self) -> ExactPermissionScope:
        if is_protected_action(self.action) or self.action not in _SUPPORTED_ACTIONS:
            raise ValueError("this action cannot receive ordinary exact project trust")
        if self.principal_role == "cos":
            raise ValueError("CoS cannot acquire execution authority")
        expected_level = {
            "fake": SandboxSecurityLevel.FAKE,
            "docker": SandboxSecurityLevel.ISOLATED,
            "local-unsafe": SandboxSecurityLevel.UNSAFE_HOST,
        }[self.sandbox_provider]
        expected_network = (
            "approved-unrestricted" if self.sandbox_provider == "local-unsafe" else "none"
        )
        if (
            self.sandbox_security_level is not expected_level
            or self.network_mode != expected_network
        ):
            raise ValueError("trust sandbox conditions must match the exact supported provider")
        if self.action in _WORKSPACE_ACTIONS:
            if self.resource.kind != "workspace_path":
                raise ValueError("workspace actions require a canonical workspace path")
            canonical_trust_path(self.resource.identifier)
        elif self.action in _VIEW_ACTIONS:
            if self.resource != CanonicalResource(kind="workspace_view", identifier="."):
                raise ValueError("workspace observations require the exact bounded view")
        elif self.action == "command.run":
            if self.command is None:
                raise ValueError("command trust requires the complete reviewed command")
            # Validate nested models even if a caller supplied an unchecked model_copy.
            command = CommandSpec.model_validate(self.command.model_dump(mode="json"))
            if PurePosixPath(command.executable).name.casefold() in {"sudo", "doas", "su"}:
                raise ValueError("privilege escalation cannot be disguised as command trust")
            canonical_trust_path(command.logical_cwd, allow_root=True)
            if self.resource != CanonicalResource(
                kind="project_command", identifier=command.command_id
            ):
                raise ValueError("command resource must exactly match its reviewed command ID")
            if self.parameters != {
                "command_id": command.command_id,
                "command_spec_sha256": canonical_json_hash(command.model_dump(mode="json")),
                "network_mode": self.network_mode,
            }:
                raise ValueError("command parameters must exactly bind its content and network")
            if command.network_requirement != "none":
                raise ValueError("network-required commands have no enforcing trust executor")
        elif (
            self.resource
            != CanonicalResource(kind="fake_side_effect", identifier="fixture://approval-proof")
            or self.parameters != {"record": "approved-once"}
            or self.sandbox_provider != "fake"
        ):
            raise ValueError("the approval fixture must use its exact non-executing scope")
        if self.action != "command.run" and self.command is not None:
            raise ValueError("only command actions can carry a command binding")
        encoded = json.dumps(self.parameters, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if len(encoded) > 262_144:
            raise ValueError("trust scope parameters exceed their byte limit")
        return self

    @property
    def scope_sha256(self) -> str:
        return canonical_json_hash(self.model_dump(mode="json"))


def validate_exact_scope(scope: ExactPermissionScope) -> ExactPermissionScope:
    """Revalidate nested state before authorizing or persisting an exact scope."""

    return ExactPermissionScope.model_validate(scope.model_dump(mode="json"))


def exact_scope_matches(left: ExactPermissionScope, right: ExactPermissionScope) -> bool:
    return validate_exact_scope(left) == validate_exact_scope(right)


class UserTrustRule(FrozenStrictModel):
    rule_id: RuleId
    scope: ExactPermissionScope
    effect: Literal["allow", "deny"]
    created_by: Literal["user"] = "user"
    created_at: datetime
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    source_approval_request_id: ApprovalRequestId | None = None

    _created_utc = field_validator("created_at")(_utc)

    @field_validator("expires_at", "revoked_at")
    @classmethod
    def validate_optional_utc(cls, value: datetime | None) -> datetime | None:
        return _utc(value) if value is not None else None

    @model_validator(mode="after")
    def validate_rule(self) -> UserTrustRule:
        validate_exact_scope(self.scope)
        if self.expires_at is not None and self.expires_at <= self.created_at:
            raise ValueError("trust expiration must be after creation")
        if self.revoked_at is not None and self.revoked_at < self.created_at:
            raise ValueError("trust revocation cannot precede creation")
        return self


def rule_matches(rule: UserTrustRule, scope: ExactPermissionScope, now: datetime) -> bool:
    checked = UserTrustRule.model_validate(rule.model_dump(mode="json"))
    _utc(now)
    return (
        checked.created_at <= now
        and checked.revoked_at is None
        and (checked.expires_at is None or checked.expires_at > now)
        and exact_scope_matches(checked.scope, scope)
    )


class ProjectTrustSettings(FrozenStrictModel):
    project_id: ProjectId
    repository_identity: Sha256
    trust_mode: TrustMode = TrustMode.BALANCED
    allowed_paths: tuple[str, ...] = Field(default_factory=tuple, max_length=128)
    grants_revoked_before: datetime | None = None

    @field_validator("grants_revoked_before")
    @classmethod
    def validate_grant_cutoff(cls, value: datetime | None) -> datetime | None:
        return _utc(value) if value is not None else None

    @field_validator("allowed_paths")
    @classmethod
    def validate_paths(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            canonical_trust_path(value, allow_root=True)
        if len({value.casefold() for value in values}) != len(values):
            raise ValueError("reviewed path ceilings must be unique")
        return values


class UserTrustPolicy(FrozenStrictModel):
    api_version: Literal["agentfleet.dev/v1alpha1"] = "agentfleet.dev/v1alpha1"
    kind: Literal["UserTrustPolicy"] = "UserTrustPolicy"
    revision: int = Field(default=0, ge=0, le=2**63 - 1, strict=True)
    projects: list[ProjectTrustSettings] = Field(default_factory=list, max_length=1024)
    rules: list[UserTrustRule] = Field(default_factory=list, max_length=8192)

    @model_validator(mode="after")
    def validate_bindings(self) -> UserTrustPolicy:
        projects = {project.project_id: project for project in self.projects}
        if len(projects) != len(self.projects):
            raise ValueError("trust policy contains duplicate project IDs")
        if len({rule.rule_id for rule in self.rules}) != len(self.rules):
            raise ValueError("trust policy contains duplicate rule IDs")
        for rule in self.rules:
            project = projects.get(rule.scope.project_id)
            if project is None or project.repository_identity != rule.scope.repository_identity:
                raise ValueError("trust rule does not bind a registered policy project identity")
        return self
