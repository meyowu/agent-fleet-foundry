"""Real SDK and Fleet persistence/Gateway, with explicitly simulated sandbox evidence."""

from __future__ import annotations

import json
import socket
from collections.abc import Iterator
from pathlib import Path

import httpx2
import pytest
from conftest import FleetHarness
from google_provider_fixtures import install_transport, response_body
from pydantic_ai.models import override_allow_model_requests

from agent_fleet.adapters.repository.git import GitRepositoryAdapter
from agent_fleet.adapters.system import UuidIdGenerator
from agent_fleet.bootstrap import ApplicationContainer, build_container
from agent_fleet.domain.models import ApprovalChoice, ArtifactKind, RunStatus
from agent_fleet.domain.offline_canary import FIXED_CANARY
from agent_fleet.domain.trust import TrustMode

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture(autouse=True)
def allow_offline_requests(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    def denied(*args: object, **kwargs: object) -> None:
        raise AssertionError("Google workflow contracts cannot open sockets")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    with override_allow_model_requests(True):
        yield


_KEY = "offline-google-workflow-credential"
_MODEL = "gemini-2.5-flash-lite"


def _events_are_secret_free(container: ApplicationContainer, run_id: str) -> None:
    events = container.state.list_events(run_id)
    assert _KEY not in str([item.model_dump(mode="json") for item in events])
    for artifact in container.state.list_artifacts(run_id):
        assert _KEY not in container.artifacts.read_text(artifact.artifact_id)


@pytest.mark.parametrize("permission", ["allow", "approve-once", "deny"])
async def test_google_workflow_respects_broker_decisions_and_retains_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    permission: str,
) -> None:
    monkeypatch.setenv("FLEET_GOOGLE_WORKFLOW", _KEY)
    repository = GitRepositoryAdapter(tmp_path, UuidIdGenerator()).create_canary_fixture(
        tmp_path / "target"
    )
    state_root = tmp_path / "state"
    container = build_container(state_root)
    assert "pydantic-ai" in container.runtimes.names
    container.projects._initialize_without_canary(
        repository,
        runtime_name="pydantic-ai",
        provider_model=f"google:{_MODEL}",
        credential_ref="env:FLEET_GOOGLE_WORKFLOW",
        sandbox_name="fake",
    )
    if permission != "allow":
        container.permissions.configure(repository, mode=TrustMode.SAFE, allowed_paths=(".",))
    harness = FleetHarness(tmp_path, state_root, repository, container)
    baseline = harness.git("rev-parse", "HEAD"), harness.git("status", "--porcelain")
    requests: dict[str, int] = {}

    def respond(received: httpx2.Request) -> httpx2.Response:
        body = json.loads(received.content)
        assert (
            str(received.url)
            == f"https://generativelanguage.googleapis.com/v1beta/models/{_MODEL}:generateContent"
        )
        assert received.headers["x-goog-api-key"] == _KEY
        assert _KEY not in received.content.decode()
        terminal = next(
            d["name"]
            for t in body["tools"]
            for d in t["functionDeclarations"]
            if d["name"].startswith("submit_")
        )
        number = requests.get(terminal, 0) + 1
        requests[terminal] = number
        calls: list[tuple[str, dict[str, object]]]
        command: tuple[str, dict[str, object]] = (
            "run_verification",
            {"command_id": "python-test", "reason": "Bounded independent command."},
        )
        if terminal == "submit_scope_decision":
            calls = [
                (
                    terminal,
                    {
                        "normalized_goal": "Fix the canary behavior.",
                        "workflow": "code-change",
                        "change_kind": "code_change",
                        "fleet_strategy": "engineer_verifier",
                        "allowed_paths": ["src/canary_calc/core.py"],
                        "forbidden_paths": [".git", ".fleet"],
                        "acceptance_criteria": [
                            {
                                "criterion_id": "canary-zero-division",
                                "description": "divide(1, 0) raises the stable ValueError",
                            }
                        ],
                        "required_evidence": [
                            "canonical_patch",
                            "command_evidence",
                            "independent_verifier_verdict",
                        ],
                    },
                )
            ]
        elif terminal == "submit_implementation_report" and number == 1:
            calls = [
                (
                    "workspace_write_file",
                    {
                        "path": "src/canary_calc/core.py",
                        "content": FIXED_CANARY,
                        "reason": "Apply the bounded repair.",
                    },
                ),
                command,
            ]
        elif terminal == "submit_implementation_report" and permission != "allow" and number == 2:
            # This is a fresh Fleet invocation after explicit approval, not a restored SDK state.
            calls = [command]
        elif terminal == "submit_implementation_report":
            calls = [
                (
                    terminal,
                    {
                        "summary": "Applied only the canary repair.",
                        "intended_changed_paths": ["src/canary_calc/core.py"],
                        "tests_added_or_changed": [],
                        "criterion_results": ["canary-zero-division: candidate updated"],
                        "evidence_artifact_ids": [],
                        "unresolved_limitations": ["FakeSandbox did not execute project code."],
                        "verifier_focus": ["Inspect the exception behavior independently."],
                    },
                )
            ]
        elif terminal == "submit_verifier_verdict" and number == 1:
            calls = [command]
        else:
            assert terminal == "submit_verifier_verdict"
            calls = [
                (
                    terminal,
                    {
                        "verdict": "pass",
                        "criterion_results": ["canary-zero-division: proposed fix"],
                        "evidence_artifact_ids": [],
                        "regressions": [],
                        "required_repairs": [],
                        "proof_gaps": ["FakeSandbox did not execute project code."],
                        "rationale": "Reviewable candidate; execution remains unverified.",
                    },
                )
            ]
        return httpx2.Response(
            200,
            request=received,
            json=response_body(
                [{"functionCall": {"name": name, "args": arguments}} for name, arguments in calls]
            ),
        )

    sync_clients, clients = install_transport(monkeypatch, respond)
    with override_allow_model_requests(True):
        run = await container.workflow.start(
            project_path=repository,
            goal="Fix the canary behavior",
            runtime_name="pydantic-ai",
            provider_model=f"google:{_MODEL}",
            credential_ref="env:FLEET_GOOGLE_WORKFLOW",
            sandbox_name="fake",
            fake_scenario=None,
        )
    if permission != "allow":
        assert run.status is RunStatus.PAUSED_FOR_APPROVAL and run.pending_approval_id is not None
        assert requests == {"submit_scope_decision": 1, "submit_implementation_report": 1}
        approval = container.state.get_approval(run.pending_approval_id)
        assert approval.action == "command.run" and approval.resource.identifier == "python-test"
        assert container.state.count_executed_intents(run.run_id, "workspace.write_file") == 1
        assert container.state.count_executed_intents(run.run_id, "command.run") == 0
        assert all(client.is_closed for client in [*sync_clients, *clients])
        reopened = build_container(state_root)
        if permission == "deny":
            reopened.approvals.deny(approval.request_id)
            denied = await reopened.workflow.resume(run.run_id)
            retained = reopened.state.get_run(run.run_id)
            assert denied == retained and retained.status is RunStatus.REJECTED
            assert reopened.state.count_executed_intents(run.run_id, "command.run") == 0
            _events_are_secret_free(reopened, run.run_id)
            assert (
                harness.git("rev-parse", "HEAD"),
                harness.git("status", "--porcelain"),
            ) == baseline
            return
        reopened.approvals.approve(approval.request_id, choice=ApprovalChoice.ALLOW_ONCE)
        run = await reopened.workflow.resume(run.run_id)
        # The independent Verifier has its own principal and requires its own exact approval.
        if run.status is RunStatus.PAUSED_FOR_APPROVAL:
            assert run.pending_approval_id is not None
            verifier_approval = reopened.state.get_approval(run.pending_approval_id)
            assert verifier_approval.principal_role == "verifier"
            assert approval.principal_role == "engineer"
            reopened.approvals.approve(
                verifier_approval.request_id, choice=ApprovalChoice.ALLOW_ONCE
            )
            # A fresh verifier invocation must request the admitted command again.
            requests["submit_verifier_verdict"] = 0
            run = await reopened.workflow.resume(run.run_id)
        container = reopened
    assert run.status is RunStatus.READY_FOR_REVIEW and not run.verified_complete
    assert run.runtime_name == "pydantic-ai" and run.provider_model == f"google:{_MODEL}"
    snapshot = container.budgets.snapshot(run.run_id)
    assert snapshot.model_requests == sum(requests.values()) + (
        1 if permission == "approve-once" else 0
    )
    assert snapshot.reported_total_tokens == snapshot.model_requests * 15
    assert snapshot.unknown_requests == snapshot.outstanding_requests == 0
    assert snapshot.reported_costs == {}
    assert container.state.count_executed_intents(run.run_id, "workspace.write_file") == 1
    assert container.state.count_executed_intents(run.run_id, "command.run") == 2
    evidence = container.inspection.status(run.run_id)["evidence"]
    assert isinstance(evidence, dict) and evidence["changed_paths"] == ["src/canary_calc/core.py"]
    assert "SIMULATED_EVIDENCE_ONLY" in evidence["completion_reason_codes"]
    usages = [
        item
        for item in container.state.list_artifacts(run.run_id)
        if item.kind is ArtifactKind.RUNTIME_USAGE
    ]
    assert len(usages) == 3
    for item in usages:
        data = json.loads(container.artifacts.read_text(item.artifact_id))
        assert data["provider_metadata"]["provider"] == "google"
        assert data["provider_metadata"]["model"] == f"google:{_MODEL}"
    assert container.state.outstanding_leases(run.run_id) == []
    assert all(client.is_closed for client in [*sync_clients, *clients])
    _events_are_secret_free(container, run.run_id)
    assert (harness.git("rev-parse", "HEAD"), harness.git("status", "--porcelain")) == baseline
