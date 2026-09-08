from __future__ import annotations

import json
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

from agent_fleet.adapters.persistence.sqlite import SUPPORTED_SCHEMA_VERSION
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
    if name.endswith("/docs/USER_GUIDE.md"):
        return "agent_fleet/assets/USER_GUIDE.md"
    if name.startswith("agent_fleet/"):
        return name
    if marker in name:
        return f"agent_fleet/{name.split(marker, maxsplit=1)[1]}"
    return name


def _package_files(root: Path) -> dict[str, bytes]:
    return {
        f"agent_fleet/{path.relative_to(root).as_posix()}": path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix not in {".pyc", ".pyo"}
    }


# This tests installed wheel contents against the existing locked dependencies. It
# is deliberately not a clean dependency installation or fresh-user release gate.
_INSTALLED_RESOURCE_SMOKE = """
import json
import sqlite3
import sys
from importlib.resources import files
from pathlib import Path

target = Path(sys.argv[1])
source = Path(sys.argv[2])
state_path = Path(sys.argv[3])
sys.path.insert(0, str(target))
import agent_fleet
from agent_fleet.adapters.persistence.sqlite import SUPPORTED_SCHEMA_VERSION, SqliteStateStore
from agent_fleet.adapters.system import SystemClock, UuidIdGenerator
from agent_fleet.domain.security import Redactor
from agent_fleet.schemas.generate import SCHEMAS

assert Path(agent_fleet.__file__).resolve().is_relative_to(target.resolve())
package = files('agent_fleet')
for path in source.rglob('*'):
    if not path.is_file() or '__pycache__' in path.parts or path.suffix in {'.pyc', '.pyo'}:
        continue
    relative = path.relative_to(source).as_posix()
    assert package.joinpath(relative).read_bytes() == path.read_bytes(), relative
for name, model in SCHEMAS.items():
    resource = files('agent_fleet.schemas').joinpath(name)
    assert json.loads(resource.read_text()) == model.model_json_schema(), name
state = SqliteStateStore(state_path, SystemClock(), UuidIdGenerator(), Redactor())
assert state.migrate() == SUPPORTED_SCHEMA_VERSION
assert state.migrate() == SUPPORTED_SCHEMA_VERSION
with sqlite3.connect(state_path) as connection:
    versions = [row[0] for row in connection.execute(
        'SELECT version FROM schema_migrations ORDER BY version'
    )]
    assert versions == list(range(1, SUPPORTED_SCHEMA_VERSION + 1))
    graph_tables = {row[0] for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'fleet_graph%'"
    )}
    assert graph_tables == {'fleet_graphs', 'fleet_graph_nodes', 'fleet_graph_driver_claims'}
    conversation_tables = {row[0] for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'conversation%'"
    )}
    assert conversation_tables == {
        'conversations', 'conversation_turns', 'conversation_turn_claims'
    }
from agent_fleet.cli.app import main
sys.argv = ['fleet', 'version', '--json']
main()
"""


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
        "agent_fleet/adapters/runtime/prompts/architect.md",
        "agent_fleet/adapters/runtime/prompts/cos.md",
        "agent_fleet/adapters/runtime/prompts/engineer.md",
        "agent_fleet/adapters/runtime/prompts/researcher.md",
        "agent_fleet/adapters/runtime/prompts/verifier.md",
        *(
            f"agent_fleet/adapters/persistence/migrations/{version:04d}.sql"
            for version in range(1, SUPPORTED_SCHEMA_VERSION + 1)
        ),
        *(f"agent_fleet/schemas/{name}" for name in SCHEMAS),
    }
    source_files = _package_files(repository_root / "src" / "agent_fleet")
    source_files["agent_fleet/assets/USER_GUIDE.md"] = (
        repository_root / "docs/USER_GUIDE.md"
    ).read_bytes()
    readme = (repository_root / "README.md").read_bytes()
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
        packaged_source = {
            _runtime_resource_name(name): content
            for name, content in files.items()
            if _runtime_resource_name(name).startswith("agent_fleet/")
        }
        assert packaged_source == source_files
        if archive_path.suffix == ".whl":
            metadata = next(
                content for name, content in files.items() if name.endswith(".dist-info/METADATA")
            )
            assert metadata.split(b"\n\n", maxsplit=1)[1] == readme
        else:
            assert (
                next(
                    content
                    for name, content in files.items()
                    if len(name.split("/")) == 2 and name.endswith("/README.md")
                )
                == readme
            )
        assert not any(
            "/tests/" in f"/{name}" and "/assets/canary/tests/" not in f"/{name}" for name in files
        )
        assert not any("/.agent/" in f"/{name}" for name in files)
        assert not any(
            part in {".git", ".fleet", ".venv", "__pycache__"}
            for name in files
            for part in name.split("/")
        )
        packaged_content = b"\n".join(files.values()).lower()
        assert all(marker not in packaged_content for marker in forbidden_content)

    installed = tmp_path / "installed-wheel"
    wheel = next(path for path in archives if path.suffix == ".whl")
    install = subprocess.run(
        ["uv", "pip", "install", "--offline", "--no-deps", "--target", str(installed), str(wheel)],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert install.returncode == 0, install.stdout + install.stderr
    smoke = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            "-c",
            _INSTALLED_RESOURCE_SMOKE,
            str(installed),
            str(repository_root / "src" / "agent_fleet"),
            str(tmp_path / "installed-state" / "fleet.db"),
        ],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert smoke.returncode == 0, smoke.stdout + smoke.stderr
    version = json.loads(smoke.stdout)
    assert version["ok"] is True
    assert version["data"]["phase"] == "6"
    assert version["data"]["version"] == "0.1.0"
