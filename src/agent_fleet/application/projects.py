"""Safe repository registration and staged `.fleet/` initialization."""

from __future__ import annotations

import json
from difflib import unified_diff
from pathlib import Path

from agent_fleet.application.artifacts import ArtifactService
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.ids import IdPrefix
from agent_fleet.domain.models import ArtifactKind, FleetEvent, Project, SandboxCapabilities
from agent_fleet.domain.repository_profile import RepositoryProfileResult
from agent_fleet.domain.security import (
    Redactor,
    canonical_json_hash,
    path_is_within,
    resolve_logical_path,
)
from agent_fleet.ports.clock import Clock
from agent_fleet.ports.config import ConfigurationPort
from agent_fleet.ports.id_generator import IdGenerator
from agent_fleet.ports.repository import RepositoryPort
from agent_fleet.ports.repository_profile import RepositoryProfilerPort
from agent_fleet.ports.state_store import StateStore


class ProjectService:
    def __init__(
        self,
        state_root: Path,
        state: StateStore,
        repository: RepositoryPort,
        profiler: RepositoryProfilerPort,
        artifacts: ArtifactService,
        config: ConfigurationPort,
        clock: Clock,
        ids: IdGenerator,
        redactor: Redactor,
        sandbox_capabilities: SandboxCapabilities,
    ) -> None:
        self.state_root = state_root
        self.state = state
        self.repository = repository
        self.profiler = profiler
        self.artifacts = artifacts
        self.config = config
        self.clock = clock
        self.ids = ids
        self.redactor = redactor
        self.sandbox_capabilities = sandbox_capabilities

    def preview(self, root: Path) -> dict[str, object]:
        self._reject_registered_secrets({"requested_root": str(root)})
        info = self.repository.inspect(root)
        self._reject_registered_secrets(info.model_dump(mode="json"))
        result = self.profiler.profile(Path(info.root))
        self._reject_registered_secrets(result.model_dump(mode="json"))
        profile_semantic_hash = self._validate_profile_hash(result)
        files = self.config.default_files(Path(info.root).name, result.profile)
        self._reject_registered_secrets(files)
        self.config.validate_files(files)
        preview: dict[str, object] = {
            "repository": info.root,
            "repository_profile": result.profile.model_dump(mode="json"),
            "repository_profile_semantic_sha256": profile_semantic_hash,
            "project_knowledge": result.project_knowledge.model_dump(mode="json"),
            "project_knowledge_semantic_sha256": canonical_json_hash(
                result.project_knowledge.model_dump(mode="json")
            ),
            "proposed_paths": sorted(f".fleet/{name}" for name in files),
            "proposed_files": {f".fleet/{name}": files[name] for name in sorted(files)},
            "proposal_patch": _proposal_patch(Path(info.root), files),
            "warnings": [item.message for item in result.profile.ambiguities],
        }
        self._reject_registered_secrets(preview)
        return preview

    def initialize(
        self,
        root: Path,
        *,
        runtime_name: str,
        sandbox_name: str,
    ) -> dict[str, object]:
        self._reject_registered_secrets(
            {
                "requested_root": str(root),
                "state_root": str(self.state_root),
                "runtime_name": runtime_name,
                "sandbox_name": sandbox_name,
            }
        )
        if runtime_name != "fake":
            raise FleetError(
                ErrorCode.RUNTIME_UNAVAILABLE,
                f"Runtime {runtime_name!r} is not available in Phase 0/1.5.",
                "Use `--runtime fake`; real providers arrive in Phase 2.",
            )
        if sandbox_name != "fake":
            raise FleetError(
                ErrorCode.SANDBOX_UNAVAILABLE,
                f"Sandbox {sandbox_name!r} is not available in Phase 0/1.5.",
                "Use `--sandbox fake`; Docker arrives in Phase 3.",
            )
        if self.sandbox_capabilities != SandboxCapabilities.phase1_fake():
            raise FleetError(
                ErrorCode.SANDBOX_UNAVAILABLE,
                "The selected fake sandbox reported an unexpected capability descriptor.",
                "Use the built-in non-executing fake sandbox for Phase 0/1.5.",
            )
        info = self.repository.inspect(root)
        self._reject_registered_secrets(info.model_dump(mode="json"))
        repository_root = Path(info.root)
        if path_is_within(self.state_root, repository_root) or path_is_within(
            repository_root, self.state_root
        ):
            raise FleetError(
                ErrorCode.PATH_OUTSIDE_SCOPE,
                "The Fleet state directory and target repository must be disjoint.",
                "Choose an AGENT_FLEET_HOME that is neither inside nor an ancestor of the "
                "repository, then retry initialization.",
            )
        profile_result = self.profiler.profile(Path(info.root))
        self._reject_registered_secrets(profile_result.model_dump(mode="json"))
        profile_semantic_hash = self._validate_profile_hash(profile_result)
        proposed_files = self.config.default_files(Path(info.root).name, profile_result.profile)
        self._reject_registered_secrets(proposed_files)
        self.config.validate_files(proposed_files)
        proposal_patch = _proposal_patch(Path(info.root), proposed_files)
        self._reject_registered_secrets(proposal_patch)
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
        profile_artifact = self.artifacts.create_text(
            kind=ArtifactKind.REPOSITORY_PROFILE,
            project_id=project.project_id,
            content=profile_result.profile.model_dump_json(indent=2),
            producer="static-repository-profiler",
            mime_type="application/json",
        )
        knowledge_artifact = self.artifacts.create_text(
            kind=ArtifactKind.PROJECT_KNOWLEDGE,
            project_id=project.project_id,
            content=profile_result.project_knowledge.model_dump_json(indent=2),
            producer="static-repository-profiler",
            mime_type="application/json",
        )
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
        self.config.apply(fleet_root, proposed_files)
        _, config_snapshot = self.config.load_snapshot(fleet_root / "fleet.yaml")
        config_snapshot_content = config_snapshot.model_dump_json(indent=2)
        config_snapshot_artifact = self.artifacts.create_text(
            kind=ArtifactKind.CONFIG_SNAPSHOT,
            project_id=project.project_id,
            content=config_snapshot_content,
            producer="project-service",
            mime_type="application/json",
            redact=False,
            reject_secret=True,
        )
        config_snapshot_hash = self.config.snapshot_hash(config_snapshot)
        if config_snapshot_artifact.sha256 != config_snapshot_hash:
            raise RuntimeError("configuration snapshot serialization is not deterministic")
        updated_info = self.repository.inspect(Path(info.root))
        project = project.model_copy(
            update={
                "fleet_spec_hash": config_snapshot_hash,
                "config_snapshot_artifact_id": config_snapshot_artifact.artifact_id,
                "init_status_fingerprint": updated_info.status_fingerprint,
                "repository_profile_artifact_id": profile_artifact.artifact_id,
                "repository_profile_semantic_hash": (profile_semantic_hash),
                "project_knowledge_artifact_id": knowledge_artifact.artifact_id,
                "project_knowledge_semantic_hash": canonical_json_hash(
                    profile_result.project_knowledge.model_dump(mode="json")
                ),
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
                    "config_snapshot_artifact_id": project.config_snapshot_artifact_id,
                    "proposal_artifact_id": proposal.artifact_id,
                    "repository_profile_artifact_id": profile_artifact.artifact_id,
                    "project_knowledge_artifact_id": knowledge_artifact.artifact_id,
                    "runtime": "fake",
                    "sandbox": "fake",
                    "sandbox_capabilities": self.sandbox_capabilities.model_dump(mode="json"),
                },
            )
        )
        return {
            "project_id": project.project_id,
            "repository": project.canonical_root,
            "fleet_spec_hash": project.fleet_spec_hash,
            "config_snapshot_artifact_id": project.config_snapshot_artifact_id,
            "proposal_artifact_id": proposal.artifact_id,
            "proposal_patch": proposal_patch,
            "repository_profile_artifact_id": profile_artifact.artifact_id,
            "repository_profile_semantic_sha256": (project.repository_profile_semantic_hash),
            "repository_profile_artifact_sha256": profile_artifact.sha256,
            "repository_profile": profile_result.profile.model_dump(mode="json"),
            "project_knowledge_artifact_id": knowledge_artifact.artifact_id,
            "project_knowledge_semantic_sha256": (project.project_knowledge_semantic_hash),
            "project_knowledge_artifact_sha256": knowledge_artifact.sha256,
            "project_knowledge": profile_result.project_knowledge.model_dump(mode="json"),
            "canary_path": str(canary),
            "runtime": "fake",
            "sandbox": "fake",
            "security_level": "fake",
            "sandbox_capabilities": self.sandbox_capabilities.model_dump(mode="json"),
            "warning": (
                "Fake runtime and sandbox provide deterministic orchestration, "
                "not model or OS isolation."
            ),
        }

    def _reject_registered_secrets(self, value: object) -> None:
        if self.redactor.contains_secret_data(value):
            raise FleetError(
                ErrorCode.COMMAND_DENIED,
                "Repository-derived bootstrap data contains a registered secret.",
                "Remove the secret from repository metadata before preview or initialization; "
                "no Fleet state or configuration was written.",
            )

    @staticmethod
    def _validate_profile_hash(result: RepositoryProfileResult) -> str:
        actual = canonical_json_hash(result.profile.model_dump(mode="json"))
        if result.project_knowledge.source_profile_sha256 != actual:
            raise FleetError(
                ErrorCode.ARTIFACT_INTEGRITY_FAILED,
                "Project Knowledge does not bind the supplied RepositoryProfile.",
                "Discard the profiler result and retry with a trusted deterministic adapter.",
            )
        return actual


def _proposal_patch(repository_root: Path, files: dict[str, str]) -> str:
    """Render the exact non-destructive `.fleet/` proposal as a unified diff."""

    root = repository_root.resolve(strict=True)
    fleet_root = root / ".fleet"
    if fleet_root.is_symlink() or (fleet_root.exists() and not fleet_root.is_dir()):
        raise FleetError(
            ErrorCode.PATH_OUTSIDE_SCOPE,
            "The repository .fleet path is a symlink.",
            "Replace it with a real directory before previewing or applying configuration.",
        )
    chunks: list[str] = []
    for relative, proposed in sorted(files.items()):
        current = ""
        if fleet_root.exists():
            safe_destination = resolve_logical_path(fleet_root, relative, allow_missing=True)
            if safe_destination.exists():
                if safe_destination.is_symlink() or not safe_destination.is_file():
                    raise FleetError(
                        ErrorCode.PATH_OUTSIDE_SCOPE,
                        f"Unsafe existing Fleet configuration path: .fleet/{relative}.",
                        "Replace symlinks and non-files with regular repository files.",
                    )
                if safe_destination.stat().st_size > 512_000:
                    raise FleetError(
                        ErrorCode.CONFIG_INVALID,
                        f"Existing Fleet configuration is too large: .fleet/{relative}.",
                        "Reduce the file below 512000 bytes before previewing changes.",
                    )
                current = safe_destination.read_text(encoding="utf-8")
        chunks.extend(
            unified_diff(
                current.splitlines(keepends=True),
                proposed.splitlines(keepends=True),
                fromfile=f"a/.fleet/{relative}",
                tofile=f"b/.fleet/{relative}",
            )
        )
    return "".join(chunks)
