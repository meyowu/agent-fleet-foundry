"""Canonical hashing, redaction, and logical path containment."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from collections.abc import Iterable
from pathlib import Path
from threading import RLock
from typing import Any
from urllib.parse import quote, quote_plus

from agent_fleet.domain.errors import ErrorCode, FleetError

MINIMUM_GIT_VERSION = (2, 45, 0)
_GIT_VERSION_PATTERN = re.compile(r"\bgit version (\d+)\.(\d+)(?:\.(\d+))?\b")


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def canonical_json_hash(value: Any) -> str:
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256_bytes(data.encode("utf-8"))


def status_fingerprint(status_porcelain: str) -> str:
    return sha256_bytes(status_porcelain.encode("utf-8"))


def path_is_within(candidate: Path, root: Path) -> bool:
    """Return whether ``candidate`` is below ``root`` by path or filesystem identity.

    ``Path.is_relative_to`` is lexical and therefore insufficient on a
    case-insensitive filesystem: differently-cased spellings can name the same
    directory while appearing unrelated.  The inode walk also covers symlinked
    spellings and missing descendants whose nearest existing ancestor is the
    authorized root.
    """

    candidate_absolute = Path(os.path.abspath(candidate))
    root_absolute = Path(os.path.abspath(root))
    if candidate_absolute == root_absolute or candidate_absolute.is_relative_to(root_absolute):
        return True
    try:
        root_stat = root_absolute.stat()
    except OSError:
        return False
    root_identity = (root_stat.st_dev, root_stat.st_ino)
    for ancestor in (candidate_absolute, *candidate_absolute.parents):
        try:
            ancestor_stat = ancestor.stat()
        except OSError:
            continue
        if (ancestor_stat.st_dev, ancestor_stat.st_ino) == root_identity:
            return True
    return False


def git_version_is_supported(version_output: str) -> bool:
    """Return whether Git supports the hardened no-lazy-fetch command ceiling."""

    match = _GIT_VERSION_PATTERN.search(version_output)
    if match is None:
        return False
    version = tuple(int(item or 0) for item in match.groups())
    return version >= MINIMUM_GIT_VERSION


class Redactor:
    """Thread-safe deterministic redactor for explicitly registered secrets.

    A resolved provider credential can become visible in a few common encoded
    forms in URLs, protocol diagnostics, or third-party exceptions.  Registering
    one value therefore registers a small, deterministic set of representations
    as one redaction group.  The registry never exposes those representations.
    """

    def __init__(self, secrets: list[str] | None = None) -> None:
        self._lock = RLock()
        self._registered_values: set[str] = set()
        self._forms: dict[str, int] = {}
        self._next_group = 1
        for secret in sorted({item for item in (secrets or []) if item}, key=len, reverse=True):
            self.register_secret(secret)

    def register_secret(self, secret: str) -> bool:
        """Register a raw secret and common encodings, idempotently.

        The return value is true only for the thread that first registers the
        raw value.  Empty values are ignored because registering an empty string
        would match every diagnostic.
        """

        if not isinstance(secret, str):
            raise TypeError("registered secrets must be strings")
        if not secret:
            return False
        forms = _secret_forms(secret)
        with self._lock:
            if secret in self._registered_values:
                return False
            group = self._next_group
            self._next_group += 1
            self._registered_values.add(secret)
            for form in forms:
                self._forms.setdefault(form, group)
            return True

    def register_secrets(self, secrets: Iterable[str]) -> int:
        """Register several values and return the count of new raw values."""

        return sum(self.register_secret(secret) for secret in secrets)

    def has_registered_secrets(self) -> bool:
        """Expose registry presence without returning any secret representation."""
        with self._lock:
            return bool(self._registered_values)

    def redact_text(self, value: str) -> tuple[str, list[str]]:
        return self._redact_text(value, self._snapshot())

    @staticmethod
    def _redact_text(value: str, forms: tuple[tuple[str, int], ...]) -> tuple[str, list[str]]:
        redacted = value
        summary: list[str] = []
        for form, group in forms:
            if form in redacted:
                redacted = redacted.replace(form, f"<redacted:{group}>")
                summary.append(f"registered_secret_{group}")
        return redacted, sorted(set(summary))

    def contains_secret(self, value: str | bytes) -> bool:
        text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value
        return any(form in text for form, _ in self._snapshot())

    def contains_secret_data(self, value: Any) -> bool:
        forms = self._snapshot()

        def contains(item: Any) -> bool:
            if isinstance(item, str | bytes):
                text = item.decode("utf-8", errors="replace") if isinstance(item, bytes) else item
                return any(form in text for form, _ in forms)
            if isinstance(item, dict):
                return any(contains(str(key)) or contains(child) for key, child in item.items())
            if isinstance(item, list | tuple):
                return any(contains(child) for child in item)
            return False

        return contains(value)

    def redact_data(self, value: Any) -> tuple[Any, list[str]]:
        summaries: list[str] = []
        forms = self._snapshot()

        def visit(item: Any) -> Any:
            if isinstance(item, str):
                cleaned, found = self._redact_text(item, forms)
                summaries.extend(found)
                return cleaned
            if isinstance(item, dict):
                cleaned_mapping: dict[str, Any] = {}
                for key, child in item.items():
                    cleaned_key, found = self._redact_text(str(key), forms)
                    summaries.extend(found)
                    unique_key = cleaned_key
                    suffix = 2
                    while unique_key in cleaned_mapping:
                        unique_key = f"{cleaned_key}#{suffix}"
                        suffix += 1
                    cleaned_mapping[unique_key] = visit(child)
                return cleaned_mapping
            if isinstance(item, list):
                return [visit(child) for child in item]
            if isinstance(item, tuple):
                return tuple(visit(child) for child in item)
            return item

        cleaned = visit(value)
        return cleaned, sorted(set(summaries))

    def _snapshot(self) -> tuple[tuple[str, int], ...]:
        with self._lock:
            return tuple(sorted(self._forms.items(), key=lambda item: (-len(item[0]), item[0])))


def _secret_forms(secret: str) -> frozenset[str]:
    encoded = secret.encode("utf-8")
    standard_base64 = base64.b64encode(encoded).decode("ascii")
    urlsafe_base64 = base64.urlsafe_b64encode(encoded).decode("ascii")
    json_escaped = json.dumps(secret, ensure_ascii=True)[1:-1]
    return frozenset(
        item
        for item in {
            secret,
            quote(secret, safe=""),
            quote_plus(secret, safe=""),
            standard_base64,
            standard_base64.rstrip("="),
            urlsafe_base64,
            urlsafe_base64.rstrip("="),
            encoded.hex(),
            json_escaped,
        }
        if item
    )


def resolve_logical_path(root: Path, logical_path: str, *, allow_missing: bool = True) -> Path:
    """Resolve a model-supplied relative path without traversal or symlink escape."""

    if not logical_path or "\x00" in logical_path:
        raise _path_error(logical_path)
    if "\\" in logical_path:
        raise _path_error(logical_path)
    candidate = Path(logical_path)
    if candidate.is_absolute() or any(part == ".." for part in candidate.parts):
        raise _path_error(logical_path)
    root_resolved = root.resolve(strict=True)
    joined = root_resolved.joinpath(candidate)
    if joined.exists() or not allow_missing:
        resolved = joined.resolve(strict=not allow_missing)
    else:
        existing = joined
        missing: list[str] = []
        while not existing.exists() and existing != root_resolved:
            missing.append(existing.name)
            existing = existing.parent
        resolved = existing.resolve(strict=True).joinpath(*reversed(missing))
    try:
        resolved.relative_to(root_resolved)
    except ValueError as error:
        raise _path_error(logical_path) from error
    if os.path.commonpath((str(root_resolved), str(resolved))) != str(root_resolved):
        raise _path_error(logical_path)
    return resolved


def _path_error(logical_path: str) -> FleetError:
    return FleetError(
        ErrorCode.PATH_OUTSIDE_SCOPE,
        f"Path is outside the authorized workspace: {logical_path!r}.",
        "Use a repository-relative path without traversal, alternate separators, "
        "or symlink escape.",
        details={"logical_path": logical_path},
    )
