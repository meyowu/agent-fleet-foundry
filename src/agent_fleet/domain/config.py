"""Strict repository-owned configuration models for the Phase 0/1 subset."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from agent_fleet.domain.models import (
    ActionId,
    AgentLifecycle,
    RoleId,
    Sha256,
    StrictModel,
    WorkflowId,
)
from agent_fleet.domain.security import sha256_bytes

_LEGACY_ROLE_LABELS: dict[str, frozenset[str]] = {
    "cos": frozenset({"chief-of-staff"}),
    "engineer": frozenset({"software-engineer"}),
}


class ConfigModel(StrictModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Metadata(ConfigModel):
    name: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._-]+$")


class RuntimeRequest(ConfigModel):
    adapter: Literal["fake"]
    required_capabilities: list[Literal["structured_output", "tool_calling"]] = Field(
        alias="requiredCapabilities"
    )


class SandboxRequest(ConfigModel):
    provider: Literal["fake"]
    network_mode: Literal["none"] = Field(alias="networkMode")


class AgentRequest(ConfigModel):
    role: RoleId
    lifecycle: AgentLifecycle
    instructions: str
    allowed_tools: list[str] = Field(alias="allowedTools")
    may_delegate_to: list[RoleId] = Field(default_factory=list, alias="mayDelegateTo")
    max_steps: int = Field(alias="maxSteps", ge=1, le=100)


class WorkflowRequest(ConfigModel):
    definition: str
    max_repair_iterations: int = Field(alias="maxRepairIterations", ge=0, le=5)


class ProjectFiles(ConfigModel):
    charter: str
    architecture: str
    verification: str


class RequestedPermission(ConfigModel):
    principal_role: RoleId = Field(alias="principalRole")
    action: ActionId
    resource: str


class FleetSpecBody(ConfigModel):
    runtime: RuntimeRequest
    sandbox: SandboxRequest
    agents: dict[RoleId, AgentRequest]
    workflows: dict[WorkflowId, WorkflowRequest]
    project: ProjectFiles
    requested_permissions: list[RequestedPermission] = Field(alias="requestedPermissions")

    @model_validator(mode="after")
    def validate_references(self) -> FleetSpecBody:
        if "cos" not in self.agents:
            raise ValueError("agents must define the user-facing cos role")
        if not self.workflows:
            raise ValueError("at least one workflow must be defined")
        known_roles = set(self.agents)
        for role_id, request in self.agents.items():
            if request.role != role_id and request.role not in _LEGACY_ROLE_LABELS.get(
                role_id, frozenset()
            ):
                raise ValueError(
                    f"agent mapping key {role_id!r} must match its role field {request.role!r}"
                )
            missing = set(request.may_delegate_to) - known_roles
            if missing:
                raise ValueError(f"agent {role_id!r} delegates to missing roles: {sorted(missing)}")
        missing_principals = {
            request.principal_role
            for request in self.requested_permissions
            if request.principal_role not in known_roles
        }
        if missing_principals:
            raise ValueError(
                f"requested permissions reference missing roles: {sorted(missing_principals)}"
            )
        return self


class FleetSpec(ConfigModel):
    api_version: Literal["agentfleet.dev/v1alpha1"] = Field(alias="apiVersion")
    kind: Literal["Fleet"]
    metadata: Metadata
    spec: FleetSpecBody


class VerificationCommand(ConfigModel):
    executable: str = Field(min_length=1, pattern=r"^(?:[A-Za-z0-9._+-]+|\./[A-Za-z0-9._+-]+)$")
    argv: list[str]
    cwd: str
    timeout_seconds: int = Field(alias="timeoutSeconds", ge=1, le=3600)
    network_required: Literal[False] = Field(alias="networkRequired")


class VerificationProfile(ConfigModel):
    api_version: Literal["agentfleet.dev/v1alpha1"] = Field(alias="apiVersion")
    kind: Literal["VerificationProfile"]
    commands: dict[str, VerificationCommand]
    required_for_code_change: list[str] = Field(alias="requiredForCodeChange")

    @model_validator(mode="after")
    def commands_exist(self) -> VerificationProfile:
        missing = set(self.required_for_code_change) - set(self.commands)
        if missing:
            raise ValueError(f"required verification commands are missing: {sorted(missing)}")
        return self


class ConfigSnapshotFile(ConfigModel):
    path: str
    sha256: Sha256
    content: str = Field(max_length=512_000)

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if (
            not value
            or value.startswith("/")
            or "\\" in value
            or ".." in path.parts
            or path.as_posix() != value
        ):
            raise ValueError("config snapshot paths must be canonical and repository-relative")
        return value

    @model_validator(mode="after")
    def validate_content_hash(self) -> ConfigSnapshotFile:
        if self.sha256 != sha256_bytes(self.content.encode("utf-8")):
            raise ValueError("config snapshot file hash does not match its UTF-8 content")
        return self


class ConfigSnapshot(ConfigModel):
    api_version: Literal["agentfleet.dev/v1alpha1"] = "agentfleet.dev/v1alpha1"
    kind: Literal["ConfigSnapshot"] = "ConfigSnapshot"
    files: list[ConfigSnapshotFile] = Field(min_length=1, max_length=256)

    @field_validator("files")
    @classmethod
    def validate_files(cls, values: list[ConfigSnapshotFile]) -> list[ConfigSnapshotFile]:
        paths = [item.path for item in values]
        if paths != sorted(set(paths)) or "fleet.yaml" not in paths:
            raise ValueError("config snapshot files must be unique, sorted, and include fleet.yaml")
        return values
