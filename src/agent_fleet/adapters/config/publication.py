"""Pinned, bounded native directory exchange; never authorization or rollback policy."""

from __future__ import annotations

import array
import base64
import ctypes
import errno
import fcntl
import os
import re
import stat
import sys
from collections.abc import Callable
from contextlib import AbstractContextManager, suppress
from functools import wraps
from pathlib import Path
from types import TracebackType
from typing import Literal, cast

from pydantic import ValidationError

from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import Project
from agent_fleet.domain.organization_tree import (
    MAX_DEPTH,
    MAX_DIRECTORIES,
    MAX_FILE_BYTES,
    MAX_FILES,
    MAX_TREE_BYTES,
    DirectoryIdentity,
    OrganizationDirectory,
    OrganizationFile,
    OrganizationTree,
    OrganizationXattr,
    PreparedPublication,
    PublicationObservation,
    validate_organization_path,
)
from agent_fleet.domain.security import Redactor, sha256_bytes
from agent_fleet.ports.organization_filesystem import OrganizationPublicationSession

_OPERATION = re.compile(r"fop_[0-9a-f]{32}\Z")


def _error(message: str = "Organization publication identity or metadata is unsafe.") -> FleetError:
    return FleetError(
        ErrorCode.RECOVERY_REQUIRED,
        message,
        "Inspect the exact operation and retained scratch. No automatic exchange or cleanup "
        "is permitted after an uncertain outcome.",
    )


def _boundary[**P, T](operation: Callable[P, T]) -> Callable[P, T]:
    @wraps(operation)
    def call(*args: P.args, **kwargs: P.kwargs) -> T:
        error: FleetError
        try:
            return operation(*args, **kwargs)
        except FleetError as caught:
            error = caught
        except (OSError, ValueError, TypeError, ValidationError, AttributeError):
            error = _error()
        error.__context__ = None
        raise error from None

    return call


def _directory_flags() -> int:
    return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def _identity(info: os.stat_result) -> DirectoryIdentity:
    if not stat.S_ISDIR(info.st_mode):
        raise _error()
    return DirectoryIdentity(
        device=info.st_dev, inode=info.st_ino, uid=info.st_uid, mode=stat.S_IMODE(info.st_mode)
    )


def _signature(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_uid,
        info.st_gid,
        info.st_mode,
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _native_backend() -> Literal["darwin-renameatx_np", "linux-renameat2"]:
    if sys.platform == "darwin":
        name, backend = "renameatx_np", "darwin-renameatx_np"
    elif sys.platform == "linux":
        name, backend = "renameat2", "linux-renameat2"
    else:
        raise _error("Native organization exchange is unsupported on this platform.")
    if not hasattr(ctypes.CDLL(None), name):
        raise _error("The native directory-exchange entry point is unavailable.")
    return backend  # type: ignore[return-value]


def _exchange_at(from_fd: int, from_name: str, to_fd: int, to_name: str) -> None:
    backend = _native_backend()
    library = ctypes.CDLL(None, use_errno=True)
    function = getattr(library, "renameatx_np" if backend.startswith("darwin") else "renameat2")
    function.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    function.restype = ctypes.c_int
    # Both platform UAPIs define their exchange-only flag as 0x2. Never use
    # path-only rename, syscall-number guesses, or an overwrite fallback.
    if function(from_fd, os.fsencode(from_name), to_fd, os.fsencode(to_name), 0x2) != 0:
        raise OSError(ctypes.get_errno(), "native directory exchange failed")


def _flush_file(descriptor: int) -> None:
    os.fsync(descriptor)
    if sys.platform == "darwin":
        # Darwin sys/fcntl.h: F_FULLFSYNC=51, fsync plus drive-cache flush.
        fcntl.fcntl(descriptor, 51)


def _probe_exchange(scratch: int) -> None:
    """Prove exchange support on private same-mount entries, never the target."""
    names = ("probe-before", "probe-after")
    for name in names:
        os.mkdir(name, 0o700, dir_fd=scratch)
    identities = tuple(
        _identity(os.stat(name, dir_fd=scratch, follow_symlinks=False)) for name in names
    )
    _exchange_at(scratch, names[0], scratch, names[1])
    if tuple(_identity(os.stat(name, dir_fd=scratch, follow_symlinks=False)) for name in names) != (
        identities[1],
        identities[0],
    ):
        raise _error("The native exchange capability probe could not be verified.")
    for name in names:
        os.rmdir(name, dir_fd=scratch)
    os.fsync(scratch)


def _xattrs(descriptor: int) -> tuple[OrganizationXattr, ...]:
    # Python exposes os.listxattr on Linux, but not on every macOS build.
    # Query the descriptor using each platform's native, bounded size API.
    library = ctypes.CDLL(None, use_errno=True)
    function = library.flistxattr
    function.restype = ctypes.c_ssize_t
    if sys.platform == "darwin":
        function.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int]
        size = function(descriptor, None, 0, 0x20)
    elif sys.platform == "linux":
        function.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_size_t]
        size = function(descriptor, None, 0)
    else:
        raise _error("Extended metadata inspection is unsupported on this platform.")
    if size < 0:
        raise _error("The platform could not inspect organization extended attributes.")
    if size == 0:
        return ()
    name = b"com.apple.provenance"
    if size != len(name) + 1:
        raise _error("Only exact supported organization extended metadata can be preserved.")
    names = ctypes.create_string_buffer(size)
    read = (
        function(descriptor, names, size, 0x20)
        if sys.platform == "darwin"
        else function(descriptor, names, size)
    )
    if read != size or names.raw != name + b"\0":
        raise _error("Unsupported or changing organization extended metadata was found.")
    get_value = library.fgetxattr
    get_value.restype = ctypes.c_ssize_t
    arguments = (ctypes.c_int, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_size_t)
    if sys.platform == "darwin":
        get_value.argtypes = [*arguments, ctypes.c_uint32, ctypes.c_int]
        length = get_value(descriptor, name, None, 0, 0, 0x20)
    else:
        get_value.argtypes = arguments
        length = get_value(descriptor, name, None, 0)
    if length < 0 or length > 4096:
        raise _error("Organization extended metadata exceeds its supported bound.")
    value = ctypes.create_string_buffer(max(1, length))
    read = (
        get_value(descriptor, name, value, length, 0, 0x20)
        if sys.platform == "darwin"
        else get_value(descriptor, name, value, length)
    )
    if read != length:
        raise _error("Organization extended metadata changed during inspection.")
    return (
        OrganizationXattr(
            name="com.apple.provenance",
            value_base64=base64.b64encode(value.raw[:length]).decode("ascii"),
        ),
    )


def _restore_created_xattrs(descriptor: int, expected: tuple[OrganizationXattr, ...]) -> None:
    """Only newly created private stage entries may have inherited metadata replaced."""
    current = _xattrs(descriptor)
    if current == expected:
        return
    library = ctypes.CDLL(None, use_errno=True)
    remove = library.fremovexattr
    remove.restype = ctypes.c_int
    remove.argtypes = (
        [ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
        if sys.platform == "darwin"
        else [ctypes.c_int, ctypes.c_char_p]
    )
    for item in current:
        name = item.name.encode("ascii")
        result = (
            remove(descriptor, name, 0) if sys.platform == "darwin" else remove(descriptor, name)
        )
        if result != 0:
            raise _error("Inherited private-stage metadata could not be replaced exactly.")
    set_value = library.fsetxattr
    set_value.restype = ctypes.c_int
    arguments = (ctypes.c_int, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_size_t)
    set_value.argtypes = (
        [*arguments, ctypes.c_uint32, ctypes.c_int]
        if sys.platform == "darwin"
        else [*arguments, ctypes.c_int]
    )
    for item in expected:
        name = item.name.encode("ascii")
        content = base64.b64decode(item.value_base64, validate=True)
        value = ctypes.create_string_buffer(content)
        result = (
            set_value(descriptor, name, value, len(content), 0, 0)
            if sys.platform == "darwin"
            else set_value(descriptor, name, value, len(content), 0)
        )
        if result != 0:
            raise _error("Private-stage metadata could not be preserved exactly.")
    if _xattrs(descriptor) != expected:
        raise _error("Private-stage metadata read-back did not match the complete tree.")


def _metadata(descriptor: int, *, directory: bool) -> os.stat_result:
    info = os.fstat(descriptor)
    modes = {0o700, 0o755} if directory else {0o600, 0o644}
    if (
        (not stat.S_ISDIR(info.st_mode) if directory else not stat.S_ISREG(info.st_mode))
        or info.st_uid != os.getuid()
        or info.st_gid != os.getgid()
        or stat.S_IMODE(info.st_mode) not in modes
        or (not directory and info.st_nlink != 1)
        or getattr(info, "st_flags", 0) != 0
    ):
        raise _error(
            "Organization publication requires plain owned files and supported exact metadata."
        )
    _xattrs(descriptor)
    if sys.platform == "darwin":
        library = ctypes.CDLL(None, use_errno=True)
        get_acl = library.acl_get_fd_np
        get_acl.argtypes, get_acl.restype = [ctypes.c_int, ctypes.c_int], ctypes.c_void_p
        get_entry = library.acl_get_entry
        get_entry.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)]
        get_entry.restype = ctypes.c_int
        free_acl = library.acl_free
        free_acl.argtypes, free_acl.restype = [ctypes.c_void_p], ctypes.c_int
        ctypes.set_errno(0)
        acl = get_acl(descriptor, 0x100)  # ACL_TYPE_EXTENDED
        if not acl:
            # Apple Libc posix1e/acl_file.c delegates to filesec_get_property;
            # gen/filesec.c reports ENOENT for a valid inode with no ACL property.
            if ctypes.get_errno() == errno.ENOENT and _signature(
                os.fstat(descriptor)
            ) == _signature(info):
                return info
            raise _error("The platform could not inspect organization ACL metadata.")
        try:
            entry = ctypes.c_void_p()
            ctypes.set_errno(0)
            result = get_entry(acl, 0, ctypes.byref(entry))  # ACL_FIRST_ENTRY
            if result == 0 or ctypes.get_errno() != errno.EINVAL:
                raise _error("Extended organization ACLs are not supported.")
        finally:
            free_acl(acl)
    elif sys.platform == "linux":
        # Linux UAPI FS_IOC_GETFLAGS = _IOR('f', 1, long), supported here only
        # for the 64-bit ABI. Extent/index implementation flags need not be
        # copied; every user-visible persistent inode flag is rejected.
        flags = array.array("l", [0])
        if flags.itemsize != 8:
            raise _error("Linux publication requires the supported 64-bit inode-flags ABI.")
        fcntl.ioctl(descriptor, 0x80086601, flags, True)
        if flags[0] & ~(0x00080000 | 0x00001000):
            raise _error("Persistent Linux inode flags are not supported.")
    else:
        raise _error("Extended metadata inspection is unsupported on this platform.")
    return info


class NativeOrganizationFileSystem:
    def __init__(self, redactor: Redactor) -> None:
        self.redactor = redactor

    def session(
        self, project: Project, operation_id: str
    ) -> AbstractContextManager[OrganizationPublicationSession]:
        return _Session(project, operation_id, self.redactor)


class _Session(AbstractContextManager[OrganizationPublicationSession]):
    def __init__(self, project: Project, operation_id: str, redactor: Redactor) -> None:
        self.project = project.model_copy(deep=True)
        self.operation_id, self.redactor = operation_id, redactor
        self._fds: list[int] = []
        self._chain: list[tuple[int, str, int]] = []
        self.parent_fd = self.repository_fd = self.lock_fd = -1
        self._entered = False
        self._before: OrganizationTree | None = None
        self._target_identity: DirectoryIdentity | None = None

    @_boundary
    def __enter__(self) -> OrganizationPublicationSession:
        if self._entered or not _OPERATION.fullmatch(self.operation_id):
            raise _error()
        self._scan(self.project.model_dump(mode="json"))
        root = Path(self.project.canonical_root)
        if (
            not root.is_absolute()
            or root == Path("/")
            or ".." in root.parts
            or str(root) != self.project.canonical_root
        ):
            raise _error()
        self.backend = _native_backend()
        self.durability: Literal["fsync+fullfsync", "fsync"] = (
            "fsync+fullfsync" if self.backend.startswith("darwin") else "fsync"
        )
        try:
            descriptor = self._keep(os.open("/", _directory_flags()))
            for component in root.parts[1:]:
                child = self._keep(os.open(component, _directory_flags(), dir_fd=descriptor))
                self._chain.append((descriptor, component, child))
                descriptor = child
            self.parent_fd, self.repository_fd = self._chain[-1][0], descriptor
            self.repository_basename = root.name
            self.parent_identity = _identity(os.fstat(self.parent_fd))
            self.repository_identity = _identity(os.fstat(self.repository_fd))
            for identity in (self.parent_identity, self.repository_identity):
                if identity.uid != os.getuid() or identity.mode & 0o022:
                    raise _error("Repository and publication parent must be privately writable.")
            if self.parent_identity.device != self.repository_identity.device:
                raise _error("Repository mount roots cannot use an outside same-mount scratch.")
            self.lock_name = ".fleet-publish-" + sha256_bytes(str(root).encode()) + ".lock"
            try:
                lock = os.open(
                    self.lock_name,
                    os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                    dir_fd=self.parent_fd,
                )
            except FileNotFoundError:
                try:
                    lock = os.open(
                        self.lock_name,
                        os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                        0o600,
                        dir_fd=self.parent_fd,
                    )
                except FileExistsError:
                    lock = os.open(
                        self.lock_name,
                        os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK,
                        dir_fd=self.parent_fd,
                    )
            self.lock_fd = self._keep(lock)
            if _metadata(lock, directory=False).st_mode & 0o777 != 0o600:
                raise _error()
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._lock_signature = _signature(os.fstat(lock))
            self._entered = True
            self._validate()
            return self
        except BaseException:
            self._close()
            raise

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._close()

    def _close(self) -> None:
        self._entered = False
        for descriptor in reversed(self._fds):
            os.close(descriptor)
        self._fds.clear()

    def _keep(self, descriptor: int) -> int:
        self._fds.append(descriptor)
        return descriptor

    def _scan(self, value: object) -> None:
        if self.redactor.contains_secret_data(value):
            raise _error("Registered secret material cannot enter organization publication.")

    def _scan_xattrs(self, attributes: tuple[OrganizationXattr, ...]) -> None:
        for attribute in attributes:
            self._scan(attribute.value_base64)
            value = base64.b64decode(attribute.value_base64, validate=True)
            decoded: str | None = None
            with suppress(UnicodeDecodeError):
                decoded = value.decode("utf-8")
            if decoded is not None:
                self._scan(decoded)

    def _validate(self) -> None:
        if not self._entered:
            raise _error("Publication session is not active.")
        for parent, name, child in self._chain:
            if _identity(os.stat(name, dir_fd=parent, follow_symlinks=False)) != _identity(
                os.fstat(child)
            ):
                raise _error()
        if (
            _identity(os.fstat(self.parent_fd)) != self.parent_identity
            or _identity(os.fstat(self.repository_fd)) != self.repository_identity
            or _signature(os.stat(self.lock_name, dir_fd=self.parent_fd, follow_symlinks=False))
            != self._lock_signature
        ):
            raise _error()

    def _capture(self, descriptor: int) -> OrganizationTree:
        files: list[OrganizationFile] = []
        directories: list[OrganizationDirectory] = []
        total = 0

        def walk(current: int, path: str, depth: int) -> None:
            nonlocal total
            if depth > MAX_DEPTH or len(directories) >= MAX_DIRECTORIES:
                raise _error()
            before = _metadata(current, directory=True)
            attributes = _xattrs(current)
            self._scan_xattrs(attributes)
            if before.st_dev != self.parent_identity.device:
                raise _error()
            directories.append(
                OrganizationDirectory(
                    path=path,
                    mode=cast(Literal[0o700, 0o755], stat.S_IMODE(before.st_mode)),
                    xattrs=attributes,
                )
            )
            names: list[str] = []
            with os.scandir(current) as entries:
                for entry in entries:
                    names.append(entry.name)
                    if len(names) > MAX_FILES + MAX_DIRECTORIES:
                        raise _error()
            for name in sorted(names):
                logical = name if path == "." else path + "/" + name
                self._scan(logical)
                validate_organization_path(logical)
                named = os.stat(name, dir_fd=current, follow_symlinks=False)
                is_directory = stat.S_ISDIR(named.st_mode)
                flags = (
                    _directory_flags()
                    if is_directory
                    else (os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
                )
                child = os.open(name, flags, dir_fd=current)
                try:
                    info = _metadata(child, directory=is_directory)
                    if _signature(named) != _signature(info):
                        raise _error()
                    if is_directory:
                        walk(child, logical, depth + 1)
                    else:
                        if len(files) >= MAX_FILES or info.st_size > MAX_FILE_BYTES:
                            raise _error()
                        chunks: list[bytes] = []
                        size = 0
                        while chunk := os.read(child, min(65536, MAX_FILE_BYTES + 1 - size)):
                            chunks.append(chunk)
                            size += len(chunk)
                            if size > MAX_FILE_BYTES:
                                raise _error()
                        total += size
                        if total > MAX_TREE_BYTES or size != info.st_size:
                            raise _error()
                        content = b"".join(chunks)
                        value = content.decode("utf-8")
                        self._scan(value)
                        attributes = _xattrs(child)
                        self._scan_xattrs(attributes)
                        files.append(
                            OrganizationFile(
                                path=logical,
                                content=value,
                                sha256=sha256_bytes(content),
                                mode=cast(Literal[0o600, 0o644], stat.S_IMODE(info.st_mode)),
                                xattrs=attributes,
                            )
                        )
                    if _signature(info) != _signature(os.fstat(child)) or _signature(info) != (
                        _signature(os.stat(name, dir_fd=current, follow_symlinks=False))
                    ):
                        raise _error()
                finally:
                    os.close(child)
            if _signature(before) != _signature(os.fstat(current)):
                raise _error()

        walk(descriptor, ".", 0)
        return OrganizationTree(
            files=tuple(sorted(files, key=lambda item: item.path)),
            directories=tuple(sorted(directories, key=lambda item: item.path)),
        )

    def _tree_at(self, parent: int, name: str) -> tuple[DirectoryIdentity, OrganizationTree]:
        descriptor = os.open(name, _directory_flags(), dir_fd=parent)
        try:
            identity = _identity(os.fstat(descriptor))
            tree = self._capture(descriptor)
            if identity != _identity(os.stat(name, dir_fd=parent, follow_symlinks=False)):
                raise _error()
            return identity, tree
        finally:
            os.close(descriptor)

    @_boundary
    def capture_target(self) -> OrganizationTree:
        self._validate()
        identity, tree = self._tree_at(self.repository_fd, ".fleet")
        self._validate()
        self._target_identity, self._before = identity, tree
        return tree

    @_boundary
    def stage(self, after: OrganizationTree) -> PreparedPublication:
        self._validate()
        self._scan(after.model_dump(mode="json"))
        after = OrganizationTree.model_validate_json(after.model_dump_json())
        entries: tuple[OrganizationFile | OrganizationDirectory, ...] = (
            *after.files,
            *after.directories,
        )
        for entry in entries:
            self._scan_xattrs(entry.xattrs)
        before = self.capture_target()
        assert self._target_identity is not None
        name = ".fleet-publication-" + self.operation_id
        os.mkdir(name, 0o700, dir_fd=self.parent_fd)
        scratch = os.open(name, _directory_flags(), dir_fd=self.parent_fd)
        try:
            scratch_identity = _identity(_metadata(scratch, directory=True))
            if scratch_identity.mode != 0o700:
                raise _error()
            _probe_exchange(scratch)
            os.mkdir("tree", 0o700, dir_fd=scratch)
            staged = os.open("tree", _directory_flags(), dir_fd=scratch)
            opened: dict[str, int] = {".": staged}
            try:
                for directory in sorted(
                    after.directories, key=lambda item: (item.path.count("/"), item.path)
                ):
                    if directory.path == ".":
                        continue
                    path = Path(directory.path)
                    parent = opened[str(path.parent)]
                    os.mkdir(path.name, 0o700, dir_fd=parent)
                    opened[directory.path] = os.open(path.name, _directory_flags(), dir_fd=parent)
                for item in after.files:
                    path = Path(item.path)
                    descriptor = os.open(
                        path.name,
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                        0o600,
                        dir_fd=opened[str(path.parent)],
                    )
                    try:
                        content = item.content.encode("utf-8")
                        offset = 0
                        while offset < len(content):
                            written = os.write(descriptor, content[offset:])
                            if written <= 0:
                                raise _error()
                            offset += written
                        os.fchmod(descriptor, item.mode)
                        _restore_created_xattrs(descriptor, item.xattrs)
                        _metadata(descriptor, directory=False)
                        _flush_file(descriptor)
                    finally:
                        os.close(descriptor)
                for directory in reversed(after.directories):
                    descriptor = opened[directory.path]
                    os.fchmod(descriptor, directory.mode)
                    _restore_created_xattrs(descriptor, directory.xattrs)
                    _metadata(descriptor, directory=True)
                    os.fsync(descriptor)
                if self._capture(staged) != after:
                    raise _error()
                staged_identity = _identity(os.fstat(staged))
                os.fsync(scratch)
                os.fsync(self.parent_fd)
                os.fsync(self.repository_fd)
                # A regular owned anchor provides the macOS device flush after
                # all directory fsyncs; it remains outside the swapped tree.
                _flush_file(self.lock_fd)
                self._validate()
                receipt = PreparedPublication(
                    operation_id=self.operation_id,
                    project_id=self.project.project_id,
                    repository_identity=self.project.identity_hash,
                    repository_basename=self.repository_basename,
                    parent_identity=self.parent_identity,
                    repository_directory_identity=self.repository_identity,
                    target_identity=self._target_identity,
                    scratch_basename=name,
                    scratch_identity=scratch_identity,
                    staged_identity=staged_identity,
                    before_sha256=before.sha256,
                    after_sha256=after.sha256,
                    backend=self.backend,
                    durability=self.durability,
                )
                if self.observe(receipt).state != "prepared":
                    raise _error()
                return receipt
            finally:
                for descriptor in reversed(list(opened.values())):
                    os.close(descriptor)
        finally:
            os.close(scratch)

    def _receipt(self, prepared: PreparedPublication) -> PreparedPublication:
        self._scan(prepared.model_dump(mode="json"))
        prepared = PreparedPublication.model_validate_json(prepared.model_dump_json())
        if (
            prepared.operation_id != self.operation_id
            or prepared.project_id != self.project.project_id
            or prepared.repository_identity != self.project.identity_hash
            or prepared.repository_basename != self.repository_basename
            or prepared.parent_identity != self.parent_identity
            or prepared.repository_directory_identity != self.repository_identity
            or prepared.backend != self.backend
            or prepared.durability != self.durability
        ):
            raise _error()
        return prepared

    @_boundary
    def observe(self, prepared: PreparedPublication) -> PublicationObservation:
        self._validate()
        prepared = self._receipt(prepared)
        target_identity, target = self._tree_at(self.repository_fd, ".fleet")
        try:
            scratch = os.open(prepared.scratch_basename, _directory_flags(), dir_fd=self.parent_fd)
        except FileNotFoundError:
            result = PublicationObservation(
                prepared=prepared,
                state="cleaned",
                target_identity=target_identity,
                target_sha256=target.sha256,
            )
        else:
            try:
                if _identity(_metadata(scratch, directory=True)) != prepared.scratch_identity:
                    raise _error()
                if os.listdir(scratch) != ["tree"]:
                    raise _error()
                backup_identity, backup = self._tree_at(scratch, "tree")
                state: Literal["prepared", "exchanged"] = (
                    "prepared" if target_identity == prepared.target_identity else "exchanged"
                )
                result = PublicationObservation(
                    prepared=prepared,
                    state=state,
                    target_identity=target_identity,
                    target_sha256=target.sha256,
                    backup_identity=backup_identity,
                    backup_sha256=backup.sha256,
                )
                if (
                    _identity(
                        os.stat(
                            prepared.scratch_basename, dir_fd=self.parent_fd, follow_symlinks=False
                        )
                    )
                    != prepared.scratch_identity
                ):
                    raise _error()
            finally:
                os.close(scratch)
        self._validate()
        return result

    @_boundary
    def exchange(self, prepared: PreparedPublication) -> PublicationObservation:
        observation = self.observe(prepared)
        if observation.state != "prepared":
            raise _error("Publication was already exchanged or cleaned; it cannot be replayed.")
        scratch = os.open(prepared.scratch_basename, _directory_flags(), dir_fd=self.parent_fd)
        try:
            if _identity(os.fstat(scratch)) != prepared.scratch_identity:
                raise _error()
            self._validate()
            _exchange_at(self.repository_fd, ".fleet", scratch, "tree")
            # From this call onward every error retains both trees and the
            # receipt for journal-governed recovery, never an automatic swap.
        finally:
            os.close(scratch)
        return self.sync_exchanged(prepared)

    @_boundary
    def sync_exchanged(self, prepared: PreparedPublication) -> PublicationObservation:
        if self.observe(prepared).state != "exchanged":
            raise _error("Only an exactly exchanged publication can be synchronized.")
        scratch = os.open(prepared.scratch_basename, _directory_flags(), dir_fd=self.parent_fd)
        try:
            if _identity(os.fstat(scratch)) != prepared.scratch_identity:
                raise _error()
            self._validate()
            os.fsync(self.repository_fd)
            os.fsync(scratch)
            _flush_file(self.lock_fd)
            result = self.observe(prepared)
            if result.state != "exchanged":
                raise _error()
            return result
        finally:
            os.close(scratch)

    @_boundary
    def cleanup_owned(
        self,
        prepared: PreparedPublication,
        *,
        expected_target_sha256: str,
        expected_backup_sha256: str | None,
        expected_backup_tree: OrganizationTree | None = None,
    ) -> None:
        self._validate()
        prepared = self._receipt(prepared)
        if expected_backup_tree is None:
            observation = self.observe(prepared)
            if observation.target_sha256 != expected_target_sha256:
                raise _error()
            if observation.state == "cleaned":
                self._sync_cleanup()
                return
            if observation.backup_sha256 != expected_backup_sha256:
                raise _error()
            backup_identity = observation.backup_identity
        else:
            self._scan(expected_backup_tree.model_dump(mode="json"))
            expected_backup_tree = OrganizationTree.model_validate_json(
                expected_backup_tree.model_dump_json()
            )
            for file in expected_backup_tree.files:
                self._scan_xattrs(file.xattrs)
            for directory in expected_backup_tree.directories:
                self._scan_xattrs(directory.xattrs)
            target_identity, target = self._tree_at(self.repository_fd, ".fleet")
            if (
                target.sha256 != expected_target_sha256
                or expected_backup_tree.sha256 != expected_backup_sha256
            ):
                raise _error()
            if (
                target_identity == prepared.target_identity
                and target.sha256 == prepared.before_sha256
            ):
                backup_identity, bound_backup_sha256 = (
                    prepared.staged_identity,
                    prepared.after_sha256,
                )
            elif (
                target_identity == prepared.staged_identity
                and target.sha256 == prepared.after_sha256
            ):
                backup_identity, bound_backup_sha256 = (
                    prepared.target_identity,
                    prepared.before_sha256,
                )
            else:
                raise _error()
            if expected_backup_sha256 != bound_backup_sha256:
                raise _error()
        if backup_identity is None:
            raise _error()
        try:
            scratch = os.open(prepared.scratch_basename, _directory_flags(), dir_fd=self.parent_fd)
        except FileNotFoundError:
            # Target and durable expected tree were checked above. Only the
            # original exact scratch name may be absent after prior cleanup.
            self._sync_cleanup()
            return
        try:
            if _identity(_metadata(scratch, directory=True)) != prepared.scratch_identity:
                raise _error()
            names = os.listdir(scratch)
            if names == ["tree"]:
                tree_fd = os.open("tree", _directory_flags(), dir_fd=scratch)
                try:
                    if _identity(os.fstat(tree_fd)) != backup_identity:
                        raise _error()
                    tree = self._capture(tree_fd)
                    if expected_backup_tree is None:
                        if tree.sha256 != expected_backup_sha256:
                            raise _error()
                    else:
                        self._known_remainder(tree, expected_backup_tree)
                    self._remove_contents(tree_fd, tree)
                finally:
                    os.close(tree_fd)
                self._validate()
                if (
                    _identity(os.stat("tree", dir_fd=scratch, follow_symlinks=False))
                    != backup_identity
                ):
                    raise _error()
                os.rmdir("tree", dir_fd=scratch)
            elif names or expected_backup_tree is None:
                raise _error()
            os.fsync(scratch)
        finally:
            os.close(scratch)
        if (
            _identity(
                os.stat(prepared.scratch_basename, dir_fd=self.parent_fd, follow_symlinks=False)
            )
            != prepared.scratch_identity
        ):
            raise _error()
        os.rmdir(prepared.scratch_basename, dir_fd=self.parent_fd)
        self._sync_cleanup()

    def _sync_cleanup(self) -> None:
        os.fsync(self.parent_fd)
        _flush_file(self.lock_fd)
        self._validate()

    @staticmethod
    def _known_remainder(remaining: OrganizationTree, complete: OrganizationTree) -> None:
        files = {file.path: file for file in complete.files}
        directories = {directory.path: directory for directory in complete.directories}
        if any(files.get(file.path) != file for file in remaining.files) or any(
            directories.get(directory.path) != directory for directory in remaining.directories
        ):
            raise _error("Cleanup remainder contains content outside the immutable backup tree.")

    def _remove_contents(self, root: int, tree: OrganizationTree) -> None:
        opened: dict[str, int] = {".": root}
        identities: dict[str, DirectoryIdentity] = {}
        try:
            for item in tree.directories:
                if item.path != ".":
                    path = Path(item.path)
                    descriptor = os.open(
                        path.name, _directory_flags(), dir_fd=opened[str(path.parent)]
                    )
                    opened[item.path] = descriptor
                descriptor = opened[item.path]
                info = _metadata(descriptor, directory=True)
                if stat.S_IMODE(info.st_mode) != item.mode or _xattrs(descriptor) != item.xattrs:
                    raise _error()
                identities[item.path] = _identity(info)
            for file in tree.files:
                path = Path(file.path)
                parent = opened[str(path.parent)]
                descriptor = os.open(
                    path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent
                )
                try:
                    info = _metadata(descriptor, directory=False)
                    if (
                        stat.S_IMODE(info.st_mode) != file.mode
                        or _xattrs(descriptor) != file.xattrs
                    ):
                        raise _error()
                    content = bytearray()
                    while chunk := os.read(
                        descriptor, min(65536, MAX_FILE_BYTES + 1 - len(content))
                    ):
                        content.extend(chunk)
                        if len(content) > MAX_FILE_BYTES:
                            raise _error()
                    if sha256_bytes(bytes(content)) != file.sha256 or (
                        _signature(info)
                        != _signature(os.stat(path.name, dir_fd=parent, follow_symlinks=False))
                    ):
                        raise _error()
                    os.unlink(path.name, dir_fd=parent)
                finally:
                    os.close(descriptor)
            for item in reversed(tree.directories):
                descriptor = opened[item.path]
                info = _metadata(descriptor, directory=True)
                if (
                    os.listdir(descriptor)
                    or _identity(info) != identities[item.path]
                    or _xattrs(descriptor) != item.xattrs
                ):
                    raise _error()
                if item.path != ".":
                    path = Path(item.path)
                    parent = opened[str(path.parent)]
                    if (
                        _identity(os.stat(path.name, dir_fd=parent, follow_symlinks=False))
                        != identities[item.path]
                    ):
                        raise _error()
                    os.rmdir(path.name, dir_fd=parent)
        finally:
            for name, descriptor in opened.items():
                if name != ".":
                    os.close(descriptor)
