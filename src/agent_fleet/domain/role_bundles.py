"""Versioned preview contracts; no execution or publication capability."""

from __future__ import annotations

import json
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from agent_fleet.domain.models import (
    ActionId,
    CommandSpec,
    FleetPatchFileChange,
    FrozenStrictModel,
    RoleId,
    Sha256,
    WorkflowId,
)
from agent_fleet.domain.security import canonical_json_hash

BundleId = Literal["general-change", "public-interface", "stateful-change", "design-guided"]
MAX_ADOPTION_BRIEF_BYTES = 16_384
MAX_BUNDLE_PREVIEW_BYTES = 1_048_576


class BundleRole(FrozenStrictModel):
    role_id: RoleId
    execution_kind: Literal["engineer", "verifier", "researcher", "architect"]
    description: str = Field(min_length=1, max_length=512)
    guidance: str = Field(min_length=1, max_length=2048)


class RoleBundleDefinition(FrozenStrictModel):
    bundle_id: BundleId
    version: int = Field(strict=True, ge=1, le=1)
    description: str = Field(min_length=1, max_length=512)
    roles: tuple[BundleRole, ...] = Field(min_length=2, max_length=4)

    @model_validator(mode="after")
    def unique_roles(self) -> Self:
        if len({role.role_id for role in self.roles}) != len(self.roles):
            raise ValueError("bundle roles must be distinct")
        if not {"engineer", "verifier"}.issubset(role.execution_kind for role in self.roles):
            raise ValueError("bundle needs independent implementation and verification roles")
        return self

    @property
    def sha256(self) -> str:
        return canonical_json_hash(self.model_dump(mode="json"))


class BundleCommand(FrozenStrictModel):
    command_id: ActionId
    definition: CommandSpec
    sha256: Sha256

    @model_validator(mode="after")
    def exact_definition(self) -> Self:
        if self.command_id != self.definition.command_id or self.sha256 != canonical_json_hash(
            self.definition.model_dump(mode="json")
        ):
            raise ValueError("bundle command identity is inconsistent")
        return self


class RoleBundlePreview(FrozenStrictModel):
    schema_version: Literal[1] = 1
    bundle: RoleBundleDefinition
    bundle_sha256: Sha256
    repository_identity: Sha256
    configuration_sha256: Sha256
    proposed_configuration_sha256: Sha256
    workflow_id: WorkflowId
    scopes: tuple[str, ...] = Field(min_length=1, max_length=32)
    commands: tuple[BundleCommand, ...] = Field(min_length=1, max_length=32)
    changes: tuple[FleetPatchFileChange, ...] = Field(min_length=1, max_length=8)
    patch: str = Field(max_length=MAX_BUNDLE_PREVIEW_BYTES)
    adoption_brief: str = Field(min_length=1, max_length=MAX_ADOPTION_BRIEF_BYTES)
    execution_authorized: Literal[False] = False
    publication_authorized: Literal[False] = False

    @field_validator("execution_authorized", "publication_authorized", mode="before")
    @classmethod
    def exact_false(cls, value: object) -> Literal[False]:
        if value is not False:
            raise ValueError("preview cannot grant authority")
        return False

    @model_validator(mode="after")
    def bounded_identity(self) -> Self:
        if self.bundle_sha256 != self.bundle.sha256:
            raise ValueError("bundle definition hash does not match")
        if (
            len(self.adoption_brief.encode("utf-8")) > MAX_ADOPTION_BRIEF_BYTES
            or "\n" in self.adoption_brief
            or "\r" in self.adoption_brief
        ):
            raise ValueError("adoption brief must fit one bounded Session input line")
        if len(json.dumps(self.model_dump(mode="json"), ensure_ascii=True).encode()) > (
            MAX_BUNDLE_PREVIEW_BYTES - 4096
        ):
            raise ValueError("bundle preview exceeds its bounded envelope allowance")
        return self
