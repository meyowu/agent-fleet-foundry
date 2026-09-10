from __future__ import annotations

from pathlib import Path

import httpx2
import pytest
from action_tool_fixtures import (
    configuration,
    make_action_tools,
    persist_action_tools,
    sdk_adapter,
    tool_response,
    wire_tools,
)
from pydantic_ai.models import override_allow_model_requests

from agent_fleet.domain.budgets import RuntimeAttemptStatus
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import AgentRole
from agent_fleet.ports.runtime import RuntimeInvocationServices

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("provider", ["openai", "openai-chat"])
@pytest.mark.parametrize("role", [AgentRole.ENGINEER, AgentRole.VERIFIER])
@pytest.mark.parametrize(
    "invalid,expected",
    [
        ({"reason": "Run python-test."}, ErrorCode.RUNTIME_OUTPUT_INVALID),
        ({"command_id": 7, "reason": "Verify."}, ErrorCode.RUNTIME_OUTPUT_INVALID),
        (
            {"command_id": "python-test", "reason": "Verify.", "extra": "untrusted"},
            ErrorCode.RUNTIME_OUTPUT_INVALID,
        ),
        ({"command_id": "python-test", "reason": "x" * 4097}, ErrorCode.RUNTIME_OUTPUT_INVALID),
        ({"command_id": "x" * 101, "reason": "Verify."}, ErrorCode.RUNTIME_OUTPUT_INVALID),
        ({"command_id": "unadmitted", "reason": "Verify."}, ErrorCode.COMMAND_NOT_REVIEWED),
    ],
    ids=["missing-id", "wrong-type", "extra", "oversized-reason", "oversized-id", "wrong-enum"],
)
async def test_sdk_invalid_fourth_response_cannot_reserve_fifth_request_or_execute_batch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    role: AgentRole,
    invalid: dict[str, object],
    expected: ErrorCode,
) -> None:
    tools = make_action_tools(role=role)
    originals = {d.name: d.model_dump_json() for d in tools.catalog.definitions}
    budget = persist_action_tools(tmp_path, tools)
    accounting = budget.begin_attempt(tools.invocation)
    sends: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        sends.append(request)
        if len(sends) < 4:
            return tool_response(
                request, [("repo_list_files", {"reason": "Inspect bounded files."})], len(sends)
            )
        assert len(sends) == 4, "invalid batch must not request a correction or replay"
        # Even a valid side effect first in a provider-violating parallel batch must not execute.
        first: tuple[str, dict[str, object]] = (
            (
                "workspace_write_file",
                {
                    "path": "src/canary_calc/core.py",
                    "content": "wrong = True\n",
                    "reason": "Candidate.",
                },
            )
            if role is AgentRole.ENGINEER
            else ("run_verification", {"command_id": "python-test", "reason": "Independent check."})
        )
        return tool_response(
            request,
            [
                first,
                ("run_verification", invalid),
            ],
            len(sends),
        )

    adapter, clients = sdk_adapter(monkeypatch, handler)
    with override_allow_model_requests(True), pytest.raises(FleetError) as caught:
        await adapter.invoke(
            tools.invocation,
            RuntimeInvocationServices(
                configuration=configuration(provider),
                tools=tools.catalog,
                accounting=accounting,
            ),
        )
    accounting.finish(RuntimeAttemptStatus.FAILED, error_code=caught.value.code)
    assert caught.value.code is expected
    if expected is ErrorCode.RUNTIME_OUTPUT_INVALID:
        assert caught.value.details["runtime_diagnostic"] == {
            "category": "tool_arguments",
            "cause_category": "schema_validation",
        }
        assert caught.value.__cause__ is None and caught.value.__context__ is None
        assert "x" * 101 not in str(caught.value.details)
    snapshot = budget.snapshot(tools.run.run_id)
    assert snapshot.model_requests == 4
    assert snapshot.tool_calls == 3
    assert snapshot.unknown_requests == snapshot.reserved_tokens == 0
    assert snapshot.reported_total_tokens == 60
    assert snapshot.completeness == "complete"
    assert len(tools.gateway.calls) == 3
    assert all(call["scripted"].action == "repo.list_files" for call in tools.gateway.calls)
    assert len(tools.catalog.records) == 3
    assert not any(record.side_effect for record in tools.catalog.records)
    assert len(sends) == 4 and all(client.is_closed for client in clients)
    assert {d.name: d.model_dump_json() for d in tools.catalog.definitions} == originals
    for request in sends:
        wire = wire_tools(request)
        assert wire["run_verification"]["strict"] is True
        assert set(wire["run_verification"]["parameters"]["required"]) == {"command_id", "reason"}
