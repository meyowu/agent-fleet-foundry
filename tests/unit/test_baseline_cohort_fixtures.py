"""Default checks inspect the six fixtures without executing their business tests."""

from __future__ import annotations

import importlib.util
import signal
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from baseline_cohort_fixtures import CASES, BaselineCase, create_repository, fixture_git

from agent_fleet.adapters.repository.profile import StaticRepositoryProfiler


@pytest.fixture(scope="module")
def cohort_module() -> Iterator[ModuleType]:
    path = Path(__file__).resolve().parents[1] / "docker" / "test_business_baseline_cohort.py"
    name = "business_baseline_cohort_under_test"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        assert sys.modules.pop(name) is module


class _FakeCliProcess:
    pid = 424_242
    returncode = -signal.SIGKILL

    def __init__(self, responses: list[tuple[str, str] | BaseException]) -> None:
        self.responses = responses
        self.timeouts: list[int] = []

    def communicate(self, *, timeout: int) -> tuple[str, str]:
        self.timeouts.append(timeout)
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def _replace_process(
    cohort: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    process: _FakeCliProcess,
) -> list[tuple[int, signal.Signals]]:
    monkeypatch.setattr(cohort.subprocess, "Popen", lambda *args, **kwargs: process)
    killed: list[tuple[int, signal.Signals]] = []
    monkeypatch.setattr(cohort.os, "killpg", lambda pid, sig: killed.append((pid, sig)))
    return killed


def test_cohort_has_exact_six_distinct_preregistered_slots() -> None:
    assert len(CASES) == len({case.identity for case in CASES}) == 6
    assert {case.outcome for case in CASES} == {
        "passing",
        "missing_dependency",
        "preexisting_failure",
    }


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.identity)
def test_cohort_profile_and_frozen_source(tmp_path: Path, case: BaselineCase) -> None:
    repository = create_repository(tmp_path / case.identity, case)
    before = fixture_git(repository, "rev-parse", "HEAD")
    result = StaticRepositoryProfiler().profile(repository)
    assert result.profile.ecosystems == [case.ecosystem]
    command = next(item for item in result.profile.commands if item.name == case.command_id)
    assert (command.executable, tuple(command.argv)) == (
        ("python", ("-m", "pytest")) if case.ecosystem == "python" else ("npm", ("run", "test"))
    )
    assert not command.execution_authorized
    assert fixture_git(repository, "status", "--porcelain") == ""
    assert fixture_git(repository, "rev-parse", "HEAD") == before
    assert {name: (repository / name).read_text() for name in case.files()} == case.files()
    assert not (repository / ".fleet").exists()


@pytest.mark.parametrize(
    "interruption",
    [
        subprocess.TimeoutExpired(cmd=("fleet",), timeout=360),
        KeyboardInterrupt(),
    ],
    ids=("watchdog", "interrupt"),
)
def test_hard_termination_marks_owner_quiescence_unknown(
    tmp_path: Path,
    cohort_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    interruption: BaseException,
) -> None:
    process = _FakeCliProcess([interruption, ("", "")])
    killed = _replace_process(cohort_module, monkeypatch, process)
    owner_state = cohort_module._CliOwnerState()

    with pytest.raises(type(interruption)):
        cohort_module._cli(tmp_path, tmp_path / "state", "readiness", owner_state=owner_state)

    assert owner_state.quiescence is cohort_module._OwnerQuiescence.UNKNOWN
    assert process.timeouts == [360, 10]
    assert killed == [(process.pid, signal.SIGKILL)]


@pytest.mark.parametrize("failure", ["kill", "reap"])
def test_failed_hard_termination_cleanup_stays_unknown(
    tmp_path: Path,
    cohort_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    watchdog = subprocess.TimeoutExpired(cmd=("fleet",), timeout=360)
    responses: list[tuple[str, str] | BaseException] = [watchdog, ("", "")]
    if failure == "reap":
        responses[-1] = subprocess.TimeoutExpired(cmd=("fleet",), timeout=10)
    process = _FakeCliProcess(responses)
    killed = _replace_process(cohort_module, monkeypatch, process)
    if failure == "kill":
        monkeypatch.setattr(
            cohort_module.os,
            "killpg",
            lambda pid, sig: (_ for _ in ()).throw(PermissionError("synthetic kill failure")),
        )
    owner_state = cohort_module._CliOwnerState()

    with pytest.raises((PermissionError, subprocess.TimeoutExpired)):
        cohort_module._cli(tmp_path, tmp_path / "state", "readiness", owner_state=owner_state)

    assert owner_state.quiescence is cohort_module._OwnerQuiescence.UNKNOWN
    assert process.timeouts == ([360] if failure == "kill" else [360, 10])
    if failure == "reap":
        assert killed == [(process.pid, signal.SIGKILL)]


def test_unknown_quiescence_never_shows_or_recovers(
    tmp_path: Path,
    cohort_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_state = cohort_module._CliOwnerState()
    owner_state.mark_unknown()

    def forbidden(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise AssertionError("unknown owner quiescence cannot inspect or recover")

    monkeypatch.setattr(cohort_module, "_data", forbidden)
    monkeypatch.setattr(cohort_module, "_cli", forbidden)

    cohort_module._recover_after_completed_cli(
        tmp_path, tmp_path / "state", "baseline_" + "1" * 32, owner_state
    )


@pytest.mark.parametrize("signal_number", [signal.SIGTERM, signal.SIGKILL])
@pytest.mark.parametrize("stdout", ['{"ok": true, "data": {}}', "", "invalid JSON"])
def test_signal_exit_fails_before_parsing_and_finally_cannot_recover(
    tmp_path: Path,
    cohort_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    signal_number: signal.Signals,
    stdout: str,
) -> None:
    process = _FakeCliProcess([(stdout, "")])
    process.returncode = -signal_number
    killed = _replace_process(cohort_module, monkeypatch, process)
    owner_state = cohort_module._CliOwnerState()
    invoke = cohort_module._cli
    calls: list[str] = []

    def forbidden(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        calls.append("unsafe show or recovery")
        raise AssertionError("signal-terminated owner cannot inspect or recover")

    monkeypatch.setattr(cohort_module, "_data", forbidden)
    monkeypatch.setattr(cohort_module, "_cli", forbidden)
    with pytest.raises(pytest.fail.Exception, match="terminated by signal"):
        try:
            invoke(tmp_path, tmp_path / "state", "readiness", owner_state=owner_state)
        finally:
            cohort_module._recover_after_completed_cli(
                tmp_path, tmp_path / "state", "baseline_" + "3" * 32, owner_state
            )

    assert owner_state.quiescence is cohort_module._OwnerQuiescence.UNKNOWN
    assert process.timeouts == [360]
    assert killed == []
    assert calls == []


@pytest.mark.parametrize("returncode", [0, 1, 2, 3])
def test_ordinary_exit_retains_known_state_and_exact_exit_code(
    tmp_path: Path,
    cohort_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    returncode: int,
) -> None:
    process = _FakeCliProcess([('{"ok": true, "data": {"retained": true}}', "")])
    process.returncode = returncode
    killed = _replace_process(cohort_module, monkeypatch, process)
    owner_state = cohort_module._CliOwnerState()

    data = cohort_module._data(
        tmp_path,
        tmp_path / "state",
        "baseline",
        "show",
        "baseline_" + "4" * 32,
        expected=returncode,
        owner_state=owner_state,
    )

    assert data == {"retained": True}
    assert owner_state.quiescence is cohort_module._OwnerQuiescence.KNOWN
    assert process.timeouts == [360]
    assert killed == []


def test_known_quiescence_retains_exact_public_recovery(
    tmp_path: Path,
    cohort_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_state = cohort_module._CliOwnerState()
    scope = "a" * 64
    calls: list[tuple[str, tuple[str, ...]]] = []

    def shown(target: Path, state: Path, *arguments: str, **kwargs: Any) -> dict[str, Any]:
        del target, state
        assert kwargs == {"owner_state": owner_state}
        calls.append(("show", arguments))
        return {"recovery_scope_sha256": scope, "report": None}

    def recovered(
        target: Path, state: Path, *arguments: str, **kwargs: Any
    ) -> tuple[int, dict[str, Any]]:
        del target, state
        assert kwargs == {"owner_state": owner_state}
        calls.append(("recover", arguments))
        return 0, {"data": {"report": {"cleanup_complete": True}}}

    monkeypatch.setattr(cohort_module, "_data", shown)
    monkeypatch.setattr(cohort_module, "_cli", recovered)
    baseline_id = "baseline_" + "2" * 32

    cohort_module._recover_after_completed_cli(
        tmp_path, tmp_path / "state", baseline_id, owner_state
    )

    assert calls == [
        ("show", ("baseline", "show", baseline_id)),
        (
            "recover",
            (
                "baseline",
                "recover",
                baseline_id,
                "--owner-stopped",
                "--cleanup-sha256",
                scope,
                "--json",
            ),
        ),
    ]
