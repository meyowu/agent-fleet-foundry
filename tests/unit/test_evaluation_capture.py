"""Descriptor and real child lifecycle negatives for the read-only observer."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import threading
from contextlib import ExitStack
from pathlib import Path

import pytest

from agent_fleet.adapters.artifacts.local import LocalArtifactStore
from agent_fleet.adapters.persistence import evaluation_capture as capture
from agent_fleet.adapters.persistence.evaluation_evidence import SqliteEvaluationEvidence
from agent_fleet.adapters.persistence.sqlite import SqliteStateStore
from agent_fleet.adapters.system import SystemClock, UuidIdGenerator
from agent_fleet.domain.security import Redactor

CAMPAIGN = "campaign_" + "a" * 32
ATTEMPT = "attempt_" + "b" * 32


def adapter(tmp_path: Path) -> SqliteEvaluationEvidence:
    state = SqliteStateStore(tmp_path / "state.db", SystemClock(), UuidIdGenerator(), Redactor())
    return SqliteEvaluationEvidence(state, LocalArtifactStore(tmp_path / "artifacts"), tmp_path)


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "fifo", "directory", "oversized"])
def test_source_descriptor_rejects_unsafe_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    path = tmp_path / "source"
    target = tmp_path / "target"
    target.write_bytes(b"original")
    if kind == "symlink":
        path.symlink_to(target)
    elif kind == "hardlink":
        os.link(target, path)
    elif kind == "fifo":
        os.mkfifo(path)
    elif kind == "directory":
        path.mkdir()
    else:
        path.write_bytes(b"12345")
        monkeypatch.setattr(capture, "MAX_FILE", 4)
    with ExitStack() as exits, pytest.raises((capture.CaptureRejected, OSError)):
        capture.DescriptorCapture(exits).first(path)


@pytest.mark.parametrize("change", ["bytes", "file-aba", "directory-aba", "new-optional"])
def test_two_pass_capture_rejects_mutation_and_restored_namespace(
    tmp_path: Path, change: str
) -> None:
    parent = tmp_path / "source"
    parent.mkdir()
    path = parent / "file"
    path.write_bytes(b"original")
    with ExitStack() as exits:
        selected = capture.DescriptorCapture(exits)
        assert selected.first(path) == b"original"
        assert selected.first(parent / "optional", required=False) is None
        if change == "bytes":
            path.write_bytes(b"mutated!")
        elif change == "file-aba":
            retained = parent / "retained"
            path.rename(retained)
            path.symlink_to(tmp_path)
            path.unlink()
            retained.rename(path)
        elif change == "directory-aba":
            retained = tmp_path / "retained"
            parent.rename(retained)
            parent.symlink_to(tmp_path)
            parent.unlink()
            retained.rename(parent)
        else:
            (parent / "optional").write_bytes(b"")
        with pytest.raises(capture.CaptureRejected):
            selected.second()


def test_aggregate_byte_budget_counts_both_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "source"
    path.write_bytes(b"12345")
    monkeypatch.setattr(capture, "MAX_READ", 9)
    with ExitStack() as exits:
        selected = capture.DescriptorCapture(exits)
        assert selected.first(path) == b"12345"
        with pytest.raises(capture.CaptureRejected):
            selected.second()


def test_source_origin_and_restart_capture_ignore_private_stage_identity(tmp_path: Path) -> None:
    path = tmp_path / "source"
    path.write_bytes(b"original")
    origins = []
    for _ in range(2):
        with ExitStack() as exits:
            selected = capture.DescriptorCapture(exits)
            assert selected.first(path) == b"original"
            selected.second()
            origins.append(selected.origin(path))
    assert origins == [(path.stat().st_dev, path.stat().st_ino)] * 2


def fake_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str
) -> list[tuple[subprocess.Popen[bytes], Path]]:
    helper = tmp_path / "fixed-test-child.py"
    helper.write_text("import os, sys, time\nsys.stdin.buffer.read()\n" + body)
    children: list[tuple[subprocess.Popen[bytes], Path]] = []

    def spawn(stage: Path) -> subprocess.Popen[bytes]:
        child = subprocess.Popen(
            [sys.executable, "-I", "-B", str(helper)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=stage,
            env={"LANG": "C", "LC_ALL": "C"},
            close_fds=True,
        )
        children.append((child, stage))
        return child

    monkeypatch.setattr(capture, "_spawn_capture", spawn)
    return children


def assert_drained(children: list[tuple[subprocess.Popen[bytes], Path]]) -> None:
    assert len(children) == 1
    child, stage = children[0]
    assert child.poll() is not None and not stage.exists()
    with pytest.raises(ProcessLookupError):
        os.kill(child.pid, 0)


@pytest.mark.parametrize(
    "body",
    [
        "sys.stdout.buffer.write(b'x' * 2000000); sys.stdout.flush(); time.sleep(30)\n",
        "sys.stderr.buffer.write(b'x' * 20000); sys.stderr.flush(); time.sleep(30)\n",
        "sys.stderr.write('SYNTHETIC_PRIVATE_ERROR'); sys.stderr.flush()\n",
        "sys.stdout.write('{malformed'); sys.exit(0)\n",
        "sys.exit(4)\n",
        "sys.stdout.write('"
        + '{"campaign_id":"'
        + CAMPAIGN
        + '","attempt_id":"'
        + ATTEMPT
        + '","state":"active","state":"reserved"}'
        + "')\n",
    ],
)
def test_stream_overflow_and_unexpected_output_are_corrupt_and_reaped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str
) -> None:
    children = fake_child(tmp_path, monkeypatch, body)
    observed = adapter(tmp_path).inspect_attempt(CAMPAIGN, ATTEMPT)
    assert observed.state == "corrupt"
    assert "SYNTHETIC_PRIVATE_ERROR" not in observed.model_dump_json()
    assert_drained(children)


def test_child_timeout_is_bounded_and_reaped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    children = fake_child(tmp_path, monkeypatch, "time.sleep(30)\n")
    monkeypatch.setattr(capture, "CHILD_TIMEOUT", 0.2)
    assert adapter(tmp_path).inspect_attempt(CAMPAIGN, ATTEMPT).state == "corrupt"
    assert_drained(children)


@pytest.mark.parametrize("boundary", ["kill", "wait", "stage"])
def test_cleanup_uncertainty_never_returns_an_accepted_observation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, boundary: str
) -> None:
    payload = '{"campaign_id":"' + CAMPAIGN + '","attempt_id":"' + ATTEMPT + '","state":"reserved"}'
    body = "time.sleep(30)\n" if boundary == "kill" else f"sys.stdout.write({payload!r})\n"
    children = fake_child(tmp_path, monkeypatch, body)
    original_spawn = capture._spawn_capture
    original_remove = capture._remove_stage
    originals = []
    faults = []

    def spawn(stage: Path) -> subprocess.Popen[bytes]:
        child = original_spawn(stage)
        kill, wait = child.kill, child.wait
        originals.append((kill, wait))

        def uncertain_kill() -> None:
            faults.append("kill")
            raise OSError("SYNTHETIC_PRIVATE_CLEANUP_ERROR")

        def uncertain_wait(timeout: float | None = None) -> int:
            faults.append("wait")
            if boundary == "wait":
                wait(timeout)
            raise subprocess.TimeoutExpired("fixed child", 0.01)

        if boundary == "kill":
            monkeypatch.setattr(child, "kill", uncertain_kill)
        if boundary in {"kill", "wait"}:
            monkeypatch.setattr(child, "wait", uncertain_wait)
        return child

    def uncertain_stage(stage: Path) -> None:
        faults.append("stage")
        raise OSError("SYNTHETIC_PRIVATE_CLEANUP_ERROR")

    monkeypatch.setattr(capture, "_spawn_capture", spawn)
    if boundary == "kill":
        monkeypatch.setattr(capture, "CHILD_TIMEOUT", 0.2)
    if boundary == "stage":
        monkeypatch.setattr(capture, "_remove_stage", uncertain_stage)
    try:
        result = adapter(tmp_path).inspect_attempt(CAMPAIGN, ATTEMPT)
        assert result.state == "corrupt" and faults
        assert "SYNTHETIC_PRIVATE_CLEANUP_ERROR" not in result.model_dump_json()
        assert len(children) == 1
        child, stage = children[0]
        assert all(
            stream is None or stream.closed for stream in (child.stdin, child.stdout, child.stderr)
        )
        if boundary == "stage":
            assert stage.exists()  # Explicit uncertainty, not product drainage.
        else:
            assert not stage.exists()
    finally:
        # These fault-injected residuals are test-owned; never report their manual
        # removal as proof that an uncertain product cleanup had succeeded.
        if children:
            child, stage = children[0]
            kill, wait = originals[0]
            if child.poll() is None:
                kill()
            wait(5)
            if stage.exists():
                original_remove(stage)
    assert_drained(children)


@pytest.mark.asyncio
async def test_repeat_cancellation_drains_actual_child_and_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    children = fake_child(tmp_path, monkeypatch, "time.sleep(30)\n")
    entered = threading.Event()
    release = threading.Event()
    started = threading.Event()
    original_spawn = capture._spawn_capture

    def spawn(stage: Path) -> subprocess.Popen[bytes]:
        child = original_spawn(stage)
        original_wait = child.wait

        def delayed_wait(timeout: float | None = None) -> int:
            entered.set()
            assert release.wait(5)
            return original_wait(timeout)

        monkeypatch.setattr(child, "wait", delayed_wait)
        started.set()
        return child

    monkeypatch.setattr(capture, "_spawn_capture", spawn)
    task = asyncio.create_task(adapter(tmp_path).inspect_attempt_async(CAMPAIGN, ATTEMPT))
    assert await asyncio.to_thread(started.wait, 3)
    try:
        task.cancel()
        assert await asyncio.to_thread(entered.wait, 3)
        for _ in range(3):
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert_drained(children)


@pytest.mark.parametrize("when", ["before", "during"])
def test_registered_secrets_never_cross_capture_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, when: str
) -> None:
    observed = adapter(tmp_path)
    launched = []

    def operation(*args: object, **kwargs: object) -> bytes:
        launched.append(True)
        observed.state.redactor.register_secret("SYNTHETIC_REGISTERED")
        return (
            '{"campaign_id":"' + CAMPAIGN + '","attempt_id":"' + ATTEMPT + '","state":"reserved"}'
        ).encode()

    if when == "before":
        observed.state.redactor.register_secret("SYNTHETIC_REGISTERED")
    monkeypatch.setattr(
        "agent_fleet.adapters.persistence.evaluation_evidence.capture_observation", operation
    )
    result = observed.inspect_attempt(CAMPAIGN, ATTEMPT)
    assert result.state == "corrupt" and "SYNTHETIC_REGISTERED" not in result.model_dump_json()
    assert bool(launched) == (when == "during")
