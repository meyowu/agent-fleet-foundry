from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tomllib
from importlib.resources import files
from pathlib import Path

from agent_fleet.domain.offline_canary import BROKEN_CANARY, FIXED_CANARY


def test_runner_is_packaged_pinned_and_uses_only_reviewed_wheels() -> None:
    root = Path(__file__).parents[2]
    runner = files("agent_fleet").joinpath("assets/runner")
    recipe = runner.joinpath("Dockerfile").read_text()
    assert recipe == (root / "tests/docker/Dockerfile.runner").read_text()
    assert recipe.startswith("FROM python:3.14-slim@sha256:")
    assert "ENV PIP_CONFIG_FILE=/dev/null" in recipe.split("FROM scratch")[0]
    assert "PIP_CONFIG_FILE" not in recipe.split("FROM scratch")[1]
    assert "ARG " not in recipe and "sh -c" not in recipe
    assert 'RUN ["python", "-I", "-m", "pip", "--isolated"' in recipe
    assert '"--require-hashes"' in recipe and '"--only-binary=:all:"' in recipe
    assert recipe.count("FROM scratch") == 1
    assert "!requirements.lock" in runner.joinpath(".dockerignore").read_text()
    lock = tomllib.loads((root / "uv.lock").read_text())
    lines = runner.joinpath("requirements.lock").read_text().splitlines()
    requirements = [line for line in lines if line and not line.startswith("#")]
    assert len(requirements) == 5
    for requirement in requirements:
        match = re.fullmatch(r"([a-z]+)==([0-9.]+) --hash=sha256:([a-f0-9]{64})", requirement)
        assert match is not None
        name, version, digest = match.groups()
        package = next(p for p in lock["package"] if p["name"] == name)
        assert package["version"] == version
        assert any(
            wheel["hash"] == f"sha256:{digest}" and wheel["url"].endswith("-py3-none-any.whl")
            for wheel in package["wheels"]
        )


def test_public_learning_fixture_really_fails_then_passes(tmp_path: Path) -> None:
    canary = files("agent_fleet").joinpath("assets/canary")
    target = tmp_path / "learning-project"
    shutil.copytree(str(canary), target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    source = target / "src/canary_calc/core.py"
    assert source.read_text() == BROKEN_CANARY
    for repaired in (False, True):
        if repaired:
            source.write_text(FIXED_CANARY)
        result = subprocess.run(
            [sys.executable, "-I", "-m", "pytest", "-q", "-p", "no:cacheprovider"],
            cwd=target,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        assert result.returncode == (0 if repaired else 1), result.stdout + result.stderr
        assert ("5 passed" if repaired else "1 failed, 4 passed") in result.stdout
