"""Immutable organization generations and exact reviewable file evolution."""

from __future__ import annotations

import difflib
from datetime import datetime, timedelta
from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.fleet_patch import validate_fleet_patch
from agent_fleet.domain.models import (
    EventId,
    FleetPatch,
    FleetPatchOperation,
    Project,
    ProjectId,
    RunId,
    Sha256,
)
from agent_fleet.domain.organization_tree import (
    OperationId,
    OrganizationDirectory,
    OrganizationFile,
    OrganizationTree,
    PreparedPublication,
)
from agent_fleet.domain.repository_boundary import OrganizationRepositoryBoundary
from agent_fleet.domain.security import Redactor, canonical_json_hash

MAX_DIFF_BYTES = 12_000_000


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def _utc(value: datetime) -> datetime:
    if value.utcoffset() != timedelta(0):
        raise ValueError("organization timestamps require UTC")
    return value


class OrganizationAdmission(_Record):
    project_id: ProjectId
    revision: int = Field(ge=0, le=1_000_000_000)
    tree_sha256: Sha256
    config_snapshot_sha256: Sha256


class OrganizationHead(OrganizationAdmission):
    project_sha256: Sha256
    pending_operation_id: OperationId | None = None
    audit_event_id: EventId

    @property
    def admission(self) -> OrganizationAdmission:
        return OrganizationAdmission(
            project_id=self.project_id,
            revision=self.revision,
            tree_sha256=self.tree_sha256,
            config_snapshot_sha256=self.config_snapshot_sha256,
        )


class OrganizationVersion(_Record):
    project_id: ProjectId
    version: int = Field(ge=0, le=1_000_000_000)
    predecessor_version: int | None = Field(default=None, ge=0)
    predecessor_sha256: Sha256 | None = None
    tree_sha256: Sha256
    config_snapshot_sha256: Sha256
    project_sha256: Sha256
    operation_id: OperationId | None = None
    created_at: datetime
    audit_event_id: EventId

    _created_utc = field_validator("created_at")(_utc)

    @model_validator(mode="after")
    def ancestry(self) -> OrganizationVersion:
        if self.version == 0:
            if (
                self.predecessor_version is not None
                or self.predecessor_sha256 is not None
                or self.operation_id is not None
            ):
                raise ValueError("baseline organization version cannot claim an applied operation")
        elif (
            self.predecessor_version != self.version - 1
            or self.predecessor_sha256 is None
            or self.operation_id is None
        ):
            raise ValueError("organization versions require an exact predecessor and operation")
        return self

    @property
    def admission(self) -> OrganizationAdmission:
        return OrganizationAdmission(
            project_id=self.project_id,
            revision=self.version,
            tree_sha256=self.tree_sha256,
            config_snapshot_sha256=self.config_snapshot_sha256,
        )


class FleetPatchSemanticChange(_Record):
    path: str = Field(min_length=8, max_length=4096)
    operation: FleetPatchOperation
    category: Literal[
        "role_guidance", "workflow", "verification", "verification_skill", "documentation"
    ]
    before_sha256: Sha256 | None = None
    after_sha256: Sha256 | None = None


class OrganizationPublicationResult(_Record):
    proposal_id: str = Field(pattern=r"^fpatch_[0-9a-f]{32}$")
    operation_id: OperationId
    status: Literal["committed", "aborted"]
    version: OrganizationVersion | None
    changed: bool
    cleanup_complete: bool | None
    warnings: tuple[str, ...] = Field(default=(), max_length=8)

    @model_validator(mode="after")
    def completion(self) -> OrganizationPublicationResult:
        if (self.status == "committed") != (self.version is not None):
            raise ValueError("publication result requires its exact committed version")
        if self.version is not None and self.version.operation_id != self.operation_id:
            raise ValueError("publication result version belongs to another operation")
        if self.status == "aborted" and self.changed:
            raise ValueError("an aborted publication did not apply an organization version")
        return self


class FleetPatchProposalRecord(_Record):
    patch: FleetPatch
    source_run_id: RunId
    base: OrganizationAdmission
    before_tree_sha256: Sha256
    after_tree_sha256: Sha256
    before_config_snapshot_sha256: Sha256
    after_config_snapshot_sha256: Sha256
    text_diff: str = Field(max_length=MAX_DIFF_BYTES)
    semantic_changes: tuple[FleetPatchSemanticChange, ...] = Field(min_length=1, max_length=128)
    created_at: datetime
    audit_event_id: EventId | None = None

    _created_utc = field_validator("created_at")(_utc)

    @field_validator("text_diff")
    @classmethod
    def bounded_diff(cls, value: str) -> str:
        if len(value.encode("utf-8")) > MAX_DIFF_BYTES:
            raise ValueError("organization diff exceeds its byte bound")
        return value

    @model_validator(mode="after")
    def bindings(self) -> FleetPatchProposalRecord:
        if (
            self.patch.project_id != self.base.project_id
            or self.patch.base_fleet_spec_sha256 != self.base.config_snapshot_sha256
            or self.before_config_snapshot_sha256 != self.base.config_snapshot_sha256
            or self.before_tree_sha256 != self.base.tree_sha256
        ):
            raise ValueError("organization proposal base identities must agree")
        return self

    @property
    def proposal_sha256(self) -> str:
        return canonical_json_hash(self.model_dump(mode="json", exclude={"audit_event_id"}))


class OrganizationOperation(_Record):
    operation_id: OperationId
    proposal_id: str = Field(pattern=r"^fpatch_[0-9a-f]{32}$")
    proposal_sha256: Sha256
    base: OrganizationAdmission
    project_before: Project
    project_sha256: Sha256
    publication: PreparedPublication
    repository_before: OrganizationRepositoryBoundary
    authorization: Literal["apply", "rollback"]
    status: Literal["prepared", "committed", "aborted", "recovery_required"]
    created_at: datetime
    updated_at: datetime
    audit_event_id: EventId
    committed_version: int | None = Field(default=None, ge=1)

    _created_utc = field_validator("created_at")(_utc)
    _updated_utc = field_validator("updated_at")(_utc)

    @model_validator(mode="after")
    def identities(self) -> OrganizationOperation:
        if (
            self.operation_id != self.publication.operation_id
            or self.base.project_id != self.project_before.project_id
            or self.publication.project_id != self.base.project_id
            or self.publication.repository_identity != self.project_before.identity_hash
            or self.publication.before_sha256 != self.base.tree_sha256
            or self.project_sha256
            != canonical_json_hash(self.project_before.model_dump(mode="json"))
            or self.updated_at < self.created_at
            or (self.status == "committed") != (self.committed_version is not None)
            or (
                self.committed_version is not None
                and self.committed_version != self.base.revision + 1
            )
        ):
            raise ValueError("organization operation identities or lifecycle disagree")
        return self


def evolve_tree(
    before: OrganizationTree, patch: FleetPatch, *, rollback_target: OrganizationTree | None = None
) -> OrganizationTree:
    """Apply exact file operations in memory, preserving modes and empty directories."""
    before = OrganizationTree.model_validate_json(before.model_dump_json())
    patch = FleetPatch.model_validate_json(patch.model_dump_json())
    validate_fleet_patch(
        patch, current_fleet_spec_sha256=patch.base_fleet_spec_sha256, redactor=Redactor()
    )
    files = {item.path: item for item in before.files}
    directories = {item.path: item for item in before.directories}
    root_xattrs = directories["."].xattrs
    for change in patch.changes:
        path = change.path.removeprefix(".fleet/")
        prior = files.get(path)
        if (
            (change.operation is FleetPatchOperation.ADD and prior is not None)
            or (
                change.operation is not FleetPatchOperation.ADD
                and (prior is None or prior.sha256 != change.before_sha256)
            )
            or path in directories
        ):
            raise FleetError(
                ErrorCode.CONFIG_INVALID,
                "FleetPatch file identities conflict with the complete tree.",
                "Create a new proposal from the exact current organization.",
            )
        if change.operation is FleetPatchOperation.REMOVE:
            del files[path]
            continue
        if change.content is None or change.after_sha256 is None:
            raise ValueError("FleetPatch content is missing")
        files[path] = (
            prior.model_copy(update={"content": change.content, "sha256": change.after_sha256})
            if prior is not None
            else OrganizationFile(
                path=path,
                content=change.content,
                sha256=change.after_sha256,
                mode=0o600,
                xattrs=root_xattrs,
            )
        )
        parent = PurePosixPath(path).parent
        while str(parent) != ".":
            directories.setdefault(
                str(parent), OrganizationDirectory(path=str(parent), mode=0o700, xattrs=root_xattrs)
            )
            parent = parent.parent
    result = OrganizationTree(
        files=tuple(files[path] for path in sorted(files)),
        directories=tuple(directories[path] for path in sorted(directories)),
    )
    if rollback_target is not None:
        rollback_target = OrganizationTree.model_validate_json(rollback_target.model_dump_json())
        if patch.rollback_of is None or [
            (item.path, item.content, item.sha256) for item in result.files
        ] != [(item.path, item.content, item.sha256) for item in rollback_target.files]:
            raise ValueError("rollback target must restore exactly the inverse file contents")
        return rollback_target
    return result


def describe_fleet_patch(
    before: OrganizationTree,
    after: OrganizationTree,
    patch: FleetPatch,
    *,
    rollback_target: OrganizationTree | None = None,
) -> tuple[str, tuple[FleetPatchSemanticChange, ...]]:
    """Derive deterministic text and typed file semantics, never model-written claims."""
    if evolve_tree(before, patch, rollback_target=rollback_target) != after:
        raise ValueError("prospective organization tree is not the exact FleetPatch result")
    old = {item.path: item.content for item in before.files}
    new = {item.path: item.content for item in after.files}
    chunks: list[str] = []
    semantics: list[FleetPatchSemanticChange] = []
    for change in sorted(patch.changes, key=lambda item: item.path):
        path = change.path.removeprefix(".fleet/")
        for line in difflib.unified_diff(
            old.get(path, "").splitlines(keepends=True),
            new.get(path, "").splitlines(keepends=True),
            fromfile="a/" + change.path if path in old else "/dev/null",
            tofile="b/" + change.path if path in new else "/dev/null",
            lineterm="\n",
        ):
            chunks.append(
                line if line.endswith("\n") else line + "\n\\ No newline at end of file\n"
            )
        category: Literal[
            "role_guidance", "workflow", "verification", "verification_skill", "documentation"
        ] = "documentation"
        if path.startswith("agents/"):
            category = "role_guidance"
        elif path.startswith("workflows/"):
            category = "workflow"
        elif path.startswith("skills/"):
            category = "verification_skill"
        elif path == "project/verification.yaml":
            category = "verification"
        semantics.append(
            FleetPatchSemanticChange(
                path=change.path,
                operation=change.operation,
                category=category,
                before_sha256=change.before_sha256,
                after_sha256=change.after_sha256,
            )
        )
    text = "".join(chunks)
    if len(text.encode("utf-8")) > MAX_DIFF_BYTES:
        raise ValueError("organization diff exceeds its byte bound")
    return text, tuple(semantics)
