"""Read-only local tool and state-directory diagnostics."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

from agent_fleet.adapters.executable_resolution import (
    resolve_trusted_executable,
    trusted_search_path,
)

_VERSION_TIMEOUT_SECONDS = 10


class LocalSystemDiagnostics:
    def __init__(self, state_root: Path | None = None) -> None:
        self.state_root = Path(os.path.abspath(state_root)) if state_root is not None else None

    def python_version(self) -> tuple[bool, str]:
        return sys.version_info >= (3, 12), sys.version.split()[0]

    def git_version(self, *untrusted_roots: Path) -> str | None:
        return self._executable_version("git", *untrusted_roots)

    def docker_version(self, *untrusted_roots: Path) -> str | None:
        return self._executable_version("docker", *untrusted_roots)

    def sqlite_version(self) -> str:
        return sqlite3.sqlite_version

    def state_directory_writable(self, path: Path) -> tuple[bool, str]:
        try:
            path.mkdir(parents=True, exist_ok=True)
            descriptor, name = tempfile.mkstemp(prefix=".doctor-", dir=path)
            os.close(descriptor)
            Path(name).unlink()
            return True, f"Writable state directory: {path}"
        except OSError as error:
            return False, f"State directory is not writable: {error}"

    def _executable_version(self, name: str, *untrusted_roots: Path) -> str | None:
        cwd = Path.cwd()
        extra_roots = tuple(untrusted_roots)
        if self.state_root is not None:
            extra_roots = (*extra_roots, self.state_root)
        executable = resolve_trusted_executable(
            name,
            cwd,
            *extra_roots,
            expected_name=name,
        )
        if executable is None:
            return None
        environment = _minimal_environment()
        environment["PATH"] = trusted_search_path(cwd, *extra_roots)
        try:
            result = subprocess.run(
                [executable, "--version"],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
                timeout=_VERSION_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        return result.stdout.strip() or result.stderr.strip() or f"{name} CLI found"


def _minimal_environment() -> dict[str, str]:
    allowed = ("PATH", "SYSTEMROOT", "TMPDIR", "TEMP", "TMP", "LANG", "LC_ALL")
    return {key: os.environ[key] for key in allowed if key in os.environ}
