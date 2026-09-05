"""Real CLI processes preserve proposals, versions, and abrupt-exit recovery."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import pytest
from evolution_fixtures import ProposalModel
from pydantic_ai.models.function import FunctionModel

from agent_fleet.adapters.repository.git import GitRepositoryAdapter
from agent_fleet.adapters.runtime.pydantic_ai import PydanticAIRuntimeAdapter
from agent_fleet.adapters.system import UuidIdGenerator
from agent_fleet.application.runtime import RuntimeRegistry
from agent_fleet.bootstrap import ApplicationContainer, build_container
from agent_fleet.domain.models import RunStatus

pytestmark = pytest.mark.e2e

# Only the provider model is substituted. The actual CLI, chat, pure tool,
# workflow, publisher, native filesystem and durable stores remain in use.
_OFFLINE_ENTRY = """
import importlib
import socket
import sys
sys.path.insert(0, sys.argv.pop(1))
from evolution_fixtures import ProposalModel
from pydantic_ai.models import override_allow_model_requests
from pydantic_ai.models.function import FunctionModel
from agent_fleet.adapters.runtime.fake import FakeRuntimeAdapter
from agent_fleet.adapters.runtime.pydantic_ai import PydanticAIRuntimeAdapter
from agent_fleet.application.runtime import RuntimeRegistry
cli = importlib.import_module('agent_fleet.cli.app')
original = cli.build_container
def offline_container(*args, **kwargs):
    container = original(*args, **kwargs)
    model = ProposalModel()
    adapter = PydanticAIRuntimeAdapter.for_test_model(
        FunctionModel(model.__call__), redactor=container.redactor)
    container.workflow.runtimes = RuntimeRegistry(
        {'fake': FakeRuntimeAdapter(), 'pydantic-ai': adapter})
    return container
def no_network(*args, **kwargs):
    raise AssertionError('offline CLI fixture attempted network access')
socket.create_connection = no_network
socket.getaddrinfo = no_network
cli.build_container = offline_container
with override_allow_model_requests(False):
    cli.main()
"""

_CRASH_ENTRY = """
import os
import sys
from agent_fleet.adapters.persistence.evolution import SqliteOrganizationStore
from agent_fleet.application.evolution import OrganizationService
from agent_fleet.cli.app import main
cut = sys.argv.pop(1)
if cut == 'prepared':
    original = SqliteOrganizationStore.prepare_operation
    def crash(*args, **kwargs):
        original(*args, **kwargs)
        os._exit(73)
    SqliteOrganizationStore.prepare_operation = crash
else:
    def crash(*args, **kwargs):
        os._exit(73)
    OrganizationService._commit = crash
main()
"""

_GOAL = "For backend changes, always run integration tests."


@dataclass
class EvolutionCli:
    repository: Path
    state_root: Path
    environment: dict[str, str]

    def execute(
        self, *args: str, entry: list[str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, *(entry or ["-m", "agent_fleet.cli.app"]), *args, "--json"],
            env=self.environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )

    def invoke(self, *args: str, entry: list[str] | None = None, code: int = 0) -> dict[str, Any]:
        result = self.execute(*args, entry=entry)
        assert result.returncode == code, result.stdout + result.stderr
        assert "Traceback" not in result.stdout + result.stderr
        envelope = json.loads(result.stdout)
        assert envelope["ok"] is (code == 0)
        return cast(dict[str, Any], envelope)

    def propose(self) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            self.invoke(
                "chat",
                str(self.repository),
                "--message",
                _GOAL,
                "--submission-id",
                "backend-rule",
                entry=["-c", _OFFLINE_ENTRY, str(Path(__file__).parents[1])],
            )["data"],
        )

    def reopen(self) -> ApplicationContainer:
        return build_container(self.state_root)


@pytest.fixture
def evolution_cli(tmp_path: Path) -> EvolutionCli:
    repository = GitRepositoryAdapter(tmp_path, UuidIdGenerator()).create_canary_fixture(
        tmp_path / "repository"
    )
    state_root = tmp_path / "state"
    # Fake sandbox setup is explicit fixture seeding, not an isolated-bootstrap claim.
    container = build_container(state_root)
    model = ProposalModel()
    adapter = PydanticAIRuntimeAdapter.for_test_model(
        FunctionModel(model.__call__), redactor=container.redactor
    )
    container.projects.runtime_registry = RuntimeRegistry({"pydantic-ai": adapter})
    container.projects._initialize_without_canary(
        repository,
        runtime_name="pydantic-ai",
        provider_model="openai:offline-test",
        credential_ref="env:FLEET_OFFLINE_TEST_KEY",
        sandbox_name="fake",
    )
    environment = {
        key: value
        for key, value in os.environ.items()
        if key in {"PATH", "TMPDIR", "TMP", "TEMP", "LANG", "LC_ALL", "SYSTEMROOT"}
    }
    environment.update(AGENT_FLEET_HOME=str(state_root), NO_COLOR="1", COLUMNS="240")
    return EvolutionCli(repository, state_root, environment)


def test_chat_proposal_and_version_lifecycle_survive_fresh_cli_processes(
    evolution_cli: EvolutionCli,
) -> None:
    cli = evolution_cli
    view = cli.propose()
    container = cli.reopen()
    run = container.state.get_run(view["run_id"])
    assert run.status is RunStatus.COMPLETED
    proposal = container.organization.list_proposals(cli.repository)[0]
    proposal_id = proposal.patch.fleet_patch_id
    baseline = container.repository.inspect_organization_boundary(cli.repository)
    grants = container.state.list_project_grants(run.project_id)
    assert not (cli.repository / ".fleet/skills").exists()
    assert (
        cli.invoke("fleet-patch", "list", "--path", str(cli.repository))["data"][0]["proposal_id"]
        == proposal_id
    )
    shown = cli.invoke("fleet-patch", "show", proposal_id)["data"]
    diff = cli.invoke("fleet-patch", "diff", proposal_id)["data"]
    assert shown["proposal_sha256"] == diff["proposal_sha256"] == proposal.proposal_sha256
    assert diff["text_diff"] == proposal.text_diff and "backend-integration" in diff["text_diff"]
    applied = cli.invoke("fleet-patch", "apply", proposal_id)["data"]
    assert applied["version"]["version"] == 1 and applied["cleanup_complete"] is True
    assert (
        cli.invoke("fleet-patch", "operation", applied["operation_id"])["data"]["status"]
        == "committed"
    )
    repeated = cli.invoke("fleet-patch", "apply", proposal_id)
    assert repeated["data"]["changed"] is False and repeated["data"]["cleanup_complete"] is None
    assert repeated["data"]["version"] == applied["version"] and repeated["warnings"]
    inverse = cli.invoke("fleet-patch", "rollback", proposal_id)["data"]
    assert inverse["version"]["version"] == 2
    assert inverse["version"]["tree_sha256"] == proposal.before_tree_sha256
    assert inverse["proposal_id"] != proposal_id and inverse["cleanup_complete"] is True
    assert not (cli.repository / ".fleet/skills").exists()
    historical = cli.invoke(
        "chat",
        str(cli.repository),
        "--message",
        _GOAL,
        "--conversation",
        view["conversation_id"],
        "--submission-id",
        "backend-rule",
    )["data"]
    assert historical["run_id"] == view["run_id"] and historical["turn_id"] == view["turn_id"]
    rebuilt = cli.reopen()
    assert rebuilt.state.get_run(run.run_id) == run
    assert rebuilt.state.list_project_grants(run.project_id) == grants
    assert baseline.unchanged_outside_organization(
        rebuilt.repository.inspect_organization_boundary(cli.repository)
    )
    assert not rebuilt.state.outstanding_leases()
    head = rebuilt.organization.store.get_head(run.project_id)
    assert head is not None and head.revision == 2 and head.pending_operation_id is None


@pytest.mark.parametrize("cut", ["prepared", "exchanged"])
def test_abrupt_publisher_process_exit_requires_exact_confirmed_cli_recovery(
    evolution_cli: EvolutionCli,
    cut: str,
) -> None:
    cli = evolution_cli
    cli.propose()
    before = cli.reopen()
    proposal = before.organization.list_proposals(cli.repository)[0]
    proposal_id = proposal.patch.fleet_patch_id
    result = cli.execute("fleet-patch", "apply", proposal_id, entry=["-c", _CRASH_ENTRY, cut])
    assert result.returncode == 73 and not result.stdout and not result.stderr
    operation = cli.reopen().organization.store.operation_for_proposal(proposal_id)
    assert operation is not None and operation.status == "prepared"
    pending = cli.reopen().organization.store.get_head(proposal.patch.project_id)
    assert pending is not None and pending.pending_operation_id == operation.operation_id
    assert (
        cli.invoke("fleet-patch", "recover", operation.operation_id, code=4)["error"]["code"]
        == "APPROVAL_REQUIRED"
    )
    inspected = cli.invoke("fleet-patch", "operation", operation.operation_id)["data"]
    assert inspected["status"] == "prepared"
    recovered = cli.invoke("fleet-patch", "recover", operation.operation_id, "--owner-stopped")[
        "data"
    ]
    assert recovered["status"] == ("aborted" if cut == "prepared" else "committed")
    assert recovered["cleanup_complete"] is True
    repeated = cli.invoke("fleet-patch", "recover", operation.operation_id, "--owner-stopped")[
        "data"
    ]
    assert repeated["changed"] is False and repeated["cleanup_complete"] is True
    final = cli.reopen().organization.store.get_head(proposal.patch.project_id)
    assert final is not None and final.pending_operation_id is None
    assert final.revision == (0 if cut == "prepared" else 1)
    assert final.tree_sha256 == (
        proposal.before_tree_sha256 if cut == "prepared" else proposal.after_tree_sha256
    )
    assert not (cli.repository.parent / operation.publication.scratch_basename).exists()
