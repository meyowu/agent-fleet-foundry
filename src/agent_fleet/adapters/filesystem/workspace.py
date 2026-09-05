"""Descriptor-relative, no-follow, bounded candidate-workspace operations."""

from __future__ import annotations

import os
import secrets
import stat
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path, PurePosixPath

from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.security import sha256_bytes

_MAX_WRITE_BYTES = 200_000
_MAX_PATH_BYTES = 4096
_MAX_COMPONENTS = 64
_PROTECTED_COMPONENTS = frozenset({".fleet", ".git"})
_PROTECTED_LEAVES = frozenset(
    {
        ".env",
        ".netrc",
        ".npmrc",
        ".pypirc",
        "credentials",
        "id_ed25519",
        "id_rsa",
    }
)


class BoundedWorkspaceFileSystem:
    """Perform file operations through pinned directory descriptors.

    The adapter deliberately supports regular UTF-8 files and directories only.
    It never follows repository symlinks and never recursively deletes.
    """

    def __init__(self) -> None:
        required = ("O_DIRECTORY", "O_NOFOLLOW", "O_NONBLOCK")
        if any(not hasattr(os, name) for name in required) or os.open not in os.supports_dir_fd:
            raise FleetError(
                ErrorCode.SANDBOX_UNAVAILABLE,
                "This platform lacks required descriptor-relative workspace primitives.",
                "Use Agent Fleet on a Unix platform with openat and O_NOFOLLOW support.",
            )

    def list_files(self, root: Path, *, max_entries: int = 4096) -> list[str]:
        if max_entries < 1 or max_entries > 100_000:
            raise ValueError("max_entries is outside the supported bound")
        with self._root(root) as root_fd:
            found: list[str] = []
            self._walk(root_fd, (), found, max_entries)
        return sorted(found)

    def read_text(self, root: Path, logical_path: str, *, max_bytes: int = 200_000) -> str:
        if max_bytes < 1 or max_bytes > 2_000_000:
            raise ValueError("max_bytes is outside the supported bound")
        components = _logical_components(logical_path)
        with self._root(root) as root_fd:
            parent_fd = self._open_parent(root_fd, components[:-1], create=False)
            try:
                return self._read_leaf(parent_fd, components[-1], max_bytes=max_bytes)
            finally:
                os.close(parent_fd)

    def search_text(
        self,
        root: Path,
        query: str,
        *,
        logical_paths: list[str] | None = None,
        max_results: int = 200,
        max_total_bytes: int = 2_000_000,
    ) -> list[dict[str, object]]:
        if not query or "\x00" in query or len(query.encode()) > 4096:
            raise FleetError(
                ErrorCode.COMMAND_DENIED,
                "Search text must be non-empty, bounded, and contain no NUL byte.",
                "Use a shorter literal UTF-8 query.",
            )
        if not 1 <= max_results <= 1000 or not 1 <= max_total_bytes <= 10_000_000:
            raise ValueError("search limits are outside the supported bounds")
        paths = self.list_files(root) if logical_paths is None else sorted(set(logical_paths))
        if len(paths) > 4096:
            raise FleetError(
                ErrorCode.COMMAND_DENIED,
                "Workspace search path set exceeds the configured entry limit.",
                "Narrow the TaskSpec path scope.",
            )
        results: list[dict[str, object]] = []
        consumed = 0
        for path in paths:
            remaining = max_total_bytes - consumed
            if remaining <= 0 or len(results) >= max_results:
                break
            try:
                text = self.read_text(root, path, max_bytes=min(remaining, 200_000))
            except (UnicodeDecodeError, FleetError):
                continue
            consumed += len(text.encode())
            for line_number, line in enumerate(text.splitlines(), start=1):
                if query in line:
                    results.append(
                        {
                            "path": path,
                            "line": line_number,
                            "text": line[:4096],
                        }
                    )
                    if len(results) >= max_results:
                        break
        return results

    def write_text(self, root: Path, logical_path: str, content: str) -> int:
        encoded = content.encode("utf-8")
        if len(encoded) > _MAX_WRITE_BYTES:
            raise FleetError(
                ErrorCode.COMMAND_DENIED,
                "Candidate write exceeds the bounded UTF-8 file limit.",
                "Write a smaller file or split the reviewed task scope.",
            )
        components = _logical_components(logical_path)
        with self._root(root) as root_fd:
            parent_fd = self._open_parent(root_fd, components[:-1], create=True)
            try:
                self._atomic_replace(parent_fd, components[-1], encoded)
            finally:
                os.close(parent_fd)
        return len(encoded)

    def apply_edit(
        self,
        root: Path,
        logical_path: str,
        *,
        expected_sha256: str,
        old: str,
        new: str,
        expected_matches: int,
    ) -> int:
        if expected_matches < 1 or expected_matches > 1000 or not old:
            raise FleetError(
                ErrorCode.COMMAND_DENIED,
                "Structured edit requires a non-empty old value and bounded positive match count.",
                "Provide an exact expected file hash, old text, replacement, and match count.",
            )
        components = _logical_components(logical_path)
        with self._root(root) as root_fd:
            parent_fd = self._open_parent(root_fd, components[:-1], create=False)
            try:
                current = self._read_leaf(parent_fd, components[-1], max_bytes=_MAX_WRITE_BYTES)
                if sha256_bytes(current.encode()) != expected_sha256:
                    raise FleetError(
                        ErrorCode.PATCH_TARGET_DIVERGED,
                        "The candidate file changed before the structured edit.",
                        "Read the file again and propose an edit against its current hash.",
                    )
                matches = current.count(old)
                if matches != expected_matches:
                    raise FleetError(
                        ErrorCode.PATCH_TARGET_DIVERGED,
                        "The structured edit match count differs from the reviewed request.",
                        "Read the file again and provide the exact expected match count.",
                        details={
                            "expected_matches": expected_matches,
                            "actual_matches": matches,
                        },
                    )
                encoded = current.replace(old, new).encode("utf-8")
                if len(encoded) > _MAX_WRITE_BYTES:
                    raise FleetError(
                        ErrorCode.COMMAND_DENIED,
                        "Candidate edit exceeds the bounded UTF-8 file limit.",
                        "Use a smaller replacement or split the reviewed task scope.",
                    )
                self._atomic_replace(parent_fd, components[-1], encoded)
                return len(encoded)
            finally:
                os.close(parent_fd)

    def delete_file(self, root: Path, logical_path: str, *, expected_sha256: str) -> None:
        components = _logical_components(logical_path)
        with self._root(root) as root_fd:
            parent_fd = self._open_parent(root_fd, components[:-1], create=False)
            try:
                current = self._read_leaf(parent_fd, components[-1], max_bytes=_MAX_WRITE_BYTES)
                if sha256_bytes(current.encode()) != expected_sha256:
                    raise FleetError(
                        ErrorCode.PATCH_TARGET_DIVERGED,
                        "The candidate file changed before deletion.",
                        "Read the file again and request deletion with its current hash.",
                    )
                os.unlink(components[-1], dir_fd=parent_fd)
                os.fsync(parent_fd)
            except FileNotFoundError as error:
                raise _unsafe_path(logical_path, "delete target does not exist") from error
            finally:
                os.close(parent_fd)

    @contextmanager
    def _root(self, root: Path) -> Iterator[int]:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        descriptor: int | None = None
        try:
            descriptor = os.open(root, flags)
            root_stat = os.fstat(descriptor)
            path_stat = os.stat(root, follow_symlinks=False)
        except OSError as error:
            if descriptor is not None:
                os.close(descriptor)
            raise _unsafe_path(".", "workspace root is unavailable or symlinked") from error
        if not stat.S_ISDIR(root_stat.st_mode) or (
            root_stat.st_dev,
            root_stat.st_ino,
        ) != (path_stat.st_dev, path_stat.st_ino):
            os.close(descriptor)
            raise _unsafe_path(".", "workspace root identity is unstable")
        try:
            yield descriptor
        finally:
            os.close(descriptor)

    def _open_parent(self, root_fd: int, components: tuple[str, ...], *, create: bool) -> int:
        current = os.dup(root_fd)
        try:
            for component in components:
                self._reject_case_collision(current, component)
                try:
                    child = os.open(
                        component,
                        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                        dir_fd=current,
                    )
                except FileNotFoundError:
                    if not create:
                        raise
                    with suppress(FileExistsError):
                        os.mkdir(component, 0o755, dir_fd=current)
                    child = os.open(
                        component,
                        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                        dir_fd=current,
                    )
                os.close(current)
                current = child
            return current
        except OSError as error:
            os.close(current)
            raise _unsafe_path("/".join(components), "unsafe or unavailable parent") from error

    def _read_leaf(self, parent_fd: int, leaf: str, *, max_bytes: int) -> str:
        self._reject_case_collision(parent_fd, leaf)
        try:
            descriptor = os.open(
                leaf,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                dir_fd=parent_fd,
            )
        except OSError as error:
            raise _unsafe_path(leaf, "file is unavailable or symlinked") from error
        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode) or before.st_size > max_bytes:
                raise _unsafe_path(leaf, "file is not a bounded regular file")
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = os.read(descriptor, min(65_536, max_bytes + 1 - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                if total > max_bytes:
                    raise _unsafe_path(leaf, "file grew beyond the read limit")
            after = os.fstat(descriptor)
            if (before.st_dev, before.st_ino, before.st_size) != (
                after.st_dev,
                after.st_ino,
                after.st_size,
            ):
                raise _unsafe_path(leaf, "file changed during the bounded read")
            return b"".join(chunks).decode("utf-8")
        finally:
            os.close(descriptor)

    def _atomic_replace(self, parent_fd: int, leaf: str, encoded: bytes) -> None:
        self._reject_case_collision(parent_fd, leaf)
        mode = 0o644
        try:
            existing = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            existing = None
        if existing is not None:
            if not stat.S_ISREG(existing.st_mode):
                raise _unsafe_path(leaf, "write target is not a regular file")
            mode = stat.S_IMODE(existing.st_mode) & 0o777
        temporary = f".fleet-write-{secrets.token_hex(16)}"
        descriptor: int | None = None
        try:
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                mode,
                dir_fd=parent_fd,
            )
            view = memoryview(encoded)
            while view:
                written = os.write(descriptor, view)
                view = view[written:]
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = None
            os.replace(
                temporary,
                leaf,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
            )
            result = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
            if not stat.S_ISREG(result.st_mode) or result.st_size != len(encoded):
                raise _unsafe_path(leaf, "atomic replacement did not produce the expected file")
            os.fsync(parent_fd)
        finally:
            if descriptor is not None:
                os.close(descriptor)
            with suppress(FileNotFoundError):
                os.unlink(temporary, dir_fd=parent_fd)

    def _walk(
        self,
        directory_fd: int,
        prefix: tuple[str, ...],
        found: list[str],
        max_entries: int,
    ) -> None:
        try:
            names = sorted(os.listdir(directory_fd), key=lambda item: (item.casefold(), item))
        except OSError as error:
            raise _unsafe_path("/".join(prefix) or ".", "directory cannot be listed") from error
        folded = [name.casefold() for name in names]
        if len(folded) != len(set(folded)):
            raise _unsafe_path("/".join(prefix) or ".", "case-folded names collide")
        for name in names:
            if name in {".", ".."} or name.casefold() in _PROTECTED_COMPONENTS:
                continue
            try:
                item = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            except OSError as error:
                raise _unsafe_path(
                    "/".join((*prefix, name)), "entry changed during listing"
                ) from error
            if stat.S_ISREG(item.st_mode):
                found.append("/".join((*prefix, name)))
                if len(found) > max_entries:
                    raise FleetError(
                        ErrorCode.COMMAND_DENIED,
                        "Workspace file listing exceeds the configured entry limit.",
                        "Narrow the TaskSpec path scope.",
                    )
            elif stat.S_ISDIR(item.st_mode):
                child = os.open(
                    name,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=directory_fd,
                )
                try:
                    self._walk(child, (*prefix, name), found, max_entries)
                finally:
                    os.close(child)
            elif stat.S_ISLNK(item.st_mode):
                continue
            else:
                raise _unsafe_path(
                    "/".join((*prefix, name)),
                    "workspace contains a special file",
                )

    @staticmethod
    def _reject_case_collision(directory_fd: int, requested: str) -> None:
        try:
            matches = [
                name for name in os.listdir(directory_fd) if name.casefold() == requested.casefold()
            ]
        except OSError as error:
            raise _unsafe_path(requested, "parent directory cannot be inspected") from error
        if matches and matches != [requested]:
            raise _unsafe_path(requested, "path has a case-folded alias")


def _logical_components(logical_path: str) -> tuple[str, ...]:
    if (
        not logical_path
        or "\x00" in logical_path
        or "\\" in logical_path
        or logical_path.startswith("/")
        or len(logical_path.encode()) > _MAX_PATH_BYTES
    ):
        raise _unsafe_path(logical_path, "path is not a bounded POSIX-relative path")
    path = PurePosixPath(logical_path)
    components = path.parts
    if (
        not components
        or len(components) > _MAX_COMPONENTS
        or "." in components
        or ".." in components
        or path.as_posix() != logical_path
        or any(
            not component or any(ord(char) < 32 for char in component) for component in components
        )
    ):
        raise _unsafe_path(logical_path, "path is not canonical")
    folded = tuple(component.casefold() for component in components)
    if any(component in _PROTECTED_COMPONENTS for component in folded):
        raise _unsafe_path(logical_path, "protected control-plane path")
    if folded[-1] in _PROTECTED_LEAVES:
        raise _unsafe_path(logical_path, "credential-like path")
    return components


def _unsafe_path(logical_path: str, reason: str) -> FleetError:
    return FleetError(
        ErrorCode.PATH_OUTSIDE_SCOPE,
        f"Workspace path is unsafe: {logical_path!r} ({reason}).",
        "Use a canonical repository-relative regular-file path inside the reviewed task scope.",
        details={"logical_path": logical_path, "reason": reason},
    )
