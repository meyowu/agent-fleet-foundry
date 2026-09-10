from __future__ import annotations

import pytest

from agent_fleet.cli.app import _runtime_warnings


@pytest.mark.parametrize(
    "runtime", ["pydantic-ai", "openai-agents", "langgraph", "fake", "unknown-runtime", None]
)
@pytest.mark.parametrize("sandbox", ["docker", "local-unsafe", "fake", "unknown-sandbox", None])
def test_configuration_warning_never_claims_observed_execution(
    runtime: str | None, sandbox: str | None
) -> None:
    warning = _runtime_warnings({"runtime": runtime, "sandbox": sandbox})[0]
    assert "was contacted" not in warning
    assert "executed project commands" not in warning
    assert "project commands used" not in warning
    assert "unknown-runtime" not in warning
    assert "unknown-sandbox" not in warning
    if runtime in {"pydantic-ai", "openai-agents", "langgraph"}:
        assert "actual provider contact requires run evidence" in warning
    elif runtime == "fake":
        assert "does not make model-provider calls" in warning
    else:
        assert "Runtime execution is not established" in warning
    if sandbox == "docker":
        assert "subject to run evidence and proof gaps" in warning
    elif sandbox == "local-unsafe":
        assert "WARNING: local-unsafe" in warning
        assert "without isolation" in warning
    elif sandbox == "fake":
        assert "FakeSandbox cannot execute" in warning
    else:
        assert "No sandbox execution or isolation is established" in warning


def test_warning_supports_the_existing_sandbox_name_alias() -> None:
    assert "Docker is configured" in _runtime_warnings({"sandbox_name": "docker"})[0]


def test_empty_status_does_not_invent_a_fake_runtime_or_sandbox() -> None:
    warning = _runtime_warnings({})[0]
    assert "fake" not in warning.casefold()
    assert "not established" in warning


@pytest.mark.parametrize("value", [[], {}, True, 1])
def test_non_string_mode_values_remain_unverified(value: object) -> None:
    warning = _runtime_warnings({"runtime": value, "sandbox": value})[0]
    assert "Runtime execution is not established" in warning
    assert "No sandbox execution or isolation is established" in warning
