"""Permission CLI contracts using fake execution and disposable local state only."""

from __future__ import annotations

import asyncio
import base64
import gc
import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Never, cast

import pytest
from conftest import FleetHarness
from typer.testing import CliRunner

from agent_fleet.adapters.persistence.sqlite import SqliteStateStore
from agent_fleet.adapters.repository.git import GitRepositoryAdapter
from agent_fleet.adapters.system import UuidIdGenerator
from agent_fleet.bootstrap import build_container
from agent_fleet.cli.app import app
from agent_fleet.domain.models import ApprovalStatus, RunStatus
from agent_fleet.domain.security import canonical_json_hash

pytestmark = pytest.mark.integration


@dataclass
class PermissionCLI:
    harness: FleetHarness
    runner: CliRunner = field(default_factory=CliRunner)
    run_ids: list[str] = field(default_factory=list)

    @property
    def environment(self) -> dict[str, str]:
        return {"AGENT_FLEET_HOME": str(self.harness.state_root), "COLUMNS": "220"}

    def call(self, *arguments: str, succeeds: bool = True) -> dict[str, Any]:
        result = self.runner.invoke(app, [*arguments, "--json"], env=self.environment)
        assert (result.exit_code == 0) is succeeds, result.output
        envelope = cast(dict[str, Any], json.loads(result.stdout))
        assert envelope["api_version"] == "agentfleet.dev/v1alpha1"
        assert envelope["ok"] is succeeds
        return envelope

    def configure(self, mode: str, *paths: str) -> dict[str, Any]:
        arguments = [
            "permissions",
            "configure",
            "--project",
            str(self.harness.repository_root),
            "--mode",
            mode,
        ]
        for path in paths:
            arguments.extend(["--allow-path", path])
        return cast(dict[str, Any], self.call(*arguments)["data"])

    def paused_request(self) -> str:
        self.configure("safe", "src", "tests")
        run = asyncio.run(self.harness.start())
        self.run_ids.append(run.run_id)
        assert run.status is RunStatus.PAUSED_FOR_APPROVAL
        assert run.pending_approval_id is not None
        assert self.harness.container.state.count_executed_intents(run.run_id, "command.run") == 0
        return run.pending_approval_id


@pytest.fixture
def permission_cli(harness: FleetHarness) -> Iterator[PermissionCLI]:
    cli = PermissionCLI(harness)
    yield cli
    for run_id in cli.run_ids:
        asyncio.run(build_container(harness.state_root).cancellation.cancel(run_id))


def _files(root: Path) -> dict[str, bytes]:
    if not root.exists():
        return {}
    return {
        str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()
    }


def test_configure_list_and_reset_preserve_omitted_narrow_project_paths(
    permission_cli: PermissionCLI,
) -> None:
    cli = permission_cli
    repository = str(cli.harness.repository_root)
    original_configuration = _files(cli.harness.repository_root / ".fleet")
    safe = cli.configure("safe", "src", "tests")
    assert safe["trust_mode"] == "safe"
    assert safe["allowed_paths"] == ["src", "tests"]
    balanced = cli.configure("balanced")
    assert balanced["trust_mode"] == "balanced"
    assert balanced["allowed_paths"] == ["src", "tests"]
    listing = cli.call("permissions", "list", "--project", repository)["data"]
    assert listing["settings"] == balanced
    assert listing["rules"] == []
    assert listing["project_id"] == safe["project_id"]
    reset = cli.call("permissions", "reset", "--project", repository)["data"]
    assert reset["project_id"] == safe["project_id"]
    assert reset["revoked_rule_ids"] == []
    assert reset["revoked_grant_ids"] == []
    after_reset = cli.call("permissions", "list", "--project", repository)["data"]
    assert after_reset["settings"]["grants_revoked_before"] is not None
    for key in ("project_id", "repository_identity", "trust_mode", "allowed_paths"):
        assert after_reset["settings"][key] == balanced[key]
    assert _files(cli.harness.repository_root / ".fleet") == original_configuration
    assert not (cli.harness.repository_root / ".fleet" / "trust.yaml").exists()
    assert (cli.harness.state_root / "trust" / "trust.yaml").is_file()


@pytest.mark.parametrize(
    "flags,choice",
    [
        (["--run"], "allow_run"),
        (["--always", "--scope", "project"], "allow_always"),
    ],
)
def test_approve_run_and_always_bind_the_exact_explained_scope(
    permission_cli: PermissionCLI, flags: list[str], choice: str
) -> None:
    cli = permission_cli
    request_id = cli.paused_request()
    explained = cli.call("permissions", "explain", request_id)["data"]
    request = explained["request"]
    decision = explained["current_decision"]
    scope = request["authorization_scope"]
    assert decision["outcome"] == "require_approval"
    assert decision["effective_scope"] == scope
    assert decision["available_choices"] == ["deny", "allow_once", "allow_run", "allow_always"]
    assert scope["action"] == "command.run"
    assert scope["principal_role"] == "engineer"
    assert scope["stage"] == "implementing"
    assert scope["network_mode"] == "none"
    assert scope["workspace_kind"] == "candidate"
    assert scope["sandbox_provider"] == "fake"
    assert scope["command"]["command_id"] == request["resource"]["identifier"]
    assert isinstance(scope["command"]["argv"], list)
    assert scope["parameters"]["command_spec_sha256"] == canonical_json_hash(scope["command"])
    human = cli.runner.invoke(app, ["permissions", "explain", request_id], env=cli.environment)
    assert human.exit_code == 0, human.output
    for visible in ("command.run", "engineer", request["resource"]["identifier"], "network_mode"):
        assert visible in human.output
    grant = cli.call("approve", request_id, *flags)["data"]
    assert grant["choice"] == choice
    assert grant["scope_sha256"] == canonical_json_hash(scope)
    assert grant["resource"] == request["resource"]
    assert grant["run_id"] == request["run_id"]
    assert grant["principal_role"] == "engineer"
    assert grant["expires_at"] is None
    assert grant["remaining_uses"] is None
    assert cli.call("approve", request_id, *flags)["data"] == grant
    persisted = build_container(cli.harness.state_root)
    assert persisted.state.get_approval(request_id).status is ApprovalStatus.APPROVED
    assert len(persisted.state.list_grants(request["run_id"])) == 1
    assert persisted.state.count_executed_intents(request["run_id"], "command.run") == 0
    if choice == "allow_always":
        listed = cli.call("permissions", "list", "--project", str(cli.harness.repository_root))[
            "data"
        ]
        assert len(listed["rules"]) == 1
        rule = listed["rules"][0]
        assert rule["rule_id"] == grant["source_rule_id"]
        assert rule["scope"] == scope
        assert rule["active"] is True
    else:
        assert grant["source_rule_id"] is None


def test_rule_and_grant_revoke_and_project_reset_are_visible_after_reopen(
    permission_cli: PermissionCLI,
) -> None:
    cli = permission_cli
    request_id = cli.paused_request()
    grant = cli.call("approve", request_id, "--always", "--scope", "project")["data"]
    rule_id = grant["source_rule_id"]
    explained = cli.call("permissions", "explain", rule_id)["data"]
    assert explained["active"] is True
    assert explained["scope"]["principal_role"] == "engineer"
    revoked_rule = cli.call("permissions", "revoke", rule_id)["data"]
    assert revoked_rule["revoked_at"] is not None
    assert cli.call("permissions", "revoke", rule_id)["data"] == revoked_rule
    assert cli.call("permissions", "explain", rule_id)["data"]["active"] is False
    reset = cli.call("permissions", "reset", "--project", str(cli.harness.repository_root))["data"]
    assert reset["revoked_grant_ids"] == [grant["grant_id"]]
    revoked_grant = cli.call("permissions", "revoke", grant["grant_id"])["data"]
    assert revoked_grant["revoked_at"] is not None
    assert cli.call("permissions", "revoke", grant["grant_id"])["data"] == revoked_grant
    listing = cli.call("permissions", "list", "--project", str(cli.harness.repository_root))["data"]
    assert listing["settings"]["allowed_paths"] == ["src", "tests"]
    assert listing["rules"][0]["rule_id"] == rule_id
    assert listing["rules"][0]["active"] is False
    current = cli.call("permissions", "explain", request_id)["data"]["current_decision"]
    assert current["outcome"] == "require_approval"
    assert current["grant_id"] is None
    reopened = build_container(cli.harness.state_root)
    events = reopened.state.list_events(grant["run_id"])
    assert len([event for event in events if event.event_type == "capability.revoked"]) == 1
    assert reopened.state.count_executed_intents(grant["run_id"], "command.run") == 0


@pytest.mark.parametrize(
    "flags",
    [
        [],
        ["--once", "--run"],
        ["--once", "--always", "--scope", "project"],
        ["--run", "--always", "--scope", "project"],
        ["--always"],
        ["--always", "--scope", "all-projects"],
        ["--once", "--scope", "project"],
        ["--run", "--scope", "project"],
    ],
)
def test_approve_requires_one_explicit_duration_before_creating_state(
    tmp_path: Path, flags: list[str]
) -> None:
    state_root = tmp_path / "unused-state"
    result = CliRunner().invoke(
        app,
        ["approve", "perm_" + "9" * 32, *flags, "--json"],
        env={"AGENT_FLEET_HOME": str(state_root)},
    )
    assert result.exit_code != 0
    envelope = json.loads(result.stdout)
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "APPROVAL_INVALID"
    assert "exactly one" in envelope["error"]["message"]
    assert not state_root.exists()


@pytest.mark.parametrize(
    "path", ["../escape", "/absolute", "src/../tests", ".fleet", "src//core.py"]
)
def test_malformed_project_settings_preserve_existing_policy(
    permission_cli: PermissionCLI, path: str
) -> None:
    cli = permission_cli
    cli.configure("safe", "src")
    previous = _files(cli.harness.state_root / "trust")
    error = cli.call(
        "permissions",
        "configure",
        "--project",
        str(cli.harness.repository_root),
        "--mode",
        "balanced",
        "--allow-path",
        path,
        succeeds=False,
    )
    assert error["error"]["code"] == "APPROVAL_INVALID"
    assert _files(cli.harness.state_root / "trust") == previous
    assert cli.call("permissions", "list", "--project", str(cli.harness.repository_root))["data"][
        "settings"
    ]["allowed_paths"] == ["src"]


def test_registered_secrets_in_settings_and_malformed_trust_are_not_echoed(
    permission_cli: PermissionCLI,
) -> None:
    cli = permission_cli
    cli.configure("safe", "src")
    secret = "permission-cli-secret-that-must-not-be-echoed"
    encoded = base64.b64encode(secret.encode()).decode()
    environment = cli.environment | {"AGENT_FLEET_REDACT_VALUES": secret}
    before = _files(cli.harness.state_root / "trust")
    result = cli.runner.invoke(
        app,
        [
            "permissions",
            "configure",
            "--project",
            str(cli.harness.repository_root),
            "--mode",
            "balanced",
            "--allow-path",
            f"src/{secret}",
            "--json",
        ],
        env=environment,
    )
    assert result.exit_code != 0
    assert json.loads(result.stdout)["error"]["code"] == "APPROVAL_INVALID"
    assert secret not in result.output and encoded not in result.output
    assert _files(cli.harness.state_root / "trust") == before
    trust_path = cli.harness.state_root / "trust" / "trust.yaml"
    corrupted = f"projects: [\nunknown: {secret}\nencoded: {encoded}\n"
    trust_path.write_text(corrupted, encoding="utf-8")
    for machine in (True, False):
        arguments = ["permissions", "list", "--project", str(cli.harness.repository_root)]
        if machine:
            arguments.append("--json")
        malformed = cli.runner.invoke(app, arguments, env=environment)
        assert malformed.exit_code != 0
        assert secret not in malformed.output and encoded not in malformed.output
        assert "Traceback" not in malformed.output
        if machine:
            assert json.loads(malformed.stdout)["error"]["code"] == "STATE_UNAVAILABLE"
    assert trust_path.read_text(encoding="utf-8") == corrupted


@pytest.mark.parametrize("command", ["configure", "init"])
@pytest.mark.parametrize("encoded_value", [False, True])
def test_invalid_trust_mode_is_redacted_before_argument_failure(
    tmp_path: Path, command: str, encoded_value: bool
) -> None:
    state_root = tmp_path / "absent-state"
    secret = "registered-invalid-trust-mode-sentinel"
    encoded = base64.b64encode(secret.encode()).decode()
    value = encoded if encoded_value else secret
    arguments = (
        ["permissions", "configure", "--mode", value]
        if command == "configure"
        else ["init", str(tmp_path), "--preview", "--trust-mode", value]
    )
    result = CliRunner().invoke(
        app,
        [*arguments, "--json"],
        env={"AGENT_FLEET_HOME": str(state_root), "AGENT_FLEET_REDACT_VALUES": secret},
    )
    assert result.exit_code != 0
    assert secret not in result.output
    assert encoded not in result.output
    envelope = json.loads(result.stdout)
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "CONFIG_INVALID"
    assert not state_root.exists()


def test_fresh_init_preview_reports_user_policy_without_any_state_mutation(tmp_path: Path) -> None:
    repository = GitRepositoryAdapter(tmp_path, UuidIdGenerator()).create_canary_fixture(
        tmp_path / "preview-repository"
    )
    state_root = tmp_path / "absent-state"
    before = _files(repository)
    result = CliRunner().invoke(
        app,
        [
            "init",
            str(repository),
            "--runtime",
            "fake",
            "--sandbox",
            "fake",
            "--preview",
            "--trust-mode",
            "safe",
            "--allow-path",
            "src",
            "--json",
        ],
        env={"AGENT_FLEET_HOME": str(state_root)},
    )
    assert result.exit_code == 0, result.output
    proposal = json.loads(result.stdout)["data"]["proposed_user_policy"]
    assert proposal["trust_mode"] == "safe"
    assert proposal["allowed_paths"] == ["src"]
    assert proposal["protected_paths"] == [".git", ".fleet"]
    assert "outside the repository" in proposal["ownership"]
    assert _files(repository) == before
    assert not (repository / ".fleet").exists()
    assert not state_root.exists()


def test_repeat_init_preview_preserves_omitted_policy_and_displays_explicit_changes(
    permission_cli: PermissionCLI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cli = permission_cli
    cli.configure("safe", "src")
    # SQLite connection cycles from fixture setup may checkpoint on collection.
    # Finish that setup before measuring the preview's strictly read-only path.
    gc.collect()
    state_before = _files(cli.harness.state_root)
    repository_before = _files(cli.harness.repository_root)

    def reject_state_access(*args: object, **kwargs: object) -> Never:
        del args, kwargs
        raise AssertionError("init preview must not open the Fleet state database")

    monkeypatch.setattr(SqliteStateStore, "_connect", reject_state_access)
    preserved = cli.call("init", str(cli.harness.repository_root), "--preview")["data"][
        "proposed_user_policy"
    ]
    assert preserved["trust_mode"] == "safe"
    assert preserved["allowed_paths"] == ["src"]
    assert _files(cli.harness.state_root) == state_before
    assert _files(cli.harness.repository_root) == repository_before
    changed = cli.call(
        "init",
        str(cli.harness.repository_root),
        "--preview",
        "--trust-mode",
        "balanced",
        "--allow-path",
        "tests",
    )["data"]["proposed_user_policy"]
    assert changed["trust_mode"] == "balanced"
    assert changed["allowed_paths"] == ["tests"]
    assert _files(cli.harness.state_root) == state_before
    assert _files(cli.harness.repository_root) == repository_before
