"""Strict wire bindings, bounded alias grammar and credential-safe projections."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone

import pytest
from model_profiles_fixtures import model_configuration
from pydantic import ValidationError

from agent_fleet.domain.model_profiles import (
    ModelProfile,
    ProjectModelSelection,
    ResolvedModelBinding,
    RunModelBindings,
    configuration_hash,
)
from agent_fleet.domain.models import RuntimeConfiguration


@pytest.mark.parametrize(
    "name", ["", "UPPER", "../key", "name.with.dot", "é", "x" * 65, "a\n", "a b", "1first"]
)
def test_alias_rejects_unsafe_and_unbounded_names(name: str) -> None:
    with pytest.raises(ValidationError):
        ModelProfile(name=name, revision=1, configuration=RuntimeConfiguration())


@pytest.mark.parametrize("revision", [True, 0, -1, "1", 2**63])
def test_profile_revision_is_strict_monotonic_integer(revision: object) -> None:
    with pytest.raises(ValidationError):
        ModelProfile.model_validate({"name": "safe", "revision": revision, "configuration": {}})


@pytest.mark.parametrize(
    "configuration",
    [
        {"runtime_name": "custom"},
        {
            "runtime_name": "pydantic-ai",
            "provider_model": "other:model",
            "credential_ref": "env:KEY",
        },
        {
            "runtime_name": "pydantic-ai",
            "provider_model": "openai:model",
            "credential_ref": "raw-secret",
        },
        {
            "runtime_name": "pydantic-ai",
            "provider_model": "openai:model",
            "credential_ref": "env:KEY",
            "base_url": "https://invalid.example",
        },
    ],
)
def test_profiles_never_add_provider_or_endpoint_trust(configuration: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ModelProfile.model_validate({"name": "safe", "revision": 1, "configuration": configuration})


def test_configuration_projection_omits_reference_and_preserves_limits() -> None:
    profile = ModelProfile(name="coding", revision=1, configuration=model_configuration())
    projected = profile.safe_projection()
    assert "FIXTURE_KEY" not in json.dumps(projected)
    assert "credential_ref" not in json.dumps(projected)
    assert projected["credential_required"] is True
    assert projected["configuration_sha256"] == configuration_hash(profile.configuration)
    assert profile == ModelProfile.model_validate_json(profile.model_dump_json())


@pytest.mark.parametrize("permitted", [(), ("other",), ("coding", "coding"), ("z", "coding")])
def test_selection_requires_exact_sorted_unique_approval(permitted: tuple[str, ...]) -> None:
    with pytest.raises(ValidationError):
        ProjectModelSelection(
            project_id="prj_" + "1" * 32,
            repository_identity="2" * 64,
            revision=1,
            default_profile="coding",
            permitted_profiles=permitted,
        )


def test_binding_hash_and_role_identity_are_enforced() -> None:
    config = RuntimeConfiguration()
    with pytest.raises(ValidationError):
        ResolvedModelBinding(
            role_id="cos", source="legacy", configuration=config, configuration_sha256="f" * 64
        )
    binding = ResolvedModelBinding(
        role_id="cos",
        source="legacy",
        configuration=config,
        configuration_sha256=configuration_hash(config),
    )
    with pytest.raises(ValidationError):
        RunModelBindings(
            root_run_id="run_" + "1" * 32,
            project_id="prj_" + "2" * 32,
            repository_identity="3" * 64,
            created_at=datetime.now(UTC),
            roles={"engineer": binding},
        )


@pytest.mark.parametrize(
    "timestamp", [datetime(2026, 9, 7), datetime(2026, 9, 7, tzinfo=timezone(timedelta(hours=1)))]
)
def test_snapshot_rejects_non_utc_timestamp(timestamp: datetime) -> None:
    config = RuntimeConfiguration()
    binding = ResolvedModelBinding(
        role_id="cos",
        source="legacy",
        configuration=config,
        configuration_sha256=configuration_hash(config),
    )
    with pytest.raises(ValidationError):
        RunModelBindings(
            root_run_id="run_" + "1" * 32,
            project_id="prj_" + "2" * 32,
            repository_identity="3" * 64,
            created_at=timestamp,
            roles={"cos": binding},
        )


def test_snapshot_cannot_mix_profile_revisions_or_legacy_sources() -> None:
    config = RuntimeConfiguration()
    first = ResolvedModelBinding(
        role_id="cos",
        source="default",
        profile_name="coding",
        profile_revision=1,
        configuration=config,
        configuration_sha256=configuration_hash(config),
    )
    second = first.model_copy(update={"role_id": "engineer", "profile_revision": 2})
    payload = {
        "root_run_id": "run_" + "1" * 32,
        "project_id": "prj_" + "2" * 32,
        "repository_identity": "3" * 64,
        "created_at": datetime.now(UTC),
        "roles": {"cos": first, "engineer": second},
    }
    with pytest.raises(ValidationError):
        RunModelBindings.model_validate(payload | {"selection_revision": 1})
    with pytest.raises(ValidationError):
        RunModelBindings.model_validate(payload | {"roles": {"cos": first}})
