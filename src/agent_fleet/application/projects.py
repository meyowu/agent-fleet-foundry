"""Safe repository registration and staged `.fleet/` initialization."""

from __future__ import annotations

import errno
import json
import os
import stat
from contextlib import suppress
from difflib import unified_diff
from pathlib import Path, PurePosixPath

from agent_fleet.application.artifacts import ArtifactService
from agent_fleet.application.runtime import RuntimeRegistry
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.ids import IdPrefix
from agent_fleet.domain.models import (
    ArtifactKind,
    FleetEvent,
    Project,
    RuntimeCapability,
    RuntimeConfiguration,
    RuntimeCredentialCheck,
    SandboxCapabilities,
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

    def preview(
        self,
        root: Path,
        *,
        runtime_name: str = "fake",
        provider_model: str | None = None,
        credential_ref: str | None = None,
        sandbox_name: str = "fake",
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
        self._validate_sandbox(sandbox_name)
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
        )
        self._reject_registered_secrets(files)
        self.config.validate_files(files)
        proposal_patch = _proposal_patch(Path(info.root), files)
        preview: dict[str, object] = {
            "repository": info.root,
            "runtime": runtime_configuration.runtime_name,
            "provider_model": runtime_configuration.provider_model,
            "sandbox": sandbox_name,
            "security_level": self.sandbox_capabilities.security_level.value,
            "sandbox_capabilities": self.sandbox_capabilities.model_dump(mode="json"),
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
            "security_warning": self._security_warning(runtime_configuration.runtime_name),
        }
        self._reject_registered_secrets(preview)
        return preview

    def initialize(
        self,
        root: Path,
        *,
        runtime_name: str = "fake",
        provider_model: str | None = None,
        credential_ref: str | None = None,
        sandbox_name: str = "fake",
        expected_proposal_hash: str | None = None,
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
        self._validate_sandbox(sandbox_name)
        self.runtime_registry.require(
            runtime_configuration,
            required_capabilities=_BOOTSTRAP_RUNTIME_CAPABILITIES,
            credential_check=RuntimeCredentialCheck.RESOLVE,
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
        proposed_files = self.config.default_files(
            Path(info.root).name,
            profile_result.profile,
            runtime_name=runtime_configuration.runtime_name,
            provider_model=runtime_configuration.provider_model,
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
        canary = self.repository.create_canary_fixture(
            self.state_root / "projects" / project.project_id / "canaries" / "bootstrap"
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
            "canary_path": str(canary),
            "runtime": runtime_configuration.runtime_name,
            "provider_model": runtime_configuration.provider_model,
            "sandbox": "fake",
            "security_level": "fake",
            "sandbox_capabilities": self.sandbox_capabilities.model_dump(mode="json"),
            "warning": self._security_warning(runtime_configuration.runtime_name),
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

    def _validate_sandbox(self, sandbox_name: str) -> None:
        if sandbox_name != "fake":
            raise FleetError(
                ErrorCode.SANDBOX_UNAVAILABLE,
                f"Sandbox {sandbox_name!r} is not available in Phase 2.",
                "Use `--sandbox fake`; Docker execution begins in Phase 3.",
            )
        if self.sandbox_capabilities != SandboxCapabilities.phase1_fake():
            raise FleetError(
                ErrorCode.SANDBOX_UNAVAILABLE,
                "The selected fake sandbox reported an unexpected capability descriptor.",
                "Use the built-in non-executing FakeSandbox for Phase 2.",
            )

    @staticmethod
    def _security_warning(runtime_name: str) -> str:
        if runtime_name == "fake":
            return (
                "Fake runtime and sandbox provide deterministic orchestration, "
                "not model or OS isolation."
            )
        return (
            "The selected runtime may contact its configured model provider, but the fake "
            "sandbox does not execute project code or provide OS isolation."
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
