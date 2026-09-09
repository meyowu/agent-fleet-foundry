"""Atomic user-owned trust policy persistence boundary."""

from contextlib import AbstractContextManager
from typing import Protocol

from agent_fleet.domain.trust import UserTrustPolicy


class TrustReadGuard(Protocol):
    @property
    def canonical_policy_utf8(self) -> bytes: ...

    @property
    def policy_sha256(self) -> str: ...

    def assert_current(self) -> None: ...


class TrustStore(Protocol):
    def load(self) -> UserTrustPolicy: ...

    def save(self, policy: UserTrustPolicy, *, expected_revision: int) -> UserTrustPolicy: ...

    def read_guard(
        self, *, expected_sha256: str | None = None
    ) -> AbstractContextManager[TrustReadGuard]: ...
