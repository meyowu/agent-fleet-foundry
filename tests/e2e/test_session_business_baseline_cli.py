"""Actual Session subprocess and SQLite, synthetic Docker transport only."""

from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import test_persistent_chat_cli as interactive

if TYPE_CHECKING:
    from test_business_baseline_integration import business_fixture
else:
    from integration.test_business_baseline_integration import business_fixture

pytestmark = pytest.mark.e2e

_ENTRY = """
import asyncio
import os
import sys
from pathlib import Path
import agent_fleet
source = Path(agent_fleet.__file__).resolve().parents[2]
assert str(source) == os.environ['FLEET_TEST_SOURCE_ROOT']
sys.path.insert(0, str(source / 'tests'))
from contract.test_baseline_sandbox import BaselineRecordingRunner
import agent_fleet.bootstrap as bootstrap
from agent_fleet.application.conversations import ConversationService
from agent_fleet.cli.app import main
original = bootstrap.build_baseline_container
def build(*args, **kwargs):
    container = original(*args, **kwargs)
    provider = container.sandboxes.get('docker')
    runner = BaselineRecordingRunner(
        Path(os.environ['FLEET_TEST_TARGET']), provider.git_shadow_path)
    provider.runner = runner
    provider.docker_executable = '/usr/bin/docker'
    provider.uid = provider.gid = 1000
    if os.environ.get('FLEET_TEST_BASELINE_HOLD') == '1':
        runner.block_start = True
        original_run = runner.run
        async def transport(argv, **kwargs):
            if argv[1:3] == ('container', 'start'):
                print('BASELINE_TRANSPORT_ENTERED', flush=True)
            return await original_run(argv, **kwargs)
        runner.run = transport
    return container
bootstrap.build_baseline_container = build
original_plan = ConversationService.baseline_plan
async def guarded(self, *args, **kwargs):
    def forbidden(*args, **kwargs):
        raise AssertionError('baseline CLI read credential/runtime/history')
    for name in ('_conversation', '_turn', '_view', '_require_current', '_review_selection',
                 '_register_redaction', '_register_run_redaction', 'status', 'progress', 'cancel'):
        setattr(self, name, forbidden)
    self.secrets.inspect = forbidden
    self.secrets.resolve = forbidden
    bootstrap.RuntimeRegistry = forbidden
    bootstrap.EnvironmentSecretStore = forbidden
    return await original_plan(self, *args, **kwargs)
ConversationService.baseline_plan = guarded
main()
"""


def fixture(tmp_path: Path) -> tuple[interactive.ChatFixture, str]:
    baseline, target, command, _ = business_fixture(tmp_path)
    environment = {
        key: value
        for key, value in os.environ.items()
        if key in {"PATH", "TMPDIR", "TMP", "TEMP", "LANG", "LC_ALL", "SYSTEMROOT"}
    }
    environment.update(
        AGENT_FLEET_HOME=str(tmp_path / "state"),
        NO_COLOR="1",
        COLUMNS="240",
        PYTHONUNBUFFERED="1",
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONNOUSERSITE="1",
        FLEET_TEST_SOURCE_ROOT=str(Path(__file__).resolve().parents[2]),
        FLEET_TEST_TARGET=str(target),
    )
    result = interactive.ChatFixture(target, tmp_path / "state", environment, ("", ""))
    result.baseline = result.git("rev-parse", "HEAD"), result.git("status", "--porcelain")
    assert baseline.state.database_path == result.state_root / "state.db"
    return result, command


def counts(fixture: interactive.ChatFixture) -> dict[str, int]:
    tables = (
        "baseline_authorizations",
        "baseline_owner_claims",
        "baseline_dispatch_claims",
        "baseline_resource_leases",
        "baseline_reports",
        "runs",
        "conversation_turns",
    )
    with sqlite3.connect(fixture.state_root / "state.db") as connection:
        return {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in tables
        }


def test_real_session_plans_confirms_runs_and_exits_without_history_reentry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target, command = fixture(tmp_path)
    monkeypatch.setattr(interactive, "_HELD_FAKE_ENTRY", _ENTRY)
    chat = interactive.InteractiveChat(target, held_role="baseline")
    try:
        chat.read_until("Type a goal")
        checkpoint = len(chat.output)
        chat.send(f"/baseline plan {command}")
        chat.read_until('"confirmation_code":', after=checkpoint)
        matched = re.search(r'"confirmation_code": "([0-9a-f]{16})"', chat.output[checkpoint:])
        assert matched is not None
        assert counts(target)["baseline_authorizations"] == 0
        checkpoint = len(chat.output)
        chat.send(f"/confirm {matched.group(1)}")
        chat.read_until("Authorized only", after=checkpoint)
        current = counts(target)
        assert current["baseline_authorizations"] == 1
        assert current["baseline_owner_claims"] == current["baseline_dispatch_claims"] == 0
        checkpoint = len(chat.output)
        chat.send("/baseline run")
        chat.read_until('"completion_assurance": "baseline_observation_only"', after=checkpoint)
        checkpoint = len(chat.output)
        chat.send("/baseline show")
        chat.read_until('"cleanup_complete": true', after=checkpoint)
        checkpoint = len(chat.output)
        chat.send(f"/confirm {matched.group(1)}")
        chat.read_until("consumed", after=checkpoint)
        chat.send("/exit")
        chat.finish()
        current = counts(target)
        assert current["baseline_owner_claims"] == current["baseline_dispatch_claims"] == 1
        assert current["baseline_reports"] == 1
        assert current["runs"] == current["conversation_turns"] == 0
        assert "Traceback" not in chat.output
        target.unchanged()
    finally:
        chat.close()


@pytest.mark.parametrize("ending", ["eof", "interrupt"])
def test_baseline_terminal_shutdown_cancels_baseline_not_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    ending: str,
) -> None:
    target, command = fixture(tmp_path)
    target.environment["FLEET_TEST_BASELINE_HOLD"] = "1"
    monkeypatch.setattr(interactive, "_HELD_FAKE_ENTRY", _ENTRY)
    chat = interactive.InteractiveChat(target, held_role="baseline")
    try:
        chat.read_until("Type a goal")
        checkpoint = len(chat.output)
        chat.send(f"/baseline plan {command}")
        chat.read_until('"confirmation_code":', after=checkpoint)
        matched = re.search(r'"confirmation_code": "([0-9a-f]{16})"', chat.output[checkpoint:])
        assert matched is not None
        checkpoint = len(chat.output)
        chat.send(f"/confirm {matched.group(1)}")
        chat.read_until("Authorized only", after=checkpoint)
        chat.send("/baseline run")
        # The process itself emits a bounded marker only after transport start;
        # it is not a model response or manufactured command receipt.
        chat.read_until("BASELINE_TRANSPORT_ENTERED")
        if ending == "eof":
            assert chat.process.stdin is not None
            chat.process.stdin.close()
        else:
            import signal

            chat.process.send_signal(signal.SIGINT)
        chat.finish()
        current = counts(target)
        assert current["runs"] == current["conversation_turns"] == 0
        assert current["baseline_owner_claims"] == current["baseline_dispatch_claims"] == 1
        assert current["baseline_reports"] == 1
        assert "cancelled_baseline_id" in chat.output
        assert "Traceback" not in chat.output
    finally:
        chat.close()


@pytest.mark.parametrize("operation", ["confirm", "run"])
def test_real_session_rejects_metadata_revision_written_by_another_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    target, command = fixture(tmp_path)
    monkeypatch.setattr(interactive, "_HELD_FAKE_ENTRY", _ENTRY)
    chat = interactive.InteractiveChat(target, held_role="baseline")
    try:
        chat.read_until("Type a goal")
        selected = re.search(r"Conversation: (conv_[0-9a-f]{32})", chat.output)
        assert selected is not None
        checkpoint = len(chat.output)
        chat.send(f"/baseline plan {command}")
        chat.read_until('"confirmation_code":', after=checkpoint)
        matched = re.search(r'"confirmation_code": "([0-9a-f]{16})"', chat.output[checkpoint:])
        assert matched is not None
        if operation == "run":
            checkpoint = len(chat.output)
            chat.send(f"/confirm {matched.group(1)}")
            chat.read_until("Authorized only", after=checkpoint)
        # This parent is a distinct process from the selected Session. Write a
        # valid metadata receipt, not a corrupt indexed column or a fabricated Turn.
        container = target.reopen()
        project = container.state.get_project_by_root(str(target.repository))
        assert project is not None
        store = container.conversation_store
        with store._transaction() as connection:
            conversation = store._conversation(connection, project.project_id, selected.group(1))
            store._write_conversation(
                connection,
                conversation.model_copy(
                    update={
                        "revision": conversation.revision + 1,
                        "updated_at": store.clock.now(),
                    }
                ),
            )
        checkpoint = len(chat.output)
        chat.send("/baseline run" if operation == "run" else f"/confirm {matched.group(1)}")
        chat.read_until(
            "metadata changed" if operation == "run" else "unavailable", after=checkpoint
        )
        current = counts(target)
        assert current["baseline_authorizations"] == (1 if operation == "run" else 0)
        assert current["baseline_owner_claims"] == current["baseline_dispatch_claims"] == 0
        assert current["runs"] == current["conversation_turns"] == 0
        chat.send("/exit")
        chat.finish()
    finally:
        chat.close()
