"""Canonical, component-aware repository scopes shared by policy and evidence."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import PurePosixPath


def _components(path: str) -> tuple[str, ...] | None:
    if (
        not path
        or len(path.encode("utf-8", errors="surrogatepass")) > 4096
        or "\\" in path
        or any(ord(character) < 32 or 0xD800 <= ord(character) <= 0xDFFF for character in path)
    ):
        return None
    parsed = PurePosixPath(path)
    if parsed.is_absolute() or str(parsed) != path or ".." in parsed.parts:
        return None
    if len(parsed.parts) > 64:
        return None
    return tuple(part.casefold() for part in parsed.parts)


def path_is_within(path: str, scopes: Iterable[str], *, forbidden: Iterable[str] = ()) -> bool:
    """Allow only an exact path/descendant; never widen a scope to its parent.

    Mutation scopes also reject ancestors of forbidden paths, so deleting a
    containing directory cannot bypass an excluded descendant.
    """

    parts = _components(path)
    allowed = [_components(scope) for scope in scopes]
    excluded = [_components(scope) for scope in forbidden]
    if parts is None or None in allowed or None in excluded:
        return False
    if any(
        item is not None and (parts[: len(item)] == item or item[: len(parts)] == parts)
        for item in excluded
    ):
        return False
    return any(item is not None and parts[: len(item)] == item for item in allowed)


def path_overlaps_scope(path: str, scopes: Iterable[str], *, forbidden: Iterable[str] = ()) -> bool:
    """Allow directory traversal toward a scope, with excluded leaves filtered.

    This is an observation/traversal predicate, not mutation authorization.
    A parent directory can be listed; each returned descendant must be checked.
    """

    parts = _components(path)
    allowed = [_components(scope) for scope in scopes]
    excluded = [_components(scope) for scope in forbidden]
    if parts is None or None in allowed or None in excluded:
        return False
    if any(item is not None and parts[: len(item)] == item for item in excluded):
        return False
    return any(
        item is not None and (parts[: len(item)] == item or item[: len(parts)] == parts)
        for item in allowed
    )
