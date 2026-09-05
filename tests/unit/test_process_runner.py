from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from agent_fleet.adapters.sandbox.process import BoundedProcessRunner


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
