"""Project-owned port for bounded static repository profiling."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from agent_fleet.domain.repository_profile import RepositoryProfileResult


class RepositoryProfilerPort(Protocol):
    def profile(self, root: Path) -> RepositoryProfileResult: ...


RepositoryProfilePort = RepositoryProfilerPort
