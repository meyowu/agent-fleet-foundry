from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

import pytest
from pydantic import JsonValue

from agent_fleet.application.gateway import ToolGateway
from agent_fleet.application.runtime_tools import GatewayRuntimeToolCatalog
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import (
    AcceptanceCriterion,
    AgentInstance,
    AgentRole,
    AgentStatus,
    FakeScenario,
    Run,
    RuntimeToolCall,
    SandboxHandle,
    TaskSpec,
    WorkflowStage,
    Workspace,
    WorkspaceKind,
)
from agent_fleet.domain.security import Redactor


class RecordingGateway:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def execute(self, **kwargs: Any) -> dict[str, object]:
        self.calls.append(kwargs)
        return {"command_evidence_artifact_id": "art_" + "9" * 32}


def _catalog(
    role: AgentRole,
    *,
    max_calls: int = 3,
    scenario: FakeScenario = FakeScenario.SUCCESS,
    redactor: Redactor | None = None,
) -> tuple[GatewayRuntimeToolCatalog, RecordingGateway]:
    now = datetime.now(UTC)
    run = Run(
        run_id="run_" + "1" * 32,
        project_id="prj_" + "2" * 32,
        correlation_id="corr_" + "3" * 32,
        goal="bounded goal",
        base_revision="a" * 40,
        target_status_fingerprint="4" * 64,
        fake_scenario=scenario,
        status="running",
        stage=(
            WorkflowStage.IMPLEMENTING if role is AgentRole.ENGINEER else WorkflowStage.VERIFYING
        ),
        task_id="task_" + "5" * 32,
        created_at=now,
        updated_at=now,
    )
    task = TaskSpec(
        task_id="task_" + "5" * 32,
        run_id=run.run_id,
        original_goal="bounded goal",
        normalized_goal="bounded goal",
        base_revision=run.base_revision,
        allowed_paths=["src/canary_calc/core.py"],
        forbidden_paths=[".git", ".fleet"],
        acceptance_criteria=[
            AcceptanceCriterion(criterion_id="canary", description="canary passes")
        ],
        required_evidence=["canonical_patch", "command_evidence"],
        max_repair_iterations=1,
        config_snapshot_hash="6" * 64,
        created_at=now,
    )
    agent = AgentInstance(
        agent_instance_id="agent_" + "7" * 32,
        run_id=run.run_id,
        task_id=task.task_id,
        role=role,
        status=AgentStatus.RUNNING,
        iteration=0,
        created_at=now,
    )
    workspace = Workspace(
        workspace_id="ws_" + "8" * 32,
        run_id=run.run_id,
        kind=(
            WorkspaceKind.CANDIDATE if role is AgentRole.ENGINEER else WorkspaceKind.VERIFICATION
        ),
        path="/trusted/application-only/path",
        base_revision=run.base_revision,
    )
    sandbox = SandboxHandle(
        sandbox_id="sandbox_" + "a" * 32,
        run_id=run.run_id,
        workspace_host_path=workspace.path,
    )
    gateway = RecordingGateway()
    return (
        GatewayRuntimeToolCatalog(
            gateway=cast(ToolGateway, gateway),
            redactor=redactor or Redactor(),
            run=run,
            task=task,
            agent=agent,
            workspace=workspace,
            sandbox_handle=sandbox,
            max_calls=max_calls,
        ),
        gateway,
    )


def test_tool_definitions_are_role_specific_and_identity_free() -> None:
    engineer, _ = _catalog(AgentRole.ENGINEER)
    verifier, _ = _catalog(AgentRole.VERIFIER)

    assert [item.name for item in engineer.definitions] == [
        "repo_list_files",
        "repo_read_file",
        "repo_search_text",
        "workspace_get_diff",
        "workspace_write_file",
        "workspace_apply_edit",
        "workspace_delete_file",
        "run_verification",
    ]
    assert [item.name for item in verifier.definitions] == [
        "repo_list_files",
        "repo_read_file",
        "repo_search_text",
        "workspace_get_diff",
        "run_verification",
    ]
    serialized = str([item.model_dump(mode="json") for item in engineer.definitions])
    for forbidden in ("run_id", "task_id", "agent_instance_id", "sandbox_handle", "host_path"):
        assert forbidden not in serialized


@pytest.mark.parametrize("role", [AgentRole.RESEARCHER, AgentRole.ARCHITECT])
async def test_specialist_catalog_has_only_reads_and_rejects_hidden_side_effects(
    role: AgentRole,
) -> None:
    catalog, gateway = _catalog(role, scenario=FakeScenario.APPROVAL)
    assert [item.name for item in catalog.definitions] == [
        "repo_list_files",
        "repo_read_file",
        "repo_search_text",
        "workspace_get_diff",
    ]
    assert all(not item.side_effect for item in catalog.definitions)
    forbidden_calls: list[tuple[str, dict[str, JsonValue]]] = [
        ("workspace_write_file", {"path": "src/canary_calc/core.py", "content": "changed"}),
        (
            "workspace_apply_edit",
            {
                "path": "src/canary_calc/core.py",
                "expected_sha256": "a" * 64,
                "old": "old",
                "new": "new",
                "expected_matches": 1,
            },
        ),
        ("workspace_delete_file", {"path": "src/canary_calc/core.py", "expected_sha256": "a" * 64}),
        ("run_verification", {"command_id": "offline-canary"}),
        ("record_approval_probe", {"record": "forbidden"}),
    ]
    for name, arguments in forbidden_calls:
        call = RuntimeToolCall(
            call_id=f"forbidden-{name}",
            name=name,
            arguments={**arguments, "reason": "Forbidden specialist escalation."},
        )
        with pytest.raises(FleetError) as caught:
            await catalog.execute(call)
        assert caught.value.code is ErrorCode.COMMAND_DENIED
    assert gateway.calls == []
    assert catalog.records == ()
    await catalog.execute(
        RuntimeToolCall(
            call_id="read",
            name="repo_read_file",
            arguments={"path": "src/canary_calc/core.py", "reason": "Read assigned context."},
        )
    )
    assert len(gateway.calls) == 1
    assert gateway.calls[0]["scripted"].side_effect is False


def test_tool_validation_is_schema_specific_and_side_effect_free() -> None:
    catalog, gateway = _catalog(AgentRole.ENGINEER)
    valid = RuntimeToolCall(
        call_id="call_write_valid",
        name="workspace_write_file",
        arguments={
            "path": "src/canary_calc/core.py",
            "content": "value = 1\n",
            "reason": "Implement the bounded task.",
        },
    )
    invalid = valid.model_copy(
        update={
            "call_id": "call_write_invalid",
            "arguments": {
                "path": "src/canary_calc/core.py",
                "content": "value = 1\n",
            },
        }
    )

    catalog.validate(valid)
    with pytest.raises(ValueError):
        catalog.validate(invalid)

    assert gateway.calls == []
    assert catalog.records == ()


@pytest.mark.asyncio
async def test_tool_execution_binds_gateway_context_and_returns_only_safe_result() -> None:
    catalog, gateway = _catalog(AgentRole.ENGINEER)
    call = RuntimeToolCall(
        call_id="call_write_1",
        name="workspace_write_file",
        arguments={
            "path": "src/canary_calc/core.py",
            "content": "def divide(a, b):\n    return a / b\n",
            "reason": "Implement the bounded task.",
        },
    )

    first = await catalog.execute(call)
    second = await catalog.execute(call)

    assert first == second
    assert len(gateway.calls) == 1
    scripted = gateway.calls[0]["scripted"]
    assert scripted.action == "workspace.write_file"
    assert scripted.resource.identifier == "src/canary_calc/core.py"
    assert first.artifact_ids == ("art_" + "9" * 32,)
    assert catalog.records[0].side_effect_committed is True


@pytest.mark.asyncio
async def test_read_edit_and_delete_tools_translate_to_narrow_gateway_actions() -> None:
    catalog, gateway = _catalog(AgentRole.ENGINEER)
    calls = [
        RuntimeToolCall(
            call_id="call_read_1",
            name="repo_read_file",
            arguments={"path": "src/canary_calc/core.py", "reason": "Inspect target."},
        ),
        RuntimeToolCall(
            call_id="call_edit_1",
            name="workspace_apply_edit",
            arguments={
                "path": "src/canary_calc/core.py",
                "expected_sha256": "a" * 64,
                "old": "value = 1",
                "new": "value = 2",
                "expected_matches": 1,
                "reason": "Apply bounded change.",
            },
        ),
        RuntimeToolCall(
            call_id="call_delete_1",
            name="workspace_delete_file",
            arguments={
                "path": "src/canary_calc/core.py",
                "expected_sha256": "b" * 64,
                "reason": "Delete reviewed file.",
            },
        ),
    ]

    for call in calls:
        await catalog.execute(call)

    scripted_actions = [item["scripted"] for item in gateway.calls]
    assert [item.action for item in scripted_actions] == [
        "repo.read_file",
        "workspace.apply_edit",
        "workspace.delete_path",
    ]
    assert scripted_actions[0].side_effect is False
    assert scripted_actions[1].parameters["expected_sha256"] == "a" * 64
    assert scripted_actions[2].parameters == {"expected_sha256": "b" * 64}
    assert [record.side_effect_committed for record in catalog.records] == [False, True, True]


@pytest.mark.asyncio
async def test_tool_budget_and_call_id_reuse_fail_closed() -> None:
    catalog, gateway = _catalog(AgentRole.ENGINEER, max_calls=1)
    call = RuntimeToolCall(
        call_id="call_check_1",
        name="run_verification",
        arguments={
            "command_id": "offline-canary",
            "reason": "Collect bounded evidence.",
        },
    )
    await catalog.execute(call)

    with pytest.raises(FleetError) as reused:
        await catalog.execute(
            call.model_copy(
                update={
                    "arguments": {
                        "command_id": "offline-canary",
                        "reason": "Changed after execution.",
                    }
                }
            )
        )
    assert reused.value.code is ErrorCode.COMMAND_DENIED

    with pytest.raises(FleetError) as exhausted:
        await catalog.execute(
            RuntimeToolCall(
                call_id="call_check_2",
                name="run_verification",
                arguments={
                    "command_id": "offline-canary",
                    "reason": "A second request.",
                },
            )
        )
    assert exhausted.value.code is ErrorCode.RUNTIME_BUDGET_EXCEEDED
    assert len(gateway.calls) == 1


@pytest.mark.asyncio
async def test_registered_secret_is_rejected_before_gateway_execution() -> None:
    secret = "RUNTIME-TOOL-SECRET-SENTINEL"
    catalog, gateway = _catalog(AgentRole.ENGINEER, redactor=Redactor([secret]))

    with pytest.raises(FleetError) as captured:
        await catalog.execute(
            RuntimeToolCall(
                call_id="call_secret_1",
                name="workspace_write_file",
                arguments={
                    "path": "src/canary_calc/core.py",
                    "content": secret,
                    "reason": "This must never cross the gateway.",
                },
            )
        )

    assert captured.value.code is ErrorCode.COMMAND_DENIED
    assert gateway.calls == []
    assert catalog.records == ()
