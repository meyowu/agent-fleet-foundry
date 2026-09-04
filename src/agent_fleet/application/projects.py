"""Safe repository registration and staged `.fleet/` initialization."""

from __future__ import annotations

import json
from pathlib import Path

from agent_fleet.application.artifacts import ArtifactService
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.ids import IdPrefix
from agent_fleet.domain.models import ArtifactKind, FleetEvent, Project
from agent_fleet.domain.security import Redactor
from agent_fleet.ports.clock import Clock
from agent_fleet.ports.config import ConfigurationPort
from agent_fleet.ports.id_generator import IdGenerator
from agent_fleet.ports.repository import RepositoryPort
from agent_fleet.ports.state_store import StateStore


class ProjectService:
    def __init__(
        self,
        state_root: Path,
        state: StateStore,
        repository: RepositoryPort,
        artifacts: ArtifactService,
        config: ConfigurationPort,
        clock: Clock,
        ids: IdGenerator,
        redactor: Redactor,
    ) -> None:
        self.state_root = state_root
        self.state = state
        self.repository = repository
        self.artifacts = artifacts
        self.config = config
        self.clock = clock
        self.ids = ids
        self.redactor = redactor

    def preview(self, root: Path) -> list[str]:
        info = self.repository.inspect(root)
        return sorted(f".fleet/{name}" for name in self.config.default_files(Path(info.root).name))

    def initialize(
        self,
        root: Path,
        *,
        runtime_name: str,
        sandbox_name: str,
    ) -> dict[str, object]:
        if runtime_name != "fake":
            raise FleetError(
                ErrorCode.RUNTIME_UNAVAILABLE,
                f"Runtime {runtime_name!r} is not available in Phase 0/1.",
                "Use `--runtime fake`; real providers arrive in Phase 2.",
            )
        if sandbox_name != "fake":
            raise FleetError(
                ErrorCode.SANDBOX_UNAVAILABLE,
                f"Sandbox {sandbox_name!r} is not available in Phase 0/1.",
                "Use `--sandbox fake`; Docker arrives in Phase 3.",
            )
        info = self.repository.inspect(root)
        if self.state_root.resolve().is_relative_to(Path(info.root).resolve()):
            raise FleetError(
                ErrorCode.PATH_OUTSIDE_SCOPE,
                "The Fleet state directory must be outside the target repository.",
                "Choose an external AGENT_FLEET_HOME and retry initialization.",
            )
        self.state.migrate()
        existing = self.state.get_project_by_root(info.root)
        now = self.clock.now()
        if existing is not None and existing.identity_hash != info.identity_hash:
            raise FleetError(
                ErrorCode.PROJECT_NOT_GIT,
                "The registered path now points to a different Git repository identity.",
                "Use a fresh state directory or restore the original repository.",
            )
        project = existing or Project(
            project_id=self.ids.new(IdPrefix.PROJECT),
            canonical_root=info.root,
            remote_fingerprint=info.remote_fingerprint,
            identity_hash=info.identity_hash,
            created_at=now,
            updated_at=now,
        )
        self.state.save_project(project)
        proposed_files = self.config.default_files(Path(info.root).name)
        self.config.validate_files(proposed_files)
        proposal_text = json.dumps(proposed_files, sort_keys=True, indent=2) + "\n"
        proposal = self.artifacts.create_text(
            kind=ArtifactKind.FLEET_CONFIG_PROPOSAL,
            project_id=project.project_id,
            content=proposal_text,
            producer="project-service",
            mime_type="application/json",
        )
        staging = self.state_root / "projects" / project.project_id / "staging" / "init"
        self.config.stage(staging, proposed_files)
        fleet_root = Path(info.root) / ".fleet"
        applied_spec = self.config.apply(fleet_root, proposed_files)
        updated_info = self.repository.inspect(Path(info.root))
        project = project.model_copy(
            update={
                "fleet_spec_hash": self.config.hash(applied_spec),
                "init_status_fingerprint": updated_info.status_fingerprint,
                "updated_at": self.clock.now(),
            }
        )
        self.state.save_project(project)
        canary = self.repository.create_canary_fixture(
            self.state_root / "projects" / project.project_id / "canaries" / "bootstrap"
        )
        correlation_id = self.ids.new(IdPrefix.CORRELATION)
        self.state.append_event(
            FleetEvent(
                event_id=self.ids.new(IdPrefix.EVENT),
                event_type="project.initialized",
                occurred_at=self.clock.now(),
                project_id=project.project_id,
                correlation_id=correlation_id,
                payload={
                    "fleet_spec_hash": project.fleet_spec_hash,
                    "proposal_artifact_id": proposal.artifact_id,
                    "runtime": "fake",
                    "sandbox": "fake",
                },
            )
        )
        return {
            "project_id": project.project_id,
            "repository": project.canonical_root,
            "fleet_spec_hash": project.fleet_spec_hash,
            "proposal_artifact_id": proposal.artifact_id,
            "canary_path": str(canary),
            "runtime": "fake",
            "sandbox": "fake",
            "security_level": "fake",
            "warning": (
                "Fake runtime and sandbox provide deterministic orchestration, "
                "not model or OS isolation."
            ),
        }
