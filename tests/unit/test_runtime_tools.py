from __future__ import annotations

import re
from datetime import UTC, datetime
from itertools import product
from pathlib import Path
from typing import Any, cast

import pytest
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from pydantic import JsonValue

import agent_fleet.application.runtime_tools as runtime_tools
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
from agent_fleet.domain.paths import path_is_within
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
    custom_role: str | None = None,
    allowed_tools: tuple[str, ...] | None = None,
    allowed_paths: list[str] | None = None,
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
        role=custom_role or role,
        execution_kind=role if custom_role is not None else None,
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
    if allowed_paths is not None:
        # Exercise defensive fallback even for legacy/unsupported mutable scopes.
        task.allowed_paths[:] = allowed_paths
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
            allowed_tools=allowed_tools,
        ),
        gateway,
    )


def _read_schema(catalog: GatewayRuntimeToolCatalog) -> dict[str, Any]:
    return next(
        definition.parameters_json_schema
        for definition in catalog.definitions
        if definition.name == "repo_read_file"
    )


@pytest.mark.parametrize("role", list(AgentRole)[1:])
def test_read_scope_hint_preserves_metadata_and_exact_component_semantics(role: AgentRole) -> None:
    catalog, gateway = _catalog(role, allowed_paths=["src/core.py", "tests"])
    schema = _read_schema(catalog)
    validator = Draft202012Validator(schema)
    for path in ("src/core.py", "SRC/CORE.PY", "src/core.py/child", "tests", "tests/unit/a.py"):
        validator.validate({"path": path, "reason": "Inspect."})
    for path in ("src", "src/other.py", "src/core.pyc", "tests2", "README.md", ".fleet"):
        errors = list(validator.iter_errors({"path": path, "reason": "Inspect."}))
        assert len(errors) == 1 and errors[0].validator == "pattern"
    pattern = schema["properties"]["path"].pop("pattern")
    assert pattern.startswith("(?:^(?:") and pattern.endswith(r"|[^\x00-\x7F])")
    assert schema == runtime_tools._READ_FILE.parameters_json_schema
    definition = next(item for item in catalog.definitions if item.name == "repo_read_file")
    assert definition.description == runtime_tools._READ_FILE.description
    assert definition.side_effect is False
    assert gateway.calls == [] and catalog.records == ()


def test_read_scope_hint_escapes_regex_literals_without_file_type_inference() -> None:
    scope = "src/a.^$+{x}(y)|-!#,=.py"
    catalog, _ = _catalog(AgentRole.ENGINEER, allowed_paths=[scope])
    pattern = _read_schema(catalog)["properties"]["path"]["pattern"]
    for path in (scope, scope.upper(), scope + "/directory/child"):
        assert re.search(pattern, path)
    for path in ("src/aX^$+{x}(y)|-!#,=.py", "src/a.py", "y", scope + "extra"):
        assert re.search(pattern, path) is None


@pytest.mark.parametrize(
    "scopes",
    [
        [],
        [""],
        ["."],
        ["/"],
        ["/src"],
        ["src/"],
        ["./src"],
        ["src//child"],
        ["src/../child"],
        ["src/./child"],
        ["src\\child"],
        ["src/*"],
        ["src/?"],
        ["src/[a]"],
        ["src/child]"],
        ["src/\x00"],
        ["src/\n"],
        ["src/\x7f"],
        ["src/é"],
        ["src/\u212a"],
        ["src/\u017f"],
        ["src/\ud800"],
        ["0" * 4097],
        [str(index) for index in range(33)],
        ["/".join(["0"] * 65)],
        ["src/core.py", "unicode/é"],
        ["src", "tests/*"],
        ["src", "."],
    ],
)
def test_unsupported_scope_sets_fall_back_wholly(scopes: list[str]) -> None:
    catalog, gateway = _catalog(AgentRole.ENGINEER, allowed_paths=scopes)
    assert _read_schema(catalog) == runtime_tools._READ_FILE.parameters_json_schema
    assert gateway.calls == []


def test_read_scope_hint_exact_input_count_depth_and_rendered_bounds() -> None:
    for scopes in (
        [str(index) for index in range(32)],
        ["0" * 4096],
        ["0" * 2048, "1" * 2048],
        ["/".join(["0"] * 64)],
    ):
        catalog, _ = _catalog(AgentRole.ENGINEER, allowed_paths=scopes)
        pattern = _read_schema(catalog)["properties"]["path"]["pattern"]
        assert len(pattern) <= 8192
        assert all(re.search(pattern, scope) for scope in scopes)
    over_input, _ = _catalog(AgentRole.ENGINEER, allowed_paths=["0" * 2048, "1" * 2049])
    assert _read_schema(over_input) == runtime_tools._READ_FILE.parameters_json_schema
    minimal, _ = _catalog(AgentRole.ENGINEER, allowed_paths=["0"])
    overhead = len(_read_schema(minimal)["properties"]["path"]["pattern"]) - 1
    letters, digits = divmod(8192 - overhead, 4)
    exact = "a" * letters + "0" * digits
    bounded, _ = _catalog(AgentRole.ENGINEER, allowed_paths=[exact])
    assert len(_read_schema(bounded)["properties"]["path"]["pattern"]) == 8192
    oversized, _ = _catalog(AgentRole.ENGINEER, allowed_paths=[exact + "0"])
    assert _read_schema(oversized) == runtime_tools._READ_FILE.parameters_json_schema


def test_read_scope_hint_has_no_false_negatives_for_bounded_path_predicate_examples() -> None:
    components = ("a", "A", "k", "s", "1", ".hidden", "a+b", "a.b", "{x}", "(y)", "x|y")
    scopes = ["a", "k/s", "a+b", "{x}/(y)"]
    catalog, _ = _catalog(AgentRole.ENGINEER, allowed_paths=scopes)
    pattern = _read_schema(catalog)["properties"]["path"]["pattern"]
    admitted = 0
    for depth in (1, 2, 3):
        for parts in product(components, repeat=depth):
            path = "/".join(parts)
            if path_is_within(path, scopes):
                assert re.search(pattern, path), path
                admitted += 1
    assert admitted > 300
    for character in (*map(chr, range(128, 384)), "\u212a", "\u017f", "ß", "中", "😀", "\ud800"):
        for path in (character, "outside/" + character, "outside/" + character + "/tail"):
            assert re.search(pattern, path)
    for path in ("\u212a/\u017f", "k/\u017f", "\u212a/s"):
        assert path_is_within(path, scopes) and re.search(pattern, path)


def test_read_scope_hint_is_frozen_fresh_and_isolated_without_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("Advertising tools must not access the filesystem or gateway")

    with monkeypatch.context() as guard:
        for name in ("open", "read_text", "read_bytes", "stat", "resolve", "iterdir"):
            guard.setattr(Path, name, forbidden)
        guard.setattr(RecordingGateway, "execute", forbidden)
        original, gateway = _catalog(AgentRole.ENGINEER, allowed_paths=["src/core.py"])
        other, _ = _catalog(AgentRole.ENGINEER, allowed_paths=["tests"])
        first = next(d for d in original.definitions if d.name == "repo_read_file")
        fresh = next(d for d in original.definitions if d.name == "repo_read_file")
        assert first is not fresh
        assert first.parameters_json_schema is not fresh.parameters_json_schema
        original._task.allowed_paths[:] = ["elsewhere"]
        first.parameters_json_schema["properties"] = {}
        first.parameters_json_schema["required"] = []
        assert _read_schema(original) == fresh.parameters_json_schema
        assert _read_schema(other) != _read_schema(original)
        assert (
            runtime_tools._READ_FILE.parameters_json_schema
            == runtime_tools._PathArguments.model_json_schema()
        )
        assert gateway.calls == [] and original.records == ()


@pytest.mark.parametrize("late", [False, True])
def test_read_scope_hint_checks_raw_registered_secret_before_regex_encoding(late: bool) -> None:
    sentinel = "SyntheticScopeSecret"
    redactor = Redactor([] if late else [sentinel])
    catalog, gateway = _catalog(
        AgentRole.ENGINEER, allowed_paths=["src/" + sentinel + ".py"], redactor=redactor
    )
    if late:
        assert "pattern" in _read_schema(catalog)["properties"]["path"]
        redactor.register_secret(sentinel)
    schema = _read_schema(catalog)
    assert schema == runtime_tools._READ_FILE.parameters_json_schema
    assert sentinel not in str(schema) and "[sS][yY]" not in str(schema)
    assert gateway.calls == [] and catalog.records == ()


def test_read_scope_hint_does_not_change_executable_argument_validation() -> None:
    catalog, gateway = _catalog(AgentRole.VERIFIER, allowed_paths=["src/core.py"])
    for path in ("README.md", ".fleet", "src/core.py/../other", "\u212a/\u017f"):
        catalog.validate(
            RuntimeToolCall(
                call_id="read",
                name="repo_read_file",
                arguments={"path": path, "reason": "Broker retains authority."},
            )
        )
    for path in ("", "a" * 4097):
        with pytest.raises(ValueError):
            catalog.validate(
                RuntimeToolCall(
                    call_id="invalid",
                    name="repo_read_file",
                    arguments={"path": path, "reason": "Original local length bounds."},
                )
            )
    assert gateway.calls == [] and catalog.records == ()


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
    assert {item.name: item.side_effect for item in verifier.definitions} == {
        "repo_list_files": False,
        "repo_read_file": False,
        "repo_search_text": False,
        "workspace_get_diff": False,
        "run_verification": True,
    }
    approval_verifier, _ = _catalog(AgentRole.VERIFIER, scenario=FakeScenario.APPROVAL)
    assert approval_verifier.definitions == verifier.definitions
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


@pytest.mark.parametrize(
    ("role", "custom_role", "name", "arguments"),
    [
        (
            AgentRole.ENGINEER,
            "backend",
            "workspace_write_file",
            {"path": "src/canary_calc/core.py", "content": "changed"},
        ),
        (
            AgentRole.VERIFIER,
            "security",
            "run_verification",
            {"command_id": "offline-canary"},
        ),
    ],
)
async def test_custom_tool_narrowing_rejects_valid_excluded_tools_before_gateway(
    role: AgentRole,
    custom_role: str,
    name: str,
    arguments: dict[str, JsonValue],
) -> None:
    unrestricted, _ = _catalog(role)
    catalog, gateway = _catalog(role, custom_role=custom_role, allowed_tools=("repo.read_file",))
    call = RuntimeToolCall(
        call_id="excluded-tool",
        name=name,
        arguments={**arguments, "reason": "Attempt a tool excluded by the reviewed template."},
    )
    assert name in {item.name for item in unrestricted.definitions}
    unrestricted.validate(call)
    assert [item.name for item in catalog.definitions] == ["repo_read_file"]

    with pytest.raises(FleetError) as validation:
        catalog.validate(call)
    assert validation.value.code is ErrorCode.COMMAND_DENIED
    with pytest.raises(FleetError) as execution:
        await catalog.execute(call)
    assert execution.value.code is ErrorCode.COMMAND_DENIED
    assert gateway.calls == []
    assert catalog.records == ()

    await catalog.execute(
        RuntimeToolCall(
            call_id="allowed-read",
            name="repo_read_file",
            arguments={"path": "src/canary_calc/core.py", "reason": "Read the permitted scope."},
        )
    )
    assert len(gateway.calls) == 1
    assert gateway.calls[0]["agent"].role == custom_role
    assert gateway.calls[0]["agent"].effective_kind is role
    assert gateway.calls[0]["scripted"].action == "repo.read_file"
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
