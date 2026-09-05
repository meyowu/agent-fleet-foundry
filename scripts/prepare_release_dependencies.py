"""Explicit network-enabled setup, never imported or invoked by Fleet itself."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    arguments = parser.parse_args()
    destination = arguments.destination
    interpreter = arguments.python
    if not destination.is_absolute() or destination.exists() or destination.is_symlink():
        parser.error("destination must be an absolute, new directory with an existing parent")
    if (
        not destination.parent.is_dir()
        or not interpreter.is_absolute()
        or not interpreter.is_file()
    ):
        parser.error("destination parent and explicit Python interpreter must exist")
    root = Path(__file__).resolve().parents[1]
    uv = shutil.which("uv")
    uvx = shutil.which("uvx")
    if uv is None or uvx is None:
        parser.error("install uv and uvx explicitly before preparation")
    environment = {
        key: value
        for key, value in os.environ.items()
        if key in {"PATH", "HOME", "SYSTEMROOT", "TMPDIR", "TEMP", "TMP", "LANG", "LC_ALL"}
    }
    environment["UV_NO_CONFIG"] = "1"
    environment["PIP_CONFIG_FILE"] = os.devnull
    environment["UV_PYTHON_DOWNLOADS"] = "never"
    destination.mkdir(mode=0o700)
    wheels = destination / "wheels"
    wheels.mkdir(mode=0o700)
    requirements = destination / "requirements.lock"
    subprocess.run(
        [
            uv,
            "export",
            "--frozen",
            "--all-extras",
            "--no-emit-project",
            "--no-header",
            "--no-annotate",
            "--format",
            "requirements.txt",
            "--output-file",
            str(requirements),
            "--quiet",
        ],
        cwd=root,
        env=environment,
        check=True,
        timeout=120,
    )
    subprocess.run(
        [
            uvx,
            "--python",
            str(interpreter),
            "--from",
            "pip==26.2.1",
            "pip",
            "--isolated",
            "--disable-pip-version-check",
            "download",
            "--index-url",
            "https://pypi.org/simple",
            "--require-hashes",
            "--only-binary=:all:",
            "--dest",
            str(wheels),
            "-r",
            str(requirements),
        ],
        cwd=destination,
        env=environment,
        check=True,
        timeout=600,
    )
    observed = subprocess.run(
        [
            str(interpreter),
            "-I",
            "-c",
            "import json,sys,sysconfig; print(json.dumps({'version':sys.version,"
            "'platform':sysconfig.get_platform(),'implementation':sys.implementation.name}))",
        ],
        env=environment,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    manifest = {
        "schema_version": 1,
        "uv_lock_sha256": hashlib.sha256((root / "uv.lock").read_bytes()).hexdigest(),
        "requirements_sha256": hashlib.sha256(requirements.read_bytes()).hexdigest(),
        "interpreter": json.loads(observed.stdout),
        "wheels": {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(wheels.glob("*.whl"))
        },
    }
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"prepared": str(destination), "wheel_count": len(manifest["wheels"])}))


if __name__ == "__main__":
    main()
