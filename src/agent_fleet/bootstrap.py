"""Single composition root for the Phase 0/1 application."""

from __future__ import annotations

import os
import secrets
import stat
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_data_path

from agent_fleet.adapters.artifacts.local import LocalArtifactStore
from agent_fleet.adapters.config.publication import NativeOrganizationFileSystem
from agent_fleet.adapters.config.role_bundle_assets import PackagedRoleBundles
from agent_fleet.adapters.config.yaml import YamlConfigurationAdapter
from agent_fleet.adapters.diagnostics.system import LocalSystemDiagnostics
from agent_fleet.adapters.executable_resolution import resolve_fixed_executable
from agent_fleet.adapters.filesystem.workspace import BoundedWorkspaceFileSystem
from agent_fleet.adapters.persistence.baseline import SqliteBaselineStore
from agent_fleet.adapters.persistence.conversations import SqliteConversationStore
from agent_fleet.adapters.persistence.evaluation_execution import SqliteEvaluationExecutionStore
from agent_fleet.adapters.persistence.evolution import SqliteOrganizationStore
from agent_fleet.adapters.persistence.graphs import SqliteGraphStore
from agent_fleet.adapters.persistence.model_profiles import SqliteModelProfileStore
from agent_fleet.adapters.persistence.plan_review import SqlitePlanReviewStore
from agent_fleet.adapters.persistence.runtime_budgets import SqliteRuntimeBudgetStore
from agent_fleet.adapters.persistence.sqlite import SqliteStateStore
from agent_fleet.adapters.repository.git import GitRepositoryAdapter
from agent_fleet.adapters.repository.profile import StaticRepositoryProfiler
from agent_fleet.adapters.runtime.fake import FakeRuntimeAdapter
from agent_fleet.adapters.runtime.langgraph import LangGraphRuntimeAdapter
from agent_fleet.adapters.runtime.openai_agents import OpenAIAgentsRuntimeAdapter
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
from agent_fleet.application.baseline import BaselineAdmissionService, BaselineService
from agent_fleet.application.bootstrap import BootstrapService
from agent_fleet.application.conversations import ConversationService
from agent_fleet.application.doctor import DoctorService
from agent_fleet.application.evaluation_execution import EvaluationExecutionService
from agent_fleet.application.evidence import EvidenceAssembler
from agent_fleet.application.evolution import OrganizationService
from agent_fleet.application.gateway import ToolGateway
from agent_fleet.application.inspection import InspectionService
from agent_fleet.application.model_profiles import ModelProfileService
from agent_fleet.application.patches import PatchService
from agent_fleet.application.permission_policy import (
    PermissionPolicyService,
    PolicyPermissionBroker,
)
from agent_fleet.application.plan_review import PlanReviewService
from agent_fleet.application.planning import FleetPlanner
from agent_fleet.application.projects import ProjectService
from agent_fleet.application.readiness import ReadinessService
from agent_fleet.application.resources import CancellationService, RecoveryService, ResourceService
from agent_fleet.application.role_bundles import RoleBundleService
from agent_fleet.application.runtime import RuntimeRegistry
from agent_fleet.application.sandboxes import SandboxRegistry
from agent_fleet.application.session_recovery import SessionRecoveryService
from agent_fleet.application.session_review import SessionReviewService
from agent_fleet.application.workflow import WorkflowEngine
from agent_fleet.domain.security import Redactor
from agent_fleet.ports.baseline_resources import (
    BaselineGatewayDependencies,
    BaselineResourceDependencies,
)

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
    graphs: SqliteGraphStore
    conversation_store: SqliteConversationStore
    conversations: ConversationService
    organization: OrganizationService
    artifacts: ArtifactService
    projects: ProjectService
    bootstrap: BootstrapService
    workflow: WorkflowEngine
    evaluation_execution: EvaluationExecutionService
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
    model_profiles: ModelProfileService
    plan_reviews: PlanReviewService
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


@dataclass(frozen=True)
class BaselineContainer:
    service: BaselineService
    state: SqliteStateStore
    store: SqliteBaselineStore
    repository: GitRepositoryAdapter
    sandboxes: SandboxRegistry
    resources: ResourceService
    gateway: ToolGateway
    permissions: PermissionPolicyService


def build_baseline_container(
    state_root: Path | None = None, *, redactor: Redactor | None = None
) -> BaselineContainer:
    """No SecretStore, RuntimeRegistry, model factories, agents or Workflow engine."""
    root = (state_root or resolve_state_root()).resolve()
    clock = SystemClock()
    ids = UuidIdGenerator()
    active_redactor = redactor or Redactor()
    state = SqliteStateStore(root / "state.db", clock, ids, active_redactor)
    state.migrate()
    installation = _load_or_create_installation_id(root)
    store = SqliteBaselineStore(state, installation_id=installation)
    config = YamlConfigurationAdapter(active_redactor)
    repository = GitRepositoryAdapter(root, ids)
    docker = DockerSandboxProvider(
        runner=BoundedProcessRunner(),
        clock=clock,
        ids=ids,
        redactor=active_redactor,
        docker_executable=resolve_fixed_executable(
            _FIXED_DOCKER_EXECUTABLES, expected_name="docker"
        ),
        installation_id=installation,
        git_shadow_path=root / "sandbox" / "git-shadow",
    )
    sandboxes = SandboxRegistry({"docker": docker}, baseline_providers={"docker": docker})
    resources = ResourceService(
        state,
        repository,
        sandboxes,
        clock,
        ids,
        baseline=BaselineResourceDependencies(store, repository),
    )
    trust = FilesystemTrustStore(root / "trust" / "trust.yaml", active_redactor)
    permissions = PermissionPolicyService(
        state, trust, config, repository, clock, ids, active_redactor, baseline=store
    )
    admission = BaselineAdmissionService(
        state=state,
        state_root=root,
        config=config,
        repository=repository,
        baseline_repository=repository,
        organization_files=NativeOrganizationFileSystem(active_redactor),
        trust=trust,
        permissions=permissions,
        sandboxes=sandboxes,
        clock=clock,
        ids=ids,
        redactor=active_redactor,
        installation_id=installation,
    )
    # The ordinary Gateway dependencies are real but unused by its baseline branch.
    artifacts = ArtifactService(
        LocalArtifactStore(root / "artifacts"), state, clock, ids, active_redactor
    )
    gateway = ToolGateway(
        state,
        artifacts,
        sandboxes,
        PolicyPermissionBroker(permissions),
        clock,
        ids,
        active_redactor,
        BoundedWorkspaceFileSystem(),
        repository=repository,
        baseline=BaselineGatewayDependencies(store, repository, admission.guard),
    )
    service = BaselineService(admission, store, resources, gateway, clock)
    return BaselineContainer(
        service, state, store, repository, sandboxes, resources, gateway, permissions
    )


def build_readiness_service(
    *, redactor: Redactor | None = None, state_root: Path | None = None
) -> ReadinessService:
    """Read-only composition: no stores, migrations, credentials, runtime or sandbox."""
    active_redactor = redactor or Redactor()
    return ReadinessService(
        GitRepositoryAdapter(state_root or resolve_state_root(), UuidIdGenerator()),
        StaticRepositoryProfiler(),
        YamlConfigurationAdapter(active_redactor),
        active_redactor,
    )


def build_role_bundle_service(
    *, redactor: Redactor | None = None, state_root: Path | None = None
) -> RoleBundleService:
    """No stores, migrations, credential lookup, runtime or sandbox construction."""
    active_redactor = redactor or Redactor()
    return RoleBundleService(
        GitRepositoryAdapter(state_root or resolve_state_root(), UuidIdGenerator()),
        YamlConfigurationAdapter(active_redactor),
        PackagedRoleBundles(),
        active_redactor,
    )


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
    config = YamlConfigurationAdapter(active_redactor)
    graphs = SqliteGraphStore(
        root / "state.db", clock, ids, active_redactor, local_artifacts, config=config
    )
    conversation_store = SqliteConversationStore(
        root / "state.db", clock, ids, active_redactor, state, graphs=graphs
    )
    repository = GitRepositoryAdapter(root, ids)
    profiler = StaticRepositoryProfiler()
    system = LocalSystemDiagnostics(root)
    secrets = EnvironmentSecretStore(active_redactor)
    runtimes = RuntimeRegistry(
        {
            "fake": FakeRuntimeAdapter(),
            "pydantic-ai": PydanticAIRuntimeAdapter(secrets, active_redactor),
            "openai-agents": OpenAIAgentsRuntimeAdapter(secrets, active_redactor),
            "langgraph": LangGraphRuntimeAdapter(secrets, active_redactor),
        }
    )
    model_profiles = ModelProfileService(
        store=SqliteModelProfileStore(state),
        state=state,
        repository=repository,
        runtimes=runtimes,
        secrets=secrets,
        redactor=active_redactor,
        clock=clock,
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
    evidence = EvidenceAssembler(state, artifacts, clock, config, graphs)
    organization_store = SqliteOrganizationStore(
        root / "state.db", clock, ids, active_redactor, state, config
    )
    organization = OrganizationService(
        state,
        organization_store,
        NativeOrganizationFileSystem(active_redactor),
        config,
        repository,
        artifacts,
        clock,
        ids,
        active_redactor,
        secrets,
        model_profiles=model_profiles,
    )
    plan_reviews = PlanReviewService(
        store=SqlitePlanReviewStore(state),
        state=state,
        artifacts=artifacts,
        repository=repository,
        config=config,
        organization=organization,
        clock=clock,
    )
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
    evaluation_store = SqliteEvaluationExecutionStore(state)
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
        graphs=graphs,
        organization=organization,
        permission_policy=permissions,
        conversations=conversation_store,
        model_profiles=model_profiles,
        plan_reviews=plan_reviews,
        evaluations=evaluation_store,
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
        organization=organization,
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
    approvals = ApprovalService(state, permissions)
    inspection = InspectionService(state, artifacts, budgets, graphs, model_profiles)
    cancellation = CancellationService(
        state, resources, clock, graphs, conversations=conversation_store
    )
    recovery = RecoveryService(state, resources, graphs, conversations=conversation_store)
    patches = PatchService(
        state, artifacts, repository, config, secrets, clock, graphs, organization
    )
    reviews = SessionReviewService(
        state, artifacts, inspection, patches, organization, clock, plan_reviews=plan_reviews
    )
    conversations = ConversationService(
        conversation_store,
        state,
        repository,
        workflow,
        inspection,
        artifacts,
        approvals,
        permissions,
        cancellation,
        ids,
        active_redactor,
        secrets,
        reviews,
        bootstrap_service,
        model_profiles=model_profiles,
        readiness=ReadinessService(repository, profiler, config, active_redactor),
        recovery=SessionRecoveryService(recovery, conversation_store, clock),
        baseline_factory=lambda: build_baseline_container(root, redactor=active_redactor).service,
    )
    return ApplicationContainer(
        state_root=root,
        state=state,
        budgets=budgets,
        graphs=graphs,
        conversation_store=conversation_store,
        conversations=conversations,
        organization=organization,
        artifacts=artifacts,
        projects=projects,
        bootstrap=bootstrap_service,
        workflow=workflow,
        evaluation_execution=EvaluationExecutionService(evaluation_store, workflow),
        approvals=approvals,
        permissions=permissions,
        patches=patches,
        inspection=inspection,
        cancellation=cancellation,
        recovery=recovery,
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
        model_profiles=model_profiles,
        plan_reviews=plan_reviews,
        secrets=secrets,
        redactor=active_redactor,
    )
