from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest
import yaml

from agent_fleet.adapters.sandbox.docker import DockerSandboxProvider
from agent_fleet.adapters.sandbox.process import ProcessResult, ProcessRunner
from agent_fleet.application.sandboxes import requirements_for_configuration
from agent_fleet.bootstrap import ApplicationContainer, build_container
from agent_fleet.domain.bootstrap import BootstrapPolicyMode
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.evidence import CommandEvidence, EvidenceStrength
from agent_fleet.domain.ids import IdPrefix
from agent_fleet.domain.models import (
    ApprovalChoice,
    ExecRequest,
    FakeScenario,
    LeaseKind,
    LeaseStatus,
    ResourceLease,
    Run,
    RunStatus,
    SandboxConfiguration,
    SandboxExecutionHandle,
    SandboxExecutionRecoveryRequest,
    SandboxHandle,
    SandboxPreflight,
    SandboxSpec,
    WorkflowStage,
    Workspace,
    WorkspaceKind,
)
from agent_fleet.domain.offline_canary import (
    BOOTSTRAP_HOST_SENTINEL_NAME,
    BOOTSTRAP_SANDBOX_PROBE_MARKER,
)
from agent_fleet.domain.security import canonical_json_hash
from agent_fleet.domain.trust import TrustMode

pytestmark = [pytest.mark.docker_integration, pytest.mark.asyncio]

_EXECUTION_LABEL_NAMES = {
    "agent-fleet.agent",
    "agent-fleet.daemon",
    "agent-fleet.execution",
    "agent-fleet.installation",
    "agent-fleet.intent",
    "agent-fleet.managed",
    "agent-fleet.project",
    "agent-fleet.run",
    "agent-fleet.sandbox",
    "agent-fleet.stage",
    "agent-fleet.task",
}


@dataclass(frozen=True)
class _PersistentRecoveryFixture:
    container: ApplicationContainer
    provider: DockerSandboxProvider
    state_root: Path
    target: Path
    run: Run
    workspace: Workspace
    sandbox: SandboxHandle
    preflight: SandboxPreflight


@dataclass
class _RecordingDelegate:
    delegate: ProcessRunner
    calls: list[tuple[str, ...]]

    async def run(
        self,
        argv: tuple[str, ...],
        *,
        environment: dict[str, str],
        cwd: str | None = None,
        timeout_seconds: int,
        max_output_bytes: int,
    ) -> ProcessResult:
        self.calls.append(argv)
        return await self.delegate.run(
            argv,
            environment=environment,
            cwd=cwd,
            timeout_seconds=timeout_seconds,
            max_output_bytes=max_output_bytes,
        )


def _record_docker_calls(
    container: ApplicationContainer,
) -> tuple[DockerSandboxProvider, list[tuple[str, ...]]]:
    provider = container.sandboxes.get("docker")
    assert isinstance(provider, DockerSandboxProvider)
    calls: list[tuple[str, ...]] = []
    provider.runner = _RecordingDelegate(provider.runner, calls)
    return provider, calls


async def _raw_inspect(
    provider: DockerSandboxProvider,
    container_id: str,
) -> dict[str, Any]:
    inspected = await provider._call(
        (provider._require_executable(), "container", "inspect", container_id),
        timeout_seconds=30,
        max_output_bytes=1_000_000,
    )
    assert inspected.returncode == 0
    assert not inspected.timed_out
    assert not inspected.output_truncated
    payload = json.loads(inspected.stdout)
    assert isinstance(payload, list) and len(payload) == 1
    assert isinstance(payload[0], dict)
    return cast(dict[str, Any], payload[0])


async def _cleanup_real_installation_scope(
    provider: DockerSandboxProvider,
    installation_id: str,
) -> None:
    """Failure-safe cleanup that still refuses any weakly identified container."""

    # A rejected TCP/SSH context must not be contacted by emergency cleanup. If
    # preflight never pinned both the local Unix endpoint and daemon identity,
    # Docker could not have created a managed resource through this provider.
    if provider._docker_host is None or provider._docker_daemon_identity is None:
        return
    executable = provider._require_executable()
    await provider._require_local_linux_daemon(
        executable,
        expected_identity=provider._docker_daemon_identity,
    )
    for container_id in await provider._list_exact(
        executable,
        {"agent-fleet.installation": installation_id},
    ):
        assert re.fullmatch(r"[0-9a-f]{64}", container_id)
        inspected = await _raw_inspect(provider, container_id)
        configuration = inspected.get("Config")
        assert isinstance(configuration, dict)
        labels = configuration.get("Labels")
        assert isinstance(labels, dict)
        assert set(labels) == _EXECUTION_LABEL_NAMES
        assert labels["agent-fleet.installation"] == installation_id
        assert labels["agent-fleet.managed"] == "true"
        execution_id = labels["agent-fleet.execution"]
        assert re.fullmatch(r"exec_[0-9a-f]{32}", execution_id)
        assert inspected.get("Id") == container_id
        assert inspected.get("Name") == f"/agent-fleet-{execution_id}"
        await provider._remove_exact(executable, container_id, labels, force=True)


def _assert_raw_hardened_container(
    inspected: dict[str, Any],
    *,
    container_id: str,
    image_identity: str,
    workspace: Path,
    git_shadow: Path,
    request: ExecRequest,
    labels: dict[str, str],
    forbidden_values: tuple[str, ...] = (),
) -> None:
    configuration = inspected["Config"]
    host = inspected["HostConfig"]
    mounts = inspected["Mounts"]
    assert isinstance(configuration, dict)
    assert isinstance(host, dict)
    assert isinstance(mounts, list)
    assert inspected["Id"] == container_id
    assert inspected["Name"] == f"/agent-fleet-{request.execution_id}"
    assert inspected["Image"] == image_identity
    assert configuration["Image"] == image_identity
    assert configuration["User"] == f"{os.getuid()}:{os.getgid()}"
    assert configuration["Entrypoint"] == [request.executable]
    assert configuration["Cmd"] == list(request.argv)
    assert configuration["WorkingDir"] == "/workspace"
    assert configuration["Labels"] == labels
    assert configuration["Healthcheck"]["Test"] == ["NONE"]
    assert configuration["StopTimeout"] == 1
    assert not configuration.get("ExposedPorts")
    environment_entries = configuration["Env"]
    assert isinstance(environment_entries, list)
    environment = dict(item.split("=", 1) for item in environment_entries)
    assert environment == {
        "HOME": "/tmp/home",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": "/usr/local/bin:/usr/bin:/bin",
    }
    serialized_inspection = json.dumps(inspected, sort_keys=True)
    assert all(value not in serialized_inspection for value in forbidden_values)

    security_options = set(host["SecurityOpt"])
    assert security_options in (
        {"no-new-privileges", "seccomp=builtin"},
        {"no-new-privileges=true", "seccomp=builtin"},
    )
    assert host["NetworkMode"] == "none"
    assert host["CapDrop"] == ["ALL"]
    assert not host.get("CapAdd")
    assert host["ReadonlyRootfs"] is True
    assert host["Privileged"] is False
    assert host["PidsLimit"] == 128
    assert host["NanoCpus"] == 1_000_000_000
    assert host["Memory"] == 512 * 1024 * 1024
    assert host["MemorySwap"] == 512 * 1024 * 1024
    assert host["MemorySwappiness"] in {None, 0}
    assert host["ShmSize"] == 64 * 1024 * 1024
    assert host["RestartPolicy"]["Name"] == "no"
    assert host["LogConfig"]["Type"] == "none"
    assert host["Ulimits"] == [{"Name": "nofile", "Soft": 1024, "Hard": 1024}]
    assert host["IpcMode"] == "private"
    assert host["CgroupnsMode"] == "private"
    assert not host.get("PidMode")
    assert not host.get("UsernsMode")
    assert not host.get("UTSMode")
    assert not host.get("GroupAdd")
    assert not host.get("DeviceCgroupRules")
    assert not host.get("VolumesFrom")
    assert host["Init"] is True
    assert not host.get("Devices")
    assert not host.get("DeviceRequests")
    assert not host.get("PortBindings")
    assert host["PublishAllPorts"] is False
    assert host["AutoRemove"] is False

    expected_mounts = {
        (str(workspace.resolve()), "/workspace", True, "rprivate"),
        (str(git_shadow.resolve()), "/workspace/.git", False, "rprivate"),
    }
    actual_mounts = {
        (
            item["Source"],
            item["Destination"],
            item["RW"],
            item.get("Propagation") or "rprivate",
        )
        for item in mounts
    }
    assert actual_mounts == expected_mounts
    tmpfs = host["Tmpfs"]
    assert set(tmpfs) == {"/tmp", "/cache"}
    for options in tmpfs.values():
        assert set(options.split(",")) == {
            "rw",
            "noexec",
            "nosuid",
            "nodev",
            "size=134217728",
        }


async def _prepared_provider(
    tmp_path: Path,
    image: str,
) -> tuple[DockerSandboxProvider, SandboxHandle, Path, SandboxPreflight]:
    container = build_container(tmp_path / "state")
    provider = container.sandboxes.get("docker")
    assert isinstance(provider, DockerSandboxProvider)
    configuration = SandboxConfiguration(provider="docker", image=image)
    requirements = requirements_for_configuration(configuration)
    preflight = await provider.preflight(configuration, requirements)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".git").write_text("sensitive-host-gitdir\n", encoding="utf-8")
    handle = await provider.create(
        "run_" + uuid4().hex,
        SandboxSpec(
            workspace_host_path=str(workspace),
            project_id="prj_" + uuid4().hex,
            configuration=configuration,
            requirements=requirements,
            image_identity=preflight.image_identity,
            daemon_identity=preflight.daemon_identity,
        ),
        sandbox_id="sandbox_" + uuid4().hex,
    )
    return provider, handle, workspace, preflight


def _request(
    suffix: str,
    code: str,
    *,
    argv: list[str] | None = None,
    timeout_seconds: int = 15,
    max_output_bytes: int = 64_000,
) -> ExecRequest:
    del suffix
    nonce = uuid4().hex
    return ExecRequest(
        execution_id="exec_" + nonce,
        intent_id="intent_" + nonce,
        task_id="task_" + nonce,
        agent_instance_id="agent_" + nonce,
        stage=WorkflowStage.VERIFYING,
        executable="python",
        argv=["-B", "-c", code, *(argv or [])],
        cwd=".",
        timeout_seconds=timeout_seconds,
        max_output_bytes=max_output_bytes,
        command_spec_hash=nonce * 2,
    )


def _recovery_request(
    handle: SandboxHandle,
    request: ExecRequest,
) -> SandboxExecutionRecoveryRequest:
    return SandboxExecutionRecoveryRequest(
        execution_id=cast(str, request.execution_id),
        sandbox_id=handle.sandbox_id,
        run_id=handle.run_id,
        project_id=cast(str, handle.project_id),
        provider="docker",
        intent_id=cast(str, request.intent_id),
        task_id=cast(str, request.task_id),
        agent_instance_id=cast(str, request.agent_instance_id),
        stage=cast(WorkflowStage, request.stage),
        creation_dispatched=True,
    )


async def _persistent_recovery_fixture(
    tmp_path: Path,
    image: str,
) -> _PersistentRecoveryFixture:
    state_root = tmp_path / "fleet-state"
    container = build_container(state_root)
    provider = container.sandboxes.get("docker")
    assert isinstance(provider, DockerSandboxProvider)
    configuration = SandboxConfiguration(provider="docker", image=image)
    requirements = requirements_for_configuration(configuration)
    preflight = await provider.preflight(configuration, requirements)
    fixture_container = build_container(tmp_path / "fixture-state")
    target = fixture_container.repository.create_canary_fixture(
        tmp_path / "fixture-state" / "target"
    )
    container.projects._initialize_without_canary(
        target,
        runtime_name="fake",
        sandbox_name="docker",
        docker_image=image,
        create_canary_fixture=False,
        sandbox_image_identity=preflight.image_identity,
        sandbox_daemon_identity=preflight.daemon_identity,
    )
    project = container.state.get_project_by_root(str(target.resolve()))
    assert project is not None
    repository_info = container.repository.inspect(target)
    now = datetime.now(UTC)
    run = Run(
        run_id=container.state.ids.new(IdPrefix.RUN),
        project_id=project.project_id,
        correlation_id=container.state.ids.new(IdPrefix.CORRELATION),
        goal="real Docker persistent recovery",
        base_revision=repository_info.head_revision,
        target_status_fingerprint=repository_info.status_fingerprint,
        sandbox_name="docker",
        sandbox_configuration=configuration,
        sandbox_requirements=requirements,
        sandbox_capabilities_snapshot=provider.capabilities,
        sandbox_image_identity=preflight.image_identity,
        sandbox_daemon_identity=preflight.daemon_identity,
        status=RunStatus.RUNNING,
        stage=WorkflowStage.VERIFYING,
        created_at=now,
        updated_at=now,
    )
    container.state.create_run(run)
    workspace = container.repository.create_workspace(
        target,
        run.run_id,
        run.base_revision,
        WorkspaceKind.CANDIDATE,
    )
    resources = container.recovery.resources
    resources.lease_workspace(workspace)
    sandbox = await resources.create_sandbox(
        run.run_id,
        SandboxSpec(
            workspace_host_path=workspace.path,
            project_id=project.project_id,
            configuration=configuration,
            requirements=requirements,
            image_identity=preflight.image_identity,
            daemon_identity=preflight.daemon_identity,
        ),
    )
    return _PersistentRecoveryFixture(
        container=container,
        provider=provider,
        state_root=state_root,
        target=target,
        run=run,
        workspace=workspace,
        sandbox=sandbox,
        preflight=preflight,
    )


def _save_execution_lease(
    fixture: _PersistentRecoveryFixture,
    request: ExecRequest,
    *,
    creation_dispatched: bool,
) -> ResourceLease:
    now = datetime.now(UTC)
    state = fixture.container.state
    lease = ResourceLease(
        lease_id=state.ids.new(IdPrefix.LEASE),
        run_id=fixture.run.run_id,
        kind=LeaseKind.EXECUTION,
        resource_id=cast(str, request.execution_id),
        status=LeaseStatus.CREATING,
        created_at=now,
        updated_at=now,
        metadata={
            "schema_version": 2,
            "provider": "docker",
            "intent_id": cast(str, request.intent_id),
            "project_id": cast(str, fixture.sandbox.project_id),
            "task_id": cast(str, request.task_id),
            "agent_instance_id": cast(str, request.agent_instance_id),
            "stage": cast(WorkflowStage, request.stage).value,
            "creation_dispatched": False,
            "sandbox_handle": fixture.sandbox.model_dump(mode="json"),
        },
    )
    state.save_lease(lease)
    if creation_dispatched:
        return state.mark_execution_creation_dispatched(lease.lease_id)
    return lease


async def _create_raw_orphan(
    fixture: _PersistentRecoveryFixture,
    request: ExecRequest,
) -> SandboxExecutionHandle:
    provider = fixture.provider
    labels = provider._labels(fixture.sandbox, request)
    prepared = provider._prepared[fixture.sandbox.sandbox_id]
    created = await provider._call(
        provider._container_create_argv(
            provider._require_executable(),
            prepared,
            request,
            f"agent-fleet-{request.execution_id}",
            labels,
        ),
        timeout_seconds=30,
        max_output_bytes=4096,
    )
    assert created.returncode == 0
    container_id = created.stdout.decode().strip()
    assert re.fullmatch(r"[0-9a-f]{64}", container_id)
    inspection = await _raw_inspect(provider, container_id)
    _assert_raw_hardened_container(
        inspection,
        container_id=container_id,
        image_identity=fixture.preflight.image_identity or "",
        workspace=Path(fixture.workspace.path),
        git_shadow=provider.git_shadow_path,
        request=request,
        labels=labels,
    )
    return SandboxExecutionHandle(
        execution_id=cast(str, request.execution_id),
        sandbox_id=fixture.sandbox.sandbox_id,
        run_id=fixture.run.run_id,
        provider="docker",
        native_resource_id=container_id,
        labels=labels,
        labels_sha256=canonical_json_hash(labels),
    )


async def test_real_docker_enforces_isolation_and_removes_every_container(
    tmp_path: Path,
    real_docker_image: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret_name = "AGENT_FLEET_TEST_PROVIDER_SECRET"
    monkeypatch.setenv(secret_name, "registered-host-secret")
    monkeypatch.setenv("AGENT_FLEET_REDACT_VALUES", "registered-host-secret")
    provider, handle, workspace, preflight = await _prepared_provider(
        tmp_path,
        real_docker_image,
    )
    sentinel = tmp_path / "outside-workspace-sentinel"
    sentinel.write_text("host-only-secret\n", encoding="utf-8")
    probe = """
import json
import hashlib
import os
from pathlib import Path
import socket
import sys

checks = {}
checks["non_root"] = os.getuid() != 0 and os.getgid() != 0
checks["secret_name_absent"] = "AGENT_FLEET_TEST_PROVIDER_SECRET" not in os.environ
checks["environment_names_allowlisted"] = set(os.environ) <= {
    "HOME", "HOSTNAME", "LANG", "LC_ALL", "PATH"
}
hostname = os.environ.get("HOSTNAME", "")
checks["hostname_bounded"] = 1 <= len(hostname) <= 64 and all(
    character.isalnum() or character in "_.-" for character in hostname
)
secret_digest = sys.argv[2]
checks["secret_value_absent"] = all(
    hashlib.sha256(value.encode()).hexdigest() != secret_digest
    for value in os.environ.values()
)
checks["docker_socket_absent"] = not Path("/var/run/docker.sock").exists()
checks["host_sentinel_hidden"] = not Path(sys.argv[1]).exists()
git_shadow = Path("/workspace/.git")
checks["git_shadowed"] = git_shadow.is_file() and git_shadow.read_bytes() == b""
try:
    Path("/agent-fleet-root-write").write_text("no", encoding="utf-8")
except OSError:
    checks["root_read_only"] = True
else:
    checks["root_read_only"] = False
Path("/workspace/probe.txt").write_text("workspace-write-ok\\n", encoding="utf-8")
checks["workspace_writable"] = Path("/workspace/probe.txt").read_text() == "workspace-write-ok\\n"
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.settimeout(1)
try:
    sock.connect(("1.1.1.1", 53))
except OSError:
    checks["network_blocked"] = True
else:
    checks["network_blocked"] = False
finally:
    sock.close()
try:
    socket.getaddrinfo("example.com", 443)
except OSError:
    checks["dns_blocked"] = True
else:
    checks["dns_blocked"] = False
print(json.dumps(checks, sort_keys=True))
raise SystemExit(0 if all(checks.values()) else 1)
"""
    request = _request(
        "4",
        probe,
        argv=[str(sentinel), hashlib.sha256(b"registered-host-secret").hexdigest()],
    )

    try:
        try:
            result = await provider.exec(handle, request)
        except FleetError as error:
            pytest.fail(f"real Docker execution failed: {error.code.value} {error.details}")
        assert result.exit_code == 0, (result.stdout, result.stderr)
        checks = json.loads(result.stdout)
        assert all(checks.values()), checks
        assert (workspace / "probe.txt").read_text(encoding="utf-8") == "workspace-write-ok\n"
        assert result.execution is not None
        assert result.execution.cleanup_result.complete is True
        assert result.execution.inspection is not None
        assert result.execution.inspection.image_identity == preflight.image_identity
        assert result.execution.inspection.daemon_identity == preflight.daemon_identity
        assert (
            await provider._list_exact(
                provider._require_executable(),
                {
                    "agent-fleet.installation": str(handle.recovery_scope_id),
                    "agent-fleet.sandbox": handle.sandbox_id,
                },
            )
            == []
        )
    finally:
        await _cleanup_real_installation_scope(provider, str(handle.recovery_scope_id))
        cleanup = await provider.terminate(handle)
        assert cleanup.complete is True


async def test_real_docker_bounds_timeout_output_cancellation_and_recovers_orphan(
    tmp_path: Path,
    real_docker_image: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host_secret = "orphan-registered-host-secret"
    monkeypatch.setenv("AGENT_FLEET_TEST_PROVIDER_SECRET", host_secret)
    monkeypatch.setenv("AGENT_FLEET_REDACT_VALUES", host_secret)
    provider, handle, workspace, preflight = await _prepared_provider(
        tmp_path,
        real_docker_image,
    )
    try:
        literal = "literal;touch /workspace/injected"
        argv_result = await provider.exec(
            handle,
            _request(
                "5",
                "import pathlib,sys; "
                "assert sys.argv[1] == 'literal;touch /workspace/injected'; "
                "assert not pathlib.Path('/workspace/injected').exists()",
                argv=[literal],
            ),
        )
        assert argv_result.exit_code == 0
        assert not (workspace / "injected").exists()

        flood = await provider.exec(
            handle,
            _request(
                "6",
                "import sys; sys.stdout.write('x' * 200000); sys.stdout.flush()",
                max_output_bytes=1024,
            ),
        )
        assert flood.exit_code == 137
        assert flood.output_truncated is True
        assert flood.execution is not None and flood.execution.cleanup_result.complete

        timeout = await provider.exec(
            handle,
            _request(
                "7",
                "import subprocess,time; "
                "subprocess.Popen(['python','-B','-c','import time; time.sleep(30)']); "
                "time.sleep(30)",
                timeout_seconds=1,
            ),
        )
        assert timeout.exit_code == 124
        assert timeout.timed_out is True
        assert timeout.execution is not None and timeout.execution.cleanup_result.complete

        failed = await provider.exec(
            handle,
            _request("a", "raise SystemExit(23)"),
        )
        assert failed.exit_code == 23
        assert failed.execution is not None and failed.execution.cleanup_result.complete

        cancellation_request = _request("8", "import time; time.sleep(30)")
        cancellation_labels = provider._labels(handle, cancellation_request)
        cancellation = asyncio.create_task(provider.exec(handle, cancellation_request))
        for _ in range(100):
            discovered = await provider._list_exact(
                provider._require_executable(),
                {
                    "agent-fleet.installation": cancellation_labels["agent-fleet.installation"],
                    "agent-fleet.execution": cancellation_request.execution_id or "",
                },
            )
            if discovered:
                assert len(discovered) == 1
                raw_cancellation = await _raw_inspect(provider, discovered[0])
                cancellation_state = raw_cancellation.get("State")
                assert isinstance(cancellation_state, dict)
                if cancellation_state.get("Running") is True:
                    break
            await asyncio.sleep(0.05)
        else:
            cancellation.cancel()
            raise AssertionError("real Docker cancellation fixture never started its container")
        cancellation.cancel()
        with pytest.raises(asyncio.CancelledError) as captured_cancellation:
            await cancellation
        cancellation_cleanup = captured_cancellation.value.__dict__["_agent_fleet_cleanup_result"]
        assert cancellation_cleanup["complete"] is True
        assert cancellation_cleanup["reconciled"] is True
        assert cancellation_cleanup["resources_found"] == 1
        assert cancellation_cleanup["resources_removed"] == 1
        assert (
            captured_cancellation.value.__dict__["_agent_fleet_cleanup_binding"]
            == cancellation_labels
        )
        assert (
            await provider._list_exact(
                provider._require_executable(),
                {
                    "agent-fleet.installation": cancellation_labels["agent-fleet.installation"],
                    "agent-fleet.execution": cancellation_request.execution_id or "",
                },
            )
            == []
        )

        orphan_request = _request("9", "raise SystemExit(0)")
        prepared = provider._prepared[handle.sandbox_id]
        orphan_labels = provider._labels(handle, orphan_request)
        create_argv = provider._container_create_argv(
            provider._require_executable(),
            prepared,
            orphan_request,
            f"agent-fleet-{orphan_request.execution_id}",
            orphan_labels,
        )
        created = await provider._call(
            create_argv,
            timeout_seconds=30,
            max_output_bytes=4096,
        )
        assert created.returncode == 0
        orphan_id = created.stdout.decode().strip()
        assert len(orphan_id) == 64
        raw_inspection = await _raw_inspect(provider, orphan_id)
        _assert_raw_hardened_container(
            raw_inspection,
            container_id=orphan_id,
            image_identity=preflight.image_identity or "",
            workspace=workspace,
            git_shadow=provider.git_shadow_path,
            request=orphan_request,
            labels=orphan_labels,
            forbidden_values=(host_secret,),
        )
        recovered = await provider.reconcile_execution(
            handle,
            _recovery_request(handle, orphan_request),
        )
        assert recovered.complete is True
        assert recovered.resources_found == 1
        assert recovered.resources_removed == 1
        assert (
            await provider._list_exact(
                provider._require_executable(),
                {
                    "agent-fleet.installation": str(handle.recovery_scope_id),
                    "agent-fleet.sandbox": handle.sandbox_id,
                },
            )
            == []
        )
    finally:
        await _cleanup_real_installation_scope(provider, str(handle.recovery_scope_id))
        cleanup = await provider.terminate(handle)
        assert cleanup.complete is True


async def test_real_docker_restart_recovers_pre_dispatch_zero_without_replay(
    tmp_path: Path,
    real_docker_image: str,
) -> None:
    fixture = await _persistent_recovery_fixture(tmp_path, real_docker_image)
    request = _request(
        "pre-dispatch",
        "from pathlib import Path; Path('/workspace/replayed-pre-dispatch').write_text('bad')",
    )
    lease = _save_execution_lease(fixture, request, creation_dispatched=False)
    installation_id = str(fixture.sandbox.recovery_scope_id)
    try:
        restarted = build_container(fixture.state_root)
        restarted_provider, recovery_calls = _record_docker_calls(restarted)
        recovered = await restarted.recovery.recover_run(fixture.run.run_id)

        assert recovered.status is RunStatus.FAILED
        stored = restarted.state.get_lease(lease.lease_id)
        assert stored.status is LeaseStatus.RECOVERED
        assert restarted.state.outstanding_leases(fixture.run.run_id) == []
        assert not await asyncio.to_thread(Path(fixture.workspace.path).exists)
        assert not any(
            call[1:3] in {("container", "create"), ("container", "start")}
            for call in recovery_calls
        )
        assert (
            await restarted_provider._list_exact(
                restarted_provider._require_executable(),
                {"agent-fleet.installation": installation_id},
            )
            == []
        )
    finally:
        await _cleanup_real_installation_scope(fixture.provider, installation_id)


async def test_real_docker_restart_keeps_ambiguous_zero_then_removes_delayed_create(
    tmp_path: Path,
    real_docker_image: str,
) -> None:
    fixture = await _persistent_recovery_fixture(tmp_path, real_docker_image)
    marker = Path(fixture.workspace.path) / "replayed-delayed-create"
    request = _request(
        "delayed-create",
        "from pathlib import Path; Path('/workspace/replayed-delayed-create').write_text('bad')",
    )
    lease = _save_execution_lease(fixture, request, creation_dispatched=True)
    installation_id = str(fixture.sandbox.recovery_scope_id)
    try:
        first_restart = build_container(fixture.state_root)
        _, first_recovery_calls = _record_docker_calls(first_restart)
        with pytest.raises(FleetError) as captured:
            await first_restart.recovery.recover_run(fixture.run.run_id)
        assert captured.value.code is ErrorCode.SANDBOX_CLEANUP_FAILED

        failed_lease = first_restart.state.get_lease(lease.lease_id)
        assert failed_lease.status is LeaseStatus.FAILED
        outstanding = first_restart.state.outstanding_leases(fixture.run.run_id)
        assert {item.kind for item in outstanding} == {
            LeaseKind.EXECUTION,
            LeaseKind.SANDBOX,
            LeaseKind.WORKTREE,
        }
        assert await asyncio.to_thread(Path(fixture.workspace.path).is_dir)
        assert not await asyncio.to_thread(marker.exists)
        assert not any(
            call[1:3] in {("container", "create"), ("container", "start")}
            for call in first_recovery_calls
        )

        execution_handle = await _create_raw_orphan(fixture, request)
        assert not await asyncio.to_thread(marker.exists)
        second_restart = build_container(fixture.state_root)
        second_provider, second_recovery_calls = _record_docker_calls(second_restart)
        recovered = await second_restart.recovery.recover_run(fixture.run.run_id)

        assert recovered.status is RunStatus.FAILED
        stored = second_restart.state.get_lease(lease.lease_id)
        assert stored.status is LeaseStatus.RECOVERED
        assert second_restart.state.outstanding_leases(fixture.run.run_id) == []
        assert not await asyncio.to_thread(Path(fixture.workspace.path).exists)
        assert not any(
            call[1:3] in {("container", "create"), ("container", "start")}
            for call in second_recovery_calls
        )
        assert (
            await second_provider._list_exact(
                second_provider._require_executable(),
                {"agent-fleet.execution": execution_handle.execution_id},
            )
            == []
        )
    finally:
        await _cleanup_real_installation_scope(fixture.provider, installation_id)


async def test_real_docker_restart_recovers_active_exact_id_without_replay(
    tmp_path: Path,
    real_docker_image: str,
) -> None:
    fixture = await _persistent_recovery_fixture(tmp_path, real_docker_image)
    marker = Path(fixture.workspace.path) / "replayed-active-orphan"
    request = _request(
        "active-orphan",
        "from pathlib import Path; Path('/workspace/replayed-active-orphan').write_text('bad')",
    )
    lease = _save_execution_lease(fixture, request, creation_dispatched=True)
    installation_id = str(fixture.sandbox.recovery_scope_id)
    try:
        execution_handle = await _create_raw_orphan(fixture, request)
        active = fixture.container.state.activate_lease(
            lease.lease_id,
            {
                **lease.metadata,
                "schema_version": 2,
                "creation_dispatched": True,
                "execution_handle": execution_handle.model_dump(mode="json"),
            },
        )
        assert active.status is LeaseStatus.ACTIVE
        assert not await asyncio.to_thread(marker.exists)

        restarted = build_container(fixture.state_root)
        restarted_provider, recovery_calls = _record_docker_calls(restarted)
        recovered = await restarted.recovery.recover_run(fixture.run.run_id)

        assert recovered.status is RunStatus.FAILED
        stored = restarted.state.get_lease(lease.lease_id)
        assert stored.status is LeaseStatus.RECOVERED
        assert restarted.state.outstanding_leases(fixture.run.run_id) == []
        assert not await asyncio.to_thread(Path(fixture.workspace.path).exists)
        assert not any(
            call[1:3] in {("container", "create"), ("container", "start")}
            for call in recovery_calls
        )
        assert (
            await restarted_provider._list_exact(
                restarted_provider._require_executable(),
                {"agent-fleet.execution": execution_handle.execution_id},
            )
            == []
        )
    finally:
        await _cleanup_real_installation_scope(fixture.provider, installation_id)


async def test_real_docker_bootstrap_publishes_only_verified_evidence_graph(
    tmp_path: Path,
    real_docker_image: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "bootstrap-registered-provider-secret"
    monkeypatch.setenv("AGENT_FLEET_TEST_PROVIDER_SECRET", secret)
    monkeypatch.setenv("AGENT_FLEET_REDACT_VALUES", secret)
    fixture = build_container(tmp_path / "fixture-state")
    target = fixture.repository.create_canary_fixture(tmp_path / "fixture-state" / "target")
    state_root = tmp_path / "fleet-state"
    container = build_container(state_root)
    provider = container.sandboxes.get("docker")
    assert isinstance(provider, DockerSandboxProvider)
    installation_id = provider.recovery_scope_id
    try:
        assert not (target / ".fleet").exists()
        assert container.state.get_project_by_root(str(target.resolve())) is None

        initialized = await container.bootstrap.initialize(
            target,
            runtime_name="fake",
            sandbox_name="docker",
            docker_image=real_docker_image,
        )

        assert initialized["bootstrap_verified"] is True
        assert initialized["bootstrap_publish_allowed"] is True
        assert initialized["bootstrap_cleanup_complete"] is True
        assert initialized["bootstrap_outstanding_lease_count"] == 0
        assert initialized["bootstrap_policy_mode"] == BootstrapPolicyMode.VERIFIED.value
        assert initialized["bootstrap_proof_gaps"] == []
        assert (target / ".fleet" / "fleet.yaml").is_file()
        project = container.state.get_project_by_root(str(target.resolve()))
        assert project is not None
        assert project.bootstrap_verified is True
        assert project.bootstrap_report_artifact_id == initialized["bootstrap_report_artifact_id"]
        report_metadata = container.state.get_artifact(project.bootstrap_report_artifact_id or "")
        report = container.bootstrap._read_and_validate_report(report_metadata)
        assert report.publish_allowed is True
        assert report.completion_decision.verified_complete is True
        assert report.policy_mode is BootstrapPolicyMode.VERIFIED
        assert report.proof_gaps == []
        transcript_contents = [
            container.artifacts.read_text(reference.artifact_id)
            for reference in report.command_transcripts
        ]
        assert len(transcript_contents) == 2
        assert all(
            content.count(BOOTSTRAP_SANDBOX_PROBE_MARKER) == 1 for content in transcript_contents
        )
        host_sentinels = list((state_root / "bootstrap").glob(f"*/{BOOTSTRAP_HOST_SENTINEL_NAME}"))
        assert len(host_sentinels) == 1
        assert host_sentinels[0].is_file()
        assert not host_sentinels[0].is_relative_to(host_sentinels[0].parent / "repository")
        assert container.state.outstanding_leases() == []
        assert report.sandbox_preflight.recovery_scope_id == installation_id
        assert (
            await provider._list_exact(
                provider._require_executable(),
                {"agent-fleet.installation": installation_id},
            )
            == []
        )
        artifact_files = [path for path in (state_root / "artifacts").rglob("*") if path.is_file()]
        assert artifact_files
        assert all(secret.encode() not in path.read_bytes() for path in artifact_files)
    finally:
        await _cleanup_real_installation_scope(provider, installation_id)


@pytest.mark.parametrize(
    "choice", [ApprovalChoice.ALLOW_ONCE, ApprovalChoice.ALLOW_RUN, ApprovalChoice.ALLOW_ALWAYS]
)
async def test_real_docker_exact_approval_resume_preserves_independent_evidence(
    tmp_path: Path,
    real_docker_image: str,
    choice: ApprovalChoice,
) -> None:
    """Private fixture registration tests real approved commands, not public bootstrap."""
    fixture = build_container(tmp_path / "fixture-state")
    target = fixture.repository.create_bootstrap_canary_fixture(
        tmp_path / "fixture-state" / "target"
    )
    state_root = tmp_path / "fleet-state"
    container = build_container(state_root)
    provider = container.sandboxes.get("docker")
    assert isinstance(provider, DockerSandboxProvider)
    configuration = SandboxConfiguration(provider="docker", image=real_docker_image)
    preflight = await provider.preflight(
        configuration, requirements_for_configuration(configuration)
    )
    assert preflight.ready
    installation_id = provider.recovery_scope_id
    try:
        container.projects._initialize_without_canary(
            target,
            sandbox_name="docker",
            docker_image=real_docker_image,
            trusted_canary_config=True,
            sandbox_image_identity=preflight.image_identity,
            sandbox_daemon_identity=preflight.daemon_identity,
        )
        # Two distinct reviewed command IDs force a pause after Verifier evidence exists.
        verification_path = target / ".fleet/project/verification.yaml"
        verification = yaml.safe_load(verification_path.read_text())
        verification["commands"]["bootstrap-unittest-repeat"] = json.loads(
            json.dumps(verification["commands"]["bootstrap-unittest"])
        )
        verification["requiredForCodeChange"].append("bootstrap-unittest-repeat")
        verification_path.write_text(yaml.safe_dump(verification, sort_keys=False))
        _, snapshot = container.projects.config.load_snapshot(target / ".fleet/fleet.yaml")
        project = container.permissions.project_at(target)
        container.state.save_project(
            project.model_copy(
                update={
                    "fleet_spec_hash": container.projects.config.snapshot_hash(snapshot),
                }
            )
        )
        container.permissions.configure(target, mode=TrustMode.SAFE, allowed_paths=("src",))
        run = await container.workflow.start(
            project_path=target,
            goal="Fix the canary behavior",
            runtime_name="fake",
            sandbox_name="docker",
            fake_scenario=FakeScenario.SUCCESS,
        )
        for expected_role in ("engineer", "engineer", "verifier", "verifier"):
            assert run.status is RunStatus.PAUSED_FOR_APPROVAL
            assert run.pending_approval_id is not None
            container = build_container(state_root)
            request = container.state.get_approval(run.pending_approval_id)
            assert request.principal_role == expected_role
            container.approvals.approve(request.request_id, choice=choice)
            container = build_container(state_root)
            run = await container.workflow.resume(run.run_id)
        assert run.status is RunStatus.READY_FOR_REVIEW
        assert run.verified_complete is True
        assert run.verification_checkpoint is None
        evidence = [
            CommandEvidence.model_validate_json(container.artifacts.read_text(item))
            for item in run.command_evidence_artifact_ids
        ]
        verified = [item for item in evidence if item.principal_role == "verifier"]
        assert len(evidence) == 4
        assert len(verified) == 2
        assert all(item.strength is EvidenceStrength.INDEPENDENTLY_VERIFIED for item in verified)
        assert {item.agent_instance_id for item in verified} == {run.verifier_agent_instance_id}
        assert len({item.sandbox_id for item in verified}) == 1
        assert container.state.count_executed_intents(run.run_id, "command.run") == 4
        assert container.state.outstanding_leases(run.run_id) == []
        if choice is ApprovalChoice.ALLOW_ALWAYS:
            container = build_container(state_root)
            subsequent = await container.workflow.start(
                project_path=target,
                goal="Fix the canary behavior",
                runtime_name="fake",
                sandbox_name="docker",
                fake_scenario=FakeScenario.SUCCESS,
            )
            assert subsequent.verified_complete is True
            receipts = container.state.list_grants(subsequent.run_id)
            assert len(receipts) == 4
            assert all(item.request_id is None and item.remaining_uses == 0 for item in receipts)
            assert not any(
                event.event_type == "approval.requested"
                for event in container.state.list_events(subsequent.run_id)
            )
            assert container.state.outstanding_leases(subsequent.run_id) == []
        assert (
            await provider._list_exact(
                provider._require_executable(), {"agent-fleet.installation": installation_id}
            )
            == []
        )
    finally:
        await _cleanup_real_installation_scope(provider, installation_id)
