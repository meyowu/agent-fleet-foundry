from __future__ import annotations

import asyncio
import importlib
import json
import os
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from agent_fleet.application.conversations import ChatExecutionOptions, SessionBootstrapOptions
from agent_fleet.application.readiness import ReadinessService
from agent_fleet.cli.app import _present_error, _present_with_warnings
from agent_fleet.cli.chat import PosixLineInput, View, register_chat_command, run_session
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import ApprovalChoice, FakeScenario
from agent_fleet.domain.readiness import (
    MAX_READINESS_BYTES,
    ReadinessReport,
    StaticDeclaration,
    StaticReadinessMetadata,
)
from agent_fleet.domain.security import Redactor


class QueuedInput:
    def __init__(self) -> None:
        self.lines: asyncio.Queue[str | None] = asyncio.Queue()

    async def read_line(self) -> str | None:
        return await self.lines.get()

    def send(self, line: str | None) -> None:
        self.lines.put_nowait(line)


class StrictService:
    """Only the frozen CLI contract; owns its cancellable execution task."""

    def __init__(self, *, immediate: bool = False) -> None:
        self.immediate = immediate
        self.calls: list[tuple[object, ...]] = []
        self.entered = asyncio.Event()
        self.cleanup_started = asyncio.Event()
        self.cleanup_release = asyncio.Event()
        self.cleanup_release.set()
        self.release = asyncio.Event()
        self.worker: asyncio.Task[bool] | None = None
        self.run_status: str | None = None
        self.progress_count = 0
        self.cancelled = 0
        self.selected = False

    def _view(self) -> View:
        return {
            "conversation_id": "conv_" + "a" * 32,
            "project_id": "prj_" + "b" * 32,
            "revision": 0,
            "active_turn_id": None,
            "turn_id": None,
            "run_id": "run_" + "c" * 32 if self.run_status else None,
            "turn_status": self.run_status,
            "run": (
                {"status": self.run_status, "stage": "scoping", "verified_complete": False}
                if self.run_status
                else None
            ),
            "user_summary": None,
            "result_summary": None,
            "summary_truncated": False,
            "recovery_required": False,
            "warnings": ["Fake sandbox did not execute code."],
        }

    def select(
        self, project_path: Path, *, conversation_id: str | None = None, create_new: bool = False
    ) -> View:
        self.selected = True
        self.calls.append(("select", project_path, conversation_id, create_new))
        return self._view()

    def status(self, conversation_id: str) -> View:
        assert self.selected
        self.calls.append(("status", conversation_id))
        return self._view()

    def preview_initialization(
        self, project_path: Path, *, options: SessionBootstrapOptions
    ) -> View:
        raise AssertionError("Registered chat must not initialize a project.")

    async def initialize(self, *, code: str) -> View:
        raise AssertionError("Registered chat must not initialize a project.")

    async def submit(
        self,
        conversation_id: str,
        *,
        message: str,
        submission_id: str | None,
        options: ChatExecutionOptions,
    ) -> View:
        assert self.selected
        self.calls.append(("submit", conversation_id, message, submission_id, options))
        self.run_status = "running"
        self.entered.set()
        if self.immediate:
            self.run_status = "ready_for_review"
            return self._view()
        self.worker = asyncio.create_task(self.release.wait())
        try:
            await self.worker
        except asyncio.CancelledError:
            return self._view()
        self.run_status = "ready_for_review"
        return self._view()

    async def resume(self, conversation_id: str, *, allow_unsafe_local: bool = False) -> View:
        self.calls.append(("resume", conversation_id, allow_unsafe_local))
        self.run_status = "ready_for_review"
        return self._view()

    async def cancel(self, conversation_id: str) -> View:
        self.calls.append(("cancel", conversation_id))
        self.cancelled += 1
        if self.worker is not None and not self.worker.done():
            self.worker.cancel()
            with suppress(asyncio.CancelledError):
                await self.worker
        self.cleanup_started.set()
        await self.cleanup_release.wait()
        self.run_status = "cancelled"
        return self._view()

    def artifacts(self, conversation_id: str) -> View:
        self.calls.append(("artifacts", conversation_id))
        return {"artifact_id": "art_" + "d" * 32}

    def tasks(
        self,
        conversation_id: str,
        *,
        before_sequence: int | None = None,
        select_sequence: int | None = None,
        current: bool = False,
    ) -> View:
        self.calls.append(("tasks", before_sequence, select_sequence, current))
        return self._view()

    def models(
        self,
        conversation_id: str,
        *,
        profile: str | None = None,
        role: str | None = None,
        default: bool = False,
    ) -> View:
        self.calls.append(("models", profile, role, default))
        return {"notice": "future tasks only"}

    def roles(self, conversation_id: str) -> View:
        self.calls.append(("roles",))
        return {"roles": []}

    def readiness(self, conversation_id: str) -> View:
        self.calls.append(("readiness",))
        return ReadinessReport(
            repository_identity="a" * 64,
            head_revision="b" * 40,
            status_fingerprint="c" * 64,
            dirty=False,
            profile_sha256="d" * 64,
            configuration_status="absent",
            ecosystems=(),
            boundaries=(),
            metadata=StaticReadinessMetadata(),
            detected_candidates=(),
            configured_commands=(),
            diagnostics=(),
            inspection_complete=True,
            next_steps=("prepare_reviewed_environment", "run_approved_baseline_later"),
        ).model_dump(mode="json")

    def review(self, conversation_id: str, *, action: str, arguments: tuple[str, ...] = ()) -> View:
        self.calls.append(("review", conversation_id, action, arguments))
        return {"action": action, "patch": "--- before\n+++ after\n+safe [text]\x1b[31m"}

    def permissions(self, conversation_id: str, *, identifier: str | None = None) -> View:
        self.calls.append(("permissions", conversation_id, identifier))
        return {"rules": []}

    def approve(
        self,
        conversation_id: str,
        request_id: str | None = None,
        *,
        choice: ApprovalChoice | None = None,
    ) -> View:
        self.calls.append(("approve", conversation_id, request_id, choice))
        return {"request_id": request_id, "choice": choice.value if choice is not None else None}

    def deny(
        self, conversation_id: str, request_id: str | None = None, *, reason: str | None = None
    ) -> View:
        self.calls.append(("deny", conversation_id, request_id, reason))
        return {"request_id": request_id, "resolution": "denied"}

    async def recover(
        self,
        conversation_id: str,
        *,
        code: str | None = None,
        confirm_owner_stopped: bool = False,
    ) -> View:
        self.calls.append(("recover", conversation_id, code, confirm_owner_stopped))
        return {"recovery_code": "fedcba9876543210", "replayed": False}

    def progress(self, conversation_id: str, *, cursor: str | None = None, limit: int = 50) -> View:
        assert limit <= 100
        self.progress_count += 1
        return {
            "cursor": "cursor1",
            "has_more": False,
            "events": []
            if cursor
            else [
                {
                    "event_id": "evt_1",
                    "sequence": 1,
                    "run_id": None,
                    "event_type": "run.started",
                    "summary": "Started [untrusted] \x1b[31mSECRET",
                    "request_ids": ["perm_pending"],
                },
                {
                    "event_id": "evt_2",
                    "sequence": 2,
                    "run_id": None,
                    "event_type": "agent.started",
                    "summary": "Agent started",
                    "request_ids": ["perm_pending"],
                },
            ],
        }


def _session(
    service: StrictService,
    reader: QueuedInput,
    output: list[str],
    errors: list[FleetError],
    *,
    interrupt: asyncio.Event | None = None,
) -> asyncio.Task[View]:
    selected = service.select(Path("."))
    return asyncio.create_task(
        run_session(
            service,
            selected,
            ChatExecutionOptions(allow_unsafe_local=True),
            reader,
            emit=output.append,
            show_error=errors.append,
            redactor=Redactor(["SECRET"]),
            interrupt=interrupt,
        )
    )


async def _wait_for(predicate: Callable[[], bool]) -> None:
    async with asyncio.timeout(3):
        while not predicate():  # noqa: ASYNC110 - bounded observation of terminal output
            await asyncio.sleep(0.005)


@pytest.mark.asyncio
async def test_session_keeps_status_cancel_responsive_and_never_queues_second_goal() -> None:
    service, reader = StrictService(), QueuedInput()
    output: list[str] = []
    errors: list[FleetError] = []
    task = _session(service, reader, output, errors)
    reader.send("first goal")
    await asyncio.wait_for(service.entered.wait(), 3)
    reader.send("second goal")
    reader.send("/status")
    await _wait_for(lambda: any("running / scoping" in text for text in output))
    assert len([call for call in service.calls if call[0] == "submit"]) == 1
    assert errors and errors[0].code is ErrorCode.RECOVERY_REQUIRED
    reader.send("/cancel")
    await asyncio.wait_for(service.cleanup_started.wait(), 3)
    await _wait_for(lambda: service.run_status == "cancelled")
    reader.send("/exit")
    view = await asyncio.wait_for(task, 3)
    assert view["turn_status"] == "cancelled"
    assert service.cancelled == 1 and service.worker is not None and service.worker.done()
    rendered = "\n".join(output)
    assert "SECRET" not in rendered and "\x1b" not in rendered and "\\x1b" in rendered


@pytest.mark.asyncio
async def test_review_commands_are_explicit_and_render_full_escaped_diff() -> None:
    service, reader = StrictService(), QueuedInput()
    output: list[str] = []
    errors: list[FleetError] = []
    task = _session(service, reader, output, errors)
    commands = [
        "/plan",
        "/diff",
        "/apply",
        "/fleet-patch list",
        "/fleet-patch diff exact-id",
        "/confirm 0123456789abcdef",
        "/dismiss",
    ]
    for command in commands:
        reader.send(command)
    reader.send("/exit")
    await asyncio.wait_for(task, 3)
    reviews = [call for call in service.calls if call[0] == "review"]
    assert len(reviews) == len(commands) and not errors
    assert reviews[-2][2:] == ("confirm", ("0123456789abcdef",))
    assert any(text == "--- before\n+++ after\n+safe [text]\\x1b[31m" for text in output)
    assert all("\x1b" not in text for text in output)
    assert not any(call[0] in {"submit", "approve"} for call in service.calls)


@pytest.mark.asyncio
async def test_management_commands_stay_in_same_session_and_never_become_goals() -> None:
    service, reader = StrictService(), QueuedInput()
    errors: list[FleetError] = []
    task = _session(service, reader, [], errors)
    for command in (
        "/models",
        "/models use small --default",
        "/models use small --role engineer",
        "/roles",
        "/readiness",
        "/tasks",
        "/tasks 21",
        "/tasks select 3",
        "/tasks current",
        "/exit",
    ):
        reader.send(command)
    await asyncio.wait_for(task, 3)
    assert not errors
    assert ("models", "small", None, True) in service.calls
    assert ("models", "small", "engineer", False) in service.calls
    assert ("tasks", 21, None, False) in service.calls
    assert ("tasks", None, 3, False) in service.calls
    assert ("tasks", None, None, True) in service.calls
    assert not any(call[0] in {"submit", "approve", "resume", "cancel"} for call in service.calls)


@pytest.mark.asyncio
async def test_recovery_preview_and_confirmation_are_separate_explicit_commands() -> None:
    service, reader = StrictService(), QueuedInput()
    errors: list[FleetError] = []
    task = _session(service, reader, [], errors)
    reader.send("/recover")
    reader.send("/recover --confirm-owner-stopped fedcba9876543210")
    reader.send("/exit")
    await asyncio.wait_for(task, 3)
    assert not errors
    recovery_calls = [call for call in service.calls if call[0] == "recover"]
    assert len(recovery_calls) == 2
    assert recovery_calls[0][2:] == (None, False)
    assert recovery_calls[1][2:] == ("fedcba9876543210", True)
    assert not any(call[0] in {"submit", "resume", "cancel"} for call in service.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "command",
    [
        "/models small",
        "/models use small",
        "/models use small --default --role engineer",
        "/models use small --role",
        "/models set small",
        "/roles extra",
        "/readiness --run",
        "/tasks 0",
        "/tasks 1001",
        "/tasks select run_abcdef",
        "/tasks select -1",
        "/tasks select \uff11",
        "/tasks current extra",
        "/recover --confirm-owner-stopped",
        "/recover fedcba9876543210",
        "/recover --force fedcba9876543210",
        "/recover --confirm-owner-stopped fedcba9876543210 extra",
    ],
)
async def test_management_command_invalid_syntax_has_no_service_side_effect(command: str) -> None:
    service, reader = StrictService(), QueuedInput()
    errors: list[FleetError] = []
    task = _session(service, reader, [], errors)
    reader.send(command)
    reader.send("/exit")
    await asyncio.wait_for(task, 3)
    assert len(errors) == 1
    assert not any(
        call[0] in {"models", "roles", "readiness", "tasks", "submit", "recover"}
        for call in service.calls
    )


@pytest.mark.asyncio
async def test_session_readiness_bounds_the_actual_pretty_printed_unicode_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, reader = StrictService(), QueuedInput()
    value = service.readiness("unused")
    path = "/".join("界" * 45 + str(index) for index in range(8)) + "/package.json"
    value["metadata"] = StaticReadinessMetadata(
        declarations=tuple(
            StaticDeclaration(
                manifest_path=path,
                ecosystem="node",
                category="dependency",
                name=f"dependency{index}",
                source_type="registry",
            )
            for index in range(512)
        )
    ).model_dump(mode="json")
    original = ReadinessService._bounded_report(dict(value))
    monkeypatch.setattr(service, "readiness", lambda _: original.model_dump(mode="json"))
    output: list[str] = []
    errors: list[FleetError] = []
    task = _session(service, reader, output, errors)
    reader.send("/readiness")
    reader.send("/exit")
    await asyncio.wait_for(task, 10)
    rendered = next(text for text in output if '"kind": "ReadinessReport"' in text)
    assert len((rendered + "\n").encode("utf-8")) <= MAX_READINESS_BYTES
    report = ReadinessReport.model_validate_json(rendered)
    assert report.metadata.omitted_declarations > original.metadata.omitted_declarations
    assert not report.inspection_complete and report.commands_executed == 0
    assert not errors


def test_bare_noninteractive_help_does_not_create_application_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("agent_fleet.cli.app")
    monkeypatch.setattr(module, "build_container", lambda **_: pytest.fail("container created"))
    monkeypatch.setattr(module, "_launch_chat", lambda: pytest.fail("chat launched"))
    for arguments in ([], ["--help"]):
        result = CliRunner().invoke(
            module.app, arguments, env={"AGENT_FLEET_HOME": str(tmp_path / "state")}
        )
        assert result.exit_code == 0 and "Usage:" in result.stdout
    assert not (tmp_path / "state").exists()


def test_bare_terminal_uses_registered_chat_launcher(monkeypatch: pytest.MonkeyPatch) -> None:
    module = importlib.import_module("agent_fleet.cli.app")
    calls: list[bool] = []
    monkeypatch.setattr(module, "_interactive_terminal", lambda: True)
    monkeypatch.setattr(module, "_launch_chat", lambda: calls.append(True))
    assert CliRunner().invoke(module.app, []).exit_code == 0
    assert calls == [True]
    assert CliRunner().invoke(module.app, ["version", "--json"]).exit_code == 0
    assert calls == [True]


@pytest.mark.asyncio
@pytest.mark.parametrize("ending", [None, "/exit", "interrupt"])
async def test_exit_eof_and_interrupt_await_service_cleanup(ending: str | None) -> None:
    service, reader = StrictService(), QueuedInput()
    service.cleanup_release.clear()
    interrupt = asyncio.Event()
    task = _session(service, reader, [], [], interrupt=interrupt)
    reader.send("goal")
    await asyncio.wait_for(service.entered.wait(), 3)
    if ending == "interrupt":
        interrupt.set()
    else:
        reader.send(ending)
    await asyncio.wait_for(service.cleanup_started.wait(), 3)
    assert not task.done()
    # Repeated task cancellation cannot tear down retained cleanup.
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    service.cleanup_release.set()
    await asyncio.wait_for(task, 3)
    assert service.run_status == "cancelled" and service.cancelled == 1


@pytest.mark.asyncio
async def test_slash_commands_are_exact_and_never_implicitly_resume_or_submit() -> None:
    service, reader = StrictService(), QueuedInput()
    errors: list[FleetError] = []
    task = _session(service, reader, [], errors)
    for line in [
        "/help",
        "/status",
        "/artifacts",
        "/permissions",
        "/permissions perm_1",
        "/approve perm_1 --once",
        "/approve perm_2 --run",
        "/approve perm_3 --always --scope project",
        "/deny perm_4 --reason 'not needed'",
        "/approve perm_1 --once --run",
        "/approve perm_1 --always",
        "/approve perm_1",
        "/unknown SECRET",
        "/deny",
        "/status --extra",
        "/approve 'unterminated",
        "/exit",
    ]:
        reader.send(line)
    await asyncio.wait_for(task, 3)
    assert not any(call[0] in {"submit", "resume", "cancel"} for call in service.calls)
    assert [call[-1] for call in service.calls if call[0] == "approve"] == [
        ApprovalChoice.ALLOW_ONCE,
        ApprovalChoice.ALLOW_RUN,
        ApprovalChoice.ALLOW_ALWAYS,
    ]
    assert next(call[-1] for call in service.calls if call[0] == "deny") == "not needed"
    assert len(errors) == 6 and all("SECRET" not in error.message for error in errors)
    assert [call[2] for call in service.calls if call[0] == "deny"] == ["perm_4", None]


@pytest.mark.asyncio
async def test_resume_passes_explicit_unsafe_confirmation_and_progress_is_not_repeated() -> None:
    service, reader = StrictService(), QueuedInput()
    output: list[str] = []
    task = _session(service, reader, output, [])
    reader.send("/resume")
    await _wait_for(lambda: any(call[0] == "resume" for call in service.calls))
    await _wait_for(lambda: service.progress_count >= 2)
    reader.send("/exit")
    await asyncio.wait_for(task, 3)
    assert next(call[-1] for call in service.calls if call[0] == "resume") is True
    assert sum("Started" in item for item in output) == 1
    assert sum("Pending approval: perm_pending" in item for item in output) == 1


@pytest.mark.asyncio
async def test_pipe_input_crlf_partial_eof_backpressure_and_descriptor_restoration() -> None:
    read_fd, write_fd = os.pipe()
    stream = os.fdopen(read_fd, "r", encoding="utf-8")
    try:
        async with PosixLineInput(stream) as reader:
            assert not os.get_blocking(read_fd)
            payload = "".join(f"line {index}\r\n" for index in range(200)) + "last é"
            os.write(write_fd, payload.encode())
            os.close(write_fd)
            write_fd = -1
            for index in range(200):
                assert await asyncio.wait_for(reader.read_line(), 3) == f"line {index}"
            assert await reader.read_line() == "last é"
            assert await reader.read_line() is None
        assert os.get_blocking(read_fd)
        assert not stream.closed
    finally:
        stream.close()
        if write_fd >= 0:
            os.close(write_fd)


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [b"\xffSECRET\n", b"a\x00SECRET\n", b"a" * 16_385])
async def test_invalid_input_is_cause_free_and_never_decoded_as_more_commands(
    payload: bytes,
) -> None:
    read_fd, write_fd = os.pipe()
    stream = os.fdopen(read_fd, "r", encoding="utf-8")
    try:
        async with PosixLineInput(stream) as reader:
            os.set_blocking(write_fd, False)
            for start in range(0, len(payload), 4096):
                os.write(write_fd, payload[start : start + 4096])
                await asyncio.sleep(0.005)
            with pytest.raises(FleetError) as caught:
                await asyncio.wait_for(reader.read_line(), 3)
            assert "SECRET" not in str(caught.value)
            assert caught.value.__cause__ is None and caught.value.__context__ is None
    finally:
        stream.close()
        os.close(write_fd)


@pytest.mark.asyncio
async def test_real_tty_input_reads_a_line_without_input_thread() -> None:
    import pty

    master, slave = pty.openpty()
    stream = os.fdopen(slave, "r", encoding="utf-8")
    try:
        async with PosixLineInput(stream) as reader:
            os.write(master, b"/status\n")
            assert await asyncio.wait_for(reader.read_line(), 3) == "/status"
        assert os.get_blocking(slave)
    finally:
        stream.close()
        os.close(master)


@pytest.mark.asyncio
async def test_unsupported_input_fails_clearly(tmp_path: Path) -> None:
    source = tmp_path / "input.txt"
    source.write_text("/status\n", encoding="utf-8")
    with source.open(encoding="utf-8") as stream, pytest.raises(FleetError):
        async with PosixLineInput(stream):
            pytest.fail("regular files are not the supported interactive input boundary")


def _app(service: StrictService) -> typer.Typer:
    app = typer.Typer()
    register_chat_command(
        app,
        service_factory=lambda _: service,
        redactor_factory=lambda: Redactor(["SECRET"]),
        presenter=_present_with_warnings,
        error_presenter=_present_error,
    )

    # Match the real multi-command app so invocation requires the `chat` name.
    @app.command()
    def noop() -> None:
        pass

    return app


def test_message_json_is_one_envelope_with_exact_options_and_no_progress() -> None:
    service = StrictService(immediate=True)
    result = CliRunner().invoke(
        _app(service),
        [
            "chat",
            "project",
            "--new",
            "--message",
            "one goal",
            "--submission-id",
            "retry-1",
            "--json",
            "--runtime",
            "fake",
            "--sandbox",
            "fake",
            "--fake-scenario",
            "direct",
            "--provider-model",
            "openai:model",
            "--credential-ref",
            "env:TEST_KEY",
            "--allow-unsafe-local",
        ],
    )
    assert result.exit_code == 0, result.output
    envelope = json.loads(result.stdout)
    assert envelope["ok"] is True and envelope["command"] == "fleet chat"
    assert envelope["warnings"] == ["Fake sandbox did not execute code."]
    assert "warnings" not in envelope["data"] and service.progress_count == 0
    call = next(call for call in service.calls if call[0] == "submit")
    assert call[2:4] == ("one goal", "retry-1")
    assert call[-1] == ChatExecutionOptions(
        runtime_name="fake",
        sandbox_name="fake",
        provider_model="openai:model",
        credential_ref="env:TEST_KEY",
        fake_scenario=FakeScenario.DIRECT,
        allow_unsafe_local=True,
    )


def test_human_final_overview_does_not_interpret_summary_terminal_controls() -> None:
    class DisplayService(StrictService):
        def _view(self) -> View:
            return {**super()._view(), "result_summary": "[red]SECRET\x1b[2J[end]"}

    result = CliRunner().invoke(_app(DisplayService(immediate=True)), ["chat", "--message", "goal"])
    assert result.exit_code == 0, result.output
    assert "SECRET" not in result.output and "\x1b" not in result.output
    assert "[red]" in result.output and "[end]" in result.output and "\\x1b" in result.output


@pytest.mark.parametrize(
    "arguments",
    [
        ["--json"],
        ["--message", "/status", "--json"],
        ["--message", "goal", "--new", "--conversation", "SECRET", "--json"],
        ["--message", "goal", "--fake-scenario", "SECRET", "--json"],
        ["--message", "goal", "--unknown-SECRET", "--json"],
        ["--json", "--message"],
        ["--submission-id", "SECRET"],
    ],
)
def test_invalid_arguments_are_redacted_local_failures(arguments: list[str]) -> None:
    service = StrictService(immediate=True)
    result = CliRunner().invoke(_app(service), ["chat", *arguments])
    assert result.exit_code == 2, result.output
    assert "SECRET" not in result.output and not service.calls
    assert "Traceback" not in result.output
    if "--json" in arguments:
        envelope = json.loads(result.stdout)
        assert envelope["ok"] is False and envelope["error"]["code"] == "CONFIG_INVALID"
