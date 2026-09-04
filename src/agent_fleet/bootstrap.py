"""Single composition root for the Phase 0/1 application."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_data_path

from agent_fleet.adapters.artifacts.local import LocalArtifactStore
from agent_fleet.adapters.config.yaml import YamlConfigurationAdapter
from agent_fleet.adapters.diagnostics.system import LocalSystemDiagnostics
from agent_fleet.adapters.persistence.sqlite import SqliteStateStore
from agent_fleet.adapters.repository.git import GitRepositoryAdapter
from agent_fleet.adapters.repository.profile import StaticRepositoryProfiler
from agent_fleet.adapters.runtime.fake import FakeRuntimeAdapter
from agent_fleet.adapters.sandbox.fake import FakeSandboxProvider
from agent_fleet.adapters.system import SystemClock, UuidIdGenerator
from agent_fleet.application.approvals import ApprovalService
from agent_fleet.application.artifacts import ArtifactService
from agent_fleet.application.doctor import DoctorService
from agent_fleet.application.evidence import EvidenceAssembler
from agent_fleet.application.gateway import ToolGateway
from agent_fleet.application.inspection import InspectionService
from agent_fleet.application.patches import PatchService
from agent_fleet.application.permissions import BaselinePermissionBroker
from agent_fleet.application.planning import FleetPlanner
from agent_fleet.application.projects import ProjectService
from agent_fleet.application.resources import CancellationService, RecoveryService, ResourceService
from agent_fleet.application.workflow import WorkflowEngine
from agent_fleet.domain.security import Redactor


@dataclass(frozen=True)
class ApplicationContainer:
    state_root: Path
    state: SqliteStateStore
    artifacts: ArtifactService
    projects: ProjectService
    workflow: WorkflowEngine
    approvals: ApprovalService
    patches: PatchService
    inspection: InspectionService
    cancellation: CancellationService
    recovery: RecoveryService
    doctor: DoctorService
    sandbox: FakeSandboxProvider
    repository: GitRepositoryAdapter
    profiler: StaticRepositoryProfiler


def resolve_state_root() -> Path:
    override = os.environ.get("AGENT_FLEET_HOME")
    if override:
        return Path(override).expanduser().resolve()
    return Path(user_data_path("agent-fleet", "agent-fleet")).resolve()


def build_container(
    state_root: Path | None = None, *, migrate: bool = True
) -> ApplicationContainer:
    root = (state_root or resolve_state_root()).resolve()
    clock = SystemClock()
    ids = UuidIdGenerator()
    redaction_values = [
        item for item in os.environ.get("AGENT_FLEET_REDACT_VALUES", "").split(",") if item
    ]
    redactor = Redactor(redaction_values)
    state = SqliteStateStore(root / "state.db", clock, ids, redactor)
    if migrate:
        state.migrate()
    local_artifacts = LocalArtifactStore(root / "artifacts")
    artifacts = ArtifactService(local_artifacts, state, clock, ids, redactor)
    repository = GitRepositoryAdapter(root, ids)
    profiler = StaticRepositoryProfiler()
    config = YamlConfigurationAdapter(redactor)
    system = LocalSystemDiagnostics(root)
    runtime = FakeRuntimeAdapter()
    sandbox = FakeSandboxProvider(clock, ids)
    resources = ResourceService(state, repository, sandbox, clock, ids)
    permission_broker = BaselinePermissionBroker()
    planner = FleetPlanner(clock, ids)
    evidence = EvidenceAssembler(state, artifacts, clock)
    gateway = ToolGateway(state, artifacts, sandbox, permission_broker, clock, ids, redactor)
    workflow = WorkflowEngine(
        state,
        repository,
        runtime,
        sandbox,
        artifacts,
        gateway,
        resources,
        planner,
        evidence,
        config,
        clock,
        ids,
        redactor,
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
        redactor,
        sandbox.capabilities,
    )
    return ApplicationContainer(
        state_root=root,
        state=state,
        artifacts=artifacts,
        projects=projects,
        workflow=workflow,
        approvals=ApprovalService(state),
        patches=PatchService(state, artifacts, repository, config, clock),
        inspection=InspectionService(state, artifacts),
        cancellation=CancellationService(state, resources, clock),
        recovery=RecoveryService(state, resources),
        doctor=DoctorService(root, state, repository, system),
        sandbox=sandbox,
        repository=repository,
        profiler=profiler,
    )
