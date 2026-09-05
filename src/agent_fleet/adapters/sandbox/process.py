"""Bounded direct-argv subprocess runner used by sandbox adapters."""

from __future__ import annotations

import asyncio
import os
import signal
import sys
from dataclasses import dataclass
from typing import Protocol

_PIPE_DRAIN_TIMEOUT_SECONDS = 1
_PROCESS_TERMINATION_TIMEOUT_SECONDS = 5
_PROCESS_GROUP_POLL_SECONDS = 0.01


class ProcessInvocationError(RuntimeError):
    """A trusted subprocess could not be created."""


class ProcessTerminationError(RuntimeError):
    """A Fleet-started subprocess could not be proven fully terminated."""


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
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=environment,
                cwd=cwd,
                start_new_session=os.name == "posix",
            )
        except (OSError, RuntimeError) as error:
            raise ProcessInvocationError("trusted subprocess could not be invoked") from error
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
        termination_task: asyncio.Task[None] | None = None
        timed_out = False
        output_truncated = False

        def ensure_termination() -> asyncio.Task[None]:
            nonlocal termination_task
            if termination_task is None:
                termination_task = asyncio.create_task(_terminate_process_tree(process, wait_task))
            return termination_task

        async def finish_termination() -> None:
            cancellation = await _await_task_completion(ensure_termination())
            if cancellation is not None:
                raise cancellation

        try:
            done, _ = await asyncio.wait(
                {wait_task, overflow_task},
                timeout=timeout_seconds,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:
                timed_out = True
                await finish_termination()
            elif overflow_task in done and overflow.is_set():
                output_truncated = True
                await finish_termination()
            else:
                await _wait_for_process(process, wait_task)
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
                await finish_termination()
                for reader in readers:
                    reader.cancel()
                await asyncio.gather(*readers, return_exceptions=True)
            output_truncated = output_truncated or overflow.is_set()
        except asyncio.CancelledError as cancellation_error:
            # Reuse the one waiter created above. Starting a second Process.wait()
            # here creates a cancellation race on short-lived control processes.
            cleanup_task = ensure_termination()
            await _await_task_completion(cleanup_task)
            raise cancellation_error
        finally:
            active_error = sys.exception()
            finalization_task = asyncio.create_task(
                _finalize_auxiliary_tasks(wait_task, overflow_task, readers)
            )
            finalization_cancellation = await _await_task_completion(finalization_task)
            if finalization_cancellation is not None and active_error is None:
                raise finalization_cancellation

        return ProcessResult(
            returncode=process.returncode if process.returncode is not None else 125,
            stdout=bytes(buffers["stdout"]),
            stderr=bytes(buffers["stderr"]),
            timed_out=timed_out,
            output_truncated=output_truncated,
        )


async def _await_task_completion(
    task: asyncio.Task[None],
) -> asyncio.CancelledError | None:
    """Retain one cleanup task and report caller cancellation after its result."""

    cancellation: asyncio.CancelledError | None = None
    while not task.done():
        try:
            # asyncio.wait does not forward cancellation into its input task and
            # avoids creating a shield future that can race an inner exception.
            await asyncio.wait({task})
        except asyncio.CancelledError as error:
            if cancellation is None:
                cancellation = error
    task.result()
    return cancellation


async def _finalize_auxiliary_tasks(
    wait_task: asyncio.Task[int],
    overflow_task: asyncio.Task[bool],
    readers: list[asyncio.Task[None]],
) -> None:
    wait_task.cancel()
    overflow_task.cancel()
    for reader in readers:
        if not reader.done():
            reader.cancel()
    await asyncio.gather(wait_task, overflow_task, *readers, return_exceptions=True)


async def _terminate_process_tree(
    process: asyncio.subprocess.Process,
    wait_task: asyncio.Task[int],
) -> None:
    signal_error: OSError | None = None
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except PermissionError as error:
            # A very short-lived child can be reaped by the asyncio watcher just
            # before its transport publishes returncode. Darwin can report EPERM
            # for killpg in that window. Do not treat EPERM as success: reap the
            # exact child below and then prove that its private process group is
            # absent. A live or unverifiable group remains a cleanup failure.
            signal_error = error
        except OSError as error:
            signal_error = error
    elif process.returncode is None:
        try:
            process.kill()
        except ProcessLookupError:
            pass
        except OSError as error:
            signal_error = error

    try:
        await _wait_for_process(process, wait_task)
        if os.name == "posix":
            await _wait_for_process_group_exit(process.pid)
    except ProcessTerminationError as error:
        if signal_error is not None:
            raise ProcessTerminationError(
                "bounded subprocess termination could not be verified after signal failure"
            ) from signal_error
        raise error
    if signal_error is not None and (
        os.name != "posix" or not isinstance(signal_error, PermissionError)
    ):
        raise ProcessTerminationError(
            "bounded subprocess termination encountered an unexpected signal failure"
        ) from signal_error


async def _wait_for_process(
    process: asyncio.subprocess.Process,
    wait_task: asyncio.Task[int],
) -> None:
    try:
        await asyncio.wait_for(
            asyncio.shield(wait_task),
            timeout=_PROCESS_TERMINATION_TIMEOUT_SECONDS,
        )
    except TimeoutError as error:
        raise ProcessTerminationError(
            "bounded subprocess did not terminate after forced cleanup"
        ) from error
    if process.returncode is None:
        raise ProcessTerminationError(
            "bounded subprocess waiter completed without a terminal return code"
        )


async def _wait_for_process_group_exit(process_group_id: int) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + _PROCESS_TERMINATION_TIMEOUT_SECONDS
    while _process_group_exists(process_group_id):
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise ProcessTerminationError(
                "bounded subprocess process group remained after forced cleanup"
            )
        await asyncio.sleep(min(_PROCESS_GROUP_POLL_SECONDS, remaining))


def _process_group_exists(process_group_id: int) -> bool:
    try:
        os.killpg(process_group_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Permission denial proves neither ownership nor absence. Fail closed by
        # treating the group as present until the bounded verification expires.
        return True
    except OSError as error:
        raise ProcessTerminationError(
            "bounded subprocess process-group absence probe failed"
        ) from error
    return True
