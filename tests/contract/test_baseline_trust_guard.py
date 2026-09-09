"""Watchdog processes, not event-loop timeouts, bound blocking-lock regressions."""

from __future__ import annotations

import multiprocessing
from multiprocessing.connection import Connection
from pathlib import Path
from threading import Event, Thread

import pytest

from agent_fleet.adapters.trust.filesystem import FilesystemTrustStore
from agent_fleet.domain.errors import FleetError
from agent_fleet.domain.security import Redactor
from agent_fleet.domain.trust import UserTrustPolicy
from agent_fleet.ports.trust_store import TrustReadGuard


def _guard_child(path: str, connection: Connection, mode: str) -> None:
    store = FilesystemTrustStore(Path(path), Redactor())
    other = FilesystemTrustStore(Path(path), Redactor())
    try:
        if mode == "fork":
            with store.read_guard() as guard:
                context = multiprocessing.get_context("fork")
                reader, writer = context.Pipe(duplex=False)
                child = context.Process(target=_inherited_guard, args=(guard, path, writer))
                try:
                    child.start()
                    writer.close()
                    assert reader.poll(3)
                    assert reader.recv() == "refused"
                    child.join(3)
                    assert child.exitcode == 0
                    guard.assert_current()
                finally:
                    if child.is_alive():
                        child.terminate()
                        child.join(3)
                    reader.close()
                    writer.close()
                    if child.exitcode is not None:
                        child.close()
            connection.send("complete")
            return
        if mode == "contended":
            try:
                with store.read_guard():
                    connection.send("unexpected")
            except FleetError:
                connection.send("refused")
            return
        with store.read_guard() as guard:
            guard.assert_current()
            for target in (store, other):
                try:
                    with target.read_guard():
                        raise AssertionError("nested guard was accepted")
                except FleetError:
                    pass
                try:
                    target.save(target.load(), expected_revision=0)
                    raise AssertionError("save inside a guard was accepted")
                except FleetError:
                    pass
            done = Event()
            results: list[str] = []

            def save() -> None:
                try:
                    other.save(other.load(), expected_revision=0)
                    results.append("unexpected")
                except FleetError:
                    results.append("refused")
                finally:
                    done.set()

            thread = Thread(target=save, daemon=True)
            thread.start()
            assert done.wait(2)
            thread.join(2)
            assert results == ["refused"]
            assert not store.path.exists()
        try:
            guard.assert_current()
            raise AssertionError("expired guard was accepted")
        except FleetError:
            pass
        assert store.save(UserTrustPolicy(), expected_revision=0).revision == 1
        connection.send("complete")
    except BaseException:
        connection.send("failed")
    finally:
        connection.close()


def _inherited_guard(guard: TrustReadGuard, path: str, connection: Connection) -> None:
    refused = 0
    try:
        try:
            guard.assert_current()
        except FleetError:
            refused += 1
        try:
            FilesystemTrustStore(Path(path), Redactor()).save(
                UserTrustPolicy(), expected_revision=0
            )
        except FleetError:
            refused += 1
        connection.send("refused" if refused == 2 else "unexpected")
    finally:
        connection.close()


def _watchdog(path: Path, mode: str) -> str:
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe(duplex=False)
    process = context.Process(target=_guard_child, args=(str(path), child, mode))
    try:
        process.start()
        child.close()
        assert parent.poll(10), "lock watchdog expired"
        result = parent.recv()
        process.join(5)
        assert process.exitcode == 0
        assert type(result) is str
        return result
    finally:
        if process.is_alive():
            process.terminate()
            process.join(5)
        parent.close()
        child.close()
        if process.exitcode is not None:
            process.close()


def test_same_process_guard_save_and_thread_nesting_are_fail_fast(tmp_path: Path) -> None:
    assert _watchdog(tmp_path / "trust" / "policy.json", "nested") == "complete"


def test_external_guard_contention_is_fail_fast(tmp_path: Path) -> None:
    path = tmp_path / "trust" / "policy.json"
    store = FilesystemTrustStore(path, Redactor())
    with store.read_guard():
        assert _watchdog(path, "contended") == "refused"


def test_fork_cannot_inherit_guard_or_block_saving_behind_it(tmp_path: Path) -> None:
    assert _watchdog(tmp_path / "trust" / "policy.json", "fork") == "complete"


def test_guard_is_immutable_and_absent_load_stays_nonmutating(tmp_path: Path) -> None:
    path = tmp_path / "trust" / "policy.json"
    store = FilesystemTrustStore(path, Redactor())
    assert store.load() == UserTrustPolicy() and not path.parent.exists()
    with store.read_guard() as guard:
        assert type(guard.canonical_policy_utf8) is bytes
        fresh = UserTrustPolicy.model_validate_json(guard.canonical_policy_utf8)
        fresh.rules.clear()
        assert not path.exists()
        assert [item.name for item in path.parent.iterdir()] == [".policy.json.lock"]
        digest = guard.policy_sha256
    with store.read_guard(expected_sha256=digest) as guard:
        guard.assert_current()
    with pytest.raises(FleetError), store.read_guard(expected_sha256="0" * 64):
        raise AssertionError("stale hash accepted")
    assert not path.exists()


@pytest.mark.parametrize("replace", ["policy", "lock"])
def test_visible_host_replacement_is_rejected_not_aba_immunity(
    tmp_path: Path, replace: str
) -> None:
    path = tmp_path / "trust" / "policy.json"
    store = FilesystemTrustStore(path, Redactor())
    store.save(UserTrustPolicy(), expected_revision=0)
    with pytest.raises(FleetError), store.read_guard() as guard:
        if replace == "policy":
            changed = store.load().model_dump(mode="json")
            changed["revision"] = 2
            import json

            path.write_text(json.dumps(changed))
        else:
            lock = path.parent / ".policy.json.lock"
            lock.rename(path.parent / ".original-lock")
            lock.touch(mode=0o600)
        guard.assert_current()


def test_guard_exception_releases_without_policy_write(tmp_path: Path) -> None:
    store = FilesystemTrustStore(tmp_path / "trust" / "policy.json", Redactor())
    with pytest.raises(RuntimeError), store.read_guard():
        raise RuntimeError("synthetic")
    assert store.save(UserTrustPolicy(), expected_revision=0).revision == 1
