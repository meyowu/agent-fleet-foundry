"""Restrictive, versioned trust files with descriptor-relative atomic publication."""

from __future__ import annotations

import json
import os
import secrets
import stat
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

import yaml
from pydantic import ValidationError
from yaml.nodes import MappingNode
from yaml.tokens import AliasToken, AnchorToken

from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.security import Redactor, sha256_bytes
from agent_fleet.domain.trust import UserTrustPolicy
from agent_fleet.ports.trust_store import TrustReadGuard

try:
    import fcntl
except ImportError:  # pragma: no cover - unsupported platforms fail closed
    fcntl = None  # type: ignore[assignment]

_MAX_POLICY_BYTES = 2_000_000
_ReservationKey = tuple[int, int, str, int, int]
_reservations_lock = Lock()
_reservations: dict[_ReservationKey, dict[object, str]] = {}


def _after_fork() -> None:
    # A fork cannot inherit the parent's Python-thread bookkeeping as authority.
    global _reservations_lock, _reservations
    _reservations_lock = Lock()
    _reservations = {key: {object(): "inherited"} for key in _reservations}


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_after_fork)


@contextmanager
def _reservation(key: _ReservationKey, kind: str) -> Iterator[None]:
    token = object()
    if not _reservations_lock.acquire(blocking=False):
        raise _conflict()
    try:
        related = [
            (other, tokens) for other, tokens in _reservations.items() if other[:3] == key[:3]
        ]
        if any(
            other != key
            or kind == "guard"
            or "guard" in tokens.values()
            or "inherited" in tokens.values()
            for other, tokens in related
        ):
            raise _conflict()
        _reservations.setdefault(key, {})[token] = kind
    finally:
        _reservations_lock.release()
    try:
        yield
    finally:
        # Bookkeeping only: no I/O, flock or user code while this mutex is held.
        with _reservations_lock:
            tokens = _reservations.get(key)
            if tokens is not None:
                tokens.pop(token, None)
                if not tokens:
                    del _reservations[key]


@dataclass(frozen=True)
class _TrustReadGuard:
    canonical_policy_utf8: bytes
    policy_sha256: str
    _check: Callable[[], None]

    def assert_current(self) -> None:
        self._check()


class _UniqueSafeLoader(yaml.SafeLoader):
    def construct_mapping(self, node: MappingNode, deep: bool = False) -> dict[object, object]:
        result: dict[object, object] = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str) or key in result:
                raise ValueError("trust mappings require unique string keys")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


class FilesystemTrustStore:
    """Construction and absent-file reads create no files or directories.

    Successful saves advance the revision exactly once and retain the validated
    prior revision in an immutable sibling backup. A failed/uncertain publish is
    reconciled by reading the current revision; backups never activate themselves.
    """

    def __init__(self, path: Path, redactor: Redactor) -> None:
        self.path = path.absolute()
        self.redactor = redactor

    def load(self) -> UserTrustPolicy:
        try:
            with self._directory(create=False) as descriptor:
                if descriptor is None:
                    return UserTrustPolicy()
                policy, _ = self._read_policy(descriptor, self.path.name)
                self._check_directory(descriptor)
                return policy if policy is not None else UserTrustPolicy()
        except FleetError:
            raise
        except (OSError, ValueError, TypeError, RecursionError, yaml.YAMLError):
            raise _unavailable() from None

    @contextmanager
    def read_guard(self, *, expected_sha256: str | None = None) -> Iterator[TrustReadGuard]:
        """Fail-fast cooperating read reservation; may create only directory/lock.

        Caller lock order is project publication, then this guard, then short
        SQLite transactions. No policy revision/backup is written by the guard.
        Ordinary load stays nonmutating. A retained guard excludes all same-
        process saves before they can block on its flock, including other store
        instances. Cross-process legacy saves still use their existing flock.
        """
        active = False
        creator_pid = os.getpid()
        try:
            if fcntl is None:
                raise _unavailable()
            if expected_sha256 is not None and (
                type(expected_sha256) is not str
                or len(expected_sha256) != 64
                or any(char not in "0123456789abcdef" for char in expected_sha256)
            ):
                raise _conflict()
            with self._directory(create=True) as descriptor:
                if descriptor is None:
                    raise _unavailable()
                name = f".{self.path.name}.lock"
                lock = self._open_lock(descriptor, name)
                try:
                    opened = os.fstat(lock)
                    _validate_file(opened)
                    directory = os.fstat(descriptor)
                    key = (*_binding(directory), name.casefold(), *_binding(opened))
                    with _reservation(key, "guard"):
                        try:
                            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        except BlockingIOError:
                            raise _conflict() from None
                        self._assert_binding(descriptor, name, opened)
                        self._check_directory(descriptor)

                        def policy_bytes() -> bytes:
                            policy, _ = self._read_policy(descriptor, self.path.name)
                            checked = UserTrustPolicy.model_validate_json(
                                (
                                    policy if policy is not None else UserTrustPolicy()
                                ).model_dump_json()
                            )
                            content = checked.model_dump(mode="json")
                            if self.redactor.contains_secret_data(content):
                                raise _unavailable()
                            raw = json.dumps(
                                content,
                                sort_keys=True,
                                separators=(",", ":"),
                                ensure_ascii=False,
                                allow_nan=False,
                            ).encode("utf-8")
                            if len(raw) > _MAX_POLICY_BYTES:
                                raise _unavailable()
                            return raw

                        raw = policy_bytes()
                        digest = sha256_bytes(raw)
                        if expected_sha256 is not None and digest != expected_sha256:
                            raise _conflict()
                        active = True

                        def check() -> None:
                            if not active or os.getpid() != creator_pid:
                                raise _unavailable()
                            self._assert_binding(descriptor, name, opened)
                            self._check_directory(descriptor)
                            if policy_bytes() != raw:
                                raise _conflict()
                            self._assert_binding(descriptor, name, opened)
                            self._check_directory(descriptor)

                        guard = _TrustReadGuard(raw, digest, check)
                        check()
                        yield guard
                        check()
                finally:
                    active = False
                    os.close(lock)
        except FleetError:
            raise
        except (OSError, ValueError, TypeError, RecursionError, yaml.YAMLError):
            raise _unavailable() from None

    def save(self, policy: UserTrustPolicy, *, expected_revision: int) -> UserTrustPolicy:
        # Validate before creating even the lock directory. Never repair policy
        # by redacting it: redaction could silently change an authorization scope.
        try:
            if type(expected_revision) is not int or expected_revision < 0:
                raise ValueError("expected revision must be a nonnegative integer")
            checked = self._validate(policy.model_dump(mode="json"))
            if checked.revision != expected_revision:
                raise _conflict()
            updated = self._validate(
                {**checked.model_dump(mode="json"), "revision": expected_revision + 1}
            )
            encoded = _encode(updated)
            if len(encoded) > _MAX_POLICY_BYTES:
                raise ValueError("trust policy exceeds its byte limit")
            with self._directory(create=True) as descriptor:
                if descriptor is None:
                    raise _unavailable()
                with self._locked(descriptor):
                    current, original = self._read_policy(descriptor, self.path.name)
                    current = current if current is not None else UserTrustPolicy()
                    if current.revision != expected_revision:
                        raise _conflict()
                    self._check_directory(descriptor)
                    if original is not None:
                        backup_name = f"{self.path.name}.revision-{current.revision:020d}.json"
                        backup, _ = self._read_policy(descriptor, backup_name)
                        if backup is not None and backup != current:
                            raise _unavailable()
                        if backup is None:
                            self._atomic_write(descriptor, backup_name, _encode(current), None)
                    self._atomic_write(descriptor, self.path.name, encoded, original)
                    published, _ = self._read_policy(descriptor, self.path.name)
                    if published != updated:
                        raise _unavailable()
                    return updated
        except FleetError:
            raise
        except (OSError, ValueError, TypeError, RecursionError, yaml.YAMLError):
            raise _unavailable() from None

    def _validate(self, content: object) -> UserTrustPolicy:
        if self.redactor.contains_secret_data(content):
            raise _unavailable()
        try:
            return UserTrustPolicy.model_validate(content)
        except ValidationError:
            raise _unavailable() from None

    def _read_policy(
        self, descriptor: int, name: str
    ) -> tuple[UserTrustPolicy | None, os.stat_result | None]:
        try:
            before = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
        except FileNotFoundError:
            return None, None
        _validate_file(before)
        if before.st_size > _MAX_POLICY_BYTES:
            raise _unavailable()
        file_descriptor = os.open(
            name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor
        )
        try:
            opened = os.fstat(file_descriptor)
            _validate_file(opened)
            if _binding(opened) != _binding(before):
                raise _unavailable()
            chunks: list[bytes] = []
            remaining = _MAX_POLICY_BYTES + 1
            while remaining:
                chunk = os.read(file_descriptor, min(65_536, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            raw = b"".join(chunks)
            after = os.fstat(file_descriptor)
            if (
                len(raw) > _MAX_POLICY_BYTES
                or _snapshot(opened) != _snapshot(after)
                or len(raw) != after.st_size
            ):
                raise _unavailable()
            self._assert_binding(descriptor, name, after)
        finally:
            os.close(file_descriptor)
        if self.redactor.contains_secret(raw):
            raise _unavailable()
        text = raw.decode("utf-8")
        if any(isinstance(token, AliasToken | AnchorToken) for token in yaml.scan(text)):
            raise _unavailable()
        loaded: object = yaml.load(text, Loader=_UniqueSafeLoader)
        return self._validate(loaded), after

    @contextmanager
    def _directory(self, *, create: bool) -> Iterator[int | None]:
        if (
            fcntl is None
            or not hasattr(os, "O_NOFOLLOW")
            or not hasattr(os, "O_DIRECTORY")
            or not hasattr(os, "geteuid")
            or ".." in self.path.parts
            or self.path.name in {"", ".", ".."}
            or len(self.path.name) > 128
        ):
            raise _unavailable()
        descriptor = os.open(self.path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            parts = self.path.parent.parts[1:]
            for index, part in enumerate(parts):
                try:
                    child = os.open(
                        part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor
                    )
                except FileNotFoundError:
                    if not create:
                        yield None
                        return
                    with suppress(FileExistsError):
                        os.mkdir(part, 0o700, dir_fd=descriptor)
                    child = os.open(
                        part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor
                    )
                try:
                    info = os.fstat(child)
                    _validate_directory(info, private=index == len(parts) - 1)
                    named = os.stat(part, dir_fd=descriptor, follow_symlinks=False)
                    if _binding(named) != _binding(info):
                        raise _unavailable()
                except BaseException:
                    os.close(child)
                    raise
                os.close(descriptor)
                descriptor = child
            if not parts:
                raise _unavailable()
            yield descriptor
        finally:
            os.close(descriptor)

    def _check_directory(self, descriptor: int) -> None:
        with self._directory(create=False) as current:
            if current is None or _binding(os.fstat(current)) != _binding(os.fstat(descriptor)):
                raise _unavailable()

    @contextmanager
    def _locked(self, descriptor: int) -> Iterator[None]:
        if fcntl is None:
            raise _unavailable()
        name = f".{self.path.name}.lock"
        lock = self._open_lock(descriptor, name)
        try:
            opened = os.fstat(lock)
            _validate_file(opened)
            key = (*_binding(os.fstat(descriptor)), name.casefold(), *_binding(opened))
            with _reservation(key, "save"):
                fcntl.flock(lock, fcntl.LOCK_EX)
                self._assert_binding(descriptor, name, os.fstat(lock))
                self._check_directory(descriptor)
                yield
                self._assert_binding(descriptor, name, os.fstat(lock))
        finally:
            os.close(lock)

    def _open_lock(self, descriptor: int, name: str) -> int:
        # Darwin can return ENOENT from concurrent non-exclusive O_CREAT opens.
        # Separate existing-file open from exclusive creation so one creator wins
        # and contenders open the same validated inode rather than create anew.
        flags = os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK
        for _ in range(4):
            try:
                return os.open(name, flags, dir_fd=descriptor)
            except FileNotFoundError:
                self._check_directory(descriptor)
                try:
                    return os.open(name, flags | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=descriptor)
                except FileExistsError:
                    continue
        raise _unavailable()

    @staticmethod
    def _assert_binding(descriptor: int, name: str, expected: os.stat_result | None) -> None:
        try:
            actual = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
        except FileNotFoundError:
            if expected is None:
                return
            raise _unavailable() from None
        _validate_file(actual)
        if expected is None or _snapshot(actual) != _snapshot(expected):
            raise _unavailable()

    def _atomic_write(
        self,
        descriptor: int,
        name: str,
        content: bytes,
        expected: os.stat_result | None,
    ) -> None:
        temporary = f".{self.path.name}.{secrets.token_hex(16)}.tmp"
        file_descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=descriptor,
        )
        original = os.fstat(file_descriptor)
        try:
            written = 0
            while written < len(content):
                written += os.write(file_descriptor, content[written:])
            os.fsync(file_descriptor)
            self._check_directory(descriptor)
            self._assert_binding(descriptor, temporary, os.fstat(file_descriptor))
            self._assert_binding(descriptor, name, expected)
            os.replace(temporary, name, src_dir_fd=descriptor, dst_dir_fd=descriptor)
            os.fsync(descriptor)
            self._check_directory(descriptor)
        finally:
            os.close(file_descriptor)
            try:
                temporary_info = os.stat(temporary, dir_fd=descriptor, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                if _binding(temporary_info) == _binding(original):
                    os.unlink(temporary, dir_fd=descriptor)


def _encode(policy: UserTrustPolicy) -> bytes:
    return (
        json.dumps(policy.model_dump(mode="json"), indent=2, sort_keys=True, ensure_ascii=False)
        + "\n"
    ).encode("utf-8")


def _binding(info: os.stat_result) -> tuple[int, int]:
    return info.st_dev, info.st_ino


def _snapshot(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _validate_file(info: os.stat_result) -> None:
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_nlink != 1
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) != 0o600
    ):
        raise _unavailable()


def _validate_directory(info: os.stat_result, *, private: bool) -> None:
    mode = stat.S_IMODE(info.st_mode)
    if not stat.S_ISDIR(info.st_mode):
        raise _unavailable()
    if private:
        if info.st_uid != os.geteuid() or mode != 0o700:
            raise _unavailable()
    elif info.st_uid not in {0, os.geteuid()} or (mode & 0o022 and not mode & stat.S_ISVTX):
        raise _unavailable()


def _unavailable() -> FleetError:
    return FleetError(
        ErrorCode.STATE_UNAVAILABLE,
        "The user trust store is unsafe, invalid, or unavailable; no authority was inferred.",
        "Inspect the user-owned policy directory and validated revision backups before retrying.",
    )


def _conflict() -> FleetError:
    return FleetError(
        ErrorCode.APPROVAL_INVALID,
        "The user trust policy changed concurrently.",
        "Reload the current policy and review the exact mutation before retrying.",
    )
