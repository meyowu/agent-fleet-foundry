from __future__ import annotations

import json
import socket

import pydantic_ai.models
import pytest
from conftest import _live_provider_inputs_are_ready
from live_provider_support import SELECTION_ENV

_SELECTION = json.dumps(
    {
        "schema_version": 1,
        "cos": {
            "runtime_name": "pydantic-ai",
            "provider_model": "openai:offline-readiness-only",
            "credential_ref": "env:FLEET_READINESS_COS_SYNTHETIC_KEY",
        },
        "engineer": {
            "runtime_name": "pydantic-ai",
            "provider_model": "openai:offline-readiness-only",
            "credential_ref": "env:FLEET_READINESS_ENGINEER_SYNTHETIC_KEY",
        },
        "verifier": {
            "runtime_name": "pydantic-ai",
            "provider_model": "openai:offline-readiness-only",
            "credential_ref": "env:FLEET_READINESS_VERIFIER_SYNTHETIC_KEY",
        },
    },
    sort_keys=True,
    separators=(",", ":"),
)

_INPUTS = {
    "AGENT_FLEET_ENABLE_LIVE_PROVIDER_TESTS": "1",
    "AGENT_FLEET_ENABLE_DOCKER_TESTS": "1",
    "AGENT_FLEET_DOCKER_TEST_IMAGE": "explicit-local-image",
    SELECTION_ENV: _SELECTION,
    "FLEET_READINESS_COS_SYNTHETIC_KEY": "synthetic-cos-readiness-value",
    "FLEET_READINESS_ENGINEER_SYNTHETIC_KEY": "synthetic-engineer-readiness-value",
    "FLEET_READINESS_VERIFIER_SYNTHETIC_KEY": "synthetic-verifier-readiness-value",
}


@pytest.mark.parametrize("missing", [None, *_INPUTS])
def test_live_readiness_requires_both_independent_opt_ins_and_all_inputs(
    monkeypatch: pytest.MonkeyPatch,
    missing: str | None,
) -> None:
    for key, value in _INPUTS.items():
        monkeypatch.setenv(key, "" if key == missing else value)
    assert _live_provider_inputs_are_ready() is (missing is None)
    # Checking inputs alone cannot open the request boundary.
    assert pydantic_ai.models.ALLOW_MODEL_REQUESTS is False
    with pytest.raises(AssertionError, match="must not perform network access"):
        socket.getaddrinfo("example.com", 443)


def test_live_readiness_rejects_malformed_selection(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in _INPUTS.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv(SELECTION_ENV, '{"schema_version":1')

    assert _live_provider_inputs_are_ready() is False


def test_live_readiness_rejects_legacy_only_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _INPUTS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("AGENT_FLEET_ENABLE_LIVE_PROVIDER_TESTS", "1")
    monkeypatch.setenv("AGENT_FLEET_ENABLE_DOCKER_TESTS", "1")
    monkeypatch.setenv("AGENT_FLEET_DOCKER_TEST_IMAGE", "explicit-local-image")
    monkeypatch.setenv("AGENT_FLEET_LIVE_PROVIDER_MODEL", "openai:offline-readiness-only")
    monkeypatch.setenv(
        "AGENT_FLEET_LIVE_PROVIDER_CREDENTIAL_REF",
        "env:FLEET_READINESS_LEGACY_SYNTHETIC_KEY",
    )
    monkeypatch.setenv(
        "FLEET_READINESS_LEGACY_SYNTHETIC_KEY",
        "synthetic-legacy-readiness-value",
    )

    assert _live_provider_inputs_are_ready() is False
