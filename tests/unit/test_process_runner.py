from __future__ import annotations

import asyncio
import errno
import os
import signal
import sys
from pathlib import Path
from typing import cast

import pytest

from agent_fleet.adapters.sandbox import process as process_module
from agent_fleet.adapters.sandbox.process import (
    BoundedProcessRunner,
    ProcessInvocationError,
    ProcessTerminationError,
)


@pytest.mark.asyncio
async def test_process_runner_passes_shell_metacharacters_as_literal_argv(
    tmp_path: Path,
) -> None:
    runner = BoundedProcessRunner()

    result = await runner.run(
        (
            sys.executable,
            "-c",
            "import sys; print(sys.argv[1])",
            "literal; touch should-not-exist",
        ),
        environment={"PATH": os.environ.get("PATH", "")},
        cwd=str(tmp_path),
        timeout_seconds=5,
        max_output_bytes=4096,
    )

    assert result.returncode == 0
    assert result.stdout == b"literal; touch should-not-exist\n"
    assert not (tmp_path / "should-not-exist").exists()


@pytest.mark.asyncio
async def test_process_runner_bounds_combined_output_and_kills_group() -> None:
    runner = BoundedProcessRunner()

    result = await runner.run(
        (
            sys.executable,
            "-c",
            "import os; os.write(1, b'a' * 4096); os.write(2, b'b' * 4096)",
        ),
        environment={},
        timeout_seconds=5,
        max_output_bytes=1024,
    )

    assert result.output_truncated is True
    assert len(result.stdout) + len(result.stderr) <= 1024


@pytest.mark.asyncio
async def test_process_runner_drains_discarded_output_beyond_pipe_capacity() -> None:
    runner = BoundedProcessRunner()

    result = await runner.run(
        (
            sys.executable,
            "-c",
            "import os; os.write(1, b'x' * 2_000_000)",
        ),
        environment={},
        timeout_seconds=5,
        max_output_bytes=1024,
    )

    assert result.output_truncated is True
    assert len(result.stdout) == 1024
    assert result.stderr == b""


@pytest.mark.asyncio
async def test_process_runner_does_not_wait_forever_for_descendant_owned_pipes() -> None:
    runner = BoundedProcessRunner()

    result = await runner.run(
        (
            sys.executable,
            "-c",
            (
                "import subprocess, sys; "
                "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); "
                "print('parent-exited', flush=True)"
            ),
        ),
        environment={"PATH": os.environ.get("PATH", "")},
        timeout_seconds=1,
        max_output_bytes=4096,
    )

    assert result.returncode == 0
    assert result.stdout == b"parent-exited\n"
    assert result.timed_out is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("script", "timeout_seconds", "max_output_bytes"),
    [
        pytest.param("import time; time.sleep(30)", 0, 4096, id="timeout"),
        pytest.param(
            "import os, time; os.write(1, b'x' * 65536); time.sleep(30)",
            5,
            128,
            id="output-overflow",
        ),
    ],
)
@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group behavior")
async def test_process_runner_cancellation_reuses_inflight_abnormal_termination(
    script: str,
    timeout_seconds: int,
    max_output_bytes: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = BoundedProcessRunner()
    original_killpg = os.killpg
    original_group_wait = process_module._wait_for_process_group_exit
    group_proof_entered = asyncio.Event()
    group_proof_release = asyncio.Event()
    destructive_signals = 0
    group_waits = 0

    def counted_killpg(process_group_id: int, requested_signal: int) -> None:
        nonlocal destructive_signals
        if requested_signal == signal.SIGKILL:
            destructive_signals += 1
        original_killpg(process_group_id, requested_signal)

    async def blocked_group_wait(process_group_id: int) -> None:
        nonlocal group_waits
        group_waits += 1
        group_proof_entered.set()
        await group_proof_release.wait()
        await original_group_wait(process_group_id)

    monkeypatch.setattr(os, "killpg", counted_killpg)
    monkeypatch.setattr(process_module, "_wait_for_process_group_exit", blocked_group_wait)
    execution = asyncio.create_task(
        runner.run(
            (sys.executable, "-c", script),
            environment={},
            timeout_seconds=timeout_seconds,
            max_output_bytes=max_output_bytes,
        )
    )
    try:
        await asyncio.wait_for(group_proof_entered.wait(), timeout=5)
        execution.cancel()
        await asyncio.sleep(0)
        execution.cancel()
        await asyncio.sleep(0)

        assert not execution.done()
        assert destructive_signals == 1
        assert group_waits == 1
        group_proof_release.set()
        with pytest.raises(asyncio.CancelledError):
            await execution

        assert destructive_signals == 1
        assert group_waits == 1
    finally:
        group_proof_release.set()
        if not execution.done():
            execution.cancel()
            await asyncio.gather(execution, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group behavior")
async def test_process_runner_cancellation_tolerates_proven_killpg_exit_race(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = BoundedProcessRunner()
    marker = tmp_path / "started"
    release = tmp_path / "release"
    original_wait = asyncio.subprocess.Process.wait
    original_killpg = os.killpg
    wait_calls = 0
    destructive_signals = 0

    async def counted_wait(process: asyncio.subprocess.Process) -> int:
        nonlocal wait_calls
        wait_calls += 1
        return await original_wait(process)

    def raced_killpg(process_group_id: int, requested_signal: int) -> None:
        nonlocal destructive_signals
        if requested_signal == signal.SIGKILL:
            destructive_signals += 1
            raise PermissionError(errno.EPERM, "simulated exit race")
        original_killpg(process_group_id, requested_signal)

    monkeypatch.setattr(asyncio.subprocess.Process, "wait", counted_wait)
    monkeypatch.setattr(os, "killpg", raced_killpg)
    execution = asyncio.create_task(
        runner.run(
            (
                sys.executable,
                "-c",
                (
                    "import pathlib, sys, time\n"
                    "pathlib.Path(sys.argv[1]).write_text('started')\n"
                    "release = pathlib.Path(sys.argv[2])\n"
                    "while not release.exists():\n"
                    "    time.sleep(0.005)\n"
                ),
                str(marker),
                str(release),
            ),
            environment={},
            timeout_seconds=5,
            max_output_bytes=4096,
        )
    )
    for _ in range(100):
        if marker.exists():
            break
        await asyncio.sleep(0.005)
    else:
        release.write_text("release")
        execution.cancel()
        await asyncio.gather(execution, return_exceptions=True)
        raise AssertionError("subprocess cancellation fixture did not start")

    execution.cancel()
    for _ in range(100):
        if destructive_signals == 1:
            break
        await asyncio.sleep(0.005)
    else:
        release.write_text("release")
        await asyncio.gather(execution, return_exceptions=True)
        raise AssertionError("cancellation cleanup did not attempt process-group termination")
    execution.cancel()
    await asyncio.sleep(0)
    assert not execution.done()
    release.write_text("release")
    with pytest.raises(asyncio.CancelledError):
        await execution

    assert destructive_signals == 1
    assert wait_calls == 1


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group behavior")
async def test_process_runner_termination_failure_wins_over_repeated_cancellation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = BoundedProcessRunner()
    marker = tmp_path / "started"
    release = tmp_path / "release"
    signal_attempted = asyncio.Event()
    destructive_signals = 0

    def unproven_killpg(_process_group_id: int, requested_signal: int) -> None:
        nonlocal destructive_signals
        if requested_signal == signal.SIGKILL:
            destructive_signals += 1
            signal_attempted.set()
            raise PermissionError(errno.EPERM, "simulated signal race")
        # Keep the absence probe inconclusive until its bounded deadline.
        return None

    monkeypatch.setattr(os, "killpg", unproven_killpg)
    monkeypatch.setattr(process_module, "_PROCESS_TERMINATION_TIMEOUT_SECONDS", 0.03)
    monkeypatch.setattr(process_module, "_PROCESS_GROUP_POLL_SECONDS", 0.001)
    execution = asyncio.create_task(
        runner.run(
            (
                sys.executable,
                "-c",
                (
                    "import pathlib, sys, time\n"
                    "pathlib.Path(sys.argv[1]).write_text('started')\n"
                    "release = pathlib.Path(sys.argv[2])\n"
                    "while not release.exists():\n"
                    "    time.sleep(0.001)\n"
                ),
                str(marker),
                str(release),
            ),
            environment={},
            timeout_seconds=30,
            max_output_bytes=4096,
        )
    )
    try:
        for _ in range(1000):
            if marker.exists():
                break
            await asyncio.sleep(0.001)
        else:
            raise AssertionError("termination-failure fixture did not start")

        execution.cancel()
        await asyncio.wait_for(signal_attempted.wait(), timeout=5)
        release.write_text("release")
        for _ in range(1000):
            if execution.done():
                break
            execution.cancel()
            await asyncio.sleep(0)
        with pytest.raises(ProcessTerminationError):
            await execution
    finally:
        release.write_text("release")
        if not execution.done():
            execution.cancel()
        await asyncio.gather(execution, return_exceptions=True)

    assert destructive_signals == 1


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group behavior")
async def test_process_runner_cancellation_removes_descendant_process_group(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = BoundedProcessRunner()
    identities = tmp_path / "process-identities"
    release_parent = tmp_path / "release-parent"
    original_killpg = os.killpg
    destructive_signals = 0

    def counted_killpg(process_group_id: int, requested_signal: int) -> None:
        nonlocal destructive_signals
        if requested_signal == signal.SIGKILL:
            destructive_signals += 1
        original_killpg(process_group_id, requested_signal)

    monkeypatch.setattr(os, "killpg", counted_killpg)
    execution = asyncio.create_task(
        runner.run(
            (
                sys.executable,
                "-c",
                (
                    "import os, pathlib, subprocess, sys, time\n"
                    "child = subprocess.Popen("
                    "[sys.executable, '-c', 'import time; time.sleep(30)'])\n"
                    "pathlib.Path(sys.argv[1]).write_text("
                    "f'{os.getpid()} {os.getpgrp()} {child.pid}')\n"
                    "release = pathlib.Path(sys.argv[2])\n"
                    "while not release.exists():\n"
                    "    time.sleep(0.005)\n"
                ),
                str(identities),
                str(release_parent),
            ),
            environment={"PATH": os.environ.get("PATH", "")},
            timeout_seconds=30,
            max_output_bytes=4096,
        )
    )
    for _ in range(100):
        if identities.exists():
            break
        await asyncio.sleep(0.01)
    else:
        execution.cancel()
        raise AssertionError("descendant cancellation fixture did not start")
    parent_pid, process_group_id, child_pid = map(int, identities.read_text().split())
    assert parent_pid == process_group_id

    # Let the group leader exit while its same-group descendant retains the
    # capture pipes. The runner remains live in pipe draining, so cancellation
    # must signal the group before bounded reap/probe rather than merely waiting.
    release_parent.write_text("release")
    for _ in range(400):
        try:
            os.kill(parent_pid, 0)
        except ProcessLookupError:
            break
        await asyncio.sleep(0.005)
    else:
        execution.cancel()
        await asyncio.gather(execution, return_exceptions=True)
        raise AssertionError("process-group leader did not exit before cancellation")
    with pytest.raises(ProcessLookupError):
        os.kill(parent_pid, 0)
    assert os.getpgid(child_pid) == process_group_id
    os.kill(child_pid, 0)
    assert not execution.done()

    execution.cancel()
    with pytest.raises(asyncio.CancelledError):
        await execution

    with pytest.raises(ProcessLookupError):
        os.kill(parent_pid, 0)
    with pytest.raises(ProcessLookupError):
        os.kill(child_pid, 0)
    with pytest.raises(ProcessLookupError):
        os.killpg(process_group_id, 0)
    assert destructive_signals == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("probe_permission_denied", [False, True])
@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group behavior")
async def test_process_runner_fails_closed_when_group_absence_is_unproven(
    monkeypatch: pytest.MonkeyPatch,
    probe_permission_denied: bool,
) -> None:
    class TerminalProcess:
        pid = 424_242
        returncode = -signal.SIGKILL

    async def terminal_wait() -> int:
        return -signal.SIGKILL

    def inaccessible_group(_process_group_id: int, requested_signal: int) -> None:
        if requested_signal == signal.SIGKILL:
            raise PermissionError(errno.EPERM, "simulated signal denial")
        if probe_permission_denied:
            raise PermissionError(errno.EPERM, "simulated probe denial")
        # A successful signal-zero probe also means the group still exists.

    monkeypatch.setattr(os, "killpg", inaccessible_group)
    monkeypatch.setattr(process_module, "_PROCESS_TERMINATION_TIMEOUT_SECONDS", 0.01)
    wait_task = asyncio.create_task(terminal_wait())

    with pytest.raises(ProcessTerminationError):
        await process_module._terminate_process_tree(
            cast(asyncio.subprocess.Process, TerminalProcess()),
            wait_task,
        )


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group behavior")
async def test_process_runner_fails_closed_when_reap_times_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RunningProcess:
        pid = 424_244
        returncode = None

    never_released = asyncio.Event()

    async def blocked_wait() -> int:
        await never_released.wait()
        return 0

    def denied_signal(_process_group_id: int, _requested_signal: int) -> None:
        raise PermissionError(errno.EPERM, "simulated signal denial")

    monkeypatch.setattr(os, "killpg", denied_signal)
    monkeypatch.setattr(process_module, "_PROCESS_TERMINATION_TIMEOUT_SECONDS", 0.01)
    wait_task = asyncio.create_task(blocked_wait())
    try:
        with pytest.raises(ProcessTerminationError):
            await process_module._terminate_process_tree(
                cast(asyncio.subprocess.Process, RunningProcess()),
                wait_task,
            )
    finally:
        wait_task.cancel()
        await asyncio.gather(wait_task, return_exceptions=True)


@pytest.mark.asyncio
async def test_process_runner_wraps_only_subprocess_creation_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_creation(*_args: object, **_kwargs: object) -> None:
        raise OSError("untrusted platform detail")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fail_creation)

    with pytest.raises(ProcessInvocationError) as captured:
        await BoundedProcessRunner().run(
            (sys.executable, "-c", "raise SystemExit(0)"),
            environment={},
            timeout_seconds=5,
            max_output_bytes=4096,
        )

    assert "untrusted" not in str(captured.value)
