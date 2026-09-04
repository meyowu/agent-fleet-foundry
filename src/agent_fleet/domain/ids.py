"""Opaque identifier generation."""

from __future__ import annotations

from enum import StrEnum
from uuid import uuid4


class IdPrefix(StrEnum):
    PROJECT = "prj"
    RUN = "run"
    TASK = "task"
    AGENT = "agent"
    EVENT = "evt"
    APPROVAL = "perm"
    GRANT = "grant"
    ARTIFACT = "art"
    INTENT = "intent"
    LEASE = "lease"
    CORRELATION = "corr"
    SANDBOX = "sandbox"
    WORKSPACE = "ws"


def new_id(prefix: IdPrefix) -> str:
    """Return a non-semantic UUID-backed identifier."""

    return f"{prefix.value}_{uuid4().hex}"
