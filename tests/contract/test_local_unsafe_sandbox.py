from __future__ import annotations

import asyncio
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
    SandboxHandle,
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
@pytest.mark.parametrize("retained", [True, False])
async def test_local_unsafe_restores_only_exact_explicitly_confirmed_context(
    tmp_path: Path,
    retained: bool,
) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingProcessRunner()
    original = _provider(tmp_path, runner)
    spec = _spec(workspace, confirmed=True)
    handle = await original.create("run_" + "6" * 32, spec)
    provider = original if retained else _provider(tmp_path, runner)
    retained_handle = original._handles[handle.sandbox_id] if retained else None

    restored = await provider.restore(handle, spec)

    assert restored == handle
    assert provider._handles[handle.sandbox_id] == handle
    if retained_handle is not None:
        assert provider._handles[handle.sandbox_id] is retained_handle
    with pytest.raises(FleetError) as captured:
        await provider.restore(
            handle,
            spec.model_copy(update={"unsafe_local_confirmed": False}),
        )
    assert captured.value.code in {
        ErrorCode.UNSAFE_LOCAL_CONFIRMATION_REQUIRED,
        ErrorCode.SANDBOX_INSPECTION_FAILED,
    }
    assert runner.calls == []


@pytest.mark.asyncio
async def test_local_unsafe_absent_restore_cannot_overwrite_second_await_competitor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingProcessRunner()
    source = _provider(tmp_path, runner)
    spec = _spec(workspace, confirmed=True)
    handle = await source.create(
        "run_" + "1" * 32,
        spec,
        sandbox_id="sandbox_" + "2" * 32,
    )
    provider = _provider(tmp_path, runner)
    original_to_thread = asyncio.to_thread
    second_await_entered = asyncio.Event()
    second_await_release = asyncio.Event()
    restore_calls = 0
    restoration: asyncio.Task[SandboxHandle] | None = None

    async def expose_second_await(
        function: object,
        *args: object,
        **kwargs: object,
    ) -> object:
        nonlocal restore_calls
        if asyncio.current_task() is restoration:
            restore_calls += 1
            if restore_calls == 2:
                second_await_entered.set()
                await second_await_release.wait()
        return await original_to_thread(function, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(asyncio, "to_thread", expose_second_await)
    restoration = asyncio.create_task(provider.restore(handle, spec))
    second_wait = asyncio.create_task(second_await_entered.wait())
    try:
        done, _pending = await asyncio.wait(
            {restoration, second_wait},
            timeout=5,
            return_when=asyncio.FIRST_COMPLETED,
        )
        assert done, "restore neither completed nor exposed a second publication await"
        if second_wait in done:
            competing = await provider.create(
                "run_" + "8" * 32,
                spec,
                sandbox_id=handle.sandbox_id,
            )
            live_handle = provider._handles[handle.sandbox_id]
            live_spec = provider._specs[handle.sandbox_id]
            second_await_release.set()
            with pytest.raises(FleetError):
                await restoration
            assert provider._handles[handle.sandbox_id] is live_handle
            assert provider._specs[handle.sandbox_id] is live_spec
            assert live_handle == competing
        else:
            second_wait.cancel()
            restored = await restoration
            assert restored == handle and restore_calls == 1
            live_handle = provider._handles[handle.sandbox_id]
            live_spec = provider._specs[handle.sandbox_id]
            with pytest.raises(FleetError) as duplicate:
                await provider.create(
                    "run_" + "8" * 32,
                    spec,
                    sandbox_id=handle.sandbox_id,
                )
            assert duplicate.value.code is ErrorCode.SANDBOX_CREATION_FAILED
            assert provider._handles[handle.sandbox_id] is live_handle
            assert provider._specs[handle.sandbox_id] is live_spec
    finally:
        second_await_release.set()
        second_wait.cancel()
        await asyncio.gather(second_wait, return_exceptions=True)
        if not restoration.done():
            restoration.cancel()
            await asyncio.gather(restoration, return_exceptions=True)

    assert runner.calls == []


@pytest.mark.asyncio
async def test_local_unsafe_restore_rejects_foreign_creation_during_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingProcessRunner()
    source = _provider(tmp_path, runner)
    spec = _spec(workspace, confirmed=True)
    handle = await source.create(
        "run_" + "1" * 32,
        spec,
        sandbox_id="sandbox_" + "2" * 32,
    )
    provider = _provider(tmp_path, runner)
    original_to_thread = asyncio.to_thread
    validation_entered = asyncio.Event()
    validation_release = asyncio.Event()
    restoration: asyncio.Task[SandboxHandle] | None = None

    async def block_restore_validation(
        function: object,
        *args: object,
        **kwargs: object,
    ) -> object:
        if asyncio.current_task() is restoration:
            validation_entered.set()
            await validation_release.wait()
        return await original_to_thread(function, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(asyncio, "to_thread", block_restore_validation)
    restoration = asyncio.create_task(provider.restore(handle, spec))
    try:
        await asyncio.wait_for(validation_entered.wait(), timeout=5)
        competing = await provider.create(
            "run_" + "8" * 32,
            spec,
            sandbox_id=handle.sandbox_id,
        )
        live_handle = provider._handles[handle.sandbox_id]
        live_spec = provider._specs[handle.sandbox_id]
        validation_release.set()
        with pytest.raises(FleetError) as captured:
            await restoration
    finally:
        validation_release.set()
        if not restoration.done():
            restoration.cancel()
            await asyncio.gather(restoration, return_exceptions=True)

    assert captured.value.code is ErrorCode.SANDBOX_INSPECTION_FAILED
    assert provider._handles[handle.sandbox_id] is live_handle
    assert provider._specs[handle.sandbox_id] is live_spec
    assert live_handle == competing
    assert runner.calls == []


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
