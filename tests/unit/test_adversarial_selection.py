from __future__ import annotations

import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from scripts import verify_adversarial

_COHORT_TEST = "tests/docker/test_business_baseline_cohort.py"


def _write_junit(
    path: Path,
    *,
    tests: int = 1,
    failures: int = 0,
    errors: int = 0,
    skipped: int = 0,
) -> None:
    suite = ET.Element(
        "testsuite",
        tests=str(tests),
        failures=str(failures),
        errors=str(errors),
        skipped=str(skipped),
    )
    for index in range(tests):
        case = ET.SubElement(
            suite,
            "testcase",
            classname="tests.synthetic.test_selection",
            name=f"test_case_{index}",
        )
        if index < skipped:
            ET.SubElement(case, "skipped")
        elif index < skipped + failures:
            ET.SubElement(case, "failure")
        elif index < skipped + failures + errors:
            ET.SubElement(case, "error")
    ET.ElementTree(suite).write(path, encoding="utf-8", xml_declaration=True)


def _invoke(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    arguments: Sequence[str],
    *,
    tests: int = 1,
    failures: int = 0,
    errors: int = 0,
    skipped: int = 0,
    pytest_exit_code: int = 0,
    write_report: bool = True,
) -> tuple[int, dict[str, Any], list[str], dict[str, str]]:
    output = tmp_path / "evidence"
    captured_command: list[str] = []
    captured_environment: dict[str, str] = {}

    def synthetic_run(
        command: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        check: bool,
        timeout: int,
    ) -> subprocess.CompletedProcess[str]:
        assert cwd == Path(verify_adversarial.__file__).resolve().parents[1]
        assert check is False
        assert timeout == 1200
        captured_command.extend(command)
        captured_environment.update(env)
        junit_argument = next(value for value in command if value.startswith("--junitxml="))
        if write_report:
            _write_junit(
                Path(junit_argument.removeprefix("--junitxml=")),
                tests=tests,
                failures=failures,
                errors=errors,
                skipped=skipped,
            )
        return subprocess.CompletedProcess(command, pytest_exit_code)

    monkeypatch.setattr("scripts.verify_adversarial.subprocess.run", synthetic_run)
    monkeypatch.setattr(
        sys,
        "argv",
        ["verify_adversarial.py", "--output", str(output), *arguments],
    )
    with pytest.raises(SystemExit) as raised:
        verify_adversarial.main()
    assert isinstance(raised.value.code, int)
    report = json.loads((output / "evidence.json").read_text())
    return (
        raised.value.code,
        report,
        captured_command,
        captured_environment,
    )


def test_existing_docker_scope_excludes_cohort_and_clears_ambient_inputs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("AGENT_FLEET_BASELINE_COHORT_IMAGE", "ambient-cohort")
    monkeypatch.setenv("OPENAI_API_KEY", "ambient-secret")
    monkeypatch.setenv("FLEET_OPENAI_TEST_KEY", "ambient-fleet-secret")

    exit_code, report, command, environment = _invoke(
        monkeypatch,
        tmp_path,
        ["--docker", "--image", "reviewed-runner"],
    )

    selection = ["-m", "docker_integration", "tests/docker", f"--ignore={_COHORT_TEST}"]
    assert exit_code == 0
    assert command == [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        *selection,
        f"--basetemp={tmp_path / 'evidence' / 'fixtures'}",
        f"--junitxml={tmp_path / 'evidence' / 'results.xml'}",
    ]
    assert report["selection"] == selection
    assert report["baseline_cohort_selected"] is False
    assert report["excluded_test_paths"] == [_COHORT_TEST]
    assert environment["AGENT_FLEET_DOCKER_TEST_IMAGE"] == "reviewed-runner"
    assert "AGENT_FLEET_BASELINE_COHORT_IMAGE" not in environment
    assert "OPENAI_API_KEY" not in environment
    assert "FLEET_OPENAI_TEST_KEY" not in environment
    assert environment["AGENT_FLEET_ENABLE_LIVE_PROVIDER_TESTS"] == "0"
    assert environment["AGENT_FLEET_ENABLE_INSTALL_TESTS"] == "0"
    assert environment["AGENT_FLEET_ENABLE_DOCKER_TESTS"] == "1"


def test_explicit_cohort_scope_includes_cohort_with_only_reviewed_image(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("AGENT_FLEET_BASELINE_COHORT_IMAGE", "ambient-cohort")
    monkeypatch.setenv("AGENT_FLEET_UNRELATED_SECRET", "ambient-secret")

    exit_code, report, command, environment = _invoke(
        monkeypatch,
        tmp_path,
        [
            "--docker",
            "--image",
            "reviewed-runner",
            "--baseline-cohort-image",
            "reviewed-cohort",
        ],
    )

    selection = ["-m", "docker_integration", "tests/docker"]
    assert exit_code == 0
    assert command[4 : 4 + len(selection)] == selection
    assert f"--ignore={_COHORT_TEST}" not in command
    assert report["selection"] == selection
    assert report["baseline_cohort_selected"] is True
    assert report["excluded_test_paths"] == []
    assert environment["AGENT_FLEET_DOCKER_TEST_IMAGE"] == "reviewed-runner"
    assert environment["AGENT_FLEET_BASELINE_COHORT_IMAGE"] == "reviewed-cohort"
    assert "AGENT_FLEET_UNRELATED_SECRET" not in environment


@pytest.mark.parametrize(
    "arguments",
    [
        ["--baseline-cohort-image", "orphan-cohort"],
        ["--docker", "--baseline-cohort-image", "orphan-cohort"],
        ["--docker", "--image", ""],
        ["--docker", "--image", "reviewed-runner", "--baseline-cohort-image", ""],
        ["--docker", "--image", "reviewed-runner", "--baseline-cohort-image", "   "],
        ["--docker", "--image", "reviewed-runner", "--baseline-cohort-image"],
    ],
)
def test_invalid_cohort_arguments_fail_before_output_or_dispatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    arguments: list[str],
) -> None:
    output = tmp_path / "evidence"
    calls: list[object] = []
    monkeypatch.setattr("scripts.verify_adversarial.subprocess.run", calls.append)
    monkeypatch.setattr(
        sys,
        "argv",
        ["verify_adversarial.py", "--output", str(output), *arguments],
    )

    with pytest.raises(SystemExit) as raised:
        verify_adversarial.main()

    assert raised.value.code == 2
    assert not output.exists()
    assert calls == []


@pytest.mark.parametrize(
    ("tests", "failures", "errors", "skipped", "pytest_exit_code", "write_report"),
    [
        (1, 0, 0, 1, 0, True),
        (0, 0, 0, 0, 0, True),
        (1, 1, 0, 0, 0, True),
        (1, 0, 1, 0, 0, True),
        (0, 0, 0, 0, 0, False),
    ],
)
def test_skip_empty_failure_and_error_results_never_pass(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    tests: int,
    failures: int,
    errors: int,
    skipped: int,
    pytest_exit_code: int,
    write_report: bool,
) -> None:
    exit_code, report, _, _ = _invoke(
        monkeypatch,
        tmp_path,
        ["--docker", "--image", "reviewed-runner"],
        tests=tests,
        failures=failures,
        errors=errors,
        skipped=skipped,
        pytest_exit_code=pytest_exit_code,
        write_report=write_report,
    )

    assert exit_code == 1
    assert report["exit_code"] == 1
    assert report["pytest_exit_code"] == pytest_exit_code
    assert report["baseline_cohort_selected"] is False
    assert report["counts"] == {
        "tests": tests if write_report else 0,
        "failures": failures if write_report else 0,
        "errors": errors if write_report else 0,
        "skipped": skipped if write_report else 0,
    }
    assert bool(report["unexpected_skips"]) is bool(skipped)


def test_ci_standard_docker_scope_excludes_optional_cohort() -> None:
    workflow = (
        Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"
    ).read_text()
    expected = """      - name: Standard Docker coverage and fresh installed public journey
        env:
          AGENT_FLEET_ENABLE_DOCKER_TESTS: \"1\"
          AGENT_FLEET_DOCKER_TEST_IMAGE: agent-fleet-runner:0.1.0-py314-v1
          AGENT_FLEET_ENABLE_INSTALL_TESTS: \"1\"
          AGENT_FLEET_TEST_WHEELHOUSE: ${{ runner.temp }}/fleet-wheelhouse
        run: >-
          uv run --offline pytest -q -m docker_integration tests/docker tests/release
          --ignore=tests/docker/test_business_baseline_cohort.py
"""

    assert expected in workflow
