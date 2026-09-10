"""Bounded POSIX chat input and thin, deterministic conversation presentation."""

from __future__ import annotations

import asyncio
import json
import os
import shlex
import signal
import stat
import sys
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Protocol, TextIO, cast

import typer
from pydantic import JsonValue
from rich.console import Console
from rich.markup import escape
from typer import _click as click
from typer._click.exceptions import UsageError
from typer.core import TyperCommand

from agent_fleet.application.readiness import ReadinessService
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import ApprovalChoice, FakeScenario, jsonable
from agent_fleet.domain.security import Redactor

if TYPE_CHECKING:
    from agent_fleet.application.conversations import ChatExecutionOptions, SessionBootstrapOptions

type View = dict[str, JsonValue]
_MAX_LINE_BYTES = 16_384
_MAX_QUEUED_LINES = 8
_PROGRESS_INTERVAL = 0.25
_HELP = (
    "/status  /artifacts  /permissions [request-id]  /cancel  /resume\n"
    "/approve [request-id] --once|--run|--always --scope project\n"
    "/approve shows pending scopes; no-ID choices require an exact /confirm code.\n"
    "/deny [request-id] [--reason <text>]  /help  /exit\n"
    "/recover  /recover --confirm-owner-stopped <recovery-code>\n"
    "/plan [approve]  /diff  /apply  /confirm <review-code>  /dismiss\n"
    "/baseline plan <command-id>  /baseline run  /baseline show\n"
    "Baseline confirmation only authorizes once; /baseline run explicitly executes.\n"
    "/models  /models use <alias> --default|--role <role>  /roles  /readiness\n"
    "/tasks [before-sequence]  /tasks select <sequence>  /tasks current\n"
    "History inspection never retargets /cancel or progress. "
    "Model selection affects future tasks only.\n"
    "/fleet-patch list|show|diff|apply|rollback [proposal-id]\n"
    "New goals wait until the current turn settles. Approval never resumes automatically.\n"
    "--review-plan pauses new tasks before execution; /plan labels gate or inspection mode. "
    "Application requires a fresh exact review code; no model message can confirm it."
)


class ConversationClient(Protocol):
    """The selected-project application boundary; no runtime or storage access."""

    def select(
        self, project_path: Path, *, conversation_id: str | None = None, create_new: bool = False
    ) -> View: ...

    def status(self, conversation_id: str) -> View: ...

    def preview_initialization(
        self, project_path: Path, *, options: SessionBootstrapOptions
    ) -> View: ...

    async def initialize(self, *, code: str) -> View: ...

    async def submit(
        self,
        conversation_id: str,
        *,
        message: str,
        submission_id: str | None,
        options: ChatExecutionOptions,
    ) -> View: ...

    async def resume(self, conversation_id: str, *, allow_unsafe_local: bool = False) -> View: ...

    async def cancel(self, conversation_id: str) -> View: ...

    def artifacts(self, conversation_id: str) -> View: ...

    def tasks(
        self,
        conversation_id: str,
        *,
        before_sequence: int | None = None,
        select_sequence: int | None = None,
        current: bool = False,
    ) -> View: ...

    def models(
        self,
        conversation_id: str,
        *,
        profile: str | None = None,
        role: str | None = None,
        default: bool = False,
    ) -> View: ...

    def roles(self, conversation_id: str) -> View: ...

    def readiness(self, conversation_id: str) -> View: ...

    def review(
        self, conversation_id: str, *, action: str, arguments: tuple[str, ...] = ()
    ) -> View: ...

    def permissions(self, conversation_id: str, *, identifier: str | None = None) -> View: ...

    def approve(
        self,
        conversation_id: str,
        request_id: str | None = None,
        *,
        choice: ApprovalChoice | None = None,
    ) -> View: ...

    def deny(
        self, conversation_id: str, request_id: str | None = None, *, reason: str | None = None
    ) -> View: ...

    async def recover(
        self,
        conversation_id: str,
        *,
        code: str | None = None,
        confirm_owner_stopped: bool = False,
    ) -> View: ...

    def progress(
        self, conversation_id: str, *, cursor: str | None = None, limit: int = 50
    ) -> View: ...


class BaselineConversationClient(Protocol):
    async def baseline_plan(
        self,
        conversation_id: str,
        command_id: str,
        *,
        on_admitted: Callable[[], None] | None = None,
    ) -> View: ...
    async def baseline_run(
        self,
        conversation_id: str,
        *,
        on_admitted: Callable[[], None] | None = None,
    ) -> View: ...
    def baseline_show(self, conversation_id: str) -> View: ...
    async def baseline_cancel(self, conversation_id: str) -> View: ...


@dataclass
class _BaselineEntry:
    """Per-attempt UI routing only; this cannot authorize command execution."""

    previous_focus: bool
    previous_progress: bool
    admitted: bool = False

    def accept(self) -> None:
        self.admitted = True


class Presenter(Protocol):
    def __call__(
        self,
        command: str,
        json_output: bool,
        operation: Callable[[], tuple[JsonValue, list[str]]],
        *,
        redactor: Redactor | None = None,
    ) -> None: ...


class ErrorPresenter(Protocol):
    def __call__(
        self, command: str, error: FleetError, json_output: bool, redactor: Redactor
    ) -> None: ...


class LineInput(Protocol):
    async def read_line(self) -> str | None: ...


def _input_error() -> FleetError:
    return FleetError(
        ErrorCode.CONFIG_INVALID,
        "Chat requires bounded UTF-8 lines from a supported POSIX pipe or terminal.",
        "Use lines up to 16 KiB, or submit one goal with --message; no input was replayed.",
    )


def _command_error() -> FleetError:
    return FleetError(
        ErrorCode.CONFIG_INVALID,
        "The chat command or its arguments are invalid.",
        "Use /help or fleet chat --help for the exact supported syntax.",
    )


class PosixLineInput:
    """Read only ready descriptors, with bounded buffering and kernel backpressure.

    No worker thread survives EOF or cancellation. This adapter never closes its
    caller's descriptor and restores its original blocking flag when detached.
    """

    def __init__(self, stream: TextIO) -> None:
        self.stream = stream
        self._fd: int | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._was_blocking = True
        self._owns_fd = False
        self._registered = False
        self._eof = False
        self._buffer = bytearray()
        self._queue: asyncio.Queue[str | FleetError | None] = asyncio.Queue(_MAX_QUEUED_LINES)

    async def __aenter__(self) -> PosixLineInput:
        valid = False
        with suppress(OSError, ValueError, AttributeError, NotImplementedError):
            fd = self.stream.fileno()
            original = os.fstat(fd)
            mode = original.st_mode
            if os.name == "posix" and (stat.S_ISFIFO(mode) or os.isatty(fd)):
                if os.isatty(fd):
                    # stdin/stdout often share one terminal open-file description.
                    # Setting O_NONBLOCK on stdin then also affects stdout, causing
                    # large TextIO writes to lose bytes. Own a separate read-only
                    # description for the exact terminal device instead of dup().
                    self._fd = os.open(os.ttyname(fd), os.O_RDONLY | os.O_NONBLOCK | os.O_NOCTTY)
                    self._owns_fd = True
                    opened = os.fstat(self._fd)
                    if not os.isatty(self._fd) or opened.st_rdev != original.st_rdev:
                        raise OSError("Terminal device changed during input setup.")
                else:
                    self._fd = fd
                    self._was_blocking = os.get_blocking(fd)
                    os.set_blocking(fd, False)
                self._loop = asyncio.get_running_loop()
                self._attach()
                valid = True
        if not valid:
            self.close()
            raise _input_error()
        return self

    async def __aexit__(self, *_: object) -> None:
        self.close()

    def _attach(self) -> None:
        if self._loop is not None and self._fd is not None and not self._registered:
            self._loop.add_reader(self._fd, self._ready)
            self._registered = True

    def _detach(self) -> None:
        if self._registered and self._loop is not None and self._fd is not None:
            self._loop.remove_reader(self._fd)
        self._registered = False

    def close(self) -> None:
        self._detach()
        if self._fd is not None:
            with suppress(OSError):
                if self._owns_fd:
                    os.close(self._fd)
                else:
                    os.set_blocking(self._fd, self._was_blocking)
        self._fd = None
        self._owns_fd = False
        self._buffer.clear()

    def _fail(self) -> None:
        self._detach()
        self._eof = True
        self._buffer.clear()
        while not self._queue.empty():
            self._queue.get_nowait()
        self._queue.put_nowait(_input_error())

    def _ready(self) -> None:
        if self._fd is None:
            return
        chunk: bytes | None = None
        failed = False
        try:
            chunk = os.read(self._fd, 4096)
        except BlockingIOError:
            return
        except OSError:
            failed = True
        if failed:
            self._fail()
            return
        if not chunk:
            self._eof = True
            self._detach()
        else:
            self._buffer.extend(chunk)
        self._pump()

    def _pump(self) -> None:
        while not self._queue.full():
            newline = self._buffer.find(b"\n")
            if newline < 0:
                if len(self._buffer) > _MAX_LINE_BYTES:
                    self._fail()
                    return
                if not self._eof:
                    break
                if not self._buffer:
                    self._queue.put_nowait(None)
                    return
                newline = len(self._buffer)
            if newline > _MAX_LINE_BYTES:
                self._fail()
                return
            raw = bytes(self._buffer[:newline]).removesuffix(b"\r")
            del self._buffer[: newline + 1]
            line: str | None = None
            with suppress(UnicodeError):
                line = raw.decode("utf-8")
            if line is None or "\x00" in line:
                self._fail()
                return
            self._queue.put_nowait(line)
        if self._queue.full():
            self._detach()
        elif not self._eof:
            self._attach()

    async def read_line(self) -> str | None:
        item = await self._queue.get()
        if isinstance(item, FleetError):
            raise item
        if item is not None:
            self._pump()
        return item


def _display_text(value: str, redactor: Redactor) -> str:
    cleaned, _ = redactor.redact_text(value)
    # Rich markup=False is not itself a terminal escape-sequence boundary.
    return "".join(
        char
        if char == "\n" or (ord(char) >= 32 and not 127 <= ord(char) <= 159)
        else f"\\x{ord(char):02x}"
        for char in cleaned
    )


def _readiness_text(view: View, redactor: Redactor) -> str:
    def encoded(data: dict[str, object]) -> str:
        cleaned, _ = redactor.redact_data(data)
        return _display_text(
            json.dumps(cleaned, ensure_ascii=True, sort_keys=True, indent=2), redactor
        )

    # Session pretty-printing has its own wire size; the static report's compact
    # JSON bound alone cannot cover indentation or the emitted trailing newline.
    report = ReadinessService._bounded_report(
        cast(dict[str, object], view),
        wire_size=lambda data: len((encoded(data) + "\n").encode("utf-8")),
    )
    return encoded(report.model_dump(mode="json"))


def _view_text(view: View) -> str:
    lines = [f"Conversation: {view.get('conversation_id')}"]
    if "inspection_mode" in view:
        lines.append(
            f"Inspection: {view.get('inspection_mode')}  inspected={view.get('inspected_run_id')}  "
            f"active={view.get('active_run_id')}"
        )
    if "cancelled_run_id" in view:
        lines.append(f"Cancellation target (active task only): {view.get('cancelled_run_id')}")
    run = view.get("run")
    if isinstance(run, dict):
        lines.append(f"Run: {view.get('run_id')}  {run.get('status')} / {run.get('stage')}")
        lines.append(f"Verified complete: {run.get('verified_complete')}")
        requests = [run.get("pending_approval_id")]
        children = run.get("pending_child_approval_ids")
        if isinstance(children, list):
            requests.extend(children)
        for request in requests:
            if isinstance(request, str):
                lines.append(f"Pending approval: {request}")
        if run.get("patch_artifact_id"):
            lines.append(f"Patch artifact: {run['patch_artifact_id']}")
        if run.get("evidence_bundle_artifact_id"):
            lines.append(f"Evidence: {run['evidence_bundle_artifact_id']}")
    summary = view.get("result_summary")
    if isinstance(summary, str):
        lines.append(summary)
    if view.get("summary_truncated"):
        lines.append("Conversation summary was shortened; the original goal remains on its Run.")
    if view.get("recovery_required"):
        lines.append("Execution ownership is uncertain. Inspect the exact run before recovery.")
    warnings = view.get("warnings")
    if isinstance(warnings, list):
        lines.extend(f"Warning: {warning}" for warning in warnings if isinstance(warning, str))
    return "\n".join(lines)


def _human_value(value: JsonValue, redactor: Redactor) -> JsonValue:
    """The shared table presenter interprets markup; escape chat text before it."""
    if isinstance(value, str):
        return escape(_display_text(value, redactor))
    if isinstance(value, list):
        return [_human_value(item, redactor) for item in value]
    if isinstance(value, dict):
        return {
            escape(_display_text(key, redactor)): _human_value(item, redactor)
            for key, item in value.items()
        }
    return value


async def _await_retained(task: asyncio.Task[View]) -> View:
    while not task.done():
        with suppress(asyncio.CancelledError):
            await asyncio.shield(task)
    return task.result()


async def run_session(
    service: ConversationClient,
    selected: View,
    options: ChatExecutionOptions,
    reader: LineInput,
    *,
    emit: Callable[[str], None],
    show_error: Callable[[FleetError], None],
    redactor: Redactor,
    interrupt: asyncio.Event | None = None,
) -> View:
    """Multiplex input and execution; all lifecycle policy stays in the service."""
    conversation_id = selected.get("conversation_id")
    if not isinstance(conversation_id, str):
        raise _command_error()
    interrupted = interrupt or asyncio.Event()
    line_task = asyncio.create_task(reader.read_line())
    interrupt_task = asyncio.create_task(interrupted.wait())
    execution: asyncio.Task[View] | None = None
    execution_is_baseline = False
    baseline_entry: _BaselineEntry | None = None
    baseline_focus = False
    baseline_result: View = {"kind": "baseline", "conversation_id": conversation_id}
    baseline = cast(BaselineConversationClient, service)
    cursor: str | None = None
    displayed_requests: set[str] = set()
    progress_enabled = True
    last_progress = 0.0

    def display(value: str) -> None:
        emit(_display_text(value, redactor))

    def result(view: View) -> None:
        nonlocal baseline_result, baseline_focus, progress_enabled
        if view.get("kind") == "baseline":
            baseline_focus = True
            progress_enabled = False
            baseline_result = view
            data(view)
        else:
            display(_view_text(view))

    def data(view: View) -> None:
        cleaned, _ = redactor.redact_data(view)
        display(json.dumps(cleaned, ensure_ascii=True, sort_keys=True, indent=2))

    def review_data(view: View) -> None:
        # Keep complete diffs readable rather than JSON-escaped, while applying
        # the same terminal-control escaping and secret redaction to every byte.
        data({key: value for key, value in view.items() if key not in {"patch", "text_diff"}})
        for key in ("patch", "text_diff"):
            value = view.get(key)
            if isinstance(value, str):
                display(value)

    async def stop() -> View:
        nonlocal execution
        is_baseline = execution_is_baseline if execution is not None else baseline_focus
        cleanup = asyncio.create_task(
            baseline.baseline_cancel(conversation_id)
            if is_baseline
            else service.cancel(conversation_id)
        )
        view = await _await_retained(cleanup)
        if execution is not None:
            with suppress(asyncio.CancelledError, FleetError):
                await _await_retained(execution)
            execution = None
        return view

    result(selected)
    display("Type a goal or /help. /exit cancels and awaits locally active work.")
    try:
        while True:
            tasks: set[asyncio.Task[object]] = {line_task, interrupt_task}
            if execution is not None:
                tasks.add(execution)
            done, _ = await asyncio.wait(
                tasks, timeout=_PROGRESS_INTERVAL, return_when=asyncio.FIRST_COMPLETED
            )
            if execution is not None and execution in done:
                try:
                    result(execution.result())
                except (FleetError, asyncio.CancelledError) as error:
                    if execution_is_baseline and baseline_entry is not None:
                        baseline_focus = (
                            True if baseline_entry.admitted else baseline_entry.previous_focus
                        )
                        progress_enabled = (
                            False if baseline_entry.admitted else baseline_entry.previous_progress
                        )
                    if isinstance(error, FleetError):
                        show_error(error)
                execution = None
                baseline_entry = None
            if interrupt_task in done:
                if execution is not None:
                    result(await stop())
                break
            if line_task in done:
                line = line_task.result()
                if line is None:
                    if execution is not None:
                        result(await stop())
                    break
                line_task = asyncio.create_task(reader.read_line())
                if not line.strip():
                    continue
                try:
                    if line.lstrip().startswith("/"):
                        words: list[str] | None = None
                        with suppress(ValueError):
                            words = shlex.split(line)
                        if not words:
                            raise _command_error()
                        command, *arguments = words
                        if command == "/exit" and not arguments:
                            if execution is not None:
                                result(await stop())
                            break
                        if command == "/help" and not arguments:
                            display(_HELP)
                        elif command == "/status" and not arguments:
                            result(service.status(conversation_id))
                        elif command == "/artifacts" and not arguments:
                            data(service.artifacts(conversation_id))
                        elif command == "/roles" and not arguments:
                            data(service.roles(conversation_id))
                        elif command == "/readiness" and not arguments:
                            display(_readiness_text(service.readiness(conversation_id), redactor))
                        elif command == "/baseline":
                            if arguments == ["show"]:
                                shown = baseline.baseline_show(conversation_id)
                                result(shown)
                            elif arguments == ["run"] or (
                                len(arguments) == 2
                                and arguments[0] == "plan"
                                and not arguments[1].startswith("--")
                            ):
                                if execution is not None:
                                    raise _busy_error()
                                baseline_entry = _BaselineEntry(baseline_focus, progress_enabled)
                                progress_enabled = False
                                execution_is_baseline = True
                                execution = asyncio.create_task(
                                    baseline.baseline_run(
                                        conversation_id, on_admitted=baseline_entry.accept
                                    )
                                    if arguments == ["run"]
                                    else baseline.baseline_plan(
                                        conversation_id,
                                        arguments[1],
                                        on_admitted=baseline_entry.accept,
                                    )
                                )
                            else:
                                raise _command_error()
                        elif command == "/models":
                            profile, role, default = _models(arguments)
                            data(
                                service.models(
                                    conversation_id, profile=profile, role=role, default=default
                                )
                            )
                        elif command == "/tasks":
                            before, selected_sequence, current = _tasks(arguments)
                            view = service.tasks(
                                conversation_id,
                                before_sequence=before,
                                select_sequence=selected_sequence,
                                current=current,
                            )
                            if selected_sequence is not None or current:
                                baseline_focus = False
                                cursor = None
                                displayed_requests.clear()
                                progress_enabled = True
                                result(view)
                            else:
                                data(view)
                        elif command in {
                            "/plan",
                            "/diff",
                            "/apply",
                            "/fleet-patch",
                            "/confirm",
                            "/dismiss",
                        }:
                            changes_target = (
                                command in {"/apply", "/confirm"}
                                or (command == "/plan" and bool(arguments))
                                or (
                                    command == "/fleet-patch"
                                    and bool(arguments)
                                    and arguments[0] in {"apply", "rollback"}
                                )
                            )
                            if execution is not None and changes_target:
                                raise _busy_error()
                            reviewed = service.review(
                                conversation_id, action=command[1:], arguments=tuple(arguments)
                            )
                            if reviewed.get("kind") == "baseline":
                                baseline_focus = True
                                progress_enabled = False
                                baseline_result = reviewed
                            review_data(reviewed)
                        elif command == "/permissions" and len(arguments) <= 1:
                            data(
                                service.permissions(
                                    conversation_id, identifier=arguments[0] if arguments else None
                                )
                            )
                        elif command == "/cancel" and not arguments:
                            result(await stop())
                        elif command == "/recover" and (
                            not arguments
                            or (len(arguments) == 2 and arguments[0] == "--confirm-owner-stopped")
                        ):
                            if execution is not None:
                                raise _busy_error()
                            data(
                                await service.recover(
                                    conversation_id,
                                    code=arguments[1] if arguments else None,
                                    confirm_owner_stopped=bool(arguments),
                                )
                            )
                        elif command == "/resume" and not arguments:
                            if execution is not None:
                                raise _busy_error()
                            execution = asyncio.create_task(
                                service.resume(
                                    conversation_id, allow_unsafe_local=options.allow_unsafe_local
                                )
                            )
                            execution_is_baseline = False
                            baseline_focus = False
                            progress_enabled = True
                        elif command == "/approve":
                            request_id, choice = _approval(arguments)
                            data(service.approve(conversation_id, request_id, choice=choice))
                        elif command == "/deny" and (
                            len(arguments) == 0
                            or (len(arguments) == 1 and not arguments[0].startswith("--"))
                            or (len(arguments) == 2 and arguments[0] == "--reason")
                            or (len(arguments) == 3 and arguments[1] == "--reason")
                        ):
                            data(
                                service.deny(
                                    conversation_id,
                                    arguments[0] if len(arguments) in {1, 3} else None,
                                    reason=arguments[-1] if len(arguments) >= 2 else None,
                                )
                            )
                        else:
                            raise _command_error()
                    else:
                        if execution is not None:
                            raise _busy_error()
                        execution = asyncio.create_task(
                            service.submit(
                                conversation_id, message=line, submission_id=None, options=options
                            )
                        )
                        execution_is_baseline = False
                        baseline_focus = False
                        progress_enabled = True
                except FleetError as error:
                    show_error(error)
            now = asyncio.get_running_loop().time()
            if progress_enabled and now - last_progress >= _PROGRESS_INTERVAL:
                last_progress = now
                try:
                    page = service.progress(conversation_id, cursor=cursor, limit=50)
                    next_cursor = page.get("cursor")
                    cursor = next_cursor if isinstance(next_cursor, str) else None
                    events = page.get("events")
                    if isinstance(events, list):
                        for event in events:
                            if isinstance(event, dict) and isinstance(event.get("summary"), str):
                                display(str(event["summary"]))
                                requests = event.get("request_ids")
                                current_requests = (
                                    {item for item in requests if isinstance(item, str)}
                                    if isinstance(requests, list)
                                    else set()
                                )
                                if isinstance(requests, list):
                                    for pending_id in requests:
                                        if (
                                            isinstance(pending_id, str)
                                            and pending_id not in displayed_requests
                                        ):
                                            display(f"Pending approval: {pending_id}")
                                displayed_requests = current_requests
                except FleetError as error:
                    show_error(error)
                    progress_enabled = False
    finally:
        try:
            if execution is not None and not execution.done():
                await stop()
            elif execution is not None:
                with suppress(asyncio.CancelledError, FleetError):
                    execution.result()
        finally:
            line_task.cancel()
            interrupt_task.cancel()
            await asyncio.gather(line_task, interrupt_task, return_exceptions=True)
    return baseline_result if baseline_focus else service.status(conversation_id)


def _models(arguments: list[str]) -> tuple[str | None, str | None, bool]:
    if not arguments:
        return None, None, False
    if len(arguments) == 3 and arguments[0] == "use" and arguments[2] == "--default":
        return arguments[1], None, True
    if len(arguments) == 4 and arguments[0] == "use" and arguments[2] == "--role":
        return arguments[1], arguments[3], False
    raise _command_error()


def _tasks(arguments: list[str]) -> tuple[int | None, int | None, bool]:
    if not arguments:
        return None, None, False
    if arguments == ["current"]:
        return None, None, True
    if len(arguments) == 1 or (len(arguments) == 2 and arguments[0] == "select"):
        raw = arguments[-1]
        if not raw.isascii() or not raw.isdigit() or len(raw) > 4 or not 1 <= int(raw) <= 1000:
            raise _command_error()
        value = int(raw)
        return (value, None, False) if len(arguments) == 1 else (None, value, False)
    raise _command_error()


def _busy_error() -> FleetError:
    return FleetError(
        ErrorCode.RECOVERY_REQUIRED,
        "This conversation already has a local execution in progress.",
        "Use /status or /cancel; a new goal is not queued automatically.",
    )


def _approval(arguments: list[str]) -> tuple[str | None, ApprovalChoice | None]:
    choices = {"--once": ApprovalChoice.ALLOW_ONCE, "--run": ApprovalChoice.ALLOW_RUN}
    if not arguments:
        return None, None
    if len(arguments) == 1 and arguments[0] in choices:
        return None, choices[arguments[0]]
    if arguments == ["--always", "--scope", "project"]:
        return None, ApprovalChoice.ALLOW_ALWAYS
    if len(arguments) == 2 and arguments[1] in choices:
        return arguments[0], choices[arguments[1]]
    if len(arguments) == 4 and arguments[1:] == ["--always", "--scope", "project"]:
        return arguments[0], ApprovalChoice.ALLOW_ALWAYS
    raise FleetError(
        ErrorCode.APPROVAL_INVALID,
        "Choose exactly one of --once, --run, or --always --scope project.",
        "Inspect the exact request with /permissions before approving it.",
    )


async def _terminal_session(
    service: ConversationClient,
    selected: View | None,
    options: ChatExecutionOptions,
    *,
    redactor: Redactor,
    show_error: Callable[[FleetError], None],
    onboarding_path: Path | None = None,
    create_new: bool = False,
) -> View:
    terminal = Console()
    interrupted = asyncio.Event()
    loop = asyncio.get_running_loop()
    previous = signal.getsignal(signal.SIGINT)
    installed = False
    try:
        with suppress(NotImplementedError, RuntimeError, ValueError):
            loop.add_signal_handler(signal.SIGINT, interrupted.set)
            installed = True
        if not installed:
            raise _input_error()
        async with PosixLineInput(sys.stdin) as reader:
            if selected is None:
                from agent_fleet.cli.onboarding import onboard

                if onboarding_path is None:
                    raise _command_error()
                selected = await onboard(
                    service,
                    onboarding_path,
                    options,
                    reader,
                    emit=lambda text: terminal.print(
                        _display_text(text, redactor), markup=False, highlight=False
                    ),
                    create_new=create_new,
                    interrupt=interrupted,
                )
                if selected is None:
                    return {
                        "conversation_opened": False,
                        "notice": (
                            "Setup stopped. If the canary had begun, inspect its local "
                            "setup evidence before retrying; no conversation was opened."
                        ),
                    }
            return await run_session(
                service,
                selected,
                options,
                reader,
                emit=lambda text: terminal.print(text, markup=False, highlight=False),
                show_error=show_error,
                redactor=redactor,
                interrupt=interrupted,
            )
    finally:
        if installed:
            loop.remove_signal_handler(signal.SIGINT)
            signal.signal(signal.SIGINT, previous)


async def _message_session(
    service: ConversationClient,
    conversation_id: str,
    *,
    message: str,
    submission_id: str | None,
    options: ChatExecutionOptions,
) -> View:
    """Keep interrupt cleanup inside the one noninteractive result envelope."""
    loop = asyncio.get_running_loop()
    interrupted = asyncio.Event()
    previous = signal.getsignal(signal.SIGINT)
    installed = False
    with suppress(NotImplementedError, RuntimeError, ValueError):
        loop.add_signal_handler(signal.SIGINT, interrupted.set)
        installed = True
    if not installed:
        raise FleetError(
            ErrorCode.CONFIG_INVALID,
            "Chat cannot install safe interrupt handling in this execution context.",
            "Run the CLI in a supported POSIX process; no conversation execution started.",
        )
    execution = asyncio.create_task(
        service.submit(
            conversation_id, message=message, submission_id=submission_id, options=options
        )
    )
    interrupt_task = asyncio.create_task(interrupted.wait())
    try:
        await asyncio.wait({execution, interrupt_task}, return_when=asyncio.FIRST_COMPLETED)
        if execution.done():
            return execution.result()
        cleanup = asyncio.create_task(service.cancel(conversation_id))
        result = await _await_retained(cleanup)
        with suppress(asyncio.CancelledError, FleetError):
            await _await_retained(execution)
        return result
    finally:
        try:
            if not execution.done():
                await _await_retained(asyncio.create_task(service.cancel(conversation_id)))
                with suppress(asyncio.CancelledError, FleetError):
                    await _await_retained(execution)
        finally:
            interrupt_task.cancel()
            await asyncio.gather(interrupt_task, return_exceptions=True)
            loop.remove_signal_handler(signal.SIGINT)
            signal.signal(signal.SIGINT, previous)


def register_chat_command(
    app: typer.Typer,
    *,
    service_factory: Callable[[Redactor], ConversationClient],
    redactor_factory: Callable[[], Redactor],
    presenter: Presenter,
    error_presenter: ErrorPresenter,
) -> Callable[[], None]:
    """Wire one command without importing the parent CLI or creating a container."""

    class SafeChatCommand(TyperCommand):
        def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
            json_requested = "--json" in args
            parsed: list[str] | None = None
            with suppress(UsageError):
                parsed = super().parse_args(ctx, args)
            if parsed is None:
                error_presenter("fleet chat", _command_error(), json_requested, redactor_factory())
                raise typer.Exit(code=2)
            return parsed

    @app.command("chat", cls=SafeChatCommand)
    def chat(
        path: Annotated[Path, typer.Argument(help="Registered project repository.")] = Path("."),
        conversation: Annotated[str | None, typer.Option("--conversation")] = None,
        create_new: Annotated[bool, typer.Option("--new")] = False,
        message: Annotated[str | None, typer.Option("--message")] = None,
        submission_id: Annotated[str | None, typer.Option("--submission-id")] = None,
        json_output: Annotated[bool, typer.Option("--json")] = False,
        runtime: Annotated[str | None, typer.Option("--runtime")] = None,
        sandbox: Annotated[str | None, typer.Option("--sandbox")] = None,
        provider_model: Annotated[str | None, typer.Option("--provider-model")] = None,
        credential_ref: Annotated[str | None, typer.Option("--credential-ref")] = None,
        fake_scenario: Annotated[str | None, typer.Option("--fake-scenario")] = None,
        allow_unsafe_local: Annotated[bool, typer.Option("--allow-unsafe-local")] = False,
        review_plan: Annotated[
            bool, typer.Option("--review-plan", help="Pause new tasks for exact plan approval.")
        ] = False,
    ) -> None:
        """Reopen a bounded conversation; approval and patch application stay explicit."""
        redactor = redactor_factory()

        def operation() -> tuple[JsonValue, list[str]]:
            from agent_fleet.application.conversations import ChatExecutionOptions

            if (create_new and conversation is not None) or (
                message is None and (json_output or submission_id is not None)
            ):
                raise _command_error()
            if message is not None and (not message.strip() or message.lstrip().startswith("/")):
                raise _command_error()
            scenario: FakeScenario | None = None
            if fake_scenario is not None:
                with suppress(ValueError):
                    scenario = FakeScenario(fake_scenario)
                if scenario is None:
                    raise _command_error()
            options = ChatExecutionOptions(
                runtime_name=runtime,
                sandbox_name=sandbox,
                provider_model=provider_model,
                credential_ref=credential_ref,
                fake_scenario=scenario,
                allow_unsafe_local=allow_unsafe_local,
                review_plan=review_plan,
            )
            service = service_factory(redactor)
            selected: View | None = None
            try:
                selected = service.select(path, conversation_id=conversation, create_new=create_new)
            except FleetError as error:
                if not (
                    error.code is ErrorCode.PROJECT_NOT_INITIALIZED
                    and message is None
                    and conversation is None
                    and sys.stdin.isatty()
                    and sys.stdout.isatty()
                ):
                    raise
            selected_id = selected.get("conversation_id") if selected is not None else None
            if selected is not None and not isinstance(selected_id, str):
                raise _command_error()
            if message is not None:
                assert isinstance(selected_id, str)
                view = asyncio.run(
                    _message_session(
                        service,
                        selected_id,
                        message=message,
                        submission_id=submission_id,
                        options=options,
                    )
                )
            else:
                view = asyncio.run(
                    _terminal_session(
                        service,
                        selected,
                        options,
                        redactor=redactor,
                        show_error=lambda error: error_presenter(
                            "fleet chat", error, False, redactor
                        ),
                        onboarding_path=path,
                        create_new=create_new,
                    )
                )
            warnings = view.get("warnings")
            data = jsonable({key: value for key, value in view.items() if key != "warnings"})
            if not json_output:
                data = _human_value(data, redactor)
            return data, (
                [warning for warning in warnings if isinstance(warning, str)]
                if isinstance(warnings, list)
                else []
            )

        presenter("fleet chat", json_output, operation, redactor=redactor)

    return chat
