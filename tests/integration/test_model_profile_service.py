"""Exact multi-role resolution using real storage, secret store and adapter preflight."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import typer
from model_profiles_fixtures import ProfileHarness, make_profile_harness, model_configuration
from typer.testing import CliRunner

from agent_fleet.cli.app import _present_error, _present_with_warnings
from agent_fleet.cli.app import app as fleet_app
from agent_fleet.cli.models import register_models_commands
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import RuntimeConfiguration

pytestmark = pytest.mark.integration


@pytest.fixture
def harness(tmp_path: Path) -> ProfileHarness:
    return make_profile_harness(tmp_path)


def test_exact_override_repository_preference_default_order(harness: ProfileHarness) -> None:
    for name in ("planning", "coding", "reviewing"):
        configuration = model_configuration(f"openai:{name}", f"env:{name.upper()}_KEY")
        harness.environment[f"{name.upper()}_KEY"] = f"fixture-{name}-credential"
        harness.service.set(name, configuration=configuration)
    harness.service.bind(
        harness.project,
        profile="planning",
        default=True,
        permit=("reviewing",),
        expected_revision=0,
    )
    harness.service.bind(
        harness.project, profile="coding", role="backend_engineer", expected_revision=1
    )
    run = harness.run()
    snapshot = harness.service.resolve(
        harness.project,
        root_run_id=run.run_id,
        roles=("cos", "backend_engineer", "verifier"),
        repository_preferences={"backend_engineer": "reviewing", "verifier": "reviewing"},
        legacy_configuration=RuntimeConfiguration(),
    )
    harness.service.save_bindings(snapshot)
    assert {role: binding.source for role, binding in snapshot.roles.items()} == {
        "cos": "default",
        "backend_engineer": "override",
        "verifier": "repository_preference",
    }
    assert {
        role: binding.configuration.provider_model for role, binding in snapshot.roles.items()
    } == {
        "cos": "openai:planning",
        "backend_engineer": "openai:coding",
        "verifier": "openai:reviewing",
    }
    assert snapshot.roles["backend_engineer"].configuration.credential_ref == "env:CODING_KEY"
    assert snapshot.roles["verifier"].configuration.credential_ref == "env:REVIEWING_KEY"
    assert harness.reopen().get_bindings(harness.project.project_id, run.run_id) == snapshot
    rendered = json.dumps(snapshot.safe_projection())
    assert "_KEY" not in rendered
    for sentinel in harness.environment.values():
        assert sentinel not in rendered
        assert sentinel.encode() not in harness.state.database_path.read_bytes()
    assert [item.action for item in harness.store.list_audit()][-1] == "run.bind"


@pytest.mark.parametrize(
    "case",
    ["unapproved", "missing", "disabled", "incomplete_default", "unreviewed_legacy_preference"],
)
def test_no_missing_or_unapproved_model_fallback(harness: ProfileHarness, case: str) -> None:
    harness.add("planning")
    preferences = {"verifier": "other"}
    if case != "unreviewed_legacy_preference":
        harness.service.bind(harness.project, profile="planning", default=True, expected_revision=0)
    if case == "unapproved":
        harness.add("other")
    if case == "disabled":
        other = harness.add("other")
        harness.service.bind(harness.project, permit=("other",), expected_revision=1)
        harness.store.save_profile(
            other.model_copy(update={"revision": 2, "enabled": False}), expected_revision=1
        )
    if case == "incomplete_default":
        harness.service.bind(harness.project, clear=True, default=True, expected_revision=1)
        preferences = {}
    with pytest.raises(FleetError):
        harness.service.resolve(
            harness.project,
            root_run_id=harness.run().run_id,
            roles=("cos", "verifier"),
            repository_preferences=preferences,
            legacy_configuration=RuntimeConfiguration(),
        )
    assert not any(item.action == "run.bind" for item in harness.store.list_audit())


def test_missing_key_fails_complete_preflight_before_binding_persistence(
    harness: ProfileHarness,
) -> None:
    harness.service.set("planning", configuration=model_configuration(reference="env:PLANNING_KEY"))
    harness.service.set(
        "reviewing", configuration=model_configuration(reference="env:REVIEWING_KEY")
    )
    harness.environment["PLANNING_KEY"] = "fixture-planning-credential"
    harness.service.bind(harness.project, profile="planning", default=True, expected_revision=0)
    harness.service.bind(harness.project, profile="reviewing", role="verifier", expected_revision=1)
    with pytest.raises(FleetError) as caught:
        harness.resolve()
    assert caught.value.code is ErrorCode.CREDENTIAL_MISSING
    assert not any(item.action == "run.bind" for item in harness.store.list_audit())


def test_profile_change_after_registration_does_not_change_resume(harness: ProfileHarness) -> None:
    harness.environment.update({"OLD_KEY": "fixture-old-secret", "NEW_KEY": "fixture-new-secret"})
    harness.service.set(
        "coding", configuration=model_configuration("openai:old-model", "env:OLD_KEY")
    )
    harness.service.bind(harness.project, profile="coding", default=True, expected_revision=0)
    snapshot = harness.resolve()
    harness.service.save_bindings(snapshot)
    harness.service.set(
        "coding",
        configuration=model_configuration("openai:new-model", "env:NEW_KEY"),
        expected_revision=1,
    )
    restored = harness.service.for_run(
        harness.project,
        root_run_id=snapshot.root_run_id,
        expected_sha256=snapshot.bindings_sha256,
        required_roles=("cos", "verifier"),
    )
    assert restored == snapshot
    assert restored.roles["verifier"].configuration.provider_model == "openai:old-model"
    assert restored.roles["verifier"].configuration.credential_ref == "env:OLD_KEY"
    assert harness.resolve().roles["verifier"].configuration.provider_model == "openai:new-model"
    del harness.environment["OLD_KEY"]
    with pytest.raises(FleetError) as caught:
        harness.service.for_run(
            harness.project,
            root_run_id=snapshot.root_run_id,
            expected_sha256=snapshot.bindings_sha256,
            required_roles=("cos",),
        )
    assert caught.value.code is ErrorCode.CREDENTIAL_MISSING


def test_same_reference_value_rotation_is_permitted(harness: ProfileHarness) -> None:
    harness.environment["FIXTURE_KEY"] = "fixture-original-value"
    harness.service.set("coding", configuration=model_configuration())
    harness.service.bind(harness.project, profile="coding", default=True, expected_revision=0)
    snapshot = harness.resolve()
    harness.service.save_bindings(snapshot)
    harness.environment["FIXTURE_KEY"] = "fixture-rotated-value"
    assert (
        harness.service.for_run(
            harness.project,
            root_run_id=snapshot.root_run_id,
            expected_sha256=snapshot.bindings_sha256,
            required_roles=("engineer",),
        )
        == snapshot
    )
    assert harness.state.redactor.contains_secret("fixture-original-value")
    assert harness.state.redactor.contains_secret("fixture-rotated-value")


def test_companion_profile_secret_is_registered_before_listing(harness: ProfileHarness) -> None:
    sentinel = "secret_model_name"
    harness.add(sentinel)
    harness.add("key_holder", model_configuration())
    harness.environment["FIXTURE_KEY"] = sentinel
    with pytest.raises(FleetError) as caught:
        harness.service.list()
    assert sentinel not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_secret_in_explicit_profile_field_is_rejected_before_mutation(
    harness: ProfileHarness,
) -> None:
    sentinel = "secret_model_name"
    harness.environment["FIXTURE_KEY"] = sentinel
    with pytest.raises(FleetError) as caught:
        harness.service.set(sentinel, configuration=model_configuration())
    assert sentinel not in str(caught.value)
    assert harness.store.list_audit() == ()
    assert sentinel.encode() not in harness.state.database_path.read_bytes()


def test_clearing_selection_is_not_reverting_to_legacy(harness: ProfileHarness) -> None:
    assert harness.service.selection(harness.project)["mode"] == "legacy"
    assert all(binding.source == "legacy" for binding in harness.resolve().roles.values())
    harness.add("coding")
    harness.service.bind(harness.project, profile="coding", default=True, expected_revision=0)
    harness.service.bind(
        harness.project, default=True, clear=True, revoke=("coding",), expected_revision=1
    )
    assert harness.service.selection(harness.project)["revision"] == 2
    with pytest.raises(FleetError):
        harness.resolve()


def test_new_selection_does_not_require_obsolete_project_credential(
    harness: ProfileHarness,
) -> None:
    project = harness.project.model_copy(
        update={
            "runtime_name": "pydantic-ai",
            "provider_model": "openai:obsolete-model",
            "credential_ref": "env:OBSOLETE_KEY",
        }
    )
    harness.state.save_project(project)
    harness.environment["OBSOLETE_KEY"] = "invalid short value"
    harness.add("offline")
    harness.service.bind(project, profile="offline", default=True, expected_revision=0)
    assert harness.service.prepare_project(project) is True
    snapshot = harness.service.resolve(
        project,
        root_run_id=harness.run().run_id,
        roles=("cos", "engineer", "verifier"),
        legacy_configuration=model_configuration("openai:obsolete-model", "env:OBSOLETE_KEY"),
    )
    assert all(item.configuration.runtime_name == "fake" for item in snapshot.roles.values())
    assert not harness.state.redactor.contains_secret("invalid short value")


def cli(harness: ProfileHarness) -> typer.Typer:
    app = typer.Typer()
    register_models_commands(
        app,
        service_factory=lambda _: harness.service,
        redactor_factory=lambda: harness.state.redactor,
        presenter=_present_with_warnings,
        error_presenter=_present_error,
    )
    return app


def test_cli_set_show_remove_is_persistent_and_revisioned(harness: ProfileHarness) -> None:
    app, runner = cli(harness), CliRunner()
    result = runner.invoke(app, ["models", "set", "coding", "--runtime", "fake", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["data"]["revision"] == 1
    result = runner.invoke(app, ["models", "show", "coding", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output)["data"]["name"] == "coding"
    stale = runner.invoke(app, ["models", "set", "coding", "--runtime", "fake", "--json"])
    assert stale.exit_code != 0
    assert harness.store.profile_revision("coding") == 1
    removed = runner.invoke(app, ["models", "remove", "coding", "--revision", "1", "--json"])
    assert removed.exit_code == 0, removed.output
    assert harness.reopen().get_profile("coding") is None
    assert json.loads(removed.output)["data"]["revision"] == 2


@pytest.mark.parametrize(
    "arguments",
    [
        ["set", "secret-value", "--runtime", "fake", "--max-requests", "secret-value"],
        [
            "set",
            "coding",
            "--runtime",
            "pydantic-ai",
            "--provider-model",
            "openai:model",
            "--credential-ref",
            "secret-value",
        ],
        ["set", "coding", "--runtime", "fake", "--unknown-secret-value"],
        ["remove", "coding", "--revision", "secret-value"],
        ["secret-value"],
        ["--secret-value"],
    ],
)
def test_cli_invalid_arguments_do_not_echo_potential_credentials(
    harness: ProfileHarness, arguments: list[str]
) -> None:
    result = CliRunner().invoke(cli(harness), ["models", *arguments, "--json"])
    assert result.exit_code != 0
    assert "secret-value" not in result.output
    assert json.loads(result.output)["ok"] is False
    assert harness.store.list_audit() == ()


def test_cli_bind_selection_against_real_registered_repository(tmp_path: Path) -> None:
    harness = make_profile_harness(tmp_path, real_repository=True)
    harness.add("coding")
    app, runner = cli(harness), CliRunner()
    bound = runner.invoke(
        app,
        [
            "models",
            "bind",
            "coding",
            "--path",
            harness.project.canonical_root,
            "--default",
            "--json",
        ],
    )
    assert bound.exit_code == 0, bound.output
    shown = runner.invoke(app, ["models", "selection", harness.project.canonical_root, "--json"])
    assert shown.exit_code == 0, shown.output
    assert json.loads(shown.output)["data"]["default_profile"] == "coding"
    persisted = harness.reopen().get_selection(harness.project.project_id)
    assert persisted is not None and persisted.permitted_profiles == ("coding",)
    assert [item.action for item in harness.store.list_audit()] == ["profile.set", "selection.set"]


def test_cli_inspection_has_no_credential_reference_or_value(harness: ProfileHarness) -> None:
    harness.environment["FIXTURE_KEY"] = "fixture-provider-secret"
    harness.add("coding", model_configuration())
    result = CliRunner().invoke(cli(harness), ["models", "list", "--json"])
    assert result.exit_code == 0, result.output
    assert "FIXTURE_KEY" not in result.output
    assert "fixture-provider-secret" not in result.output
    assert "credential_ref" not in result.output
    assert "openai:fixture-model" in result.output


def test_real_cli_composition_reopens_profile_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AGENT_FLEET_HOME", str(tmp_path / "cli-state"))
    runner = CliRunner()
    created = runner.invoke(fleet_app, ["models", "set", "offline", "--runtime", "fake", "--json"])
    assert created.exit_code == 0, created.output
    listed = runner.invoke(fleet_app, ["models", "list", "--json"])
    assert listed.exit_code == 0, listed.output
    assert json.loads(listed.output)["data"]["profiles"][0]["name"] == "offline"
    removed = runner.invoke(fleet_app, ["models", "remove", "offline", "--revision", "1", "--json"])
    assert removed.exit_code == 0, removed.output
    assert (
        json.loads(runner.invoke(fleet_app, ["models", "list", "--json"]).output)["data"][
            "profiles"
        ]
        == []
    )
