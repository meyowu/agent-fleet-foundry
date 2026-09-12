from __future__ import annotations

import asyncio
import json
import os
from dataclasses import replace
from io import FileIO
from pathlib import Path
from typing import cast

import pytest

from agent_fleet.adapters.sandbox.docker import DockerSandboxProvider
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
    SandboxExecutionHandle,
    SandboxExecutionRecoveryRequest,
    SandboxHandle,
    SandboxSpec,
    WorkflowStage,
)
from agent_fleet.domain.security import Redactor, canonical_json_hash

_CONTAINER_ID = "c" * 64
_IMAGE_ID = "sha256:" + "a" * 64
_DAEMON_ENDPOINT = "unix:///var/run/docker.sock"
_DAEMON_ID = "contract-daemon-id"
_DAEMON_IDENTITY = canonical_json_hash(
    {
        "architecture": "amd64",
        "daemon_id": _DAEMON_ID,
        "endpoint": _DAEMON_ENDPOINT,
        "os": "linux",
        "server_version": "28.3.3",
    }
)


class RecordingDockerRunner:
    def __init__(self, workspace: Path, shadow: Path) -> None:
        self.workspace = workspace
        self.shadow = shadow
        self.calls: list[tuple[tuple[str, ...], dict[str, str]]] = []
        self.create_argv: tuple[str, ...] | None = None
        self.endpoint = _DAEMON_ENDPOINT
        self.daemon_id = _DAEMON_ID
        self.daemon_architecture = "x86_64"
        self.daemon_os = "linux"
        self.client_version = "28.3.3"
        self.client_api_version = "1.51"
        self.server_version = "28.3.3"
        self.server_api_version = "1.51"
        self.memory_limit = True
        self.swap_limit = True
        self.pids_limit = True
        self.cpu_cfs_period = True
        self.cpu_cfs_quota = True
        self.security_options = ["name=seccomp,profile=builtin", "name=cgroupns"]
        self.init_binary = "docker-init"
        self.image_id = _IMAGE_ID
        self.image_architecture = "amd64"
        self.image_environment = [
            "PATH=/image/bin:/usr/bin",
            "LANG=C.UTF-8",
        ]
        self.image_exposed_ports: dict[str, object] | None = None
        self.image_configuration_overrides: dict[str, object] = {}
        self.malformed_image_configuration = False
        self.start_timed_out = False
        self.start_output_truncated = False
        self.create_timed_out = False
        self.create_output_truncated = False
        self.create_stdout = _CONTAINER_ID + "\n"
        self.replace_daemon_after_create = False
        self.replace_daemon_after_image_inspect = False
        self.replace_daemon_after_container_inspect = False
        self.replace_daemon_after_start = False
        self.replace_daemon_after_container_list = False
        self.replace_daemon_after_kill = False
        self.replace_daemon_after_rm = False
        self.block_create = False
        self.create_entered = asyncio.Event()
        self.create_release = asyncio.Event()
        self.block_start = False
        self.start_entered = asyncio.Event()
        self.start_release = asyncio.Event()
        self.block_rm = False
        self.rm_entered = asyncio.Event()
        self.rm_release = asyncio.Event()
        self.privileged = False
        self.rm_returncode = 0
        self.inspection_mutation: str | None = None
        self.start_returncode = 0
        self.listed_ids: list[str] = []
        self.id_lookup_ids: list[str] | None = None
        self.raise_os_error = False
        self.raise_termination_error = False
        self.raise_runtime_error = False
        self.block_next_info_after_create = False
        self.info_after_create_entered = asyncio.Event()
        self.info_after_create_release = asyncio.Event()
        self.operation_results: dict[str, list[ProcessResult]] = {}

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
        assert cwd is None
        if self.raise_os_error:
            raise ProcessInvocationError("trusted subprocess could not be invoked")
        if self.raise_termination_error:
            raise ProcessTerminationError("trusted subprocess termination was not proven")
        if self.raise_runtime_error:
            raise RuntimeError("runner invariant failed")
        self.calls.append((argv, environment))
        operation = _operation_name(argv)
        queued_results = self.operation_results.get(operation, [])
        if queued_results:
            return queued_results.pop(0)
        if argv[1:3] == ("context", "inspect"):
            return _result(json.dumps(self.endpoint))
        if argv[1:2] == ("version",):
            return _result(
                json.dumps(
                    {
                        "Client": {
                            "Version": self.client_version,
                            "ApiVersion": self.client_api_version,
                        },
                        "Server": {
                            "Version": self.server_version,
                            "ApiVersion": self.server_api_version,
                        },
                    }
                )
                + "\n"
            )
        if argv[1:2] == ("info",):
            if self.block_next_info_after_create and self.create_argv is not None:
                self.block_next_info_after_create = False
                self.info_after_create_entered.set()
                await self.info_after_create_release.wait()
            return _result(
                json.dumps(
                    {
                        "OSType": self.daemon_os,
                        "Architecture": self.daemon_architecture,
                        "ID": self.daemon_id,
                        "ServerVersion": self.server_version,
                        "MemoryLimit": self.memory_limit,
                        "SwapLimit": self.swap_limit,
                        "PidsLimit": self.pids_limit,
                        "CpuCfsPeriod": self.cpu_cfs_period,
                        "CpuCfsQuota": self.cpu_cfs_quota,
                        "SecurityOptions": self.security_options,
                        "InitBinary": self.init_binary,
                    }
                )
                + "\n"
            )
        if argv[1:3] == ("image", "inspect"):
            image_configuration: object
            if self.malformed_image_configuration:
                image_configuration = ["not", "an", "object"]
            else:
                configured: dict[str, object] = {
                    "Env": self.image_environment,
                    "Volumes": None,
                    "ExposedPorts": self.image_exposed_ports,
                }
                configured.update(self.image_configuration_overrides)
                image_configuration = configured
            result = _result(
                json.dumps(
                    [
                        {
                            "Id": self.image_id,
                            "Os": "linux",
                            "Architecture": self.image_architecture,
                            "Config": image_configuration,
                        }
                    ]
                )
            )
            if self.replace_daemon_after_image_inspect:
                self.replace_daemon_after_image_inspect = False
                self.daemon_id = "replacement-daemon-after-image-inspect"
            return result
        if argv[1:3] == ("container", "create"):
            self.create_argv = argv
            self.create_entered.set()
            if self.block_create:
                await self.create_release.wait()
            result = _result(
                self.create_stdout,
                timed_out=self.create_timed_out,
                output_truncated=self.create_output_truncated,
            )
            if self.replace_daemon_after_create:
                self.daemon_id = "replacement-daemon-after-create"
            return result
        if argv[1:3] == ("container", "inspect"):
            assert self.create_argv is not None
            inspected = self._container_inspection()
            if self.inspection_mutation == "inspect_empty":
                self.inspection_mutation = None
                return _result("[]")
            if self.inspection_mutation == "inspect_multiple":
                self.inspection_mutation = None
                return _result(json.dumps([inspected, inspected]))
            result = _result(json.dumps([inspected]))
            if self.replace_daemon_after_container_inspect:
                self.replace_daemon_after_container_inspect = False
                self.daemon_id = "replacement-daemon-after-inspect"
            return result
        if argv[1:4] == ("container", "start", "--attach"):
            self.start_entered.set()
            if self.block_start:
                await self.start_release.wait()
            result = _result(
                "verification passed\n",
                returncode=self.start_returncode,
                timed_out=self.start_timed_out,
                output_truncated=self.start_output_truncated,
            )
            if self.replace_daemon_after_start:
                self.replace_daemon_after_start = False
                self.daemon_id = "replacement-daemon-after-start"
            return result
        if argv[1:3] == ("container", "kill"):
            result = _result(_CONTAINER_ID + "\n")
            if self.replace_daemon_after_kill:
                self.replace_daemon_after_kill = False
                self.daemon_id = "replacement-daemon-after-kill"
            return result
        if argv[1:3] == ("container", "rm"):
            self.rm_entered.set()
            if self.block_rm:
                await self.rm_release.wait()
            result = _result(_CONTAINER_ID + "\n", returncode=self.rm_returncode)
            if self.replace_daemon_after_rm:
                self.replace_daemon_after_rm = False
                self.daemon_id = "replacement-daemon-after-rm"
            return result
        if argv[1:3] == ("container", "ls"):
            identities = (
                self.id_lookup_ids
                if "--filter" in argv
                and any(value.startswith("id=") for value in argv)
                and self.id_lookup_ids is not None
                else self.listed_ids
            )
            result = _result("".join(f"{identity}\n" for identity in identities))
            if self.replace_daemon_after_container_list:
                self.replace_daemon_after_container_list = False
                self.daemon_id = "replacement-daemon-after-container-list"
            return result
        raise AssertionError(f"unexpected Docker argv: {argv!r}")

    def _container_inspection(self) -> dict[str, object]:
        assert self.create_argv is not None
        argv = self.create_argv
        labels = _option_map(argv, "--label")
        effective_environment = {
            item.split("=", 1)[0]: item.split("=", 1)[1] for item in self.image_environment
        }
        for item in _option_values(argv, "--env"):
            key, value = item.split("=", 1)
            effective_environment[key] = value
        mounts: list[dict[str, object]] = []
        for item in _option_values(argv, "--mount"):
            parts = item.split(",")
            values = {
                key: value for part in parts if "=" in part for key, value in [part.split("=", 1)]
            }
            mounts.append(
                {
                    "Type": values["type"],
                    "Source": values["src"],
                    "Destination": values["dst"],
                    "RW": "readonly" not in parts,
                    "Propagation": values.get("bind-propagation", "rprivate"),
                }
            )
        inspection: dict[str, object] = {
            "Id": _CONTAINER_ID,
            "Name": "/" + argv[argv.index("--name") + 1],
            "Image": _IMAGE_ID,
            "Config": {
                "User": "1000:1000",
                "Image": _IMAGE_ID,
                "Entrypoint": ["python"],
                "Cmd": list(argv[argv.index(_IMAGE_ID) + 1 :]),
                "WorkingDir": "/workspace",
                "Env": [f"{key}={value}" for key, value in effective_environment.items()],
                "Labels": labels,
                "Healthcheck": {"Test": ["NONE"]},
                "StopTimeout": 1,
                "ExposedPorts": None,
            },
            "HostConfig": {
                "NetworkMode": "none",
                "CapDrop": ["ALL"],
                "CapAdd": None,
                "SecurityOpt": ["no-new-privileges=true", "seccomp=builtin"],
                "ReadonlyRootfs": True,
                "Privileged": self.privileged,
                "PidsLimit": 128,
                "NanoCpus": round(float(_option_values(argv, "--cpus")[0]) * 1_000_000_000),
                "Memory": 512 * 1024 * 1024,
                "MemorySwap": 512 * 1024 * 1024,
                "MemorySwappiness": 0,
                "ShmSize": 64 * 1024 * 1024,
                "RestartPolicy": {"Name": "no"},
                "LogConfig": {"Type": "none"},
                "Ulimits": [{"Name": "nofile", "Soft": 1024, "Hard": 1024}],
                "IpcMode": "private",
                "CgroupnsMode": "private",
                "PidMode": "",
                "UsernsMode": "",
                "UTSMode": "",
                "GroupAdd": None,
                "DeviceCgroupRules": None,
                "VolumesFrom": None,
                "Init": True,
                "Tmpfs": {
                    "/tmp": "rw,noexec,nosuid,nodev,size=134217728",
                    "/cache": "rw,noexec,nosuid,nodev,size=134217728",
                },
                "Devices": None,
                "DeviceRequests": None,
                "PortBindings": None,
                "PublishAllPorts": False,
                "AutoRemove": False,
            },
            "Mounts": mounts,
            "State": {
                "Status": "exited",
                "Running": False,
                "Paused": False,
                "Restarting": False,
                "Dead": False,
                "Error": "",
                "OOMKilled": False,
                "ExitCode": 0,
                "FinishedAt": "2026-09-04T12:00:00Z",
            },
        }
        config = inspection["Config"]
        host = inspection["HostConfig"]
        state = inspection["State"]
        assert isinstance(config, dict)
        assert isinstance(host, dict)
        assert isinstance(state, dict)
        if self.inspection_mutation == "extra_mount":
            mounts.append(
                {
                    "Type": "volume",
                    "Source": "unexpected",
                    "Destination": "/unexpected",
                    "RW": True,
                    "Propagation": "rprivate",
                }
            )
        elif self.inspection_mutation == "mount_unhashable":
            mounts[0]["Source"] = ["not", "a", "path"]
        elif self.inspection_mutation == "cap_drop_unhashable":
            host["CapDrop"] = [["ALL"]]
        elif self.inspection_mutation == "cap_add_mapping":
            host["CapAdd"] = {"unexpected": "shape"}
        elif self.inspection_mutation == "group_add_nested":
            host["GroupAdd"] = [["0"]]
        elif self.inspection_mutation == "nnp_false":
            host["SecurityOpt"] = ["no-new-privileges=false", "seccomp=builtin"]
        elif self.inspection_mutation == "seccomp_unconfined":
            host["SecurityOpt"] = ["no-new-privileges=true", "seccomp=unconfined"]
        elif self.inspection_mutation == "tmpfs_without_noexec":
            tmpfs = host["Tmpfs"]
            assert isinstance(tmpfs, dict)
            tmpfs["/tmp"] = "rw,nosuid,nodev,size=134217728"
        elif self.inspection_mutation == "tmpfs_conflicting_exec":
            tmpfs = host["Tmpfs"]
            assert isinstance(tmpfs, dict)
            tmpfs["/tmp"] = "rw,noexec,exec,nosuid,nodev,size=134217728"
        elif self.inspection_mutation == "extra_ulimit":
            ulimits = host["Ulimits"]
            assert isinstance(ulimits, list)
            ulimits.append({"Name": "nproc", "Soft": 64, "Hard": 64})
        elif self.inspection_mutation == "ulimit_float":
            host["Ulimits"] = [{"Name": "nofile", "Soft": 1024.0, "Hard": 1024.0}]
        elif self.inspection_mutation == "memory_swappiness":
            host["MemorySwappiness"] = 60
        elif self.inspection_mutation == "memory_swappiness_list":
            host["MemorySwappiness"] = []
        elif self.inspection_mutation == "memory_swappiness_mapping":
            host["MemorySwappiness"] = {}
        elif self.inspection_mutation == "readonly_root_int":
            host["ReadonlyRootfs"] = 1
        elif self.inspection_mutation == "privileged_int":
            host["Privileged"] = 0
        elif self.inspection_mutation == "init_int":
            host["Init"] = 1
        elif self.inspection_mutation == "stop_timeout_bool":
            config["StopTimeout"] = True
        elif self.inspection_mutation == "restart_missing":
            host["RestartPolicy"] = {}
        elif self.inspection_mutation == "restart_null":
            host["RestartPolicy"] = {"Name": None}
        elif self.inspection_mutation == "auto_remove_int":
            host["AutoRemove"] = 0
        elif self.inspection_mutation == "publish_all_ports_int":
            host["PublishAllPorts"] = 0
        elif self.inspection_mutation == "pid_mode_missing":
            host.pop("PidMode")
        elif self.inspection_mutation == "mount_propagation_missing":
            mounts[0].pop("Propagation")
        elif self.inspection_mutation == "argv":
            config["Cmd"] = ["-c", "unreviewed"]
        elif self.inspection_mutation == "cmd_false":
            config["Cmd"] = False
        elif self.inspection_mutation == "environment_value":
            environment = config["Env"]
            assert isinstance(environment, list)
            config["Env"] = [
                "LANG=mutated" if item.startswith("LANG=") else item for item in environment
            ]
        elif self.inspection_mutation == "uts_host":
            host["UTSMode"] = "host"
        elif self.inspection_mutation == "supplementary_group":
            host["GroupAdd"] = ["0"]
        elif self.inspection_mutation == "device_cgroup_rule":
            host["DeviceCgroupRules"] = ["c 1:3 rwm"]
        elif self.inspection_mutation == "volumes_from":
            host["VolumesFrom"] = ["foreign:rw"]
        elif self.inspection_mutation == "name":
            inspection["Name"] = "/foreign-name"
        elif self.inspection_mutation == "backing_image":
            inspection["Image"] = "sha256:" + "f" * 64
        elif self.inspection_mutation == "malformed_host":
            inspection["HostConfig"] = ["not", "an", "object"]
            self.inspection_mutation = None
        elif self.inspection_mutation == "malformed_config":
            inspection["Config"] = ["not", "an", "object"]
            self.inspection_mutation = None
        elif self.inspection_mutation == "label_run":
            labels["agent-fleet.run"] = "run_" + "8" * 32
        elif self.inspection_mutation == "label_intent":
            labels["agent-fleet.intent"] = "intent_" + "8" * 32
        elif self.inspection_mutation == "label_task":
            labels["agent-fleet.task"] = "task_" + "8" * 32
        elif self.inspection_mutation == "label_agent":
            labels["agent-fleet.agent"] = "agent_" + "8" * 32
        elif self.inspection_mutation == "label_stage":
            labels["agent-fleet.stage"] = WorkflowStage.INTAKE.value
        elif self.inspection_mutation == "nonterminal_state":
            state.update(
                {
                    "Status": "created",
                    "Running": False,
                    "ExitCode": 0,
                    "FinishedAt": "",
                }
            )
        elif self.inspection_mutation == "terminal_error":
            state["Error"] = "runtime reported an error"
        elif self.inspection_mutation == "terminal_error_list":
            state["Error"] = []
        elif self.inspection_mutation == "terminal_error_mapping":
            state["Error"] = {}
        elif self.inspection_mutation == "terminal_error_missing":
            state.pop("Error")
        elif self.inspection_mutation == "terminal_error_null":
            state["Error"] = None
        elif self.inspection_mutation == "dead_state":
            state["Dead"] = True
        elif self.inspection_mutation == "oom_killed":
            state["OOMKilled"] = True
            state["ExitCode"] = 137
        elif self.inspection_mutation == "running_int":
            state["Running"] = 0
        elif self.inspection_mutation == "paused_int":
            state["Paused"] = 0
        elif self.inspection_mutation == "restarting_int":
            state["Restarting"] = 0
        elif self.inspection_mutation == "dead_int":
            state["Dead"] = 0
        elif self.inspection_mutation == "oom_killed_int":
            state["OOMKilled"] = 0
        elif self.inspection_mutation == "exit_code_bool":
            state["ExitCode"] = False
        elif self.inspection_mutation == "finished_at_missing":
            state.pop("FinishedAt")
        elif self.inspection_mutation == "finished_at_null":
            state["FinishedAt"] = None
        elif self.inspection_mutation == "finished_at_list":
            state["FinishedAt"] = []
        return inspection


def _result(
    stdout: str = "",
    *,
    stderr: str = "",
    returncode: int = 0,
    timed_out: bool = False,
    output_truncated: bool = False,
) -> ProcessResult:
    return ProcessResult(
        returncode=returncode,
        stdout=stdout.encode(),
        stderr=stderr.encode(),
        timed_out=timed_out,
        output_truncated=output_truncated,
    )


def _option_values(argv: tuple[str, ...], option: str) -> list[str]:
    return [argv[index + 1] for index, value in enumerate(argv[:-1]) if value == option]


def _option_map(argv: tuple[str, ...], option: str) -> dict[str, str]:
    return {item.split("=", 1)[0]: item.split("=", 1)[1] for item in _option_values(argv, option)}


def _operation_name(argv: tuple[str, ...]) -> str:
    if argv[1:3] == ("context", "inspect"):
        return "context"
    if argv[1:2] == ("version",):
        return "version"
    if argv[1:2] == ("info",):
        return "info"
    if argv[1:3] == ("image", "inspect"):
        return "image"
    if argv[1:3] == ("container", "create"):
        return "create"
    if argv[1:3] == ("container", "inspect"):
        return "inspect"
    if argv[1:4] == ("container", "start", "--attach"):
        return "start"
    if argv[1:3] == ("container", "kill"):
        return "kill"
    if argv[1:3] == ("container", "rm"):
        return "rm"
    if argv[1:3] == ("container", "ls"):
        return "id-lookup" if any(value.startswith("id=") for value in argv) else "list"
    return "unknown"


def _assert_final_remove_is_daemon_bound(
    calls: list[tuple[tuple[str, ...], dict[str, str]]],
) -> None:
    operations = [_operation_name(call[0]) for call in calls]
    assert operations[-3:] == ["rm", "context", "info"]


def _failure_result(mode: str) -> ProcessResult:
    return ProcessResult(
        returncode=125 if mode == "nonzero" else 0,
        stdout=b"\xff" if mode == "malformed" else b"",
        stderr=b"",
        timed_out=mode == "timeout",
        output_truncated=mode == "truncated",
    )


def _provider(
    tmp_path: Path,
    runner: RecordingDockerRunner,
    *,
    redactor: Redactor | None = None,
) -> DockerSandboxProvider:
    return DockerSandboxProvider(
        runner=runner,
        clock=SystemClock(),
        ids=UuidIdGenerator(),
        redactor=redactor or Redactor(),
        docker_executable="/usr/bin/docker",
        installation_id="1" * 32,
        git_shadow_path=tmp_path / "state" / "git-shadow",
        uid=1000,
        gid=1000,
    )


def _verification_request() -> ExecRequest:
    return ExecRequest(
        execution_id="exec_" + "3" * 32,
        intent_id="intent_" + "4" * 32,
        task_id="task_" + "5" * 32,
        agent_instance_id="agent_" + "6" * 32,
        stage=WorkflowStage.VERIFYING,
        executable="python",
        argv=["-m", "unittest"],
        cwd=".",
        command_spec_hash="7" * 64,
    )


def _recovery_request(
    handle: SandboxHandle,
    request: ExecRequest | None = None,
    *,
    creation_dispatched: bool = True,
) -> SandboxExecutionRecoveryRequest:
    command = request or _verification_request()
    return SandboxExecutionRecoveryRequest(
        execution_id=cast(str, command.execution_id),
        sandbox_id=handle.sandbox_id,
        run_id=handle.run_id,
        project_id=cast(str, handle.project_id),
        provider="docker",
        intent_id=cast(str, command.intent_id),
        task_id=cast(str, command.task_id),
        agent_instance_id=cast(str, command.agent_instance_id),
        stage=cast(WorkflowStage, command.stage),
        creation_dispatched=creation_dispatched,
    )


def _docker_spec(workspace: Path) -> SandboxSpec:
    return SandboxSpec(
        workspace_host_path=str(workspace),
        project_id="prj_" + "9" * 32,
        configuration=SandboxConfiguration(provider="docker", image="runner:test"),
        image_identity=_IMAGE_ID,
        daemon_identity=_DAEMON_IDENTITY,
    )


@pytest.mark.asyncio
async def test_docker_provider_uses_hardened_direct_argv_and_inspects_before_start(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    shadow = tmp_path / "state" / "git-shadow"
    runner = RecordingDockerRunner(workspace.resolve(), shadow)
    provider = _provider(tmp_path, runner)
    spec = _docker_spec(workspace)
    handle = await provider.create(
        "run_" + "1" * 32,
        spec,
        sandbox_id="sandbox_" + "2" * 32,
    )
    inspection = await provider.inspect(handle)
    request = ExecRequest(
        execution_id="exec_" + "3" * 32,
        intent_id="intent_" + "4" * 32,
        task_id="task_" + "5" * 32,
        agent_instance_id="agent_" + "6" * 32,
        stage=WorkflowStage.VERIFYING,
        executable="python",
        argv=["-m", "pytest", "-q", "literal;touch /tmp/nope"],
        cwd=".",
        environment={"PYTHONPATH": "/workspace/src"},
        command_spec_hash="7" * 64,
    )

    created_resources = []

    def record_created(resource: object) -> None:
        assert not any(call[0][1:3] == ("container", "start") for call in runner.calls)
        created_resources.append(resource)

    result = await provider.exec(
        handle,
        request,
        on_resource_created=record_created,
    )

    assert inspection.ready is True
    assert inspection.daemon_identity == _DAEMON_IDENTITY
    assert handle.recovery_scope_id == "1" * 32
    assert result.exit_code == 0
    assert result.execution is not None
    assert result.execution.provider == "docker"
    assert created_resources == [result.execution.resource_handle]
    assert result.execution.resource_handle.native_resource_id == _CONTAINER_ID
    assert result.execution.cleanup_result.complete is True
    assert runner.create_argv is not None
    argv = runner.create_argv
    for required in (
        "--pull=never",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges=true",
        "--security-opt=seccomp=builtin",
        "--read-only",
        "--network=none",
        "--cgroupns=private",
        "--ipc=private",
        "--no-healthcheck",
        "--log-driver=none",
        "--init",
    ):
        assert required in argv
    assert argv[-4:] == ("-m", "pytest", "-q", "literal;touch /tmp/nope")
    assert _IMAGE_ID in argv
    assert "/tmp:rw,noexec,nosuid,nodev,size=134217728" in argv
    assert "/cache:rw,noexec,nosuid,nodev,size=134217728" in argv
    assert f"agent-fleet.installation={'1' * 32}" in argv
    assert f"agent-fleet.daemon={_DAEMON_IDENTITY}" in argv
    assert str(workspace.resolve()) in " ".join(argv)
    assert str(shadow) in " ".join(argv)
    assert runner.calls[0][1] == {}
    assert all(
        environment == {"DOCKER_HOST": "unix:///var/run/docker.sock"}
        for _, environment in runner.calls[1:]
    )
    operations = [call[0][1:3] for call in runner.calls]
    assert operations.index(("container", "inspect")) < operations.index(("container", "start"))
    _assert_final_remove_is_daemon_bound(runner.calls)


@pytest.mark.asyncio
async def test_docker_preflight_binds_all_create_prerequisites_without_container(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    shadow = tmp_path / "state" / "git-shadow"
    runner = RecordingDockerRunner(workspace.resolve(), shadow)
    provider = _provider(tmp_path, runner)
    configuration = SandboxConfiguration(provider="docker", image="runner:test")
    requirements = _docker_spec(workspace).requirements

    preflight = await provider.preflight(configuration, requirements)

    assert preflight.ready is True
    assert preflight.executable_path == "/usr/bin/docker"
    assert preflight.cli_version == runner.client_version
    assert preflight.daemon_os == "linux"
    assert preflight.daemon_architecture == "amd64"
    assert preflight.daemon_server_version == runner.server_version
    assert preflight.daemon_identity == _DAEMON_IDENTITY
    assert preflight.image_identity == _IMAGE_ID
    assert preflight.recovery_scope_id == "1" * 32
    assert shadow.is_file()
    assert shadow.stat().st_mode & 0o777 == 0o400
    assert not any(call[0][1:3] == ("container", "create") for call in runner.calls)


@pytest.mark.asyncio
async def test_docker_provider_rejects_remote_endpoint_without_creating_container(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingDockerRunner(workspace, tmp_path / "state" / "git-shadow")
    runner.endpoint = "tcp://remote.example:2376"
    provider = _provider(tmp_path, runner)

    with pytest.raises(FleetError) as captured:
        await provider.create(
            "run_" + "1" * 32,
            _docker_spec(workspace),
        )

    assert captured.value.code is ErrorCode.SANDBOX_REMOTE_DAEMON_DENIED
    assert not any(call[0][1:3] == ("container", "create") for call in runner.calls)


@pytest.mark.asyncio
async def test_docker_preflight_rejects_remote_context_before_version_or_daemon_contact(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingDockerRunner(workspace, tmp_path / "state" / "git-shadow")
    runner.endpoint = "ssh://remote.example"
    provider = _provider(tmp_path, runner)

    with pytest.raises(FleetError) as captured:
        await provider.preflight(
            SandboxConfiguration(provider="docker", image="runner:test"),
            _docker_spec(workspace).requirements,
        )

    assert captured.value.code is ErrorCode.SANDBOX_REMOTE_DAEMON_DENIED
    assert [call[0][1:3] for call in runner.calls] == [("context", "inspect")]


@pytest.mark.asyncio
async def test_docker_provider_rejects_sensitive_image_environment(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingDockerRunner(workspace, tmp_path / "state" / "git-shadow")
    runner.image_environment = ["OPENAI_API_KEY=provider-secret"]
    provider = _provider(tmp_path, runner, redactor=Redactor(["provider-secret"]))

    with pytest.raises(FleetError) as captured:
        await provider.create(
            "run_" + "1" * 32,
            _docker_spec(workspace),
        )

    assert captured.value.code is ErrorCode.SANDBOX_IMAGE_UNAVAILABLE
    serialized_calls = repr(runner.calls)
    assert "provider-secret" not in serialized_calls
    assert not any(call[0][1:3] == ("container", "create") for call in runner.calls)


@pytest.mark.asyncio
async def test_docker_provider_missing_cli_fails_without_runner_call(tmp_path: Path) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingDockerRunner(workspace, tmp_path / "state" / "git-shadow")
    provider = DockerSandboxProvider(
        runner=runner,
        clock=SystemClock(),
        ids=UuidIdGenerator(),
        redactor=Redactor(),
        docker_executable=None,
        installation_id="1" * 32,
        git_shadow_path=tmp_path / "state" / "git-shadow",
        uid=1000,
        gid=1000,
    )

    with pytest.raises(FleetError) as captured:
        await provider.create(
            "run_" + "1" * 32,
            _docker_spec(workspace),
        )

    assert captured.value.code is ErrorCode.SANDBOX_UNAVAILABLE
    assert runner.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("timed_out", "output_truncated", "expected_exit"),
    [(True, False, 124), (False, True, 137)],
)
async def test_docker_provider_kills_and_removes_on_bounded_attach_failure(
    tmp_path: Path,
    timed_out: bool,
    output_truncated: bool,
    expected_exit: int,
) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingDockerRunner(workspace, tmp_path / "state" / "git-shadow")
    runner.start_timed_out = timed_out
    runner.start_output_truncated = output_truncated
    provider = _provider(tmp_path, runner)
    handle = await provider.create(
        "run_" + "1" * 32,
        _docker_spec(workspace),
        sandbox_id="sandbox_" + "2" * 32,
    )

    result = await provider.exec(
        handle,
        ExecRequest(
            execution_id="exec_" + "3" * 32,
            intent_id="intent_" + "4" * 32,
            task_id="task_" + "5" * 32,
            agent_instance_id="agent_" + "6" * 32,
            stage=WorkflowStage.VERIFYING,
            executable="python",
            argv=["-m", "unittest"],
            cwd=".",
            command_spec_hash="7" * 64,
        ),
    )

    assert result.exit_code == expected_exit
    operations = [call[0][1:3] for call in runner.calls]
    assert ("container", "kill") in operations
    _assert_final_remove_is_daemon_bound(runner.calls)


@pytest.mark.asyncio
async def test_docker_provider_cancellation_removes_exact_created_container(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingDockerRunner(workspace, tmp_path / "state" / "git-shadow")
    runner.block_start = True
    provider = _provider(tmp_path, runner)
    handle = await provider.create(
        "run_" + "1" * 32,
        _docker_spec(workspace),
        sandbox_id="sandbox_" + "2" * 32,
    )
    request = ExecRequest(
        execution_id="exec_" + "3" * 32,
        intent_id="intent_" + "4" * 32,
        task_id="task_" + "5" * 32,
        agent_instance_id="agent_" + "6" * 32,
        stage=WorkflowStage.VERIFYING,
        executable="python",
        argv=["-m", "unittest"],
        cwd=".",
        command_spec_hash="7" * 64,
    )

    execution = asyncio.create_task(provider.exec(handle, request))
    await runner.start_entered.wait()
    execution.cancel()
    with pytest.raises(asyncio.CancelledError):
        await execution

    rm_calls = [call[0] for call in runner.calls if call[0][1:3] == ("container", "rm")]
    assert len(rm_calls) == 1
    assert "--force" in rm_calls[0]


@pytest.mark.asyncio
async def test_docker_provider_repeated_cancellation_cannot_interrupt_cleanup_proof(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingDockerRunner(workspace, tmp_path / "state" / "git-shadow")
    runner.block_start = True
    runner.block_rm = True
    provider = _provider(tmp_path, runner)
    handle = await provider.create(
        "run_" + "1" * 32,
        _docker_spec(workspace),
        sandbox_id="sandbox_" + "2" * 32,
    )
    request = _verification_request()
    labels = provider._labels(handle, request)

    execution = asyncio.create_task(provider.exec(handle, request))
    await runner.start_entered.wait()
    execution.cancel()
    await runner.rm_entered.wait()
    execution.cancel()
    await asyncio.sleep(0)
    assert not execution.done()

    runner.rm_release.set()
    with pytest.raises(asyncio.CancelledError) as captured:
        await execution

    cleanup = captured.value.__dict__["_agent_fleet_cleanup_result"]
    assert cleanup["complete"] is True
    assert cleanup["reconciled"] is True
    assert cleanup["resources_found"] == 1
    assert cleanup["resources_removed"] == 1
    assert captured.value.__dict__["_agent_fleet_cleanup_binding"] == labels
    rm_calls = [call[0] for call in runner.calls if call[0][1:3] == ("container", "rm")]
    assert len(rm_calls) == 1


@pytest.mark.asyncio
async def test_docker_provider_late_cancellation_cannot_replace_failure_cleanup(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingDockerRunner(workspace, tmp_path / "state" / "git-shadow")
    runner.start_returncode = 23
    runner.block_rm = True
    provider = _provider(tmp_path, runner)
    handle = await provider.create(
        "run_" + "1" * 32,
        _docker_spec(workspace),
        sandbox_id="sandbox_" + "2" * 32,
    )

    execution = asyncio.create_task(provider.exec(handle, _verification_request()))
    await runner.rm_entered.wait()
    execution.cancel()
    await asyncio.sleep(0)
    assert not execution.done()

    runner.rm_release.set()
    with pytest.raises(FleetError) as captured:
        await execution

    assert captured.value.code is ErrorCode.SANDBOX_EXECUTION_FAILED
    cleanup = captured.value.__dict__["_agent_fleet_cleanup_result"]
    assert cleanup["complete"] is True
    assert cleanup["resources_removed"] == 1


@pytest.mark.asyncio
async def test_docker_provider_cancellation_during_post_create_daemon_check(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingDockerRunner(workspace, tmp_path / "state" / "git-shadow")
    provider = _provider(tmp_path, runner)
    handle = await provider.create(
        "run_" + "1" * 32,
        _docker_spec(workspace),
        sandbox_id="sandbox_" + "2" * 32,
    )
    request = _verification_request()
    labels = provider._labels(handle, request)
    runner.block_next_info_after_create = True

    execution = asyncio.create_task(provider.exec(handle, request))
    await runner.info_after_create_entered.wait()
    execution.cancel()
    with pytest.raises(asyncio.CancelledError) as captured:
        await execution

    cleanup = captured.value.__dict__["_agent_fleet_cleanup_result"]
    assert cleanup["complete"] is True
    assert cleanup["reconciled"] is True
    assert cleanup["resources_found"] == 1
    assert cleanup["resources_removed"] == 1
    assert captured.value.__dict__["_agent_fleet_cleanup_binding"] == labels
    _assert_final_remove_is_daemon_bound(runner.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout", "overflow", "malformed_id"])
async def test_docker_ambiguous_create_reconciles_by_exact_execution_labels(
    tmp_path: Path,
    failure: str,
) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingDockerRunner(workspace, tmp_path / "state" / "git-shadow")
    runner.listed_ids = [_CONTAINER_ID]
    if failure == "timeout":
        runner.create_timed_out = True
    elif failure == "overflow":
        runner.create_output_truncated = True
    else:
        runner.create_stdout = "malformed\n"
    provider = _provider(tmp_path, runner)
    handle = await provider.create(
        "run_" + "1" * 32,
        _docker_spec(workspace),
        sandbox_id="sandbox_" + "2" * 32,
    )

    with pytest.raises(FleetError) as captured:
        await provider.exec(handle, _verification_request())

    assert captured.value.code is ErrorCode.SANDBOX_CREATION_FAILED
    operations = [call[0][1:3] for call in runner.calls]
    assert ("container", "start") not in operations
    _assert_final_remove_is_daemon_bound(runner.calls)
    rm_argv = next(
        call[0] for call in reversed(runner.calls) if call[0][1:3] == ("container", "rm")
    )
    assert "--force" in rm_argv


@pytest.mark.asyncio
async def test_docker_ambiguous_create_with_no_match_remains_recovery_required(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingDockerRunner(workspace, tmp_path / "state" / "git-shadow")
    runner.create_timed_out = True
    runner.listed_ids = []
    provider = _provider(tmp_path, runner)
    handle = await provider.create(
        "run_" + "1" * 32,
        _docker_spec(workspace),
        sandbox_id="sandbox_" + "2" * 32,
    )

    with pytest.raises(FleetError) as captured:
        await provider.exec(handle, _verification_request())

    assert captured.value.code is ErrorCode.SANDBOX_CLEANUP_FAILED
    operations = [call[0][1:3] for call in runner.calls]
    assert ("container", "start") not in operations
    assert ("container", "rm") not in operations


@pytest.mark.asyncio
async def test_docker_create_cancellation_runs_shielded_reconciliation(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingDockerRunner(workspace, tmp_path / "state" / "git-shadow")
    runner.block_create = True
    runner.listed_ids = [_CONTAINER_ID]
    provider = _provider(tmp_path, runner)
    handle = await provider.create(
        "run_" + "1" * 32,
        _docker_spec(workspace),
        sandbox_id="sandbox_" + "2" * 32,
    )

    execution = asyncio.create_task(provider.exec(handle, _verification_request()))
    await runner.create_entered.wait()
    execution.cancel()
    with pytest.raises(asyncio.CancelledError):
        await execution

    _assert_final_remove_is_daemon_bound(runner.calls)


@pytest.mark.asyncio
async def test_docker_recovery_reconciles_a_creating_lease_by_deterministic_identity(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingDockerRunner(workspace, tmp_path / "state" / "git-shadow")
    runner.listed_ids = [_CONTAINER_ID]
    provider = _provider(tmp_path, runner)
    handle = await provider.create(
        "run_" + "1" * 32,
        _docker_spec(workspace),
        sandbox_id="sandbox_" + "2" * 32,
    )
    # Seed the exact labels/name that a process crash could leave after docker create.
    runner.create_argv = provider._container_create_argv(
        "/usr/bin/docker",
        provider._prepared[handle.sandbox_id],
        _verification_request(),
        "agent-fleet-exec_" + "3" * 32,
        provider._labels(handle, _verification_request()),
    )

    cleanup = await provider.reconcile_execution(handle, _recovery_request(handle))

    assert cleanup.complete is True
    assert cleanup.resources_found == 1
    assert cleanup.resources_removed == 1
    _assert_final_remove_is_daemon_bound(runner.calls)


@pytest.mark.asyncio
async def test_docker_recovery_proves_zero_match_only_before_dispatch(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingDockerRunner(workspace, tmp_path / "state" / "git-shadow")
    provider = _provider(tmp_path, runner)
    handle = await provider.create(
        "run_" + "1" * 32,
        _docker_spec(workspace),
        sandbox_id="sandbox_" + "2" * 32,
    )

    before_dispatch = await provider.reconcile_execution(
        handle,
        _recovery_request(handle, creation_dispatched=False),
    )
    after_dispatch = await provider.reconcile_execution(
        handle,
        _recovery_request(handle, creation_dispatched=True),
    )

    assert before_dispatch.complete is True
    assert before_dispatch.reconciled is True
    assert before_dispatch.resources_found == 0
    assert after_dispatch.complete is False
    assert after_dispatch.reconciled is False
    assert after_dispatch.resources_found == 0
    assert not any(
        call[0][1:3] in {("container", "create"), ("container", "start")} for call in runner.calls
    )


@pytest.mark.asyncio
async def test_docker_recovery_removes_resource_that_appears_after_ambiguous_zero(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingDockerRunner(workspace, tmp_path / "state" / "git-shadow")
    provider = _provider(tmp_path, runner)
    handle = await provider.create(
        "run_" + "1" * 32,
        _docker_spec(workspace),
        sandbox_id="sandbox_" + "2" * 32,
    )
    request = _verification_request()

    first = await provider.reconcile_execution(
        handle,
        _recovery_request(handle, request, creation_dispatched=True),
    )
    runner.listed_ids = [_CONTAINER_ID]
    runner.create_argv = provider._container_create_argv(
        "/usr/bin/docker",
        provider._prepared[handle.sandbox_id],
        request,
        "agent-fleet-exec_" + "3" * 32,
        provider._labels(handle, request),
    )
    second = await provider.reconcile_execution(
        handle,
        _recovery_request(handle, request, creation_dispatched=True),
    )

    assert first.complete is False
    assert second.complete is True
    assert second.resources_removed == 1
    operations = [call[0][1:3] for call in runner.calls]
    assert ("container", "rm") in operations
    assert ("container", "create") not in operations
    assert ("container", "start") not in operations


@pytest.mark.asyncio
async def test_docker_dispatch_checkpoint_failure_prevents_container_create(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingDockerRunner(workspace, tmp_path / "state" / "git-shadow")
    provider = _provider(tmp_path, runner)
    handle = await provider.create(
        "run_" + "1" * 32,
        _docker_spec(workspace),
        sandbox_id="sandbox_" + "2" * 32,
    )

    def reject_dispatch() -> None:
        assert not any(call[0][1:3] == ("container", "create") for call in runner.calls)
        raise FleetError(
            ErrorCode.STATE_UNAVAILABLE,
            "Injected dispatch checkpoint failure.",
            "Do not dispatch the command.",
        )

    with pytest.raises(FleetError) as captured:
        await provider.exec(
            handle,
            _verification_request(),
            on_creation_dispatched=reject_dispatch,
        )

    assert captured.value.code is ErrorCode.STATE_UNAVAILABLE
    assert not any(call[0][1:3] == ("container", "create") for call in runner.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("label_name", ["run", "intent", "task", "agent", "stage"])
async def test_docker_recovery_detects_partial_logical_label_drift(
    tmp_path: Path,
    label_name: str,
) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingDockerRunner(workspace, tmp_path / "state" / "git-shadow")
    runner.listed_ids = [_CONTAINER_ID]
    runner.inspection_mutation = f"label_{label_name}"
    provider = _provider(tmp_path, runner)
    handle = await provider.create(
        "run_" + "1" * 32,
        _docker_spec(workspace),
        sandbox_id="sandbox_" + "2" * 32,
    )
    runner.create_argv = provider._container_create_argv(
        "/usr/bin/docker",
        provider._prepared[handle.sandbox_id],
        _verification_request(),
        "agent-fleet-exec_" + "3" * 32,
        provider._labels(handle, _verification_request()),
    )

    with pytest.raises(FleetError) as captured:
        await provider.reconcile_execution(handle, _recovery_request(handle))

    assert captured.value.code is ErrorCode.SANDBOX_CLEANUP_FAILED
    assert not any(call[0][1:3] == ("container", "rm") for call in runner.calls)


@pytest.mark.asyncio
async def test_docker_inspection_mismatch_never_starts_and_still_cleans_up(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingDockerRunner(workspace, tmp_path / "state" / "git-shadow")
    runner.privileged = True
    provider = _provider(tmp_path, runner)
    handle = await provider.create(
        "run_" + "1" * 32,
        _docker_spec(workspace),
        sandbox_id="sandbox_" + "2" * 32,
    )

    with pytest.raises(FleetError) as captured:
        await provider.exec(
            handle,
            ExecRequest(
                execution_id="exec_" + "3" * 32,
                intent_id="intent_" + "4" * 32,
                task_id="task_" + "5" * 32,
                agent_instance_id="agent_" + "6" * 32,
                stage=WorkflowStage.VERIFYING,
                executable="python",
                argv=["-m", "unittest"],
                cwd=".",
                command_spec_hash="7" * 64,
            ),
        )

    assert captured.value.code is ErrorCode.SANDBOX_INSPECTION_FAILED
    operations = [call[0][1:3] for call in runner.calls]
    assert ("container", "start") not in operations
    _assert_final_remove_is_daemon_bound(runner.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation",
    [
        "extra_mount",
        "nnp_false",
        "seccomp_unconfined",
        "tmpfs_without_noexec",
        "tmpfs_conflicting_exec",
        "extra_ulimit",
        "ulimit_float",
        "memory_swappiness",
        "memory_swappiness_list",
        "memory_swappiness_mapping",
        "readonly_root_int",
        "privileged_int",
        "init_int",
        "stop_timeout_bool",
        "restart_missing",
        "restart_null",
        "auto_remove_int",
        "publish_all_ports_int",
        "pid_mode_missing",
        "mount_propagation_missing",
        "argv",
        "environment_value",
        "uts_host",
        "supplementary_group",
        "device_cgroup_rule",
        "volumes_from",
        "name",
        "backing_image",
        "malformed_host",
        "malformed_config",
        "mount_unhashable",
        "cap_drop_unhashable",
        "cap_add_mapping",
        "group_add_nested",
        "inspect_empty",
        "inspect_multiple",
    ],
)
async def test_docker_effective_inspection_rejects_security_drift(
    tmp_path: Path,
    mutation: str,
) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingDockerRunner(workspace, tmp_path / "state" / "git-shadow")
    runner.inspection_mutation = mutation
    provider = _provider(tmp_path, runner)
    handle = await provider.create(
        "run_" + "1" * 32,
        _docker_spec(workspace),
        sandbox_id="sandbox_" + "2" * 32,
    )

    with pytest.raises(FleetError) as captured:
        await provider.exec(handle, _verification_request())

    assert captured.value.code is ErrorCode.SANDBOX_INSPECTION_FAILED
    operations = [call[0][1:3] for call in runner.calls]
    assert ("container", "start") not in operations
    _assert_final_remove_is_daemon_bound(runner.calls)


@pytest.mark.asyncio
async def test_docker_rejects_falsey_non_list_cmd_for_empty_reviewed_argv(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingDockerRunner(workspace, tmp_path / "state" / "git-shadow")
    runner.inspection_mutation = "cmd_false"
    provider = _provider(tmp_path, runner)
    handle = await provider.create(
        "run_" + "1" * 32,
        _docker_spec(workspace),
        sandbox_id="sandbox_" + "2" * 32,
    )
    request = _verification_request().model_copy(update={"argv": []})

    with pytest.raises(FleetError) as captured:
        await provider.exec(handle, request)

    assert captured.value.code is ErrorCode.SANDBOX_INSPECTION_FAILED
    operations = [call[0][1:3] for call in runner.calls]
    assert ("container", "start") not in operations
    _assert_final_remove_is_daemon_bound(runner.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation",
    [
        "nonterminal_state",
        "terminal_error",
        "terminal_error_list",
        "terminal_error_mapping",
        "terminal_error_missing",
        "terminal_error_null",
        "dead_state",
        "oom_killed",
        "running_int",
        "paused_int",
        "restarting_int",
        "dead_int",
        "oom_killed_int",
        "exit_code_bool",
        "finished_at_missing",
        "finished_at_null",
        "finished_at_list",
    ],
)
async def test_docker_untrustworthy_terminal_state_cannot_be_reported_as_success(
    tmp_path: Path,
    mutation: str,
) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingDockerRunner(workspace, tmp_path / "state" / "git-shadow")
    runner.inspection_mutation = mutation
    runner.start_returncode = 125
    provider = _provider(tmp_path, runner)
    handle = await provider.create(
        "run_" + "1" * 32,
        _docker_spec(workspace),
        sandbox_id="sandbox_" + "2" * 32,
    )

    with pytest.raises(FleetError) as captured:
        await provider.exec(handle, _verification_request())

    assert captured.value.code is ErrorCode.SANDBOX_EXECUTION_FAILED
    _assert_final_remove_is_daemon_bound(runner.calls)


@pytest.mark.asyncio
async def test_docker_rejects_root_group_before_any_daemon_call(tmp_path: Path) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingDockerRunner(workspace, tmp_path / "state" / "git-shadow")
    provider = DockerSandboxProvider(
        runner=runner,
        clock=SystemClock(),
        ids=UuidIdGenerator(),
        redactor=Redactor(),
        docker_executable="/usr/bin/docker",
        installation_id="1" * 32,
        git_shadow_path=tmp_path / "state" / "git-shadow",
        uid=1000,
        gid=0,
    )

    with pytest.raises(FleetError) as captured:
        await provider.create(
            "run_" + "1" * 32,
            _docker_spec(workspace),
        )

    assert captured.value.code is ErrorCode.SANDBOX_UNAVAILABLE
    assert runner.calls == []


@pytest.mark.asyncio
async def test_docker_preflight_rejects_root_group_before_any_daemon_call(tmp_path: Path) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingDockerRunner(workspace, tmp_path / "state" / "git-shadow")
    provider = DockerSandboxProvider(
        runner=runner,
        clock=SystemClock(),
        ids=UuidIdGenerator(),
        redactor=Redactor(),
        docker_executable="/usr/bin/docker",
        installation_id="1" * 32,
        git_shadow_path=tmp_path / "state" / "git-shadow",
        uid=0,
        gid=1000,
    )

    with pytest.raises(FleetError) as captured:
        await provider.preflight(
            SandboxConfiguration(provider="docker", image="runner:test"),
            _docker_spec(workspace).requirements,
        )

    assert captured.value.code is ErrorCode.SANDBOX_UNAVAILABLE
    assert runner.calls == []


@pytest.mark.asyncio
async def test_docker_preflight_rejects_malformed_recovery_identity_without_daemon_call(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingDockerRunner(workspace, tmp_path / "state" / "git-shadow")
    provider = DockerSandboxProvider(
        runner=runner,
        clock=SystemClock(),
        ids=UuidIdGenerator(),
        redactor=Redactor(),
        docker_executable="/usr/bin/docker",
        installation_id="not-valid",
        git_shadow_path=tmp_path / "state" / "git-shadow",
        uid=1000,
        gid=1000,
    )

    with pytest.raises(FleetError) as captured:
        await provider.preflight(
            SandboxConfiguration(provider="docker", image="runner:test"),
            _docker_spec(workspace).requirements,
        )

    assert captured.value.code is ErrorCode.SANDBOX_UNAVAILABLE
    assert runner.calls == []


@pytest.mark.asyncio
async def test_docker_preflight_maps_recovery_identity_io_failure_to_stable_error(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingDockerRunner(workspace, tmp_path / "state" / "git-shadow")

    def fail_identity() -> str:
        raise RuntimeError("untrusted state path detail")

    provider = DockerSandboxProvider(
        runner=runner,
        clock=SystemClock(),
        ids=UuidIdGenerator(),
        redactor=Redactor(),
        docker_executable="/usr/bin/docker",
        installation_id=fail_identity,
        git_shadow_path=tmp_path / "state" / "git-shadow",
        uid=1000,
        gid=1000,
    )

    with pytest.raises(FleetError) as captured:
        await provider.preflight(
            SandboxConfiguration(provider="docker", image="runner:test"),
            _docker_spec(workspace).requirements,
        )

    assert captured.value.code is ErrorCode.SANDBOX_UNAVAILABLE
    assert "untrusted" not in str(captured.value)
    assert runner.calls == []


@pytest.mark.asyncio
async def test_docker_maps_vanished_cli_to_stable_unavailable_error(tmp_path: Path) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingDockerRunner(workspace, tmp_path / "state" / "git-shadow")
    runner.raise_os_error = True
    provider = _provider(tmp_path, runner)

    with pytest.raises(FleetError) as captured:
        await provider.preflight(
            SandboxConfiguration(provider="docker", image="runner:test"),
            _docker_spec(workspace).requirements,
        )

    assert captured.value.code is ErrorCode.SANDBOX_UNAVAILABLE
    assert "vanished" not in str(captured.value)


@pytest.mark.asyncio
async def test_docker_maps_typed_process_termination_failure_to_cleanup_error(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingDockerRunner(workspace, tmp_path / "state" / "git-shadow")
    runner.raise_termination_error = True
    provider = _provider(tmp_path, runner)

    with pytest.raises(FleetError) as captured:
        await provider.preflight(
            SandboxConfiguration(provider="docker", image="runner:test"),
            _docker_spec(workspace).requirements,
        )

    assert captured.value.code is ErrorCode.SANDBOX_CLEANUP_FAILED
    assert "termination was not proven" not in str(captured.value)


@pytest.mark.asyncio
async def test_docker_does_not_mask_untyped_runner_invariant_failure(tmp_path: Path) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingDockerRunner(workspace, tmp_path / "state" / "git-shadow")
    runner.raise_runtime_error = True
    provider = _provider(tmp_path, runner)

    with pytest.raises(RuntimeError, match="runner invariant failed"):
        await provider.preflight(
            SandboxConfiguration(provider="docker", image="runner:test"),
            _docker_spec(workspace).requirements,
        )


@pytest.mark.asyncio
async def test_docker_rejects_image_environment_outside_allowlist(tmp_path: Path) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingDockerRunner(workspace, tmp_path / "state" / "git-shadow")
    runner.image_environment.append("PYTHON_VERSION=3.12.11")
    provider = _provider(tmp_path, runner)

    with pytest.raises(FleetError) as captured:
        await provider.create("run_" + "1" * 32, _docker_spec(workspace))

    assert captured.value.code is ErrorCode.SANDBOX_IMAGE_UNAVAILABLE
    assert not any(call[0][1:3] == ("container", "create") for call in runner.calls)


@pytest.mark.asyncio
async def test_docker_rejects_image_architecture_mismatch(tmp_path: Path) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingDockerRunner(workspace, tmp_path / "state" / "git-shadow")
    runner.image_architecture = "arm64"
    provider = _provider(tmp_path, runner)

    with pytest.raises(FleetError) as captured:
        await provider.create("run_" + "1" * 32, _docker_spec(workspace))

    assert captured.value.code is ErrorCode.SANDBOX_IMAGE_UNAVAILABLE
    assert not any(call[0][1:3] == ("container", "create") for call in runner.calls)


@pytest.mark.asyncio
async def test_docker_rejects_image_declared_ports(tmp_path: Path) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingDockerRunner(workspace, tmp_path / "state" / "git-shadow")
    runner.image_exposed_ports = {"8080/tcp": {}}
    provider = _provider(tmp_path, runner)

    with pytest.raises(FleetError) as captured:
        await provider.create("run_" + "1" * 32, _docker_spec(workspace))

    assert captured.value.code is ErrorCode.SANDBOX_IMAGE_UNAVAILABLE
    assert not any(call[0][1:3] == ("container", "create") for call in runner.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("Volumes", []),
        ("Volumes", False),
        ("ExposedPorts", []),
        ("ExposedPorts", False),
        ("Env", {}),
        ("Env", False),
    ],
)
async def test_docker_rejects_falsey_malformed_image_collections(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingDockerRunner(workspace, tmp_path / "state" / "git-shadow")
    runner.image_configuration_overrides[field] = value
    provider = _provider(tmp_path, runner)

    with pytest.raises(FleetError) as captured:
        await provider.create("run_" + "1" * 32, _docker_spec(workspace))

    assert captured.value.code is ErrorCode.SANDBOX_IMAGE_UNAVAILABLE
    assert not any(call[0][1:3] == ("container", "create") for call in runner.calls)


@pytest.mark.asyncio
async def test_docker_rejects_malformed_image_configuration_with_typed_error(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingDockerRunner(workspace, tmp_path / "state" / "git-shadow")
    runner.malformed_image_configuration = True
    provider = _provider(tmp_path, runner)

    with pytest.raises(FleetError) as captured:
        await provider.create("run_" + "1" * 32, _docker_spec(workspace))

    assert captured.value.code is ErrorCode.SANDBOX_IMAGE_UNAVAILABLE
    assert not any(call[0][1:3] == ("container", "create") for call in runner.calls)


@pytest.mark.asyncio
async def test_docker_rejects_mutated_image_identity_before_container_create(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingDockerRunner(workspace, tmp_path / "state" / "git-shadow")
    runner.image_id = "sha256:" + "b" * 64
    provider = _provider(tmp_path, runner)

    with pytest.raises(FleetError) as captured:
        await provider.create("run_" + "1" * 32, _docker_spec(workspace))

    assert captured.value.code is ErrorCode.SANDBOX_IMAGE_UNAVAILABLE
    assert not any(call[0][1:3] == ("container", "create") for call in runner.calls)


@pytest.mark.asyncio
async def test_docker_rejects_tampered_handle_before_container_create(tmp_path: Path) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingDockerRunner(workspace, tmp_path / "state" / "git-shadow")
    provider = _provider(tmp_path, runner)
    handle = await provider.create(
        "run_" + "1" * 32,
        _docker_spec(workspace),
        sandbox_id="sandbox_" + "2" * 32,
    )
    handle.run_id = "run_" + "8" * 32
    runner.calls.clear()

    with pytest.raises(FleetError) as captured:
        await provider.exec(handle, _verification_request())

    assert captured.value.code is ErrorCode.SANDBOX_EXECUTION_FAILED
    assert not any(call[0][1:3] == ("container", "create") for call in runner.calls)


@pytest.mark.asyncio
async def test_docker_prepared_spec_is_a_deep_snapshot(tmp_path: Path) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingDockerRunner(workspace, tmp_path / "state" / "git-shadow")
    provider = _provider(tmp_path, runner)
    spec = _docker_spec(workspace)
    handle = await provider.create(
        "run_" + "1" * 32,
        spec,
        sandbox_id="sandbox_" + "2" * 32,
    )
    spec.configuration = SandboxConfiguration(
        provider="docker",
        image="runner:test",
        cpu_limit=2.0,
    )

    await provider.exec(handle, _verification_request())

    assert runner.create_argv is not None
    cpu_index = runner.create_argv.index("--cpus")
    assert runner.create_argv[cpu_index + 1] == "1"


@pytest.mark.asyncio
async def test_docker_shadow_pin_survives_candidate_writes_and_repeated_exec(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingDockerRunner(workspace, tmp_path / "state" / "git-shadow")
    provider = _provider(tmp_path, runner)
    handle = await provider.create("run_" + "1" * 32, _docker_spec(workspace))
    prepared = provider._prepared[handle.sandbox_id]
    shadow_file = prepared.git_shadow_file
    descriptor = shadow_file.fileno()
    assert shadow_file.readable() and not shadow_file.writable()
    assert os.get_inheritable(descriptor) is False
    for index in range(2):
        (workspace / f"ordinary-change-{index}.txt").write_text("candidate changes are allowed\n")
        request = _verification_request().model_copy(
            update={"execution_id": "exec_" + str(index + 1) * 32}
        )
        result = await provider.exec(handle, request)
        assert result.exit_code == 0
        assert shadow_file.closed is False
        current = os.fstat(descriptor)
        assert (current.st_dev, current.st_ino, current.st_mtime_ns, current.st_ctime_ns) == (
            prepared.git_shadow_identity
        )
    assert sum(call[0][1:3] == ("container", "create") for call in runner.calls) == 2
    assert (await provider.terminate(handle)).complete is True
    assert shadow_file.closed is True and handle.sandbox_id not in provider._prepared
    with pytest.raises(OSError):
        os.fstat(descriptor)
    assert (await provider.terminate(handle)).complete is True


@pytest.mark.asyncio
@pytest.mark.parametrize("cancelled", [False, True])
async def test_docker_failed_preparation_closes_shadow_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cancelled: bool
) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingDockerRunner(workspace, tmp_path / "state" / "git-shadow")
    provider = _provider(tmp_path, runner)
    opened: list[FileIO] = []
    original_open = provider._open_git_shadow

    def track_open() -> FileIO:
        result = original_open()
        opened.append(result)
        return result

    def fail_validation(prepared: object) -> None:
        if cancelled:
            raise asyncio.CancelledError("injected preparation failure")
        raise FleetError(
            ErrorCode.SANDBOX_CREATION_FAILED, "injected preparation failure", "Retry preparation."
        )

    monkeypatch.setattr(provider, "_open_git_shadow", track_open)
    monkeypatch.setattr(provider, "_revalidate_prepared_paths", fail_validation)
    with pytest.raises(
        asyncio.CancelledError if cancelled else FleetError, match="injected preparation failure"
    ):
        await provider.create("run_" + "1" * 32, _docker_spec(workspace))
    assert len(opened) == 1 and opened[0].closed is True
    assert provider._prepared == {}


@pytest.mark.asyncio
async def test_docker_preflight_closes_its_temporary_shadow_descriptor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingDockerRunner(workspace, tmp_path / "state" / "git-shadow")
    provider = _provider(tmp_path, runner)
    opened: list[FileIO] = []
    original_open = provider._open_git_shadow

    def track_open() -> FileIO:
        result = original_open()
        opened.append(result)
        return result

    monkeypatch.setattr(provider, "_open_git_shadow", track_open)
    spec = _docker_spec(workspace)
    assert (await provider.preflight(spec.configuration, spec.requirements)).ready is True
    assert len(opened) == 1 and opened[0].closed is True
    assert provider._prepared == {}


@pytest.mark.asyncio
async def test_docker_failed_termination_retains_shadow_pin_until_exact_cleanup(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingDockerRunner(workspace, tmp_path / "state" / "git-shadow")
    provider = _provider(tmp_path, runner)
    handle = await provider.create("run_" + "1" * 32, _docker_spec(workspace))
    shadow_file = provider._prepared[handle.sandbox_id].git_shadow_file
    runner.listed_ids = [_CONTAINER_ID]
    with pytest.raises(FleetError) as captured:
        await provider.terminate(handle)
    assert captured.value.code is ErrorCode.SANDBOX_CLEANUP_FAILED
    assert shadow_file.closed is False
    assert not any(call[0][1:3] == ("container", "rm") for call in runner.calls)
    runner.listed_ids = []
    assert (await provider.terminate(handle)).complete is True
    assert shadow_file.closed is True


@pytest.mark.asyncio
async def test_docker_duplicate_preparation_cannot_replace_live_shadow_pin(tmp_path: Path) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingDockerRunner(workspace, tmp_path / "state" / "git-shadow")
    provider = _provider(tmp_path, runner)
    handle = await provider.create("run_" + "1" * 32, _docker_spec(workspace))
    original = provider._prepared[handle.sandbox_id]
    with pytest.raises(FleetError) as captured:
        await provider.create(handle.run_id, _docker_spec(workspace), sandbox_id=handle.sandbox_id)
    assert captured.value.code is ErrorCode.SANDBOX_CREATION_FAILED
    assert provider._prepared[handle.sandbox_id] is original
    assert original.git_shadow_file.closed is False
    assert (await provider.terminate(handle)).complete is True
    assert original.git_shadow_file.closed is True


@pytest.mark.asyncio
async def test_docker_restore_reuses_exact_preparation_and_open_shadow_pin(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingDockerRunner(workspace, tmp_path / "state" / "git-shadow")
    provider = _provider(tmp_path, runner)
    spec = _docker_spec(workspace)
    handle = await provider.create(
        "run_" + "1" * 32,
        spec,
        sandbox_id="sandbox_" + "2" * 32,
    )
    original = provider._prepared[handle.sandbox_id]
    descriptor = original.git_shadow_file.fileno()
    runner.calls.clear()

    restored = await provider.restore(handle, spec)

    assert restored == handle and restored is not handle
    assert provider._prepared[handle.sandbox_id] is original
    assert original.git_shadow_file.closed is False
    assert original.git_shadow_file.fileno() == descriptor
    assert not any(
        call[0][1:3] in {("container", "create"), ("container", "rm")} for call in runner.calls
    )
    assert (await provider.terminate(handle)).complete is True


@pytest.mark.asyncio
async def test_docker_restore_recreates_only_absent_exact_preparation(tmp_path: Path) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    shadow = tmp_path / "state" / "git-shadow"
    runner = RecordingDockerRunner(workspace, shadow)
    original_provider = _provider(tmp_path, runner)
    spec = _docker_spec(workspace)
    handle = await original_provider.create(
        "run_" + "1" * 32,
        spec,
        sandbox_id="sandbox_" + "2" * 32,
    )
    original_provider._prepared.pop(handle.sandbox_id).git_shadow_file.close()
    provider = _provider(tmp_path, runner)
    runner.calls.clear()

    restored = await provider.restore(handle, spec)

    assert restored == handle
    assert provider._prepared[handle.sandbox_id].handle == handle
    assert provider._prepared[handle.sandbox_id].spec == spec
    assert provider._prepared[handle.sandbox_id].git_shadow_file.closed is False
    assert not any(
        call[0][1:3] in {("container", "create"), ("container", "rm")} for call in runner.calls
    )
    assert (await provider.terminate(handle)).complete is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mismatch",
    [
        "run",
        "project",
        "spec",
        "requirements",
        "configuration",
        "capabilities",
        "image",
        "daemon",
        "recovery-scope",
    ],
)
async def test_docker_restore_rejects_changed_checkpoint_without_replacement_or_dispatch(
    tmp_path: Path,
    mismatch: str,
) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingDockerRunner(workspace, tmp_path / "state" / "git-shadow")
    provider = _provider(tmp_path, runner)
    spec = _docker_spec(workspace)
    handle = await provider.create(
        "run_" + "1" * 32,
        spec,
        sandbox_id="sandbox_" + "2" * 32,
    )
    original = provider._prepared[handle.sandbox_id]
    changed_handle = handle.model_copy(deep=True)
    changed_spec = spec.model_copy(deep=True)
    if mismatch == "run":
        changed_handle.run_id = "run_" + "8" * 32
    elif mismatch == "project":
        changed_handle.project_id = "prj_" + "8" * 32
        changed_spec.project_id = "prj_" + "8" * 32
    elif mismatch == "spec":
        changed_spec.timeout_seconds += 1
    elif mismatch == "requirements":
        changed_spec.requirements = changed_spec.requirements.model_copy(
            update={"code_execution_required": True}
        )
    elif mismatch == "configuration":
        changed_spec.configuration = changed_spec.configuration.model_copy(
            update={"cpu_limit": 2.0}
        )
        changed_handle.configuration_hash = canonical_json_hash(
            changed_spec.configuration.model_dump(mode="json")
        )
    elif mismatch == "capabilities":
        changed_handle.capabilities = changed_handle.capabilities.phase1_fake()
    elif mismatch == "image":
        changed_handle.image_identity = "sha256:" + "b" * 64
        changed_spec.image_identity = "sha256:" + "b" * 64
    elif mismatch == "daemon":
        changed_handle.daemon_identity = "8" * 64
        changed_spec.daemon_identity = "8" * 64
    else:
        changed_handle.recovery_scope_id = "8" * 32
    runner.calls.clear()

    with pytest.raises(FleetError):
        await provider.restore(changed_handle, changed_spec)

    assert provider._prepared[handle.sandbox_id] is original
    assert original.git_shadow_file.closed is False
    assert runner.calls == []
    assert (await provider.terminate(handle)).complete is True


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", ["workspace", "shadow", "closed-pin"])
async def test_docker_restore_rejects_changed_mount_or_pin_without_dispatch(
    tmp_path: Path,
    changed: str,
) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    shadow = tmp_path / "state" / "git-shadow"
    runner = RecordingDockerRunner(workspace, shadow)
    provider = _provider(tmp_path, runner)
    spec = _docker_spec(workspace)
    handle = await provider.create(
        "run_" + "1" * 32,
        spec,
        sandbox_id="sandbox_" + "2" * 32,
    )
    original = provider._prepared[handle.sandbox_id]
    if changed == "workspace":
        workspace.rename(tmp_path / "old-candidate")
        workspace.mkdir()
    elif changed == "shadow":
        shadow.unlink()
        shadow.write_bytes(b"")
        shadow.chmod(0o400)
    else:
        original.git_shadow_file.close()
    runner.calls.clear()

    with pytest.raises(FleetError):
        await provider.restore(handle, spec)

    assert provider._prepared[handle.sandbox_id] is original
    assert runner.calls == []
    assert (await provider.terminate(handle)).complete is True


@pytest.mark.asyncio
async def test_docker_restore_rejects_inflight_preparation_map_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingDockerRunner(workspace, tmp_path / "state" / "git-shadow")
    provider = _provider(tmp_path, runner)
    spec = _docker_spec(workspace)
    handle = await provider.create(
        "run_" + "1" * 32,
        spec,
        sandbox_id="sandbox_" + "2" * 32,
    )
    original = provider._prepared[handle.sandbox_id]
    original_run = runner.run
    restore_info_entered = asyncio.Event()
    restore_info_release = asyncio.Event()

    async def block_restore_info(
        argv: tuple[str, ...],
        *,
        environment: dict[str, str],
        cwd: str | None = None,
        timeout_seconds: int,
        max_output_bytes: int,
    ) -> ProcessResult:
        if argv[1:2] == ("info",) and not restore_info_entered.is_set():
            restore_info_entered.set()
            await restore_info_release.wait()
        return await original_run(
            argv,
            environment=environment,
            cwd=cwd,
            timeout_seconds=timeout_seconds,
            max_output_bytes=max_output_bytes,
        )

    monkeypatch.setattr(runner, "run", block_restore_info)
    runner.calls.clear()
    restoration = asyncio.create_task(provider.restore(handle, spec))
    try:
        await asyncio.wait_for(restore_info_entered.wait(), timeout=5)
        replacement = replace(original)
        provider._prepared[handle.sandbox_id] = replacement
        restore_info_release.set()
        with pytest.raises(FleetError) as captured:
            await restoration
    finally:
        restore_info_release.set()
        if not restoration.done():
            restoration.cancel()
            await asyncio.gather(restoration, return_exceptions=True)

    assert captured.value.code is ErrorCode.SANDBOX_INSPECTION_FAILED
    assert provider._prepared[handle.sandbox_id] is replacement
    assert original.git_shadow_file.closed is False
    assert not any(
        call[0][1:3] in {("container", "create"), ("container", "rm")} for call in runner.calls
    )
    assert (await provider.terminate(handle)).complete is True


@pytest.mark.parametrize("unsafe", ["nonempty", "permissions", "hardlink"])
def test_docker_invalid_shadow_closes_acquired_descriptor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, unsafe: str
) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    shadow = tmp_path / "state" / "git-shadow"
    runner = RecordingDockerRunner(workspace, shadow)
    provider = _provider(tmp_path, runner)
    provider._open_git_shadow().close()
    if unsafe == "hardlink":
        os.link(shadow, shadow.parent / "second-name")
    else:
        shadow.chmod(0o600)
        if unsafe == "nonempty":
            shadow.write_bytes(b"not empty")
            shadow.chmod(0o400)
    descriptors: list[int] = []
    original_open = os.open

    def track_open(path: str | bytes | os.PathLike[str] | os.PathLike[bytes], flags: int) -> int:
        descriptor = original_open(path, flags)
        descriptors.append(descriptor)
        return descriptor

    monkeypatch.setattr(os, "open", track_open)
    with pytest.raises(FleetError) as captured:
        provider._open_git_shadow()
    assert captured.value.code is ErrorCode.SANDBOX_UNAVAILABLE
    assert len(descriptors) == 1
    with pytest.raises(OSError):
        os.fstat(descriptors[0])


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["workspace", "git-shadow", "git-shadow-same-inode"])
async def test_docker_revalidates_bind_path_identity_before_create(
    tmp_path: Path,
    target: str,
) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    shadow = tmp_path / "state" / "git-shadow"
    runner = RecordingDockerRunner(workspace, shadow)
    provider = _provider(tmp_path, runner)
    handle = await provider.create(
        "run_" + "1" * 32,
        _docker_spec(workspace),
        sandbox_id="sandbox_" + "2" * 32,
    )
    if target == "workspace":
        workspace.rename(tmp_path / "old-candidate")
        workspace.mkdir()
    elif target == "git-shadow":
        shadow.unlink()
        shadow.write_bytes(b"")
        shadow.chmod(0o400)
    else:
        original = shadow.stat()
        os.utime(shadow, ns=(original.st_atime_ns, original.st_mtime_ns + 2_000_000_000))
        assert shadow.stat().st_ino == original.st_ino
    runner.calls.clear()
    dispatched: list[bool] = []

    with pytest.raises(FleetError) as captured:
        await provider.exec(
            handle, _verification_request(), on_creation_dispatched=lambda: dispatched.append(True)
        )

    assert captured.value.code is ErrorCode.SANDBOX_CREATION_FAILED
    cleanup = captured.value.__dict__["_agent_fleet_cleanup_result"]
    assert cleanup["complete"] is True
    assert cleanup["resources_found"] == 0
    assert runner.calls == []
    assert dispatched == []


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["workspace", "git-shadow", "git-shadow-same-inode"])
async def test_docker_revalidates_bind_identity_after_final_daemon_round_trip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target: str,
) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    shadow = tmp_path / "state" / "git-shadow"
    runner = RecordingDockerRunner(workspace, shadow)
    provider = _provider(tmp_path, runner)
    handle = await provider.create(
        "run_" + "1" * 32,
        _docker_spec(workspace),
        sandbox_id="sandbox_" + "2" * 32,
    )
    original_run = runner.run
    replaced = False

    async def replace_after_info(
        argv: tuple[str, ...],
        *,
        environment: dict[str, str],
        cwd: str | None = None,
        timeout_seconds: int,
        max_output_bytes: int,
    ) -> ProcessResult:
        nonlocal replaced
        result = await original_run(
            argv,
            environment=environment,
            cwd=cwd,
            timeout_seconds=timeout_seconds,
            max_output_bytes=max_output_bytes,
        )
        if not replaced and argv[1:2] == ("info",):
            replaced = True
            if target == "workspace":
                workspace.rename(tmp_path / "old-candidate")
                workspace.mkdir()
            elif target == "git-shadow":
                shadow.unlink()
                shadow.write_bytes(b"")
                shadow.chmod(0o400)
            else:
                original = shadow.stat()
                os.utime(shadow, ns=(original.st_atime_ns, original.st_mtime_ns + 2_000_000_000))
                assert shadow.stat().st_ino == original.st_ino
        return result

    monkeypatch.setattr(runner, "run", replace_after_info)
    runner.calls.clear()
    dispatched: list[bool] = []

    with pytest.raises(FleetError) as captured:
        await provider.exec(
            handle, _verification_request(), on_creation_dispatched=lambda: dispatched.append(True)
        )

    assert captured.value.code is ErrorCode.SANDBOX_CREATION_FAILED
    assert replaced is True
    assert not any(call[0][1:3] == ("container", "create") for call in runner.calls)
    assert dispatched == []


@pytest.mark.asyncio
async def test_docker_requires_full_execution_identity_before_daemon_call(tmp_path: Path) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingDockerRunner(workspace, tmp_path / "state" / "git-shadow")
    provider = _provider(tmp_path, runner)
    handle = await provider.create(
        "run_" + "1" * 32,
        _docker_spec(workspace),
        sandbox_id="sandbox_" + "2" * 32,
    )
    runner.calls.clear()

    with pytest.raises(FleetError) as captured:
        await provider.exec(
            handle,
            ExecRequest(
                executable="python",
                argv=["-m", "unittest"],
                cwd=".",
            ),
        )

    assert captured.value.code is ErrorCode.SANDBOX_EXECUTION_FAILED
    assert runner.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("provider", "fake"),
        ("sandbox_id", "sandbox_" + "8" * 32),
        ("run_id", "run_" + "8" * 32),
        ("project_id", "prj_" + "8" * 32),
    ],
)
async def test_docker_recovery_request_must_match_sandbox_before_daemon_call(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingDockerRunner(workspace, tmp_path / "state" / "git-shadow")
    provider = _provider(tmp_path, runner)
    handle = await provider.create(
        "run_" + "1" * 32,
        _docker_spec(workspace),
        sandbox_id="sandbox_" + "2" * 32,
    )
    recovery = _recovery_request(handle).model_copy(update={field: value})
    runner.calls.clear()

    with pytest.raises(FleetError) as captured:
        await provider.reconcile_execution(handle, recovery)

    assert captured.value.code is ErrorCode.SANDBOX_CLEANUP_FAILED
    assert runner.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["cleanup", "reconcile", "terminate"])
async def test_docker_rejects_foreign_installation_scope_before_daemon_call(
    tmp_path: Path,
    operation: str,
) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingDockerRunner(workspace, tmp_path / "state" / "git-shadow")
    provider = _provider(tmp_path, runner)
    handle = await provider.create(
        "run_" + "1" * 32,
        _docker_spec(workspace),
        sandbox_id="sandbox_" + "2" * 32,
    )
    foreign = handle.model_copy(update={"recovery_scope_id": "8" * 32})
    runner.calls.clear()

    with pytest.raises(FleetError) as captured:
        if operation == "terminate":
            await provider.terminate(foreign)
        elif operation == "reconcile":
            await provider.reconcile_execution(foreign, _recovery_request(foreign))
        else:
            request = _verification_request()
            labels = provider._labels(handle, request)
            labels["agent-fleet.installation"] = "8" * 32
            execution = SandboxExecutionHandle(
                execution_id=cast(str, request.execution_id),
                sandbox_id=handle.sandbox_id,
                run_id=handle.run_id,
                provider="docker",
                native_resource_id=_CONTAINER_ID,
                labels=labels,
                labels_sha256=canonical_json_hash(labels),
            )
            await provider.cleanup_execution(execution)

    assert captured.value.code is ErrorCode.SANDBOX_CLEANUP_FAILED
    assert runner.calls == []


@pytest.mark.asyncio
async def test_docker_cleanup_does_not_treat_label_drift_as_absence(tmp_path: Path) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingDockerRunner(workspace, tmp_path / "state" / "git-shadow")
    provider = _provider(tmp_path, runner)
    handle = await provider.create(
        "run_" + "1" * 32,
        _docker_spec(workspace),
        sandbox_id="sandbox_" + "2" * 32,
    )
    request = _verification_request()
    labels = provider._labels(handle, request)
    execution_handle = SandboxExecutionHandle(
        execution_id=request.execution_id,
        sandbox_id=handle.sandbox_id,
        run_id=handle.run_id,
        provider="docker",
        native_resource_id=_CONTAINER_ID,
        labels=labels,
        labels_sha256=canonical_json_hash(labels),
    )
    runner.listed_ids = []
    runner.id_lookup_ids = [_CONTAINER_ID]

    with pytest.raises(FleetError) as captured:
        await provider.cleanup_execution(execution_handle)

    assert captured.value.code is ErrorCode.SANDBOX_CLEANUP_FAILED
    assert not any(call[0][1:3] == ("container", "rm") for call in runner.calls)


@pytest.mark.asyncio
async def test_docker_terminate_refuses_unknown_sandbox_labeled_resources(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingDockerRunner(workspace, tmp_path / "state" / "git-shadow")
    provider = _provider(tmp_path, runner)
    handle = await provider.create(
        "run_" + "1" * 32,
        _docker_spec(workspace),
        sandbox_id="sandbox_" + "2" * 32,
    )
    runner.listed_ids = [_CONTAINER_ID]

    with pytest.raises(FleetError) as captured:
        await provider.terminate(handle)

    assert captured.value.code is ErrorCode.SANDBOX_CLEANUP_FAILED
    assert not any(call[0][1:3] == ("container", "rm") for call in runner.calls)


@pytest.mark.asyncio
async def test_docker_recovery_refuses_changed_local_daemon(tmp_path: Path) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingDockerRunner(workspace, tmp_path / "state" / "git-shadow")
    provider = _provider(tmp_path, runner)
    handle = await provider.create(
        "run_" + "1" * 32,
        _docker_spec(workspace),
        sandbox_id="sandbox_" + "2" * 32,
    )
    runner.daemon_id = "different-daemon-id"

    with pytest.raises(FleetError) as captured:
        await provider.reconcile_execution(handle, _recovery_request(handle))

    assert captured.value.code is ErrorCode.SANDBOX_REMOTE_DAEMON_DENIED
    assert not any(call[0][1:3] == ("container", "rm") for call in runner.calls)


@pytest.mark.asyncio
async def test_docker_exec_revalidates_daemon_before_container_create(tmp_path: Path) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingDockerRunner(workspace, tmp_path / "state" / "git-shadow")
    provider = _provider(tmp_path, runner)
    handle = await provider.create(
        "run_" + "1" * 32,
        _docker_spec(workspace),
        sandbox_id="sandbox_" + "2" * 32,
    )
    runner.daemon_id = "replacement-daemon"

    with pytest.raises(FleetError) as captured:
        await provider.exec(handle, _verification_request())

    assert captured.value.code is ErrorCode.SANDBOX_REMOTE_DAEMON_DENIED
    cleanup = captured.value.__dict__["_agent_fleet_cleanup_result"]
    assert cleanup["complete"] is True
    assert cleanup["resources_found"] == 0
    assert not any(call[0][1:3] == ("container", "create") for call in runner.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["preflight", "create"])
async def test_docker_revalidates_daemon_after_image_inspection(
    tmp_path: Path,
    operation: str,
) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingDockerRunner(workspace, tmp_path / "state" / "git-shadow")
    runner.replace_daemon_after_image_inspect = True
    provider = _provider(tmp_path, runner)

    with pytest.raises(FleetError) as captured:
        if operation == "preflight":
            await provider.preflight(
                SandboxConfiguration(provider="docker", image="runner:test"),
                _docker_spec(workspace).requirements,
            )
        else:
            await provider.create("run_" + "1" * 32, _docker_spec(workspace))

    assert captured.value.code is ErrorCode.SANDBOX_REMOTE_DAEMON_DENIED
    assert not any(call[0][1:3] == ("container", "create") for call in runner.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("attach_times_out", [False, True])
async def test_docker_inflight_cleanup_refuses_replaced_daemon(
    tmp_path: Path,
    attach_times_out: bool,
) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingDockerRunner(workspace, tmp_path / "state" / "git-shadow")
    runner.start_timed_out = attach_times_out
    provider = _provider(tmp_path, runner)
    handle = await provider.create(
        "run_" + "1" * 32,
        _docker_spec(workspace),
        sandbox_id="sandbox_" + "2" * 32,
    )

    def replace_daemon(_: SandboxExecutionHandle) -> None:
        runner.daemon_id = "replacement-daemon-after-dispatch"

    with pytest.raises(FleetError) as captured:
        await provider.exec(
            handle,
            _verification_request(),
            on_resource_created=replace_daemon,
        )

    assert captured.value.code is ErrorCode.SANDBOX_CLEANUP_FAILED
    operations = [call[0][1:3] for call in runner.calls]
    create_index = operations.index(("container", "create"))
    assert ("container", "inspect") not in operations[create_index + 1 :]
    assert ("container", "start") not in operations
    assert ("container", "kill") not in operations
    assert ("container", "rm") not in operations


@pytest.mark.asyncio
async def test_docker_revalidates_daemon_between_inspection_and_start(tmp_path: Path) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingDockerRunner(workspace, tmp_path / "state" / "git-shadow")
    runner.replace_daemon_after_container_inspect = True
    provider = _provider(tmp_path, runner)
    handle = await provider.create(
        "run_" + "1" * 32,
        _docker_spec(workspace),
        sandbox_id="sandbox_" + "2" * 32,
    )

    with pytest.raises(FleetError) as captured:
        await provider.exec(handle, _verification_request())

    assert captured.value.code is ErrorCode.SANDBOX_CLEANUP_FAILED
    operations = [call[0][1:3] for call in runner.calls]
    assert ("container", "inspect") in operations
    assert ("container", "start") not in operations
    assert ("container", "kill") not in operations
    assert ("container", "rm") not in operations


@pytest.mark.asyncio
@pytest.mark.parametrize("attach_overflow", [False, True])
async def test_docker_revalidates_daemon_after_start_before_state_or_kill(
    tmp_path: Path,
    attach_overflow: bool,
) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingDockerRunner(workspace, tmp_path / "state" / "git-shadow")
    runner.start_output_truncated = attach_overflow
    runner.replace_daemon_after_start = True
    provider = _provider(tmp_path, runner)
    handle = await provider.create(
        "run_" + "1" * 32,
        _docker_spec(workspace),
        sandbox_id="sandbox_" + "2" * 32,
    )

    with pytest.raises(FleetError) as captured:
        await provider.exec(handle, _verification_request())

    assert captured.value.code is ErrorCode.SANDBOX_CLEANUP_FAILED
    operations = [call[0][1:3] for call in runner.calls]
    start_index = operations.index(("container", "start"))
    assert ("container", "inspect") not in operations[start_index + 1 :]
    assert ("container", "kill") not in operations
    assert ("container", "rm") not in operations


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["kill", "rm"])
async def test_docker_destructive_postcondition_refuses_replaced_daemon(
    tmp_path: Path,
    operation: str,
) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingDockerRunner(workspace, tmp_path / "state" / "git-shadow")
    if operation == "kill":
        runner.start_timed_out = True
        runner.replace_daemon_after_kill = True
    else:
        runner.replace_daemon_after_rm = True
    provider = _provider(tmp_path, runner)
    handle = await provider.create(
        "run_" + "1" * 32,
        _docker_spec(workspace),
        sandbox_id="sandbox_" + "2" * 32,
    )

    with pytest.raises(FleetError) as captured:
        await provider.exec(handle, _verification_request())

    assert captured.value.code is ErrorCode.SANDBOX_CLEANUP_FAILED
    operations = [_operation_name(call[0]) for call in runner.calls]
    assert operations.count(operation) == 1
    if operation == "kill":
        assert "rm" not in operations
    assert operations[-2:] == ["context", "info"]


@pytest.mark.asyncio
async def test_docker_failed_remove_still_revalidates_pinned_daemon(tmp_path: Path) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingDockerRunner(workspace, tmp_path / "state" / "git-shadow")
    runner.rm_returncode = 1
    runner.replace_daemon_after_rm = True
    provider = _provider(tmp_path, runner)
    handle = await provider.create(
        "run_" + "1" * 32,
        _docker_spec(workspace),
        sandbox_id="sandbox_" + "2" * 32,
    )

    with pytest.raises(FleetError) as captured:
        await provider.exec(handle, _verification_request())

    assert captured.value.code is ErrorCode.SANDBOX_CLEANUP_FAILED
    operations = [_operation_name(call[0]) for call in runner.calls]
    assert operations.count("rm") == 1
    assert operations[-2:] == ["context", "info"]


@pytest.mark.asyncio
async def test_docker_ambiguous_create_does_not_list_on_replaced_daemon(tmp_path: Path) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingDockerRunner(workspace, tmp_path / "state" / "git-shadow")
    runner.create_timed_out = True
    runner.replace_daemon_after_create = True
    provider = _provider(tmp_path, runner)
    handle = await provider.create(
        "run_" + "1" * 32,
        _docker_spec(workspace),
        sandbox_id="sandbox_" + "2" * 32,
    )

    with pytest.raises(FleetError) as captured:
        await provider.exec(handle, _verification_request())

    assert captured.value.code is ErrorCode.SANDBOX_CLEANUP_FAILED
    operations = [call[0][1:3] for call in runner.calls]
    assert ("container", "ls") not in operations
    assert ("container", "kill") not in operations
    assert ("container", "rm") not in operations


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "expected_code"),
    [
        ("failed-create", ErrorCode.SANDBOX_CLEANUP_FAILED),
        ("cleanup", ErrorCode.SANDBOX_REMOTE_DAEMON_DENIED),
        ("reconcile", ErrorCode.SANDBOX_REMOTE_DAEMON_DENIED),
        ("terminate", ErrorCode.SANDBOX_REMOTE_DAEMON_DENIED),
    ],
)
async def test_docker_absence_proof_revalidates_daemon_after_listing(
    tmp_path: Path,
    operation: str,
    expected_code: ErrorCode,
) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingDockerRunner(workspace, tmp_path / "state" / "git-shadow")
    provider = _provider(tmp_path, runner)
    handle = await provider.create(
        "run_" + "1" * 32,
        _docker_spec(workspace),
        sandbox_id="sandbox_" + "2" * 32,
    )
    request = _verification_request()
    runner.calls.clear()
    runner.listed_ids = []
    runner.replace_daemon_after_container_list = True

    with pytest.raises(FleetError) as captured:
        if operation == "failed-create":
            runner.operation_results["create"] = [_failure_result("nonzero")]
            await provider.exec(handle, request)
        elif operation == "cleanup":
            labels = provider._labels(handle, request)
            execution = SandboxExecutionHandle(
                execution_id=cast(str, request.execution_id),
                sandbox_id=handle.sandbox_id,
                run_id=handle.run_id,
                provider="docker",
                native_resource_id=_CONTAINER_ID,
                labels=labels,
                labels_sha256=canonical_json_hash(labels),
            )
            await provider.cleanup_execution(execution)
        elif operation == "reconcile":
            await provider.reconcile_execution(handle, _recovery_request(handle))
        else:
            await provider.terminate(handle)

    assert captured.value.code is expected_code
    operations = [_operation_name(call[0]) for call in runner.calls]
    assert "rm" not in operations
    assert "kill" not in operations
    if operation == "cleanup":
        assert "id-lookup" not in operations


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "unsupported",
    ["memory_limit", "swap_limit", "pids_limit", "cpu_cfs_period", "cpu_cfs_quota"],
)
async def test_docker_preflight_requires_daemon_resource_limit_support(
    tmp_path: Path,
    unsupported: str,
) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingDockerRunner(workspace, tmp_path / "state" / "git-shadow")
    setattr(runner, unsupported, False)
    provider = _provider(tmp_path, runner)

    with pytest.raises(FleetError) as captured:
        await provider.preflight(
            SandboxConfiguration(provider="docker", image="runner:test"),
            _docker_spec(workspace).requirements,
        )

    assert captured.value.code is ErrorCode.SANDBOX_UNAVAILABLE
    assert not any(call[0][1:3] == ("image", "inspect") for call in runner.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("attribute", "value"),
    [
        ("security_options", []),
        ("security_options", ["name=seccomp,profile=builtin"]),
        ("security_options", ["name=cgroupns"]),
        ("init_binary", ""),
        ("client_api_version", "1.40"),
        ("server_api_version", "1.40"),
    ],
)
async def test_docker_preflight_requires_isolation_and_api_support(
    tmp_path: Path,
    attribute: str,
    value: object,
) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingDockerRunner(workspace, tmp_path / "state" / "git-shadow")
    setattr(runner, attribute, value)
    provider = _provider(tmp_path, runner)

    with pytest.raises(FleetError) as captured:
        await provider.preflight(
            SandboxConfiguration(provider="docker", image="runner:test"),
            _docker_spec(workspace).requirements,
        )

    assert captured.value.code is ErrorCode.SANDBOX_UNAVAILABLE
    assert not any(call[0][1:3] == ("container", "create") for call in runner.calls)


@pytest.mark.parametrize("cpu_limit", [0.0001, 1.2345])
def test_docker_configuration_rejects_noncanonical_cpu_precision(cpu_limit: float) -> None:
    with pytest.raises(ValueError):
        SandboxConfiguration(
            provider="docker",
            image="runner:test",
            cpu_limit=cpu_limit,
        )


def test_docker_execution_handle_rejects_self_consistent_foreign_labels() -> None:
    labels = {
        "agent-fleet.managed": "true",
        "agent-fleet.installation": "1" * 32,
        "agent-fleet.daemon": _DAEMON_IDENTITY,
        "agent-fleet.run": "run_" + "8" * 32,
        "agent-fleet.sandbox": "sandbox_" + "2" * 32,
        "agent-fleet.execution": "exec_" + "3" * 32,
    }

    with pytest.raises(ValueError, match="trusted identities"):
        SandboxExecutionHandle(
            execution_id="exec_" + "3" * 32,
            sandbox_id="sandbox_" + "2" * 32,
            run_id="run_" + "1" * 32,
            provider="docker",
            native_resource_id=_CONTAINER_ID,
            labels=labels,
            labels_sha256=canonical_json_hash(labels),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "expected_code"),
    [
        ("context", ErrorCode.SANDBOX_UNAVAILABLE),
        ("info", ErrorCode.SANDBOX_UNAVAILABLE),
        ("version", ErrorCode.SANDBOX_UNAVAILABLE),
        ("image", ErrorCode.SANDBOX_IMAGE_UNAVAILABLE),
    ],
)
@pytest.mark.parametrize("mode", ["nonzero", "timeout", "truncated", "malformed"])
async def test_docker_preflight_maps_every_control_metadata_failure(
    tmp_path: Path,
    operation: str,
    expected_code: ErrorCode,
    mode: str,
) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingDockerRunner(workspace, tmp_path / "state" / "git-shadow")
    runner.operation_results[operation] = [_failure_result(mode)]
    provider = _provider(tmp_path, runner)

    with pytest.raises(FleetError) as captured:
        await provider.preflight(
            SandboxConfiguration(provider="docker", image="runner:test"),
            _docker_spec(workspace).requirements,
        )

    assert captured.value.code is expected_code
    assert not any(call[0][1:3] == ("container", "create") for call in runner.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["nonzero", "timeout", "truncated", "malformed"])
async def test_docker_container_inspect_failure_never_starts_and_is_removed(
    tmp_path: Path,
    mode: str,
) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingDockerRunner(workspace, tmp_path / "state" / "git-shadow")
    provider = _provider(tmp_path, runner)
    handle = await provider.create(
        "run_" + "1" * 32,
        _docker_spec(workspace),
        sandbox_id="sandbox_" + "2" * 32,
    )
    runner.operation_results["inspect"] = [_failure_result(mode)]

    with pytest.raises(FleetError) as captured:
        await provider.exec(handle, _verification_request())

    assert captured.value.code is ErrorCode.SANDBOX_INSPECTION_FAILED
    operations = [_operation_name(call[0]) for call in runner.calls]
    assert "start" not in operations
    _assert_final_remove_is_daemon_bound(runner.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("returncode", [125, -9])
async def test_docker_failed_create_stays_recoverable_until_delayed_resource_is_removed(
    tmp_path: Path,
    returncode: int,
) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingDockerRunner(workspace, tmp_path / "state" / "git-shadow")
    provider = _provider(tmp_path, runner)
    handle = await provider.create(
        "run_" + "1" * 32,
        _docker_spec(workspace),
        sandbox_id="sandbox_" + "2" * 32,
    )
    runner.operation_results["create"] = [_result(returncode=returncode)]
    request = _verification_request()

    with pytest.raises(FleetError) as captured:
        await provider.exec(handle, request)

    assert captured.value.code is ErrorCode.SANDBOX_CLEANUP_FAILED
    assert "start" not in [_operation_name(call[0]) for call in runner.calls]
    assert "rm" not in [_operation_name(call[0]) for call in runner.calls]

    runner.listed_ids = [_CONTAINER_ID]
    runner.create_argv = provider._container_create_argv(
        "/usr/bin/docker",
        provider._prepared[handle.sandbox_id],
        request,
        f"agent-fleet-{request.execution_id}",
        provider._labels(handle, request),
    )
    cleanup = await provider.reconcile_execution(
        handle,
        _recovery_request(handle, request, creation_dispatched=True),
    )

    assert cleanup.complete is True
    assert cleanup.reconciled is True
    assert cleanup.resources_found == 1
    assert cleanup.resources_removed == 1
    _assert_final_remove_is_daemon_bound(runner.calls)


@pytest.mark.asyncio
async def test_docker_attach_exit_disagreement_is_removed(tmp_path: Path) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingDockerRunner(workspace, tmp_path / "state" / "git-shadow")
    runner.start_returncode = 125
    provider = _provider(tmp_path, runner)
    handle = await provider.create(
        "run_" + "1" * 32,
        _docker_spec(workspace),
        sandbox_id="sandbox_" + "2" * 32,
    )

    with pytest.raises(FleetError) as captured:
        await provider.exec(handle, _verification_request())

    assert captured.value.code is ErrorCode.SANDBOX_EXECUTION_FAILED
    _assert_final_remove_is_daemon_bound(runner.calls)


@pytest.mark.asyncio
async def test_docker_bounded_attach_accepts_failed_kill_only_after_terminal_inspect(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingDockerRunner(workspace, tmp_path / "state" / "git-shadow")
    provider = _provider(tmp_path, runner)
    handle = await provider.create(
        "run_" + "1" * 32,
        _docker_spec(workspace),
        sandbox_id="sandbox_" + "2" * 32,
    )
    runner.start_output_truncated = True
    runner.operation_results["kill"] = [_failure_result("nonzero")]

    result = await provider.exec(handle, _verification_request())

    assert result.exit_code == 137
    assert result.output_truncated is True
    operations = [_operation_name(call[0]) for call in runner.calls]
    assert operations[-17:] == [
        "inspect",
        "context",
        "info",
        "kill",
        "context",
        "info",
        "inspect",
        "context",
        "info",
        "context",
        "info",
        "inspect",
        "context",
        "info",
        "rm",
        "context",
        "info",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["kill", "rm"])
@pytest.mark.parametrize("mode", ["nonzero", "timeout", "truncated"])
async def test_docker_terminal_cleanup_operation_failures_are_explicitly_reconciled(
    tmp_path: Path,
    operation: str,
    mode: str,
) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingDockerRunner(workspace, tmp_path / "state" / "git-shadow")
    provider = _provider(tmp_path, runner)
    handle = await provider.create(
        "run_" + "1" * 32,
        _docker_spec(workspace),
        sandbox_id="sandbox_" + "2" * 32,
    )
    runner.operation_results[operation] = [_failure_result(mode)]
    if operation == "kill":
        runner.start_timed_out = True
        runner.inspection_mutation = "nonterminal_state"

    with pytest.raises(FleetError) as captured:
        await provider.exec(handle, _verification_request())

    assert captured.value.code is ErrorCode.SANDBOX_CLEANUP_FAILED
    operations = [_operation_name(call[0]) for call in runner.calls]
    _assert_final_remove_is_daemon_bound(runner.calls)
    assert operations.count("rm") == (1 if operation == "kill" else 2)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["list", "id-lookup"])
@pytest.mark.parametrize("mode", ["nonzero", "timeout", "truncated", "malformed"])
async def test_docker_discovery_failures_never_delete_unproven_resources(
    tmp_path: Path,
    operation: str,
    mode: str,
) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    runner = RecordingDockerRunner(workspace, tmp_path / "state" / "git-shadow")
    provider = _provider(tmp_path, runner)
    handle = await provider.create(
        "run_" + "1" * 32,
        _docker_spec(workspace),
        sandbox_id="sandbox_" + "2" * 32,
    )
    runner.operation_results[operation] = [_failure_result(mode)]

    with pytest.raises(FleetError) as captured:
        if operation == "list":
            runner.create_timed_out = True
            await provider.exec(handle, _verification_request())
        else:
            request = _verification_request()
            labels = provider._labels(handle, request)
            execution = SandboxExecutionHandle(
                execution_id=cast(str, request.execution_id),
                sandbox_id=handle.sandbox_id,
                run_id=handle.run_id,
                provider="docker",
                native_resource_id=_CONTAINER_ID,
                labels=labels,
                labels_sha256=canonical_json_hash(labels),
            )
            runner.listed_ids = []
            await provider.cleanup_execution(execution)

    assert captured.value.code is ErrorCode.SANDBOX_CLEANUP_FAILED
    assert not any(_operation_name(call[0]) == "rm" for call in runner.calls)
