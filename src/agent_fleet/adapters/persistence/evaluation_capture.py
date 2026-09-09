"""Fixed clean-child evidence capture; never open a source SQLite file in the parent."""

from __future__ import annotations

import asyncio
import json
import os
import re
import selectors
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from contextlib import ExitStack
from pathlib import Path
from typing import Any

MAX_FILE = 32 * 1024 * 1024
MAX_READ = 128 * 1024 * 1024
MAX_INPUT = 16_384
MAX_OUTPUT = 1_048_576
MAX_STDERR = 4096
CHILD_TIMEOUT = 15.0


class CaptureRejected(Exception):
    """Internal fixed failure: no untrusted detail crosses the child boundary."""


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CaptureRejected()
        result[key] = value
    return result


def _path(value: object) -> Path:
    if not isinstance(value, str) or len(value) > 4096 or "\x00" in value:
        raise CaptureRejected()
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise CaptureRejected()
    return path


def _identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
        value.st_mode,
        value.st_nlink,
    )


class DescriptorCapture:
    """Retain all source descriptors through two byte-identical bounded passes.

    Only the fixed child instantiates this class on a source database. Raw close
    in a live parent can release that parent's unrelated POSIX SQLite locks.
    """

    def __init__(self, exits: ExitStack) -> None:
        self.exits = exits
        self.directories: dict[Path, int] = {}
        self.chain: list[tuple[int, str, int, tuple[int, ...]]] = []
        self.files: dict[Path, tuple[int, int | None, tuple[int, ...] | None, bytes | None]] = {}
        self.read_bytes = 0

    def directory(self, path: Path) -> int:
        _path(str(path))
        if path in self.directories:
            return self.directories[path]
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        if path == Path("/"):
            fd = os.open("/", flags)
        else:
            parent = self.directory(path.parent)
            fd = os.open(path.name, flags, dir_fd=parent)
            self.chain.append((parent, path.name, fd, _identity(os.fstat(fd))))
        self.exits.callback(os.close, fd)
        self.directories[path] = fd
        return fd

    def check(self) -> None:
        for parent, name, fd, before in self.chain:
            if (
                _identity(os.stat(name, dir_fd=parent, follow_symlinks=False)) != before
                or _identity(os.fstat(fd)) != before
            ):
                raise CaptureRejected()

    def _read(self, path: Path, parent: int, fd: int, before: tuple[int, ...]) -> bytes:
        if _identity(os.fstat(fd)) != before:
            raise CaptureRejected()
        content = bytearray()
        while len(content) <= MAX_FILE:
            part = os.pread(fd, min(65536, MAX_FILE + 1 - len(content)), len(content))
            self.read_bytes += len(part)
            if self.read_bytes > MAX_READ:
                raise CaptureRejected()
            if not part:
                break
            content.extend(part)
        if (
            len(content) != before[2]
            or len(content) > MAX_FILE
            or _identity(os.fstat(fd)) != before
            or _identity(os.stat(path.name, dir_fd=parent, follow_symlinks=False)) != before
        ):
            raise CaptureRejected()
        self.check()
        return bytes(content)

    def first(self, path: Path, *, required: bool = True) -> bytes | None:
        if path in self.files:
            return self.files[path][3]
        if len(self.files) >= 259:
            raise CaptureRejected()
        parent = self.directory(path.parent)
        try:
            fd = os.open(
                path.name,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                dir_fd=parent,
            )
        except FileNotFoundError:
            if required:
                raise CaptureRejected() from None
            self.files[path] = (parent, None, None, None)
            return None
        self.exits.callback(os.close, fd)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_FILE:
            raise CaptureRejected()
        before = _identity(info)
        content = self._read(path, parent, fd, before)
        self.files[path] = (parent, fd, before, content)
        return content

    def second(self) -> None:
        for path, (parent, fd, before, content) in self.files.items():
            if fd is None:
                try:
                    os.stat(path.name, dir_fd=parent, follow_symlinks=False)
                except FileNotFoundError:
                    continue
                raise CaptureRejected()
            assert before is not None
            if self._read(path, parent, fd, before) != content:
                raise CaptureRejected()
        self.check()

    def origin(self, path: Path) -> tuple[int, int]:
        before = self.files[path][2]
        if before is None:
            raise CaptureRejected()
        return before[0], before[1]


def _exclusive(path: Path, content: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(content)


def _inspect(request: dict[str, str]) -> bytes:
    # These imports are product-owned validators; they never initialize a container.
    from agent_fleet.adapters.artifacts.local import LocalArtifactStore
    from agent_fleet.adapters.persistence.evaluation_evidence import (
        SqliteEvaluationEvidence,
        _NoElapsedClock,
    )
    from agent_fleet.adapters.persistence.sqlite import SUPPORTED_SCHEMA_VERSION, SqliteStateStore
    from agent_fleet.adapters.system import UuidIdGenerator
    from agent_fleet.domain.security import Redactor

    source = _path(request["database_path"])
    artifact_root = _path(request["artifact_root"])
    stage = _path(request["stage"])
    info = stage.lstat()
    if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o700:
        raise CaptureRejected()
    with ExitStack() as exits:
        capture = DescriptorCapture(exits)
        database = capture.first(source)
        wal = capture.first(source.with_name(source.name + "-wal"), required=False)
        journal = capture.first(source.with_name(source.name + "-journal"), required=False)
        if database is None or journal:
            raise CaptureRejected()
        private = stage / "state.db"
        _exclusive(private, database)
        if wal is not None:
            _exclusive(stage / "state.db-wal", wal)
        connection = sqlite3.connect(private, timeout=0)
        exits.callback(connection.close)
        connection.row_factory = sqlite3.Row
        connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 2_097_152)
        connection.setlimit(sqlite3.SQLITE_LIMIT_ATTACHED, 0)
        connection.execute("PRAGMA temp_store=MEMORY")
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.execute("PRAGMA query_only=ON")
        if [tuple(row) for row in connection.execute("PRAGMA quick_check")] != [("ok",)]:
            raise CaptureRejected()
        connection.execute("BEGIN")

        def authorize(
            operation: int,
            first: str | None,
            second: str | None,
            database_name: str | None,
            source_name: str | None,
        ) -> int:
            if source_name is not None:
                return sqlite3.SQLITE_DENY
            if operation in {
                sqlite3.SQLITE_SELECT,
                sqlite3.SQLITE_READ,
                sqlite3.SQLITE_TRANSACTION,
            }:
                return sqlite3.SQLITE_OK
            if operation == sqlite3.SQLITE_FUNCTION and second in {
                "count",
                "sum",
                "max",
                "min",
                "coalesce",
                "length",
                "json_extract",
                "instr",
            }:
                return sqlite3.SQLITE_OK
            return sqlite3.SQLITE_DENY

        connection.set_authorizer(authorize)
        versions = [
            row[0]
            for row in connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version LIMIT ?",
                (SUPPORTED_SCHEMA_VERSION + 2,),
            )
        ]
        if versions != list(range(1, SUPPORTED_SCHEMA_VERSION + 1)):
            raise CaptureRejected()
        state = SqliteStateStore(private, _NoElapsedClock(), UuidIdGenerator(), Redactor())
        evidence = SqliteEvaluationEvidence(
            state, LocalArtifactStore(stage / "unused"), artifact_root
        )
        evidence._source_identity = capture.origin(source)
        evidence._captured_artifact = lambda relative: capture.first(artifact_root / relative)
        snapshot = evidence._database(connection, request["campaign_id"], request["attempt_id"])
        observation = evidence._observe(connection, snapshot, request["attempt_id"])
        capture.second()
        result = observation.model_dump_json().encode("utf-8")
        if len(result) > MAX_OUTPUT:
            raise CaptureRejected()
        return result


def child_main() -> None:
    result = b'{"capture_rejected":true}'
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT + 1)
        if len(raw) > MAX_INPUT:
            raise CaptureRejected()
        request = json.loads(raw, object_pairs_hook=_unique_object)
        if (
            not isinstance(request, dict)
            or set(request)
            != {
                "database_path",
                "artifact_root",
                "stage",
                "campaign_id",
                "attempt_id",
            }
            or not all(isinstance(value, str) for value in request.values())
        ):
            raise CaptureRejected()
        for name, prefix in (("campaign_id", "campaign"), ("attempt_id", "attempt")):
            if re.fullmatch(prefix + r"_[0-9a-f]{32}", request[name]) is None:
                raise CaptureRejected()
        result = _inspect(request)
    except Exception:
        # Fixed child projection is deliberate; do not expose raw DB/path/exception data.
        pass
    sys.stdout.buffer.write(result)


def _spawn_capture(stage: Path) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [sys.executable, "-I", "-B", str(Path(__file__).with_name("evaluation_capture.py"))],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=stage,
        env={"LANG": "C", "LC_ALL": "C"},
        close_fds=True,
    )


def _remove_stage(stage: Path) -> None:
    shutil.rmtree(stage)


def capture_observation(
    database_path: Path,
    artifact_root: Path,
    campaign_id: str,
    attempt_id: str,
    cancelled: threading.Event | None = None,
) -> bytes | None:
    """One finite process; bound both pipes as bytes arrive, then reap and remove stage."""
    stage = Path(tempfile.mkdtemp(prefix="agent-fleet-observation-")).resolve()
    process: subprocess.Popen[bytes] | None = None
    result: bytes | None = None
    try:
        request = {
            "database_path": str(database_path.absolute()),
            "artifact_root": str(artifact_root.absolute()),
            "stage": str(stage),
            "campaign_id": campaign_id,
            "attempt_id": attempt_id,
        }
        payload = json.dumps(request, separators=(",", ":")).encode("utf-8")
        if len(payload) > MAX_INPUT:
            raise CaptureRejected()
        process = _spawn_capture(stage)
        assert (
            process.stdin is not None and process.stdout is not None and process.stderr is not None
        )
        deadline = time.monotonic() + CHILD_TIMEOUT
        output = bytearray()
        errors = 0
        written = 0
        with selectors.DefaultSelector() as selected:
            for stream, mode, label in (
                (process.stdin, selectors.EVENT_WRITE, "input"),
                (process.stdout, selectors.EVENT_READ, "output"),
                (process.stderr, selectors.EVENT_READ, "error"),
            ):
                os.set_blocking(stream.fileno(), False)
                selected.register(stream, mode, label)
            while selected.get_map() or process.poll() is None:
                if (cancelled is not None and cancelled.is_set()) or time.monotonic() >= deadline:
                    raise CaptureRejected()
                for key, _ in selected.select(min(0.05, max(0.0, deadline - time.monotonic()))):
                    fd = key.fd
                    if key.data == "input":
                        written += os.write(fd, payload[written:])
                        if written == len(payload):
                            selected.unregister(key.fileobj)
                            process.stdin.close()
                    else:
                        chunk = os.read(fd, 65536)
                        if not chunk:
                            selected.unregister(key.fileobj)
                        elif key.data == "output":
                            if len(output) + len(chunk) > MAX_OUTPUT:
                                raise CaptureRejected()
                            output.extend(chunk)
                        else:
                            errors += len(chunk)
                            if errors > MAX_STDERR:
                                raise CaptureRejected()
            if process.wait(timeout=max(0.001, deadline - time.monotonic())) != 0 or errors:
                raise CaptureRejected()
            result = bytes(output)
            json.loads(result, object_pairs_hook=_unique_object)
    except (OSError, ValueError, CaptureRejected, subprocess.SubprocessError):
        result = None
    finally:
        cleanup_failed = False
        if process is not None:
            try:
                if process.poll() is None:
                    process.kill()
            except (OSError, subprocess.SubprocessError):
                cleanup_failed = True
            try:
                process.wait(timeout=10)
            except (OSError, subprocess.SubprocessError):
                cleanup_failed = True
            for remaining_stream in (process.stdin, process.stdout, process.stderr):
                if remaining_stream is not None:
                    try:
                        remaining_stream.close()
                    except OSError:
                        cleanup_failed = True
        try:
            _remove_stage(stage)
        except OSError:
            cleanup_failed = True
        if cleanup_failed:
            result = None
    return result


async def capture_observation_async(
    operation: Callable[[threading.Event], Any],
) -> Any:
    """Keep the actual child-owning thread alive until cleanup survives repeat cancel."""
    cancelled = threading.Event()
    owner = asyncio.create_task(asyncio.to_thread(operation, cancelled))
    cancellation: asyncio.CancelledError | None = None
    while not owner.done():
        try:
            await asyncio.wait({owner})
        except asyncio.CancelledError as error:
            cancelled.set()
            if cancellation is None:
                cancellation = error
    result = owner.result()
    if cancellation is not None:
        raise cancellation
    return result


if __name__ == "__main__":
    # -I ignores CWD/PYTHONPATH. Only this fixed installed package root is added.
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    child_main()
