from __future__ import annotations

import copy

import pytest
from conftest import FleetHarness

from agent_fleet.adapters.runtime.fake import FakeRuntimeAdapter
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import (
    AgentInvocation,
    AgentInvocationResult,
    AgentRole,
    FakeScenario,
    RunStatus,
)


class CommandInjectionRuntime(FakeRuntimeAdapter):
    async def invoke(self, request: AgentInvocation) -> AgentInvocationResult:
        result = await super().invoke(request)
        if request.role is AgentRole.ENGINEER:
            output = copy.deepcopy(result.output)
            actions = output["actions"]
            assert isinstance(actions, list)
            for action in actions:
                assert isinstance(action, dict)
                if action["action"] == "command.run":
                    parameters = action["parameters"]
                    assert isinstance(parameters, dict)
                    parameters["argv"] = ["-m", "pytest", "-q", "&&", "curl", "example.invalid"]
            return AgentInvocationResult(output=output)
        return result


@pytest.mark.integration
@pytest.mark.asyncio
async def test_structured_command_exact_match_rejects_compound_injection(
    harness: FleetHarness,
) -> None:
    harness.container.workflow.runtime = CommandInjectionRuntime()
    with pytest.raises(FleetError) as captured:
        await harness.start(FakeScenario.SUCCESS)
    assert captured.value.code is ErrorCode.COMMAND_DENIED
    run_events = []
    with harness.container.state._connect() as connection:
        rows = connection.execute("SELECT run_id, data_json FROM runs").fetchall()
    for row in rows:
        if row["run_id"].startswith("run_"):
            run_events.append(harness.container.state.get_run(row["run_id"]))
    assert any(run.status is RunStatus.FAILED for run in run_events)
    assert all("curl" not in request.argv for request in harness.container.sandbox.requests)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_git_worktree_creation_runs_no_repository_hook_or_smudge_filter(
    harness: FleetHarness,
) -> None:
    hook_sentinel = harness.root / "hook-executed"
    filter_sentinel = harness.root / "filter-executed"
    hook = harness.repository_root / ".git" / "hooks" / "post-checkout"
    hook.write_text(f"#!/bin/sh\ntouch '{hook_sentinel}'\n", encoding="utf-8")
    hook.chmod(0o755)
    filter_script = harness.root / "malicious-smudge"
    filter_script.write_text(f"#!/bin/sh\ntouch '{filter_sentinel}'\ncat\n", encoding="utf-8")
    filter_script.chmod(0o755)
    (harness.repository_root / ".gitattributes").write_text(
        "filtered.txt filter=evil\n", encoding="utf-8"
    )
    (harness.repository_root / "filtered.txt").write_text("unchanged\n", encoding="utf-8")
    harness.git("add", ".gitattributes", "filtered.txt")
    harness.git(
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-m",
        "add filtered fixture",
        "--",
        ".gitattributes",
        "filtered.txt",
    )
    harness.git("config", "filter.evil.smudge", str(filter_script))
    harness.git("config", "filter.evil.clean", "cat")

    run = await harness.start(FakeScenario.SUCCESS)
    assert run.status is RunStatus.READY_FOR_REVIEW
    assert not hook_sentinel.exists()
    assert not filter_sentinel.exists()
    assert harness.container.patches.show(run.run_id)
