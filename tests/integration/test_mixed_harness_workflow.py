"""Actual mixed SDK/Harness workflows; synthetic HTTP and sandbox are not live proof."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx2
import pytest
from conftest import FleetHarness
from pydantic_ai.models import override_allow_model_requests

import agent_fleet.adapters.runtime.openai_client as transport_module
import agent_fleet.adapters.runtime.pydantic_ai as pydantic_module
from agent_fleet.adapters.repository.git import GitRepositoryAdapter
from agent_fleet.adapters.system import UuidIdGenerator
from agent_fleet.bootstrap import build_container
from agent_fleet.domain.models import ApprovalChoice, RunStatus, RuntimeConfiguration
from agent_fleet.domain.offline_canary import FIXED_CANARY
from agent_fleet.domain.trust import TrustMode

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]
_ROLES = ("cos", "engineer", "verifier")
_TERMINALS = {
    "cos": "submit_scope_decision",
    "engineer": "submit_implementation_report",
    "verifier": "submit_verifier_verdict",
}
_OUTPUTS: dict[str, dict[str, object]] = {
    "cos": {
        "normalized_goal": "Repair the bounded canary behavior.",
        "workflow": "code-change",
        "change_kind": "code_change",
        "fleet_strategy": "engineer_verifier",
        "allowed_paths": ["src/canary_calc/core.py"],
        "forbidden_paths": [".git", ".fleet"],
        "acceptance_criteria": [
            {
                "criterion_id": "zero-division",
                "description": "Reject a zero divisor with ValueError",
            }
        ],
        "required_evidence": [
            "canonical_patch",
            "command_evidence",
            "independent_verifier_verdict",
        ],
    },
    "engineer": {
        "summary": "Applied the single-file canary guard.",
        "intended_changed_paths": ["src/canary_calc/core.py"],
        "tests_added_or_changed": [],
        "criterion_results": ["zero-division: candidate updated"],
        "evidence_artifact_ids": [],
        "unresolved_limitations": ["FakeSandbox does not execute project code."],
        "verifier_focus": ["Inspect the exception independently."],
    },
    "verifier": {
        "verdict": "pass",
        "criterion_results": ["zero-division: proposed repair"],
        "evidence_artifact_ids": [],
        "regressions": [],
        "required_repairs": [],
        "proof_gaps": ["FakeSandbox does not execute project code."],
        "rationale": "Reviewable candidate, not verified execution.",
    },
}


@pytest.mark.parametrize(
    "runtimes",
    [
        ("pydantic-ai", "openai-agents", "langgraph"),
        ("openai-agents", "langgraph", "pydantic-ai"),
        ("langgraph", "pydantic-ai", "openai-agents"),
    ],
    ids=["pydantic-cos", "sdk-cos", "graph-cos"],
)
@pytest.mark.parametrize("permission", ["allow", "approve-once", "deny"])
async def test_mixed_harnesses_keep_exact_role_bindings_across_real_workflow_and_reopen(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    runtimes: tuple[str, str, str],
    permission: str,
) -> None:
    for name in ("OPENAI_LOG", "OPENAI_CUSTOM_HEADERS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "offline-ambient-must-not-be-selected")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://untrusted.invalid/v1")
    keys = {role: f"offline-mixed-{role}-only-credential" for role in _ROLES}
    for role, key in keys.items():
        monkeypatch.setenv(f"FLEET_MIXED_{role.upper()}", key)
    repository = GitRepositoryAdapter(tmp_path, UuidIdGenerator()).create_canary_fixture(
        tmp_path / "target"
    )
    state_root = tmp_path / "state"
    container = build_container(state_root)
    container.projects._initialize_without_canary(repository)
    harness = FleetHarness(tmp_path, state_root, repository, container)
    baseline = harness.git("rev-parse", "HEAD"), harness.git("status", "--porcelain")
    service = container.model_profiles
    project = service.project(repository)
    selected = dict(zip(_ROLES, runtimes, strict=True))
    for role, runtime in selected.items():
        service.set(
            role,
            configuration=RuntimeConfiguration(
                runtime_name=runtime,
                provider_model=f"openai:gpt-mixed-{role}",
                credential_ref=f"env:FLEET_MIXED_{role.upper()}",
                max_requests=8,
                max_retries=0,
            ),
        )
    service.bind(project, default=True, profile="cos", expected_revision=0)
    service.bind(project, role="engineer", profile="engineer", expected_revision=1)
    service.bind(project, role="verifier", profile="verifier", expected_revision=2)
    if permission != "allow":
        container.permissions.configure(repository, mode=TrustMode.SAFE, allowed_paths=(".",))
    clients: list[httpx2.AsyncClient] = []
    requests = dict.fromkeys(_ROLES, 0)
    sends: list[tuple[str, str, str]] = []

    def respond(received: httpx2.Request) -> httpx2.Response:
        body = json.loads(received.content)
        role = str(body["model"]).removeprefix("gpt-mixed-")
        assert role in selected
        assert str(received.url) == "https://api.openai.com/v1/responses"
        assert received.headers["authorization"] == f"Bearer {keys[role]}"
        assert _TERMINALS[role] in {tool["name"] for tool in body["tools"]}
        serialized = received.content.decode()
        assert all(key not in serialized for key in keys.values())
        assert "offline-ambient-must-not-be-selected" not in serialized
        assert "env:FLEET_MIXED_" not in serialized
        sends.append((role, body["model"], received.headers["authorization"]))
        requests[role] += 1
        number = requests[role]
        command: tuple[str, dict[str, object]] = (
            "run_verification",
            {"command_id": "python-test", "reason": "Check the bounded candidate."},
        )
        calls: list[tuple[str, dict[str, object]]]
        if role == "engineer" and number == 1:
            calls = [
                (
                    "workspace_write_file",
                    {
                        "path": "src/canary_calc/core.py",
                        "content": FIXED_CANARY,
                        "reason": "Add only the canary guard.",
                    },
                ),
                command,
            ]
        elif (role == "verifier" and number == 1) or (
            role in {"engineer", "verifier"} and permission == "approve-once" and number == 2
        ):
            calls = [command]
        else:
            calls = [(_TERMINALS[role], _OUTPUTS[role])]
        return httpx2.Response(
            200,
            request=received,
            json={
                "id": f"response-{role}-{number}",
                "object": "response",
                "created_at": 0,
                "status": "completed",
                "model": body["model"],
                "output": [
                    {
                        "type": "function_call",
                        "id": f"item-{role}-{number}-{index}",
                        "call_id": f"call-{role}-{number}-{index}",
                        "name": name,
                        "arguments": json.dumps(arguments),
                        "status": "completed",
                    }
                    for index, (name, arguments) in enumerate(calls)
                ],
                "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            },
        )

    def transport(**kwargs: Any) -> httpx2.AsyncClient:
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        client = httpx2.AsyncClient(transport=httpx2.MockTransport(respond), **kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(transport_module, "DefaultAsyncHttpxClient", transport)
    monkeypatch.setattr(pydantic_module, "DefaultAsyncHttpxClient", transport)
    with override_allow_model_requests(True):
        run = await container.workflow.start(
            project_path=repository,
            goal="Repair only the canary guard",
            runtime_name=None,
            sandbox_name=None,
            fake_scenario=None,
        )
        bindings_digest = run.model_bindings_sha256
        assert bindings_digest is not None
        if permission != "allow":
            assert run.status is RunStatus.PAUSED_FOR_APPROVAL
            assert run.pending_approval_id is not None
            assert requests == {"cos": 1, "engineer": 1, "verifier": 0}
            assert container.state.count_executed_intents(run.run_id, "command.run") == 0
            assert all(client.is_closed for client in clients)
            # A later profile revision must not rebind either resumed principal.
            for role in ("engineer", "verifier"):
                service.set(role, configuration=RuntimeConfiguration(), expected_revision=1)
            container = build_container(state_root)
            approval = container.state.get_approval(run.pending_approval_id)
            assert approval.principal_role == "engineer"
            assert approval.resource.identifier == "python-test"
            if permission == "deny":
                container.approvals.deny(approval.request_id)
                run = await container.workflow.resume(run.run_id)
                assert run.status is RunStatus.REJECTED
            else:
                container.approvals.approve(approval.request_id, choice=ApprovalChoice.ALLOW_ONCE)
                run = await container.workflow.resume(run.run_id)
                assert run.status is RunStatus.PAUSED_FOR_APPROVAL
                assert run.pending_approval_id is not None
                independent = container.state.get_approval(run.pending_approval_id)
                assert independent.principal_role == "verifier"
                assert independent.resource.identifier == "python-test"
                assert independent.request_id != approval.request_id
                assert all(client.is_closed for client in clients)
                container = build_container(state_root)
                container.approvals.approve(
                    independent.request_id, choice=ApprovalChoice.ALLOW_ONCE
                )
                run = await container.workflow.resume(run.run_id)
    assert run.model_bindings_sha256 == bindings_digest
    assert not run.verified_complete
    assert container.state.count_executed_intents(run.run_id, "workspace.write_file") == 1
    assert container.state.count_executed_intents(run.run_id, "command.run") == (
        0 if permission == "deny" else 2
    )
    if permission != "deny":
        assert run.status is RunStatus.READY_FOR_REVIEW
        evidence = container.inspection.status(run.run_id)["evidence"]
        assert isinstance(evidence, dict)
        assert evidence["changed_paths"] == ["src/canary_calc/core.py"]
        assert "SIMULATED_EVIDENCE_ONLY" in evidence["completion_reason_codes"]
        usage_artifacts = [
            json.loads(container.artifacts.read_text(item))
            for item in run.runtime_usage_artifact_ids
        ]
        assert len(usage_artifacts) == 3
        assert [item["selected_model"]["runtime_name"] for item in usage_artifacts] == list(
            runtimes
        )
        assert [item["selected_model"]["provider_model"] for item in usage_artifacts] == [
            f"openai:gpt-mixed-{role}" for role in _ROLES
        ]
        assert all(item["model_bindings_sha256"] == bindings_digest for item in usage_artifacts)
        assert "credential_ref" not in json.dumps(usage_artifacts)
    snapshot = container.budgets.snapshot(run.run_id)
    assert snapshot.model_requests == len(sends) == sum(requests.values())
    assert snapshot.reported_total_tokens == snapshot.model_requests * 15
    assert snapshot.unknown_requests == snapshot.outstanding_requests == 0
    assert snapshot.reported_costs == {}
    assert container.state.outstanding_leases(run.run_id) == []
    assert all(client.is_closed for client in clients)
    assert (harness.git("rev-parse", "HEAD"), harness.git("status", "--porcelain")) == baseline
    durable = json.dumps(
        [item.model_dump(mode="json") for item in container.state.list_events(run.run_id)]
    )
    for artifact in container.state.list_artifacts(run.run_id):
        durable += container.artifacts.read_text(artifact.artifact_id)
    assert all(key not in durable for key in keys.values())
    assert "offline-ambient-must-not-be-selected" not in durable
