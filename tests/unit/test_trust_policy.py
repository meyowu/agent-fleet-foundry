from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from agent_fleet.domain.models import (
    CanonicalResource,
    CommandSpec,
    SandboxSecurityLevel,
    WorkflowStage,
    WorkspaceKind,
)
from agent_fleet.domain.security import canonical_json_hash
from agent_fleet.domain.trust import (
    ExactPermissionScope,
    ProjectTrustSettings,
    TrustMode,
    UserTrustPolicy,
    UserTrustRule,
    canonical_trust_path,
    exact_scope_matches,
    is_protected_action,
    rule_matches,
    validate_exact_scope,
)

NOW = datetime(2026, 9, 5, tzinfo=UTC)


def scope(**changes: Any) -> ExactPermissionScope:
    command = CommandSpec(command_id="unit-tests", executable="npm", argv=("test",))
    values: dict[str, Any] = {
        "project_id": "prj_" + "1" * 32,
        "repository_identity": "a" * 64,
        "principal_role": "engineer",
        "workflow": "code-change",
        "stage": WorkflowStage.IMPLEMENTING,
        "action": "command.run",
        "resource": CanonicalResource(kind="project_command", identifier="unit-tests"),
        "parameters": {
            "command_id": command.command_id,
            "command_spec_sha256": canonical_json_hash(command.model_dump(mode="json")),
            "network_mode": "none",
        },
        "command": command,
        "workspace_kind": WorkspaceKind.CANDIDATE,
        "sandbox_provider": "docker",
        "sandbox_security_level": SandboxSecurityLevel.ISOLATED,
        "network_mode": "none",
    }
    return ExactPermissionScope.model_validate({**values, **changes})


def rule(**changes: Any) -> UserTrustRule:
    return UserTrustRule.model_validate(
        {
            "rule_id": "rule_" + "1" * 32,
            "scope": scope(),
            "effect": "allow",
            "created_at": NOW,
            **changes,
        }
    )


def test_exact_scope_round_trip_and_hash_do_not_expand_literal_parameters() -> None:
    original = scope()
    reconstructed = ExactPermissionScope.model_validate_json(original.model_dump_json())
    assert exact_scope_matches(original, reconstructed)
    assert original.scope_sha256 == canonical_json_hash(original.model_dump(mode="json"))
    write = scope(
        action="workspace.write_file",
        resource=CanonicalResource(kind="workspace_path", identifier="src/main.py"),
        parameters={"content": "print('*')\n"},
        command=None,
    )
    assert write.parameters["content"] == "print('*')\n"
    search = scope(
        action="repo.search_text",
        resource=CanonicalResource(kind="workspace_view", identifier="."),
        parameters={"query": "[a-z]*"},
        command=None,
    )
    assert search.parameters["query"] == "[a-z]*"


@pytest.mark.parametrize(
    "changes",
    [
        {"project_id": "prj_" + "2" * 32},
        {"repository_identity": "b" * 64},
        {"principal_role": "verifier"},
        {"workflow": "another-workflow"},
        {"stage": WorkflowStage.REPAIRING},
        {"workspace_kind": WorkspaceKind.VERIFICATION},
        {
            "sandbox_provider": "fake",
            "sandbox_security_level": SandboxSecurityLevel.FAKE,
        },
    ],
)
def test_exact_rule_does_not_match_another_authority_dimension(changes: dict[str, Any]) -> None:
    assert not rule_matches(rule(), scope(**changes), NOW)


@pytest.mark.parametrize("argv", [("install",), ("publish",), ("test", "&&", "curl"), ("test*",)])
def test_exact_command_argv_is_never_prefix_or_compound_authorization(
    argv: tuple[str, ...],
) -> None:
    command = scope().command
    assert command is not None
    changed = command.model_copy(update={"argv": argv})
    parameters = {
        "command_id": changed.command_id,
        "command_spec_sha256": canonical_json_hash(changed.model_dump(mode="json")),
        "network_mode": "none",
    }
    assert not rule_matches(rule(), scope(command=changed, parameters=parameters), NOW)


@pytest.mark.parametrize(
    "changes",
    [
        {"action": "host.sudo"},
        {"action": "audit.delete"},
        {"action": "policy.self-approve"},
        {"action": "network.any"},
        {"principal_role": "cos"},
        {"command": None},
        {"resource": {"kind": "project_command", "identifier": "unit-tests*"}},
        {"parameters": {"command_id": "unit-tests"}},
        {"source_checkout_read_only": False},
        {"sandbox_security_level": "unsafe_host"},
        {"network_mode": "approved-unrestricted"},
        {"unrecognized": True},
    ],
)
def test_malformed_or_protected_scope_is_rejected(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        scope(**changes)


@pytest.mark.parametrize("executable", ["sudo", "./sudo", "doas", "su"])
def test_command_action_cannot_disguise_privilege_escalation(executable: str) -> None:
    command = CommandSpec(command_id="unit-tests", executable=executable, argv=("npm", "test"))
    with pytest.raises(ValidationError):
        scope(
            command=command,
            parameters={
                "command_id": command.command_id,
                "command_spec_sha256": canonical_json_hash(command.model_dump(mode="json")),
                "network_mode": "none",
            },
        )


@pytest.mark.parametrize(
    "path",
    [
        ".",
        "../outside",
        "/etc/passwd",
        "src//a",
        "src/./a",
        "src/../a",
        "src/*",
        "a?",
        "a[b]",
        ".git/config",
        "src/.FLEET/a",
        "C:secret",
        "a\\b",
        "a\x00b",
    ],
)
def test_exact_path_scope_rejects_noncanonical_or_protected_selection(path: str) -> None:
    with pytest.raises(ValueError):
        canonical_trust_path(path)


def test_only_user_reviewed_ceiling_can_explicitly_cover_repository_root() -> None:
    settings = ProjectTrustSettings(
        project_id="prj_" + "1" * 32,
        repository_identity="a" * 64,
        allowed_paths=(".",),
    )
    assert settings.trust_mode is TrustMode.BALANCED
    assert settings.allowed_paths == (".",)
    assert ProjectTrustSettings.model_validate_json(settings.model_dump_json()) == settings


def test_rule_expiration_revocation_creation_and_owner_are_checked() -> None:
    active = rule(expires_at=NOW + timedelta(seconds=1))
    assert rule_matches(active, scope(), NOW)
    assert not rule_matches(active, scope(), NOW + timedelta(seconds=1))
    assert not rule_matches(active, scope(), NOW - timedelta(seconds=1))
    assert not rule_matches(rule(revoked_at=NOW), scope(), NOW)
    for changes in (
        {"created_by": "cos"},
        {"expires_at": NOW},
        {"revoked_at": NOW - timedelta(seconds=1)},
        {"created_at": NOW.replace(tzinfo=None)},
    ):
        with pytest.raises(ValidationError):
            rule(**changes)


def test_unchecked_nested_mutation_cannot_bypass_scope_revalidation() -> None:
    original = scope()
    original.parameters["network_mode"] = "approved-unrestricted"
    with pytest.raises(ValidationError):
        validate_exact_scope(original)


def test_policy_requires_unique_projects_rules_and_matching_repository_identity() -> None:
    settings = ProjectTrustSettings(project_id="prj_" + "1" * 32, repository_identity="a" * 64)
    valid = UserTrustPolicy(projects=[settings], rules=[rule()])
    assert valid.revision == 0
    assert UserTrustPolicy.model_validate_json(valid.model_dump_json()) == valid
    changes: dict[str, Any]
    for changes in (
        {"projects": []},
        {"projects": [settings, settings]},
        {"rules": [rule(), rule()]},
        {"rules": [rule(scope=scope(repository_identity="b" * 64))]},
        {"revision": True},
        {"hardDenies": []},
    ):
        with pytest.raises(ValidationError):
            UserTrustPolicy.model_validate({**valid.model_dump(mode="json"), **changes})


def test_protected_registry_covers_unknown_members_of_protected_families() -> None:
    assert is_protected_action("policy.future-approval-bypass")
    assert is_protected_action("sandbox.new-privileged-mode")
    assert not is_protected_action("command.run")
