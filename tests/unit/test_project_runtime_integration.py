from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import cast

import pytest

from agent_fleet.adapters.artifacts.local import LocalArtifactStore
from agent_fleet.adapters.config.yaml import YamlConfigurationAdapter
from agent_fleet.adapters.persistence.sqlite import SqliteStateStore
from agent_fleet.adapters.repository.git import GitRepositoryAdapter
from agent_fleet.adapters.repository.profile import StaticRepositoryProfiler
from agent_fleet.adapters.system import SystemClock, UuidIdGenerator
from agent_fleet.application.artifacts import ArtifactService
from agent_fleet.application.projects import ProjectService
from agent_fleet.application.runtime import RuntimeRegistry
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import (
    RuntimeCapability,
    RuntimeConfiguration,
    RuntimeCredentialCheck,
    SandboxCapabilities,
)
from agent_fleet.domain.security import Redactor
from agent_fleet.ports.clock import Clock
from agent_fleet.ports.config import ConfigurationPort
from agent_fleet.ports.id_generator import IdGenerator
from agent_fleet.ports.repository import RepositoryPort
from agent_fleet.ports.repository_profile import RepositoryProfilerPort
from agent_fleet.ports.runtime import RuntimeAdapter
from agent_fleet.ports.state_store import StateStore


class RecordingRuntimeRegistry:
    def __init__(self, failure: FleetError | None = None) -> None:
        self.failure = failure
        self.require_calls: list[
            tuple[RuntimeConfiguration, frozenset[RuntimeCapability], RuntimeCredentialCheck]
        ] = []
        self.inspect_calls = 0

    def require(
        self,
        configuration: RuntimeConfiguration,
        *,
        required_capabilities: Iterable[RuntimeCapability],
        credential_check: RuntimeCredentialCheck,
    ) -> RuntimeAdapter:
        self.require_calls.append(
            (configuration, frozenset(required_capabilities), credential_check)
        )
        if self.failure is not None:
            raise self.failure
        return cast(RuntimeAdapter, object())

    def inspect(self, *_args: object, **_kwargs: object) -> object:
        self.inspect_calls += 1
        raise AssertionError("project preview must not inspect or resolve a runtime")


class ExplodingDependency:
    def __getattr__(self, name: str) -> object:
        raise AssertionError(f"dependency access before runtime preflight: {name}")


def _real_service(
    tmp_path: Path,
    registry: RecordingRuntimeRegistry,
) -> tuple[ProjectService, SqliteStateStore, Path]:
    state_root = tmp_path / "fleet-state"
    clock = SystemClock()
    ids = UuidIdGenerator()
    redactor = Redactor()
    state = SqliteStateStore(state_root / "state.db", clock, ids, redactor)
    repository = GitRepositoryAdapter(state_root, ids)
    fixture_root = tmp_path / "fixture-state"
    repository_root = GitRepositoryAdapter(fixture_root, ids).create_canary_fixture(
        fixture_root / "repository"
    )
    artifacts = ArtifactService(
        LocalArtifactStore(state_root / "artifacts"), state, clock, ids, redactor
    )
    service = ProjectService(
        state_root,
        state,
        repository,
        StaticRepositoryProfiler(),
        artifacts,
        YamlConfigurationAdapter(redactor),
        clock,
        ids,
        redactor,
        SandboxCapabilities.phase1_fake(),
        cast(RuntimeRegistry, registry),
    )
    return service, state, repository_root


def _preflight_only_service(
    tmp_path: Path,
    registry: RecordingRuntimeRegistry,
) -> ProjectService:
    dependency = ExplodingDependency()
    return ProjectService(
        tmp_path / "fleet-state",
        cast(StateStore, dependency),
        cast(RepositoryPort, dependency),
        cast(RepositoryProfilerPort, dependency),
        cast(ArtifactService, dependency),
        cast(ConfigurationPort, dependency),
        cast(Clock, dependency),
        cast(IdGenerator, dependency),
        Redactor(),
        SandboxCapabilities.phase1_fake(),
        cast(RuntimeRegistry, registry),
    )


def test_provider_preview_preflights_without_credential_resolution_or_writes(
    tmp_path: Path,
) -> None:
    registry = RecordingRuntimeRegistry()
    service, _state, repository_root = _real_service(tmp_path, registry)
    state_root = service.state_root
    assert not state_root.exists()

    preview = service.preview(
        repository_root,
        runtime_name="pydantic-ai",
        provider_model="openai:gpt-5-mini",
        credential_ref="env:PREVIEW_ONLY_KEY",
    )

    serialized = json.dumps(preview, sort_keys=True)
    assert preview["runtime"] == "pydantic-ai"
    assert preview["provider_model"] == "openai:gpt-5-mini"
    assert "adapter: pydantic-ai" in serialized
    assert "providerModel: openai:gpt-5-mini" in serialized
    assert "env:PREVIEW_ONLY_KEY" not in serialized
    [(configuration, capabilities, credential_check)] = registry.require_calls
    assert configuration.provider_model == "openai:gpt-5-mini"
    assert configuration.credential_ref == "env:PREVIEW_ONLY_KEY"
    assert capabilities == {
        RuntimeCapability.STRUCTURED_OUTPUT,
        RuntimeCapability.TOOL_CALLING,
    }
    assert credential_check is RuntimeCredentialCheck.NONE
    assert registry.inspect_calls == 0
    assert not state_root.exists()
    assert not (repository_root / ".fleet").exists()


def test_preview_rejects_malformed_credential_before_repository_access(tmp_path: Path) -> None:
    registry = RecordingRuntimeRegistry()
    service = _preflight_only_service(tmp_path, registry)
    malformed = "raw-provider-secret"

    with pytest.raises(FleetError) as captured:
        service.preview(
            tmp_path / "does-not-exist",
            runtime_name="pydantic-ai",
            provider_model="openai:gpt-5-mini",
            credential_ref=malformed,
        )

    assert captured.value.code is ErrorCode.CONFIG_INVALID
    assert malformed not in str(captured.value)
    assert registry.require_calls == []
    assert registry.inspect_calls == 0
    assert not service.state_root.exists()


@pytest.mark.parametrize("operation", ["preview", "initialize"])
def test_bootstrap_rejects_registered_secret_with_stable_error(
    tmp_path: Path,
    operation: str,
) -> None:
    registry = RecordingRuntimeRegistry()
    service, _state, repository_root = _real_service(tmp_path, registry)
    secret_path = str(repository_root)
    service.redactor.register_secret(secret_path)

    with pytest.raises(FleetError) as captured:
        getattr(service, operation)(repository_root)

    assert captured.value.code is ErrorCode.COMMAND_DENIED
    assert secret_path not in str(captured.value)
    assert captured.value.__cause__ is None
    assert not (repository_root / ".fleet").exists()


def test_initialize_preflight_failure_precedes_all_repository_and_state_access(
    tmp_path: Path,
) -> None:
    failure = FleetError(
        ErrorCode.CREDENTIAL_MISSING,
        "The selected credential is not configured.",
        "Configure the selected environment variable and retry.",
    )
    registry = RecordingRuntimeRegistry(failure)
    service = _preflight_only_service(tmp_path, registry)

    with pytest.raises(FleetError) as captured:
        service.initialize(
            tmp_path / "does-not-exist",
            runtime_name="pydantic-ai",
            provider_model="openai:gpt-5-mini",
            credential_ref="env:MISSING_PROVIDER_KEY",
        )

    assert captured.value.code is ErrorCode.CREDENTIAL_MISSING
    [(configuration, capabilities, credential_check)] = registry.require_calls
    assert configuration.provider_model == "openai:gpt-5-mini"
    assert configuration.credential_ref == "env:MISSING_PROVIDER_KEY"
    assert capabilities == {
        RuntimeCapability.STRUCTURED_OUTPUT,
        RuntimeCapability.TOOL_CALLING,
    }
    assert credential_check is RuntimeCredentialCheck.RESOLVE
    assert not service.state_root.exists()


def test_initialize_persists_selection_only_on_project_and_omits_reference_elsewhere(
    tmp_path: Path,
) -> None:
    credential_ref = "env:PROJECT_OWNED_PROVIDER_KEY"
    registry = RecordingRuntimeRegistry()
    service, state, repository_root = _real_service(tmp_path, registry)

    result = service.initialize(
        repository_root,
        runtime_name="pydantic-ai",
        provider_model="openai:gpt-5-mini",
        credential_ref=credential_ref,
    )

    project = state.get_project_by_root(str(repository_root.resolve()))
    assert project is not None
    assert project.runtime_name == "pydantic-ai"
    assert project.provider_model == "openai:gpt-5-mini"
    assert project.credential_ref == credential_ref
    assert result["runtime"] == "pydantic-ai"
    assert result["provider_model"] == "openai:gpt-5-mini"
    assert credential_ref not in json.dumps(result, sort_keys=True)
    assert credential_ref not in (repository_root / ".fleet" / "fleet.yaml").read_text(
        encoding="utf-8"
    )
    with sqlite3.connect(service.state_root / "state.db") as connection:
        event_rows = connection.execute("SELECT data_json FROM run_events").fetchall()
    assert event_rows
    assert all(credential_ref not in str(row[0]) for row in event_rows)
    artifact_files = [
        path for path in (service.state_root / "artifacts").rglob("*") if path.is_file()
    ]
    assert artifact_files
    assert all(credential_ref.encode() not in path.read_bytes() for path in artifact_files)
    [(configuration, _capabilities, credential_check)] = registry.require_calls
    assert configuration.credential_ref == credential_ref
    assert credential_check is RuntimeCredentialCheck.RESOLVE


def _fleet_contents(repository_root: Path) -> dict[str, bytes]:
    fleet_root = repository_root / ".fleet"
    return {
        path.relative_to(fleet_root).as_posix(): path.read_bytes()
        for path in sorted(fleet_root.rglob("*"))
        if path.is_file()
    }


def _state_counts(state_root: Path) -> tuple[int, int, int]:
    with sqlite3.connect(state_root / "state.db") as connection:
        return tuple(
            int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in ("projects", "artifacts", "run_events")
        )  # type: ignore[return-value]


def test_fake_to_provider_reinitialization_fails_before_state_or_artifact_mutation(
    tmp_path: Path,
) -> None:
    registry = RecordingRuntimeRegistry()
    service, state, repository_root = _real_service(tmp_path, registry)
    service.initialize(repository_root)
    before_project = state.get_project_by_root(str(repository_root.resolve()))
    before_files = _fleet_contents(repository_root)
    before_counts = _state_counts(service.state_root)

    with pytest.raises(FleetError) as captured:
        service.initialize(
            repository_root,
            runtime_name="pydantic-ai",
            provider_model="openai:gpt-5-mini",
            credential_ref="env:RECONFIG_PROVIDER_KEY",
        )

    assert captured.value.code is ErrorCode.CONFIG_INVALID
    assert "overwrite" in captured.value.message
    assert state.get_project_by_root(str(repository_root.resolve())) == before_project
    assert _fleet_contents(repository_root) == before_files
    assert _state_counts(service.state_root) == before_counts


def test_provider_model_reinitialization_fails_without_split_brain(tmp_path: Path) -> None:
    registry = RecordingRuntimeRegistry()
    service, state, repository_root = _real_service(tmp_path, registry)
    service.initialize(
        repository_root,
        runtime_name="pydantic-ai",
        provider_model="openai:model-a",
        credential_ref="env:RECONFIG_PROVIDER_KEY",
    )
    before_project = state.get_project_by_root(str(repository_root.resolve()))
    before_files = _fleet_contents(repository_root)
    before_counts = _state_counts(service.state_root)

    with pytest.raises(FleetError) as captured:
        service.initialize(
            repository_root,
            runtime_name="pydantic-ai",
            provider_model="openai:model-b",
            credential_ref="env:RECONFIG_PROVIDER_KEY",
        )

    assert captured.value.code is ErrorCode.CONFIG_INVALID
    assert state.get_project_by_root(str(repository_root.resolve())) == before_project
    assert _fleet_contents(repository_root) == before_files
    assert _state_counts(service.state_root) == before_counts


def test_preview_rejects_symlink_swapped_in_at_open_without_reading_outside(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = RecordingRuntimeRegistry()
    service, _state, repository_root = _real_service(tmp_path, registry)
    service.initialize(repository_root)
    destination = repository_root / ".fleet" / "README.md"
    outside_sentinel = "outside-preview-sentinel-must-not-be-read"
    outside = tmp_path / "outside-preview.md"
    outside.write_text(outside_sentinel, encoding="utf-8")
    original_open = os.open
    swapped = False

    def swapping_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal swapped
        if path == "README.md" and dir_fd is not None and not swapped:
            swapped = True
            destination.unlink()
            destination.symlink_to(outside)
            assert flags & os.O_NOFOLLOW
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", swapping_open)

    with pytest.raises(FleetError) as captured:
        service.preview(repository_root)

    assert swapped is True
    assert captured.value.code is ErrorCode.PATH_OUTSIDE_SCOPE
    assert outside_sentinel not in str(captured.value)
    assert outside.read_text(encoding="utf-8") == outside_sentinel


def test_preview_rejects_baseline_that_grows_beyond_limit_after_fstat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = RecordingRuntimeRegistry()
    service, _state, repository_root = _real_service(tmp_path, registry)
    service.initialize(repository_root)
    destination = repository_root / ".fleet" / "README.md"
    destination_stat = destination.stat()
    destination_identity = (destination_stat.st_dev, destination_stat.st_ino)
    original_read = os.read
    grew = False
    requested_sizes: list[int] = []
    total_read = 0

    def growing_read(descriptor: int, size: int) -> bytes:
        nonlocal grew, total_read
        opened = os.fstat(descriptor)
        if not grew and (opened.st_dev, opened.st_ino) == destination_identity:
            grew = True
            with destination.open("ab") as stream:
                stream.write(b"x" * 512_001)
        content = original_read(descriptor, size)
        if (opened.st_dev, opened.st_ino) == destination_identity:
            requested_sizes.append(size)
            total_read += len(content)
        return content

    monkeypatch.setattr(os, "read", growing_read)

    with pytest.raises(FleetError) as captured:
        service.preview(repository_root)

    assert grew is True
    assert captured.value.code is ErrorCode.CONFIG_INVALID
    assert destination.stat().st_size > 512_000
    assert requested_sizes
    assert max(requested_sizes) <= 65_536
    assert total_read <= 512_001


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO support is unavailable")
def test_preview_rejects_fifo_with_nonblocking_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = RecordingRuntimeRegistry()
    service, _state, repository_root = _real_service(tmp_path, registry)
    service.initialize(repository_root)
    destination = repository_root / ".fleet" / "README.md"
    destination.unlink()
    os.mkfifo(destination)
    original_open = os.open
    inspected_fifo = False

    def checking_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal inspected_fifo
        if path == "README.md" and dir_fd is not None:
            inspected_fifo = True
            assert flags & os.O_NONBLOCK
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", checking_open)

    with pytest.raises(FleetError) as captured:
        service.preview(repository_root)

    assert inspected_fifo is True
    assert captured.value.code is ErrorCode.PATH_OUTSIDE_SCOPE


def test_conflicting_fleet_tree_is_rejected_before_state_creation(tmp_path: Path) -> None:
    registry = RecordingRuntimeRegistry()
    service, _state, repository_root = _real_service(tmp_path, registry)
    custom = repository_root / ".fleet" / "README.md"
    custom.parent.mkdir()
    custom.write_text("user-owned configuration\n", encoding="utf-8")

    with pytest.raises(FleetError) as captured:
        service.initialize(repository_root)

    assert captured.value.code is ErrorCode.CONFIG_INVALID
    assert custom.read_text(encoding="utf-8") == "user-owned configuration\n"
    assert not service.state_root.exists()


@pytest.mark.parametrize("failure_point", ["stage", "snapshot", "canary"])
def test_preapply_bootstrap_failure_does_not_register_project_or_apply_fleet_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_point: str,
) -> None:
    registry = RecordingRuntimeRegistry()
    service, state, repository_root = _real_service(tmp_path, registry)

    def fail(*_args: object, **_kwargs: object) -> object:
        raise FleetError(
            ErrorCode.CONFIG_INVALID,
            f"Injected {failure_point} failure.",
            "Retry after correcting the injected failure.",
        )

    if failure_point == "stage":
        monkeypatch.setattr(service.config, "stage", fail)
    elif failure_point == "snapshot":
        monkeypatch.setattr(service.config, "load_snapshot", fail)
    else:
        monkeypatch.setattr(service.repository, "create_canary_fixture", fail)

    with pytest.raises(FleetError) as captured:
        service.initialize(repository_root)

    assert captured.value.code is ErrorCode.CONFIG_INVALID
    assert state.get_project_by_root(str(repository_root.resolve())) is None
    assert not (repository_root / ".fleet").exists()
    assert _state_counts(service.state_root) == (0, 0, 0)


def test_apply_failure_does_not_register_project_or_apply_fleet_tree(tmp_path: Path) -> None:
    registry = RecordingRuntimeRegistry()
    service, state, repository_root = _real_service(tmp_path, registry)

    def fail_apply(*_args: object, **_kwargs: object) -> object:
        raise FleetError(
            ErrorCode.CONFIG_INVALID,
            "Injected apply failure.",
            "Retry after correcting the injected failure.",
        )

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(service.config, "apply", fail_apply)
    try:
        with pytest.raises(FleetError) as captured:
            service.initialize(
                repository_root,
                runtime_name="pydantic-ai",
                provider_model="openai:gpt-5-mini",
                credential_ref="env:APPLY_FAILURE_KEY",
            )
    finally:
        monkeypatch.undo()

    assert captured.value.code is ErrorCode.CONFIG_INVALID
    registered = state.get_project_by_root(str(repository_root.resolve()))
    assert registered is None
    assert not (repository_root / ".fleet").exists()


def test_post_apply_tampering_is_rejected_before_project_or_artifact_persistence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = RecordingRuntimeRegistry()
    service, state, repository_root = _real_service(tmp_path, registry)
    original_apply = service.config.apply

    def tampering_apply(root: Path, files: dict[str, str]) -> object:
        spec = original_apply(root, files)
        (root / "agents" / "engineer.md").write_text(
            "tampered after adapter apply\n", encoding="utf-8"
        )
        return spec

    monkeypatch.setattr(service.config, "apply", tampering_apply)

    with pytest.raises(FleetError) as captured:
        service.initialize(repository_root)

    assert captured.value.code is ErrorCode.ARTIFACT_INTEGRITY_FAILED
    assert state.get_project_by_root(str(repository_root.resolve())) is None
    assert _state_counts(service.state_root) == (0, 0, 0)


def test_post_apply_repository_failure_does_not_persist_a_false_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = RecordingRuntimeRegistry()
    service, state, repository_root = _real_service(tmp_path, registry)
    original_inspect = service.repository.inspect
    calls = 0

    def fail_second_inspection(root: Path) -> object:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise FleetError(
                ErrorCode.PROJECT_NOT_GIT,
                "Injected post-apply inspection failure.",
                "Retry after correcting the injected failure.",
            )
        return original_inspect(root)

    monkeypatch.setattr(service.repository, "inspect", fail_second_inspection)

    with pytest.raises(FleetError) as captured:
        service.initialize(repository_root)

    assert captured.value.code is ErrorCode.PROJECT_NOT_GIT
    assert state.get_project_by_root(str(repository_root.resolve())) is None
    assert _state_counts(service.state_root) == (0, 0, 0)
    assert (repository_root / ".fleet" / "fleet.yaml").is_file()
