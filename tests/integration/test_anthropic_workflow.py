"""Actual SDK + production control plane, with offline HTTP and FakeSandbox receipts."""

import json
from pathlib import Path
from typing import Any

import httpx2
import pytest
from conftest import FleetHarness
from pydantic_ai.models import override_allow_model_requests

import agent_fleet.adapters.runtime.anthropic_provider as provider_module
from agent_fleet.adapters.repository.git import GitRepositoryAdapter
from agent_fleet.adapters.system import UuidIdGenerator
from agent_fleet.bootstrap import build_container
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import ArtifactKind, RunStatus
from agent_fleet.domain.offline_canary import FIXED_CANARY

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]
_MODEL = "claude-haiku-4-5-20251001"
_KEY = "offline-anthropic-workflow-credential"


@pytest.mark.parametrize("cleanup_failure", [False, True])
async def test_anthropic_sdk_roles_cross_real_gateway_and_keep_simulated_proof_gap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cleanup_failure: bool
) -> None:
    clients: list[httpx2.AsyncClient] = []
    requests: dict[str, int] = {}
    monkeypatch.delenv("ANTHROPIC_LOG", raising=False)
    monkeypatch.delenv("ANTHROPIC_CUSTOM_HEADERS", raising=False)
    monkeypatch.setenv("FLEET_ANTHROPIC_WORKFLOW", _KEY)
    repository = GitRepositoryAdapter(tmp_path, UuidIdGenerator()).create_canary_fixture(
        tmp_path / "target"
    )
    state_root = tmp_path / "state"
    container = build_container(state_root)
    container.projects._initialize_without_canary(
        repository,
        runtime_name="pydantic-ai",
        provider_model=f"anthropic:{_MODEL}",
        credential_ref="env:FLEET_ANTHROPIC_WORKFLOW",
        sandbox_name="fake",
    )
    harness = FleetHarness(tmp_path, state_root, repository, container)
    heads = harness.git("rev-parse", "HEAD"), harness.git("status", "--porcelain")

    def respond(received: httpx2.Request) -> httpx2.Response:
        body = json.loads(received.content)
        assert body["model"] == _MODEL
        assert received.headers["x-api-key"] == _KEY
        assert _KEY not in received.content.decode()
        assert str(received.url) == "https://api.anthropic.com/v1/messages?beta=true"
        output = next(tool["name"] for tool in body["tools"] if tool["name"].startswith("submit_"))
        number = requests.get(output, 0) + 1
        requests[output] = number
        calls: list[tuple[str, dict[str, object]]]
        if output == "submit_scope_decision":
            calls = [
                (
                    output,
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
        elif output == "submit_implementation_report" and number == 1:
            calls = [
                (
                    "workspace_write_file",
                    {
                        "path": "src/canary_calc/core.py",
                        "content": FIXED_CANARY,
                        "reason": "Bounded repair.",
                    },
                ),
                ("run_verification", {"command_id": "python-test", "reason": "Check candidate."}),
            ]
        elif output == "submit_implementation_report":
            calls = [
                (
                    output,
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
        elif output == "submit_verifier_verdict" and number == 1:
            calls = [
                (
                    "run_verification",
                    {"command_id": "python-test", "reason": "Independent simulated verification."},
                )
            ]
        else:
            assert output == "submit_verifier_verdict" and number == 2
            calls = [
                (
                    output,
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
            json={
                "id": f"msg_{len(requests)}_{number}",
                "type": "message",
                "role": "assistant",
                "model": _MODEL,
                "stop_reason": "tool_use",
                "stop_sequence": None,
                "content": [
                    {
                        "type": "tool_use",
                        "id": f"call_{number}_{index}",
                        "name": name,
                        "input": arguments,
                    }
                    for index, (name, arguments) in enumerate(calls)
                ],
                "usage": {"input_tokens": 10, "output_tokens": 5},
            },
        )

    class ClosingTransport(httpx2.MockTransport):
        async def aclose(self) -> None:
            await super().aclose()
            if cleanup_failure:
                raise RuntimeError(_KEY)

    def transport(**kwargs: Any) -> httpx2.AsyncClient:
        client = httpx2.AsyncClient(transport=ClosingTransport(respond), **kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(provider_module, "AsyncClient", transport)
    with override_allow_model_requests(True):
        execution = harness.container.workflow.start(
            project_path=harness.repository_root,
            goal="Fix the canary behavior",
            runtime_name="pydantic-ai",
            provider_model=f"anthropic:{_MODEL}",
            credential_ref="env:FLEET_ANTHROPIC_WORKFLOW",
            sandbox_name="fake",
            fake_scenario=None,
        )
        if cleanup_failure:
            with pytest.raises(FleetError) as caught:
                await execution
            assert caught.value.code is ErrorCode.PROVIDER_FAILED
            run = harness.container.state.get_run(caught.value.details["run_id"])
        else:
            run = await execution
    if cleanup_failure:
        assert run.status is RunStatus.FAILED and not run.verified_complete
        assert requests == {"submit_scope_decision": 1}
        events = harness.container.state.list_events(run.run_id)
        failed = [event for event in events if event.event_type == "agent.failed"]
        assert len(failed) == 1
        assert failed[0].payload["runtime_diagnostic"] == {
            "category": "provider_sdk",
            "cause_category": "client_cleanup",
        }
        assert not any(event.event_type == "tool.intent_executed" for event in events)
        assert _KEY not in str([event.model_dump(mode="json") for event in events])
        snapshot = harness.container.budgets.snapshot(run.run_id)
        assert snapshot.model_requests == 1 and snapshot.reported_total_tokens == 15
        assert snapshot.unknown_requests == snapshot.outstanding_requests == 0
        assert snapshot.tool_calls == 0
        assert harness.container.state.outstanding_leases(run.run_id) == []
        assert (harness.git("rev-parse", "HEAD"), harness.git("status", "--porcelain")) == heads
        assert len(clients) == 1 and clients[0].is_closed
        return
    assert run.status is RunStatus.READY_FOR_REVIEW and not run.verified_complete
    assert run.provider_model == f"anthropic:{_MODEL}"
    assert requests == {
        "submit_scope_decision": 1,
        "submit_implementation_report": 2,
        "submit_verifier_verdict": 2,
    }
    assert len(clients) == 3 and all(client.is_closed for client in clients)
    snapshot = harness.container.budgets.snapshot(run.run_id)
    assert snapshot.model_requests == 5 and snapshot.reported_total_tokens == 75
    assert snapshot.unknown_requests == snapshot.outstanding_requests == 0
    assert snapshot.tool_calls == 3 and snapshot.agent_invocations == 3
    assert snapshot.reported_costs == {}
    artifacts = harness.container.state.list_artifacts(run.run_id)
    usages = [item for item in artifacts if item.kind is ArtifactKind.RUNTIME_USAGE]
    assert len(usages) == 3
    for item in usages:
        raw = harness.container.artifacts.read_text(item.artifact_id)
        value = json.loads(raw)
        assert value["provider_metadata"]["provider"] == "anthropic"
        assert value["provider_metadata"]["model"] == f"anthropic:{_MODEL}"
        assert _KEY not in raw
    events = harness.container.state.list_events(run.run_id)
    assert [
        event.payload["action"] for event in events if event.event_type == "tool.intent_executed"
    ] == ["workspace.write_file", "command.run", "command.run"]
    assert _KEY not in str([event.model_dump(mode="json") for event in events])
    status = harness.container.inspection.status(run.run_id)
    evidence = status["evidence"]
    assert isinstance(evidence, dict)
    assert evidence["changed_paths"] == ["src/canary_calc/core.py"]
    assert "SIMULATED_EVIDENCE_ONLY" in evidence["completion_reason_codes"]
    assert harness.container.state.outstanding_leases(run.run_id) == []
    assert (harness.git("rev-parse", "HEAD"), harness.git("status", "--porcelain")) == heads
