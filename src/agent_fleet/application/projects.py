"""Safe repository registration and staged `.fleet/` initialization."""

from __future__ import annotations

import errno
import json
import os
import stat
from contextlib import suppress
from difflib import unified_diff
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from agent_fleet.application.artifacts import ArtifactService
from agent_fleet.application.runtime import RuntimeRegistry
from agent_fleet.application.sandboxes import (
    SandboxRegistry,
    requirements_for_configuration,
)
from agent_fleet.domain.bootstrap import BootstrapReport
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.ids import IdPrefix
from agent_fleet.domain.models import (
    ArtifactKind,
    FleetEvent,
    Project,
    RunStatus,
    RuntimeCapability,
    RuntimeConfiguration,
    RuntimeCredentialCheck,
    SandboxCapabilities,
    SandboxConfiguration,
)
from agent_fleet.domain.repository_profile import RepositoryProfileResult
from agent_fleet.domain.security import (
    Redactor,
    canonical_json_hash,
    path_is_within,
)
from agent_fleet.ports.clock import Clock
from agent_fleet.ports.config import ConfigurationPort
from agent_fleet.ports.id_generator import IdGenerator
from agent_fleet.ports.repository import RepositoryPort
from agent_fleet.ports.repository_profile import RepositoryProfilerPort
from agent_fleet.ports.state_store import StateStore

if TYPE_CHECKING:
    from agent_fleet.application.bootstrap import VerifiedBootstrapReport

_BOOTSTRAP_RUNTIME_CAPABILITIES = frozenset(
    {
        RuntimeCapability.STRUCTURED_OUTPUT,
        RuntimeCapability.TOOL_CALLING,
    }
)
_MAX_PROPOSAL_BASELINE_BYTES = 512_000
_PROPOSAL_READ_CHUNK_BYTES = 65_536
_UNSAFE_PROPOSAL_OPEN_ERRNOS = frozenset({errno.ELOOP, errno.ENOTDIR})


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
        runtime_registry: RuntimeRegistry,
        sandboxes: SandboxRegistry | None = None,
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
        self.runtime_registry = runtime_registry
        self.sandboxes = sandboxes

    def preview(
        self,
        root: Path,
        *,
        runtime_name: str = "fake",
        provider_model: str | None = None,
        credential_ref: str | None = None,
        sandbox_name: str = "fake",
        docker_image: str | None = None,
    ) -> dict[str, object]:
        self._reject_registered_secrets(
            {
                "requested_root": str(root),
                "runtime_name": runtime_name,
                "provider_model": provider_model,
                "sandbox_name": sandbox_name,
            }
        )
        runtime_configuration = self._runtime_configuration(
            runtime_name=runtime_name,
            provider_model=provider_model,
            credential_ref=credential_ref,
        )
        sandbox_configuration = self._sandbox_configuration(
            sandbox_name,
            docker_image=docker_image,
        )
        sandbox_capabilities = self._validate_sandbox(sandbox_configuration)
        self.runtime_registry.require(
            runtime_configuration,
            required_capabilities=_BOOTSTRAP_RUNTIME_CAPABILITIES,
            credential_check=RuntimeCredentialCheck.NONE,
        )
        info = self.repository.inspect(root)
        self._reject_registered_secrets(info.model_dump(mode="json"))
        result = self.profiler.profile(Path(info.root))
        self._reject_registered_secrets(result.model_dump(mode="json"))
        profile_semantic_hash = self._validate_profile_hash(result)
        files = self.config.default_files(
            Path(info.root).name,
            result.profile,
            runtime_name=runtime_configuration.runtime_name,
            provider_model=runtime_configuration.provider_model,
            sandbox_configuration=sandbox_configuration,
        )
        self._reject_registered_secrets(files)
        self.config.validate_files(files)
        proposal_patch = _proposal_patch(Path(info.root), files)
        preview: dict[str, object] = {
            "repository": info.root,
            "runtime": runtime_configuration.runtime_name,
            "provider_model": runtime_configuration.provider_model,
            "sandbox": sandbox_name,
            "security_level": sandbox_capabilities.security_level.value,
            "sandbox_configuration": sandbox_configuration.model_dump(mode="json"),
            "sandbox_capabilities": sandbox_capabilities.model_dump(mode="json"),
            "repository_profile": result.profile.model_dump(mode="json"),
            "repository_profile_semantic_sha256": profile_semantic_hash,
            "project_knowledge": result.project_knowledge.model_dump(mode="json"),
            "project_knowledge_semantic_sha256": canonical_json_hash(
                result.project_knowledge.model_dump(mode="json")
            ),
            "proposed_paths": sorted(f".fleet/{name}" for name in files),
            "proposed_files": {f".fleet/{name}": files[name] for name in sorted(files)},
            "proposal_sha256": _proposal_hash(files, proposal_patch),
            "proposal_patch": proposal_patch,
            "warnings": [item.message for item in result.profile.ambiguities],
            "security_warning": self._security_warning(
                runtime_configuration.runtime_name,
                sandbox_configuration.provider,
            ),
        }
        self._reject_registered_secrets(preview)
        return preview

    def register_bootstrap_canary(
        self,
        root: Path,
        *,
        sandbox_name: str,
        docker_image: str | None,
        sandbox_image_identity: str | None,
        sandbox_daemon_identity: str | None,
        allow_unsafe_local: bool,
    ) -> dict[str, object]:
        return self._initialize_without_canary(
            root,
            runtime_name="fake",
            sandbox_name=sandbox_name,
            docker_image=docker_image,
            sandbox_image_identity=sandbox_image_identity,
            sandbox_daemon_identity=sandbox_daemon_identity,
            allow_unsafe_local=allow_unsafe_local,
            trusted_canary_config=True,
            create_canary_fixture=False,
            fleet_owned_repository=True,
        )

    def _publish_bootstrap_target(
        self,
        root: Path,
        *,
        verified: VerifiedBootstrapReport,
    ) -> dict[str, object]:
        report_artifact = self.state.get_artifact(verified.report_artifact_id)
        report = BootstrapReport.model_validate_json(
            self.artifacts.read_text(verified.report_artifact_id)
        )
        canary_run = self.state.get_run(verified.canary_run_id)
        if (
            report_artifact.kind is not ArtifactKind.BOOTSTRAP_REPORT
            or report_artifact.artifact_id != verified.report_artifact_id
            or report_artifact.sha256 != verified.report_artifact_sha256
            or report_artifact.project_id != verified.canary_project_id
            or report_artifact.run_id != verified.canary_run_id
            or report_artifact.task_id != verified.canary_task_id
            or report.canary_project_id != verified.canary_project_id
            or report.canary_run_id != verified.canary_run_id
            or report.canary_task_id != verified.canary_task_id
            or report.target_identity_hash != verified.target_identity_hash
            or report.target_head_revision != verified.target_head_revision
            or report.target_status_fingerprint != verified.target_status_fingerprint
            or report.proposal_sha256 != verified.proposal_sha256
            or report.target_runtime_configuration != verified.target_runtime_configuration
            or report.sandbox_configuration != verified.sandbox_configuration
            or report.sandbox_preflight.image_identity != verified.sandbox_image_identity
            or report.sandbox_preflight.daemon_identity != verified.sandbox_daemon_identity
            or not report.publish_allowed
            or not report.cleanup_complete
            or report.outstanding_lease_count != 0
            or not report.completion_decision.verified_complete
            or verified.sandbox_configuration.provider != "docker"
            or self.state.outstanding_leases(verified.canary_run_id)
            or canary_run.status is not RunStatus.READY_FOR_REVIEW
            or not canary_run.verified_complete
            or canary_run.task_id != verified.canary_task_id
            or canary_run.project_id != verified.canary_project_id
            or canary_run.assurance_verdict is None
            or canary_run.assurance_verdict.value != "pass"
            or canary_run.evidence_bundle_artifact_id != report.evidence_bundle.artifact_id
            or canary_run.evidence_bundle_hash != report.evidence_bundle.sha256
        ):
            raise FleetError(
                ErrorCode.BOOTSTRAP_REPORT_INVALID,
                "The verified bootstrap capability is not authorized for target publication.",
                "Run a new disposable Docker canary and validate its complete evidence graph.",
            )
        runtime_configuration = verified.target_runtime_configuration
        return self._initialize_without_canary(
            root,
            runtime_name=runtime_configuration.runtime_name,
            provider_model=runtime_configuration.provider_model,
            credential_ref=runtime_configuration.credential_ref,
            sandbox_name="docker",
            docker_image=verified.sandbox_configuration.image,
            sandbox_image_identity=verified.sandbox_image_identity,
            sandbox_daemon_identity=verified.sandbox_daemon_identity,
            allow_unsafe_local=False,
            expected_proposal_hash=verified.proposal_sha256,
            expected_identity_hash=verified.target_identity_hash,
            expected_head_revision=verified.target_head_revision,
            expected_status_fingerprint=verified.target_status_fingerprint,
            create_canary_fixture=False,
            bootstrap_report_artifact_id=report_artifact.artifact_id,
            bootstrap_report_sha256=report_artifact.sha256,
            bootstrap_canary_run_id=verified.canary_run_id,
            bootstrap_verified=True,
        )

    def _initialize_without_canary(
        self,
        root: Path,
        *,
        runtime_name: str = "fake",
        provider_model: str | None = None,
        credential_ref: str | None = None,
        sandbox_name: str = "fake",
        docker_image: str | None = None,
        allow_unsafe_local: bool = False,
        expected_proposal_hash: str | None = None,
        expected_identity_hash: str | None = None,
        expected_head_revision: str | None = None,
        expected_status_fingerprint: str | None = None,
        trusted_canary_config: bool = False,
        create_canary_fixture: bool = True,
        fleet_owned_repository: bool = False,
        bootstrap_report_artifact_id: str | None = None,
        bootstrap_report_sha256: str | None = None,
        bootstrap_canary_run_id: str | None = None,
        bootstrap_verified: bool = False,
        sandbox_image_identity: str | None = None,
        sandbox_daemon_identity: str | None = None,
    ) -> dict[str, object]:
        self._reject_registered_secrets(
            {
                "requested_root": str(root),
                "state_root": str(self.state_root),
                "runtime_name": runtime_name,
                "provider_model": provider_model,
                "sandbox_name": sandbox_name,
            }
        )
        runtime_configuration = self._runtime_configuration(
            runtime_name=runtime_name,
            provider_model=provider_model,
            credential_ref=credential_ref,
        )
        sandbox_configuration = self._sandbox_configuration(
            sandbox_name,
            docker_image=docker_image,
        )
        sandbox_capabilities = self._validate_sandbox(sandbox_configuration)
        if sandbox_name == "local-unsafe" and not allow_unsafe_local:
            raise FleetError(
                ErrorCode.UNSAFE_LOCAL_CONFIRMATION_REQUIRED,
                "Local-unsafe initialization requires a separate high-risk confirmation.",
                "Pass --allow-unsafe-local explicitly; --yes is not sufficient.",
            )
        self.runtime_registry.require(
            runtime_configuration,
            required_capabilities=_BOOTSTRAP_RUNTIME_CAPABILITIES,
            credential_check=RuntimeCredentialCheck.RESOLVE,
        )
        info = self.repository.inspect(root)
        self._reject_registered_secrets(info.model_dump(mode="json"))
        repository_root = Path(info.root)
        repository_is_fleet_owned = path_is_within(repository_root, self.state_root)
        if fleet_owned_repository and not repository_is_fleet_owned:
            raise FleetError(
                ErrorCode.PATH_OUTSIDE_SCOPE,
                "A Fleet-owned repository must remain beneath the Fleet state directory.",
                "Create the bootstrap canary through the trusted BootstrapService.",
            )
        if not fleet_owned_repository and (
            repository_is_fleet_owned or path_is_within(self.state_root, repository_root)
        ):
            raise FleetError(
                ErrorCode.PATH_OUTSIDE_SCOPE,
                "The Fleet state directory and target repository must be disjoint.",
                "Choose an AGENT_FLEET_HOME that is neither inside nor an ancestor of the "
                "repository, then retry initialization.",
            )
        expected_repository_values = {
            "identity_hash": expected_identity_hash,
            "head_revision": expected_head_revision,
            "status_fingerprint": expected_status_fingerprint,
        }
        actual_repository_values = {
            "identity_hash": info.identity_hash,
            "head_revision": info.head_revision,
            "status_fingerprint": info.status_fingerprint,
        }
        mismatched_repository_values = sorted(
            name
            for name, expected in expected_repository_values.items()
            if expected is not None and actual_repository_values[name] != expected
        )
        if mismatched_repository_values:
            raise FleetError(
                ErrorCode.BOOTSTRAP_TARGET_DRIFTED,
                "The target repository changed after bootstrap evidence was recorded.",
                "Review a fresh initialization proposal and run the canary again.",
                details={"mismatched_fields": mismatched_repository_values},
            )
        profile_result = self.profiler.profile(Path(info.root))
        self._reject_registered_secrets(profile_result.model_dump(mode="json"))
        profile_semantic_hash = self._validate_profile_hash(profile_result)
        proposed_files = self.config.default_files(
            Path(info.root).name,
            profile_result.profile,
            runtime_name=runtime_configuration.runtime_name,
            provider_model=runtime_configuration.provider_model,
            sandbox_configuration=sandbox_configuration,
            trusted_canary=trusted_canary_config,
        )
        self._reject_registered_secrets(proposed_files)
        self.config.validate_files(proposed_files)
        proposal_patch = _proposal_patch(Path(info.root), proposed_files)
        self._reject_registered_secrets(proposal_patch)
        proposal_hash = _proposal_hash(proposed_files, proposal_patch)
        if expected_proposal_hash is not None and proposal_hash != expected_proposal_hash:
            raise FleetError(
                ErrorCode.CONFIG_INVALID,
                "The Fleet initialization proposal changed after it was reviewed.",
                "Run `fleet init --preview` again, review the new patch, and retry explicitly.",
            )
        fleet_root = Path(info.root) / ".fleet"
        # Reject conflicts before migration, project updates, or artifact creation. Phase 2
        # deliberately does not overwrite a user-editable .fleet tree in place.
        self.config.check_apply(fleet_root, proposed_files)
        self.state.migrate()
        existing = self.state.get_project_by_root(info.root)
        now = self.clock.now()
        if existing is not None and existing.identity_hash != info.identity_hash:
            raise FleetError(
                ErrorCode.PROJECT_NOT_GIT,
                "The registered path now points to a different Git repository identity.",
                "Use a fresh state directory or restore the original repository.",
            )
        runtime_fields = {
            "runtime_name": runtime_configuration.runtime_name,
            "provider_model": runtime_configuration.provider_model,
            "credential_ref": runtime_configuration.credential_ref,
            "sandbox_name": sandbox_configuration.provider,
            "sandbox_configuration": sandbox_configuration,
            "sandbox_image_identity": sandbox_image_identity,
            "sandbox_daemon_identity": sandbox_daemon_identity,
            "bootstrap_report_artifact_id": bootstrap_report_artifact_id,
            "bootstrap_report_sha256": bootstrap_report_sha256,
            "bootstrap_canary_run_id": bootstrap_canary_run_id,
            "bootstrap_verified": bootstrap_verified,
        }
        if existing is None:
            project = Project(
                project_id=self.ids.new(IdPrefix.PROJECT),
                canonical_root=info.root,
                remote_fingerprint=info.remote_fingerprint,
                identity_hash=info.identity_hash,
                created_at=now,
                updated_at=now,
                **runtime_fields,
            )
        else:
            project = Project.model_validate(
                {
                    **existing.model_dump(mode="json"),
                    **runtime_fields,
                    "updated_at": now,
                }
            )
        staging = (
            self.state_root / "projects" / project.project_id / "staging" / f"init-{proposal_hash}"
        )
        self.config.stage(staging, proposed_files)
        _, config_snapshot = self.config.load_snapshot(staging / "fleet.yaml")
        config_snapshot_content = config_snapshot.model_dump_json(indent=2)
        config_snapshot_hash = self.config.snapshot_hash(config_snapshot)
        canary = (
            self.repository.create_canary_fixture(
                self.state_root / "projects" / project.project_id / "canaries" / "bootstrap"
            )
            if create_canary_fixture
            else None
        )
        self.config.apply(fleet_root, proposed_files)
        _, applied_snapshot = self.config.load_snapshot(fleet_root / "fleet.yaml")
        applied_snapshot_hash = self.config.snapshot_hash(applied_snapshot)
        if applied_snapshot_hash != config_snapshot_hash:
            raise FleetError(
                ErrorCode.ARTIFACT_INTEGRITY_FAILED,
                "The applied Fleet configuration differs from the validated staging snapshot.",
                "Do not run the project; inspect or remove the .fleet tree and initialize again.",
            )
        config_snapshot = applied_snapshot
        config_snapshot_content = config_snapshot.model_dump_json(indent=2)
        config_snapshot_hash = applied_snapshot_hash
        updated_info = self.repository.inspect(Path(info.root))
        project = Project.model_validate(
            {
                **project.model_dump(mode="json"),
                "fleet_spec_hash": config_snapshot_hash,
                "init_status_fingerprint": updated_info.status_fingerprint,
                **runtime_fields,
                "updated_at": self.clock.now(),
            }
        )
        # From this write onward, Fleet-owned state and the active .fleet runtime/hash agree.
        # Artifact identifiers are attached only after their rows exist.
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
        config_snapshot_artifact = self.artifacts.create_text(
            kind=ArtifactKind.CONFIG_SNAPSHOT,
            project_id=project.project_id,
            content=config_snapshot_content,
            producer="project-service",
            mime_type="application/json",
            redact=False,
            reject_secret=True,
        )
        if config_snapshot_artifact.sha256 != config_snapshot_hash:
            raise RuntimeError("configuration snapshot serialization is not deterministic")
        project = Project.model_validate(
            {
                **project.model_dump(mode="json"),
                "config_snapshot_artifact_id": config_snapshot_artifact.artifact_id,
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
                    "runtime": runtime_configuration.runtime_name,
                    "provider_model": runtime_configuration.provider_model,
                    "sandbox": sandbox_configuration.provider,
                    "sandbox_configuration": sandbox_configuration.model_dump(mode="json"),
                    "sandbox_capabilities": sandbox_capabilities.model_dump(mode="json"),
                    "bootstrap_report_artifact_id": bootstrap_report_artifact_id,
                    "bootstrap_canary_run_id": bootstrap_canary_run_id,
                    "bootstrap_verified": bootstrap_verified,
                },
            )
        )
        return {
            "project_id": project.project_id,
            "repository": project.canonical_root,
            "fleet_spec_hash": project.fleet_spec_hash,
            "config_snapshot_artifact_id": project.config_snapshot_artifact_id,
            "proposal_artifact_id": proposal.artifact_id,
            "proposal_sha256": proposal_hash,
            "proposal_patch": proposal_patch,
            "repository_profile_artifact_id": profile_artifact.artifact_id,
            "repository_profile_semantic_sha256": (project.repository_profile_semantic_hash),
            "repository_profile_artifact_sha256": profile_artifact.sha256,
            "repository_profile": profile_result.profile.model_dump(mode="json"),
            "project_knowledge_artifact_id": knowledge_artifact.artifact_id,
            "project_knowledge_semantic_sha256": (project.project_knowledge_semantic_hash),
            "project_knowledge_artifact_sha256": knowledge_artifact.sha256,
            "project_knowledge": profile_result.project_knowledge.model_dump(mode="json"),
            "canary_path": str(canary) if canary is not None else None,
            "runtime": runtime_configuration.runtime_name,
            "provider_model": runtime_configuration.provider_model,
            "sandbox": sandbox_configuration.provider,
            "security_level": sandbox_capabilities.security_level.value,
            "sandbox_configuration": sandbox_configuration.model_dump(mode="json"),
            "sandbox_capabilities": sandbox_capabilities.model_dump(mode="json"),
            "bootstrap_report_artifact_id": bootstrap_report_artifact_id,
            "bootstrap_report_sha256": bootstrap_report_sha256,
            "bootstrap_canary_run_id": bootstrap_canary_run_id,
            "bootstrap_verified": bootstrap_verified,
            "warning": self._security_warning(
                runtime_configuration.runtime_name,
                sandbox_configuration.provider,
            ),
        }

    @staticmethod
    def _runtime_configuration(
        *,
        runtime_name: str,
        provider_model: str | None,
        credential_ref: str | None,
    ) -> RuntimeConfiguration:
        try:
            return RuntimeConfiguration(
                runtime_name=runtime_name,
                provider_model=provider_model,
                credential_ref=credential_ref,
            )
        except ValueError:
            raise FleetError(
                ErrorCode.CONFIG_INVALID,
                "The requested runtime selection is invalid.",
                (
                    "Use `fake` without provider metadata, or provide an explicit compatible "
                    "runtime, provider model, and env credential reference."
                ),
            ) from None

    @staticmethod
    def _sandbox_configuration(
        sandbox_name: str,
        *,
        docker_image: str | None,
    ) -> SandboxConfiguration:
        try:
            return SandboxConfiguration(
                provider=sandbox_name,
                image=docker_image,
                network_mode=(
                    "approved-unrestricted" if sandbox_name == "local-unsafe" else "none"
                ),
            )
        except ValueError:
            raise FleetError(
                ErrorCode.CONFIG_INVALID,
                "The requested sandbox configuration is invalid.",
                "Use fake, Docker with an explicit local image, or explicit local-unsafe.",
            ) from None

    def _validate_sandbox(
        self,
        configuration: SandboxConfiguration,
    ) -> SandboxCapabilities:
        if self.sandboxes is not None:
            provider = self.sandboxes.require(
                configuration,
                requirements_for_configuration(configuration),
            )
            return provider.capabilities
        if configuration.provider != "fake":
            raise FleetError(
                ErrorCode.SANDBOX_UNAVAILABLE,
                f"Sandbox {configuration.provider!r} is not registered.",
                "Construct ProjectService with the exact sandbox registry.",
            )
        if self.sandbox_capabilities != SandboxCapabilities.phase1_fake():
            raise FleetError(
                ErrorCode.SANDBOX_UNAVAILABLE,
                "The selected fake sandbox reported an unexpected capability descriptor.",
                "Use the built-in non-executing FakeSandbox.",
            )
        return self.sandbox_capabilities

    @staticmethod
    def _security_warning(runtime_name: str, sandbox_name: str) -> str:
        if sandbox_name == "fake":
            return (
                "FakeSandbox provides deterministic orchestration only; it executes no "
                "project code and cannot produce independently verified evidence."
            )
        if sandbox_name == "local-unsafe":
            return (
                "local-unsafe executes reviewed commands directly on the host without "
                "isolation; each run requires a separate explicit confirmation."
            )
        if runtime_name == "fake":
            return "The fake runtime drives reviewed commands inside the isolated Docker sandbox."
        return (
            "The selected runtime may contact its configured model provider from the control "
            "plane; project commands execute only through the isolated Docker sandbox."
        )

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

    try:
        return _render_proposal_patch(repository_root, files)
    except FleetError:
        raise
    except (OSError, UnicodeError, ValueError, NotImplementedError) as error:
        raise FleetError(
            ErrorCode.CONFIG_INVALID,
            "The existing Fleet configuration could not be inspected safely.",
            "Replace invalid or unreadable .fleet files with bounded UTF-8 regular files.",
        ) from error


def _render_proposal_patch(repository_root: Path, files: dict[str, str]) -> str:
    """Render after the public wrapper has established a typed filesystem boundary."""

    repository_fd = _open_proposal_directory(repository_root)
    fleet_fd: int | None = None
    try:
        with suppress(FileNotFoundError):
            fleet_fd = _open_proposal_directory(".fleet", dir_fd=repository_fd)

        chunks: list[str] = []
        for relative, proposed in sorted(files.items()):
            current = ""
            if fleet_fd is not None:
                baseline = _read_proposal_baseline(fleet_fd, relative)
                if baseline is not None:
                    current = baseline.decode("utf-8")
            chunks.extend(
                unified_diff(
                    current.splitlines(keepends=True),
                    proposed.splitlines(keepends=True),
                    fromfile=f"a/.fleet/{relative}",
                    tofile=f"b/.fleet/{relative}",
                )
            )
        return "".join(chunks)
    finally:
        if fleet_fd is not None:
            os.close(fleet_fd)
        os.close(repository_fd)


def _open_proposal_directory(path: Path | str, *, dir_fd: int | None = None) -> int:
    """Open one real directory without following its final path component."""

    flags = os.O_RDONLY | _required_open_flag("O_DIRECTORY") | _required_open_flag("O_NOFOLLOW")
    flags |= getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(path, flags) if dir_fd is None else os.open(path, flags, dir_fd=dir_fd)
    except OSError as error:
        if error.errno in _UNSAFE_PROPOSAL_OPEN_ERRNOS:
            raise _unsafe_proposal_path() from None
        raise
    try:
        if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise _unsafe_proposal_path()
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _read_proposal_baseline(fleet_fd: int, relative: str) -> bytes | None:
    """Read one existing proposal baseline relative to a stable `.fleet` FD."""

    parts = _proposal_path_parts(relative)
    parent_fd = fleet_fd
    opened_directories: list[int] = []
    try:
        for component in parts[:-1]:
            try:
                child_fd = _open_proposal_directory(component, dir_fd=parent_fd)
            except FileNotFoundError:
                return None
            opened_directories.append(child_fd)
            parent_fd = child_fd
        try:
            return _read_bounded_proposal_file(parent_fd, parts[-1], relative)
        except FileNotFoundError:
            return None
    finally:
        for descriptor in reversed(opened_directories):
            os.close(descriptor)


def _read_bounded_proposal_file(parent_fd: int, name: str, relative: str) -> bytes:
    """Open and read a stable regular file without exceeding the proposal ceiling."""

    flags = os.O_RDONLY | _required_open_flag("O_NOFOLLOW")
    flags |= _required_open_flag("O_NONBLOCK") | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(name, flags, dir_fd=parent_fd)
    except OSError as error:
        if error.errno in _UNSAFE_PROPOSAL_OPEN_ERRNOS:
            raise _unsafe_proposal_path(relative) from None
        raise
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise _unsafe_proposal_path(relative)
        if opened.st_size > _MAX_PROPOSAL_BASELINE_BYTES:
            raise _oversized_proposal_file(relative)

        chunks: list[bytes] = []
        remaining = _MAX_PROPOSAL_BASELINE_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(_PROPOSAL_READ_CHUNK_BYTES, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)

    if len(content) > _MAX_PROPOSAL_BASELINE_BYTES or (
        after.st_size > _MAX_PROPOSAL_BASELINE_BYTES
    ):
        raise _oversized_proposal_file(relative)
    if (
        (after.st_dev, after.st_ino) != (opened.st_dev, opened.st_ino)
        or after.st_size != opened.st_size
        or after.st_mtime_ns != opened.st_mtime_ns
        or after.st_ctime_ns != opened.st_ctime_ns
        or len(content) != after.st_size
    ):
        raise FleetError(
            ErrorCode.CONFIG_INVALID,
            "An existing Fleet configuration changed while its proposal was rendered.",
            "Stop concurrent writers, review the .fleet tree, and preview again.",
        )
    return content


def _proposal_path_parts(relative: str) -> tuple[str, ...]:
    path = PurePosixPath(relative)
    if (
        not relative
        or relative.startswith("/")
        or "\\" in relative
        or "\x00" in relative
        or ".." in path.parts
        or path.as_posix() != relative
        or not path.parts
    ):
        raise FleetError(
            ErrorCode.CONFIG_INVALID,
            "A proposed Fleet configuration path is not canonical and repository-relative.",
            "Regenerate the proposal with canonical relative .fleet paths.",
        )
    return path.parts


def _required_open_flag(name: str) -> int:
    flag = getattr(os, name, None)
    if not isinstance(flag, int) or flag == 0:
        raise FleetError(
            ErrorCode.CONFIG_INVALID,
            "Secure Fleet proposal inspection is unavailable on this platform.",
            "Preview on a platform that supports descriptor-relative no-follow file access.",
        )
    return flag


def _unsafe_proposal_path(relative: str | None = None) -> FleetError:
    path_description = "The repository .fleet path" if relative is None else f".fleet/{relative}"
    return FleetError(
        ErrorCode.PATH_OUTSIDE_SCOPE,
        f"Unsafe existing Fleet configuration path: {path_description}.",
        "Replace symlinks and non-files with real directories and bounded regular files.",
    )


def _oversized_proposal_file(relative: str) -> FleetError:
    return FleetError(
        ErrorCode.CONFIG_INVALID,
        f"Existing Fleet configuration is too large: .fleet/{relative}.",
        "Reduce the file below 512000 bytes before previewing changes.",
    )


def _proposal_hash(files: dict[str, str], patch: str) -> str:
    """Bind the exact proposed bytes to the repository baseline shown in the diff."""

    return canonical_json_hash({"files": files, "patch": patch})
