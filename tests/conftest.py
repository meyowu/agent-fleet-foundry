from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from agent_fleet.adapters.repository.git import GitRepositoryAdapter
from agent_fleet.adapters.system import UuidIdGenerator
from agent_fleet.bootstrap import ApplicationContainer, build_container
from agent_fleet.domain.models import FakeScenario, Run


@dataclass
class FleetHarness:
    root: Path
    state_root: Path
    repository_root: Path
    container: ApplicationContainer

    async def start(self, scenario: FakeScenario = FakeScenario.SUCCESS) -> Run:
        return await self.container.workflow.start(
            project_path=self.repository_root,
            goal="Fix the canary behavior",
            runtime_name="fake",
            sandbox_name="fake",
            fake_scenario=scenario,
        )

    def git(self, *argv: str) -> str:
        result = subprocess.run(
            ["git", *argv],
            cwd=self.repository_root,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout


@pytest.fixture
def harness(tmp_path: Path) -> FleetHarness:
    repository_root = GitRepositoryAdapter(tmp_path, UuidIdGenerator()).create_canary_fixture(
        tmp_path / "target-repository"
    )
    state_root = tmp_path / "fleet-state"
    container = build_container(state_root)
    container.projects.initialize(
        repository_root,
        runtime_name="fake",
        sandbox_name="fake",
    )
    return FleetHarness(tmp_path, state_root, repository_root, container)
