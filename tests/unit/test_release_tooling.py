from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from pip._internal import configuration as pip_configuration


def test_pinned_pip_devnull_disables_global_and_site_config_even_when_isolated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    global_config = tmp_path / "global-pip.conf"
    site_config = tmp_path / "site-pip.conf"
    global_config.write_text(
        "[global]\nextra-index-url = https://untrusted.example.invalid/simple\n"
    )
    site_config.write_text("[global]\nproxy = https://untrusted.example.invalid/proxy\n")
    kinds = pip_configuration.kinds
    monkeypatch.setattr(
        pip_configuration,
        "get_configuration_files",
        lambda: {
            kinds.GLOBAL: [str(global_config)],
            kinds.USER: [],
            kinds.SITE: [str(site_config)],
        },
    )
    monkeypatch.delenv("PIP_CONFIG_FILE", raising=False)
    inherited = pip_configuration.Configuration(isolated=True)
    inherited.load()
    assert (
        inherited.get_value("global.extra-index-url") == "https://untrusted.example.invalid/simple"
    )
    assert inherited.get_value("global.proxy") == "https://untrusted.example.invalid/proxy"
    monkeypatch.setenv("PIP_CONFIG_FILE", os.devnull)
    isolated = pip_configuration.Configuration(isolated=True)
    isolated.load()
    assert dict(isolated.items()) == {}
    assert (
        'environment["PIP_CONFIG_FILE"] = os.devnull'
        in (Path(__file__).parents[2] / "scripts/prepare_release_dependencies.py").read_text()
    )


_ROOT = Path(__file__).parents[2]


def test_ci_uses_read_only_pinned_actions_and_no_live_provider() -> None:
    workflow = yaml.load((_ROOT / ".github/workflows/ci.yml").read_text(), Loader=yaml.BaseLoader)
    assert workflow["permissions"] == {"contents": "read"}
    assert set(workflow["on"]) == {"pull_request", "push", "workflow_dispatch"}
    assert workflow["on"]["push"]["branches"] == ["main"]
    assert workflow["on"]["pull_request"]["branches"] == ["main"]
    assert workflow["env"]["AGENT_FLEET_ENABLE_LIVE_PROVIDER_TESTS"] == "0"
    matrix = workflow["jobs"]["platform"]["strategy"]["matrix"]
    assert matrix == {"os": ["ubuntu-24.04", "macos-14"], "python": ["3.12", "3.13", "3.14"]}
    for job in workflow["jobs"].values():
        assert 1 <= int(job["timeout-minutes"]) <= 40
        assert "permissions" not in job
        for step in job["steps"]:
            if "uses" in step:
                assert re.fullmatch(r"[a-zA-Z0-9/_-]+@[a-f0-9]{40}", step["uses"])
                if step["uses"].startswith("actions/checkout@"):
                    assert step["with"]["persist-credentials"] == "false"
    source = (_ROOT / ".github/workflows/ci.yml").read_text()
    assert "secrets." not in source and "pull_request_target" not in source
    assert "uv python install" in source and "--frozen" in source and "--offline" in source
    assert "python scripts/verify_adversarial.py" in source


@pytest.mark.parametrize(
    "script,flag",
    [("prepare_release_dependencies.py", "--destination"), ("verify_adversarial.py", "--output")],
)
@pytest.mark.parametrize("destination_kind", ["existing", "relative", "symlink"])
def test_release_scripts_reject_unsafe_destinations_before_setup_or_execution(
    tmp_path: Path,
    script: str,
    flag: str,
    destination_kind: str,
) -> None:
    original = tmp_path / "preserved"
    original.mkdir()
    marker = original / "user-file"
    marker.write_text("Keep this exact file unchanged.\n")
    link = tmp_path / "linked"
    link.symlink_to(original, target_is_directory=True)
    target = {"existing": str(original), "relative": "new-relative", "symlink": str(link)}[
        destination_kind
    ]
    result = subprocess.run(
        [sys.executable, "-I", str(_ROOT / "scripts" / script), flag, target],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 2 and "error:" in result.stderr
    assert marker.read_text() == "Keep this exact file unchanged.\n"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["linked", "preserved"]
