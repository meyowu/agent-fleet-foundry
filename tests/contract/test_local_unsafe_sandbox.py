from __future__ import annotations

from pathlib import Path

import pytest

from agent_fleet.adapters.sandbox.local_unsafe import LocalUnsafeSandboxProvider
from agent_fleet.adapters.sandbox.process import (
    ProcessInvocationError,
    ProcessResult,
    ProcessTerminationError,
)
from agent_fleet.adapters.system import SystemClock, UuidIdGenerator
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import (
    ExecRequest,
    SandboxConfiguration,
    SandboxSecurityLevel,
    SandboxSpec,
    WorkflowStage,
)
from agent_fleet.domain.security import Redactor


class RecordingProcessRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], dict[str, str], str | None]] = []
        self.failure: Exception | None = None

    async def run(
        self,
        argv: tuple[str, ...],
        *,
        environment: dict[str, str],
        cwd: str | None = None,
        timeout_seconds: int,
        max_output_bytes: int,
    ) -> ProcessResult:
        del timeout_seconds, max_output_bytes
        self.calls.append((argv, environment, cwd))
        if self.failure is not None:
            raise self.failure
        return ProcessResult(returncode=0, stdout=b"local diagnostic\n", stderr=b"")


def _provider(
    tmp_path: Path,
    runner: RecordingProcessRunner,
    *,
    redactor: Redactor | None = None,
) -> LocalUnsafeSandboxProvider:
    return LocalUnsafeSandboxProvider(
        runner=runner,
        clock=SystemClock(),
        ids=UuidIdGenerator(),
        state_root=tmp_path / "state",
        redactor=redactor or Redactor(),
    )


def _spec(workspace: Path, *, confirmed: bool) -> SandboxSpec:
    return SandboxSpec(
        workspace_host_path=str(workspace),
        configuration=SandboxConfiguration(
            provider="local-unsafe",
            network_mode="approved-unrestricted",
        ),
        unsafe_local_confirmed=confirmed,
    )


def _request(*, environment: dict[str, str] | None = None) -> ExecRequest:
    return ExecRequest(
        execution_id="exec_" + "1" * 32,
        intent_id="intent_" + "2" * 32,
        task_id="task_" + "3" * 32,
        agent_instance_id="agent_" + "4" * 32,
        stage=WorkflowStage.IMPLEMENTING,
        executable="true",
        argv=["literal;touch", "/tmp/must-not-run"],
        cwd="src",
        environment=environment or {},
        network_mode="approved-unrestricted",
        command_spec_hash="5" * 64,
    )


@pytest.mark.asyncio
async def test_local_unsafe_requires_separate_confirmation_before_execution(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingProcessRunner()
    provider = _provider(tmp_path, runner)

    with pytest.raises(FleetError) as captured:
        await provider.create("run_" + "6" * 32, _spec(workspace, confirmed=False))

    assert captured.value.code is ErrorCode.UNSAFE_LOCAL_CONFIRMATION_REQUIRED
    assert runner.calls == []


@pytest.mark.asyncio
async def test_local_unsafe_reports_host_risk_and_uses_direct_argv_in_workspace(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "candidate"
    (workspace / "src").mkdir(parents=True)
    runner = RecordingProcessRunner()
    provider = _provider(tmp_path, runner)
    handle = await provider.create(
        "run_" + "6" * 32,
        _spec(workspace, confirmed=True),
        sandbox_id="sandbox_" + "7" * 32,
    )

    inspection = await provider.inspect(handle)
    result = await provider.exec(handle, _request(environment={"CI": "1"}))

    assert provider.capabilities.security_level is SandboxSecurityLevel.UNSAFE_HOST
    assert provider.capabilities.isolation_enforced is False
    assert provider.capabilities.supported_network_modes == ("approved-unrestricted",)
    assert inspection.effective_network_mode == "approved-unrestricted"
    assert result.exit_code == 0
    assert result.execution is not None
    assert result.execution.provider == "local-unsafe"
    assert len(runner.calls) == 1
    argv, environment, cwd = runner.calls[0]
    assert Path(argv[0]).name == "true"
    assert argv[1:] == ("literal;touch", "/tmp/must-not-run")
    assert cwd == str((workspace / "src").resolve())
    assert environment["CI"] == "1"
    assert "PATH" in environment


@pytest.mark.asyncio
async def test_local_unsafe_rejects_registered_secret_environment(
    tmp_path: Path,
) -> None:
    sentinel = "LOCAL-UNSAFE-SECRET-SENTINEL"
    workspace = tmp_path / "candidate"
    (workspace / "src").mkdir(parents=True)
    runner = RecordingProcessRunner()
    provider = _provider(tmp_path, runner, redactor=Redactor([sentinel]))
    handle = await provider.create("run_" + "6" * 32, _spec(workspace, confirmed=True))

    with pytest.raises(FleetError) as captured:
        await provider.exec(handle, _request(environment={"CI": sentinel}))

    assert captured.value.code is ErrorCode.COMMAND_DENIED
    assert sentinel not in str(captured.value)
    assert runner.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "expected_code"),
    [
        (
            ProcessInvocationError("trusted subprocess could not be invoked"),
            ErrorCode.SANDBOX_EXECUTION_FAILED,
        ),
        (
            ProcessTerminationError("trusted subprocess termination was not proven"),
            ErrorCode.SANDBOX_CLEANUP_FAILED,
        ),
    ],
)
async def test_local_unsafe_maps_typed_process_failures(
    tmp_path: Path,
    failure: Exception,
    expected_code: ErrorCode,
) -> None:
    workspace = tmp_path / "candidate"
    (workspace / "src").mkdir(parents=True)
    runner = RecordingProcessRunner()
    runner.failure = failure
    provider = _provider(tmp_path, runner)
    handle = await provider.create("run_" + "6" * 32, _spec(workspace, confirmed=True))

    with pytest.raises(FleetError) as captured:
        await provider.exec(handle, _request())

    assert captured.value.code is expected_code
