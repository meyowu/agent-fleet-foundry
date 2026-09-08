"""Explicit offline-only fixture for reproducible local observer/browser checks.

This is test support, not public initialization: fake execution cannot satisfy
the real Bootstrap canary. All paths are newly created under the supplied root.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from pydantic_ai.models import override_allow_model_requests

from agent_fleet.adapters.dashboard.http import DashboardServer
from agent_fleet.adapters.repository.git import GitRepositoryAdapter
from agent_fleet.adapters.system import UuidIdGenerator
from agent_fleet.bootstrap import build_container
from agent_fleet.cli.dashboard import dashboard_service
from agent_fleet.domain.models import FakeScenario


async def prepare(root: Path, *, empty: bool = False) -> None:
    repository = GitRepositoryAdapter(root, UuidIdGenerator()).create_canary_fixture(
        root / "project"
    )
    container = build_container(root / "state")
    container.projects._initialize_without_canary(
        repository, runtime_name="fake", sandbox_name="fake"
    )
    if empty:
        return
    await container.workflow.start(
        project_path=repository,
        goal="Fix the canary behavior <script>window.compromised=true</script>",
        runtime_name="fake",
        sandbox_name="fake",
        fake_scenario=FakeScenario.PARALLEL_ENGINEERS,
    )
    await container.workflow.start(
        project_path=repository,
        goal="Review the next bounded change before execution",
        runtime_name="fake",
        sandbox_name="fake",
        fake_scenario=FakeScenario.SUCCESS,
        review_plan=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--empty", action="store_true")
    args = parser.parse_args()
    with override_allow_model_requests(False):
        asyncio.run(prepare(args.root, empty=args.empty))
    container = build_container(args.root / "state", migrate=False)
    service = dashboard_service(container)
    with DashboardServer(service, service.open_project(args.root / "project")) as server:
        print(
            json.dumps({"origin": server.origin, "token": server.token, "fixture": str(args.root)}),
            flush=True,
        )
        try:
            server.serve_forever(poll_interval=0.2)
        except KeyboardInterrupt:
            return


if __name__ == "__main__":
    main()
