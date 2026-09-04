"""Schema and protected-boundary validation for future FleetPatch operations."""

from __future__ import annotations

from enum import StrEnum
from pathlib import PurePosixPath
from typing import Annotated, Literal, cast

from pydantic import Field, StringConstraints, ValidationError, field_validator, model_validator

from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import FleetPatchId, ProjectId, Sha256, StrictModel
from agent_fleet.domain.security import Redactor, sha256_bytes

FleetPatchPath = Annotated[
    str,
    StringConstraints(
        min_length=8,
        max_length=4096,
        pattern=r"^\.fleet/[^/\\\x00][^\\\x00]*$",
    ),
]
FleetPatchContent = Annotated[str, StringConstraints(max_length=1_000_000)]
FleetPatchRationale = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4096)
]
MAX_RAW_FLEET_PATCH_DEPTH = 64
MAX_RAW_FLEET_PATCH_NODES = 10_000


class FleetPatchOperation(StrEnum):
    ADD = "add"
    REPLACE = "replace"
    REMOVE = "remove"


class FleetPatchFileChange(StrictModel):
    operation: FleetPatchOperation
    path: FleetPatchPath
    before_sha256: Sha256 | None = None
    after_sha256: Sha256 | None = None
    content: FleetPatchContent | None = None

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if (
            not value
            or "\x00" in value
            or value.startswith("/")
            or "\\" in value
            or not path.parts
            or ".." in path.parts
            or path.parts[0] != ".fleet"
            or path.as_posix() != value
        ):
            raise ValueError(
                "FleetPatch paths must be canonical repository-relative paths beneath .fleet/"
            )
        return value

    @model_validator(mode="after")
    def validate_operation_content(self) -> FleetPatchFileChange:
        if self.operation is FleetPatchOperation.ADD:
            if self.before_sha256 is not None:
                raise ValueError("add changes cannot declare a prior content hash")
            self._require_content_hash()
        elif self.operation is FleetPatchOperation.REPLACE:
            if self.before_sha256 is None:
                raise ValueError("replace changes require a prior content hash")
            self._require_content_hash()
        elif (
            self.before_sha256 is None or self.after_sha256 is not None or self.content is not None
        ):
            raise ValueError(
                "remove changes require a prior hash and cannot contain an after hash or content"
            )
        return self

    def _require_content_hash(self) -> None:
        if self.content is None or self.after_sha256 is None:
            raise ValueError("add/replace changes require content and its SHA-256 hash")
        actual = sha256_bytes(self.content.encode("utf-8"))
        if self.after_sha256 != actual:
            raise ValueError("FleetPatch after hash does not match its UTF-8 content")


class FleetPatch(StrictModel):
    api_version: Literal["agentfleet.dev/v1alpha1"] = "agentfleet.dev/v1alpha1"
    kind: Literal["FleetPatch"] = "FleetPatch"
    fleet_patch_id: FleetPatchId
    project_id: ProjectId
    base_fleet_spec_sha256: Sha256
    changes: list[FleetPatchFileChange] = Field(min_length=1, max_length=128)
    rationale: FleetPatchRationale
    rollback_of: FleetPatchId | None = None


def parse_and_validate_fleet_patch(
    payload: object,
    *,
    current_fleet_spec_sha256: str,
    redactor: Redactor,
) -> FleetPatch:
    """Parse an untrusted proposal without echoing registered secrets on failure."""

    if not _is_builtin_json_value(payload) or type(payload) is not dict:
        raise _invalid("FleetPatch input must be a plain JSON object.")
    if redactor.contains_secret_data(payload):
        raise _invalid("FleetPatch contains a registered secret.")
    try:
        patch = FleetPatch.model_validate(payload)
    except ValidationError:
        raise _invalid("FleetPatch does not match the required schema.") from None
    validate_fleet_patch(
        patch,
        current_fleet_spec_sha256=current_fleet_spec_sha256,
        redactor=redactor,
    )
    return patch


def _is_builtin_json_value(value: object) -> bool:
    stack: list[tuple[object, int]] = [(value, 0)]
    seen_containers: set[int] = set()
    visited_nodes = 0
    while stack:
        item, depth = stack.pop()
        visited_nodes += 1
        if visited_nodes > MAX_RAW_FLEET_PATCH_NODES:
            return False
        if item is None or type(item) in {str, int, float, bool}:
            continue
        if type(item) not in {dict, list} or depth >= MAX_RAW_FLEET_PATCH_DEPTH:
            return False
        identity = id(item)
        if identity in seen_containers:
            return False
        seen_containers.add(identity)
        if type(item) is dict:
            mapping = cast(dict[object, object], item)
            if visited_nodes + len(mapping) > MAX_RAW_FLEET_PATCH_NODES:
                return False
            for key, child in mapping.items():
                if type(key) is not str:
                    return False
                stack.append((child, depth + 1))
        else:
            sequence = cast(list[object], item)
            if visited_nodes + len(sequence) > MAX_RAW_FLEET_PATCH_NODES:
                return False
            stack.extend((child, depth + 1) for child in sequence)
    return True


def validate_fleet_patch(
    patch: FleetPatch,
    *,
    current_fleet_spec_sha256: str,
    redactor: Redactor,
) -> None:
    if redactor.contains_secret_data(patch.model_dump(mode="json")):
        raise _invalid("FleetPatch contains a registered secret.")
    if patch.base_fleet_spec_sha256 != current_fleet_spec_sha256:
        raise _invalid("FleetPatch base hash does not match the current FleetSpec.")
    seen: set[tuple[str, ...]] = set()
    for change in patch.changes:
        canonical_path = PurePosixPath(change.path).as_posix()
        if canonical_path != change.path:
            raise _invalid(f"FleetPatch path is not canonical: {change.path!r}.")
        folded_path = tuple(part.casefold() for part in PurePosixPath(canonical_path).parts)
        if folded_path in seen:
            raise _invalid(f"FleetPatch changes path more than once: {change.path!r}.")
        seen.add(folded_path)
        if not _is_allowed_organization_path(change.path):
            raise _invalid(f"FleetPatch targets a protected path: {change.path!r}.")


def _is_allowed_organization_path(value: str) -> bool:
    path = PurePosixPath(value)
    relative = PurePosixPath(*path.parts[1:])
    if not relative.parts:
        return False
    first = relative.parts[0]
    if first in {"agents", "workflows"}:
        return len(relative.parts) > 1
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
