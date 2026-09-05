from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from conftest import FleetHarness

from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.ids import IdPrefix
from agent_fleet.domain.models import LeaseStatus, Run, Workspace, WorkspaceKind

pytestmark = pytest.mark.integration


def _run(harness: FleetHarness) -> Run:
    state = harness.container.state
    info = harness.container.repository.inspect(harness.repository_root)
    project = state.get_project_by_root(info.root)
    assert project is not None
    now = state.clock.now()
    run = Run(
        run_id=state.ids.new(IdPrefix.RUN),
        project_id=project.project_id,
        correlation_id=state.ids.new(IdPrefix.CORRELATION),
        goal="Verify exact worktree preparation and cleanup",
        base_revision=info.head_revision,
        target_status_fingerprint=info.status_fingerprint,
        created_at=now,
        updated_at=now,
    )
    state.create_run(run)
    return run


def test_workspace_identity_is_durable_before_git_effect(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = _run(harness)
    container = harness.container
    repository = container.repository
    resources = container.recovery.resources
    original = repository.materialize_workspace

    def inspect_preparation(root: Path, workspace: Workspace) -> Workspace:
        leases = container.state.outstanding_leases(run.run_id)
        assert len(leases) == 1
        assert leases[0].status is LeaseStatus.CREATING
        assert leases[0].resource_id == workspace.workspace_id
        assert leases[0].path == workspace.path
        assert not Path(workspace.path).exists()
        return original(root, workspace)

    monkeypatch.setattr(repository, "materialize_workspace", inspect_preparation)
    workspace, lease = resources.create_workspace(run, WorkspaceKind.CANDIDATE)
    assert lease.status is LeaseStatus.ACTIVE
    assert Path(workspace.path).is_dir()
    asyncio.run(container.cancellation.cancel(run.run_id))
    assert not Path(workspace.path).exists()
    assert not container.state.outstanding_leases(run.run_id)


def test_failure_after_git_creation_keeps_exact_recoverable_lease(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = _run(harness)
    container = harness.container
    repository = container.repository
    original = repository.materialize_workspace

    def fail_after_creation(root: Path, workspace: Workspace) -> Workspace:
        original(root, workspace)
        raise FleetError(
            ErrorCode.RECOVERY_REQUIRED,
            "Injected interruption after Git creation.",
            "Recover its exact persisted lease.",
        )

    monkeypatch.setattr(repository, "materialize_workspace", fail_after_creation)
    with pytest.raises(FleetError):
        container.recovery.resources.create_workspace(run, WorkspaceKind.CANDIDATE)
    leases = container.state.outstanding_leases(run.run_id)
    assert len(leases) == 1 and leases[0].status is LeaseStatus.FAILED
    assert leases[0].path is not None and Path(leases[0].path).exists()
    asyncio.run(container.cancellation.cancel(run.run_id))
    assert not Path(leases[0].path).exists()
    assert not container.state.outstanding_leases(run.run_id)


def test_missing_worktree_directory_does_not_hide_its_registration(
    harness: FleetHarness,
) -> None:
    run = _run(harness)
    container = harness.container
    workspace, _ = container.recovery.resources.create_workspace(run, WorkspaceKind.CANDIDATE)
    original = Path(workspace.path)
    retained = original.with_name(f"retained-{workspace.workspace_id}")
    original.rename(retained)
    assert container.repository._workspace_is_registered(harness.repository_root, original)
    asyncio.run(container.cancellation.cancel(run.run_id))
    assert not container.repository._workspace_is_registered(harness.repository_root, original)
    assert retained.is_dir(), "Exact recovery must not sweep a separately retained directory."
    assert not container.state.outstanding_leases(run.run_id)


def test_preallocation_is_read_only_and_rejects_substituted_path(harness: FleetHarness) -> None:
    run = _run(harness)
    repository = harness.container.repository
    before = harness.git("worktree", "list", "--porcelain")
    workspace = repository.prepare_workspace(run.run_id, run.base_revision, WorkspaceKind.CANDIDATE)
    assert not Path(workspace.path).exists()
    assert harness.git("worktree", "list", "--porcelain") == before
    with pytest.raises(FleetError) as captured:
        repository.materialize_workspace(
            harness.repository_root,
            workspace.model_copy(update={"path": str(harness.repository_root)}),
        )
    assert captured.value.code is ErrorCode.PATH_OUTSIDE_SCOPE
    assert harness.git("worktree", "list", "--porcelain") == before
