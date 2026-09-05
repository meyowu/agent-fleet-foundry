"""Resolve host executables without trusting repository-controlled PATH entries."""

from __future__ import annotations

import os
import shutil
import stat
from contextlib import suppress
from pathlib import Path

from agent_fleet.domain.security import path_is_within

_MAX_GIT_POINTER_BYTES = 4096


def untrusted_executable_roots(cwd: Path, *extra_roots: Path) -> tuple[Path, ...]:
    """Return caller-controlled roots without invoking repository tooling.

    A command can begin below the repository root, so excluding only ``cwd``
    would still permit a sibling ``bin`` directory owned by the repository.
    Every ancestor with a Git marker is included; taking all markers prevents a
    nested untrusted marker from hiding an outer repository boundary.
    """

    seeds: set[Path] = set()
    for supplied in (cwd, *extra_roots):
        lexical = Path(os.path.abspath(supplied))
        seeds.add(lexical)
        with suppress(OSError):
            seeds.add(lexical.resolve())
    roots = set(seeds)
    for seed in seeds:
        for candidate in (seed, *seed.parents):
            marker = candidate / ".git"
            try:
                marker_stat = marker.lstat()
            except FileNotFoundError:
                continue
            except OSError:
                roots.add(Path(candidate.anchor))
            else:
                roots.add(candidate)
                with suppress(OSError):
                    roots.add(candidate.resolve())
                if stat.S_ISDIR(marker_stat.st_mode):
                    try:
                        resolved_marker = marker.resolve(strict=True)
                    except OSError:
                        roots.add(Path(candidate.anchor))
                    else:
                        roots.update({resolved_marker, resolved_marker.parent})
                    continue
                try:
                    git_dirs = _git_file_roots(marker, marker_stat)
                except (OSError, UnicodeError, ValueError):
                    roots.add(Path(candidate.anchor))
                    continue
                roots.update(git_dirs)
    return tuple(sorted(roots, key=str))


def _git_file_roots(marker: Path, marker_stat: os.stat_result) -> set[Path]:
    if not stat.S_ISREG(marker_stat.st_mode) or marker_stat.st_size > _MAX_GIT_POINTER_BYTES:
        raise ValueError("unsafe Git marker")
    pointer = _read_single_path(marker, prefix="gitdir: ")
    roots = _path_variants(pointer)
    resolved_git_dir = pointer.resolve(strict=True)
    common_marker = resolved_git_dir / "commondir"
    try:
        common_stat = common_marker.lstat()
    except FileNotFoundError:
        common_roots = {resolved_git_dir}
    else:
        if not stat.S_ISREG(common_stat.st_mode):
            raise ValueError("unsafe Git common-dir marker")
        common_roots = _path_variants(_read_single_path(common_marker))
    roots.update(common_roots)
    for root in tuple(roots):
        for candidate in (root, *root.parents):
            if candidate.name == ".git":
                roots.update({candidate, candidate.parent})
                break
    return roots


def _read_single_path(path: Path, *, prefix: str = "") -> Path:
    file_stat = path.lstat()
    if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_size > _MAX_GIT_POINTER_BYTES:
        raise ValueError("unsafe Git pointer file")
    text = path.read_text(encoding="utf-8")
    if "\x00" in text or len(text.encode("utf-8")) > _MAX_GIT_POINTER_BYTES:
        raise ValueError("unsafe Git pointer content")
    lines = text.splitlines()
    if len(lines) != 1 or not lines[0].startswith(prefix):
        raise ValueError("malformed Git pointer content")
    raw_value = lines[0][len(prefix) :]
    if not raw_value:
        raise ValueError("empty Git pointer")
    value = Path(raw_value)
    return value if value.is_absolute() else path.parent / value


def _path_variants(path: Path) -> set[Path]:
    lexical = Path(os.path.abspath(path))
    return {lexical, lexical.resolve(strict=True)}


def trusted_search_path(cwd: Path, *extra_roots: Path) -> str:
    """Keep only absolute, existing PATH directories outside untrusted roots."""

    forbidden = untrusted_executable_roots(cwd, *extra_roots)
    safe_entries: list[str] = []
    for raw_entry in os.environ.get("PATH", os.defpath).split(os.pathsep):
        if not raw_entry:
            continue
        entry = Path(raw_entry)
        if not entry.is_absolute():
            continue
        try:
            resolved = entry.resolve(strict=True)
        except OSError:
            continue
        if not resolved.is_dir() or any(path_is_within(resolved, root) for root in forbidden):
            continue
        safe_entries.append(str(resolved))
    return os.pathsep.join(dict.fromkeys(safe_entries))


def resolve_trusted_executable(
    requested: str,
    cwd: Path,
    *extra_roots: Path,
    expected_name: str | None = None,
) -> str | None:
    """Resolve an executable and reject repository/state-owned candidates."""

    search_path = trusted_search_path(cwd, *extra_roots)
    requested_path = Path(requested)
    try:
        candidate = (
            requested_path.resolve(strict=True)
            if requested_path.is_absolute()
            else Path(found).resolve(strict=True)
            if (found := shutil.which(requested, path=search_path)) is not None
            else None
        )
    except OSError:
        return None
    if candidate is None or not candidate.is_file():
        return None
    if expected_name is not None and candidate.name != expected_name:
        return None
    if any(
        path_is_within(candidate, root) for root in untrusted_executable_roots(cwd, *extra_roots)
    ):
        return None
    return str(candidate)


def resolve_fixed_executable(
    candidates: tuple[Path, ...],
    *,
    expected_name: str,
) -> str | None:
    """Resolve only an audited absolute-path allowlist, never ambient ``PATH``.

    This is the stricter boundary used for the Docker control-plane client.  A
    repository can influence the process environment but cannot add a candidate
    location to this list.
    """

    for requested in candidates:
        if not requested.is_absolute():
            raise ValueError("fixed executable candidates must be absolute")
        try:
            candidate = requested.resolve(strict=True)
            candidate_stat = candidate.stat()
        except OSError:
            continue
        if (
            candidate.name != expected_name
            or not stat.S_ISREG(candidate_stat.st_mode)
            or candidate_stat.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
            or not os.access(candidate, os.X_OK)
        ):
            continue
        return str(candidate)
    return None
