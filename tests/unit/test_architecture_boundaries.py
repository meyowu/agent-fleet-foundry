from __future__ import annotations

import ast
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_fleet.domain.models import AgentInvocation, WorkflowStage


def test_application_layer_does_not_import_concrete_adapters() -> None:
    application_root = Path(__file__).parents[2] / "src" / "agent_fleet" / "application"
    violations: list[str] = []
    for module_path in sorted(application_root.rglob("*.py")):
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            imported: list[str] = []
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
                line_number = node.lineno
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imported.append(node.module)
                line_number = node.lineno
            else:
                continue
            for imported_module in imported:
                if imported_module == "agent_fleet.adapters" or imported_module.startswith(
                    "agent_fleet.adapters."
                ):
                    violations.append(
                        f"{module_path.relative_to(application_root)}:{line_number} "
                        f"imports {imported_module}"
                    )

    assert violations == []


def test_runtime_invocation_rejects_host_paths_and_sandbox_handles() -> None:
    common = {
        "run_id": "run_" + "1" * 32,
        "task_id": "task_" + "2" * 32,
        "agent_instance_id": "agent_" + "3" * 32,
        "role": "verifier",
        "stage": WorkflowStage.VERIFYING,
        "iteration": 0,
        "max_steps": 10,
    }
    for protected in (
        "verification_workspace_path",
        "workspace_host_path",
        "workspace_path",
        "candidate_workspace_path",
        "repository_root",
        "repository_path",
        "project_root",
        "host_path",
        "alternate_filesystem_path",
        "alternate_absolute_path",
        "sandbox_handle",
        "sandbox_id",
    ):
        with pytest.raises(ValidationError, match="execution capability"):
            AgentInvocation(**common, input={"nested": {protected: "/tmp/escape"}})


def test_runtime_invocation_accepts_logical_artifact_and_patch_identity() -> None:
    request = AgentInvocation(
        run_id="run_" + "1" * 32,
        task_id="task_" + "2" * 32,
        agent_instance_id="agent_" + "3" * 32,
        role="verifier",
        stage=WorkflowStage.VERIFYING,
        iteration=0,
        max_steps=10,
        input={
            "patch_sha256": "a" * 64,
            "artifact_id": "art_" + "4" * 32,
            "requested_at": datetime(2026, 9, 4, tzinfo=UTC).isoformat(),
        },
    )
    assert request.input["patch_sha256"] == "a" * 64


def test_pydantic_runtime_has_no_repository_sandbox_or_native_execution_import() -> None:
    adapter_path = (
        Path(__file__).parents[2]
        / "src"
        / "agent_fleet"
        / "adapters"
        / "runtime"
        / "pydantic_ai.py"
    )
    source = adapter_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported_modules.add(node.module)

    forbidden_prefixes = (
        "subprocess",
        "agent_fleet.application",
        "agent_fleet.adapters.repository",
        "agent_fleet.adapters.sandbox",
        "pydantic_ai.mcp",
        "pydantic_ai.builtin_tools",
    )
    assert not any(
        module == prefix or module.startswith(f"{prefix}.")
        for module in imported_modules
        for prefix in forbidden_prefixes
    )
    for forbidden_symbol in (
        "MCPServer",
        "ShellToolset",
        "CodeExecutionTool",
        "WebSearchTool",
        "FunctionToolset",
    ):
        assert forbidden_symbol not in source
