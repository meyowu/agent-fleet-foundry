"""Canonical FleetPatch imports and bounded, protected proposal validation."""

from __future__ import annotations

import math
import re
from contextlib import suppress
from pathlib import PurePosixPath
from typing import cast

from pydantic import ValidationError

from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import (
    FleetPatch,
    FleetPatchContent,
    FleetPatchFileChange,
    FleetPatchOperation,
    FleetPatchPath,
    FleetPatchRationale,
)
from agent_fleet.domain.security import Redactor

__all__ = [
    "FleetPatch",
    "FleetPatchContent",
    "FleetPatchFileChange",
    "FleetPatchOperation",
    "FleetPatchPath",
    "FleetPatchRationale",
    "parse_and_validate_fleet_patch",
    "validate_fleet_patch",
]

MAX_RAW_FLEET_PATCH_DEPTH = 64
MAX_RAW_FLEET_PATCH_NODES = 10_000
MAX_RAW_FLEET_PATCH_STRING_BYTES = 4_000_000
_SKILL_FILENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}\.yaml")


def parse_and_validate_fleet_patch(
    payload: object,
    *,
    current_fleet_spec_sha256: str,
    redactor: Redactor,
) -> FleetPatch:
    """Parse untrusted built-in JSON before any proposal use or persistence."""

    patch = _parse_bounded_patch(payload, redactor)
    _validate_proposal_scope(patch, current_fleet_spec_sha256)
    return patch


def _parse_bounded_patch(payload: object, redactor: Redactor) -> FleetPatch:
    if type(payload) is not dict or not _is_builtin_json_value(payload):
        raise _invalid("FleetPatch input must be a bounded plain JSON object.")
    if redactor.contains_secret_data(payload):
        raise _invalid("FleetPatch contains a registered secret.")
    patch: FleetPatch | None = None
    with suppress(ValidationError, ValueError, TypeError):
        patch = FleetPatch.model_validate(payload)
    # Raise outside the parser handler: even __context__ must not retain raw input.
    if patch is None:
        raise _invalid("FleetPatch does not match the required schema.")
    return patch


def _is_builtin_json_value(value: object) -> bool:
    stack: list[tuple[object, int]] = [(value, 0)]
    seen_containers: set[int] = set()
    visited_nodes = 0
    string_bytes = 0
    while stack:
        item, depth = stack.pop()
        visited_nodes += 1
        if visited_nodes > MAX_RAW_FLEET_PATCH_NODES:
            return False
        if type(item) is str:
            size = _bounded_utf8_size(item, MAX_RAW_FLEET_PATCH_STRING_BYTES - string_bytes)
            if size is None:
                return False
            string_bytes += size
            continue
        if item is None or type(item) is int or type(item) is bool:
            continue
        if type(item) is float:
            if not math.isfinite(item):
                return False
            continue
        if (
            type(item) is not dict and type(item) is not list
        ) or depth >= MAX_RAW_FLEET_PATCH_DEPTH:
            return False
        identity = id(item)
        if identity in seen_containers:
            return False
        seen_containers.add(identity)
        if type(item) is dict:
            mapping = cast(dict[object, object], item)
            if visited_nodes + len(stack) + len(mapping) > MAX_RAW_FLEET_PATCH_NODES:
                return False
            for key, child in mapping.items():
                if type(key) is not str:
                    return False
                size = _bounded_utf8_size(key, MAX_RAW_FLEET_PATCH_STRING_BYTES - string_bytes)
                if size is None:
                    return False
                string_bytes += size
                stack.append((child, depth + 1))
        else:
            sequence = cast(list[object], item)
            if visited_nodes + len(stack) + len(sequence) > MAX_RAW_FLEET_PATCH_NODES:
                return False
            stack.extend((child, depth + 1) for child in sequence)
    return True


def _bounded_utf8_size(value: str, remaining: int) -> int | None:
    # Character count is a cheap lower bound; never encode an unbounded string.
    if len(value) > remaining:
        return None
    size: int | None = None
    with suppress(UnicodeError):
        size = len(value.encode("utf-8"))
    return size if size is not None and size <= remaining else None


def _typed_payload(patch: FleetPatch) -> dict[str, object]:
    """Inspect exact schema instances without invoking Pydantic serialization."""

    if type(patch) is not FleetPatch or len(vars(patch)) > len(FleetPatch.model_fields):
        raise _invalid("FleetPatch does not match the required schema.")
    payload: dict[str, object] = dict(vars(patch))
    changes = payload.get("changes")
    if type(changes) is not list or not 1 <= len(changes) <= 128:
        raise _invalid("FleetPatch does not match the required schema.")
    records: list[dict[str, object]] = []
    for change in changes:
        if type(change) is not FleetPatchFileChange or len(vars(change)) > len(
            FleetPatchFileChange.model_fields
        ):
            raise _invalid("FleetPatch does not match the required schema.")
        record: dict[str, object] = dict(vars(change))
        operation = record.get("operation")
        if type(operation) is not FleetPatchOperation:
            raise _invalid("FleetPatch does not match the required schema.")
        record["operation"] = operation.value
        records.append(record)
    payload["changes"] = records
    return payload


def validate_fleet_patch(
    patch: FleetPatch,
    *,
    current_fleet_spec_sha256: str,
    redactor: Redactor,
) -> None:
    # model_copy/model_construct and in-place mutations do not run validators.
    # Reparse only after bounding and scanning their plain field representation.
    validated = _parse_bounded_patch(_typed_payload(patch), redactor)
    _validate_proposal_scope(validated, current_fleet_spec_sha256)


def _validate_proposal_scope(patch: FleetPatch, current_fleet_spec_sha256: str) -> None:
    if patch.base_fleet_spec_sha256 != current_fleet_spec_sha256:
        raise _invalid("FleetPatch base hash does not match the current FleetSpec.")
    seen: set[tuple[str, ...]] = set()
    for change in patch.changes:
        folded_path = tuple(part.casefold() for part in PurePosixPath(change.path).parts)
        if folded_path in seen:
            raise _invalid("FleetPatch changes path more than once.")
        if any(
            folded_path[: len(prior)] == prior or prior[: len(folded_path)] == folded_path
            for prior in seen
        ):
            raise _invalid("FleetPatch change paths contain an ancestor collision.")
        seen.add(folded_path)
        if not _is_allowed_organization_path(change.path):
            raise _invalid("FleetPatch targets a protected path.")


def _is_allowed_organization_path(value: str) -> bool:
    path = PurePosixPath(value)
    relative = PurePosixPath(*path.parts[1:])
    if not relative.parts:
        return False
    first = relative.parts[0]
    if first in {"agents", "workflows"}:
        return len(relative.parts) > 1
    if first == "skills":
        return len(relative.parts) == 2 and _SKILL_FILENAME.fullmatch(relative.name) is not None
    return str(relative) in {
        "project/charter.md",
        "project/architecture.md",
        "project/verification.yaml",
        "README.md",
    }


def _invalid(message: str) -> FleetError:
    return FleetError(
        ErrorCode.CONFIG_INVALID,
        message,
        "Create a new patch against the current FleetSpec using only reviewable "
        "organization files.",
    )
