"""Offline CoS proposals cross the real structured-output and pure-tool boundaries."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest
from evolution_fixtures import deliver_proposal

from agent_fleet.bootstrap import build_container
from agent_fleet.domain.errors import FleetError
from agent_fleet.domain.ids import IdPrefix
from agent_fleet.domain.models import AgentRole, ArtifactKind, FleetPatch, RunStatus

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_offline_proposal_hashes_persists_and_delivers_without_application(
    tmp_path: Path,
) -> None:
    container, repository, run, model, before = await deliver_proposal(tmp_path)
    assert run.status is RunStatus.COMPLETED
    assert run.task_id is not None
    task = container.state.get_task(run.task_id)
    assert task.change_kind == "read_only" and task.allowed_paths == []
    assert task.required_verification_command_ids == []
    assert len(model.hash_results) == 3
    assert container.sandbox.requests == []
    assert container.state.list_leases(run.run_id) == []
    assert run.patch_artifact_id is None and run.applied_revision is None
    proposals = container.organization.store.list_proposals(run.project_id)
    assert len(proposals) == 1
    proposal = proposals[0]
    assert proposal.patch.fleet_patch_id == model.context["proposal_id"]
    assert proposal.before_tree_sha256 == before
    assert {item.category for item in proposal.semantic_changes} == {
        "workflow",
        "verification",
        "verification_skill",
    }
    assert "backend-integration" in proposal.text_diff
    artifacts = container.state.list_artifacts(run.run_id)
    structured = [item for item in artifacts if item.kind is ArtifactKind.FLEET_PATCH]
    diffs = [item for item in artifacts if item.kind is ArtifactKind.FLEET_PATCH_DIFF]
    assert len(structured) == len(diffs) == 1
    assert (
        FleetPatch.model_validate_json(container.artifacts.read_text(structured[0].artifact_id))
        == proposal.patch
    )
    assert container.artifacts.read_text(diffs[0].artifact_id) == proposal.text_diff
    budget = container.budgets.snapshot(run.run_id)
    assert (budget.agent_invocations, budget.model_requests, budget.tool_calls) == (1, 2, 3)
    agents = [
        event.payload.get("role")
        for event in container.state.list_events(run.run_id)
        if event.event_type == "agent.started"
    ]
    assert agents == [AgentRole.COS.value]
    reopened = build_container(container.state_root)
    assert reopened.organization.store.get_proposal(proposal.patch.fleet_patch_id) == proposal
    head = reopened.organization.store.get_head(run.project_id)
    assert head is not None and head.revision == 0 and head.tree_sha256 == before
    project = reopened.state.get_project(run.project_id)
    with reopened.organization.files.session(
        project, reopened.organization.ids.new(IdPrefix.ORGANIZATION_OPERATION)
    ) as session:
        assert session.capture_target().sha256 == before
    assert not (repository / ".fleet/skills").exists()
    assert reopened.organization.store.operation_for_proposal(proposal.patch.fleet_patch_id) is None


@pytest.mark.parametrize("invalid", ["wrong-id", "protected", "hash", "reference"])
async def test_invalid_proposal_never_persists_authority_or_changes_target(
    tmp_path: Path, invalid: str
) -> None:
    container, _, run, _, before = await deliver_proposal(tmp_path, invalid)
    assert run.status is RunStatus.FAILED
    assert container.organization.store.list_proposals(run.project_id) == ()
    assert container.sandbox.requests == []
    assert container.state.list_leases(run.run_id) == []
    head = container.organization.store.get_head(run.project_id)
    assert head is not None and head.revision == 0 and head.pending_operation_id is None
    project = container.state.get_project(run.project_id)
    with container.organization.files.session(
        project, container.organization.ids.new(IdPrefix.ORGANIZATION_OPERATION)
    ) as session:
        assert session.capture_target().sha256 == before


@pytest.mark.parametrize("tracked", [False, True])
async def test_real_directory_apply_and_exact_inverse_survive_reopen(
    tmp_path: Path, tracked: bool
) -> None:
    container, repository, run, _, before = await deliver_proposal(tmp_path, retain_extras=True)
    proposal = container.organization.store.list_proposals(run.project_id)[0]
    if tracked:
        for argv in (("add", ".fleet"), ("commit", "-m", "Track reviewed organization")):
            await asyncio.to_thread(
                subprocess.run, ["git", *argv], cwd=repository, check=True, capture_output=True
            )
    original_boundary = container.repository.inspect_organization_boundary(repository)
    grants = container.state.list_project_grants(run.project_id)
    applied = container.organization.apply(proposal.patch.fleet_patch_id)
    assert applied.changed and applied.status == "committed" and applied.cleanup_complete is True
    assert applied.version is not None and applied.version.version == 1
    assert (repository / ".fleet/retained-notes.md").read_text() == (
        "Local notes: preserve exact UTF-8 bytes. 保留。\n"
    )
    assert (repository / ".fleet/retained-empty").is_dir()
    assert container.repository.inspect_organization_boundary(
        repository
    ).unchanged_outside_organization(original_boundary)
    assert not (repository.parent / (".fleet-publication-" + applied.operation_id)).exists()
    reopened = build_container(container.state_root)
    head = reopened.organization.store.get_head(run.project_id)
    assert head is not None and head.revision == 1 and head.pending_operation_id is None
    assert head.tree_sha256 == proposal.after_tree_sha256
    project = reopened.state.get_project(run.project_id)
    spec, snapshot = reopened.organization.config.load_snapshot(repository / ".fleet/fleet.yaml")
    assert project.fleet_spec_hash == proposal.after_config_snapshot_sha256
    assert (
        project.init_status_fingerprint
        == reopened.repository.inspect(repository).status_fingerprint
    )
    assert "backend-integration" in reopened.organization.config.required_verification_commands(
        spec,
        snapshot,
        workflow_id="code-change",
        allowed_paths=("src/canary_calc/core.py",),
        change_kind="code_change",
    )
    repeated = reopened.organization.apply(proposal.patch.fleet_patch_id)
    assert not repeated.changed and repeated.version == applied.version
    assert repeated.cleanup_complete is None
    rolled_back = reopened.organization.rollback(proposal.patch.fleet_patch_id)
    assert rolled_back.changed and rolled_back.cleanup_complete is True
    assert rolled_back.version is not None and rolled_back.version.version == 2
    inverse = reopened.organization.get_proposal(rolled_back.proposal_id)
    assert inverse.patch.rollback_of == proposal.patch.fleet_patch_id
    assert inverse.after_tree_sha256 == before
    current = reopened.state.get_project(run.project_id)
    with reopened.organization.files.session(
        current, reopened.organization.ids.new(IdPrefix.ORGANIZATION_OPERATION)
    ) as session:
        assert session.capture_target().sha256 == before
    assert not (repository / ".fleet/skills").exists()
    assert reopened.state.list_project_grants(run.project_id) == grants
    assert not (repository.parent / (".fleet-publication-" + rolled_back.operation_id)).exists()
    assert reopened.repository.inspect_organization_boundary(
        repository
    ).unchanged_outside_organization(original_boundary)
    historical_repeat = reopened.organization.apply(proposal.patch.fleet_patch_id)
    assert historical_repeat.version == applied.version and not historical_repeat.changed
    with pytest.raises(FleetError):
        reopened.organization.rollback(proposal.patch.fleet_patch_id)
