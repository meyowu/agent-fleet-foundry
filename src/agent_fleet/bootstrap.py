"""Single composition root for the Phase 0/1 application."""

from __future__ import annotations

import os
import secrets
import stat
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_data_path

from agent_fleet.adapters.artifacts.local import LocalArtifactStore
from agent_fleet.adapters.config.yaml import YamlConfigurationAdapter
from agent_fleet.adapters.diagnostics.system import LocalSystemDiagnostics
from agent_fleet.adapters.executable_resolution import resolve_fixed_executable
from agent_fleet.adapters.filesystem.workspace import BoundedWorkspaceFileSystem
from agent_fleet.adapters.persistence.runtime_budgets import SqliteRuntimeBudgetStore
from agent_fleet.adapters.persistence.sqlite import SqliteStateStore
from agent_fleet.adapters.repository.git import GitRepositoryAdapter
from agent_fleet.adapters.repository.profile import StaticRepositoryProfiler
from agent_fleet.adapters.runtime.fake import FakeRuntimeAdapter
from agent_fleet.adapters.runtime.pydantic_ai import PydanticAIRuntimeAdapter
from agent_fleet.adapters.sandbox.docker import DockerSandboxProvider
from agent_fleet.adapters.sandbox.fake import FakeSandboxProvider
from agent_fleet.adapters.sandbox.local_unsafe import LocalUnsafeSandboxProvider
from agent_fleet.adapters.sandbox.process import BoundedProcessRunner
from agent_fleet.adapters.secrets.environment import EnvironmentSecretStore
from agent_fleet.adapters.system import SystemClock, UuidIdGenerator
from agent_fleet.adapters.trust.filesystem import FilesystemTrustStore
from agent_fleet.application.approvals import ApprovalService
from agent_fleet.application.artifacts import ArtifactService
from agent_fleet.application.bootstrap import BootstrapService
from agent_fleet.application.doctor import DoctorService
from agent_fleet.application.evidence import EvidenceAssembler
from agent_fleet.application.gateway import ToolGateway
from agent_fleet.application.inspection import InspectionService
from agent_fleet.application.patches import PatchService
from agent_fleet.application.permission_policy import (
    PermissionPolicyService,
    PolicyPermissionBroker,
)
from agent_fleet.application.planning import FleetPlanner
from agent_fleet.application.projects import ProjectService
from agent_fleet.application.resources import CancellationService, RecoveryService, ResourceService
from agent_fleet.application.runtime import RuntimeRegistry
from agent_fleet.application.sandboxes import SandboxRegistry
from agent_fleet.application.workflow import WorkflowEngine
from agent_fleet.domain.security import Redactor

_FIXED_DOCKER_EXECUTABLES = (
    Path("/usr/local/bin/docker"),
    Path("/opt/homebrew/bin/docker"),
    Path("/usr/bin/docker"),
    Path("/Applications/Docker.app/Contents/Resources/bin/docker"),
    Path("/snap/bin/docker"),
)


@dataclass(frozen=True)
class ApplicationContainer:
    state_root: Path
    state: SqliteStateStore
    budgets: SqliteRuntimeBudgetStore
    artifacts: ArtifactService
    projects: ProjectService
    bootstrap: BootstrapService
    workflow: WorkflowEngine
    approvals: ApprovalService
    permissions: PermissionPolicyService
    patches: PatchService
    inspection: InspectionService
    cancellation: CancellationService
    recovery: RecoveryService
    doctor: DoctorService
    sandbox: FakeSandboxProvider
    sandboxes: SandboxRegistry
    repository: GitRepositoryAdapter
    profiler: StaticRepositoryProfiler
    runtimes: RuntimeRegistry
    secrets: EnvironmentSecretStore
    redactor: Redactor


def resolve_state_root() -> Path:
    override = os.environ.get("AGENT_FLEET_HOME")
    if override:
        return Path(override).expanduser().resolve()
    return Path(user_data_path("agent-fleet", "agent-fleet")).resolve()


def _load_or_create_installation_id(root: Path) -> str:
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory_flag = getattr(os, "O_DIRECTORY", None)
    if nofollow is None or directory_flag is None or not hasattr(os, "open"):
        raise RuntimeError("secure installation identity operations are unavailable")
    try:
        root_descriptor = os.open(
            root,
            os.O_RDONLY | directory_flag | nofollow | getattr(os, "O_CLOEXEC", 0),
        )
    except OSError:
        raise RuntimeError("Fleet state directory is not a secure local directory") from None
    try:
        root_stat = os.fstat(root_descriptor)
        if (
            not stat.S_ISDIR(root_stat.st_mode)
            or root_stat.st_uid != os.geteuid()
            or root_stat.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
        ):
            raise RuntimeError("Fleet state directory ownership or permissions are unsafe")
        open_flags = os.O_RDONLY | nofollow | getattr(os, "O_CLOEXEC", 0)
        try:
            descriptor = os.open("installation-id", open_flags, dir_fd=root_descriptor)
        except FileNotFoundError:
            value = secrets.token_hex(16)
            create_flags = (
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow | getattr(os, "O_CLOEXEC", 0)
            )
            try:
                descriptor = os.open(
                    "installation-id",
                    create_flags,
                    0o600,
                    dir_fd=root_descriptor,
                )
            except FileExistsError:
                descriptor = os.open("installation-id", open_flags, dir_fd=root_descriptor)
            else:
                try:
                    _validate_installation_id_stat(os.fstat(descriptor))
                    payload = f"{value}\n".encode("ascii")
                    written = 0
                    while written < len(payload):
                        written += os.write(descriptor, payload[written:])
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
                os.fsync(root_descriptor)
                descriptor = os.open("installation-id", open_flags, dir_fd=root_descriptor)
        except OSError:
            raise RuntimeError("Fleet installation identity is not a secure file") from None
        try:
            _validate_installation_id_stat(os.fstat(descriptor))
            payload = os.read(descriptor, 34)
        finally:
            os.close(descriptor)
    finally:
        os.close(root_descriptor)
    if (
        len(payload) != 33
        or payload[-1:] != b"\n"
        or any(character not in b"0123456789abcdef" for character in payload[:-1])
    ):
        raise RuntimeError("Fleet installation identity is missing or malformed")
    return payload[:-1].decode("ascii")


def _validate_installation_id_stat(file_stat: os.stat_result) -> None:
    if (
        not stat.S_ISREG(file_stat.st_mode)
        or file_stat.st_uid != os.geteuid()
        or file_stat.st_nlink != 1
        or stat.S_IMODE(file_stat.st_mode) != 0o600
        or file_stat.st_size not in {0, 33}
    ):
        raise RuntimeError("Fleet installation identity ownership or permissions are unsafe")


def build_container(
    state_root: Path | None = None,
    *,
    migrate: bool = True,
    redactor: Redactor | None = None,
) -> ApplicationContainer:
    root = (state_root or resolve_state_root()).resolve()
    clock = SystemClock()
    ids = UuidIdGenerator()
    redaction_values = [
        item for item in os.environ.get("AGENT_FLEET_REDACT_VALUES", "").split(",") if item
    ]
    active_redactor = redactor or Redactor(redaction_values)
    if redactor is not None:
        active_redactor.register_secrets(redaction_values)
    state = SqliteStateStore(root / "state.db", clock, ids, active_redactor)
    if migrate:
        state.migrate()
    budgets = SqliteRuntimeBudgetStore(root / "state.db", clock, ids, active_redactor, state)
    local_artifacts = LocalArtifactStore(root / "artifacts")
    artifacts = ArtifactService(local_artifacts, state, clock, ids, active_redactor)
    repository = GitRepositoryAdapter(root, ids)
    profiler = StaticRepositoryProfiler()
    config = YamlConfigurationAdapter(active_redactor)
    system = LocalSystemDiagnostics(root)
    secrets = EnvironmentSecretStore(active_redactor)
    runtimes = RuntimeRegistry(
        {
            "fake": FakeRuntimeAdapter(),
            "pydantic-ai": PydanticAIRuntimeAdapter(secrets, active_redactor),
        }
    )
    sandbox = FakeSandboxProvider(clock, ids)
    process_runner = BoundedProcessRunner()
    docker_executable = resolve_fixed_executable(
        _FIXED_DOCKER_EXECUTABLES,
        expected_name="docker",
    )
    docker = DockerSandboxProvider(
        runner=process_runner,
        clock=clock,
        ids=ids,
        redactor=active_redactor,
        docker_executable=docker_executable,
        installation_id=lambda: _load_or_create_installation_id(root),
        git_shadow_path=root / "sandbox" / "git-shadow",
    )
    local_unsafe = LocalUnsafeSandboxProvider(
        runner=process_runner,
        clock=clock,
        ids=ids,
        state_root=root,
        redactor=active_redactor,
    )
    sandboxes = SandboxRegistry({"fake": sandbox, "docker": docker, "local-unsafe": local_unsafe})
    resources = ResourceService(state, repository, sandboxes, clock, ids)
    trust = FilesystemTrustStore(root / "trust" / "trust.yaml", active_redactor)
    permissions = PermissionPolicyService(
        state, trust, config, repository, clock, ids, active_redactor
    )
    permission_broker = PolicyPermissionBroker(permissions)
    planner = FleetPlanner(clock, ids)
    evidence = EvidenceAssembler(state, artifacts, clock)
    gateway = ToolGateway(
        state,
        artifacts,
        sandboxes,
        permission_broker,
        clock,
        ids,
        active_redactor,
        BoundedWorkspaceFileSystem(),
        repository=repository,
    )
    workflow = WorkflowEngine(
        state,
        repository,
        runtimes,
        sandbox,
        artifacts,
        gateway,
        resources,
        planner,
        evidence,
        config,
        clock,
        ids,
        active_redactor,
        budgets=budgets,
        permission_policy=permissions,
    )
    projects = ProjectService(
        root,
        state,
        repository,
        profiler,
        artifacts,
        config,
        clock,
        ids,
        active_redactor,
        sandbox.capabilities,
        runtimes,
        sandboxes=sandboxes,
    )
    bootstrap_service = BootstrapService(
        state_root=root,
        state=state,
        projects=projects,
        workflow=workflow,
        repository=repository,
        artifacts=artifacts,
        evidence=evidence,
        config=config,
        runtimes=runtimes,
        sandboxes=sandboxes,
        clock=clock,
        ids=ids,
        redactor=active_redactor,
    )
    return ApplicationContainer(
        state_root=root,
        state=state,
        budgets=budgets,
        artifacts=artifacts,
        projects=projects,
        bootstrap=bootstrap_service,
        workflow=workflow,
        approvals=ApprovalService(state, permissions),
        permissions=permissions,
        patches=PatchService(state, artifacts, repository, config, secrets, clock),
        inspection=InspectionService(state, artifacts, budgets),
        cancellation=CancellationService(state, resources, clock),
        recovery=RecoveryService(state, resources),
        doctor=DoctorService(
            root,
            state,
            repository,
            system,
            runtimes,
            sandboxes,
            active_redactor,
        ),
        sandbox=sandbox,
        sandboxes=sandboxes,
        repository=repository,
        profiler=profiler,
        runtimes=runtimes,
        secrets=secrets,
        redactor=active_redactor,
    )
