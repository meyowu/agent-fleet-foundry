"""Atomic user-owned trust policy persistence boundary."""

from typing import Protocol

from agent_fleet.domain.trust import UserTrustPolicy


class TrustStore(Protocol):
    def load(self) -> UserTrustPolicy: ...

    def save(self, policy: UserTrustPolicy, *, expected_revision: int) -> UserTrustPolicy: ...
