from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import FleetHarness
from typer.testing import CliRunner

from agent_fleet.bootstrap import build_container
from agent_fleet.cli.app import app
from agent_fleet.domain.budgets import RunBudgetLimits, RunBudgetSnapshot
from agent_fleet.domain.errors import ErrorCode
from agent_fleet.domain.models import RunStatus

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    "options,expected",
    [
        ([], RunBudgetLimits()),
        (["--max-model-requests", "7"], RunBudgetLimits(max_model_requests=7)),
        (
            [
                "--max-agent-invocations",
                "12",
                "--max-model-requests",
                "24",
                "--max-tool-calls",
                "32",
                "--max-total-tokens",
                "65536",
                "--max-active-seconds",
                "600",
            ],
            RunBudgetLimits(
                max_agent_invocations=12,
                max_model_requests=24,
                max_tool_calls=32,
                max_total_tokens=65_536,
                max_active_seconds=600,
            ),
        ),
    ],
)
def test_cli_run_limits_persist_and_reopen(
    harness: FleetHarness, options: list[str], expected: RunBudgetLimits
) -> None:
    runner = CliRunner()
    environment = {"AGENT_FLEET_HOME": str(harness.state_root)}
    result = runner.invoke(
        app,
        [
            "run",
            "Fix the canary behavior",
            "--project",
            str(harness.repository_root),
            *options,
            "--json",
        ],
        env=environment,
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)["data"]
    assert data["status"] == RunStatus.READY_FOR_REVIEW.value
    snapshot = RunBudgetSnapshot.model_validate(data["runtime_budget"])
    assert snapshot.limits == expected
    assert snapshot.agent_invocations == 3
    assert snapshot.model_requests == 0
    assert snapshot.token_limit_is_pre_spend_billing_cap is False
    reopened = build_container(harness.state_root)
    assert reopened.budgets.snapshot(data["run_id"]) == snapshot
    inspected = runner.invoke(app, ["status", data["run_id"], "--json"], env=environment)
    assert inspected.exit_code == 0, inspected.output
    assert json.loads(inspected.stdout)["data"]["runtime_budget"] == data["runtime_budget"]


@pytest.mark.parametrize(
    "option,value",
    [
        ("--max-agent-invocations", "0"),
        ("--max-agent-invocations", "10001"),
        ("--max-model-requests", "0"),
        ("--max-model-requests", "100001"),
        ("--max-tool-calls", "-1"),
        ("--max-tool-calls", "100001"),
        ("--max-total-tokens", "0"),
        ("--max-total-tokens", "100000001"),
        ("--max-active-seconds", "0"),
        ("--max-active-seconds", "86401"),
    ],
)
def test_invalid_cli_limits_fail_before_creating_state(
    tmp_path: Path, option: str, value: str
) -> None:
    state_root = tmp_path / "state-must-not-exist"
    result = CliRunner().invoke(
        app,
        ["run", "No work may start", "--project", str(tmp_path), option, value, "--json"],
        env={"AGENT_FLEET_HOME": str(state_root)},
    )
    assert result.exit_code == 2, result.output
    envelope = json.loads(result.stdout)
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == ErrorCode.CONFIG_INVALID.value
    assert not state_root.exists()


@pytest.mark.parametrize("value", ["not-an-integer", "1.5"])
def test_noninteger_cli_limit_fails_before_creating_state(tmp_path: Path, value: str) -> None:
    state_root = tmp_path / "state-must-not-exist"
    result = CliRunner().invoke(
        app,
        ["run", "No work may start", "--max-total-tokens", value, "--json"],
        env={"AGENT_FLEET_HOME": str(state_root)},
    )
    assert result.exit_code == 2, result.output
    assert not state_root.exists()


@pytest.mark.parametrize(
    "option,value,expected",
    [
        ("--max-agent-invocations", "1", RunBudgetLimits(max_agent_invocations=1)),
        ("--max-tool-calls", "0", RunBudgetLimits(max_tool_calls=0)),
    ],
)
def test_cli_low_limits_stop_before_engineer_effect_and_clean_resources(
    harness: FleetHarness, option: str, value: str, expected: RunBudgetLimits
) -> None:
    original_status = harness.git("status", "--porcelain")
    result = CliRunner().invoke(
        app,
        [
            "run",
            "Fix the canary behavior",
            "--project",
            str(harness.repository_root),
            option,
            value,
            "--json",
        ],
        env={"AGENT_FLEET_HOME": str(harness.state_root)},
    )
    assert result.exit_code == 5, result.output
    error = json.loads(result.stdout)["error"]
    assert error["code"] == ErrorCode.RUNTIME_BUDGET_EXCEEDED.value
    run_id = error["details"]["run_id"]
    reopened = build_container(harness.state_root)
    assert reopened.state.get_run(run_id).status is RunStatus.FAILED
    assert not reopened.state.outstanding_leases(run_id)
    assert reopened.state.count_executed_intents(run_id, "workspace.write_file") == 0
    snapshot = reopened.budgets.snapshot(run_id)
    assert snapshot.limits == expected
    assert snapshot.agent_invocations <= expected.max_agent_invocations
    assert snapshot.tool_calls == 0
    assert harness.git("status", "--porcelain") == original_status


def test_cli_approval_resume_preserves_exhausted_invocation_budget(harness: FleetHarness) -> None:
    runner = CliRunner()
    environment = {"AGENT_FLEET_HOME": str(harness.state_root)}
    result = runner.invoke(
        app,
        [
            "run",
            "Fix the canary behavior",
            "--project",
            str(harness.repository_root),
            "--fake-scenario",
            "approval",
            "--max-agent-invocations",
            "2",
            "--json",
        ],
        env=environment,
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)["data"]
    assert data["status"] == RunStatus.PAUSED_FOR_APPROVAL.value
    run_id = data["run_id"]
    approved = runner.invoke(
        app, ["approve", data["pending_approval_id"], "--once", "--json"], env=environment
    )
    assert approved.exit_code == 0, approved.output
    resumed = runner.invoke(app, ["resume", run_id, "--json"], env=environment)
    assert resumed.exit_code == 5, resumed.output
    assert json.loads(resumed.stdout)["error"]["code"] == ErrorCode.RUNTIME_BUDGET_EXCEEDED.value
    reopened = build_container(harness.state_root)
    snapshot = reopened.budgets.snapshot(run_id)
    assert snapshot.limits == RunBudgetLimits(max_agent_invocations=2)
    assert snapshot.agent_invocations == 2
    assert reopened.state.get_run(run_id).status is RunStatus.FAILED
    assert reopened.state.count_executed_intents(run_id, "fixture.record_side_effect") == 0
    assert not reopened.state.outstanding_leases(run_id)
