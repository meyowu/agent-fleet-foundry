"""Real CLI processes, pipes and TTYs use one durable conversation/run binding."""

from __future__ import annotations

import codecs
import errno
import json
import os
import re
import selectors
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import pytest

from agent_fleet.adapters.repository.git import GitRepositoryAdapter
from agent_fleet.adapters.system import UuidIdGenerator
from agent_fleet.bootstrap import ApplicationContainer, build_container
from agent_fleet.domain.models import ApprovalStatus, RunStatus

pytestmark = pytest.mark.e2e

# This process still runs the real CLI/container/store/workflow. Only the fake
# runtime await is held open to make active terminal-control tests deterministic.
_HELD_FAKE_ENTRY = """
import asyncio
import os
from agent_fleet.adapters.runtime.fake import FakeRuntimeAdapter
from agent_fleet.cli.app import main
original = FakeRuntimeAdapter.invoke
async def held(self, request, services):
    if str(request.role) == os.environ['FLEET_TEST_HELD_ROLE']:
        await asyncio.Event().wait()
    return await original(self, request, services)
FakeRuntimeAdapter.invoke = held
main()
"""


@dataclass
class ChatFixture:
    repository: Path
    state_root: Path
    environment: dict[str, str]
    baseline: tuple[str, str]

    def invoke(self, *arguments: str, success: bool = True) -> dict[str, Any]:
        result = subprocess.run(
            [sys.executable, "-m", "agent_fleet.cli.app", *arguments, "--json"],
            env=self.environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        assert (result.returncode == 0) is success, result.stdout + result.stderr
        assert "Traceback" not in result.stdout + result.stderr
        envelope = json.loads(result.stdout)
        assert envelope["ok"] is success
        return cast(dict[str, Any], envelope["data"] if success else envelope["error"])

    def message(self, text: str, *arguments: str, success: bool = True) -> dict[str, Any]:
        return self.invoke(
            "chat", str(self.repository), "--message", text, *arguments, success=success
        )

    def reopen(self) -> ApplicationContainer:
        return build_container(self.state_root)

    def git(self, *arguments: str) -> str:
        return subprocess.run(
            ["git", *arguments],
            cwd=self.repository,
            env=self.environment,
            capture_output=True,
            text=True,
            check=True,
        ).stdout

    def unchanged(self) -> None:
        assert (self.git("rev-parse", "HEAD"), self.git("status", "--porcelain")) == self.baseline


@pytest.fixture
def chat_fixture(tmp_path: Path) -> ChatFixture:
    repository = GitRepositoryAdapter(tmp_path, UuidIdGenerator()).create_canary_fixture(
        tmp_path / "target"
    )
    state_root = tmp_path / "state"
    # Fake is an explicit offline fixture, not proof of a verified bootstrap.
    build_container(state_root).projects._initialize_without_canary(
        repository, runtime_name="fake", sandbox_name="fake"
    )
    environment = {
        key: value
        for key, value in os.environ.items()
        if key in {"PATH", "TMPDIR", "TMP", "TEMP", "LANG", "LC_ALL", "SYSTEMROOT"}
    }
    environment.update(
        AGENT_FLEET_HOME=str(state_root), NO_COLOR="1", COLUMNS="240", PYTHONUNBUFFERED="1"
    )
    fixture = ChatFixture(repository, state_root, environment, ("", ""))
    fixture.baseline = (fixture.git("rev-parse", "HEAD"), fixture.git("status", "--porcelain"))
    return fixture


class InteractiveChat:
    def __init__(
        self,
        fixture: ChatFixture,
        *,
        conversation: str | None = None,
        held_role: str | None = None,
        tty: bool = False,
    ) -> None:
        self.master: int | None = None
        slave: int | None = None
        if tty:
            import pty

            self.master, slave = pty.openpty()
        environment = dict(fixture.environment)
        if held_role is not None:
            environment["FLEET_TEST_HELD_ROLE"] = held_role
        command = [sys.executable, "-u"]
        command += ["-c", _HELD_FAKE_ENTRY] if held_role else ["-m", "agent_fleet.cli.app"]
        command += ["chat", str(fixture.repository)]
        if conversation is not None:
            command += ["--conversation", conversation]
        self.process = subprocess.Popen(
            command,
            env=environment,
            stdin=slave if slave is not None else subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if slave is not None:
            os.close(slave)
        assert self.process.stdout is not None
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.process.stdout, selectors.EVENT_READ)
        self.output = ""

    def send(self, line: str) -> None:
        data = (line + "\n").encode()
        if self.master is not None:
            os.write(self.master, data)
        else:
            assert self.process.stdin is not None
            self.process.stdin.write(data)
            self.process.stdin.flush()

    def read_until(self, needle: str, *, after: int = 0) -> str:
        deadline = time.monotonic() + 30
        while needle not in self.output[after:]:
            assert time.monotonic() < deadline, self.output
            for key, _ in self.selector.select(0.2):
                chunk = os.read(key.fd, 16_384)
                if chunk:
                    self.output += chunk.decode("utf-8")
                    assert len(self.output) <= 512_000
                elif self.process.poll() is not None:
                    pytest.fail(f"Chat exited before {needle!r}: {self.output}")
        return self.output

    def eof(self) -> None:
        assert self.process.stdin is not None
        self.process.stdin.close()

    def finish(self) -> None:
        assert self.process.wait(timeout=30) == 0, self.output
        assert self.process.stdout is not None
        self.output += self.process.stdout.read().decode()
        assert "Traceback" not in self.output
        self.close()

    def close(self) -> None:
        if self.process.poll() is None:
            # Test teardown is scoped only to its own child process.
            self.process.kill()
            self.process.wait(timeout=5)
        self.selector.close()
        for stream in (self.process.stdin, self.process.stdout):
            if stream is not None:
                stream.close()
        if self.master is not None:
            os.close(self.master)
            self.master = None


def test_bare_real_terminal_restores_reviews_and_applies_without_leaving_session(
    chat_fixture: ChatFixture,
) -> None:
    import pty

    first = chat_fixture.message("Fix the canary", "--submission-id", "bare-review")
    run_id = first["run_id"]
    master, slave = pty.openpty()
    process = subprocess.Popen(
        [sys.executable, "-u", "-m", "agent_fleet.cli.app"],
        cwd=chat_fixture.repository,
        env=chat_fixture.environment,
        stdin=slave,
        stdout=slave,
        stderr=slave,
    )
    os.close(slave)
    selector = selectors.DefaultSelector()
    selector.register(master, selectors.EVENT_READ)
    output = ""
    decoder = codecs.getincrementaldecoder("utf-8")()

    def until(needle: str, *, after: int = 0) -> str:
        nonlocal output
        deadline = time.monotonic() + 30
        while needle not in output[after:]:
            assert time.monotonic() < deadline, output
            for key, _ in selector.select(0.2):
                output += decoder.decode(os.read(key.fd, 16_384))
                assert len(output) <= 512_000
        return output

    try:
        until("Type a goal")
        assert first["conversation_id"] in output
        os.write(master, b"/plan\n")
        until("inspection_only")
        os.write(master, b"/diff\n")
        until("diff --git")
        chat_fixture.unchanged()
        checkpoint = len(output)
        os.write(master, b"/apply\n")
        until('"confirmation_code":', after=checkpoint)
        # Wait for the complete code even if a descriptor read split its line.
        until('"expires_at":', after=checkpoint)
        code = re.search(r'"confirmation_code": "([0-9a-f]{16})"', output[checkpoint:])
        assert code is not None, output
        chat_fixture.unchanged()
        os.write(master, f"/confirm {code.group(1)}\n".encode())
        until('"status": "completed"', after=checkpoint)
        os.write(master, b"/exit\n")
        # A terminal consumer must drain the final result while awaiting exit;
        # otherwise bounded kernel output backpressure correctly blocks it.
        deadline = time.monotonic() + 30
        while process.poll() is None:
            assert time.monotonic() < deadline, output
            for key, _ in selector.select(0.2):
                try:
                    chunk = os.read(key.fd, 16_384)
                except OSError as error:
                    assert error.errno == errno.EIO
                    chunk = b""  # A closed PTY reports EIO on supported POSIX hosts.
                output += decoder.decode(chunk)
                assert len(output) <= 512_000
        assert process.returncode == 0
        container = chat_fixture.reopen()
        run = container.state.get_run(run_id)
        assert run.status is RunStatus.COMPLETED and run.applied_revision is not None
        assert chat_fixture.git("diff") == container.patches.show(run_id)
        assert (
            sum(
                event.event_type == "patch.applied" for event in container.state.list_events(run_id)
            )
            == 1
        )
        assert "Traceback" not in output
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        selector.close()
        os.close(master)


def test_plan_review_session_restart_confirms_only_then_explicitly_resumes(
    chat_fixture: ChatFixture,
) -> None:
    first = chat_fixture.message("Fix the canary", "--review-plan")
    run_id = first["run_id"]
    assert first["run"]["status"] == "paused_for_plan" and first["turn_status"] == "waiting"
    chat = InteractiveChat(chat_fixture, conversation=first["conversation_id"])
    try:
        chat.read_until("Type a goal")
        chat.send("/plan")
        chat.read_until('"mode": "pre_execution_gate"')
        before = len(chat.output)
        chat.send("/plan approve")
        chat.read_until('"confirmation_code":', after=before)
        chat.read_until('"expires_at":', after=before)
        match = re.search(r'"confirmation_code": "([0-9a-f]{16})"', chat.output[before:])
        assert match is not None
        chat_fixture.unchanged()
        before = len(chat.output)
        chat.send(f"/confirm {match.group(1)}")
        chat.read_until('"status": "approved"', after=before)
        container = chat_fixture.reopen()
        assert container.state.get_run(run_id).status is RunStatus.PAUSED_FOR_PLAN
        assert container.state.list_leases(run_id) == []
        chat_fixture.unchanged()
        before = len(chat.output)
        chat.send("/resume")
        chat.read_until("ready_for_review / presenting", after=before)
        chat.send("/exit")
        chat.finish()
        container = chat_fixture.reopen()
        assert container.plan_reviews.inspect(container.state.get_run(run_id)).status == "consumed"
        assert (
            sum(
                event.event_type == "fleet.plan_accepted"
                for event in container.state.list_events(run_id)
            )
            == 1
        )
        chat_fixture.unchanged()
    finally:
        chat.close()


def test_one_shot_review_plan_cli_requires_exact_hash_and_explicit_resume(
    chat_fixture: ChatFixture,
) -> None:
    run = chat_fixture.invoke(
        "run", "Fix the canary", "--project", str(chat_fixture.repository), "--review-plan"
    )
    run_id = run["run_id"]
    assert run["status"] == "paused_for_plan"
    shown = chat_fixture.invoke("plan", "show", run_id)
    assert shown["mode"] == "pre_execution_gate" and shown["task"] and shown["plan"]
    digest = shown["checkpoint"]["checkpoint_sha256"]
    chat_fixture.invoke("plan", "approve", run_id, "--expected-sha256", "0" * 64, success=False)
    approved = chat_fixture.invoke("plan", "approve", run_id, "--expected-sha256", digest)
    assert approved["checkpoint"]["status"] == "approved"
    container = chat_fixture.reopen()
    assert container.state.get_run(run_id).status is RunStatus.PAUSED_FOR_PLAN
    assert container.state.list_leases(run_id) == []
    chat_fixture.invoke("plan", "approve", run_id, "--expected-sha256", digest, success=False)
    result = chat_fixture.invoke("resume", run_id)
    assert result["status"] == "ready_for_review"
    chat_fixture.unchanged()


def test_no_id_permission_choice_requires_confirmation_and_explicit_resume(
    chat_fixture: ChatFixture,
) -> None:
    first = chat_fixture.message("Fix the canary", "--fake-scenario", "approval")
    run_id = first["run_id"]
    request_id = first["run"]["pending_approval_id"]
    assert request_id is not None
    chat = InteractiveChat(chat_fixture, conversation=first["conversation_id"])
    try:
        chat.read_until("Type a goal")
        chat.send("/approve")
        chat.read_until("Choose /approve --once")
        checkpoint = len(chat.output)
        chat.send("/approve --once")
        chat.read_until('"confirmation_code":', after=checkpoint)
        chat.read_until('"expires_at":', after=checkpoint)
        code = re.search(r'"confirmation_code": "([0-9a-f]{16})"', chat.output[checkpoint:])
        assert code is not None
        assert chat_fixture.reopen().state.get_approval(request_id).status is ApprovalStatus.PENDING
        chat.send(f"/confirm {code.group(1)}")
        chat.read_until('"grant_id":', after=checkpoint)
        rebuilt = chat_fixture.reopen()
        assert rebuilt.state.get_approval(request_id).status is ApprovalStatus.APPROVED
        assert rebuilt.state.get_run(run_id).status is RunStatus.PAUSED_FOR_APPROVAL
        checkpoint = len(chat.output)
        chat.send("/resume")
        chat.read_until("ready_for_review / presenting", after=checkpoint)
        chat.send("/exit")
        chat.finish()
        assert chat_fixture.reopen().state.get_run(run_id).status is RunStatus.READY_FOR_REVIEW
        chat_fixture.unchanged()
    finally:
        chat.close()


def test_unregistered_pipe_does_not_consume_setup_answers_or_publish(
    chat_fixture: ChatFixture,
    tmp_path: Path,
) -> None:
    target = GitRepositoryAdapter(tmp_path, UuidIdGenerator()).create_canary_fixture(
        tmp_path / "unregistered-pipe"
    )
    result = subprocess.run(
        [sys.executable, "-m", "agent_fleet.cli.app", "chat", str(target)],
        env=chat_fixture.environment,
        input="yes\nfake\nfleet-local:prepared\nsafe\n.\n",
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode != 0
    output = result.stdout + result.stderr
    assert "PROJECT_NOT_INITIALIZED" in output and "Review initialization" not in output
    assert not (target / ".fleet").exists()
    assert chat_fixture.reopen().state.get_project_by_root(str(target)) is None


def test_bare_unregistered_terminal_previews_then_cancels_without_publication(
    chat_fixture: ChatFixture,
    tmp_path: Path,
) -> None:
    import pty

    target = GitRepositoryAdapter(tmp_path, UuidIdGenerator()).create_canary_fixture(
        tmp_path / "unregistered-tty"
    )
    master, slave = pty.openpty()
    process = subprocess.Popen(
        [sys.executable, "-u", "-m", "agent_fleet.cli.app"],
        cwd=target,
        env=chat_fixture.environment,
        stdin=slave,
        stdout=slave,
        stderr=slave,
    )
    os.close(slave)
    selector = selectors.DefaultSelector()
    selector.register(master, selectors.EVENT_READ)
    output = ""
    decoder = codecs.getincrementaldecoder("utf-8")()
    sent = False
    try:
        deadline = time.monotonic() + 30
        while process.poll() is None:
            assert time.monotonic() < deadline, output
            for key, _ in selector.select(0.2):
                try:
                    chunk = os.read(key.fd, 16_384)
                except OSError as error:
                    assert error.errno == errno.EIO
                    chunk = b""
                output += decoder.decode(chunk)
                assert len(output) <= 512_000
            if not sent and "Review initialization" in output:
                os.write(master, b"yes\nfake\nfleet-local:prepared\nsafe\n.\n\n")
                sent = True
        assert process.returncode == 0, output
        assert "+++ b/.fleet/fleet.yaml" in output and "Type initialize" in output
        assert "Setup stopped" in output and "Traceback" not in output
        assert not (target / ".fleet").exists()
        assert chat_fixture.reopen().state.get_project_by_root(str(target)) is None
        assert not (chat_fixture.state_root / "bootstrap").exists()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        selector.close()
        os.close(master)


def test_message_retry_reopens_same_turn_and_normal_artifacts_without_reexecution(
    chat_fixture: ChatFixture,
) -> None:
    first = chat_fixture.message("Fix the canary", "--submission-id", "first-message")
    assert first["run"]["status"] == "ready_for_review"
    assert first["run"]["verified_complete"] is False
    retry = chat_fixture.message(
        "Fix the canary",
        "--conversation",
        first["conversation_id"],
        "--submission-id",
        "first-message",
    )
    assert (retry["run_id"], retry["turn_id"]) == (first["run_id"], first["turn_id"])
    container = chat_fixture.reopen()
    events = container.state.list_events(first["run_id"])
    assert sum(event.event_type == "run.created" for event in events) == 1
    assert (
        sum(
            event.event_type == "agent.started" and event.payload.get("role") == "cos"
            for event in events
        )
        == 1
    )
    changed = chat_fixture.message(
        "A changed goal",
        "--conversation",
        first["conversation_id"],
        "--submission-id",
        "first-message",
        success=False,
    )
    assert changed["code"] in {"CONFIG_INVALID", "RECOVERY_REQUIRED", "COMMAND_DENIED"}
    second = chat_fixture.message(
        "Fix the canary again",
        "--conversation",
        first["conversation_id"],
        "--submission-id",
        "second-message",
    )
    assert second["run_id"] != first["run_id"] and second["turn_id"] != first["turn_id"]
    old_retry = chat_fixture.message(
        "Fix the canary",
        "--conversation",
        first["conversation_id"],
        "--submission-id",
        "first-message",
    )
    assert old_retry["run_id"] == first["run_id"] and old_retry["turn_id"] == first["turn_id"]
    chat = InteractiveChat(chat_fixture, conversation=first["conversation_id"])
    try:
        chat.read_until("Type a goal")
        offset = len(chat.output)
        chat.send("/artifacts")
        chat.read_until('"artifacts": [', after=offset)
        chat.read_until(second["run"]["patch_artifact_id"], after=offset)
        chat.send("/permissions")
        chat.send("/status")
        chat.send("/exit")
        chat.finish()
        assert "ready_for_review" in chat.output and "False" in chat.output
        assert second["run"]["evidence_bundle_artifact_id"] in chat.output
    finally:
        chat.close()
    chat_fixture.unchanged()


def test_safe_approval_restart_and_public_resume_keep_one_conversation_run(
    chat_fixture: ChatFixture,
) -> None:
    chat_fixture.invoke(
        "permissions", "configure", "--project", str(chat_fixture.repository), "--mode", "safe"
    )
    initial = chat_fixture.message("Fix the canary", "--submission-id", "safe-message")
    assert initial["run"]["status"] == "paused_for_approval"
    request_id = initial["run"]["pending_approval_id"]
    run_id = initial["run_id"]
    before = chat_fixture.reopen().state.list_events(run_id)
    chat = InteractiveChat(chat_fixture, conversation=initial["conversation_id"])
    try:
        chat.read_until("Type a goal")
        chat.send(f"/permissions {request_id}")
        chat.send(f"/approve {request_id} --once")
        chat.read_until("allow_once")
        chat.send("/status")
        chat.send("/exit")
        chat.finish()
    finally:
        chat.close()
    container = chat_fixture.reopen()
    assert container.state.get_run(run_id).status is RunStatus.PAUSED_FOR_APPROVAL
    assert container.state.get_approval(request_id).status is ApprovalStatus.APPROVED
    assert sum(event.event_type == "agent.started" for event in before) == sum(
        event.event_type == "agent.started" for event in container.state.list_events(run_id)
    )
    chat = InteractiveChat(chat_fixture, conversation=initial["conversation_id"])
    try:
        chat.read_until("Type a goal")
        offset = len(chat.output)
        chat.send("/resume")
        chat.read_until("paused_for_approval /", after=offset)
        chat.send("/exit")
        chat.finish()
    finally:
        chat.close()
    # Further separate public resume commands share the conversation ownership boundary.
    status = chat_fixture.invoke("status", run_id)
    for _ in range(10):
        if status["status"] == "ready_for_review":
            break
        assert status["status"] == "paused_for_approval"
        pending_id = status["pending_approval_id"]
        chat_fixture.invoke("approve", pending_id, "--once")
        status = chat_fixture.invoke("resume", run_id)
    assert status["status"] == "ready_for_review" and status["verified_complete"] is False
    latest = chat_fixture.message(
        "Fix the canary",
        "--conversation",
        initial["conversation_id"],
        "--submission-id",
        "safe-message",
    )
    assert latest["run_id"] == run_id and latest["turn_id"] == initial["turn_id"]
    container = chat_fixture.reopen()
    events = container.state.list_events(run_id)
    assert (
        sum(
            event.event_type == "agent.started" and event.payload.get("role") == "cos"
            for event in events
        )
        == 1
    )
    assert not container.state.outstanding_leases(run_id)
    chat_fixture.unchanged()


def test_selected_chat_rejects_foreign_approval_and_cross_project_selection(
    chat_fixture: ChatFixture,
    tmp_path: Path,
) -> None:
    chat_fixture.invoke(
        "permissions", "configure", "--project", str(chat_fixture.repository), "--mode", "safe"
    )
    first = chat_fixture.message("First goal", "--submission-id", "first")
    other = chat_fixture.message("Other goal", "--new", "--submission-id", "other")
    foreign_request = other["run"]["pending_approval_id"]
    chat = InteractiveChat(chat_fixture, conversation=first["conversation_id"])
    try:
        chat.read_until("Type a goal")
        chat.send(f"/approve {foreign_request} --once")
        chat.send(f"/deny {foreign_request}")
        chat.send("/exit")
        chat.finish()
        assert "APPROVAL_INVALID" in chat.output
    finally:
        chat.close()
    container = chat_fixture.reopen()
    assert container.state.get_approval(foreign_request).status is ApprovalStatus.PENDING
    second_repository = GitRepositoryAdapter(tmp_path, UuidIdGenerator()).create_canary_fixture(
        tmp_path / "other-target"
    )
    container.projects._initialize_without_canary(
        second_repository, runtime_name="fake", sandbox_name="fake"
    )
    error = chat_fixture.invoke(
        "chat",
        str(second_repository),
        "--conversation",
        first["conversation_id"],
        "--message",
        "Must not execute",
        success=False,
    )
    assert error["code"] in {
        "COMMAND_DENIED",
        "CONFIG_INVALID",
        "RESOURCE_NOT_FOUND",
        "RECOVERY_REQUIRED",
    }
    for view in (first, other):
        chat_fixture.invoke("cancel", view["run_id"])
    chat_fixture.unchanged()


def test_interrupted_owner_reopens_without_replay_and_requires_explicit_recovery(
    chat_fixture: ChatFixture,
) -> None:
    owner = InteractiveChat(chat_fixture, held_role="cos")
    try:
        owner.read_until("Type a goal")
        owner.send("Fix the canary")
        owner.read_until("scoping")
        container = chat_fixture.reopen()
        before = container.conversations.select(chat_fixture.repository)
        run_id, conversation_id = str(before["run_id"]), str(before["conversation_id"])
        # An abrupt process death cannot become permission to replay the claimed CoS.
        owner.close()
    finally:
        owner.close()
    observer = InteractiveChat(chat_fixture, conversation=conversation_id)
    try:
        observer.read_until("Type a goal")
        observer.send("/status")
        observer.send("/resume")
        observer.read_until("RECOVERY_REQUIRED")
        observer.send("/exit")
        observer.finish()
    finally:
        observer.close()
    container = chat_fixture.reopen()
    assert container.state.get_run(run_id).status is RunStatus.RUNNING
    assert (
        sum(
            event.event_type == "agent.started" and event.payload.get("role") == "cos"
            for event in container.state.list_events(run_id)
        )
        == 1
    )
    refusal = chat_fixture.invoke("recover", run_id, success=False)
    assert refusal["code"] == "RECOVERY_REQUIRED"
    recovered = chat_fixture.invoke("recover", run_id, "--confirm-owner-stopped")
    assert recovered["status"] == "failed" and recovered["outstanding_lease_ids"] == []
    container = chat_fixture.reopen()
    after = container.conversations.select(chat_fixture.repository, conversation_id=conversation_id)
    assert after["run_id"] == run_id and after["active_turn_id"] is None
    assert after["recovery_required"] is False
    chat_fixture.unchanged()


def test_noninteractive_repeated_interrupt_returns_one_cancelled_json_envelope(
    chat_fixture: ChatFixture,
) -> None:
    container = chat_fixture.reopen()
    project = container.state.get_project_by_root(str(chat_fixture.repository.resolve()))
    assert project is not None
    environment = {**chat_fixture.environment, "FLEET_TEST_HELD_ROLE": "cos"}
    process = subprocess.Popen(
        [
            sys.executable,
            "-u",
            "-c",
            _HELD_FAKE_ENTRY,
            "chat",
            str(chat_fixture.repository),
            "--message",
            "Fix the canary",
            "--submission-id",
            "interrupted-message",
            "--json",
        ],
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 30
        run_id: str | None = None
        while time.monotonic() < deadline:
            conversation = container.conversation_store.latest(
                project.project_id, project.identity_hash
            )
            if conversation is not None:
                turns = container.conversation_store.list_turns(
                    project.project_id, conversation.conversation_id, limit=1
                )
                if turns:
                    candidate_id = turns[0].binding.run_id
                    if any(
                        event.event_type == "agent.started" and event.payload.get("role") == "cos"
                        for event in container.state.list_events(candidate_id)
                    ):
                        run_id = candidate_id
                        break
            time.sleep(0.02)
        assert run_id is not None
        process.send_signal(signal.SIGINT)
        process.send_signal(signal.SIGINT)
        stdout, stderr = process.communicate(timeout=30)
        assert process.returncode == 0, stdout.decode() + stderr.decode()
        assert b"Traceback" not in stderr
        envelope = json.loads(stdout)
        assert envelope["ok"] is True and envelope["command"] == "fleet chat"
        assert envelope["data"]["run_id"] == run_id
        assert envelope["data"]["run"]["status"] == "cancelled"
        assert envelope["data"]["active_turn_id"] is None
        assert not container.state.outstanding_leases(run_id)
        chat_fixture.unchanged()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                stream.close()


@pytest.mark.parametrize(
    "role,ending,tty",
    [
        ("cos", "exit", False),
        ("engineer", "eof", False),
        ("verifier", "interrupt", False),
        ("engineer", "cancel", False),
        ("engineer", "cancel", True),
    ],
)
def test_real_pipe_or_tty_inspection_and_stop_remain_responsive_during_work(
    chat_fixture: ChatFixture,
    role: str,
    ending: str,
    tty: bool,
) -> None:
    chat = InteractiveChat(chat_fixture, held_role=role, tty=tty)
    run_id: str | None = None
    try:
        chat.read_until("Type a goal")
        chat.send("Fix the canary")
        stage = {"cos": "scoping", "engineer": "implementing", "verifier": "verifying"}[role]
        # Progress comes from durable recorded events, not a test-side runtime signal.
        chat.read_until(stage)
        offset = len(chat.output)
        chat.send("/status")
        chat.read_until(f"running / {stage}", after=offset)
        container = chat_fixture.reopen()
        selected = container.conversations.select(chat_fixture.repository)
        run_id = str(selected["run_id"])
        events = container.state.list_events(run_id)
        assert any(
            event.event_type == "agent.started" and event.payload.get("role") == role
            for event in events
        )
        if ending == "exit":
            chat.send("/exit")
        elif ending == "eof":
            chat.eof()
        elif ending == "interrupt":
            chat.process.send_signal(signal.SIGINT)
            chat.process.send_signal(signal.SIGINT)
        else:
            chat.send("/cancel")
            chat.read_until("cancelled /")
            chat.send("/exit")
        chat.finish()
        container = chat_fixture.reopen()
        assert container.state.get_run(run_id).status is RunStatus.CANCELLED
        assert not container.state.outstanding_leases(run_id)
        view = container.conversations.select(chat_fixture.repository)
        assert view["run_id"] == run_id and view["active_turn_id"] is None
        assert view["recovery_required"] is False
        chat_fixture.unchanged()
    finally:
        chat.close()
