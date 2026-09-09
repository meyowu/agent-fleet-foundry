from __future__ import annotations

import importlib.util
import json
import os
import signal
import subprocess
import sys
from contextlib import suppress
from pathlib import Path
from types import ModuleType, SimpleNamespace

import live_provider_support
import pytest

SENTINEL = "sk-offline-synthetic-launcher-credential-123456789"


@pytest.fixture
def launcher() -> ModuleType:
    path = Path(__file__).resolve().parents[2] / "scripts" / "run_live_canary.py"
    spec = importlib.util.spec_from_file_location("live_canary_launcher", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_child_environment_is_explicit(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_LOG", "PYTEST_ADDOPTS", "PYTHONPATH"):
        monkeypatch.setenv(name, "unrelated-must-not-inherit")
    result = launcher.child_environment(SENTINEL, "local-image", Path("/safe/evidence"))
    assert result["FLEET_OPENAI_TEST_KEY"] == SENTINEL
    assert result["AGENT_FLEET_LIVE_PROVIDER_MODEL"] == "openai:gpt-5-nano"
    assert result["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"
    assert (
        not {"OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_LOG", "PYTEST_ADDOPTS", "PYTHONPATH"}
        & result.keys()
    )


def test_safe_output_rejects_secret_and_encoded_forms(launcher: ModuleType, tmp_path: Path) -> None:
    forms = live_provider_support.credential_forms(SENTINEL)
    for index, form in enumerate(forms):
        output = tmp_path / f"rejected-{index}.json"
        with pytest.raises(ValueError, match="credential-bearing"):
            launcher.write_safe(output, b"prefix" + form, forms)
        assert not output.exists()
    output = tmp_path / "safe.json"
    launcher.write_safe(output, b'{"safe":true}', forms)
    assert output.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        launcher.write_safe(output, b"second", forms)


def test_read_rejects_secret_and_symlink(launcher: ModuleType, tmp_path: Path) -> None:
    forms = live_provider_support.credential_forms(SENTINEL)
    secret_file = tmp_path / "secret.json"
    secret_file.write_text(json.dumps({"unexpected": SENTINEL}))
    with pytest.raises(ValueError, match="credential-bearing"):
        launcher.read_safe(secret_file, forms)
    link = tmp_path / "link.json"
    link.symlink_to(secret_file)
    with pytest.raises(ValueError, match="invalid evidence"):
        launcher.read_safe(link, forms)


def test_successful_child_capture_is_bounded_and_reaped(launcher: ModuleType) -> None:
    code, captured, reason = launcher.capture_test(
        [sys.executable, "-I", "-c", "print('safe child output')"], {"PATH": os.defpath}
    )
    assert code == 0 and reason == "normal"
    assert captured == b"safe child output\n"


def test_output_limit_stops_child(launcher: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(launcher, "MAX_CAPTURE_BYTES", 8)
    _, captured, reason = launcher.capture_test(
        [sys.executable, "-I", "-c", "import time; print('X'*100, flush=True); time.sleep(20)"],
        {"PATH": os.defpath},
    )
    assert reason == "output_limit" and len(captured) <= 8


def test_dead_leader_still_stops_descendant_group(launcher: ModuleType) -> None:
    child_program = "import os,time; pid=os.fork(); time.sleep(30) if pid == 0 else os._exit(0)"
    with subprocess.Popen(
        [sys.executable, "-I", "-c", child_program],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    ) as process:
        try:
            process.wait(timeout=10)
            assert process.poll() == 0
            os.killpg(process.pid, 0)
            launcher.stop_child(process)
            with pytest.raises(ProcessLookupError):
                os.killpg(process.pid, 0)
        finally:
            with suppress(ProcessLookupError, PermissionError):
                os.killpg(process.pid, signal.SIGKILL)


def test_permission_error_does_not_prove_process_group_absence(
    launcher: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticks = iter(range(100))
    monkeypatch.setattr(launcher.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(launcher.time, "sleep", lambda _: None)

    def denied(pid: int, signum: int) -> None:
        raise PermissionError

    monkeypatch.setattr(launcher.os, "killpg", denied)
    process = SimpleNamespace(pid=12345, poll=lambda: 0)
    with pytest.raises(RuntimeError, match="not proven stopped"):
        launcher.stop_child(process)


@pytest.mark.parametrize(
    "exit_code,assertions,complete", [(1, True, True), (0, False, True), (0, True, False)]
)
def test_no_false_pass(
    launcher: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    exit_code: int,
    assertions: bool,
    complete: bool,
) -> None:
    output = tmp_path / "attempt"
    monkeypatch.setenv("FLEET_OPENAI_TEST_KEY", SENTINEL)
    monkeypatch.setattr(sys, "argv", ["probe", "--run", "--output", str(output)])

    def captured(command: list[str], environment: dict[str, str]) -> tuple[int, bytes, str]:
        assert SENTINEL not in " ".join(command)
        assert environment["AGENT_FLEET_LIVE_PROVIDER_MODEL"] == "openai:gpt-5-nano"
        (output / "canary-evidence.json").write_text(json.dumps({"assertions_passed": assertions}))
        (output / "cleanup.json").write_text(json.dumps({"complete": complete}))
        return exit_code, b"safe test output", "normal"

    monkeypatch.setattr(launcher, "capture_test", captured)
    assert launcher.main() == 1
    assert json.loads((output / "summary.json").read_text())["outcome"] == "NOT_PASSED"


def test_pass_and_repeat_guard(
    launcher: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "attempt"
    monkeypatch.setenv("FLEET_OPENAI_TEST_KEY", SENTINEL)
    monkeypatch.setattr(sys, "argv", ["probe", "--run", "--output", str(output)])
    calls = []

    def captured(command: list[str], environment: dict[str, str]) -> tuple[int, bytes, str]:
        calls.append(1)
        (output / "canary-evidence.json").write_text('{"assertions_passed":true}')
        (output / "cleanup.json").write_text('{"complete":true}')
        return 0, b"safe", "normal"

    monkeypatch.setattr(launcher, "capture_test", captured)
    assert launcher.main() == 0
    assert launcher.main() == 2
    assert len(calls) == 1
    assert output.stat().st_mode & 0o777 == 0o700


@pytest.mark.parametrize(
    "cleanup_bytes", [b"invalid json", SENTINEL.encode(), b'{"complete":false}']
)
def test_invalid_or_incomplete_cleanup_never_infers_safe_recovery(
    launcher: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cleanup_bytes: bytes,
) -> None:
    output = tmp_path / "attempt"
    state_root = output / "fixtures" / "test_canary0" / "live-provider-state"
    monkeypatch.setenv("FLEET_OPENAI_TEST_KEY", SENTINEL)
    monkeypatch.setattr(sys, "argv", ["probe", "--run", "--output", str(output)])

    def captured(command: list[str], environment: dict[str, str]) -> tuple[int, bytes, str]:
        state_root.mkdir(parents=True)
        (output / "cleanup.json").write_bytes(cleanup_bytes)
        return 1, b"safe", "normal"

    def recover(path: Path, *, owner_stopped: bool) -> dict[str, object]:
        pytest.fail("launcher must not infer safe recovery")

    monkeypatch.setattr(launcher, "capture_test", captured)
    monkeypatch.setattr(live_provider_support, "cleanup_disposable_state", recover)
    assert launcher.main() == 1
    summary = json.loads((output / "summary.json").read_text())
    assert "RECOVERY_WITHHELD" in summary["diagnostic_errors"]
    assert summary["recovery_withheld"] is True
    assert not (output / "launcher-recovery.json").exists()
    assert SENTINEL not in (output / "summary.json").read_text()


def test_missing_key_does_not_create_attempt(
    launcher: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "attempt"
    monkeypatch.delenv("FLEET_OPENAI_TEST_KEY", raising=False)
    monkeypatch.setattr(sys, "argv", ["probe", "--run", "--output", str(output)])
    assert launcher.main() == 2
    assert not output.exists()


@pytest.mark.parametrize(
    "returncode,reason",
    [
        (0, "normal"),
        (-15, "normal"),
        (0, "wall_timeout"),
        (0, "output_limit"),
        (0, "operator_interrupt"),
        (0, "capture_error"),
    ],
)
def test_unproven_owner_never_runs_recovery(
    launcher: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    returncode: int,
    reason: str,
) -> None:
    output = tmp_path / "attempt"
    monkeypatch.setenv("FLEET_OPENAI_TEST_KEY", SENTINEL)
    monkeypatch.setattr(sys, "argv", ["probe", "--run", "--output", str(output)])

    def captured(command: list[str], environment: dict[str, str]) -> tuple[int, bytes, str]:
        (output / "fixtures" / "test_canary0" / "live-provider-state").mkdir(parents=True)
        return returncode, b"safe", reason

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("recovery requires a normally exited owner")

    monkeypatch.setattr(launcher, "capture_test", captured)
    monkeypatch.setattr(live_provider_support, "cleanup_disposable_state", forbidden)
    assert launcher.main() == 1
    summary = json.loads((output / "summary.json").read_text())
    assert summary["outcome"] == "NOT_PASSED"
    assert summary["cleanup_complete"] is False
    expected = (
        "RECOVERY_WITHHELD"
        if returncode == 0 and reason == "normal"
        else "OWNER_QUIESCENCE_UNPROVEN"
    )
    assert summary["diagnostic_errors"] == [expected]
    assert not (output / "launcher-recovery.json").exists()


def test_secret_in_output_path_is_not_echoed_or_created(
    launcher: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / SENTINEL
    monkeypatch.setenv("FLEET_OPENAI_TEST_KEY", SENTINEL)
    monkeypatch.setattr(sys, "argv", ["probe", "--run", "--output", str(output)])
    assert launcher.main() == 2
    assert not output.exists()
    captured = capsys.readouterr()
    assert SENTINEL not in captured.out + captured.err
