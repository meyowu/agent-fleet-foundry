"""A credential-free child boundary can inspect presence, never registry values."""

from concurrent.futures import ThreadPoolExecutor

from agent_fleet.domain.security import Redactor


def test_presence_has_exact_boolean_type_and_ignores_empty_registration() -> None:
    redactor = Redactor()
    assert redactor.has_registered_secrets() is False
    assert redactor.register_secret("") is False
    assert redactor.has_registered_secrets() is False
    assert redactor.register_secret("synthetic-registry-test-value") is True
    assert redactor.has_registered_secrets() is True
    assert redactor.register_secret("synthetic-registry-test-value") is False
    assert redactor.has_registered_secrets() is True


def test_presence_observes_registration_from_another_thread() -> None:
    redactor = Redactor()
    with ThreadPoolExecutor(max_workers=1) as executor:
        assert redactor.has_registered_secrets() is False
        assert executor.submit(redactor.register_secret, "synthetic-thread-value").result()
        assert executor.submit(redactor.has_registered_secrets).result() is True
    assert redactor.has_registered_secrets() is True
    assert redactor.contains_secret("synthetic-thread-value") is True
