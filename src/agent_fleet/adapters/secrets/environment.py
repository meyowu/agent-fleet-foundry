"""Environment-backed BYOK credential resolution."""

from __future__ import annotations

import os
from collections.abc import Mapping

from agent_fleet.domain.security import Redactor
from agent_fleet.ports.secret_store import (
    InvalidSecretReferenceError,
    SecretInspection,
    SecretNotConfiguredError,
    SecretRef,
    SecretResolutionError,
    SecretStatus,
    SecretValue,
)


class EnvironmentSecretStore:
    """Resolve exactly one explicit ``env:NAME`` reference in the control plane."""

    def __init__(
        self,
        redactor: Redactor,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        self._redactor = redactor
        self._environment = environment if environment is not None else os.environ

    def inspect(self, reference: SecretRef | str) -> SecretInspection:
        try:
            parsed = _parse_reference(reference)
        except InvalidSecretReferenceError:
            return SecretInspection(status=SecretStatus.INVALID)
        value = self._environment.get(parsed.name)
        if not value:
            return SecretInspection(status=SecretStatus.MISSING)
        try:
            SecretValue(value)
        except SecretResolutionError:
            return SecretInspection(status=SecretStatus.INVALID)
        return SecretInspection(status=SecretStatus.CONFIGURED)

    def is_configured(self, reference: SecretRef | str) -> bool:
        return self.inspect(reference).status is SecretStatus.CONFIGURED

    def resolve(self, reference: SecretRef | str) -> SecretValue:
        parsed = _parse_reference(reference)
        value = self._environment.get(parsed.name)
        if not value:
            raise SecretNotConfiguredError(parsed.name)
        try:
            resolved = SecretValue(value)
        except SecretResolutionError:
            raise SecretResolutionError from None
        self._redactor.register_secret(value)
        return resolved


def _parse_reference(reference: SecretRef | str) -> SecretRef:
    if isinstance(reference, SecretRef):
        return reference
    return SecretRef.parse(reference)
