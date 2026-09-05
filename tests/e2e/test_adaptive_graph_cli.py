"""Separate offline CLI processes exercise durable adaptive graph inspection."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import pytest

from agent_fleet.adapters.repository.git import GitRepositoryAdapter
from agent_fleet.adapters.system import UuidIdGenerator
from agent_fleet.bootstrap import ApplicationContainer, build_container
from agent_fleet.domain.models import ArtifactKind, RunStatus

pytestmark = pytest.mark.e2e


@dataclass
class CliGraph:
    repository: Path
    state_root: Path
    executable: Path
    environment: dict[str, str]
    baseline_status: str
    baseline_revision: str

    def invoke(self, *arguments: str, json_output: bool = True, success: bool = True) -> Any:
        """Every call starts the installed CLI in a fresh, credential-free process."""
        result = subprocess.run(
            [str(self.executable), *arguments, *(["--json"] if json_output else [])],
            check=False,
            capture_output=True,
            text=True,
            env=self.environment,
            timeout=60,
        )
        assert result.returncode == (0 if success else 1), result.stdout + result.stderr
        assert "Traceback" not in result.stdout + result.stderr
        if not json_output:
            return result.stdout + result.stderr
        envelope = json.loads(result.stdout)
        assert isinstance(envelope, dict) and envelope["ok"] is success
        return envelope["data"] if success else envelope["error"]

    def start(self, scenario: str = "parallel_engineers") -> dict[str, Any]:
        return cast(
            dict[str, Any],
            self.invoke(
                "run",
                "Produce bounded adaptive fixture changes.",
                "--project",
                str(self.repository),
                "--runtime",
                "fake",
                "--sandbox",
                "fake",
                "--fake-scenario",
                scenario,
            ),
        )

    def reopen(self) -> ApplicationContainer:
        return build_container(self.state_root)

    def git(self, *arguments: str) -> str:
        return subprocess.run(
            ["git", *arguments],
            cwd=self.repository,
            check=True,
            capture_output=True,
            text=True,
            env=self.environment,
        ).stdout

    def unchanged(self) -> None:
        assert self.git("status", "--porcelain") == self.baseline_status
        assert self.git("rev-parse", "HEAD") == self.baseline_revision

    def safe(self) -> None:
        configured = self.invoke(
            "permissions",
            "configure",
            "--project",
            str(self.repository),
            "--mode",
            "safe",
            "--allow-path",
            ".",
        )
        assert configured["trust_mode"] == "safe"


@pytest.fixture
def cli_graph(tmp_path: Path) -> CliGraph:
    repository = GitRepositoryAdapter(tmp_path, UuidIdGenerator()).create_canary_fixture(
        tmp_path / "target-repository"
    )
    state_root = tmp_path / "fleet-state"
    # Fake cannot pass isolated bootstrap; seed the same explicit legacy fixture
    # as the existing offline CLI tests, without claiming bootstrap verification.
    build_container(state_root).projects._initialize_without_canary(
        repository, runtime_name="fake", sandbox_name="fake"
    )
    executable = Path(sys.executable).parent / "fleet"
    assert executable.is_file()
    environment = {
        key: value
        for key, value in os.environ.items()
        if key in {"PATH", "SYSTEMROOT", "TMPDIR", "TEMP", "TMP", "LANG", "LC_ALL"}
    }
    environment.update(AGENT_FLEET_HOME=str(state_root), COLUMNS="240", NO_COLOR="1")
    fixture = CliGraph(repository, state_root, executable, environment, "", "")
    fixture.baseline_status = fixture.git("status", "--porcelain")
    fixture.baseline_revision = fixture.git("rev-parse", "HEAD")
    return fixture


def _child_ids(data: dict[str, Any]) -> list[str]:
    return [str(node["binding"]["child_run_id"]) for node in data["graph"]["nodes"]]


@pytest.mark.parametrize(
    "scenario,roles",
    [
        ("parallel_engineers", ["engineer", "engineer"]),
        ("specialist", ["architect", "engineer", "researcher"]),
    ],
)
def test_completed_graph_status_artifacts_and_child_denials_survive_cli_reconstruction(
    cli_graph: CliGraph,
    scenario: str,
    roles: list[str],
) -> None:
    data = cli_graph.start(scenario)
    parent_id = str(data["run_id"])
    assert data["status"] == "ready_for_review" and data["verified_complete"] is False
    status = cli_graph.invoke("status", parent_id)
    assert status["graph"]["status"] == "joined"
    assert status["graph"]["driver_claim"] is None
    assert sorted(node["node"]["role_id"] for node in status["graph"]["nodes"]) == roles
    assert all(node["status"] == "succeeded" for node in status["graph"]["nodes"])
    assert status["pending_approval_id"] is None and status["pending_child_approval_ids"] == []
    assert status["patch_sha256"] == data["patch_sha256"]
    human = cli_graph.invoke("status", parent_id, json_output=False)
    assert parent_id in human and "ready_for_review" in human and "joined" in human
    assert "verified_complete" in human and "False" in human
    artifacts = cli_graph.invoke("artifacts", parent_id)
    kinds = {item["kind"] for item in artifacts}
    assert {"fleet_plan", "graph_join", "patch", "evidence_bundle", "run_summary"} <= kinds
    patch_metadata = next(
        item for item in artifacts if item["artifact_id"] == data["patch_artifact_id"]
    )
    assert patch_metadata["sha256"] == data["patch_sha256"]
    patch = cli_graph.invoke("patch", "show", parent_id)
    assert "src/canary_calc/core.py" in patch["patch"]
    assert (
        cli_graph.invoke("patch", "show", parent_id, json_output=False).strip()
        == patch["patch"].strip()
    )
    logs = cli_graph.invoke("logs", parent_id)
    assert sum(event["event_type"] == "graph.join_completed" for event in logs) == 1
    assert cli_graph.invoke("resume", parent_id)["patch_sha256"] == data["patch_sha256"]

    for child_id in _child_ids(data):
        child_status = cli_graph.invoke("status", child_id)
        assert child_status["parent_run_id"] == parent_id
        assert child_status["status"] == "completed" and not child_status["verified_complete"]
        assert child_status["graph"] is None
        child_artifacts = cli_graph.invoke("artifacts", child_id)
        assert "resource_cleanup" in {item["kind"] for item in child_artifacts}
        assert all(item["run_id"] == child_id for item in child_artifacts)
    child_id = _child_ids(data)[0]
    for arguments in (
        ("resume", child_id),
        ("cancel", child_id),
        ("recover", child_id, "--confirm-owner-stopped"),
        ("patch", "apply", child_id),
    ):
        error = cli_graph.invoke(*arguments, success=False)
        assert error["code"] in {"COMMAND_DENIED", "RECOVERY_REQUIRED"}
        assert error["details"]["parent_run_id"] == parent_id
        assert "parent" in error["remediation"].lower()
        human_error = cli_graph.invoke(*arguments, json_output=False, success=False)
        assert parent_id in human_error
    cli_graph.unchanged()


def test_waiting_graph_shows_exact_requests_and_cli_approval_resumes_only_its_child(
    cli_graph: CliGraph,
) -> None:
    cli_graph.safe()
    paused = cli_graph.start()
    parent_id = str(paused["run_id"])
    assert paused["status"] == "waiting_for_children"
    assert paused["stage"] == "implementing" and paused["pending_approval_id"] is None
    request_ids = paused["pending_child_approval_ids"]
    assert len(request_ids) == len(set(request_ids)) == 2
    container = cli_graph.reopen()
    children = [container.state.get_run(child_id) for child_id in _child_ids(paused)]
    assert set(request_ids) == {child.pending_approval_id for child in children}
    human = cli_graph.invoke("status", parent_id, json_output=False)
    assert "waiting_for_children" in human and all(
        request_id in human for request_id in request_ids
    )
    untouched = cli_graph.invoke("resume", parent_id)
    assert untouched["status"] == "waiting_for_children"
    assert set(untouched["pending_child_approval_ids"]) == set(request_ids)
    assert all(
        container.state.count_executed_intents(child.run_id, "command.run") == 0
        for child in children
    )

    first_request = container.state.get_approval(request_ids[0])
    approved = cli_graph.invoke("approve", request_ids[0], "--once")
    assert approved["run_id"] == first_request.run_id
    pending = cli_graph.invoke("status", parent_id)
    assert request_ids[0] not in pending["pending_child_approval_ids"]
    assert request_ids[1] in pending["pending_child_approval_ids"]
    resumed = cli_graph.invoke("resume", parent_id)
    rebuilt = cli_graph.reopen()
    assert rebuilt.state.count_executed_intents(first_request.run_id, "command.run") == 1
    other = next(child for child in children if child.run_id != first_request.run_id)
    assert rebuilt.state.count_executed_intents(other.run_id, "command.run") == 0
    assert rebuilt.state.get_run(other.run_id).engineer_checkpoint == other.engineer_checkpoint
    assert rebuilt.state.get_run(other.run_id).pending_approval_id == other.pending_approval_id

    approved_ids = {str(request_ids[0])}
    for _ in range(12):
        if resumed["status"] == "ready_for_review":
            break
        pending_ids = resumed["pending_child_approval_ids"] or [resumed["pending_approval_id"]]
        assert pending_ids and pending_ids[0] is not None
        request_id = str(pending_ids[0])
        assert request_id not in approved_ids
        cli_graph.invoke("approve", request_id, "--once")
        approved_ids.add(request_id)
        resumed = cli_graph.invoke("resume", parent_id)
    assert resumed["status"] == "ready_for_review" and not resumed["verified_complete"]
    assert resumed["pending_child_approval_ids"] == [] and resumed["pending_approval_id"] is None
    final = cli_graph.reopen()
    all_run_ids = [parent_id, *_child_ids(resumed)]
    for run_id in all_run_ids:
        assert not final.state.outstanding_leases(run_id)
        logs = cli_graph.invoke("logs", run_id)
        consumed = [
            event["payload"]["grant_id"]
            for event in logs
            if event["event_type"] == "capability.consumed"
        ]
        assert consumed and len(consumed) == len(set(consumed))
        command_artifacts = [
            item
            for item in final.state.list_artifacts(run_id)
            if item.kind is ArtifactKind.COMMAND_EVIDENCE
        ]
        command_ids = [
            json.loads(final.artifacts.read_text(item.artifact_id))["command_id"]
            for item in command_artifacts
        ]
        assert command_ids and len(command_ids) == len(set(command_ids))
    cli_graph.unchanged()


def test_parent_cancel_command_cleans_exact_waiting_children_without_replay(
    cli_graph: CliGraph,
) -> None:
    cli_graph.safe()
    paused = cli_graph.start()
    parent_id = str(paused["run_id"])
    child_ids = _child_ids(paused)
    assert all(cli_graph.reopen().state.outstanding_leases(child_id) for child_id in child_ids)
    cancelled = cli_graph.invoke("cancel", parent_id)
    assert cancelled["status"] == "cancelled"
    assert cancelled["graph"]["status"] == "cancelled"
    assert cancelled["pending_child_approval_ids"] == []
    assert cli_graph.invoke("cancel", parent_id)["status"] == "cancelled"
    assert cli_graph.invoke("resume", parent_id)["status"] == "cancelled"
    container = cli_graph.reopen()
    for child_id in child_ids:
        assert container.state.get_run(child_id).status is RunStatus.CANCELLED
        assert not container.state.outstanding_leases(child_id)
        assert container.state.count_executed_intents(child_id, "command.run") == 0
    logs = cli_graph.invoke("logs", parent_id)
    assert sum(event["event_type"] == "graph.cancel_requested" for event in logs) == 1
    cli_graph.unchanged()


def test_recover_command_reports_descendant_only_cleanup_and_preserves_other_graph(
    cli_graph: CliGraph,
) -> None:
    cli_graph.safe()
    paused = cli_graph.start()
    unrelated = cli_graph.start()
    parent_id = str(paused["run_id"])
    child_ids = _child_ids(paused)
    container = cli_graph.reopen()
    graph = container.graphs.get(parent_id)
    assert graph is not None
    # Crash boundary: a durable owner claim was written, then its process stopped
    # before dispatch. No synthetic completion, tool execution, or grant is added.
    container.graphs.claim_driver(parent_id, expected_revision=graph.revision)
    before = {
        lease.lease_id
        for child_id in child_ids
        for lease in container.state.outstanding_leases(child_id)
    }
    assert before and not container.state.outstanding_leases(parent_id)
    unrelated_before = [
        container.state.outstanding_leases(child_id) for child_id in _child_ids(unrelated)
    ]
    refused = cli_graph.invoke("recover", parent_id, success=False)
    assert refused["code"] == "RECOVERY_REQUIRED"
    assert "--confirm-owner-stopped" in refused["remediation"]
    assert {
        lease.lease_id
        for child_id in child_ids
        for lease in container.state.outstanding_leases(child_id)
    } == before
    recovered = cli_graph.invoke("recover", parent_id, "--confirm-owner-stopped")
    assert recovered["status"] == "failed" and recovered["recovered"] is True
    assert set(recovered["child_run_ids"]) == set(child_ids)
    assert set(recovered["recovered_lease_ids"]) == before
    assert recovered["outstanding_lease_ids"] == []
    reconstructed = cli_graph.reopen()
    for child_id in child_ids:
        assert not reconstructed.state.outstanding_leases(child_id)
        assert reconstructed.state.count_executed_intents(child_id, "command.run") == 0
    assert [
        reconstructed.state.outstanding_leases(child_id) for child_id in _child_ids(unrelated)
    ] == unrelated_before
    assert (
        reconstructed.state.get_run(str(unrelated["run_id"])).status
        is RunStatus.WAITING_FOR_CHILDREN
    )
    repeated = cli_graph.invoke("recover", parent_id, "--confirm-owner-stopped")
    assert repeated["recovered"] is False and repeated["recovered_lease_ids"] == []
    assert cli_graph.invoke("status", parent_id)["graph"]["status"] == "cancelled"
    cli_graph.invoke("cancel", str(unrelated["run_id"]))
    cli_graph.unchanged()
