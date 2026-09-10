"""Real baseline store fencing with synthetic cleanup facts, never physical Docker."""

import asyncio
import sqlite3
from pathlib import Path

import pytest
from business_baseline_fixtures import BaselineFixture, baseline_fixture

from agent_fleet.adapters.repository.git import GitRepositoryAdapter
from agent_fleet.adapters.sandbox.docker import DockerSandboxProvider
from agent_fleet.adapters.sandbox.process import ProcessResult
from agent_fleet.application.resources import ResourceService
from agent_fleet.application.sandboxes import SandboxRegistry
from agent_fleet.domain.baseline import baseline_id
from agent_fleet.domain.baseline_resources import (
    BaselineCleanupClaim,
    BaselineExecutionHandle,
    BaselineSandboxHandle,
    BaselineWorkspace,
)
from agent_fleet.domain.errors import FleetError
from agent_fleet.domain.models import SandboxCleanupResult
from agent_fleet.domain.security import Redactor
from agent_fleet.ports.baseline_resources import BaselineResourceDependencies


class NoProcessRunner:
    async def run(
        self,
        argv: tuple[str, ...],
        *,
        environment: dict[str, str],
        cwd: str | None = None,
        timeout_seconds: int,
        max_output_bytes: int,
    ) -> ProcessResult:
        raise AssertionError("cleanup unit contract must not execute any process")


def cleanup_fixture(
    tmp_path: Path,
) -> tuple[BaselineFixture, ResourceService, DockerSandboxProvider, BaselineCleanupClaim]:
    h = baseline_fixture(tmp_path)
    claim = h.claim()
    h.dispatched_observation(claim)
    plan = h.store.begin_baseline_cleanup(
        claim, h.store.baseline_resource_snapshot(h.review.baseline_id)
    )
    repository = GitRepositoryAdapter(tmp_path, h.state.ids)
    provider = DockerSandboxProvider(
        runner=NoProcessRunner(),
        clock=h.state.clock,
        ids=h.state.ids,
        redactor=Redactor(),
        installation_id=h.review.installation_id,
        docker_executable="/usr/bin/docker",
        git_shadow_path=tmp_path / "shadow",
        uid=1000,
        gid=1000,
    )
    registry = SandboxRegistry({"docker": provider}, baseline_providers={"docker": provider})
    service = ResourceService(
        h.state,
        repository,
        registry,
        h.state.clock,
        h.state.ids,
        baseline=BaselineResourceDependencies(store=h.store, repository=repository),
    )
    return h, service, provider, plan


@pytest.mark.parametrize("mode", ["complete", "partial", "before_effect", "after_effect"])
async def test_cleanup_tiers_and_full_payload_fence_are_not_dynamic_resource_sweeps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    h, service, provider, plan = cleanup_fixture(tmp_path)
    calls: list[str] = []

    def corrupt() -> None:
        with sqlite3.connect(h.state.database_path) as connection:
            connection.execute(
                "UPDATE baseline_resource_leases SET revision=revision+1 WHERE record_id=?",
                (next(item.lease_id for item in plan.snapshot.leases if item.kind == "sandbox"),),
            )

    def result(identity: str, *, complete: bool = True) -> SandboxCleanupResult:
        return SandboxCleanupResult(
            provider="docker",
            resource_id=identity,
            resources_found=0,
            resources_removed=0,
            reconciled=complete,
            complete=complete,
            completed_at=h.state.clock.now(),
        )

    async def execution(handle: BaselineExecutionHandle) -> SandboxCleanupResult:
        calls.append("execution")
        if mode == "after_effect":
            corrupt()
        return result(handle.native_resource_id, complete=mode != "partial")

    async def sandbox(handle: BaselineSandboxHandle) -> SandboxCleanupResult:
        calls.append("sandbox")
        return result(handle.sandbox_id)

    def workspace(root: Path, resource: BaselineWorkspace) -> None:
        assert str(root) == h.review.repository_root and resource.owner == plan.owner
        calls.append("workspace")

    monkeypatch.setattr(provider, "cleanup_baseline_execution", execution)
    monkeypatch.setattr(provider, "terminate_baseline", sandbox)
    monkeypatch.setattr(service.repository, "cleanup_baseline_workspace", workspace)
    if mode == "before_effect":
        corrupt()
    if mode == "complete":
        await service.cleanup_baseline(plan)
        assert calls == ["execution", "sandbox", "workspace"]
        assert all(item.status == "released" for item in h.store.validate_cleanup(plan).leases)
        await service.cleanup_baseline(plan)
        assert calls == ["execution", "sandbox", "workspace"]
    else:
        with pytest.raises(FleetError):
            await service.cleanup_baseline(plan)
        assert calls == ([] if mode == "before_effect" else ["execution"])
        if mode == "partial":
            state = h.store.validate_cleanup(plan)
            assert (
                next(item for item in state.leases if item.kind == "execution").status == "failed"
            )
            assert all(item.status == "active" for item in state.leases if item.kind != "execution")
        else:
            with pytest.raises(FleetError):
                h.store.validate_cleanup(plan)
        with sqlite3.connect(h.state.database_path) as connection:
            assert connection.execute("SELECT COUNT(*) FROM baseline_cleanup_receipts").fetchone()[
                0
            ] == (1 if mode == "partial" else 0)


async def test_repeated_cleanup_cancel_drains_same_exact_plan_and_rejects_conflicting_join(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h, service, provider, plan = cleanup_fixture(tmp_path)
    entered, release = asyncio.Event(), asyncio.Event()
    calls: list[str] = []

    def result(identity: str) -> SandboxCleanupResult:
        return SandboxCleanupResult(
            provider="docker",
            resource_id=identity,
            resources_found=0,
            resources_removed=0,
            reconciled=True,
            complete=True,
            completed_at=h.state.clock.now(),
        )

    async def execution(handle: BaselineExecutionHandle) -> SandboxCleanupResult:
        calls.append("execution")
        entered.set()
        await release.wait()
        return result(handle.native_resource_id)

    async def sandbox(handle: BaselineSandboxHandle) -> SandboxCleanupResult:
        calls.append("sandbox")
        return result(handle.sandbox_id)

    monkeypatch.setattr(provider, "cleanup_baseline_execution", execution)
    monkeypatch.setattr(provider, "terminate_baseline", sandbox)
    monkeypatch.setattr(
        service.repository, "cleanup_baseline_workspace", lambda *_: calls.append("workspace")
    )
    task = asyncio.create_task(service.cleanup_baseline(plan))
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        with pytest.raises(FleetError):
            await service.cleanup_baseline(
                plan.model_copy(update={"claim_id": baseline_id("bclaim")})
            )
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert calls == ["execution", "sandbox", "workspace"]
        assert all(item.status == "released" for item in h.store.validate_cleanup(plan).leases)
        await service.cleanup_baseline(plan)
        assert calls == ["execution", "sandbox", "workspace"]
    finally:
        release.set()
        if not task.done():
            await task
