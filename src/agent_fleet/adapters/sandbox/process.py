"""Bounded direct-argv subprocess runner used by sandbox adapters."""

from __future__ import annotations

import asyncio
import os
import signal
from contextlib import suppress
from dataclasses import dataclass
from typing import Protocol

_PIPE_DRAIN_TIMEOUT_SECONDS = 1


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    stdout: bytes
    stderr: bytes
    timed_out: bool = False
    output_truncated: bool = False


class ProcessRunner(Protocol):
    async def run(
        self,
        argv: tuple[str, ...],
        *,
        environment: dict[str, str],
        cwd: str | None = None,
        timeout_seconds: int,
        max_output_bytes: int,
    ) -> ProcessResult: ...


class BoundedProcessRunner:
    """Execute one process without a shell and bound its combined captured output."""

    async def run(
        self,
        argv: tuple[str, ...],
        *,
        environment: dict[str, str],
        cwd: str | None = None,
        timeout_seconds: int,
        max_output_bytes: int,
    ) -> ProcessResult:
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=environment,
            cwd=cwd,
            start_new_session=os.name == "posix",
        )
        assert process.stdout is not None
        assert process.stderr is not None
        buffers = {"stdout": bytearray(), "stderr": bytearray()}
        total = 0
        overflow = asyncio.Event()

        async def consume(name: str, stream: asyncio.StreamReader) -> None:
            nonlocal total
            while True:
                chunk = await stream.read(8192)
                if not chunk:
                    return
                remaining = max_output_bytes - total
                if remaining > 0:
                    kept = chunk[:remaining]
                    buffers[name].extend(kept)
                    total += len(kept)
                if len(chunk) > remaining:
                    overflow.set()
                    # Keep draining without retaining bytes until the process-group
                    # kill closes the pipe. Stopping the reader here can deadlock
                    # Process.wait() behind a full subprocess pipe buffer.

        readers = [
            asyncio.create_task(consume("stdout", process.stdout)),
            asyncio.create_task(consume("stderr", process.stderr)),
        ]
        wait_task = asyncio.create_task(process.wait())
        overflow_task = asyncio.create_task(overflow.wait())
        timed_out = False
        output_truncated = False
        try:
            done, _ = await asyncio.wait(
                {wait_task, overflow_task},
                timeout=timeout_seconds,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:
                timed_out = True
                await _kill_process_tree(process)
            elif overflow_task in done and overflow.is_set():
                output_truncated = True
                await _kill_process_tree(process)
            await _wait_for_process(process)
            try:
                await asyncio.wait_for(
                    asyncio.gather(*readers),
                    timeout=_PIPE_DRAIN_TIMEOUT_SECONDS,
                )
            except TimeoutError:
                # A descendant can inherit the capture pipes after its parent exits.
                # Kill the Fleet-created process group and stop waiting on untrusted FDs.
                output_truncated = True
                timed_out = True
                await _kill_process_tree(process)
                for reader in readers:
                    reader.cancel()
                await asyncio.gather(*readers, return_exceptions=True)
            output_truncated = output_truncated or overflow.is_set()
        except asyncio.CancelledError:
            await asyncio.shield(_kill_process_tree(process))
            await asyncio.shield(_wait_for_process(process))
            raise
        finally:
            wait_task.cancel()
            overflow_task.cancel()
            for reader in readers:
                if not reader.done():
                    reader.cancel()
            await asyncio.gather(wait_task, overflow_task, *readers, return_exceptions=True)

        return ProcessResult(
            returncode=process.returncode if process.returncode is not None else 125,
            stdout=bytes(buffers["stdout"]),
            stderr=bytes(buffers["stderr"]),
            timed_out=timed_out,
            output_truncated=output_truncated,
        )


async def _kill_process_tree(process: asyncio.subprocess.Process) -> None:
    if os.name == "posix":
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
    elif process.returncode is None:
        with suppress(ProcessLookupError):
            process.kill()


async def _wait_for_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    try:
        await asyncio.wait_for(process.wait(), timeout=5)
    except TimeoutError as error:
        raise RuntimeError("bounded subprocess did not terminate after forced cleanup") from error
