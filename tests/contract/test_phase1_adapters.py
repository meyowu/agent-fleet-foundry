from __future__ import annotations

import ast
import re
import sqlite3
from datetime import timedelta
from pathlib import Path

import pytest

import agent_fleet.adapters.runtime.fake as fake_runtime_module
from agent_fleet.adapters.artifacts.local import LocalArtifactStore
from agent_fleet.adapters.config.yaml import YamlConfigurationAdapter
from agent_fleet.adapters.diagnostics.system import LocalSystemDiagnostics
from agent_fleet.adapters.persistence.sqlite import SUPPORTED_SCHEMA_VERSION, SqliteStateStore
from agent_fleet.adapters.repository.git import GitRepositoryAdapter
from agent_fleet.adapters.repository.profile import StaticRepositoryProfiler
from agent_fleet.adapters.runtime.fake import FakeRuntimeAdapter
from agent_fleet.adapters.system import SystemClock, UuidIdGenerator
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.ids import IdPrefix
from agent_fleet.domain.models import (
    AgentInvocation,
    AgentRole,
    FakeScenario,
    ImplementationReport,
    RuntimeConfiguration,
    RuntimeCredentialCheck,
    RuntimeToolCall,
    RuntimeToolDefinition,
    RuntimeToolExecutionRecord,
    RuntimeToolResult,
    ScopeDecision,
    Verdict,
    VerifierVerdict,
    WorkflowStage,
    WorkspaceKind,
)
from agent_fleet.domain.offline_canary import FIXED_CANARY
from agent_fleet.domain.security import Redactor
from agent_fleet.ports.artifact_store import ArtifactStore
from agent_fleet.ports.clock import Clock
from agent_fleet.ports.config import ConfigurationPort
from agent_fleet.ports.diagnostics import SystemDiagnostics
from agent_fleet.ports.id_generator import IdGenerator
from agent_fleet.ports.repository import RepositoryPort
from agent_fleet.ports.repository_profile import RepositoryProfilerPort
from agent_fleet.ports.runtime import (
    EMPTY_RUNTIME_TOOL_CATALOG,
    RuntimeAdapter,
    RuntimeInvocationServices,
)
from agent_fleet.ports.state_store import StateStore


def test_local_artifact_store_is_content_addressed_and_checks_integrity(tmp_path: Path) -> None:
    store: ArtifactStore = LocalArtifactStore(tmp_path / "artifacts")
    content = b"same bytes always have the same address\n"

    first = store.put(content)
    second = store.put(content)

    assert first == second
    content_ref, digest, byte_size = first
    assert content_ref.endswith(digest)
    assert byte_size == len(content)
    assert store.get(content_ref, digest) == content

    (tmp_path / "artifacts" / content_ref).write_bytes(b"tampered")
    with pytest.raises(FleetError) as captured:
        store.get(content_ref, digest)
    assert captured.value.code is ErrorCode.ARTIFACT_INTEGRITY_FAILED


def test_yaml_configuration_defaults_validate_and_hash_deterministically() -> None:
    adapter: ConfigurationPort = YamlConfigurationAdapter()

    first_files = adapter.default_files("contract-project")
    second_files = adapter.default_files("contract-project")
    first_spec = adapter.validate_files(first_files)
    second_spec = adapter.validate_files(second_files)

    assert first_files == second_files
    assert first_spec == second_spec
    assert adapter.hash(first_spec) == adapter.hash(second_spec)
    assert len(adapter.hash(first_spec)) == 64
    assert first_spec.metadata.name == "contract-project"


def test_static_repository_profiler_is_deterministic_and_executes_nothing(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "repository-code-executed"
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "package.json").write_text(
        '{"scripts":{"test":"touch ' + str(marker) + '","build":"echo build"}}',
        encoding="utf-8",
    )
    (repository / "Makefile").write_text(f"test:\n\ttouch {marker}\n", encoding="utf-8")
    profiler: RepositoryProfilerPort = StaticRepositoryProfiler()

    first = profiler.profile(repository)
    second = profiler.profile(repository)

    assert first == second
    assert (
        first.project_knowledge.source_profile_sha256
        == second.project_knowledge.source_profile_sha256
    )
    assert not marker.exists()
    assert {"node", "make"}.issubset(first.profile.ecosystems)
    assert all(command.execution_authorized is False for command in first.profile.commands)


def test_git_repository_workspace_patch_round_trip_does_not_run_checkout_hook(
    tmp_path: Path,
) -> None:
    ids = UuidIdGenerator()
    concrete = GitRepositoryAdapter(tmp_path / "fleet-state", ids)
    repository: RepositoryPort = concrete
    target = concrete.create_canary_fixture(tmp_path / "fleet-state" / "fixtures" / "canary")
    marker = tmp_path / "checkout-hook-executed"
    hook = target / ".git" / "hooks" / "post-checkout"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text(f"#!/bin/sh\ntouch {marker}\n", encoding="utf-8")
    hook.chmod(0o755)
    info = repository.inspect(target)
    run_id = ids.new(IdPrefix.RUN)
    candidate = repository.create_workspace(
        target, run_id, info.head_revision, WorkspaceKind.CANDIDATE
    )
    verifier = None
    try:
        candidate_root = Path(candidate.path)
        (candidate_root / "src/canary_calc/core.py").write_text(FIXED_CANARY, encoding="utf-8")
        patch = repository.compute_patch(candidate)
        assert patch.changed_paths == ["src/canary_calc/core.py"]

        verifier = repository.create_workspace(
            target, run_id, info.head_revision, WorkspaceKind.VERIFICATION
        )
        repository.apply_patch_to_workspace(verifier, patch.content.encode("utf-8"))
        reconstructed = repository.compute_patch(verifier)

        assert reconstructed.content == patch.content
        assert reconstructed.sha256 == patch.sha256
        assert not marker.exists()
    finally:
        if verifier is not None:
            repository.cleanup_workspace(target, verifier)
        repository.cleanup_workspace(target, candidate)


class _RecordingRuntimeToolCatalog:
    def __init__(self) -> None:
        self.calls: list[RuntimeToolCall] = []

    @property
    def definitions(self) -> tuple[RuntimeToolDefinition, ...]:
        return ()

    @property
    def records(self) -> tuple[RuntimeToolExecutionRecord, ...]:
        return ()

    def validate(self, call: RuntimeToolCall) -> None:
        del call

    async def execute(self, call: RuntimeToolCall) -> RuntimeToolResult:
        self.calls.append(call)
        return RuntimeToolResult(call_id=call.call_id, name=call.name)


@pytest.mark.asyncio
async def test_fake_runtime_returns_typed_outputs_and_delegates_actions(
    tmp_path: Path,
) -> None:
    runtime: RuntimeAdapter = FakeRuntimeAdapter()
    ids = UuidIdGenerator()
    run_id = ids.new(IdPrefix.RUN)
    task_id = ids.new(IdPrefix.TASK)
    workspace = tmp_path / "runtime-observation"
    workspace.mkdir()
    before = _snapshot(workspace)
    configuration = RuntimeConfiguration()
    catalog = _RecordingRuntimeToolCatalog()
    preflight = runtime.preflight(configuration, credential_check=RuntimeCredentialCheck.RESOLVE)
    assert preflight.ready is True
    assert preflight.credential_status.value == "not_selected"

    cos_result = await runtime.invoke(
        AgentInvocation(
            run_id=run_id,
            task_id=task_id,
            agent_instance_id=ids.new(IdPrefix.AGENT),
            role=AgentRole.COS,
            stage=WorkflowStage.SCOPING,
            iteration=0,
            max_steps=10,
            input={"goal": "Fix the canary", "fake_scenario": FakeScenario.SUCCESS.value},
        ),
        RuntimeInvocationServices(configuration, EMPTY_RUNTIME_TOOL_CATALOG),
    )
    engineer_result = await runtime.invoke(
        AgentInvocation(
            run_id=run_id,
            task_id=task_id,
            agent_instance_id=ids.new(IdPrefix.AGENT),
            role=AgentRole.ENGINEER,
            stage=WorkflowStage.IMPLEMENTING,
            iteration=0,
            max_steps=20,
            input={"goal": "Fix the canary", "fake_scenario": FakeScenario.SUCCESS.value},
        ),
        RuntimeInvocationServices(configuration, catalog),
    )
    verifier_result = await runtime.invoke(
        AgentInvocation(
            run_id=run_id,
            task_id=task_id,
            agent_instance_id=ids.new(IdPrefix.AGENT),
            role=AgentRole.VERIFIER,
            stage=WorkflowStage.VERIFYING,
            iteration=0,
            max_steps=10,
            input={
                "goal": "Fix the canary",
                "fake_scenario": FakeScenario.SUCCESS.value,
                "repair_iterations": 0,
            },
        ),
        RuntimeInvocationServices(configuration, catalog),
    )

    assert isinstance(cos_result.output, ScopeDecision)
    assert isinstance(engineer_result.output, ImplementationReport)
    assert isinstance(verifier_result.output, VerifierVerdict)
    assert cos_result.output.fleet_strategy == "engineer_verifier"
    assert verifier_result.output.verdict is Verdict.PASS
    assert [call.name for call in catalog.calls] == [
        "workspace_write_file",
        "run_verification",
        "run_verification",
    ]
    assert _snapshot(workspace) == before
    assert not _runtime_imports_execution_bypass()


def test_sqlite_state_store_migrates_to_supported_version_and_reopens(tmp_path: Path) -> None:
    database = tmp_path / "state" / "state.db"
    first: StateStore = SqliteStateStore(database, SystemClock(), UuidIdGenerator(), Redactor())
    assert first.migrate() == SUPPORTED_SCHEMA_VERSION

    reopened: StateStore = SqliteStateStore(database, SystemClock(), UuidIdGenerator(), Redactor())
    assert reopened.migrate() == SUPPORTED_SCHEMA_VERSION
    with sqlite3.connect(database) as connection:
        versions = connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
    assert versions == [(version,) for version in range(1, SUPPORTED_SCHEMA_VERSION + 1)]


def test_local_diagnostics_clock_and_uuid_ids_satisfy_system_contracts(tmp_path: Path) -> None:
    diagnostics: SystemDiagnostics = LocalSystemDiagnostics()
    clock: Clock = SystemClock()
    generator: IdGenerator = UuidIdGenerator()

    python_ok, python_version = diagnostics.python_version()
    writable, detail = diagnostics.state_directory_writable(tmp_path / "state")
    now = clock.now()
    generated = [generator.new(prefix) for prefix in IdPrefix]

    assert python_ok is True
    assert python_version
    assert diagnostics.sqlite_version()
    assert diagnostics.git_version() is None or diagnostics.git_version()
    assert diagnostics.docker_version() is None or diagnostics.docker_version()
    assert writable is True
    assert "Writable" in detail
    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(0)
    assert len(generated) == len(set(generated))
    for prefix, value in zip(IdPrefix, generated, strict=True):
        assert re.fullmatch(rf"{re.escape(prefix.value)}_[0-9a-f]{{32}}", value)


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _runtime_imports_execution_bypass() -> bool:
    source_path = Path(str(fake_runtime_module.__file__))
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    forbidden = {
        "os",
        "pathlib",
        "shutil",
        "subprocess",
        "agent_fleet.adapters.repository",
        "agent_fleet.adapters.sandbox",
    }
    return any(
        name in forbidden
        or name.startswith("agent_fleet.adapters.sandbox.")
        or name.startswith("agent_fleet.adapters.repository.")
        for name in imported
    )
