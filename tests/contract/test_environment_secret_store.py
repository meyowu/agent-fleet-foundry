from __future__ import annotations

from collections.abc import Iterator, Mapping

import pytest

from agent_fleet.adapters.secrets.environment import EnvironmentSecretStore
from agent_fleet.domain.security import Redactor
from agent_fleet.ports.secret_store import (
    InvalidSecretReferenceError,
    SecretInspection,
    SecretNotConfiguredError,
    SecretRef,
    SecretResolutionError,
    SecretStatus,
    SecretStore,
)


class CountingEnvironment(Mapping[str, str]):
    def __init__(self, values: dict[str, str]) -> None:
        self._values = values
        self.reads: list[str] = []

    def __getitem__(self, key: str) -> str:
        self.reads.append(key)
        return self._values[key]

    def __iter__(self) -> Iterator[str]:
        raise AssertionError("secret resolution must not enumerate the environment")

    def __len__(self) -> int:
        return len(self._values)


def test_environment_secret_store_satisfies_synchronous_port_and_reads_once() -> None:
    raw = "provider-secret+/="
    environment = CountingEnvironment({"MODEL_KEY": raw, "UNRELATED": "do-not-read"})
    redactor = Redactor()
    store: SecretStore = EnvironmentSecretStore(redactor, environment)

    resolved = store.resolve(SecretRef("env:MODEL_KEY"))

    assert resolved.reveal_for_provider() == raw
    assert environment.reads == ["MODEL_KEY"]
    assert redactor.contains_secret(raw)
    assert redactor.contains_secret("cHJvdmlkZXItc2VjcmV0Ky89")


def test_inspection_is_side_effect_free_and_exposes_only_status() -> None:
    raw = "inspect-only-secret"
    redactor = Redactor()
    store = EnvironmentSecretStore(redactor, {"MODEL_KEY": raw})

    inspection = store.inspect("env:MODEL_KEY")

    assert inspection == SecretInspection(status=SecretStatus.CONFIGURED)
    assert store.is_configured("env:MODEL_KEY") is True
    assert raw not in repr(inspection)
    assert redactor.contains_secret(raw) is False


@pytest.mark.parametrize("environment", [{}, {"MODEL_KEY": ""}])
def test_missing_and_empty_environment_values_are_not_configured(
    environment: dict[str, str],
) -> None:
    store = EnvironmentSecretStore(Redactor(), environment)

    assert store.inspect("env:MODEL_KEY").status is SecretStatus.MISSING
    assert store.is_configured("env:MODEL_KEY") is False
    with pytest.raises(SecretNotConfiguredError) as captured:
        store.resolve("env:MODEL_KEY")
    assert captured.value.variable_name == "MODEL_KEY"
    assert "MODEL_KEY" not in str(captured.value)


def test_invalid_reference_inspects_safely_and_resolve_fails_without_echo() -> None:
    invalid = "not-env:credential-secret"
    store = EnvironmentSecretStore(Redactor(), {})

    assert store.inspect(invalid).status is SecretStatus.INVALID
    assert store.is_configured(invalid) is False
    with pytest.raises(InvalidSecretReferenceError) as captured:
        store.resolve(invalid)
    assert invalid not in str(captured.value)


@pytest.mark.parametrize(
    "raw",
    ["short", "contains\x00nul", "contains\nnewline", "unicode-secret-ü", "x" * 16_385],
)
def test_invalid_resolved_value_is_not_registered(raw: str) -> None:
    redactor = Redactor()
    store = EnvironmentSecretStore(redactor, {"MODEL_KEY": raw})

    assert store.inspect("env:MODEL_KEY").status is SecretStatus.INVALID
    assert store.is_configured("env:MODEL_KEY") is False
    with pytest.raises(SecretResolutionError):
        store.resolve("env:MODEL_KEY")
    assert redactor.contains_secret(raw) is False


def test_resolve_never_mutates_the_environment_mapping() -> None:
    environment = {"MODEL_KEY": "provider-secret", "UNCHANGED": "value"}
    before = environment.copy()

    EnvironmentSecretStore(Redactor(), environment).resolve("env:MODEL_KEY")

    assert environment == before
