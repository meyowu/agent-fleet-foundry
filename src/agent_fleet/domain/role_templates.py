"""Bounded role identities derived from supported execution semantics.

Repository catalogs request responsibilities, not authority. The application
must preserve the actual role ID in every principal and use execution_kind only
to select the existing tool/output/isolation ceiling.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, StringConstraints, field_validator, model_validator

from agent_fleet.domain.config import ConfigModel, FleetSpec
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.fleet_plan import FleetPlan
from agent_fleet.domain.models import ActionId, AgentLifecycle, AgentRole, FrozenStrictModel, RoleId
from agent_fleet.domain.paths import path_is_within
from agent_fleet.domain.trust import canonical_trust_path

ROLE_CATALOG_PATH = "agents/roles.yaml"
MAX_ROLE_TEMPLATES = 32
MAX_ROLE_GUIDANCE_BYTES = 32_768
ModelProfileAlias = Annotated[
    str, StringConstraints(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_-]{0,63}$")
]
_READ_TOOLS = frozenset(
    {"repo.list_files", "repo.read_file", "repo.search_text", "workspace.get_diff"}
)
_WRITE_TOOLS = _READ_TOOLS | {
    "workspace.write_file",
    "workspace.apply_edit",
    "workspace.delete_path",
    "command.run",
    "fixture.record_side_effect",
}
ROLE_TOOL_CEILINGS: dict[AgentRole, frozenset[str]] = {
    AgentRole.COS: frozenset(),
    AgentRole.ENGINEER: frozenset(_WRITE_TOOLS),
    AgentRole.VERIFIER: _READ_TOOLS | {"command.run"},
    AgentRole.RESEARCHER: _READ_TOOLS,
    AgentRole.ARCHITECT: _READ_TOOLS,
}


class RoleTemplate(ConfigModel):
    base_role: Literal["engineer", "verifier", "researcher", "architect"] = Field(alias="baseRole")
    description: str = Field(min_length=1, max_length=512)
    instructions: str = Field(min_length=1, max_length=4096)
    model_profile: ModelProfileAlias | None = Field(default=None, alias="modelProfile")
    allowed_tools: list[ActionId] | None = Field(default=None, alias="allowedTools", max_length=32)
    max_steps: int | None = Field(default=None, alias="maxSteps", ge=1, le=100)
    allowed_paths: list[str] | None = Field(
        default=None, alias="allowedPaths", min_length=1, max_length=128
    )

    @field_validator("instructions")
    @classmethod
    def validate_instruction_path(cls, value: str) -> str:
        canonical_trust_path(value)
        path = PurePosixPath(value)
        if (
            len(path.parts) < 2
            or len(path.parts) > 16
            or path.parts[0] != "agents"
            or path.suffix != ".md"
            or len(value.encode("utf-8", errors="surrogatepass")) > 4096
            or any(0xD800 <= ord(char) <= 0xDFFF for char in value)
        ):
            raise ValueError("role instructions must be canonical agents/*.md references")
        return value

    @field_validator("description")
    @classmethod
    def plain_description(cls, value: str) -> str:
        if any(
            ord(char) < 32 or ord(char) == 127 or 0xD800 <= ord(char) <= 0xDFFF for char in value
        ):
            raise ValueError("role descriptions must be bounded plain text")
        return value

    @field_validator("allowed_paths")
    @classmethod
    def exact_paths(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return values
        for value in values:
            canonical_trust_path(value, allow_root=True)
            if (
                len(value.encode("utf-8", errors="surrogatepass")) > 4096
                or len(PurePosixPath(value).parts) > 64
                or any(0xD800 <= ord(char) <= 0xDFFF for char in value)
            ):
                raise ValueError("role paths exceed canonical UTF-8 bounds")
        if len({value.casefold() for value in values}) != len(values):
            raise ValueError("role path scopes must be unique")
        return values

    @model_validator(mode="after")
    def kind_tool_ceiling(self) -> RoleTemplate:
        if self.allowed_tools is not None:
            if len(set(self.allowed_tools)) != len(self.allowed_tools):
                raise ValueError("role tool requests must be unique")
            if set(self.allowed_tools) - ROLE_TOOL_CEILINGS[AgentRole(self.base_role)]:
                raise ValueError("role tools exceed the supported execution-kind ceiling")
        return self


class RoleCatalog(ConfigModel):
    api_version: Literal["agentfleet.dev/v1alpha1"] = Field(alias="apiVersion")
    kind: Literal["RoleCatalog"]
    roles: dict[RoleId, RoleTemplate] = Field(max_length=MAX_ROLE_TEMPLATES)

    @field_validator("roles")
    @classmethod
    def distinct_custom_principals(cls, roles: dict[str, RoleTemplate]) -> dict[str, RoleTemplate]:
        reserved = {role.value for role in AgentRole} | {"chief-of-staff", "software-engineer"}
        folded = {key.casefold() for key in roles}
        if len(folded) != len(roles) or folded & reserved:
            raise ValueError("custom roles must not replace or alias built-in role identities")
        return roles


class ResolvedRoleTemplate(FrozenStrictModel):
    """Trusted resolver output; not accepted from model output as authority."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    role_id: RoleId
    execution_kind: AgentRole
    lifecycle: AgentLifecycle
    description: str = Field(max_length=512)
    instructions: str = Field(max_length=MAX_ROLE_GUIDANCE_BYTES)
    instruction_references: tuple[str, ...] = Field(min_length=1, max_length=2)
    allowed_tools: tuple[ActionId, ...] = Field(max_length=64)
    max_steps: int = Field(ge=1, le=100)
    allowed_paths: tuple[str, ...] | None = Field(default=None, max_length=128)
    model_profile: ModelProfileAlias | None = None
    delegation_allowed: bool


def resolve_role_templates(
    spec: FleetSpec,
    contents: dict[str, str],
    catalog: RoleCatalog | None = None,
) -> dict[str, ResolvedRoleTemplate]:
    """Resolve a validated configuration closure without filesystem/model access.

    This does not grant a tool or path. The task/user/workflow/broker ceilings
    still apply, using role_id as the actual principal. Unknown legacy roles
    remain non-executable rather than being inferred from their names.
    """

    delegated = set(spec.spec.agents["cos"].may_delegate_to)
    resolved: dict[str, ResolvedRoleTemplate] = {}

    def guidance(reference: str) -> str:
        content = contents.get(reference)
        if content is None or len(content.encode("utf-8")) > MAX_ROLE_GUIDANCE_BYTES:
            raise ValueError("role guidance is missing or exceeds its byte limit")
        return content

    for kind in AgentRole:
        requested_base = spec.spec.agents.get(kind.value)
        if requested_base is None:
            continue
        resolved[kind.value] = ResolvedRoleTemplate(
            role_id=kind.value,
            execution_kind=kind,
            lifecycle=requested_base.lifecycle,
            description=f"Built-in {kind.value} responsibility",
            instructions=guidance(requested_base.instructions),
            instruction_references=(requested_base.instructions,),
            allowed_tools=tuple(requested_base.allowed_tools),
            max_steps=requested_base.max_steps,
            delegation_allowed=kind.value in delegated,
        )
    for role_id, template in catalog.roles.items() if catalog else ():
        if role_id in spec.spec.agents:
            raise ValueError("catalog roles cannot replace declared FleetSpec identities")
        base = resolved.get(template.base_role)
        if base is None:
            raise ValueError("custom role requires a declared executable base role")
        tools = template.allowed_tools
        if tools is None:
            tools = [
                tool
                for tool in base.allowed_tools
                if tool in ROLE_TOOL_CEILINGS[base.execution_kind]
            ]
        if set(tools) - set(base.allowed_tools):
            raise ValueError("custom role tools exceed the declared base-role ceiling")
        steps = base.max_steps if template.max_steps is None else template.max_steps
        if steps > base.max_steps:
            raise ValueError("custom role steps exceed the declared base-role ceiling")
        instructions = base.instructions + "\n\n" + guidance(template.instructions)
        if len(instructions.encode("utf-8")) > MAX_ROLE_GUIDANCE_BYTES:
            raise ValueError("combined role guidance exceeds its byte limit")
        resolved[role_id] = ResolvedRoleTemplate(
            role_id=role_id,
            execution_kind=base.execution_kind,
            lifecycle=AgentLifecycle.PER_TASK,
            description=template.description,
            instructions=instructions,
            instruction_references=(base.instruction_references[0], template.instructions),
            allowed_tools=tuple(tools),
            max_steps=steps,
            allowed_paths=None if template.allowed_paths is None else tuple(template.allowed_paths),
            model_profile=template.model_profile,
            delegation_allowed=base.delegation_allowed,
        )
    return resolved


def validate_role_plan(plan: FleetPlan, templates: dict[str, ResolvedRoleTemplate]) -> None:
    """Check control-plane node bindings against the exact configuration closure."""

    if plan.repair_role_id is not None:
        repair = templates.get(plan.repair_role_id)
        # Joined repair executes on the parent task, whose full scope is also
        # bound by the final verifier node. Check that scope before any dispatch.
        scope = [
            path
            for node in plan.nodes
            if node.can_write or node.independent_verifier
            for path in node.scope
        ]
        if (
            repair is None
            or repair.execution_kind is not AgentRole.ENGINEER
            or not repair.delegation_allowed
            or (
                repair.allowed_paths is not None
                and any(not path_is_within(path, list(repair.allowed_paths)) for path in scope)
            )
        ):
            raise FleetError(
                ErrorCode.COMMAND_DENIED,
                "The repair role cannot cover the reviewed parent repair scope.",
                "Select an explicit compatible repair writer without expanding its template.",
            )

    for node in plan.nodes:
        template = templates.get(node.role_id)
        if (
            template is None
            or not template.delegation_allowed
            or template.execution_kind is not node.effective_kind
            or node.max_steps > template.max_steps
            or (
                template.allowed_paths is not None
                and any(
                    not path_is_within(path, list(template.allowed_paths)) for path in node.scope
                )
            )
        ):
            raise FleetError(
                ErrorCode.COMMAND_DENIED,
                "The selected role exceeds its reviewed template or delegation scope.",
                "Select a declared compatible role within its exact path and step ceiling.",
            )
