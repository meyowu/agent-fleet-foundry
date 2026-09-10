"""Actual Workflow/database capture, source locking and clean-process boundaries."""

from __future__ import annotations

import asyncio
import gc
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import FleetHarness
from evaluation_execution_fixtures import execution_fixture
from test_evaluation_observation_workflow import attempt_id, failed, service
from test_evaluation_observation_workflow import (
    observation_children_are_reaped as observation_children_are_reaped,
)

from agent_fleet.adapters.persistence import evaluation_capture as capture

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def physical_snapshot(root: Path) -> str:
    # Source reads/closes live in a separate process, including the test oracle.
    script = (
        "import hashlib,json,sys;from pathlib import Path;root=Path(sys.argv[1]);"
        "print(json.dumps({str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() "
        "for p in root.rglob('*') if p.is_file()},sort_keys=True))"
    )
    return subprocess.run(
        [sys.executable, "-I", "-B", "-c", script, str(root)],
        check=True,
        capture_output=True,
        text=True,
        close_fds=True,
        env={"LANG": "C", "LC_ALL": "C"},
        timeout=10,
    ).stdout


@pytest.mark.parametrize("journal", ["DELETE", "WAL"])
async def test_actual_capture_preserves_parent_sqlite_lock_and_every_source_byte(
    harness: FleetHarness, journal: str
) -> None:
    fixture, _ = await failed(harness)
    selected = attempt_id(harness)
    # Fixture helpers use temporary sqlite3 connection context managers, which
    # commit but do not close. Drop their unreachable cycles before selecting
    # DELETE mode; the live connection below remains strongly held throughout.
    gc.collect()
    connection = sqlite3.connect(harness.container.state.database_path, isolation_level=None)
    try:
        connection.execute(f"PRAGMA journal_mode={journal}")
        connection.execute("BEGIN IMMEDIATE")
        before = physical_snapshot(harness.state_root)
        observed = service(harness).inspect_attempt(fixture.manifest.campaign_id, selected)
        assert observed.state == "failed", observed
        assert physical_snapshot(harness.state_root) == before
        contender = (
            "import sqlite3,sys;db=sqlite3.connect(sys.argv[1],timeout=0);"
            "\ntry: db.execute('BEGIN IMMEDIATE')"
            "\nexcept sqlite3.OperationalError: print('busy')"
            "\nelse: print('admitted');db.rollback()"
            "\nfinally: db.close()"
        )
        result = await asyncio.to_thread(
            subprocess.run,
            [
                sys.executable,
                "-I",
                "-B",
                "-c",
                contender,
                str(harness.container.state.database_path),
            ],
            check=True,
            capture_output=True,
            text=True,
            close_fds=True,
            env={"LANG": "C", "LC_ALL": "C"},
            timeout=10,
        )
        assert result.stdout.strip() == "busy"
    finally:
        connection.rollback()
        connection.close()


@pytest.mark.parametrize("wal_state", ["committed", "uncommitted", "partial-tail"])
async def test_sqlite_interprets_hot_wal_without_source_sidecar_changes(
    harness: FleetHarness, wal_state: str
) -> None:
    fixture, run = await failed(harness)
    selected = attempt_id(harness)
    observer = service(harness)
    original = observer.inspect_attempt(fixture.manifest.campaign_id, selected)
    database = harness.container.state.database_path
    connection = sqlite3.connect(database)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA wal_autocheckpoint=0")
        connection.execute("PRAGMA cache_size=1")
        raw = connection.execute(
            "SELECT data_json FROM run_events WHERE run_id=? AND event_type='run.failed'",
            (run.run_id,),
        ).fetchone()[0]
        payload = json.loads(raw)
        payload["payload"]["message"] = "retained fixture " + "x" * 200_000
        connection.execute(
            "UPDATE run_events SET data_json=? WHERE run_id=? AND event_type='run.failed'",
            (json.dumps(payload), run.run_id),
        )
        if wal_state != "uncommitted":
            connection.commit()
        wal = database.with_name(database.name + "-wal")
        assert wal.stat().st_size > 32
        if wal_state == "partial-tail":
            with wal.open("ab") as stream:
                stream.write(b"partial frame tail")
        before = physical_snapshot(harness.state_root)
        observed = observer.inspect_attempt(fixture.manifest.campaign_id, selected)
        assert observed.state == "failed", observed
        assert (observed == original) == (wal_state == "uncommitted")
        assert physical_snapshot(harness.state_root) == before
    finally:
        connection.rollback()
        connection.close()


def instrumented_child(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch, code: str
) -> list[tuple[subprocess.Popen[bytes], Path]]:
    script = harness.root / "fixed-capture-probe.py"
    package = str(Path(capture.__file__).resolve().parents[3])
    script.write_text(
        "import sys,os,sqlite3\nfrom pathlib import Path\n"
        f"sys.path.insert(0,{package!r})\n"
        "from agent_fleet.adapters.persistence import evaluation_capture as capture\n"
        + code
        + "\ncapture.child_main()\n"
    )
    children: list[tuple[subprocess.Popen[bytes], Path]] = []

    def spawn(stage: Path) -> subprocess.Popen[bytes]:
        child = subprocess.Popen(
            [sys.executable, "-I", "-B", str(script)],
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


def drained(children: list[tuple[subprocess.Popen[bytes], Path]]) -> None:
    assert len(children) == 1
    child, stage = children[0]
    assert child.poll() is not None and not stage.exists()
    with pytest.raises(ProcessLookupError):
        os.kill(child.pid, 0)


@pytest.mark.parametrize("target", ["database", "artifact"])
async def test_transient_source_file_aba_is_rejected_after_original_namespace_restored(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch, target: str
) -> None:
    fixture = execution_fixture(harness)
    run = await fixture.execute()
    assert run.config_snapshot_artifact_id is not None
    metadata = harness.container.state.get_artifact(run.config_snapshot_artifact_id)
    path = (
        harness.container.state.database_path
        if target == "database"
        else harness.state_root / "artifacts" / metadata.content_ref
    )
    selected = attempt_id(harness)
    original = path.read_bytes()
    code = f"""
target = Path({str(path)!r})
original = capture.DescriptorCapture._read
fired = False
def swapped(self, path, parent, fd, before):
    global fired
    result = original(self, path, parent, fd, before)
    if path == target and not fired:
        fired = True
        retained = path.with_name(path.name + '.retained-test')
        path.rename(retained)
        try:
            path.symlink_to(retained)
        finally:
            path.unlink()
            retained.rename(path)
    return result
capture.DescriptorCapture._read = swapped
"""
    children = instrumented_child(harness, monkeypatch, code)
    observed = service(harness).inspect_attempt(fixture.manifest.campaign_id, selected)
    assert observed.state == "corrupt", observed
    assert path.read_bytes() == original and not path.is_symlink()
    drained(children)


async def test_checkpoint_between_capture_passes_is_rejected(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture, _ = await failed(harness)
    selected = attempt_id(harness)
    database = harness.container.state.database_path
    connection = sqlite3.connect(database)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA wal_autocheckpoint=0")
        connection.execute("UPDATE runs SET data_json=data_json")
        connection.commit()
        code = f"""
original = capture.DescriptorCapture.second
def checkpoint(self):
    connection = sqlite3.connect({str(database)!r}, timeout=0)
    try:
        connection.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchall()
    finally:
        connection.close()
    return original(self)
capture.DescriptorCapture.second = checkpoint
"""
        children = instrumented_child(harness, monkeypatch, code)
        assert (
            service(harness).inspect_attempt(fixture.manifest.campaign_id, selected).state
            == "corrupt"
        )
        drained(children)
    finally:
        connection.close()


async def test_nonempty_rollback_journal_is_not_recovered_or_modified(
    harness: FleetHarness,
) -> None:
    fixture, _ = await failed(harness)
    selected = attempt_id(harness)
    database = harness.container.state.database_path
    journal = database.with_name(database.name + "-journal")
    journal.write_bytes(b"not safe to replay")
    before = physical_snapshot(harness.state_root)
    assert (
        service(harness).inspect_attempt(fixture.manifest.campaign_id, selected).state == "corrupt"
    )
    assert physical_snapshot(harness.state_root) == before


async def test_fixed_child_receives_no_credentials_provider_environment_or_parent_fd(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture, _ = await failed(harness)
    selected = attempt_id(harness)
    monkeypatch.setenv("OPENAI_API_KEY", "SYNTHETIC_NOT_A_CREDENTIAL")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://not-a-provider.invalid")
    fd = os.open(harness.root / "parent-only", os.O_CREAT | os.O_RDWR, 0o600)
    os.set_inheritable(fd, True)
    try:
        code = f"""
assert not {{'OPENAI_API_KEY','OPENAI_BASE_URL','PYTHONPATH'}}.intersection(os.environ)
try:
    os.fstat({fd})
except OSError:
    pass
else:
    raise AssertionError('inherited parent descriptor')
original = capture._inspect
def private_only(request):
    stage = Path(request['stage'])
    assert stage.stat().st_mode & 0o777 == 0o700
    connection = sqlite3.connect
    opens = []
    def private_connection(path, *args, **kwargs):
        assert Path(path) == stage / 'state.db'
        assert not (stage / 'state.db-shm').exists()
        assert all(item.stat().st_mode & 0o777 == 0o600 for item in stage.iterdir())
        opens.append(True)
        return connection(path, *args, **kwargs)
    sqlite3.connect = private_connection
    try:
        result = original(request)
        assert len(opens) == 1
        assert all(item.stat().st_mode & 0o777 == 0o600 for item in stage.iterdir())
        return result
    finally:
        sqlite3.connect = connection
capture._inspect = private_only
"""
        children = instrumented_child(harness, monkeypatch, code)
        observed = service(harness).inspect_attempt(fixture.manifest.campaign_id, selected)
        assert observed.state == "failed", observed
        drained(children)
    finally:
        os.close(fd)
