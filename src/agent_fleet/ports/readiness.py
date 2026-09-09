"""Implemented read-only profiler seam; no execution or evidence-store authority."""

from pathlib import Path
from typing import Protocol

from agent_fleet.domain.readiness import StaticReadinessMetadata
from agent_fleet.domain.repository_profile import RepositoryProfileResult


class ReadinessProfilerPort(Protocol):
    def profile_with_metadata(
        self, root: Path
    ) -> tuple[RepositoryProfileResult, StaticReadinessMetadata]: ...
