"""User-owned model selections and immutable per-run routing snapshots."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import (
    Field,
    StrictBool,
    StrictInt,
    StringConstraints,
    field_validator,
    model_validator,
)

from agent_fleet.domain.models import (
    FrozenStrictModel,
    ProjectId,
    RoleId,
    RunId,
    RuntimeConfiguration,
    Sha256,
)
from agent_fleet.domain.security import canonical_json_hash

ProfileName = Annotated[
    str, StringConstraints(strict=True, min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_-]*$")
]
Revision = Annotated[StrictInt, Field(ge=1, le=2**63 - 1)]


def configuration_hash(configuration: RuntimeConfiguration) -> str:
    return canonical_json_hash(configuration.model_dump(mode="json"))


def validate_profile_configuration(configuration: RuntimeConfiguration) -> None:
    """A profile is not an endpoint configuration or extensible adapter registry."""
    if configuration.runtime_name not in {"fake", "pydantic-ai"}:
        raise ValueError("model profile runtime is unsupported")
    if configuration.runtime_name == "pydantic-ai" and (
        configuration.provider_model is None
        or configuration.provider_model.partition(":")[0] not in {"openai", "openai-chat"}
    ):
        raise ValueError("model profile provider is unsupported")


class ModelProfile(FrozenStrictModel):
    schema_version: Literal[1] = 1
    name: ProfileName
    revision: Revision
    enabled: StrictBool = True
    configuration: RuntimeConfiguration

    @model_validator(mode="after")
    def validate_configuration(self) -> Self:
        validate_profile_configuration(self.configuration)
        return self

    @property
    def configuration_sha256(self) -> str:
        return configuration_hash(self.configuration)

    def safe_projection(self) -> dict[str, object]:
        return {
            "name": self.name,
            "revision": self.revision,
            "enabled": self.enabled,
            "configuration": self.configuration.model_dump(mode="json", exclude={"credential_ref"}),
            "credential_required": self.configuration.credential_ref is not None,
            "configuration_sha256": self.configuration_sha256,
        }


class ProjectModelSelection(FrozenStrictModel):
    schema_version: Literal[1] = 1
    project_id: ProjectId
    repository_identity: Sha256
    revision: Revision
    default_profile: ProfileName | None = None
    role_overrides: dict[RoleId, ProfileName] = Field(default_factory=dict, max_length=64)
    permitted_profiles: tuple[ProfileName, ...] = Field(default=(), max_length=128)

    @model_validator(mode="after")
    def validate_approval(self) -> Self:
        if tuple(sorted(set(self.permitted_profiles))) != self.permitted_profiles:
            raise ValueError("permitted profiles must be unique and sorted")
        selected = set(self.role_overrides.values())
        if self.default_profile is not None:
            selected.add(self.default_profile)
        if not selected.issubset(self.permitted_profiles):
            raise ValueError("selected profiles require exact user approval")
        return self


class ResolvedModelBinding(FrozenStrictModel):
    role_id: RoleId
    source: Literal["override", "repository_preference", "default", "legacy"]
    profile_name: ProfileName | None = None
    profile_revision: Revision | None = None
    configuration: RuntimeConfiguration
    configuration_sha256: Sha256

    @model_validator(mode="after")
    def validate_binding(self) -> Self:
        validate_profile_configuration(self.configuration)
        if self.configuration_sha256 != configuration_hash(self.configuration):
            raise ValueError("model configuration hash is inconsistent")
        if self.source == "legacy":
            if self.profile_name is not None or self.profile_revision is not None:
                raise ValueError("legacy binding must not claim a model profile")
        elif self.profile_name is None or self.profile_revision is None:
            raise ValueError("profile binding requires an exact profile revision")
        return self

    def safe_projection(self) -> dict[str, object]:
        return {
            "role_id": self.role_id,
            "source": self.source,
            "profile_name": self.profile_name,
            "profile_revision": self.profile_revision,
            "configuration_sha256": self.configuration_sha256,
            "configuration": self.configuration.model_dump(mode="json", exclude={"credential_ref"}),
        }


class RunModelBindings(FrozenStrictModel):
    schema_version: Literal[1] = 1
    root_run_id: RunId
    project_id: ProjectId
    repository_identity: Sha256
    selection_revision: Revision | None = None
    created_at: datetime
    roles: dict[RoleId, ResolvedModelBinding] = Field(min_length=1, max_length=64)

    @field_validator("created_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        offset = value.utcoffset()
        if value.tzinfo is None or offset is None or offset.total_seconds():
            raise ValueError("model binding timestamp must be UTC")
        return value

    @model_validator(mode="after")
    def validate_roles(self) -> Self:
        profiles: dict[str, tuple[int | None, str]] = {}
        for role, binding in self.roles.items():
            if role != binding.role_id:
                raise ValueError("model binding role identity is inconsistent")
            if (self.selection_revision is None) != (binding.source == "legacy"):
                raise ValueError("legacy routing requires absent user selection")
            if binding.profile_name is not None:
                identity = (binding.profile_revision, binding.configuration_sha256)
                if profiles.setdefault(binding.profile_name, identity) != identity:
                    raise ValueError("one profile cannot resolve to multiple revisions in a run")
        return self

    @property
    def bindings_sha256(self) -> str:
        return canonical_json_hash(self.model_dump(mode="json"))

    def safe_projection(self) -> dict[str, object]:
        return {
            "root_run_id": self.root_run_id,
            "project_id": self.project_id,
            "selection_revision": self.selection_revision,
            "bindings_sha256": self.bindings_sha256,
            "roles": {role: binding.safe_projection() for role, binding in self.roles.items()},
        }


class ModelConfigurationAudit(FrozenStrictModel):
    schema_version: Literal[1] = 1
    sequence: Revision
    action: Literal["profile.set", "profile.remove", "selection.set", "run.bind"]
    target: Annotated[str, StringConstraints(strict=True, max_length=128)]
    revision: Revision
    record_sha256: Sha256
    previous_sha256: Sha256 | None = None
    occurred_at: datetime

    @field_validator("occurred_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        return RunModelBindings.require_utc(value)

    @property
    def audit_sha256(self) -> str:
        return canonical_json_hash(self.model_dump(mode="json"))
