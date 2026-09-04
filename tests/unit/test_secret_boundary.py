from __future__ import annotations

import base64
import json
import pickle
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote, quote_plus

import pytest

from agent_fleet.domain.security import Redactor
from agent_fleet.ports.secret_store import (
    InvalidSecretReferenceError,
    SecretRef,
    SecretResolutionError,
    SecretValue,
)


@pytest.mark.parametrize(
    "reference,name",
    [
        ("env:A", "A"),
        ("env:_TOKEN", "_TOKEN"),
        ("env:OPENAI_API_KEY", "OPENAI_API_KEY"),
        ("env:provider_key_2", "provider_key_2"),
        ("env:" + "A" * 128, "A" * 128),
    ],
)
def test_secret_ref_accepts_only_canonical_environment_references(
    reference: str, name: str
) -> None:
    parsed = SecretRef.parse(reference)

    assert parsed.name == name
    assert parsed.scheme == "env"
    assert parsed.reference == reference
    assert str(parsed) == reference


@pytest.mark.parametrize(
    "reference",
    [
        "",
        "OPENAI_API_KEY",
        "keyring:agent-fleet/openai",
        "env:",
        "env:1KEY",
        "env:BAD-NAME",
        "env:SPACE KEY",
        "env:KEY\n",
        " env:KEY",
        "env:KEY ",
        "env:ÅPI_KEY",
        "env:" + "A" * 129,
    ],
)
def test_secret_ref_rejects_malformed_values_without_echo(reference: str) -> None:
    with pytest.raises(InvalidSecretReferenceError) as captured:
        SecretRef(reference)

    if reference:
        assert reference not in str(captured.value)


def test_secret_value_is_opaque_and_cannot_be_serialized() -> None:
    raw = "phase-2-provider-secret+/="
    secret = SecretValue(raw)

    assert secret.reveal_for_provider() == raw
    assert raw not in str(secret)
    assert raw not in repr(secret)
    assert raw not in f"{secret:>100}"
    with pytest.raises(TypeError, match="not JSON serializable"):
        json.dumps({"secret": secret})
    assert raw not in json.dumps({"secret": secret}, default=str)
    with pytest.raises(TypeError, match="cannot be serialized"):
        secret.to_json()
    with pytest.raises(TypeError, match="cannot be serialized"):
        pickle.dumps(secret)


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "short",
        "contains\x00nul",
        "contains\nnewline",
        "contains space",
        "unicode-credential-ü",
        "surrogate-\ud800-credential",
        "x" * 16_385,
    ],
)
def test_secret_value_rejects_unsafe_or_unbounded_values(raw: str) -> None:
    with pytest.raises(SecretResolutionError):
        SecretValue(raw)


def test_dynamic_redaction_covers_raw_and_common_encodings() -> None:
    raw = "provider-secret/ü +?="
    encoded = raw.encode("utf-8")
    forms = {
        raw,
        quote(raw, safe=""),
        quote_plus(raw, safe=""),
        base64.b64encode(encoded).decode("ascii"),
        base64.b64encode(encoded).decode("ascii").rstrip("="),
        base64.urlsafe_b64encode(encoded).decode("ascii"),
        base64.urlsafe_b64encode(encoded).decode("ascii").rstrip("="),
        encoded.hex(),
        json.dumps(raw, ensure_ascii=True)[1:-1],
    }
    redactor = Redactor()

    assert redactor.register_secret(raw) is True
    assert redactor.register_secret(raw) is False
    for form in forms:
        assert redactor.contains_secret(f"prefix:{form}:suffix") is True
        cleaned, summary = redactor.redact_text(f"prefix:{form}:suffix")
        assert form not in cleaned
        assert summary == ["registered_secret_1"]


def test_registration_is_thread_safe_and_idempotent() -> None:
    secrets = [f"concurrent-secret-{index:03d}+/=" for index in range(32)]
    redactor = Redactor()

    with ThreadPoolExecutor(max_workers=16) as executor:
        registrations = list(executor.map(redactor.register_secret, secrets * 20))

    assert sum(registrations) == len(secrets)
    for secret in secrets:
        assert redactor.contains_secret(secret)
        assert redactor.contains_secret(base64.b64encode(secret.encode()).decode())


def test_bulk_registration_counts_only_new_nonempty_values() -> None:
    redactor = Redactor(["already-registered"])

    assert redactor.register_secrets(["new-secret", "", "new-secret"]) == 1
    assert redactor.contains_secret("already-registered")
    assert redactor.contains_secret("new-secret")
