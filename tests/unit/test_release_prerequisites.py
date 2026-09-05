from __future__ import annotations

import socket

import pydantic_ai.models
import pytest
from conftest import _live_provider_inputs_are_ready

_INPUTS = {
    "AGENT_FLEET_ENABLE_LIVE_PROVIDER_TESTS": "1",
    "AGENT_FLEET_ENABLE_DOCKER_TESTS": "1",
    "AGENT_FLEET_DOCKER_TEST_IMAGE": "explicit-local-image",
    "AGENT_FLEET_LIVE_PROVIDER_MODEL": "openai:offline-readiness-only",
    "AGENT_FLEET_LIVE_PROVIDER_CREDENTIAL_REF": "env:FLEET_READINESS_SYNTHETIC_KEY",
    "FLEET_READINESS_SYNTHETIC_KEY": "synthetic-readiness-value-not-a-provider-credential",
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
