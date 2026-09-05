"""Strict repository-owned configuration models for the Phase 0/1 subset."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from agent_fleet.domain.models import (
    ActionId,
    AgentLifecycle,
    CommandSpec,
    LogicalRepoPath,
    ProviderModelId,
    RoleId,
    RuntimeCapability,
    SandboxName,
    SandboxNetworkMode,
    Sha256,
    StrictModel,
    WorkflowId,
)
from agent_fleet.domain.security import sha256_bytes
from agent_fleet.domain.trust import canonical_trust_path

_LEGACY_ROLE_LABELS: dict[str, frozenset[str]] = {
    "cos": frozenset({"chief-of-staff"}),
    "engineer": frozenset({"software-engineer"}),
}


class ConfigModel(StrictModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Metadata(ConfigModel):
    name: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._-]+$")


class RuntimeRequest(ConfigModel):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        json_schema_extra={
            "allOf": [
                {
                    "if": {
                        "properties": {"adapter": {"const": "fake"}},
                        "required": ["adapter"],
                    },
                    "then": {"properties": {"providerModel": {"type": "null"}}},
                },
                {
                    "if": {
                        "properties": {"adapter": {"const": "pydantic-ai"}},
                        "required": ["adapter"],
                    },
                    "then": {
                        "properties": {"providerModel": {"type": "string"}},
                        "required": ["providerModel"],
                    },
                },
            ]
        },
    )

    adapter: Literal["fake", "pydantic-ai"]
    provider_model: ProviderModelId | None = Field(
        default=None,
        alias="providerModel",
        min_length=3,
        max_length=200,
        pattern=r"^[a-z][a-z0-9-]*:[A-Za-z0-9][A-Za-z0-9._:/-]*$",
    )
    required_capabilities: list[RuntimeCapability] = Field(
        alias="requiredCapabilities",
        min_length=1,
        max_length=8,
        json_schema_extra={
            "uniqueItems": True,
            "allOf": [
                {"contains": {"const": "structured_output"}},
                {"contains": {"const": "tool_calling"}},
            ],
        },
    )

    @model_validator(mode="after")
    def validate_runtime_selection(self) -> RuntimeRequest:
        if len(self.required_capabilities) != len(set(self.required_capabilities)):
            raise ValueError("runtime capabilities must be unique")
        required = {
            RuntimeCapability.STRUCTURED_OUTPUT,
            RuntimeCapability.TOOL_CALLING,
        }
        if not required.issubset(self.required_capabilities):
            raise ValueError("runtime must require structured_output and tool_calling capabilities")
        if self.adapter == "fake" and self.provider_model is not None:
            raise ValueError("fake runtime cannot declare a provider model")
        if self.adapter == "pydantic-ai" and self.provider_model is None:
            raise ValueError("pydantic-ai runtime requires providerModel")
        return self


class SandboxRequest(ConfigModel):
    provider: SandboxName
    network_mode: SandboxNetworkMode = Field(alias="networkMode")
    image: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]*$",
    )
    cpu_limit: float = Field(
        default=1.0,
        alias="cpuLimit",
        ge=0.001,
        le=16,
        multiple_of=0.001,
    )
    memory_mb: int = Field(default=512, alias="memoryMb", ge=64, le=32768)
    pids_limit: int = Field(default=128, alias="pidsLimit", ge=16, le=4096)
    shm_mb: int = Field(default=64, alias="shmMb", ge=16, le=1024)
    tmpfs_mb: int = Field(default=128, alias="tmpfsMb", ge=16, le=4096)

    @model_validator(mode="after")
    def validate_provider_configuration(self) -> SandboxRequest:
        if self.provider == "docker" and self.image is None:
            raise ValueError("docker sandbox requires an explicit local image reference")
        if self.provider != "docker" and self.image is not None:
            raise ValueError("only the docker sandbox accepts an image reference")
        if self.provider == "local-unsafe" and self.network_mode != "approved-unrestricted":
            raise ValueError("local-unsafe must declare approved-unrestricted networking")
        if self.provider != "local-unsafe" and self.network_mode != "none":
            raise ValueError("fake and docker sandboxes require networkMode=none")
        return self


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
    max_parallel_agents: int = Field(default=2, alias="maxParallelAgents", ge=1, le=8)
    allowed_tools: list[ActionId] | None = Field(default=None, alias="allowedTools", max_length=64)


WORKFLOW_STAGES = (
    "intake",
    "scoping",
    "workspace-preparation",
    "implementing",
    "verifying",
    "repairing",
    "presenting",
    "applying",
)


class WorkflowDefinitionLimits(ConfigModel):
    max_repair_iterations: int = Field(alias="maxRepairIterations", ge=0, le=5)


class WorkflowDefinition(ConfigModel):
    api_version: Literal["agentfleet.dev/v1alpha1"] = Field(alias="apiVersion")
    kind: Literal["Workflow"]
    metadata: Metadata
    stages: list[str] = Field(min_length=8, max_length=8)
    limits: WorkflowDefinitionLimits
    verification_skills: list[str] = Field(
        default_factory=list, alias="verificationSkills", max_length=32
    )

    @field_validator("stages")
    @classmethod
    def fixed_stage_sequence(cls, values: list[str]) -> list[str]:
        if tuple(values) != WORKFLOW_STAGES:
            raise ValueError("workflow stages must retain the supported code-change sequence")
        return values

    @field_validator("verification_skills")
    @classmethod
    def canonical_skill_references(cls, values: list[str]) -> list[str]:
        folded: set[str] = set()
        for value in values:
            path = PurePosixPath(value)
            if (
                len(path.parts) != 2
                or path.parts[0] != "skills"
                or path.suffix != ".yaml"
                or path.as_posix() != value
                or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", path.stem) is None
                or value.casefold() in folded
            ):
                raise ValueError(
                    "verification skills require unique canonical skills/name.yaml references"
                )
            folded.add(value.casefold())
        return values


class VerificationSkill(ConfigModel):
    api_version: Literal["agentfleet.dev/v1alpha1"] = Field(alias="apiVersion")
    kind: Literal["VerificationSkill"]
    metadata: Metadata
    applies_to_paths: list[LogicalRepoPath] = Field(
        alias="appliesToPaths", min_length=1, max_length=128
    )
    required_command_ids: list[ActionId] = Field(
        alias="requiredCommandIds", min_length=1, max_length=128
    )

    @field_validator("applies_to_paths")
    @classmethod
    def canonical_scope(cls, values: list[str]) -> list[str]:
        folded: set[str] = set()
        for value in values:
            canonical_trust_path(value, allow_root=True)
            if (
                len(value.encode("utf-8", errors="surrogatepass")) > 4096
                or any(0xD800 <= ord(char) <= 0xDFFF for char in value)
                or len(PurePosixPath(value).parts) > 64
                or value.casefold() in folded
            ):
                raise ValueError(
                    "skill scopes must be bounded, UTF-8 and case-insensitively unique"
                )
            folded.add(value.casefold())
        return values

    @field_validator("required_command_ids")
    @classmethod
    def unique_commands(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("skill command IDs must be unique")
        return values


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
    commands: dict[ActionId, VerificationCommand] = Field(max_length=32)
    required_for_code_change: list[ActionId] = Field(alias="requiredForCodeChange", max_length=32)

    @model_validator(mode="after")
    def commands_exist(self) -> VerificationProfile:
        if len(self.required_for_code_change) != len(set(self.required_for_code_change)):
            raise ValueError("required verification command IDs must be unique")
        missing = set(self.required_for_code_change) - set(self.commands)
        if missing:
            raise ValueError(f"required verification commands are missing: {sorted(missing)}")
        for command_id, command in self.commands.items():
            CommandSpec(
                command_id=command_id,
                executable=command.executable,
                argv=tuple(command.argv),
                logical_cwd=command.cwd,
                timeout_seconds=command.timeout_seconds,
            )
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
