"""Fresh environments; local wheelhouse setup is separate from offline execution."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from urllib.parse import unquote, urlsplit

import pytest

from agent_fleet.domain.offline_canary import BROKEN_CANARY, FIXED_CANARY

pytestmark = pytest.mark.installed_distribution
_ROOT = Path(__file__).parents[2]
_NETWORK_GUARD = """import socket
import pydantic_ai.models
pydantic_ai.models.ALLOW_MODEL_REQUESTS = False
def deny(*args, **kwargs):
    raise AssertionError("installed release checks forbid network access")
original = socket.socket.connect
original_ex = socket.socket.connect_ex
def connect(sock, address):
    if sock.family in {socket.AF_INET, socket.AF_INET6}:
        deny()
    return original(sock, address)
def connect_ex(sock, address):
    if sock.family in {socket.AF_INET, socket.AF_INET6}:
        deny()
    return original_ex(sock, address)
socket.create_connection = socket.getaddrinfo = socket.socket.sendto = deny
socket.socket.connect = connect
socket.socket.connect_ex = connect_ex
if hasattr(socket.socket, "sendmsg"):
    socket.socket.sendmsg = deny
"""
_SMOKE = """import importlib.metadata as metadata
import json, pathlib, socket, sys
from importlib.resources import files
import agent_fleet
import pydantic_ai.models
from agent_fleet.adapters.persistence.sqlite import SqliteStateStore
from agent_fleet.adapters.system import SystemClock, UuidIdGenerator
from agent_fleet.domain.security import Redactor
from agent_fleet.schemas.generate import SCHEMAS
environment = pathlib.Path(sys.prefix)
assert environment != pathlib.Path(sys.base_prefix)
assert pathlib.Path(agent_fleet.__file__).is_relative_to(environment)
assert pydantic_ai.models.ALLOW_MODEL_REQUESTS is False
try:
    socket.getaddrinfo("example.com", 443)
except AssertionError:
    pass
else:
    raise AssertionError("installed network guard missing")
for name, model in SCHEMAS.items():
    observed = json.loads(files("agent_fleet.schemas").joinpath(name).read_text())
    assert observed == model.model_json_schema()
state = SqliteStateStore(pathlib.Path(sys.argv[1]), SystemClock(), UuidIdGenerator(), Redactor())
assert state.migrate() == state.migrate() == 8
print(json.dumps({
    "package": str(pathlib.Path(agent_fleet.__file__)),
    "assets": str(files("agent_fleet").joinpath("assets")),
    "schemas": len(SCHEMAS),
    "distributions": {
        d.metadata["Name"].lower().replace("_", "-"): d.version
        for d in metadata.distributions()
    },
}))
"""
_OFFLINE_PROPOSAL_ENTRY = """import importlib, importlib.util, pathlib, sys
import agent_fleet
assert pathlib.Path(agent_fleet.__file__).is_relative_to(pathlib.Path(sys.prefix))
# Load only a deterministic test response producer; never add checkout source to sys.path.
spec = importlib.util.spec_from_file_location("release_proposal_fixture", sys.argv.pop(1))
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
from pydantic_ai.models import override_allow_model_requests
from pydantic_ai.models.function import FunctionModel
from agent_fleet.adapters.runtime.fake import FakeRuntimeAdapter
from agent_fleet.adapters.runtime.pydantic_ai import PydanticAIRuntimeAdapter
from agent_fleet.application.runtime import RuntimeRegistry
cli = importlib.import_module("agent_fleet.cli.app")
original = cli.build_container
def offline_container(*args, **kwargs):
    container = original(*args, **kwargs)
    model = fixture.ProposalModel()
    adapter = PydanticAIRuntimeAdapter.for_test_model(
        FunctionModel(model.__call__), redactor=container.redactor)
    registry = RuntimeRegistry({"fake": FakeRuntimeAdapter(), "pydantic-ai": adapter})
    container.projects.runtime_registry = registry
    container.workflow.runtimes = registry
    container.bootstrap.runtimes = registry
    container.doctor.runtime_registry = registry
    return container
cli.build_container = offline_container
with override_allow_model_requests(False):
    cli.main()
"""


@dataclass(frozen=True)
class InstalledFleet:
    root: Path
    python: Path
    executable: Path
    environment: dict[str, str]
    assets: Path

    def process(
        self, arguments: list[str], *, expected: int = 0
    ) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            arguments,
            cwd=self.root,
            env=self.environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=180,
        )
        # Test-owned evidence only: never capture environment values or provider keys.
        with (self.root / "command-evidence.jsonl").open("a", encoding="utf-8") as evidence:
            evidence.write(
                json.dumps(
                    {
                        "argv": arguments,
                        "exit_code": result.returncode,
                        "stdout": result.stdout,
                        "stderr": result.stderr,
                    }
                )
                + "\n"
            )
        assert result.returncode == expected, result.stdout + result.stderr
        return result

    def payload(
        self, arguments: list[str], *, expected: int = 0, entry: list[str] | None = None
    ) -> object:
        result = self.process(
            [*(entry or [str(self.executable)]), *arguments, "--json"], expected=expected
        )
        payload = json.loads(result.stdout)
        assert isinstance(payload, dict) and payload["ok"] is (expected == 0)
        return payload["data" if expected == 0 else "error"]

    def invoke(
        self, arguments: list[str], *, expected: int = 0, entry: list[str] | None = None
    ) -> dict[str, object]:
        value = self.payload(arguments, expected=expected, entry=entry)
        assert isinstance(value, dict)
        return cast(dict[str, object], value)

    def listing(self, arguments: list[str]) -> list[dict[str, object]]:
        value = self.payload(arguments)
        assert isinstance(value, list) and all(isinstance(item, dict) for item in value)
        return cast(list[dict[str, object]], value)


@pytest.fixture
def prepared_wheelhouse() -> Path:
    if os.environ.get("AGENT_FLEET_ENABLE_INSTALL_TESTS") != "1":
        pytest.skip("fresh installation requires AGENT_FLEET_ENABLE_INSTALL_TESTS=1")
    supplied = os.environ.get("AGENT_FLEET_TEST_WHEELHOUSE", "")
    path = Path(supplied)
    assert supplied and path.is_absolute() and path.is_dir(), "provide the prepared wheelhouse root"
    manifest = json.loads((path / "manifest.json").read_text())
    assert manifest["schema_version"] == 1
    assert (
        manifest["uv_lock_sha256"] == hashlib.sha256((_ROOT / "uv.lock").read_bytes()).hexdigest()
    )
    assert (
        manifest["requirements_sha256"]
        == hashlib.sha256((path / "requirements.lock").read_bytes()).hexdigest()
    )
    lock = tomllib.loads((_ROOT / "uv.lock").read_text())
    allowed = {
        unquote(Path(urlsplit(wheel["url"]).path).name): wheel["hash"].removeprefix("sha256:")
        for package in lock["package"]
        for wheel in package.get("wheels", ())
    }
    observed = {
        wheel.name: hashlib.sha256(wheel.read_bytes()).hexdigest()
        for wheel in (path / "wheels").iterdir()
        if wheel.is_file() and not wheel.is_symlink() and wheel.suffix == ".whl"
    }
    assert observed and observed == manifest["wheels"]
    assert all(allowed.get(name) == digest for name, digest in observed.items())
    return path


def _install(root: Path, wheelhouse: Path, archive_kind: str) -> InstalledFleet:
    root.mkdir()
    environment = {
        key: value
        for key, value in os.environ.items()
        if key in {"PATH", "HOME", "SYSTEMROOT", "TMPDIR", "TEMP", "TMP", "LANG", "LC_ALL"}
    }
    environment.update(
        {
            "AGENT_FLEET_HOME": str(root / "state"),
            "PYTHONNOUSERSITE": "1",
            "UV_NO_CONFIG": "1",
            "UV_PYTHON_DOWNLOADS": "never",
            "UV_OFFLINE": "1",
        }
    )
    uv = shutil.which("uv")
    assert uv is not None
    built = subprocess.run(
        [uv, "build", "--offline", "--out-dir", str(root / "archives")],
        cwd=_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert built.returncode == 0, built.stdout + built.stderr
    archive = next((root / "archives").glob(f"*.{archive_kind}"))
    virtual = root / "environment"
    created = subprocess.run(
        [sys.executable, "-I", "-m", "venv", "--without-pip", str(virtual)],
        cwd=root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert created.returncode == 0, created.stderr
    interpreter = virtual / "bin/python"
    installed = subprocess.run(
        [
            uv,
            "pip",
            "install",
            "--offline",
            "--no-index",
            "--no-config",
            "--no-python-downloads",
            "--cache-dir",
            str(root / "empty-install-cache"),
            "--python",
            str(interpreter),
            "--find-links",
            str(wheelhouse / "wheels"),
            "--constraints",
            str(wheelhouse / "requirements.lock"),
            "--build-constraints",
            str(wheelhouse / "requirements.lock"),
            "--strict",
            str(archive),
        ],
        cwd=root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert installed.returncode == 0, installed.stdout + installed.stderr
    configuration = (virtual / "pyvenv.cfg").read_text()
    assert "include-system-site-packages = false" in configuration
    site = next((virtual / "lib").glob("python*/site-packages"))
    (site / "_fleet_release_network_guard.py").write_text(_NETWORK_GUARD)
    (site / "fleet_release_network_guard.pth").write_text("import _fleet_release_network_guard\n")
    smoke = subprocess.run(
        [str(interpreter), "-I", "-c", _SMOKE, str(root / "smoke-state/fleet.db")],
        cwd=root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert smoke.returncode == 0, smoke.stdout + smoke.stderr
    report = json.loads(smoke.stdout)
    assert Path(report["package"]).is_relative_to(virtual)
    assert not Path(report["package"]).is_relative_to(_ROOT)
    assert report["schemas"] == 82
    locked_versions = {
        package["name"]: package["version"]
        for package in tomllib.loads((_ROOT / "uv.lock").read_text())["package"]
    }
    assert len(report["distributions"]) > 20
    assert all(
        locked_versions[name] == version for name, version in report["distributions"].items()
    )
    assets = Path(report["assets"])
    assert (
        assets.joinpath("USER_GUIDE.md").read_bytes() == (_ROOT / "docs/USER_GUIDE.md").read_bytes()
    )
    for source in (_ROOT / "src/agent_fleet/assets").rglob("*"):
        if source.is_file() and source.suffix != ".pyc" and "__pycache__" not in source.parts:
            assert (
                assets.joinpath(source.relative_to(_ROOT / "src/agent_fleet/assets")).read_bytes()
                == source.read_bytes()
            )
    (root / "installation-evidence.json").write_text(json.dumps(report, indent=2) + "\n")
    return InstalledFleet(root, interpreter, virtual / "bin/fleet", environment, assets)


def _project(installed: InstalledFleet, name: str = "learning-project") -> Path:
    target = installed.root / name
    shutil.copytree(
        installed.assets / "canary", target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
    )
    # A normal raw git add would load this global filter. Hardened adapter calls
    # must ignore it, preserving the real HOME needed only for local Docker context.
    sentinel = installed.root / "unexpected-git-filter"
    attributes = installed.root / "global-attributes"
    attributes.write_text("*.py filter=fleet_release_probe\n")
    poison = installed.root / "global-git-config"
    poison.write_text(
        f'[core]\nattributesFile = "{attributes}"\n'
        f'[filter "fleet_release_probe"]\nclean = touch "{sentinel}"\nrequired = true\n'
    )
    installed.environment.update(
        {"GIT_CONFIG_GLOBAL": str(poison), "GIT_CONFIG_SYSTEM": str(poison)}
    )
    commands = (
        ["init", "--template=", "--initial-branch=main"],
        ["add", "--", "."],
        [
            "commit",
            "--no-gpg-sign",
            "--no-verify",
            "--no-status",
            "-m",
            "Learning baseline",
        ],
    )
    installed.process(
        [
            str(installed.python),
            "-I",
            "-c",
            "import json,sys; from pathlib import Path; "
            "from agent_fleet.adapters.repository.git import GitRepositoryAdapter; "
            "from agent_fleet.adapters.system import UuidIdGenerator; "
            "adapter=GitRepositoryAdapter(Path(sys.argv[2]), UuidIdGenerator()); "
            "[adapter._run(['git', *argv], cwd=Path(sys.argv[1])) "
            "for argv in json.loads(sys.argv[3])]",
            str(target),
            str(installed.root / "state"),
            json.dumps(commands),
        ]
    )
    assert not sentinel.exists()
    return target


def _run_and_apply(installed: InstalledFleet, target: Path, *, isolated: bool) -> None:
    goal = "Fix the canary behavior"
    conversation: dict[str, object] | None = None
    if isolated:
        conversation = installed.invoke(
            ["chat", str(target), "--message", goal, "--submission-id", "learning-change"]
        )
        result = cast(dict[str, object], conversation["run"])
    else:
        result = installed.invoke(["run", goal, "--project", str(target)])
    run_id = str(result["run_id"])
    persistent_rule: str | None = None
    for _ in range(12):
        if result["status"] != "paused_for_approval":
            break
        approval = str(result["pending_approval_id"])
        explanation = installed.invoke(["permissions", "explain", approval])
        request = cast(dict[str, object], explanation["request"])
        if isolated and persistent_rule is None and request["action"] == "command.run":
            grant = installed.invoke(["approve", approval, "--always", "--scope", "project"])
            assert isinstance(grant["source_rule_id"], str)
            persistent_rule = grant["source_rule_id"]
        else:
            installed.invoke(["approve", approval, "--once"])
        result = installed.invoke(["resume", run_id])
    assert result["status"] == "ready_for_review", result
    assert result["verified_complete"] is isolated
    evidence = result["evidence"]
    assert isinstance(evidence, dict)
    assert evidence["changed_paths"] == ["src/canary_calc/core.py"]
    commands = evidence["command_results"]
    assert isinstance(commands, list) and len(commands) == 2
    assert len({c["agent_instance_id"] for c in commands}) == 2
    assert all(c["command_id"] == "python-test" for c in commands)
    if isolated:
        assert evidence["proof_gaps"] == []
        assert all(
            c["exit_code"] == 0
            and c["strength"] in {"observed", "independently_verified"}
            and c["sandbox_security_level"] == "isolated"
            for c in commands
        )
        transcripts = installed.process(
            [
                str(installed.python),
                "-I",
                "-c",
                "import json,sys; from pathlib import Path; "
                "from agent_fleet.bootstrap import build_container; "
                "c=build_container(Path(sys.argv[1])); "
                "print(json.dumps([c.artifacts.read_text(i) for i in json.loads(sys.argv[2])]))",
                str(installed.root / "state"),
                json.dumps([c["transcript_artifact_id"] for c in commands]),
            ]
        )
        assert all("5 passed" in transcript for transcript in json.loads(transcripts.stdout))
    else:
        assert "SIMULATED_EVIDENCE_ONLY" in evidence["completion_reason_codes"]
    assert (target / "src/canary_calc/core.py").read_text() == BROKEN_CANARY
    assert installed.invoke(["status", run_id])["status"] == "ready_for_review"
    artifacts = installed.listing(["artifacts", run_id])
    assert artifacts and all(len(str(item["sha256"])) == 64 for item in artifacts)
    installed.invoke(["patch", "show", run_id])
    applied = installed.invoke(["patch", "apply", run_id])
    assert applied["status"] == "completed"
    assert (target / "src/canary_calc/core.py").read_text() == FIXED_CANARY
    if conversation is not None:
        replay = installed.invoke(
            [
                "chat",
                str(target),
                "--message",
                goal,
                "--conversation",
                str(conversation["conversation_id"]),
                "--submission-id",
                "learning-change",
            ]
        )
        assert (replay["run_id"], replay["turn_id"]) == (run_id, conversation["turn_id"])
        events = installed.listing(["logs", run_id])
        assert sum(item["event_type"] == "run.created" for item in events) == 1
        assert persistent_rule is not None
        assert installed.invoke(["permissions", "explain", persistent_rule])["active"] is True
        installed.invoke(["permissions", "revoke", persistent_rule])
        assert installed.invoke(["permissions", "explain", persistent_rule])["active"] is False
        recovered = installed.invoke(["recover", run_id, "--confirm-owner-stopped"])
        assert recovered["status"] == "completed" and recovered["recovered"] is False
        assert recovered["outstanding_lease_ids"] == recovered["recovered_lease_ids"] == []
    installed.process(
        [
            str(installed.python),
            "-I",
            "-c",
            "from pathlib import Path; from agent_fleet.bootstrap import build_container; "
            "c=build_container(Path(__import__('sys').argv[1])); "
            "assert not c.state.outstanding_leases()",
            str(installed.root / "state"),
        ]
    )


def _evolve_installed_organization(installed: InstalledFleet, image: str) -> None:
    # A separate public registration uses only an offline model substitution.
    # Stock fake does not promise natural-language organization understanding.
    target = _project(installed, "organization-project")
    entry = [
        str(installed.python),
        "-I",
        "-c",
        _OFFLINE_PROPOSAL_ENTRY,
        str(_ROOT / "tests/evolution_fixtures.py"),
    ]
    initialized = installed.invoke(
        [
            "init",
            str(target),
            "--runtime",
            "pydantic-ai",
            "--provider-model",
            "openai:offline-test",
            "--credential-ref",
            "env:FLEET_RELEASE_UNUSED_TEST_KEY",
            "--sandbox",
            "docker",
            "--docker-image",
            image,
            "--trust-mode",
            "safe",
            "--allow-path",
            "src",
            "--yes",
        ],
        entry=entry,
    )
    assert initialized["bootstrap_verified"] is True
    baseline = {
        file.relative_to(target).as_posix(): file.read_bytes()
        for file in (target / ".fleet").rglob("*")
        if file.is_file()
    }
    goal = "For backend changes, always run integration tests."
    view = installed.invoke(
        ["chat", str(target), "--message", goal, "--submission-id", "backend-rule"], entry=entry
    )
    assert cast(dict[str, object], view["run"])["status"] == "completed"
    proposals = installed.listing(["fleet-patch", "list", "--path", str(target)])
    assert len(proposals) == 1
    proposal_id = str(proposals[0]["proposal_id"])
    shown = installed.invoke(["fleet-patch", "show", proposal_id])
    diff = installed.invoke(["fleet-patch", "diff", proposal_id])
    assert shown["proposal_sha256"] == diff["proposal_sha256"]
    assert "backend-integration" in str(diff["text_diff"])
    assert baseline == {
        file.relative_to(target).as_posix(): file.read_bytes()
        for file in (target / ".fleet").rglob("*")
        if file.is_file()
    }
    applied = installed.invoke(["fleet-patch", "apply", proposal_id])
    assert cast(dict[str, object], applied["version"])["version"] == 1
    assert applied["cleanup_complete"] is True
    assert (target / ".fleet/skills/backend-integration.yaml").is_file()
    assert (
        installed.invoke(["fleet-patch", "operation", str(applied["operation_id"])])["status"]
        == "committed"
    )
    inverse = installed.invoke(["fleet-patch", "rollback", proposal_id])
    assert cast(dict[str, object], inverse["version"])["version"] == 2
    assert inverse["proposal_id"] != proposal_id and inverse["cleanup_complete"] is True
    assert baseline == {
        file.relative_to(target).as_posix(): file.read_bytes()
        for file in (target / ".fleet").rglob("*")
        if file.is_file()
    }
    replay = installed.invoke(
        [
            "chat",
            str(target),
            "--message",
            goal,
            "--conversation",
            str(view["conversation_id"]),
            "--submission-id",
            "backend-rule",
        ]
    )
    assert (replay["run_id"], replay["turn_id"]) == (view["run_id"], view["turn_id"])
    assert (target / "src/canary_calc/core.py").read_text() == BROKEN_CANARY


@pytest.mark.parametrize("archive_kind", ["whl", "tar.gz"])
def test_fresh_distribution_offline_resources_and_test_seeded_workflow(
    tmp_path: Path,
    prepared_wheelhouse: Path,
    archive_kind: str,
) -> None:
    installed = _install(tmp_path / "fresh", prepared_wheelhouse, archive_kind)
    assert installed.invoke(["version"])["phase"] == "6"
    target = _project(installed)
    before = (target / "src/canary_calc/core.py").read_bytes()
    installed.invoke(["init", str(target), "--runtime", "fake", "--sandbox", "fake", "--preview"])
    assert not (target / ".fleet").exists() and not (installed.root / "state").exists()
    error = installed.invoke(
        ["init", str(target), "--runtime", "fake", "--sandbox", "fake", "--yes"], expected=1
    )
    assert error["code"] == "BOOTSTRAP_CANARY_FAILED" and not (target / ".fleet").exists()
    assert (target / "src/canary_calc/core.py").read_bytes() == before
    # Private test seed is intentionally not a supported public initialization shortcut.
    installed.process(
        [
            str(installed.python),
            "-I",
            "-c",
            "from pathlib import Path; from agent_fleet.bootstrap import build_container; "
            "import sys; build_container(Path(sys.argv[2])).projects._initialize_without_canary("
            "Path(sys.argv[1]), runtime_name='fake', sandbox_name='fake')",
            str(target),
            str(installed.root / "state"),
        ]
    )
    _run_and_apply(installed, target, isolated=False)


@pytest.mark.docker_integration
def test_fresh_installed_public_docker_learning_journey(
    tmp_path: Path,
    prepared_wheelhouse: Path,
    real_docker_image: str,
) -> None:
    installed = _install(tmp_path / "fresh", prepared_wheelhouse, "whl")
    target = _project(installed)
    try:
        doctor = installed.invoke(
            [
                "doctor",
                "--path",
                str(target),
                "--sandbox",
                "docker",
                "--docker-image",
                real_docker_image,
            ]
        )
        assert doctor["healthy"] is True
        checks = cast(list[dict[str, object]], doctor["checks"])
        assert all(check["ok"] is True for check in checks if check["required"])
        initialized = installed.invoke(
            [
                "init",
                str(target),
                "--runtime",
                "fake",
                "--sandbox",
                "docker",
                "--docker-image",
                real_docker_image,
                "--trust-mode",
                "safe",
                "--allow-path",
                "src",
                "--yes",
            ]
        )
        assert initialized["bootstrap_verified"] is True
        assert initialized["bootstrap_cleanup_complete"] is True
        _run_and_apply(installed, target, isolated=True)
        _evolve_installed_organization(installed, real_docker_image)
    finally:
        # All CLI subprocesses have stopped; reconcile only this disposable state's
        # exact outstanding Run identities, then inspect its exact container scope.
        installed.process(
            [
                str(installed.python),
                "-I",
                "-c",
                """
import asyncio, sys
from pathlib import Path
from agent_fleet.bootstrap import build_container
container = build_container(Path(sys.argv[1]))
async def reconcile():
    for run_id in sorted({lease.run_id for lease in container.state.outstanding_leases()}):
        await container.recovery.recover_run(run_id)
    assert not container.state.outstanding_leases()
    provider = container.sandboxes.get("docker")
    executable = provider._require_executable()
    await provider._require_local_linux_daemon(executable)
    assert await provider._list_exact(
        executable, {"agent-fleet.installation": provider.recovery_scope_id}
    ) == []
asyncio.run(reconcile())
""",
                str(installed.root / "state"),
            ]
        )
