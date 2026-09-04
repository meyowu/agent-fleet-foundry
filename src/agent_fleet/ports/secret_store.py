from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, Self

_ENV_REFERENCE_PREFIX = "env:"
_ENV_NAME_PATTERN = r"[A-Za-z_][A-Za-z0-9_]*"
_MAX_REFERENCE_LENGTH = 132
_MIN_SECRET_BYTES = 8
_MAX_SECRET_BYTES = 16_384


class SecretStoreError(Exception):
    """Base error for provider-neutral secret-store failures."""


class InvalidSecretReferenceError(SecretStoreError):
    """Raised without echoing an invalid, potentially sensitive reference."""

    def __init__(self) -> None:
        super().__init__("The credential reference is invalid.")


class SecretNotConfiguredError(SecretStoreError):
    """Raised when a valid reference has no non-empty environment value."""

    def __init__(self, variable_name: str) -> None:
        super().__init__("The referenced environment credential is not configured.")
        self.variable_name = variable_name


class SecretResolutionError(SecretStoreError):
    """Raised when a configured value is unsafe to pass to a provider."""

    def __init__(self) -> None:
        super().__init__("The referenced environment credential is invalid.")


@dataclass(frozen=True, slots=True, init=False)
class SecretRef:
    """Validated reference to one explicitly named environment variable."""

    name: str

    def __init__(self, reference: str) -> None:
        if (
            type(reference) is not str
            or len(reference) > _MAX_REFERENCE_LENGTH
            or not reference.startswith(_ENV_REFERENCE_PREFIX)
            or re.fullmatch(_ENV_NAME_PATTERN, reference[len(_ENV_REFERENCE_PREFIX) :]) is None
        ):
            raise InvalidSecretReferenceError from None
        object.__setattr__(self, "name", reference[len(_ENV_REFERENCE_PREFIX) :])

    @classmethod
    def parse(cls, reference: str) -> Self:
        return cls(reference)

    @property
    def scheme(self) -> str:
        return "env"

    @property
    def reference(self) -> str:
        return f"{_ENV_REFERENCE_PREFIX}{self.name}"

    def __str__(self) -> str:
        return self.reference


class SecretValue:
    """Opaque resolved value with an explicit provider-only reveal method."""

    __slots__ = ("__value",)

    def __init__(self, value: str) -> None:
        if type(value) is not str:
            raise SecretResolutionError
        try:
            encoded = value.encode("utf-8")
        except UnicodeEncodeError:
            raise SecretResolutionError from None
        if (
            len(encoded) < _MIN_SECRET_BYTES
            or len(encoded) > _MAX_SECRET_BYTES
            or any(byte < 0x21 or byte > 0x7E for byte in encoded)
        ):
            raise SecretResolutionError
        self.__value = value

    def reveal_for_provider(self) -> str:
        """Return the value only at the trusted provider-construction boundary."""

        return self.__value

    def __str__(self) -> str:
        return "<redacted-secret>"

    def __repr__(self) -> str:
        return "SecretValue(<redacted>)"

    def __format__(self, format_spec: str) -> str:
        del format_spec
        return str(self)

    def __getstate__(self) -> object:
        raise TypeError("SecretValue cannot be serialized")

    def to_json(self) -> str:
        """Reject explicit JSON serialization instead of returning the value."""

        raise TypeError("SecretValue cannot be serialized")


class SecretStatus(StrEnum):
    CONFIGURED = "configured"
    MISSING = "missing"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class SecretInspection:
    status: SecretStatus


class SecretStore(Protocol):
    """Control-plane resolver; resolution registers redaction before returning."""

    def inspect(self, reference: SecretRef | str) -> SecretInspection: ...

    def is_configured(self, reference: SecretRef | str) -> bool: ...

    def resolve(self, reference: SecretRef | str) -> SecretValue: ...
