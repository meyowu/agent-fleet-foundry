"""Public chat/review CLI and generation fences around existing execution paths."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, cast

import pytest
from conftest import FleetHarness
from evolution_fixtures import deliver_proposal
from typer.testing import CliRunner

from agent_fleet.adapters.runtime.fake import FakeRuntimeAdapter
from agent_fleet.application.conversations import ChatExecutionOptions
from agent_fleet.application.runtime import RuntimeRegistry
from agent_fleet.bootstrap import build_container
from agent_fleet.cli.app import app
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import (
    AgentInvocation,
    AgentInvocationResult,
    AgentRole,
    ArtifactKind,
    FleetPatch,
    FleetPatchFileChange,
    FleetPatchOperation,
    RunStatus,
)
from agent_fleet.domain.security import sha256_bytes
from agent_fleet.ports.runtime import RuntimeInvocationServices

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def cli(
    arguments: list[str], state: Path, *, extra_env: dict[str, str] | None = None
) -> tuple[int, dict[str, Any], str]:
    result = CliRunner().invoke(
        app,
        ["fleet-patch", *arguments, "--json"],
        env={
            "AGENT_FLEET_HOME": str(state),
            **(extra_env or {}),
        },
    )
    return result.exit_code, json.loads(result.stdout), result.stdout


async def test_chat_proposal_delivers_refs_and_public_cli_applies_and_rolls_back(
    tmp_path: Path,
) -> None:
    container, repository, run, model, before = await deliver_proposal(tmp_path, conversation=True)
    binding = container.conversation_store.binding_for_run(run.run_id)
    assert binding is not None
    turn = container.conversation_store.get_turn(binding.project_id, binding.turn_id)
    assert turn.active_claim_id is None and turn.result_summary is not None
    assert "proposed and not applied" in turn.result_summary.text
    assert {ArtifactKind.FLEET_PATCH, ArtifactKind.FLEET_PATCH_DIFF} <= {
        item.kind for item in turn.artifact_refs
    }
    rebuilt = build_container(container.state_root)
    selected = rebuilt.conversations.select(repository)
    assert selected["run_id"] == run.run_id
    duplicate = await rebuilt.conversations.submit(
        binding.conversation_id,
        message="For backend changes, always run integration tests.",
        submission_id="organization-proposal",
        options=ChatExecutionOptions(),
    )
    assert duplicate["run_id"] == run.run_id
    code, listing, _ = await asyncio.to_thread(
        cli, ["list", "--path", str(repository)], container.state_root
    )
    assert code == 0 and listing["ok"] is True
    proposal_id = listing["data"][0]["proposal_id"]
    assert proposal_id == model.context["proposal_id"]
    for command in ("show", "diff"):
        code, result, _ = await asyncio.to_thread(cli, [command, proposal_id], container.state_root)
        assert code == 0 and result["ok"] is True
        assert "backend-integration" in json.dumps(result["data"])
    assert not (repository / ".fleet/skills").exists()
    code, result, _ = await asyncio.to_thread(cli, ["apply", proposal_id], container.state_root)
    assert code == 0 and result["data"]["status"] == "committed"
    assert result["data"]["cleanup_complete"] is True
    operation_id = result["data"]["operation_id"]
    code, operation, _ = await asyncio.to_thread(
        cli, ["operation", operation_id], container.state_root
    )
    assert code == 0 and operation["data"]["status"] == "committed"
    code, rejected, _ = await asyncio.to_thread(
        cli, ["recover", operation_id], container.state_root
    )
    assert code == 4 and rejected["error"]["code"] == "APPROVAL_REQUIRED"
    code, inverse, _ = await asyncio.to_thread(cli, ["rollback", proposal_id], container.state_root)
    assert code == 0 and inverse["data"]["status"] == "committed"
    assert inverse["data"]["version"]["version"] == 2
    assert inverse["data"]["version"]["tree_sha256"] == before
    assert inverse["data"]["proposal_id"] != proposal_id
    assert not (repository / ".fleet/skills").exists()
    historical = await rebuilt.conversations.submit(
        binding.conversation_id,
        message="For backend changes, always run integration tests.",
        submission_id="organization-proposal",
        options=ChatExecutionOptions(),
    )
    assert historical["run_id"] == run.run_id
    assert rebuilt.conversation_store.get_turn(binding.project_id, binding.turn_id) == turn


async def test_cli_rereads_proposal_with_fresh_explicit_secret_registry(tmp_path: Path) -> None:
    container, repository, run, _, _ = await deliver_proposal(tmp_path)
    proposal = container.organization.list_proposals(repository)[0]
    secret = proposal.patch.rationale
    code, envelope, rendered = await asyncio.to_thread(
        cli,
        ["show", proposal.patch.fleet_patch_id],
        container.state_root,
        extra_env={"FLEET_OFFLINE_TEST_KEY": secret},
    )
    assert code != 0 and envelope["ok"] is False and secret not in rendered
    head = container.organization.store.get_head(run.project_id)
    assert head is not None and head.revision == 0 and head.pending_operation_id is None


class ReadmeProposalRuntime(FakeRuntimeAdapter):
    async def invoke(
        self, request: AgentInvocation, services: RuntimeInvocationServices
    ) -> AgentInvocationResult:
        if request.role != AgentRole.COS:
            return await super().invoke(request, services)
        context = cast(dict[str, Any], request.input["organization_context"])
        readme = next(item for item in context["files"] if item["path"] == ".fleet/README.md")
        content = readme["content"] + "\nReviewed organization note.\n"
        return AgentInvocationResult(
            output=FleetPatch(
                fleet_patch_id=context["proposal_id"],
                project_id=context["project_id"],
                base_fleet_spec_sha256=context["base_fleet_spec_sha256"],
                rationale="Propose a durable documentation-only organization change.",
                changes=[
                    FleetPatchFileChange(
                        operation=FleetPatchOperation.REPLACE,
                        path=".fleet/README.md",
                        before_sha256=readme["sha256"],
                        after_sha256=sha256_bytes(content.encode()),
                        content=content,
                    )
                ],
            )
        )


async def test_ready_code_patch_rejects_same_config_hash_and_rollback_aba(
    harness: FleetHarness,
) -> None:
    ready = await harness.start()
    assert ready.status is RunStatus.READY_FOR_REVIEW
    before_source = (harness.repository_root / "src/canary_calc/core.py").read_bytes()
    admitted = harness.container.organization.store.admission_for_run(ready.run_id)
    assert admitted is not None
    harness.container.workflow.runtimes = RuntimeRegistry({"fake": ReadmeProposalRuntime()})
    proposal_run = await harness.start()
    proposal = harness.container.organization.list_proposals(harness.repository_root)[0]
    assert proposal_run.status is RunStatus.COMPLETED
    assert proposal.before_config_snapshot_sha256 == proposal.after_config_snapshot_sha256
    applied = harness.container.organization.apply(proposal.patch.fleet_patch_id)
    assert applied.version is not None and applied.version.version == 1
    for after_rollback in (False, True):
        if after_rollback:
            harness.container.organization.rollback(proposal.patch.fleet_patch_id)
        with pytest.raises(FleetError) as stale_patch:
            harness.container.patches.apply(ready.run_id)
        assert stale_patch.value.code is ErrorCode.PATCH_TARGET_DIVERGED
        assert stale_patch.value.__cause__ is None and stale_patch.value.__context__ is None
        with pytest.raises(FleetError):
            project = harness.container.state.get_project(ready.project_id)
            with harness.container.organization.admission(project, expected=admitted):
                pytest.fail("stale preflight was admitted")
        assert harness.container.state.get_run(ready.run_id) == ready
        assert (harness.repository_root / "src/canary_calc/core.py").read_bytes() == before_source


async def test_headed_initialization_rejects_before_staging_or_project_rebinding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    container, repository, run, _, before = await deliver_proposal(tmp_path)
    project = container.state.get_project(run.project_id)
    artifacts = container.state.list_artifacts(run.run_id)

    def no_stage(*args: Any, **kwargs: Any) -> None:
        pytest.fail("headed initialization reached staging")

    monkeypatch.setattr(container.projects.config, "stage", no_stage)
    with pytest.raises(FleetError) as caught:
        container.projects._initialize_without_canary(
            repository,
            runtime_name="pydantic-ai",
            provider_model="openai:offline-test",
            credential_ref="env:FLEET_OFFLINE_TEST_KEY",
            sandbox_name="fake",
        )
    assert caught.value.code is ErrorCode.CONFIG_INVALID
    assert container.state.get_project(run.project_id) == project
    assert container.state.list_artifacts(run.run_id) == artifacts
    head = container.organization.store.get_head(run.project_id)
    assert head is not None and head.tree_sha256 == before and head.revision == 0
