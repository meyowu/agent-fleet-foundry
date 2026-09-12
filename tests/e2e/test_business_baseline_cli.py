"""Public subprocess CLI admission/help plus an in-process offline transport journey."""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

if TYPE_CHECKING:
    from test_business_baseline_integration import business_fixture, set_baseline_output
else:
    from integration.test_business_baseline_integration import business_fixture, set_baseline_output

import agent_fleet
import agent_fleet.cli.app as cli
from agent_fleet.domain.security import Redactor


@pytest.mark.e2e
@pytest.mark.parametrize(
    "arguments",
    [["baseline", "--help"], ["baseline", "run", "--help"], ["baseline", "recover", "--help"]],
)
def test_baseline_help_subprocess_does_not_construct_state(
    tmp_path: Path, arguments: list[str]
) -> None:
    source = Path(agent_fleet.__file__).resolve().parents[1]
    environment = {
        "PATH": os.defpath,
        "PYTHONPATH": str(source),
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "AGENT_FLEET_HOME": str(tmp_path / "state"),
        "AGENT_FLEET_ENABLE_LIVE_PROVIDER_TESTS": "0",
        "AGENT_FLEET_ENABLE_DOCKER_TESTS": "0",
        "AGENT_FLEET_ENABLE_INSTALL_TESTS": "0",
    }
    result = subprocess.run(
        [sys.executable, "-m", "agent_fleet.cli.app", *arguments],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (tmp_path / "state").exists()


@pytest.mark.parametrize("command_exit", [0, 1])
def test_public_cli_offline_baseline_consent_and_durable_observation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command_exit: int
) -> None:
    secret = "standalone-fixture-secret"
    container, root, command, transport = business_fixture(tmp_path, redactor=Redactor([secret]))
    set_baseline_output(
        monkeypatch,
        transport,
        stdout=f"public stdout {secret} \x1b\n".encode(),
        stderr=b"public assertion stderr \x00\n",
        returncode=command_exit,
    )
    monkeypatch.setattr(cli, "build_baseline_container", lambda **_: container)
    runner = CliRunner()
    planned = runner.invoke(
        cli.app, ["baseline", "plan", str(root), "--command", command, "--json"]
    )
    assert planned.exit_code == 0, planned.output
    data = json.loads(planned.stdout)["data"]
    assert data["observation"] is None
    review = data["review"]["review_id"]
    missing = runner.invoke(cli.app, ["baseline", "run", review, "--json"])
    assert missing.exit_code == 2, missing.output
    assert not any(argv[1:3] == ("container", "create") for argv, _ in transport.calls)
    observed = runner.invoke(
        cli.app,
        [
            "baseline",
            "run",
            review,
            "--allow-once",
            "--review-sha256",
            data["review_sha256"],
            "--json",
        ],
    )
    assert observed.exit_code == command_exit, observed.output
    assert secret not in observed.stdout
    assert "\x1b" not in observed.stdout and "\x00" not in observed.stdout
    result = json.loads(observed.stdout)["data"]
    report = result["report"]
    assert report["status"] == "observed" and report["cleanup_complete"]
    assert report["completion_assurance"] == "baseline_observation_only"
    assert report["target_applied"] is False
    assert report["observed_exit_code"] == command_exit
    observation = result["observation"]
    assert observation["stdout"] == "public stdout <redacted:1> \\u001b\n"
    assert observation["stderr"] == "public assertion stderr \\u0000\n"
    assert observation["exit_code"] == command_exit
    before_show = len(transport.calls)
    shown = runner.invoke(cli.app, ["baseline", "show", data["review"]["baseline_id"], "--json"])
    assert shown.exit_code == 0, shown.output
    assert json.loads(shown.stdout)["data"] == result
    assert len(transport.calls) == before_show
    assert sum(argv[1:3] == ("container", "start") for argv, _ in transport.calls) == 1
