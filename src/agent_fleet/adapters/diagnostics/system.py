"""Read-only local tool and state-directory diagnostics."""

from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path


class LocalSystemDiagnostics:
    def python_version(self) -> tuple[bool, str]:
        return sys.version_info >= (3, 12), sys.version.split()[0]

    def git_version(self) -> str | None:
        return self._executable_version("git")

    def docker_version(self) -> str | None:
        return self._executable_version("docker")

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

    @staticmethod
    def _executable_version(name: str) -> str | None:
        executable = shutil.which(name)
        if executable is None:
            return None
        result = subprocess.run(
            [executable, "--version"],
            check=False,
            capture_output=True,
            text=True,
            env=_minimal_environment(),
        )
        return result.stdout.strip() or result.stderr.strip() or f"{name} CLI found"


def _minimal_environment() -> dict[str, str]:
    allowed = ("PATH", "SYSTEMROOT", "TMPDIR", "TEMP", "TMP", "LANG", "LC_ALL")
    return {key: os.environ[key] for key in allowed if key in os.environ}
