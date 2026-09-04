"""Strict repository-owned configuration models for the Phase 0/1 subset."""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from agent_fleet.domain.models import AgentLifecycle, StrictModel


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
    role: Literal["chief-of-staff", "software-engineer", "verifier"]
    lifecycle: AgentLifecycle
    instructions: str
    allowed_tools: list[str] = Field(alias="allowedTools")
    may_delegate_to: list[Literal["engineer", "verifier"]] = Field(
        default_factory=list, alias="mayDelegateTo"
    )
    max_steps: int = Field(alias="maxSteps", ge=1, le=100)


class WorkflowRequest(ConfigModel):
    definition: str
    max_repair_iterations: int = Field(alias="maxRepairIterations", ge=0, le=5)


class ProjectFiles(ConfigModel):
    charter: str
    architecture: str
    verification: str


class RequestedPermission(ConfigModel):
    principal_role: Literal["engineer", "verifier"] = Field(alias="principalRole")
    action: Literal["repo.read", "workspace.write", "command.run"]
    resource: str


class FleetSpecBody(ConfigModel):
    runtime: RuntimeRequest
    sandbox: SandboxRequest
    agents: dict[Literal["cos", "engineer", "verifier"], AgentRequest]
    workflows: dict[Literal["code-change"], WorkflowRequest]
    project: ProjectFiles
    requested_permissions: list[RequestedPermission] = Field(alias="requestedPermissions")

    @model_validator(mode="after")
    def require_all_roles(self) -> FleetSpecBody:
        if set(self.agents) != {"cos", "engineer", "verifier"}:
            raise ValueError("agents must define exactly cos, engineer, and verifier")
        return self


class FleetSpec(ConfigModel):
    api_version: Literal["agentfleet.dev/v1alpha1"] = Field(alias="apiVersion")
    kind: Literal["Fleet"]
    metadata: Metadata
    spec: FleetSpecBody


class VerificationCommand(ConfigModel):
    executable: str = Field(min_length=1, pattern=r"^[A-Za-z0-9._+-]+$")
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
