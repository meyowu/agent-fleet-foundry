from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from agent_fleet.adapters.executable_resolution import resolve_fixed_executable
from agent_fleet.adapters.repository.git import GitRepositoryAdapter
from agent_fleet.adapters.system import UuidIdGenerator
from agent_fleet.bootstrap import _load_or_create_installation_id
from agent_fleet.domain.offline_canary import (
    BOOTSTRAP_HOST_SENTINEL_NAME,
    BOOTSTRAP_SANDBOX_PROBE_MARKER,
)


def test_installation_identity_is_private_regular_stable_file(tmp_path: Path) -> None:
    state_root = tmp_path / "state"

    first = _load_or_create_installation_id(state_root)
    second = _load_or_create_installation_id(state_root)

    identity_path = state_root / "installation-id"
    identity_stat = identity_path.lstat()
    assert first == second
    assert len(first) == 32
    assert set(first) <= set("0123456789abcdef")
    assert stat.S_ISREG(identity_stat.st_mode)
    assert stat.S_IMODE(identity_stat.st_mode) == 0o600
    assert identity_stat.st_nlink == 1
    assert identity_path.read_bytes() == f"{first}\n".encode("ascii")


def test_installation_identity_fsyncs_file_and_parent_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_fsync = os.fsync
    fsynced: list[int] = []

    def record_fsync(descriptor: int) -> None:
        fsynced.append(descriptor)
        original_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", record_fsync)

    identity = _load_or_create_installation_id(tmp_path / "state")

    assert len(identity) == 32
    assert len(fsynced) == 2


def test_installation_identity_rejects_symlink_without_reading_target(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    state_root.mkdir(mode=0o700)
    target = tmp_path / "target"
    sentinel = b"a" * 32 + b"\n"
    target.write_bytes(sentinel)
    (state_root / "installation-id").symlink_to(target)

    with pytest.raises(RuntimeError, match="secure file"):
        _load_or_create_installation_id(state_root)

    assert target.read_bytes() == sentinel


def test_installation_identity_rejects_hardlink_and_weak_mode(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    state_root.mkdir(mode=0o700)
    source = tmp_path / "identity-source"
    source.write_text("b" * 32 + "\n", encoding="ascii")
    source.chmod(0o600)
    os.link(source, state_root / "installation-id")

    with pytest.raises(RuntimeError, match="ownership or permissions"):
        _load_or_create_installation_id(state_root)

    (state_root / "installation-id").unlink()
    identity_path = state_root / "installation-id"
    identity_path.write_text("c" * 32 + "\n", encoding="ascii")
    identity_path.chmod(0o644)

    with pytest.raises(RuntimeError, match="ownership or permissions"):
        _load_or_create_installation_id(state_root)


def test_fixed_executable_resolution_ignores_ambient_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository_bin = tmp_path / "repository" / "bin"
    repository_bin.mkdir(parents=True)
    hostile = repository_bin / "docker"
    hostile.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
    hostile.chmod(0o755)
    monkeypatch.setenv("PATH", str(repository_bin))

    assert (
        resolve_fixed_executable(
            (Path("/definitely/missing/docker"),),
            expected_name="docker",
        )
        is None
    )


def test_bootstrap_fixture_binds_outside_mount_and_environment_probe(tmp_path: Path) -> None:
    state_root = tmp_path / "fixture-state"
    target = GitRepositoryAdapter(state_root, UuidIdGenerator()).create_bootstrap_canary_fixture(
        state_root / "bootstrap" / "fixture" / "repository"
    )

    sentinel = target.parent / BOOTSTRAP_HOST_SENTINEL_NAME
    probe = (target / "tests/test_sandbox_boundary.py").read_text(encoding="utf-8")
    assert sentinel.is_file()
    assert not sentinel.is_relative_to(target)
    assert repr(str(sentinel)) in probe
    assert BOOTSTRAP_SANDBOX_PROBE_MARKER in probe
    assert "ALLOWED_ENVIRONMENT_NAMES" in probe
