from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from agent_fleet.adapters.diagnostics.system import LocalSystemDiagnostics


def test_git_version_ignores_repository_controlled_path_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    subdirectory = repository / "subdirectory"
    repository_bin = repository / "bin"
    (repository / ".git").mkdir(parents=True)
    subdirectory.mkdir()
    repository_bin.mkdir()
    sentinel = tmp_path / "diagnostics-git-executed"
    real_git = shutil.which("git")
    assert real_git is not None
    fake_git = repository_bin / "git"
    fake_git.write_text(
        f"#!/bin/sh\ntouch '{sentinel}'\nexec '{real_git}' \"$@\"\n",
        encoding="utf-8",
    )
    fake_git.chmod(0o755)
    safe_directory = tmp_path / "safe"
    safe_directory.mkdir()
    monkeypatch.chdir(safe_directory)
    monkeypatch.setenv("PATH", f"{repository_bin}{os.pathsep}{os.environ['PATH']}")

    version = LocalSystemDiagnostics(tmp_path / "state").git_version(subdirectory)

    assert version is not None
    assert version.startswith("git version ")
    assert not sentinel.exists()
