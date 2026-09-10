"""Hardened local Docker sandbox using one inspected container per command."""

from __future__ import annotations

import asyncio
import hmac
import json
import os
import re
import stat
from collections.abc import Callable
from dataclasses import dataclass
from io import FileIO
from pathlib import Path
from typing import Any, Literal, cast

from agent_fleet.adapters.sandbox.baseline_docker import (
    BaselineDockerTransport,
    BaselinePreparedView,
    BaselineRequestView,
)
from agent_fleet.adapters.sandbox.process import (
    ProcessInvocationError,
    ProcessResult,
    ProcessRunner,
    ProcessTerminationError,
)
from agent_fleet.domain.baseline_resources import (
    BaselineExecRequest,
    BaselineExecResult,
    BaselineExecutionHandle,
    BaselineExecutionRecoveryRequest,
    BaselineSandboxHandle,
    BaselineSandboxInspection,
    BaselineSandboxSpec,
)
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.ids import IdPrefix
from agent_fleet.domain.models import (
    ExecRequest,
    ExecResult,
    SandboxCapabilities,
    SandboxCleanupResult,
    SandboxConfiguration,
    SandboxExecutionHandle,
    SandboxExecutionMetadata,
    SandboxExecutionRecoveryRequest,
    SandboxHandle,
    SandboxInspection,
    SandboxPreflight,
    SandboxRequirements,
    SandboxSecurityLevel,
    SandboxSpec,
)
from agent_fleet.domain.security import Redactor, canonical_json_hash, sha256_bytes
from agent_fleet.ports.clock import Clock
from agent_fleet.ports.id_generator import IdGenerator

_CONTROLLED_PATH = "/usr/local/bin:/usr/bin:/bin"
_DOCKER_METADATA_OUTPUT_LIMIT = 1_000_000
_DOCKER_CONTROL_TIMEOUT = 30
_SAFE_IMAGE_ENV_NAMES = frozenset({"LANG", "LC_ALL", "PATH"})
_SENSITIVE_ENV_FRAGMENT = re.compile(
    r"(?:TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|API_KEY|PRIVATE_KEY|ACCESS_KEY|SESSION|COOKIE|"
    r"SSH|AWS|AZURE|GCP|GOOGLE|OPENAI|ANTHROPIC|DOCKER|KUBE)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class _PreparedSandbox:
    spec: SandboxSpec
    handle: SandboxHandle
    workspace: Path
    image_identity: str
    image_environment: tuple[tuple[str, str], ...]
    inspection: SandboxInspection
    workspace_identity: tuple[int, int]
    git_shadow_identity: tuple[int, int, int, int]
    git_shadow_file: FileIO


@dataclass(frozen=True)
class _DockerDaemon:
    endpoint: str
    architecture: Literal["amd64", "arm64"]
    identity: str
    server_version: str


class DockerSandboxProvider:
    """Use only a local Docker daemon; never pulls, builds, shells, or falls back."""

    def __init__(
        self,
        *,
        runner: ProcessRunner,
        clock: Clock,
        ids: IdGenerator,
        redactor: Redactor,
        docker_executable: str | None,
        installation_id: str | Callable[[], str],
        git_shadow_path: Path,
        uid: int | None = None,
        gid: int | None = None,
    ) -> None:
        self.runner = runner
        self.clock = clock
        self.ids = ids
        self.redactor = redactor
        self.docker_executable = docker_executable
        self._installation_id_source = installation_id
        self.git_shadow_path = git_shadow_path
        self.uid = os.getuid() if uid is None else uid
        self.gid = os.getgid() if gid is None else gid
        self._prepared: dict[str, _PreparedSandbox] = {}
        self._docker_host: str | None = None
        self._docker_daemon_identity: str | None = None
        self._baseline_transport = BaselineDockerTransport(self)

    async def create_baseline(
        self, spec: BaselineSandboxSpec, *, sandbox_id: str
    ) -> BaselineSandboxHandle:
        return await self._baseline_transport.create(spec, sandbox_id=sandbox_id)

    async def inspect_baseline(self, handle: BaselineSandboxHandle) -> BaselineSandboxInspection:
        return await self._baseline_transport.inspect(handle)

    async def exec_baseline(
        self,
        handle: BaselineSandboxHandle,
        request: BaselineExecRequest,
        *,
        on_creation_dispatched: Callable[[], None],
        on_resource_created: Callable[[BaselineExecutionHandle], None],
    ) -> BaselineExecResult:
        return await self._baseline_transport.execute(
            handle,
            request,
            on_creation_dispatched=on_creation_dispatched,
            on_resource_created=on_resource_created,
        )

    async def cleanup_baseline_execution(
        self, handle: BaselineExecutionHandle
    ) -> SandboxCleanupResult:
        return await self._baseline_transport.cleanup_execution(handle)

    async def reconcile_baseline_execution(
        self, sandbox: BaselineSandboxHandle, request: BaselineExecutionRecoveryRequest
    ) -> SandboxCleanupResult:
        return await self._baseline_transport.reconcile(sandbox, request)

    async def terminate_baseline(self, handle: BaselineSandboxHandle) -> SandboxCleanupResult:
        return await self._baseline_transport.terminate(handle)

    @property
    def installation_id(self) -> str:
        """Resolve the persistent installation identity only when Docker needs labels."""

        source = self._installation_id_source
        value = source() if callable(source) else source
        if not value:
            raise RuntimeError("Fleet installation identity is missing")
        return value

    @property
    def capabilities(self) -> SandboxCapabilities:
        return SandboxCapabilities(
            provider="docker",
            security_level=SandboxSecurityLevel.ISOLATED,
            isolation_enforced=True,
            executes_code=True,
            supported_network_modes=("none",),
            supports_resource_limits=True,
            supports_recovery=True,
            supports_non_root=True,
            supports_read_only_root=True,
            supports_no_new_privileges=True,
            supports_capability_drop=True,
        )

    @property
    def security_level(self) -> SandboxSecurityLevel:
        return self.capabilities.security_level

    @property
    def recovery_scope_id(self) -> str:
        return self._require_recovery_scope_id()

    async def preflight(
        self,
        configuration: SandboxConfiguration,
        requirements: SandboxRequirements,
    ) -> SandboxPreflight:
        if configuration.provider != "docker" or configuration.image is None:
            raise ValueError("DockerSandboxProvider requires an image-bound Docker configuration")
        self._require_worker_identity()
        recovery_scope_id = self._require_recovery_scope_id()
        self._open_git_shadow().close()
        executable = self._require_executable()
        daemon = await self._require_local_linux_daemon(executable)
        # This Docker subcommand can contact the active daemon despite formatting
        # only a client field. Invoke it only after a local Unix endpoint is pinned.
        cli_version = await self._inspect_cli_version(
            executable,
            expected_server_version=daemon.server_version,
        )
        await self._require_local_linux_daemon(
            executable,
            expected_identity=daemon.identity,
        )
        image_identity, _image_environment = await self._inspect_image(
            executable,
            configuration.image,
            expected_architecture=daemon.architecture,
        )
        await self._require_local_linux_daemon(
            executable,
            expected_identity=daemon.identity,
        )
        return SandboxPreflight(
            provider="docker",
            ready=True,
            capabilities=self.capabilities,
            configuration_hash=canonical_json_hash(configuration.model_dump(mode="json")),
            requirements_hash=canonical_json_hash(requirements.model_dump(mode="json")),
            image_identity=image_identity,
            daemon_identity=daemon.identity,
            recovery_scope_id=recovery_scope_id,
            executable_path=executable,
            cli_version=cli_version,
            daemon_os="linux",
            daemon_architecture=daemon.architecture,
            daemon_server_version=daemon.server_version,
            endpoint_kind="local-unix",
            diagnostic="Local Linux Docker daemon and immutable runner image are ready.",
            checked_at=self.clock.now(),
        )

    async def create(
        self,
        run_id: str,
        spec: SandboxSpec,
        *,
        sandbox_id: str | None = None,
    ) -> SandboxHandle:
        if spec.configuration.provider != "docker":
            raise ValueError("DockerSandboxProvider requires provider='docker'")
        if spec.project_id is None:
            raise FleetError(
                ErrorCode.SANDBOX_CREATION_FAILED,
                "Docker execution requires an immutable project identity binding.",
                "Create the sandbox through WorkflowEngine for a registered project.",
            )
        if spec.configuration.network_mode != "none":
            raise FleetError(
                ErrorCode.SANDBOX_CAPABILITY_MISSING,
                "Docker Phase 3 execution requires network=none.",
                "Review the project sandbox configuration and retry without network access.",
            )
        executable = self._require_executable()
        self._require_worker_identity()
        if spec.environment:
            raise FleetError(
                ErrorCode.COMMAND_DENIED,
                "Ambient sandbox environment injection is forbidden.",
                "Bind non-secret values to an exact reviewed command profile instead.",
            )
        workspace = _validated_workspace(spec.workspace_host_path)
        _reject_mount_delimiters(workspace)
        _reject_mount_delimiters(self.git_shadow_path)
        if spec.image_identity is None or spec.daemon_identity is None:
            raise FleetError(
                ErrorCode.SANDBOX_IMAGE_UNAVAILABLE,
                "Docker sandbox creation has no reviewed image or daemon identity.",
                "Run sandbox preflight before creating the Run.",
            )
        daemon = await self._require_local_linux_daemon(
            executable,
            expected_identity=spec.daemon_identity,
        )
        image_identity, image_environment = await self._inspect_image(
            executable,
            spec.image_identity,
            expected_architecture=daemon.architecture,
        )
        await self._require_local_linux_daemon(
            executable,
            expected_identity=daemon.identity,
        )
        if image_identity != spec.image_identity:
            raise FleetError(
                ErrorCode.SANDBOX_IMAGE_UNAVAILABLE,
                "Docker resolved an image different from the immutable Run binding.",
                "Restore the reviewed local image and retry without using a mutable tag.",
            )
        workspace_identity = _path_identity(workspace)
        identity = sandbox_id or self.ids.new(IdPrefix.SANDBOX)
        if identity in self._prepared:
            raise FleetError(
                ErrorCode.SANDBOX_CREATION_FAILED,
                "Docker sandbox preparation is already active for this identity.",
                "Terminate the existing logical sandbox before preparing it again.",
            )
        configuration_hash = canonical_json_hash(spec.configuration.model_dump(mode="json"))
        inspection = SandboxInspection(
            sandbox_id=identity,
            provider="docker",
            ready=True,
            capabilities=self.capabilities,
            configuration_hash=configuration_hash,
            image_identity=image_identity,
            daemon_identity=daemon.identity,
            effective_network_mode="none",
            non_root=True,
            read_only_root=True,
            no_new_privileges=True,
            capabilities_dropped=True,
            resource_limits_enforced=True,
            exact_mounts=True,
            inspected_at=self.clock.now(),
        )
        handle = SandboxHandle(
            sandbox_id=identity,
            run_id=run_id,
            project_id=spec.project_id,
            workspace_host_path=str(workspace),
            provider="docker",
            capabilities=self.capabilities,
            configuration_hash=configuration_hash,
            image_identity=image_identity,
            daemon_identity=daemon.identity,
            recovery_scope_id=self._require_recovery_scope_id(),
        )
        spec_snapshot = SandboxSpec.model_validate(spec.model_dump(mode="json"))
        handle_snapshot = SandboxHandle.model_validate(handle.model_dump(mode="json"))
        result_handle = SandboxHandle.model_validate(handle_snapshot.model_dump(mode="json"))
        # Keep the validated inode alive: unlink/recreate may reuse both its number
        # and coarse timestamps once the last descriptor has been closed.
        shadow_file = self._open_git_shadow()
        try:
            prepared = _PreparedSandbox(
                spec=spec_snapshot,
                handle=handle_snapshot,
                workspace=workspace,
                image_identity=image_identity,
                image_environment=image_environment,
                inspection=inspection,
                workspace_identity=workspace_identity,
                git_shadow_identity=_shadow_identity(os.fstat(shadow_file.fileno())),
                git_shadow_file=shadow_file,
            )
            self._revalidate_prepared_paths(prepared)
            self._prepared[identity] = prepared
        except BaseException:
            shadow_file.close()
            raise
        return result_handle

    async def inspect(self, handle: SandboxHandle) -> SandboxInspection:
        prepared = self._prepared.get(handle.sandbox_id)
        if prepared is None or handle.provider != "docker" or handle != prepared.handle:
            raise FleetError(
                ErrorCode.SANDBOX_INSPECTION_FAILED,
                "Docker sandbox preparation state is unavailable.",
                "Recover the logical sandbox and start a new execution.",
            )
        return prepared.inspection

    async def exec(
        self,
        handle: SandboxHandle,
        request: ExecRequest,
        *,
        on_creation_dispatched: Callable[[], None] | None = None,
        on_resource_created: Callable[[SandboxExecutionHandle], None] | None = None,
    ) -> ExecResult:
        prepared = self._prepared.get(handle.sandbox_id)
        if prepared is None or handle.provider != "docker" or handle != prepared.handle:
            raise FleetError(
                ErrorCode.SANDBOX_EXECUTION_FAILED,
                "Docker sandbox handle is not active in this process.",
                "Recover the prior sandbox and start a new bounded execution.",
            )
        if (
            request.execution_id is None
            or request.intent_id is None
            or request.task_id is None
            or request.agent_instance_id is None
            or request.stage is None
        ):
            raise FleetError(
                ErrorCode.SANDBOX_EXECUTION_FAILED,
                "Docker execution requires every control-plane execution identity.",
                "Retry through ToolGateway; direct provider execution is unsupported.",
            )
        container_name = f"agent-fleet-{request.execution_id}"
        labels = self._labels(handle, request)
        executable = ""
        created_id: str | None = None
        create_attempted = False
        dispatch_checkpoint_failed = False
        started_at = self.clock.now()
        try:
            if request.network_mode != "none":
                raise FleetError(
                    ErrorCode.COMMAND_DENIED,
                    "The reviewed command requested an unavailable network mode.",
                    "Use a network-free verification command for Phase 3.",
                )
            self._validate_request_environment(request.environment)
            self._require_current_recovery_scope(handle.recovery_scope_id)
            self._revalidate_prepared_paths(prepared)
            executable = self._require_executable()
            create_argv = self._container_create_argv(
                executable,
                prepared,
                request,
                container_name,
                labels,
            )
            if handle.daemon_identity is None:
                raise FleetError(
                    ErrorCode.SANDBOX_EXECUTION_FAILED,
                    "Docker execution has no immutable daemon binding.",
                    "Recover the logical sandbox and start a new run.",
                )
            await self._require_local_linux_daemon(
                executable,
                expected_identity=handle.daemon_identity,
            )
            # Recheck mount roots after the final daemon round trip, immediately before
            # persisting the dispatch checkpoint and invoking container create.
            self._revalidate_prepared_paths(prepared)
            if on_creation_dispatched is not None:
                try:
                    on_creation_dispatched()
                except Exception:
                    # The transaction may have committed before its acknowledgement was
                    # lost. In either case Docker create must not be invoked or replayed.
                    dispatch_checkpoint_failed = True
                    raise
            create_attempted = True
            created = await self._call(
                create_argv,
                timeout_seconds=_DOCKER_CONTROL_TIMEOUT,
                max_output_bytes=_DOCKER_METADATA_OUTPUT_LIMIT,
            )
            if created.returncode != 0 or created.timed_out or created.output_truncated:
                raise _docker_failure(
                    ErrorCode.SANDBOX_CREATION_FAILED,
                    "Docker create did not return an authoritative bounded container identity.",
                    created,
                )
            candidate_id = created.stdout.decode("utf-8", errors="replace").strip()
            if re.fullmatch(r"[0-9a-f]{64}", candidate_id) is None:
                raise FleetError(
                    ErrorCode.SANDBOX_CREATION_FAILED,
                    "Docker returned a malformed container identity.",
                    "Keep the execution lease and reconcile the local daemon; "
                    "do not replay the command.",
                )
            created_id = candidate_id
            resource_handle = SandboxExecutionHandle(
                execution_id=request.execution_id,
                sandbox_id=handle.sandbox_id,
                run_id=handle.run_id,
                provider="docker",
                native_resource_id=created_id,
                labels=labels,
                labels_sha256=canonical_json_hash(labels),
            )
            if on_resource_created is not None:
                on_resource_created(resource_handle)
            await self._require_labels_daemon(executable, labels)
            raw_inspection = await self._inspect_container(executable, created_id)
            effective = self._validate_effective_container(
                raw_inspection,
                created_id=created_id,
                prepared=prepared,
                request=request,
                labels=labels,
            )
            effective_inspection = SandboxInspection(
                sandbox_id=handle.sandbox_id,
                provider="docker",
                ready=True,
                capabilities=self.capabilities,
                configuration_hash=cast(str, handle.configuration_hash),
                image_identity=cast(str, effective["image_identity"]),
                daemon_identity=cast(str, effective["daemon_identity"]),
                effective_network_mode="none",
                non_root=True,
                read_only_root=True,
                no_new_privileges=True,
                capabilities_dropped=True,
                resource_limits_enforced=True,
                exact_mounts=True,
                inspected_at=self.clock.now(),
            )
            await self._require_labels_daemon(executable, labels)
            execution = await self._call(
                (executable, "container", "start", "--attach", created_id),
                timeout_seconds=request.timeout_seconds,
                max_output_bytes=request.max_output_bytes,
            )
            if execution.timed_out or execution.output_truncated:
                await self._kill_exact(executable, created_id, labels)
                exit_code = 124 if execution.timed_out else 137
            else:
                await self._require_labels_daemon(executable, labels)
                state = await self._inspect_container_state(executable, created_id)
                exit_code = _validated_terminal_exit_code(state)
                if execution.returncode != exit_code:
                    raise FleetError(
                        ErrorCode.SANDBOX_EXECUTION_FAILED,
                        "Docker attach result disagreed with the terminal container state.",
                        "Treat the execution outcome as ambiguous and run Fleet recovery.",
                        details={"execution_id": request.execution_id},
                    )
            completed_at = self.clock.now()
            removed_id = created_id
            await self._remove_exact(executable, created_id, labels)
            created_id = None
            cleanup_result = SandboxCleanupResult(
                provider="docker",
                resource_id=removed_id,
                resources_found=1,
                resources_removed=1,
                reconciled=True,
                complete=True,
                completed_at=self.clock.now(),
            )
            return ExecResult(
                exit_code=exit_code,
                stdout=execution.stdout.decode("utf-8", errors="replace"),
                stderr=execution.stderr.decode("utf-8", errors="replace"),
                started_at=started_at,
                completed_at=completed_at,
                timed_out=execution.timed_out,
                output_truncated=execution.output_truncated,
                execution=SandboxExecutionMetadata(
                    execution_id=request.execution_id,
                    provider="docker",
                    resource_id_sha256=sha256_bytes(f"docker-container:{removed_id}".encode()),
                    configuration_hash=cast(str, handle.configuration_hash),
                    capabilities_hash=canonical_json_hash(
                        self.capabilities.model_dump(mode="json")
                    ),
                    inspection_hash=canonical_json_hash(
                        effective_inspection.model_dump(mode="json")
                    ),
                    inspection=effective_inspection,
                    resource_handle=resource_handle,
                    cleanup_result=cleanup_result,
                ),
            )
        except asyncio.CancelledError as cancellation_error:
            cleanup_task = asyncio.create_task(
                self._cleanup_failed_execution(
                    executable,
                    created_id=created_id,
                    container_name=container_name,
                    labels=labels,
                    create_attempted=create_attempted,
                )
            )
            try:
                cleanup = await _await_cleanup_task(cleanup_task)
            except Exception as cleanup_error:
                raise FleetError(
                    ErrorCode.SANDBOX_CLEANUP_FAILED,
                    "Docker execution was cancelled but exact reconciliation failed.",
                    "Run Fleet recovery before starting another command.",
                    details={"execution_id": request.execution_id},
                ) from cleanup_error
            _attach_cleanup_proof(
                cancellation_error,
                cleanup,
                create_attempted=create_attempted,
                labels=labels,
            )
            raise cancellation_error
        except Exception as execution_error:
            if dispatch_checkpoint_failed:
                raise
            cleanup_task = asyncio.create_task(
                self._cleanup_failed_execution(
                    executable,
                    created_id=created_id,
                    container_name=container_name,
                    labels=labels,
                    create_attempted=create_attempted,
                )
            )
            try:
                cleanup = await _await_cleanup_task(cleanup_task)
            except Exception as cleanup_error:
                raise FleetError(
                    ErrorCode.SANDBOX_CLEANUP_FAILED,
                    "Docker command failed and exact reconciliation also failed.",
                    "Run Fleet recovery before starting another command.",
                    details={
                        "execution_id": request.execution_id,
                        "original_error_type": type(execution_error).__name__,
                    },
                ) from cleanup_error
            _attach_cleanup_proof(
                execution_error,
                cleanup,
                create_attempted=create_attempted,
                labels=labels,
            )
            raise

    async def _cleanup_failed_execution(
        self,
        executable: str,
        *,
        created_id: str | None,
        container_name: str,
        labels: dict[str, str],
        create_attempted: bool,
    ) -> SandboxCleanupResult:
        if not create_attempted:
            return SandboxCleanupResult(
                provider="docker",
                resource_id=labels["agent-fleet.execution"],
                resources_found=0,
                resources_removed=0,
                reconciled=True,
                complete=True,
                completed_at=self.clock.now(),
            )
        await self._require_labels_daemon(executable, labels)
        if created_id is not None:
            await self._remove_exact(executable, created_id, labels, force=True)
            return SandboxCleanupResult(
                provider="docker",
                resource_id=created_id,
                resources_found=1,
                resources_removed=1,
                reconciled=True,
                complete=True,
                completed_at=self.clock.now(),
            )
        identities = await self._list_exact(
            executable,
            {
                "agent-fleet.installation": labels["agent-fleet.installation"],
                "agent-fleet.execution": labels["agent-fleet.execution"],
            },
        )
        await self._require_labels_daemon(executable, labels)
        if not identities:
            raise FleetError(
                ErrorCode.SANDBOX_CLEANUP_FAILED,
                "Docker create was dispatched and absence is not yet proven.",
                "Keep the execution lease for later reconciliation; do not replay the command.",
            )
        if len(identities) != 1:
            raise FleetError(
                ErrorCode.SANDBOX_CLEANUP_FAILED,
                "Docker ambiguous-create reconciliation found multiple resources.",
                "Inspect the labeled resources manually; Fleet did not delete them.",
            )
        identity = identities[0]
        inspected = await self._inspect_container(executable, identity)
        if inspected.get("Name") != f"/{container_name}":
            raise FleetError(
                ErrorCode.SANDBOX_CLEANUP_FAILED,
                "Docker ambiguous-create reconciliation found an unexpected name.",
                "Inspect the labeled resource manually; Fleet did not delete it.",
            )
        await self._remove_exact(executable, identity, labels, force=True)
        return SandboxCleanupResult(
            provider="docker",
            resource_id=identity,
            resources_found=1,
            resources_removed=1,
            reconciled=True,
            complete=True,
            completed_at=self.clock.now(),
        )

    async def cleanup_execution(self, handle: SandboxExecutionHandle) -> SandboxCleanupResult:
        if (
            handle.provider != "docker"
            or re.fullmatch(r"[0-9a-f]{64}", handle.native_resource_id) is None
        ):
            raise FleetError(
                ErrorCode.SANDBOX_CLEANUP_FAILED,
                "The persisted Docker execution identity is invalid.",
                "Inspect the lease manually; Fleet did not delete any resource.",
            )
        if canonical_json_hash(handle.labels) != handle.labels_sha256:
            raise FleetError(
                ErrorCode.SANDBOX_CLEANUP_FAILED,
                "The persisted Docker execution label binding is invalid.",
                "Inspect the lease manually; Fleet did not delete any resource.",
            )
        self._require_current_recovery_scope(handle.labels.get("agent-fleet.installation"))
        executable = self._require_executable()
        expected_daemon = handle.labels.get("agent-fleet.daemon")
        if expected_daemon is None or re.fullmatch(r"[0-9a-f]{64}", expected_daemon) is None:
            raise FleetError(
                ErrorCode.SANDBOX_CLEANUP_FAILED,
                "The persisted Docker daemon binding is invalid.",
                "Inspect the lease manually; Fleet did not delete any resource.",
            )
        await self._require_local_linux_daemon(
            executable,
            expected_identity=expected_daemon,
        )
        identities = await self._list_exact(executable, handle.labels)
        await self._require_local_linux_daemon(
            executable,
            expected_identity=expected_daemon,
        )
        exact_id_present = await self._exact_id_present(
            executable,
            handle.native_resource_id,
        )
        await self._require_local_linux_daemon(
            executable,
            expected_identity=expected_daemon,
        )
        if not identities:
            if exact_id_present:
                raise FleetError(
                    ErrorCode.SANDBOX_CLEANUP_FAILED,
                    "The persisted Docker container exists with different labels.",
                    "Inspect the exact container manually; Fleet did not delete it.",
                )
            return SandboxCleanupResult(
                provider="docker",
                resource_id=handle.native_resource_id,
                resources_found=0,
                resources_removed=0,
                reconciled=True,
                complete=True,
                completed_at=self.clock.now(),
            )
        if (
            not exact_id_present
            or len(identities) != 1
            or identities[0] != handle.native_resource_id
        ):
            raise FleetError(
                ErrorCode.SANDBOX_CLEANUP_FAILED,
                "Docker reconciliation did not match the persisted exact execution ID.",
                "Inspect the labeled resources manually; Fleet did not delete them.",
                details={"match_count": len(identities)},
            )
        await self._remove_exact(
            executable,
            handle.native_resource_id,
            handle.labels,
            force=True,
        )
        return SandboxCleanupResult(
            provider="docker",
            resource_id=handle.native_resource_id,
            resources_found=1,
            resources_removed=1,
            reconciled=True,
            complete=True,
            completed_at=self.clock.now(),
        )

    async def reconcile_execution(
        self,
        sandbox: SandboxHandle,
        request: SandboxExecutionRecoveryRequest,
    ) -> SandboxCleanupResult:
        execution_id = request.execution_id
        if (
            request.provider != "docker"
            or request.sandbox_id != sandbox.sandbox_id
            or request.run_id != sandbox.run_id
            or request.project_id != sandbox.project_id
        ):
            raise FleetError(
                ErrorCode.SANDBOX_CLEANUP_FAILED,
                "The Docker execution recovery request is outside its sandbox binding.",
                "Inspect the persisted lease manually; Fleet did not delete any resource.",
            )
        if re.fullmatch(r"exec_[0-9a-f]{32}", execution_id) is None:
            raise FleetError(
                ErrorCode.SANDBOX_CLEANUP_FAILED,
                "The persisted execution identity is malformed.",
                "Inspect the lease manually; Fleet did not delete any resource.",
            )
        self._require_current_recovery_scope(sandbox.recovery_scope_id)
        executable = self._require_executable()
        if sandbox.daemon_identity is None:
            raise FleetError(
                ErrorCode.SANDBOX_CLEANUP_FAILED,
                "The persisted sandbox has no Docker daemon binding.",
                "Inspect the lease manually; Fleet did not delete any resource.",
            )
        await self._require_local_linux_daemon(
            executable,
            expected_identity=sandbox.daemon_identity,
        )
        labels = self._sandbox_labels(sandbox)
        labels.update(
            {
                "agent-fleet.execution": execution_id,
                "agent-fleet.intent": request.intent_id,
                "agent-fleet.task": request.task_id,
                "agent-fleet.agent": request.agent_instance_id,
                "agent-fleet.stage": request.stage.value,
            }
        )
        identities = await self._list_exact(
            executable,
            {
                "agent-fleet.installation": labels["agent-fleet.installation"],
                "agent-fleet.execution": execution_id,
            },
        )
        await self._require_labels_daemon(executable, labels)
        if len(identities) > 1:
            raise FleetError(
                ErrorCode.SANDBOX_CLEANUP_FAILED,
                "Docker execution reconciliation found multiple exact-label resources.",
                "Inspect the labeled resources manually; Fleet did not delete them.",
            )
        resource_id = execution_id
        removed = 0
        if identities:
            resource_id = identities[0]
            inspected = await self._inspect_container(executable, resource_id)
            if inspected.get("Name") != f"/agent-fleet-{execution_id}":
                raise FleetError(
                    ErrorCode.SANDBOX_CLEANUP_FAILED,
                    "Docker execution reconciliation found an unexpected resource name.",
                    "Inspect the labeled resource manually; Fleet did not delete it.",
                )
            await self._remove_exact(executable, resource_id, labels, force=True)
            removed = 1
        else:
            await self._require_labels_daemon(executable, labels)
            return SandboxCleanupResult(
                provider="docker",
                resource_id=resource_id,
                resources_found=0,
                resources_removed=0,
                reconciled=not request.creation_dispatched,
                complete=not request.creation_dispatched,
                completed_at=self.clock.now(),
            )
        return SandboxCleanupResult(
            provider="docker",
            resource_id=resource_id,
            resources_found=len(identities),
            resources_removed=removed,
            reconciled=True,
            complete=True,
            completed_at=self.clock.now(),
        )

    async def terminate(self, handle: SandboxHandle) -> SandboxCleanupResult:
        self._require_current_recovery_scope(handle.recovery_scope_id)
        executable = self._require_executable()
        if handle.daemon_identity is None:
            raise FleetError(
                ErrorCode.SANDBOX_CLEANUP_FAILED,
                "The persisted sandbox has no Docker daemon binding.",
                "Inspect the lease manually; Fleet did not delete any resource.",
            )
        await self._require_local_linux_daemon(
            executable,
            expected_identity=handle.daemon_identity,
        )
        labels = self._sandbox_labels(handle)
        identities = await self._list_exact(
            executable,
            {
                "agent-fleet.installation": labels["agent-fleet.installation"],
                "agent-fleet.sandbox": handle.sandbox_id,
            },
        )
        await self._require_labels_daemon(executable, labels)
        if identities:
            raise FleetError(
                ErrorCode.SANDBOX_CLEANUP_FAILED,
                "Docker found resources not owned by an active execution lease.",
                "Recover each exact execution lease; Fleet did not delete unknown resources.",
                details={"match_count": len(identities)},
            )
        prepared = self._prepared.pop(handle.sandbox_id, None)
        if prepared is not None:
            prepared.git_shadow_file.close()
        return SandboxCleanupResult(
            provider="docker",
            resource_id=handle.sandbox_id,
            resources_found=0,
            resources_removed=0,
            reconciled=True,
            complete=True,
            completed_at=self.clock.now(),
        )

    async def _list_exact(
        self,
        executable: str,
        labels: dict[str, str],
    ) -> list[str]:
        argv = [executable, "container", "ls", "--all", "--no-trunc", "--quiet"]
        for key, value in sorted(labels.items()):
            argv.extend(("--filter", f"label={key}={value}"))
        listed = await self._call(
            tuple(argv),
            timeout_seconds=_DOCKER_CONTROL_TIMEOUT,
            max_output_bytes=_DOCKER_METADATA_OUTPUT_LIMIT,
        )
        if listed.returncode != 0 or listed.timed_out or listed.output_truncated:
            raise _docker_failure(
                ErrorCode.SANDBOX_CLEANUP_FAILED,
                "Docker resource reconciliation failed.",
                listed,
            )
        try:
            decoded = listed.stdout.decode("utf-8")
        except UnicodeDecodeError as error:
            raise FleetError(
                ErrorCode.SANDBOX_CLEANUP_FAILED,
                "Docker reconciliation returned malformed resource identities.",
                "Inspect the local daemon manually; Fleet did not delete any resource.",
            ) from error
        identities = [line.strip() for line in decoded.splitlines() if line.strip()]
        if len(identities) > 128 or any(
            re.fullmatch(r"[0-9a-f]{64}", identity) is None for identity in identities
        ):
            raise FleetError(
                ErrorCode.SANDBOX_CLEANUP_FAILED,
                "Docker reconciliation returned an invalid resource identity set.",
                "Inspect the local daemon manually; Fleet did not delete any resource.",
            )
        return identities

    async def _exact_id_present(self, executable: str, identity: str) -> bool:
        listed = await self._call(
            (
                executable,
                "container",
                "ls",
                "--all",
                "--no-trunc",
                "--quiet",
                "--filter",
                f"id={identity}",
            ),
            timeout_seconds=_DOCKER_CONTROL_TIMEOUT,
            max_output_bytes=4096,
        )
        if listed.returncode != 0 or listed.timed_out or listed.output_truncated:
            raise _docker_failure(
                ErrorCode.SANDBOX_CLEANUP_FAILED,
                "Docker exact resource lookup failed.",
                listed,
            )
        try:
            decoded = listed.stdout.decode("utf-8")
        except UnicodeDecodeError as error:
            raise FleetError(
                ErrorCode.SANDBOX_CLEANUP_FAILED,
                "Docker exact lookup returned malformed resource identities.",
                "Inspect the local daemon manually; Fleet did not delete any resource.",
            ) from error
        identities = [line.strip() for line in decoded.splitlines() if line.strip()]
        if identities not in ([], [identity]):
            raise FleetError(
                ErrorCode.SANDBOX_CLEANUP_FAILED,
                "Docker exact resource lookup returned an inconsistent identity set.",
                "Inspect the local daemon manually; Fleet did not delete any resource.",
            )
        return bool(identities)

    async def _require_local_linux_daemon(
        self,
        executable: str,
        *,
        expected_identity: str | None = None,
    ) -> _DockerDaemon:
        context = await self._call(
            (executable, "context", "inspect", "--format", "{{json .Endpoints.docker.Host}}"),
            timeout_seconds=_DOCKER_CONTROL_TIMEOUT,
            max_output_bytes=4096,
        )
        if context.returncode != 0 or context.timed_out or context.output_truncated:
            raise _docker_failure(
                ErrorCode.SANDBOX_UNAVAILABLE,
                "The local Docker daemon context is unavailable.",
                context,
            )
        try:
            endpoint = json.loads(context.stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise FleetError(
                ErrorCode.SANDBOX_UNAVAILABLE,
                "Docker returned a malformed daemon endpoint.",
                "Select a local Unix Docker context and retry.",
            ) from error
        if not isinstance(endpoint, str) or not endpoint.startswith("unix://"):
            raise FleetError(
                ErrorCode.SANDBOX_REMOTE_DAEMON_DENIED,
                "Only a local Unix Docker daemon endpoint is supported.",
                "Select a local Unix-socket Docker context; remote TCP/SSH daemons are denied.",
            )
        socket_path = endpoint.removeprefix("unix://")
        if (
            not socket_path.startswith("/")
            or "\x00" in socket_path
            or "\n" in socket_path
            or "\r" in socket_path
        ):
            raise FleetError(
                ErrorCode.SANDBOX_REMOTE_DAEMON_DENIED,
                "The Docker Unix endpoint is not an absolute canonical socket path.",
                "Select a local Unix-socket Docker context and retry.",
            )
        if self._docker_host is not None and self._docker_host != endpoint:
            raise FleetError(
                ErrorCode.SANDBOX_REMOTE_DAEMON_DENIED,
                "The Docker daemon endpoint changed after it was pinned.",
                "Restart Fleet after selecting one stable local Docker context.",
            )
        self._docker_host = endpoint
        info = await self._call(
            (
                executable,
                "info",
                "--format",
                "{{json .}}",
            ),
            timeout_seconds=_DOCKER_CONTROL_TIMEOUT,
            max_output_bytes=_DOCKER_METADATA_OUTPUT_LIMIT,
        )
        if info.returncode != 0 or info.timed_out or info.output_truncated:
            raise _docker_failure(
                ErrorCode.SANDBOX_UNAVAILABLE,
                "The Docker daemon is not reachable.",
                info,
            )
        try:
            payload = json.loads(info.stdout.decode("utf-8"))
            if not isinstance(payload, dict):
                raise TypeError("Docker info must be an object")
            os_type = payload.get("OSType")
            raw_architecture = payload.get("Architecture")
            daemon_id = payload.get("ID")
            server_version = payload.get("ServerVersion")
            memory_limit = payload.get("MemoryLimit")
            swap_limit = payload.get("SwapLimit")
            pids_limit = payload.get("PidsLimit")
            cpu_cfs_period = payload.get("CpuCfsPeriod")
            cpu_cfs_quota = payload.get("CpuCfsQuota")
            security_options = payload.get("SecurityOptions")
            init_binary = payload.get("InitBinary")
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as error:
            raise FleetError(
                ErrorCode.SANDBOX_UNAVAILABLE,
                "Docker returned malformed daemon platform metadata.",
                "Verify the daemon is running Linux containers and retry.",
            ) from error
        if os_type != "linux":
            raise FleetError(
                ErrorCode.SANDBOX_UNAVAILABLE,
                "The selected Docker daemon is not running Linux containers.",
                "Switch the local daemon to Linux-container mode and retry.",
            )
        architecture = (
            {
                "amd64": "amd64",
                "x86_64": "amd64",
                "arm64": "arm64",
                "aarch64": "arm64",
            }.get(raw_architecture)
            if isinstance(raw_architecture, str)
            else None
        )
        if (
            architecture is None
            or not isinstance(daemon_id, str)
            or not daemon_id
            or len(daemon_id) > 256
            or any(character in daemon_id for character in "\x00\r\n")
            or not isinstance(server_version, str)
            or not server_version
            or len(server_version) > 128
            or any(character in server_version for character in "\x00\r\n")
            or memory_limit is not True
            or swap_limit is not True
            or pids_limit is not True
            or cpu_cfs_period is not True
            or cpu_cfs_quota is not True
            or not isinstance(security_options, list)
            or not all(isinstance(item, str) for item in security_options)
            or not any(item.startswith("name=seccomp") for item in security_options)
            or "name=cgroupns" not in security_options
            or not isinstance(init_binary, str)
            or not init_binary
            or len(init_binary) > 256
            or any(character in init_binary for character in "\x00\r\n")
        ):
            raise FleetError(
                ErrorCode.SANDBOX_UNAVAILABLE,
                "Docker lacks required daemon identity, isolation, init, or resource support.",
                "Enable Linux seccomp, private cgroup namespaces, init, memory, swap, PID, "
                "and CPU controls, then retry.",
            )
        identity = canonical_json_hash(
            {
                "architecture": architecture,
                "daemon_id": daemon_id,
                "endpoint": endpoint,
                "os": "linux",
                "server_version": server_version,
            }
        )
        if self._docker_daemon_identity is not None and identity != self._docker_daemon_identity:
            raise FleetError(
                ErrorCode.SANDBOX_REMOTE_DAEMON_DENIED,
                "The local Docker daemon changed after it was pinned.",
                "Restore the recorded daemon or inspect the resources manually; "
                "Fleet deleted nothing.",
            )
        if expected_identity is not None and identity != expected_identity:
            raise FleetError(
                ErrorCode.SANDBOX_REMOTE_DAEMON_DENIED,
                "The local Docker daemon changed after the sandbox was recorded.",
                "Restore the recorded daemon or inspect the resources manually; "
                "Fleet deleted nothing.",
            )
        self._docker_daemon_identity = identity
        return _DockerDaemon(
            endpoint=endpoint,
            architecture=cast(Literal["amd64", "arm64"], architecture),
            identity=identity,
            server_version=server_version,
        )

    async def _inspect_cli_version(
        self,
        executable: str,
        *,
        expected_server_version: str,
    ) -> str:
        result = await self._call(
            (executable, "version", "--format", "{{json .}}"),
            timeout_seconds=_DOCKER_CONTROL_TIMEOUT,
            max_output_bytes=4096,
        )
        if result.returncode != 0 or result.timed_out or result.output_truncated:
            raise _docker_failure(
                ErrorCode.SANDBOX_UNAVAILABLE,
                "The trusted Docker CLI version could not be inspected.",
                result,
            )
        try:
            payload = json.loads(result.stdout.decode("utf-8"))
            if not isinstance(payload, dict):
                raise TypeError("Docker version must be an object")
            client = payload.get("Client")
            server = payload.get("Server")
            if not isinstance(client, dict) or not isinstance(server, dict):
                raise TypeError("Docker client and server versions must be objects")
            version = client.get("Version")
            client_api = client.get("ApiVersion", client.get("APIVersion"))
            server_api = server.get("ApiVersion", server.get("APIVersion"))
            reported_server_version = server.get("Version")
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as error:
            raise FleetError(
                ErrorCode.SANDBOX_UNAVAILABLE,
                "Docker returned malformed client/server version metadata.",
                "Repair the trusted Docker CLI installation and retry.",
            ) from error
        if (
            not isinstance(version, str)
            or not version
            or len(version) > 128
            or any(character in version for character in "\x00\r\n")
            or reported_server_version != expected_server_version
            or not _api_version_at_least(client_api, 1, 41)
            or not _api_version_at_least(server_api, 1, 41)
        ):
            raise FleetError(
                ErrorCode.SANDBOX_UNAVAILABLE,
                "Docker client/server versions cannot enforce the Phase 3 isolation contract.",
                "Use a matching Docker client and daemon with API version 1.41 or newer.",
            )
        return version

    async def _inspect_image(
        self,
        executable: str,
        reference: str,
        *,
        expected_architecture: str,
    ) -> tuple[str, tuple[tuple[str, str], ...]]:
        result = await self._call(
            (executable, "image", "inspect", reference),
            timeout_seconds=_DOCKER_CONTROL_TIMEOUT,
            max_output_bytes=_DOCKER_METADATA_OUTPUT_LIMIT,
        )
        if result.returncode != 0 or result.timed_out or result.output_truncated:
            raise _docker_failure(
                ErrorCode.SANDBOX_IMAGE_UNAVAILABLE,
                "The configured Docker runner image is not available locally.",
                result,
            )
        try:
            payload = json.loads(result.stdout.decode("utf-8"))
            if not isinstance(payload, list) or len(payload) != 1:
                raise TypeError("image inspection must contain exactly one image")
            image = payload[0]
            if not isinstance(image, dict):
                raise TypeError("image inspection entry must be an object")
            image_identity = image["Id"]
            raw_configuration = image.get("Config")
            configuration = {} if raw_configuration is None else raw_configuration
            if not isinstance(configuration, dict):
                raise TypeError("image configuration must be an object")
        except (UnicodeDecodeError, json.JSONDecodeError, IndexError, KeyError, TypeError) as error:
            raise FleetError(
                ErrorCode.SANDBOX_IMAGE_UNAVAILABLE,
                "Docker returned malformed runner image metadata.",
                "Inspect the configured local image and retry.",
            ) from error
        if (
            not isinstance(image_identity, str)
            or re.fullmatch(r"sha256:[0-9a-f]{64}", image_identity) is None
        ):
            raise FleetError(
                ErrorCode.SANDBOX_IMAGE_UNAVAILABLE,
                "The Docker runner image lacks an immutable local image identity.",
                "Use a locally present image that Docker can resolve to a sha256 image ID.",
            )
        if image.get("Os") != "linux" or image.get("Architecture") != expected_architecture:
            raise FleetError(
                ErrorCode.SANDBOX_IMAGE_UNAVAILABLE,
                "The Docker runner image platform does not match the local Linux daemon.",
                "Use a local runner image for the daemon's exact architecture.",
            )
        raw_volumes = configuration.get("Volumes")
        if raw_volumes is not None and not isinstance(raw_volumes, dict):
            raise FleetError(
                ErrorCode.SANDBOX_IMAGE_UNAVAILABLE,
                "The Docker runner image has malformed volume metadata.",
                "Use a runner image with ordinary Docker image configuration metadata.",
            )
        if raw_volumes:
            raise FleetError(
                ErrorCode.SANDBOX_IMAGE_UNAVAILABLE,
                "The Docker runner image declares volumes that would weaken the mount contract.",
                "Use a runner image with no image-declared volumes.",
            )
        raw_exposed_ports = configuration.get("ExposedPorts")
        if raw_exposed_ports is not None and not isinstance(raw_exposed_ports, dict):
            raise FleetError(
                ErrorCode.SANDBOX_IMAGE_UNAVAILABLE,
                "The Docker runner image has malformed exposed-port metadata.",
                "Use a runner image with ordinary Docker image configuration metadata.",
            )
        if raw_exposed_ports:
            raise FleetError(
                ErrorCode.SANDBOX_IMAGE_UNAVAILABLE,
                "The Docker runner image declares exposed ports outside the network contract.",
                "Use a runner image with no image-declared exposed ports.",
            )
        raw_environment = configuration.get("Env")
        environment = [] if raw_environment is None else raw_environment
        if not isinstance(environment, list) or not all(
            isinstance(item, str) for item in environment
        ):
            raise FleetError(
                ErrorCode.SANDBOX_IMAGE_UNAVAILABLE,
                "The Docker runner image has malformed environment metadata.",
                "Use a runner image with ordinary KEY=VALUE environment entries.",
            )
        image_environment: dict[str, str] = {}
        for item in environment:
            name, separator, value = item.partition("=")
            if not separator or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) is None:
                raise FleetError(
                    ErrorCode.SANDBOX_IMAGE_UNAVAILABLE,
                    "The Docker runner image has a malformed environment entry.",
                    "Use a runner image with canonical environment names.",
                )
            if name in image_environment:
                raise FleetError(
                    ErrorCode.SANDBOX_IMAGE_UNAVAILABLE,
                    "The Docker runner image contains a duplicate environment name.",
                    "Use a runner image with one canonical value for each environment name.",
                )
            if (
                name not in _SAFE_IMAGE_ENV_NAMES
                or _SENSITIVE_ENV_FRAGMENT.search(name)
                or self.redactor.contains_secret(value)
                or len(value.encode("utf-8")) > 4096
                or any(character in value for character in "\x00\r\n")
            ):
                raise FleetError(
                    ErrorCode.SANDBOX_IMAGE_UNAVAILABLE,
                    "The Docker runner image contains an environment entry outside the allowlist.",
                    "Rebuild the trusted runner image with only PATH, LANG, or LC_ALL defaults.",
                )
            image_environment[name] = value
        return image_identity, tuple(sorted(image_environment.items()))

    def _container_create_argv(
        self,
        executable: str,
        prepared: _PreparedSandbox | BaselinePreparedView,
        request: ExecRequest | BaselineRequestView,
        name: str,
        labels: dict[str, str],
        *,
        owner_kind: Literal["run", "baseline"] = "run",
    ) -> tuple[str, ...]:
        configuration = prepared.spec.configuration
        logical_cwd = request.cwd.removeprefix("./")
        workdir = "/workspace" if logical_cwd in {"", "."} else f"/workspace/{logical_cwd}"
        argv = [
            executable,
            "container",
            "create",
            "--pull=never",
            "--name",
            name,
            "--user",
            f"{self.uid}:{self.gid}",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges=true",
            "--security-opt=seccomp=builtin",
            "--read-only",
            "--network=none",
            "--cgroupns=private",
            "--ipc=private",
            "--pids-limit",
            str(configuration.pids_limit),
            "--cpus",
            _format_cpu(configuration.cpu_limit),
            "--memory",
            f"{configuration.memory_mb}m",
            "--memory-swap",
            f"{configuration.memory_mb}m",
            "--memory-swappiness",
            "0",
            "--shm-size",
            f"{configuration.shm_mb}m",
            "--restart=no",
            "--no-healthcheck",
            "--log-driver=none",
            "--ulimit",
            "nofile=1024:1024",
            "--stop-timeout",
            "1",
            "--init",
            "--mount",
            (
                f"type=bind,src={prepared.workspace},dst=/workspace,"
                f"{'readonly,' if owner_kind == 'baseline' else ''}bind-propagation=rprivate"
            ),
            "--mount",
            (
                f"type=bind,src={self.git_shadow_path},dst=/workspace/.git,"
                "readonly,bind-propagation=rprivate"
            ),
            "--tmpfs",
            (f"/tmp:rw,noexec,nosuid,nodev,size={configuration.tmpfs_mb * 1024 * 1024}"),
            "--tmpfs",
            (f"/cache:rw,noexec,nosuid,nodev,size={configuration.tmpfs_mb * 1024 * 1024}"),
            "--workdir",
            workdir,
            "--entrypoint",
            request.executable,
        ]
        for key, value in sorted(labels.items()):
            argv.extend(("--label", f"{key}={value}"))
        safe_environment = {"HOME": "/tmp/home", "PATH": _CONTROLLED_PATH}
        safe_environment.update(request.environment)
        for key, value in sorted(safe_environment.items()):
            argv.extend(("--env", f"{key}={value}"))
        argv.append(prepared.image_identity)
        argv.extend(request.argv)
        return tuple(argv)

    async def _inspect_container(self, executable: str, identity: str) -> dict[str, Any]:
        result = await self._call(
            (executable, "container", "inspect", identity),
            timeout_seconds=_DOCKER_CONTROL_TIMEOUT,
            max_output_bytes=_DOCKER_METADATA_OUTPUT_LIMIT,
        )
        if result.returncode != 0 or result.timed_out or result.output_truncated:
            raise _docker_failure(
                ErrorCode.SANDBOX_INSPECTION_FAILED,
                "Docker container inspection failed before execution.",
                result,
            )
        try:
            payload = json.loads(result.stdout.decode("utf-8"))
            if not isinstance(payload, list) or len(payload) != 1:
                raise TypeError("container inspect must return exactly one item")
            inspected = payload[0]
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as error:
            raise FleetError(
                ErrorCode.SANDBOX_INSPECTION_FAILED,
                "Docker returned malformed container inspection metadata.",
                "Inspect the daemon manually; Fleet did not start the container.",
            ) from error
        if not isinstance(inspected, dict):
            raise FleetError(
                ErrorCode.SANDBOX_INSPECTION_FAILED,
                "Docker returned an invalid container inspection object.",
                "Inspect the daemon manually; Fleet did not start the container.",
            )
        return cast(dict[str, Any], inspected)

    async def _inspect_container_state(self, executable: str, identity: str) -> dict[str, Any]:
        inspected = await self._inspect_container(executable, identity)
        state = inspected.get("State")
        if not isinstance(state, dict):
            raise FleetError(
                ErrorCode.SANDBOX_INSPECTION_FAILED,
                "Docker did not report an authoritative container exit state.",
                "Inspect the daemon manually and recover the recorded execution.",
            )
        return cast(dict[str, Any], state)

    def _validate_effective_container(
        self,
        inspected: dict[str, Any],
        *,
        created_id: str,
        prepared: _PreparedSandbox | BaselinePreparedView,
        request: ExecRequest | BaselineRequestView,
        labels: dict[str, str],
        owner_kind: Literal["run", "baseline"] = "run",
    ) -> dict[str, Any]:
        raw_configuration = inspected.get("Config")
        raw_host = inspected.get("HostConfig")
        raw_mounts = inspected.get("Mounts")
        configuration = {} if raw_configuration is None else raw_configuration
        host = {} if raw_host is None else raw_host
        mounts = [] if raw_mounts is None else raw_mounts
        if (
            not isinstance(configuration, dict)
            or not isinstance(host, dict)
            or not isinstance(mounts, list)
        ):
            raise _malformed_container_inspection()
        raw_restart = host.get("RestartPolicy")
        restart = {} if raw_restart is None else raw_restart
        raw_effective_labels = configuration.get("Labels")
        effective_labels = {} if raw_effective_labels is None else raw_effective_labels
        if not isinstance(restart, dict) or not isinstance(effective_labels, dict):
            raise _malformed_container_inspection()
        expected_binds = {
            (str(prepared.workspace), "/workspace", owner_kind == "run", "rprivate"),
            (str(self.git_shadow_path), "/workspace/.git", False, "rprivate"),
        }
        actual_binds: set[tuple[str, str, bool, str]] = set()
        mounts_valid = len(mounts) == len(expected_binds)
        for item in mounts:
            if not isinstance(item, dict) or item.get("Type") != "bind":
                mounts_valid = False
                break
            source = item.get("Source")
            destination = item.get("Destination")
            read_write = item.get("RW")
            propagation = item.get("Propagation")
            if (
                not isinstance(source, str)
                or not isinstance(destination, str)
                or not isinstance(read_write, bool)
                or not isinstance(propagation, str)
            ):
                mounts_valid = False
                break
            actual_binds.add((source, destination, read_write, propagation))
        mounts_valid = mounts_valid and len(actual_binds) == len(expected_binds)
        environment_entries = configuration.get("Env") or []
        effective_environment: dict[str, str] = {}
        environment_valid = isinstance(environment_entries, list)
        if environment_valid:
            for item in environment_entries:
                if not isinstance(item, str) or "=" not in item:
                    environment_valid = False
                    break
                name, value = item.split("=", 1)
                if (
                    re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) is None
                    or _SENSITIVE_ENV_FRAGMENT.search(name)
                    or self.redactor.contains_secret(value)
                ):
                    environment_valid = False
                    break
                if name in effective_environment:
                    environment_valid = False
                    break
                effective_environment[name] = value
        expected_environment = dict(prepared.image_environment)
        for key in set(expected_environment) - _SAFE_IMAGE_ENV_NAMES:
            expected_environment[key] = ""
        expected_environment.update({"HOME": "/tmp/home", "PATH": _CONTROLLED_PATH})
        expected_environment.update(request.environment)
        raw_tmpfs = host.get("Tmpfs")
        tmpfs = {} if raw_tmpfs is None else raw_tmpfs
        if not isinstance(tmpfs, dict):
            raise _malformed_container_inspection()
        tmpfs_valid = set(tmpfs) == {"/tmp", "/cache"} and all(
            isinstance(value, str)
            and set(value.split(","))
            == {
                "rw",
                "noexec",
                "nosuid",
                "nodev",
                f"size={prepared.spec.configuration.tmpfs_mb * 1024 * 1024}",
            }
            for value in tmpfs.values()
        )
        raw_healthcheck = configuration.get("Healthcheck")
        healthcheck = {} if raw_healthcheck is None else raw_healthcheck
        raw_ulimits = host.get("Ulimits")
        ulimits = [] if raw_ulimits is None else raw_ulimits
        raw_log_config = host.get("LogConfig")
        log_config = {} if raw_log_config is None else raw_log_config
        if (
            not isinstance(healthcheck, dict)
            or not isinstance(ulimits, list)
            or not isinstance(log_config, dict)
        ):
            raise _malformed_container_inspection()
        nofile_limit = (
            len(ulimits) == 1
            and isinstance(ulimits[0], dict)
            and set(ulimits[0]) == {"Name", "Soft", "Hard"}
            and type(ulimits[0].get("Name")) is str
            and ulimits[0].get("Name") == "nofile"
            and type(ulimits[0].get("Soft")) is int
            and ulimits[0].get("Soft") == 1024
            and type(ulimits[0].get("Hard")) is int
            and ulimits[0].get("Hard") == 1024
        )
        raw_command = configuration.get("Cmd")
        if raw_command is None:
            effective_command: list[str] | None = []
        elif isinstance(raw_command, list) and all(isinstance(item, str) for item in raw_command):
            effective_command = raw_command
        else:
            effective_command = None
        expected = {
            "id": created_id,
            "name": (
                f"/agent-fleet-{'baseline-' if owner_kind == 'baseline' else ''}"
                f"{request.execution_id}"
            ),
            "backing_image": prepared.image_identity,
            "user": f"{self.uid}:{self.gid}",
            "image": prepared.image_identity,
            "entrypoint": [request.executable],
            "cmd": list(request.argv),
            "workdir": (
                "/workspace"
                if request.cwd.removeprefix("./") in {"", "."}
                else f"/workspace/{request.cwd.removeprefix('./')}"
            ),
            "network": "none",
            "cap_drop": {"ALL"},
            "cap_add": set(),
            "read_only": True,
            "privileged": False,
            "security_options": True,
            "pids": prepared.spec.configuration.pids_limit,
            "nano_cpus": round(prepared.spec.configuration.cpu_limit * 1_000_000_000),
            "memory": prepared.spec.configuration.memory_mb * 1024 * 1024,
            "memory_swap": prepared.spec.configuration.memory_mb * 1024 * 1024,
            # Cgroup-v2 daemons may report null after accepting swappiness=0. The
            # equal memory/memory-swap hard limits still prove that no swap is available.
            "memory_swappiness": True,
            "shm": prepared.spec.configuration.shm_mb * 1024 * 1024,
            "restart": "no",
            "healthcheck_disabled": True,
            "log_driver": "none",
            "nofile_limit": True,
            "stop_timeout": 1,
            "ipc": "private",
            "cgroupns": "private",
            "pid_mode": "",
            "userns_mode": "",
            "uts_mode": "",
            "group_add": (),
            "device_cgroup_rules": (),
            "volumes_from": (),
            "init": True,
            "binds": expected_binds,
            "tmpfs": True,
            "environment": True,
            "devices": True,
            "ports": True,
            "auto_remove": False,
            "labels": labels,
        }
        raw_security_options = host.get("SecurityOpt") or []
        security_options_valid_type = isinstance(raw_security_options, list) and all(
            isinstance(item, str) for item in raw_security_options
        )
        security_options = set(raw_security_options) if security_options_valid_type else set()
        nnp_options = security_options & {
            "no-new-privileges",
            "no-new-privileges=true",
        }
        seccomp_options = {item for item in security_options if item.startswith("seccomp=")}
        security_options_valid = (
            security_options_valid_type
            and len(raw_security_options) == len(security_options)
            and len(nnp_options) == 1
            and seccomp_options == {"seccomp=builtin"}
            and security_options == nnp_options | seccomp_options
        )
        cap_drop = _optional_string_sequence(host.get("CapDrop"))
        cap_add = _optional_string_sequence(host.get("CapAdd"))
        group_add = _optional_string_sequence(host.get("GroupAdd"))
        device_cgroup_rules = _optional_string_sequence(host.get("DeviceCgroupRules"))
        volumes_from = _optional_string_sequence(host.get("VolumesFrom"))
        raw_memory_swappiness = host.get("MemorySwappiness")
        memory_swappiness_valid = raw_memory_swappiness is None or (
            isinstance(raw_memory_swappiness, int)
            and not isinstance(raw_memory_swappiness, bool)
            and raw_memory_swappiness == 0
        )
        strict_scalar_shapes = (
            all(
                type(value) is bool
                for value in (
                    host.get("ReadonlyRootfs"),
                    host.get("Privileged"),
                    host.get("Init"),
                    host.get("PublishAllPorts"),
                    host.get("AutoRemove"),
                )
            )
            and all(
                isinstance(value, int) and not isinstance(value, bool)
                for value in (
                    host.get("PidsLimit"),
                    host.get("NanoCpus"),
                    host.get("Memory"),
                    host.get("MemorySwap"),
                    host.get("ShmSize"),
                    configuration.get("StopTimeout"),
                )
            )
            and all(
                isinstance(value, str)
                for value in (
                    host.get("NetworkMode"),
                    host.get("IpcMode"),
                    host.get("CgroupnsMode"),
                    host.get("PidMode"),
                    host.get("UsernsMode"),
                    host.get("UTSMode"),
                    restart.get("Name"),
                )
            )
        )
        expected["scalar_shapes"] = True
        actual = {
            "id": inspected.get("Id"),
            "name": inspected.get("Name"),
            "backing_image": inspected.get("Image"),
            "user": configuration.get("User"),
            "image": configuration.get("Image"),
            "entrypoint": configuration.get("Entrypoint"),
            "cmd": effective_command,
            "workdir": configuration.get("WorkingDir"),
            "network": host.get("NetworkMode"),
            "cap_drop": set(cap_drop) if cap_drop is not None else None,
            "cap_add": set(cap_add) if cap_add is not None else None,
            "read_only": host.get("ReadonlyRootfs"),
            "privileged": host.get("Privileged"),
            "security_options": security_options_valid,
            "pids": host.get("PidsLimit"),
            "nano_cpus": host.get("NanoCpus"),
            "memory": host.get("Memory"),
            "memory_swap": host.get("MemorySwap"),
            "memory_swappiness": memory_swappiness_valid,
            "shm": host.get("ShmSize"),
            "restart": restart.get("Name"),
            "healthcheck_disabled": healthcheck.get("Test") == ["NONE"],
            "log_driver": log_config.get("Type"),
            "nofile_limit": nofile_limit,
            "stop_timeout": configuration.get("StopTimeout"),
            "ipc": host.get("IpcMode"),
            "cgroupns": host.get("CgroupnsMode"),
            "pid_mode": host.get("PidMode"),
            "userns_mode": host.get("UsernsMode"),
            "uts_mode": host.get("UTSMode"),
            "group_add": group_add,
            "device_cgroup_rules": device_cgroup_rules,
            "volumes_from": volumes_from,
            "init": host.get("Init"),
            "binds": actual_binds if mounts_valid else None,
            "tmpfs": tmpfs_valid,
            "environment": environment_valid and effective_environment == expected_environment,
            "devices": host.get("Devices") in (None, [])
            and host.get("DeviceRequests") in (None, []),
            "ports": host.get("PortBindings") in (None, {})
            and configuration.get("ExposedPorts") in (None, {})
            and host.get("PublishAllPorts") is False,
            "auto_remove": host.get("AutoRemove"),
            "labels": {key: effective_labels.get(key) for key in labels},
            "scalar_shapes": strict_scalar_shapes,
        }
        mismatches = sorted(key for key in expected if actual[key] != expected[key])
        if owner_kind == "baseline" and effective_labels != labels:
            mismatches.append("exact_baseline_labels")
        if mismatches:
            raise FleetError(
                ErrorCode.SANDBOX_INSPECTION_FAILED,
                "Docker effective configuration did not match the hardened request.",
                "Inspect the daemon/platform compatibility; Fleet did not start the container.",
                details={"mismatched_fields": mismatches},
            )
        return {
            "provider": "docker",
            "image_identity": prepared.image_identity,
            "daemon_identity": prepared.spec.daemon_identity,
            "network_mode": "none",
            "non_root": True,
            "read_only_root": True,
            "no_new_privileges": True,
            "capabilities_dropped": True,
            "resource_limits_enforced": True,
            "exact_mounts": True,
        }

    def _labels(self, handle: SandboxHandle, request: ExecRequest) -> dict[str, str]:
        labels = self._sandbox_labels(handle)
        labels["agent-fleet.execution"] = cast(str, request.execution_id)
        if request.intent_id is not None:
            labels["agent-fleet.intent"] = request.intent_id
        if request.task_id is not None:
            labels["agent-fleet.task"] = request.task_id
        if request.agent_instance_id is not None:
            labels["agent-fleet.agent"] = request.agent_instance_id
        if request.stage is not None:
            labels["agent-fleet.stage"] = request.stage.value
        return labels

    def _sandbox_labels(self, handle: SandboxHandle) -> dict[str, str]:
        labels = {
            "agent-fleet.managed": "true",
            "agent-fleet.installation": cast(str, handle.recovery_scope_id),
            "agent-fleet.run": handle.run_id,
            "agent-fleet.sandbox": handle.sandbox_id,
            "agent-fleet.daemon": cast(str, handle.daemon_identity),
        }
        if handle.project_id is not None:
            labels["agent-fleet.project"] = handle.project_id
        return labels

    async def _kill_exact(
        self,
        executable: str,
        identity: str,
        labels: dict[str, str],
        *,
        owner_kind: Literal["run", "baseline"] = "run",
    ) -> None:
        await self._require_labels_daemon(executable, labels)
        if owner_kind == "run":
            await self._assert_exact_labels(executable, identity, labels)
        else:
            await self._assert_exact_labels(executable, identity, labels, owner_kind=owner_kind)
        await self._require_labels_daemon(executable, labels)
        result = await self._call(
            (executable, "container", "kill", identity),
            timeout_seconds=_DOCKER_CONTROL_TIMEOUT,
            max_output_bytes=4096,
        )
        if result.returncode != 0 or result.timed_out or result.output_truncated:
            try:
                await self._require_labels_daemon(executable, labels)
                state = await self._inspect_container_state(executable, identity)
            except FleetError as state_error:
                raise _docker_failure(
                    ErrorCode.SANDBOX_CLEANUP_FAILED,
                    "Docker could not kill the bounded command container.",
                    result,
                ) from state_error
            if not (
                state.get("Status") == "exited"
                and state.get("Running") is False
                and state.get("Paused") is False
                and state.get("Restarting") is False
                and state.get("Dead") is False
            ):
                raise _docker_failure(
                    ErrorCode.SANDBOX_CLEANUP_FAILED,
                    "Docker could not kill the bounded command container.",
                    result,
                )
        await self._require_labels_daemon(executable, labels)

    async def _remove_exact(
        self,
        executable: str,
        identity: str,
        labels: dict[str, str],
        *,
        force: bool = False,
        owner_kind: Literal["run", "baseline"] = "run",
    ) -> None:
        await self._require_labels_daemon(executable, labels)
        if owner_kind == "run":
            await self._assert_exact_labels(executable, identity, labels)
        else:
            await self._assert_exact_labels(executable, identity, labels, owner_kind=owner_kind)
        await self._require_labels_daemon(executable, labels)
        argv = [executable, "container", "rm"]
        if force:
            argv.append("--force")
        argv.append(identity)
        result = await self._call(
            tuple(argv),
            timeout_seconds=_DOCKER_CONTROL_TIMEOUT,
            max_output_bytes=4096,
        )
        # A failed/timed-out rm is itself ambiguous.  Revalidate the pinned daemon
        # before classifying that result so a daemon switch cannot be hidden behind
        # the original CLI failure.
        await self._require_labels_daemon(executable, labels)
        if result.returncode != 0 or result.timed_out or result.output_truncated:
            raise _docker_failure(
                ErrorCode.SANDBOX_CLEANUP_FAILED,
                "Docker could not remove the exact managed container.",
                result,
            )

    async def _assert_exact_labels(
        self,
        executable: str,
        identity: str,
        labels: dict[str, str],
        *,
        owner_kind: Literal["run", "baseline"] = "run",
    ) -> None:
        inspected = await self._inspect_container(executable, identity)
        if inspected.get("Id") != identity:
            raise FleetError(
                ErrorCode.SANDBOX_CLEANUP_FAILED,
                "Docker resource identity changed during cleanup.",
                "Inspect the resource manually; Fleet did not delete it.",
            )
        raw_configuration = inspected.get("Config")
        if not isinstance(raw_configuration, dict):
            raise FleetError(
                ErrorCode.SANDBOX_CLEANUP_FAILED,
                "Docker resource configuration is malformed during cleanup.",
                "Inspect the resource manually; Fleet did not delete it.",
            )
        actual = raw_configuration.get("Labels") or {}
        if not isinstance(actual, dict):
            raise FleetError(
                ErrorCode.SANDBOX_CLEANUP_FAILED,
                "Docker resource labels are malformed during cleanup.",
                "Inspect the resource manually; Fleet did not delete it.",
            )
        if owner_kind == "baseline" and (
            actual != labels
            or labels.get("agent-fleet.owner-kind") != "baseline"
            or inspected.get("Name")
            != f"/agent-fleet-baseline-{labels.get('agent-fleet.execution')}"
        ):
            raise FleetError(
                ErrorCode.SANDBOX_CLEANUP_FAILED,
                "The exact baseline native name or full label set changed.",
                "Preserve this resource for explicit recovery; no deletion was attempted.",
            )
        if any(actual.get(key) != value for key, value in labels.items()):
            raise FleetError(
                ErrorCode.SANDBOX_CLEANUP_FAILED,
                "Docker resource labels do not match the persisted Fleet identity.",
                "Inspect the resource manually; Fleet did not delete it.",
            )

    async def _require_labels_daemon(
        self,
        executable: str,
        labels: dict[str, str],
    ) -> None:
        expected_identity = labels.get("agent-fleet.daemon")
        if expected_identity is None or re.fullmatch(r"[0-9a-f]{64}", expected_identity) is None:
            raise FleetError(
                ErrorCode.SANDBOX_CLEANUP_FAILED,
                "The Docker cleanup request has no valid daemon identity binding.",
                "Inspect the resource manually; Fleet did not delete it.",
            )
        await self._require_local_linux_daemon(
            executable,
            expected_identity=expected_identity,
        )

    async def _call(
        self,
        argv: tuple[str, ...],
        *,
        timeout_seconds: int,
        max_output_bytes: int,
    ) -> ProcessResult:
        if self.redactor.contains_secret_data(argv):
            raise FleetError(
                ErrorCode.COMMAND_DENIED,
                "A registered secret reached the Docker command boundary.",
                "Remove secret-bearing command or image metadata and retry.",
            )
        environment = {"DOCKER_HOST": self._docker_host} if self._docker_host is not None else {}
        if self.redactor.contains_secret_data(environment):
            raise FleetError(
                ErrorCode.COMMAND_DENIED,
                "A registered secret reached the Docker environment boundary.",
                "Select a non-secret local Unix endpoint and retry.",
            )
        try:
            return await self.runner.run(
                argv,
                environment=environment,
                cwd=None,
                timeout_seconds=timeout_seconds,
                max_output_bytes=max_output_bytes,
            )
        except ProcessTerminationError as error:
            raise FleetError(
                ErrorCode.SANDBOX_CLEANUP_FAILED,
                "A trusted Docker CLI process could not be proven fully terminated.",
                "Inspect local Docker processes and run Fleet recovery before retrying.",
            ) from error
        except ProcessInvocationError:
            raise FleetError(
                ErrorCode.SANDBOX_UNAVAILABLE,
                "The trusted Docker CLI process could not be invoked.",
                "Repair the fixed Docker installation and run `fleet doctor` again.",
            ) from None

    def _validate_request_environment(self, environment: dict[str, str]) -> None:
        for name, value in environment.items():
            if _SENSITIVE_ENV_FRAGMENT.search(name) or self.redactor.contains_secret(value):
                raise FleetError(
                    ErrorCode.COMMAND_DENIED,
                    "A prohibited secret-like command environment value was requested.",
                    "Use only the fixed non-secret verification environment allowlist.",
                    details={"environment_name": name},
                )

    def _open_git_shadow(self) -> FileIO:
        parent = self.git_shadow_path.parent
        descriptor: int | None = None
        try:
            parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            parent_stat = parent.lstat()
            if (
                parent.is_symlink()
                or not stat.S_ISDIR(parent_stat.st_mode)
                or parent_stat.st_uid != os.geteuid()
                or stat.S_IMODE(parent_stat.st_mode) & 0o022
            ):
                raise OSError("unsafe git shadow directory")
            nofollow = getattr(os, "O_NOFOLLOW", 0)
            cloexec = getattr(os, "O_CLOEXEC", 0)
            flags = os.O_RDONLY | nofollow | cloexec
            try:
                descriptor = os.open(self.git_shadow_path, flags)
            except FileNotFoundError:
                descriptor = os.open(
                    self.git_shadow_path,
                    flags | os.O_CREAT | os.O_EXCL,
                    0o400,
                )
            current = os.fstat(descriptor)
            if (
                not stat.S_ISREG(current.st_mode)
                or current.st_uid != os.geteuid()
                or current.st_nlink != 1
                or stat.S_IMODE(current.st_mode) != 0o400
                or current.st_size != 0
            ):
                raise FleetError(
                    ErrorCode.SANDBOX_UNAVAILABLE,
                    "The Fleet-owned .git shadow is not a private empty regular file.",
                    "Repair the private Fleet sandbox state directory before retrying.",
                )
            shadow_file = FileIO(descriptor, mode="rb", closefd=True)
            descriptor = None  # FileIO now owns deterministic closure and finalization.
            return shadow_file
        except OSError:
            raise FleetError(
                ErrorCode.SANDBOX_UNAVAILABLE,
                "The Fleet-owned .git shadow boundary is unavailable or unsafe.",
                "Repair the private Fleet sandbox state directory before retrying.",
            ) from None
        finally:
            if descriptor is not None:
                os.close(descriptor)

    def _require_worker_identity(self) -> None:
        if self.uid <= 0 or self.gid <= 0:
            raise FleetError(
                ErrorCode.SANDBOX_UNAVAILABLE,
                "Docker sandbox requires positive non-root worker uid and gid values.",
                "Run Fleet as an unprivileged user with access to a local Docker daemon.",
            )

    def _require_recovery_scope_id(self) -> str:
        try:
            value = self.installation_id
        except (OSError, RuntimeError):
            raise FleetError(
                ErrorCode.SANDBOX_UNAVAILABLE,
                "The Fleet installation recovery identity is unavailable.",
                "Repair the private Fleet state directory before retrying Docker.",
            ) from None
        if re.fullmatch(r"[0-9a-f]{32}", value) is None:
            raise FleetError(
                ErrorCode.SANDBOX_UNAVAILABLE,
                "The Fleet installation recovery identity is malformed.",
                "Repair the private Fleet state directory before retrying Docker.",
            )
        return value

    def _require_current_recovery_scope(self, recorded: str | None) -> None:
        current = self._require_recovery_scope_id()
        if recorded is None or not hmac.compare_digest(recorded, current):
            raise FleetError(
                ErrorCode.SANDBOX_CLEANUP_FAILED,
                "The Docker resource belongs to a different Fleet installation identity.",
                "Use the original Fleet state to inspect and recover the resource.",
            )

    def _revalidate_prepared_paths(self, prepared: _PreparedSandbox) -> None:
        workspace = _validated_workspace(str(prepared.workspace))
        with self._open_git_shadow() as current_shadow:
            shadow_identity = _shadow_identity(os.fstat(current_shadow.fileno()))
        current_path = _bind_path_stat(self.git_shadow_path)
        if (
            workspace != prepared.workspace
            or _path_identity(workspace) != prepared.workspace_identity
            or prepared.git_shadow_file.closed
            or shadow_identity != prepared.git_shadow_identity
            or _shadow_identity(current_path) != prepared.git_shadow_identity
        ):
            raise FleetError(
                ErrorCode.SANDBOX_CREATION_FAILED,
                "A Docker bind-mount path changed after sandbox preparation.",
                "Recreate the sandbox from a stable Fleet workspace and state directory.",
            )

    def _require_executable(self) -> str:
        if self.docker_executable is None:
            raise FleetError(
                ErrorCode.SANDBOX_UNAVAILABLE,
                "A trusted Docker CLI executable is not available.",
                "Install Docker, select a local Unix-socket daemon, and run `fleet doctor`.",
            )
        executable = Path(self.docker_executable)
        if not executable.is_absolute():
            raise FleetError(
                ErrorCode.SANDBOX_UNAVAILABLE,
                "The Docker adapter was not given an absolute trusted executable.",
                "Run through the Agent Fleet composition root and doctor preflight.",
            )
        return str(executable)


def _validated_workspace(value: str) -> Path:
    path = Path(value)
    try:
        raw = path.lstat()
        resolved = path.resolve(strict=True)
        resolved_stat = resolved.stat()
    except OSError as error:
        raise FleetError(
            ErrorCode.SANDBOX_CREATION_FAILED,
            "The candidate workspace is unavailable.",
            "Recover the run workspace and retry.",
        ) from error
    if (
        path.is_symlink()
        or not stat.S_ISDIR(raw.st_mode)
        or not stat.S_ISDIR(resolved_stat.st_mode)
    ):
        raise FleetError(
            ErrorCode.SANDBOX_CREATION_FAILED,
            "The candidate workspace must be a real directory, not a symlink.",
            "Use a Fleet-created candidate worktree.",
        )
    return resolved


def _path_identity(path: Path) -> tuple[int, int]:
    file_stat = _bind_path_stat(path)
    return file_stat.st_dev, file_stat.st_ino


def _shadow_identity(file_stat: os.stat_result) -> tuple[int, int, int, int]:
    return file_stat.st_dev, file_stat.st_ino, file_stat.st_mtime_ns, file_stat.st_ctime_ns


def _bind_path_stat(path: Path) -> os.stat_result:
    try:
        return path.lstat()
    except OSError as error:
        raise FleetError(
            ErrorCode.SANDBOX_CREATION_FAILED,
            "A Docker bind-mount path is unavailable.",
            "Recreate the sandbox from stable Fleet-owned paths.",
        ) from error


def _reject_mount_delimiters(path: Path) -> None:
    if "," in str(path) or "\n" in str(path) or "\r" in str(path):
        raise FleetError(
            ErrorCode.SANDBOX_CREATION_FAILED,
            "A sandbox mount path contains an unsupported delimiter.",
            "Use a repository and Fleet state path without commas or control characters.",
        )


def _validated_terminal_exit_code(state: dict[str, Any]) -> int:
    exit_code = state.get("ExitCode")
    finished_at = state.get("FinishedAt")
    oom_killed = state.get("OOMKilled")
    state_error = state.get("Error")
    state_error_empty = isinstance(state_error, str) and state_error == ""
    if (
        state.get("Status") != "exited"
        or state.get("Running") is not False
        or state.get("Paused") is not False
        or state.get("Restarting") is not False
        or state.get("Dead") is not False
        or not state_error_empty
        or not isinstance(oom_killed, bool)
        or oom_killed
        or isinstance(exit_code, bool)
        or not isinstance(exit_code, int)
        or not isinstance(finished_at, str)
        or not finished_at
    ):
        raise FleetError(
            ErrorCode.SANDBOX_EXECUTION_FAILED,
            "Docker did not report an authoritative terminal command state.",
            "Treat the execution outcome as ambiguous and run Fleet recovery.",
        )
    return exit_code


def _malformed_container_inspection() -> FleetError:
    return FleetError(
        ErrorCode.SANDBOX_INSPECTION_FAILED,
        "Docker returned malformed effective container metadata.",
        "Inspect the daemon manually; Fleet did not start the container.",
    )


def _optional_string_sequence(value: object) -> tuple[str, ...] | None:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return None
    values = tuple(value)
    return values if len(values) == len(set(values)) else None


def _attach_cleanup_proof(
    error: BaseException,
    cleanup: SandboxCleanupResult,
    *,
    create_attempted: bool,
    labels: dict[str, str],
) -> None:
    error.__dict__["_agent_fleet_cleanup_result"] = cleanup.model_dump(mode="json")
    error.__dict__["_agent_fleet_create_attempted"] = create_attempted
    error.__dict__["_agent_fleet_cleanup_binding"] = dict(labels)


async def _await_cleanup_task(
    cleanup_task: asyncio.Task[SandboxCleanupResult],
) -> SandboxCleanupResult:
    """Finish bounded resource reconciliation despite repeated caller cancellation."""

    while not cleanup_task.done():
        try:
            await asyncio.wait({cleanup_task})
        except asyncio.CancelledError:
            continue
    return cleanup_task.result()


def _format_cpu(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".")


def _api_version_at_least(value: object, major: int, minor: int) -> bool:
    if not isinstance(value, str):
        return False
    match = re.fullmatch(r"([0-9]+)\.([0-9]+)", value)
    return match is not None and (int(match.group(1)), int(match.group(2))) >= (major, minor)


def _docker_failure(code: ErrorCode, message: str, result: ProcessResult) -> FleetError:
    return FleetError(
        code,
        message,
        "Run `fleet doctor` and inspect the local Docker daemon; Fleet did not fall back.",
        details={
            "exit_code": result.returncode,
            "timed_out": result.timed_out,
            "output_truncated": result.output_truncated,
        },
    )
