"""Launch one bounded real-provider canary from the credential-owning terminal."""

from __future__ import annotations

import argparse
import json
import os
import selectors
import signal
import stat
import subprocess
import sys
import time
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_CAPTURE_BYTES = 2 * 1024 * 1024
WALL_SECONDS = 900
TEST = "tests/live/test_provider_smoke.py::test_live_provider_cli_cos_engineer_verifier_canary"


def read_selection_file(path: Path) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= 16 * 1024:
            raise ValueError("invalid selection file")
        payload = stream.read(16 * 1024 + 1)
    if len(payload) > 16 * 1024:
        raise ValueError("invalid selection file")
    return payload


def child_environment(
    credentials: dict[str, str], selection_json: str, image: str, output: Path
) -> dict[str, str]:
    environment = {
        name: os.environ[name]
        for name in ("PATH", "HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "TMPDIR")
        if name in os.environ
    }
    environment.update(
        {
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "AGENT_FLEET_ENABLE_LIVE_PROVIDER_TESTS": "1",
            "AGENT_FLEET_ENABLE_DOCKER_TESTS": "1",
            "AGENT_FLEET_ENABLE_INSTALL_TESTS": "0",
            "AGENT_FLEET_DOCKER_TEST_IMAGE": image,
            "AGENT_FLEET_LIVE_SELECTION_JSON": selection_json,
            "AGENT_FLEET_LIVE_EVIDENCE_DIR": str(output),
        }
    )
    environment.update(credentials)
    return environment


def stop_child(process: subprocess.Popen[bytes]) -> None:
    """Stop only the new process group owned by this launcher, then reap it."""
    # A dead leader does not imply stopped descendants (e.g. inherited stdout).
    for stop_signal in (signal.SIGTERM, signal.SIGKILL):
        # macOS may briefly return EPERM while an orphan is being reaped. It
        # never counts as proof of absence; only ESRCH permits recovery.
        with suppress(ProcessLookupError, PermissionError):
            os.killpg(process.pid, stop_signal)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            process.poll()
            try:
                os.killpg(process.pid, 0)
            except ProcessLookupError:
                process.wait(timeout=5)
                return
            except PermissionError:
                pass
            time.sleep(0.05)
    raise RuntimeError("child process group not proven stopped; recovery withheld")


def capture_test(command: list[str], environment: dict[str, str]) -> tuple[int, bytes, str]:
    captured = bytearray()
    started = time.monotonic()
    next_notice = started + 30
    stop_reason = "normal"
    with subprocess.Popen(
        command,
        cwd=ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    ) as process:
        assert process.stdout is not None
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            try:
                while selector.get_map():
                    now = time.monotonic()
                    if now - started >= WALL_SECONDS:
                        stop_reason = "wall_timeout"
                        break
                    if now >= next_notice:
                        print(f"Live canary running: {int(now - started)} seconds.", flush=True)
                        next_notice = now + 30
                    for key, _ in selector.select(timeout=0.25):
                        chunk = os.read(key.fd, 65536)
                        if not chunk:
                            selector.unregister(key.fd)
                            break
                        if len(captured) + len(chunk) > MAX_CAPTURE_BYTES:
                            stop_reason = "output_limit"
                            break
                        captured.extend(chunk)
                    if stop_reason != "normal":
                        break
                if stop_reason == "normal":
                    process.wait(timeout=max(1, WALL_SECONDS - (time.monotonic() - started)))
            except KeyboardInterrupt:
                stop_reason = "operator_interrupt"
            except subprocess.TimeoutExpired:
                stop_reason = "wall_timeout"
            except OSError:
                stop_reason = "capture_error"
            finally:
                stop_child(process)
        return process.returncode, bytes(captured), stop_reason


def write_safe(path: Path, payload: bytes, forms: tuple[bytes, ...]) -> None:
    if any(form in payload for form in forms):
        raise ValueError("credential-bearing diagnostic rejected")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as output:
        output.write(payload)


def read_safe(path: Path, forms: tuple[bytes, ...]) -> dict[str, object]:
    if not path.exists():
        return {}
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("invalid evidence file")
    payload = path.read_bytes()
    if any(form in payload for form in forms):
        raise ValueError("credential-bearing evidence rejected")
    value = json.loads(payload)
    if not isinstance(value, dict):
        raise ValueError("invalid evidence object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="Authorize one real API/Docker test")
    parser.add_argument(
        "--output", type=Path, required=True, help="New absolute evidence directory"
    )
    parser.add_argument(
        "--selection",
        type=Path,
        help="Strict schema-version-1 JSON selecting cos, engineer and verifier models",
    )
    parser.add_argument("--image", default="agent-fleet-runner:0.1.0-py314-v1")
    args = parser.parse_args()
    if not args.run:
        parser.error("--run is required; no test started")

    # Load the offline-test helper only after argument parsing, but validate the
    # immutable selection before any credential lookup or output creation.
    sys.path.insert(0, str(ROOT / "tests"))
    from live_provider_support import (
        default_live_canary_selection,
        parse_live_canary_selection,
        resolve_live_canary_credentials,
        selected_credential_forms,
    )

    try:
        if args.selection is None:
            selection = default_live_canary_selection()
        else:
            selection = parse_live_canary_selection(read_selection_file(args.selection))
    except (OSError, ValueError):
        print("SELECTION_INVALID: no credential read, directory, or request created.")
        return 2
    try:
        credentials = resolve_live_canary_credentials(selection, os.environ)
    except ValueError:
        print("CREDENTIALS_NOT_READY: configure only the selected dedicated references.")
        return 2
    forms = selected_credential_forms(credentials)

    output = args.output
    if (
        not output.is_absolute()
        or output.exists()
        or output.is_symlink()
        or not output.parent.is_dir()
        or output.resolve().is_relative_to(ROOT)
    ):
        print(
            "OUTPUT_NOT_NEW: use a new absolute directory outside the repository. No test started."
        )
        return 2

    operator_metadata = json.dumps(
        [str(output), str(ROOT), args.image, selection.safe_projection()], sort_keys=True
    ).encode("utf-8")
    if any(form in operator_metadata for form in forms):
        print("SENSITIVE_LAUNCH_METADATA: no directory or request created.")
        return 2
    output.mkdir(mode=0o700)
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-p",
        "pytest_asyncio.plugin",
        "-q",
        TEST,
        "--tb=short",
        "--show-capture=no",
        "-o",
        "log_cli=false",
        "-o",
        "log_file=",
        f"--basetemp={output / 'fixtures'}",
    ]
    started = time.monotonic()
    manifest = {
        "scope": "real_provider_docker_cli_canary",
        "model": selection.cos.provider_model,
        "selected_roles": selection.safe_projection()["roles"],
        "selection_sha256": selection.sha256,
        "image": args.image,
        "started_at": datetime.now(UTC).isoformat(),
        "whole_test_attempts": 1,
        "wall_seconds": WALL_SECONDS,
        "outcome": "STARTED_OUTCOME_UNKNOWN",
    }
    write_safe(output / "attempt.json", json.dumps(manifest, indent=2).encode(), forms)
    print(f"One bounded live canary. Evidence: {output}", flush=True)
    returncode, captured, stop_reason = capture_test(
        command,
        child_environment(credentials, selection.canonical_json, args.image, output),
    )

    diagnostic_errors: list[str] = []
    try:
        cleanup = read_safe(output / "cleanup.json", forms)
    except (OSError, ValueError):
        cleanup = {}
        diagnostic_errors.append("INVALID_CLEANUP_REPORT")
    owner_quiescence_unproven = stop_reason != "normal" or returncode < 0
    if owner_quiescence_unproven:
        # Trusted Docker/Git subprocesses can own separate sessions. Stopping
        # pytest's process group alone cannot establish that they also stopped.
        diagnostic_errors.append("OWNER_QUIESCENCE_UNPROVEN")
    elif cleanup.get("complete") is not True:
        # Only the synchronous test finalizer has the context to clean safely.
        # Missing/failed finalization requires explicit reconciliation, not a
        # launcher inference that all detached control subprocesses have ended.
        diagnostic_errors.append("RECOVERY_WITHHELD")
    try:
        write_safe(output / "pytest.log", captured, forms)
    except (OSError, ValueError):
        diagnostic_errors.append("CAPTURE_NOT_SAVED")
    try:
        evidence = read_safe(output / "canary-evidence.json", forms)
    except (OSError, ValueError):
        evidence = {}
        diagnostic_errors.append("INVALID_CANARY_REPORT")
    if evidence.get("selection_sha256") != selection.sha256:
        diagnostic_errors.append("SELECTION_EVIDENCE_MISMATCH")
    passed = (
        returncode == 0
        and stop_reason == "normal"
        and evidence.get("assertions_passed") is True
        and cleanup.get("complete") is True
        and not diagnostic_errors
    )
    summary = {
        **manifest,
        "outcome": "PASS" if passed else "NOT_PASSED",
        "pytest_exit_code": returncode,
        "stop_reason": stop_reason,
        "assertions_passed": evidence.get("assertions_passed") is True,
        "cleanup_complete": cleanup.get("complete") is True and not owner_quiescence_unproven,
        "recovery_withheld": owner_quiescence_unproven or cleanup.get("complete") is not True,
        "diagnostic_errors": diagnostic_errors,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "finished_at": datetime.now(UTC).isoformat(),
    }
    write_safe(output / "summary.json", json.dumps(summary, indent=2).encode(), forms)
    print(json.dumps(summary, indent=2))
    print(f"Retained safe evidence: {output}. No automatic retry or patch application.")
    return 0 if passed else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired):
        print(
            "LAUNCHER_ERROR: retained attempt must be inspected before retry; no raw error printed."
        )
        raise SystemExit(2) from None
