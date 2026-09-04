from __future__ import annotations

import subprocess
import tarfile
import zipfile
from pathlib import Path

import pytest

from agent_fleet.schemas.generate import SCHEMAS


def _archive_files(path: Path) -> dict[str, bytes]:
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            return {
                name: archive.read(name) for name in archive.namelist() if not name.endswith("/")
            }
    with tarfile.open(path) as archive:
        result: dict[str, bytes] = {}
        for member in archive.getmembers():
            if not member.isfile():
                continue
            stream = archive.extractfile(member)
            assert stream is not None
            result[member.name] = stream.read()
        return result


def _runtime_resource_name(name: str) -> str:
    marker = "/src/agent_fleet/"
    if name.startswith("agent_fleet/"):
        return name
    if marker in name:
        return f"agent_fleet/{name.split(marker, maxsplit=1)[1]}"
    return name


@pytest.mark.integration
def test_wheel_and_sdist_ship_runtime_resources_without_development_fixtures(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).parents[2]
    output = tmp_path / "distribution"
    completed = subprocess.run(
        ["uv", "build", "--offline", "--out-dir", str(output)],
        cwd=repository_root,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    archives = sorted(output.glob("agent_fleet-*"))
    assert {path.suffix for path in archives} == {".gz", ".whl"}

    required_suffixes = {
        "agent_fleet/adapters/runtime/prompts/cos.md",
        "agent_fleet/adapters/runtime/prompts/engineer.md",
        "agent_fleet/adapters/runtime/prompts/verifier.md",
        "agent_fleet/adapters/persistence/migrations/0001.sql",
        "agent_fleet/adapters/persistence/migrations/0002.sql",
        *(f"agent_fleet/schemas/{name}" for name in SCHEMAS),
    }
    forbidden_content = (
        b"/users/",
        b"secret-sentinel",
        b"phase2-provider-secret",
        b"registered-runtime-output-secret",
    )
    for archive_path in archives:
        files = _archive_files(archive_path)
        normalized_names = {_runtime_resource_name(name) for name in files}
        assert required_suffixes <= normalized_names
        assert not any("/tests/" in f"/{name}" for name in files)
        assert not any("/.agent/" in f"/{name}" for name in files)
        packaged_content = b"\n".join(files.values()).lower()
        assert all(marker not in packaged_content for marker in forbidden_content)
