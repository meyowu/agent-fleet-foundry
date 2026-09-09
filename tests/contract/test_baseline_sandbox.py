"""Actual Docker adapter with an offline argv/inspection transport; no Docker daemon."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from business_baseline_fixtures import baseline_fixture

if TYPE_CHECKING:
    from test_docker_sandbox import (
        _CONTAINER_ID,
        _DAEMON_IDENTITY,
        RecordingDockerRunner,
        _option_values,
    )
else:
    from contract.test_docker_sandbox import (
        _CONTAINER_ID,
        _DAEMON_IDENTITY,
        RecordingDockerRunner,
        _option_values,
    )

from agent_fleet.adapters.sandbox.docker import DockerSandboxProvider
from agent_fleet.adapters.sandbox.process import ProcessResult
from agent_fleet.adapters.system import SystemClock, UuidIdGenerator
from agent_fleet.domain.baseline import baseline_id, canonical, freeze_sandbox, reconstruct_sandbox
from agent_fleet.domain.baseline_resources import (
    BaselineExecRequest,
    BaselineExecutionHandle,
    BaselineExecutionRecoveryRequest,
    BaselineSandboxSpec,
    baseline_labels,
)
from agent_fleet.domain.errors import FleetError
from agent_fleet.domain.security import Redactor


class BaselineRecordingRunner(RecordingDockerRunner):
    """Derive effective limits from argv while retaining the existing hostile controls."""

    def _container_inspection(self) -> dict[str, object]:
        inspected = super()._container_inspection()
        assert self.create_argv is not None
        host = inspected["HostConfig"]
        assert isinstance(host, dict)
        host["PidsLimit"] = int(_option_values(self.create_argv, "--pids-limit")[0])
        host["Memory"] = int(_option_values(self.create_argv, "--memory")[0][:-1]) * 1024 * 1024
        host["MemorySwap"] = host["Memory"]
        host["ShmSize"] = int(_option_values(self.create_argv, "--shm-size")[0][:-1]) * 1024 * 1024
        host["Tmpfs"] = {
            value.split(":", 1)[0]: value.split(":", 1)[1]
            for value in _option_values(self.create_argv, "--tmpfs")
        }
        state = inspected["State"]
        assert isinstance(state, dict)
        state["ExitCode"] = self.start_returncode
        return inspected

    async def run(
        self,
        argv: tuple[str, ...],
        *,
        environment: dict[str, str],
        cwd: str | None = None,
        timeout_seconds: int,
        max_output_bytes: int,
    ) -> ProcessResult:
        result = await super().run(
            argv,
            environment=environment,
            cwd=cwd,
            timeout_seconds=timeout_seconds,
            max_output_bytes=max_output_bytes,
        )
        if argv[1:3] == ("container", "create") and not result.timed_out:
            self.listed_ids = [_CONTAINER_ID]
        if argv[1:3] == ("container", "rm") and result.returncode == 0:
            self.listed_ids = []
        return result


def transport_fixture(
    tmp_path: Path,
) -> tuple[
    DockerSandboxProvider, BaselineRecordingRunner, BaselineSandboxSpec, BaselineExecRequest
]:
    h = baseline_fixture(tmp_path)
    workspace = Path(h.spec.workspace.path)
    workspace.mkdir(parents=True)
    runner = BaselineRecordingRunner(workspace, tmp_path / "shadow")
    provider = DockerSandboxProvider(
        runner=runner,
        clock=SystemClock(),
        ids=UuidIdGenerator(),
        redactor=Redactor(),
        docker_executable="/usr/bin/docker",
        installation_id=h.review.installation_id,
        git_shadow_path=tmp_path / "shadow",
        uid=1000,
        gid=1000,
    )
    local = reconstruct_sandbox(h.spec.sandbox).model_dump(mode="json")
    local["daemon_identity"] = _DAEMON_IDENTITY
    spec = BaselineSandboxSpec(
        owner=h.spec.owner, workspace=h.spec.workspace, sandbox=freeze_sandbox(canonical(local))
    )
    request = BaselineExecRequest(
        owner=h.spec.owner,
        claim_id=baseline_id("bclaim"),
        execution_id=baseline_id("bexec"),
        workspace_id=spec.workspace.workspace_id,
        command=h.review.command,
    )
    return provider, runner, spec, request


@pytest.mark.asyncio
async def test_readonly_baseline_argv_inspection_and_exact_cleanup(tmp_path: Path) -> None:
    provider, runner, spec, request = transport_fixture(tmp_path)
    handle = await provider.create_baseline(spec, sandbox_id=baseline_id("bsandbox"))
    callbacks: list[str] = []
    native: list[BaselineExecutionHandle] = []

    def created(value: BaselineExecutionHandle) -> None:
        callbacks.append("native")
        native.append(value)

    result = await provider.exec_baseline(
        handle,
        request,
        on_creation_dispatched=lambda: callbacks.append("creation"),
        on_resource_created=created,
    )
    assert callbacks == ["creation", "native"]
    assert result.exit_code == 0 and result.stdout == b"verification passed\n"
    assert result.metadata.inspection.workspace_read_only
    assert native == [result.metadata.handle]
    assert result.metadata.request_sha256 == request.digest
    assert runner.create_argv is not None
    assert "--network=none" in runner.create_argv
    mounts = _option_values(runner.create_argv, "--mount")
    assert all("readonly" in item.split(",") for item in mounts)
    assert all("agent-fleet.run=" not in item for item in runner.create_argv)
    with pytest.raises(FleetError):
        await provider.exec_baseline(
            handle, request, on_creation_dispatched=lambda: None, on_resource_created=lambda _: None
        )
    cleanup = await provider.cleanup_baseline_execution(native[0])
    assert cleanup.complete and cleanup.resources_removed == 1
    logical = await provider.terminate_baseline(handle)
    assert logical.complete
    assert runner.listed_ids == []


@pytest.mark.parametrize("mutation", ["extra_mount", "name", "label_run", "readonly_root_int"])
@pytest.mark.asyncio
async def test_baseline_inspection_rejects_hostile_controls_before_start(
    tmp_path: Path, mutation: str
) -> None:
    provider, runner, spec, request = transport_fixture(tmp_path)
    handle = await provider.create_baseline(spec, sandbox_id=baseline_id("bsandbox"))
    runner.inspection_mutation = mutation
    try:
        with pytest.raises(FleetError):
            await provider.exec_baseline(
                handle,
                request,
                on_creation_dispatched=lambda: None,
                on_resource_created=lambda _: None,
            )
        assert not any(argv[1:3] == ("container", "start") for argv, _ in runner.calls)
    finally:
        runner.inspection_mutation = None
        # Test-only provider-local cleanup uses the exact observed label/native pair.
        # If the create result never reached its callback it remains unknown to a store.
        runner.listed_ids = []
        await provider.terminate_baseline(handle)


@pytest.mark.parametrize("boundary", ["creation", "native"])
async def test_failed_creation_callbacks_never_start_or_repeat(
    tmp_path: Path, boundary: str
) -> None:
    provider, runner, spec, request = transport_fixture(tmp_path)
    handle = await provider.create_baseline(spec, sandbox_id=baseline_id("bsandbox"))
    calls: list[str] = []

    def creation() -> None:
        calls.append("creation")
        if boundary == "creation":
            raise RuntimeError("controlled test callback failure")

    def native(_: BaselineExecutionHandle) -> None:
        calls.append("native")
        raise RuntimeError("controlled test callback failure")

    with pytest.raises(RuntimeError):
        await provider.exec_baseline(
            handle, request, on_creation_dispatched=creation, on_resource_created=native
        )
    assert calls == (["creation"] if boundary == "creation" else ["creation", "native"])
    assert sum(argv[1:3] == ("container", "create") for argv, _ in runner.calls) == (
        0 if boundary == "creation" else 1
    )
    assert not any(argv[1:3] == ("container", "start") for argv, _ in runner.calls)
    assert runner.listed_ids == []
    count = len(runner.calls)
    with pytest.raises(FleetError):
        await provider.exec_baseline(
            handle, request, on_creation_dispatched=lambda: None, on_resource_created=lambda _: None
        )
    assert len(runner.calls) == count
    assert (await provider.terminate_baseline(handle)).complete


@pytest.mark.parametrize("damage", ["workspace_rw", "image", "memory", "tmpfs", "command"])
async def test_baseline_exact_effective_controls_cannot_be_substituted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, damage: str
) -> None:
    provider, runner, spec, request = transport_fixture(tmp_path)
    handle = await provider.create_baseline(spec, sandbox_id=baseline_id("bsandbox"))
    original = runner._container_inspection

    def inspection() -> dict[str, object]:
        data = original()
        if damage == "workspace_rw":
            mounts = data["Mounts"]
            assert isinstance(mounts, list)
            next(item for item in mounts if item["Destination"] == "/workspace")["RW"] = True
        elif damage == "image":
            data["Image"] = "sha256:" + "9" * 64
        elif damage == "command":
            config = data["Config"]
            assert isinstance(config, dict)
            config["Cmd"] = ["unreviewed"]
        else:
            host = data["HostConfig"]
            assert isinstance(host, dict)
            if damage == "memory":
                host["Memory"] = 0
            else:
                host["Tmpfs"] = {"/tmp": "rw,exec,size=512m"}
        return data

    with monkeypatch.context() as scoped:
        scoped.setattr(runner, "_container_inspection", inspection)
        with pytest.raises(FleetError):
            await provider.exec_baseline(
                handle,
                request,
                on_creation_dispatched=lambda: None,
                on_resource_created=lambda _: None,
            )
    assert not any(argv[1:3] == ("container", "start") for argv, _ in runner.calls)
    # This runner is a synthetic transport. No absence of a physical container is claimed.
    runner.listed_ids = []
    assert (await provider.terminate_baseline(handle)).complete


@pytest.mark.parametrize("created,matches", [(False, 0), (True, 0), (True, 2)])
async def test_unknown_create_reconciliation_never_invents_absence_or_sweeps_matches(
    tmp_path: Path, created: bool, matches: int
) -> None:
    provider, runner, spec, request = transport_fixture(tmp_path)
    handle = await provider.create_baseline(spec, sandbox_id=baseline_id("bsandbox"))
    runner.listed_ids = [_CONTAINER_ID, "8" * 64][:matches]
    recovery = BaselineExecutionRecoveryRequest(
        request=request,
        sandbox=handle,
        creation_dispatched=created,
        expected_labels=baseline_labels(handle, request),
    )
    if matches:
        with pytest.raises(FleetError):
            await provider.reconcile_baseline_execution(handle, recovery)
    else:
        result = await provider.reconcile_baseline_execution(handle, recovery)
        assert result.complete is (not created)
        assert result.resources_found == result.resources_removed == 0
    assert not any(
        argv[1:3] in {("container", "rm"), ("container", "start"), ("container", "create")}
        for argv, _ in runner.calls
    )
    runner.listed_ids = []
    assert (await provider.terminate_baseline(handle)).complete
