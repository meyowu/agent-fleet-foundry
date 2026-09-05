from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import FleetHarness

from agent_fleet.adapters.repository.profile import StaticRepositoryProfiler
from agent_fleet.adapters.runtime.fake import FakeRuntimeAdapter
from agent_fleet.application.runtime import RuntimeRegistry
from agent_fleet.bootstrap import build_container
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import (
    AgentInstance,
    AgentInvocation,
    AgentInvocationResult,
    AgentRole,
    AgentStatus,
    CanonicalResource,
    FakeScenario,
    RunStatus,
    RuntimeToolCall,
    SandboxCapabilities,
    SandboxHandle,
    SandboxSecurityLevel,
    ScopeDecision,
    ScriptedAction,
    Workspace,
    WorkspaceKind,
)
from agent_fleet.domain.repository_profile import RepositoryProfileResult
from agent_fleet.domain.security import Redactor
from agent_fleet.ports.runtime import RuntimeInvocationServices


class CommandInjectionRuntime(FakeRuntimeAdapter):
    async def invoke(
        self,
        request: AgentInvocation,
        services: RuntimeInvocationServices,
    ) -> AgentInvocationResult:
        if request.role == AgentRole.ENGINEER:
            await services.tools.execute(
                RuntimeToolCall(
                    call_id="injected_command",
                    name="command_run",
                    arguments={
                        "executable": "python",
                        "argv": ["-m", "pytest", "-q", "&&", "curl", "example.invalid"],
                        "cwd": ".",
                    },
                )
            )
            raise AssertionError("bound runtime catalog accepted an arbitrary command tool")
        return await super().invoke(request, services)


class SecretScopeRuntime(FakeRuntimeAdapter):
    def __init__(self, secret: str) -> None:
        self.secret = secret

    async def invoke(
        self,
        request: AgentInvocation,
        services: RuntimeInvocationServices,
    ) -> AgentInvocationResult:
        result = await super().invoke(request, services)
        if request.role == AgentRole.COS:
            assert isinstance(result.output, ScopeDecision)
            output = ScopeDecision.model_validate(
                {
                    **result.output.model_dump(mode="json"),
                    "normalized_goal": f"untrusted {self.secret} output",
                }
            )
            return AgentInvocationResult(
                output=output,
                usage=result.usage,
                checkpoint_ref=result.checkpoint_ref,
                provider_metadata=result.provider_metadata,
            )
        return result


class MismatchedProfileHashProfiler:
    def __init__(self) -> None:
        self.delegate = StaticRepositoryProfiler()

    def profile(self, root: Path) -> RepositoryProfileResult:
        result = self.delegate.profile(root)
        knowledge = result.project_knowledge.model_copy(update={"source_profile_sha256": "f" * 64})
        return result.model_copy(update={"project_knowledge": knowledge})


def test_bootstrap_rejects_profile_secret_before_any_fleet_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sentinel = "FLEET-MANIFEST-REGISTERED-SECRET"
    monkeypatch.setenv("AGENT_FLEET_REDACT_VALUES", sentinel)
    fixture_container = build_container(tmp_path / "fixture-state")
    repository = fixture_container.repository.create_canary_fixture(
        tmp_path / "fixture-state" / "target"
    )
    (repository / "package.json").write_text(
        json.dumps(
            {
                "packageManager": "npm@10.0.0",
                "scripts": {f"test-{sentinel}": "echo safe"},
            }
        ),
        encoding="utf-8",
    )
    state_root = tmp_path / "fleet-state"
    container = build_container(state_root, migrate=False)

    with pytest.raises(FleetError) as captured:
        container.projects._initialize_without_canary(
            repository, runtime_name="fake", sandbox_name="fake"
        )

    assert captured.value.code is ErrorCode.COMMAND_DENIED
    assert sentinel not in str(captured.value)
    assert not (repository / ".fleet").exists()
    assert not state_root.exists()


def test_project_init_rejects_nonexact_fake_sandbox_before_state_write(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "fleet-state"
    container = build_container(state_root, migrate=False)
    container.projects.sandbox_capabilities = SandboxCapabilities.model_construct(
        provider="fake",
        security_level=SandboxSecurityLevel.ISOLATED,
        isolation_enforced=True,
        executes_code=False,
        supported_network_modes=("approved-unrestricted",),
        supports_resource_limits=True,
        supports_recovery=True,
    )
    container.projects.sandboxes = None

    with pytest.raises(FleetError) as captured:
        container.projects._initialize_without_canary(
            tmp_path / "uninspected-repository",
            runtime_name="fake",
            sandbox_name="fake",
        )

    assert captured.value.code is ErrorCode.SANDBOX_UNAVAILABLE
    assert not state_root.exists()


@pytest.mark.parametrize("operation", ["preview", "initialize"])
def test_bootstrap_rejects_secret_from_existing_config_diff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    sentinel = "FLEET-EXISTING-CONFIG-SECRET"
    monkeypatch.setenv("AGENT_FLEET_REDACT_VALUES", sentinel)
    fixture_container = build_container(tmp_path / "fixture-state")
    repository = fixture_container.repository.create_canary_fixture(
        tmp_path / "fixture-state" / "target"
    )
    existing = repository / ".fleet" / "README.md"
    existing.parent.mkdir()
    existing.write_text(f"existing {sentinel}\n", encoding="utf-8")
    state_root = tmp_path / "fleet-state"
    container = build_container(state_root, migrate=False)

    with pytest.raises(FleetError) as captured:
        if operation == "preview":
            container.projects.preview(repository)
        else:
            container.projects._initialize_without_canary(
                repository, runtime_name="fake", sandbox_name="fake"
            )

    assert captured.value.code is ErrorCode.COMMAND_DENIED
    assert sentinel not in str(captured.value)
    assert existing.read_text(encoding="utf-8") == f"existing {sentinel}\n"
    assert sorted(
        path.relative_to(repository / ".fleet").as_posix() for path in existing.parent.rglob("*")
    ) == ["README.md"]
    assert not state_root.exists()


def test_bootstrap_rejects_secret_in_canonical_repository_root_before_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sentinel = "FLEET-CANONICAL-PATH-SECRET"
    monkeypatch.setenv("AGENT_FLEET_REDACT_VALUES", sentinel)
    fixture_container = build_container(tmp_path / "fixture-state")
    repository = fixture_container.repository.create_canary_fixture(
        tmp_path / "fixture-state" / sentinel / "repository"
    )
    safe_alias = tmp_path / "safe-repository-alias"
    safe_alias.symlink_to(repository, target_is_directory=True)
    state_root = tmp_path / "fleet-state"
    container = build_container(state_root, migrate=False)

    with pytest.raises(FleetError) as captured:
        container.projects._initialize_without_canary(
            safe_alias, runtime_name="fake", sandbox_name="fake"
        )

    assert captured.value.code is ErrorCode.COMMAND_DENIED
    assert sentinel not in str(captured.value)
    assert not (repository / ".fleet").exists()
    assert not state_root.exists()


@pytest.mark.parametrize("operation", ["preview", "initialize"])
def test_bootstrap_rejects_secret_in_raw_path_before_repository_inspection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    sentinel = "FLEET-RAW-PATH-SECRET"
    monkeypatch.setenv("AGENT_FLEET_REDACT_VALUES", sentinel)
    secret_path = tmp_path / f"invalid-{sentinel}"
    state_root = tmp_path / "fleet-state"
    container = build_container(state_root, migrate=False)

    with pytest.raises(FleetError) as captured:
        if operation == "preview":
            container.projects.preview(secret_path)
        else:
            container.projects._initialize_without_canary(
                secret_path, runtime_name="fake", sandbox_name="fake"
            )

    assert captured.value.code is ErrorCode.COMMAND_DENIED
    assert sentinel not in str(captured.value)
    assert not state_root.exists()


@pytest.mark.parametrize("field", ["runtime", "sandbox"])
def test_project_init_rejects_secret_in_adapter_option_without_echo_or_write(
    tmp_path: Path, field: str
) -> None:
    sentinel = "FLEET-ADAPTER-OPTION-SECRET"
    state_root = tmp_path / "fleet-state"
    container = build_container(state_root, migrate=False)
    container.projects.redactor = Redactor([sentinel])

    with pytest.raises(FleetError) as captured:
        container.projects._initialize_without_canary(
            tmp_path,
            runtime_name=sentinel if field == "runtime" else "fake",
            sandbox_name=sentinel if field == "sandbox" else "fake",
        )

    assert captured.value.code is ErrorCode.COMMAND_DENIED
    assert sentinel not in str(captured.value)
    assert not state_root.exists()


def test_bootstrap_rejects_mismatched_profile_hash_before_write(tmp_path: Path) -> None:
    fixture_container = build_container(tmp_path / "fixture-state")
    repository = fixture_container.repository.create_canary_fixture(
        tmp_path / "fixture-state" / "target"
    )
    state_root = tmp_path / "fleet-state"
    container = build_container(state_root, migrate=False)
    container.projects.profiler = MismatchedProfileHashProfiler()

    with pytest.raises(FleetError) as captured:
        container.projects._initialize_without_canary(
            repository, runtime_name="fake", sandbox_name="fake"
        )

    assert captured.value.code is ErrorCode.ARTIFACT_INTEGRITY_FAILED
    assert not (repository / ".fleet").exists()
    assert not state_root.exists()


@pytest.mark.asyncio
async def test_workflow_rejects_secret_in_adapter_option_without_echo_or_run(
    harness: FleetHarness,
) -> None:
    sentinel = "FLEET-WORKFLOW-OPTION-SECRET"
    harness.container.workflow.redactor = Redactor([sentinel])

    with pytest.raises(FleetError) as captured:
        await harness.container.workflow.start(
            project_path=harness.repository_root,
            goal="safe goal",
            runtime_name=sentinel,
            sandbox_name="fake",
            fake_scenario=FakeScenario.SUCCESS,
        )

    assert captured.value.code is ErrorCode.COMMAND_DENIED
    assert sentinel not in str(captured.value)
    with harness.container.state._connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_structured_command_exact_match_rejects_compound_injection(
    harness: FleetHarness,
) -> None:
    harness.container.workflow.runtimes = RuntimeRegistry({"fake": CommandInjectionRuntime()})
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
async def test_runtime_scope_secret_is_rejected_before_task_persistence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sentinel = "FLEET-RUNTIME-SCOPE-SECRET"
    monkeypatch.setenv("AGENT_FLEET_REDACT_VALUES", sentinel)
    fixture_container = build_container(tmp_path / "fixture-state")
    repository = fixture_container.repository.create_canary_fixture(
        tmp_path / "fixture-state" / "target"
    )
    state_root = tmp_path / "fleet-state"
    container = build_container(state_root)
    container.projects._initialize_without_canary(
        repository, runtime_name="fake", sandbox_name="fake"
    )
    container.workflow.runtimes = RuntimeRegistry({"fake": SecretScopeRuntime(sentinel)})

    with pytest.raises(FleetError) as captured:
        await container.workflow.start(
            project_path=repository,
            goal="safe goal",
            runtime_name="fake",
            sandbox_name="fake",
            fake_scenario=FakeScenario.SUCCESS,
        )

    assert captured.value.code is ErrorCode.COMMAND_DENIED
    with container.state._connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0
    for path in state_root.rglob("*"):
        if path.is_file():
            assert sentinel.encode() not in path.read_bytes(), path


@pytest.mark.integration
@pytest.mark.asyncio
async def test_gateway_rejects_secret_before_intent_or_event_persistence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sentinel = "FLEET-RUNTIME-INTENT-SECRET"
    monkeypatch.setenv("AGENT_FLEET_REDACT_VALUES", sentinel)
    fixture_container = build_container(tmp_path / "fixture-state")
    repository = fixture_container.repository.create_canary_fixture(
        tmp_path / "fixture-state" / "target"
    )
    state_root = tmp_path / "fleet-state"
    container = build_container(state_root)
    container.projects._initialize_without_canary(
        repository, runtime_name="fake", sandbox_name="fake"
    )
    run = await container.workflow.start(
        project_path=repository,
        goal="safe goal",
        runtime_name="fake",
        sandbox_name="fake",
        fake_scenario=FakeScenario.SUCCESS,
    )
    assert run.task_id is not None
    task = container.state.get_task(run.task_id)
    agent = AgentInstance(
        agent_instance_id="agent_" + "7" * 32,
        run_id=run.run_id,
        task_id=task.task_id,
        role=AgentRole.ENGINEER,
        status=AgentStatus.RUNNING,
        iteration=0,
        created_at=container.state.clock.now(),
    )
    workspace = Workspace(
        workspace_id="ws_" + "7" * 32,
        run_id=run.run_id,
        kind=WorkspaceKind.CANDIDATE,
        path=str(repository),
        base_revision=run.base_revision,
    )
    handle = SandboxHandle(
        sandbox_id="sandbox_" + "7" * 32,
        run_id=run.run_id,
        workspace_host_path=str(repository),
    )
    action = ScriptedAction(
        action="workspace.write_file",
        resource=CanonicalResource(kind="workspace_path", identifier="src/canary_calc/core.py"),
        parameters={"content": "safe content", f"untrusted-{sentinel}": "value"},
        reason="untrusted runtime output",
        side_effect=True,
        idempotency_key="secret-intent",
    )

    with pytest.raises(FleetError) as captured:
        await container.workflow.gateway.execute(
            run=run,
            task=task,
            agent=agent,
            workspace=workspace,
            sandbox_handle=handle,
            scripted=action,
        )

    assert captured.value.code is ErrorCode.COMMAND_DENIED
    with container.state._connect() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM tool_intents WHERE idempotency_key = ?",
                ("secret-intent",),
            ).fetchone()[0]
            == 0
        )
    for path in state_root.rglob("*"):
        if path.is_file():
            assert sentinel.encode() not in path.read_bytes(), path


@pytest.mark.integration
@pytest.mark.asyncio
async def test_repository_smudge_filter_fails_closed_without_hook_or_filter_execution(
    harness: FleetHarness,
) -> None:
    hook_sentinel = harness.root / "hook-executed"
    filter_sentinel = harness.root / "filter-executed"
    hook = harness.repository_root / ".git" / "hooks" / "post-checkout"
    hook.parent.mkdir(parents=True, exist_ok=True)
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

    with pytest.raises(FleetError) as captured:
        await harness.start(FakeScenario.SUCCESS)

    assert captured.value.code is ErrorCode.CONFIG_INVALID
    assert not hook_sentinel.exists()
    assert not filter_sentinel.exists()
    with harness.container.state._connect() as connection:
        row = connection.execute("SELECT COUNT(*) FROM runs").fetchone()
        assert row is not None
        assert row[0] == 0
