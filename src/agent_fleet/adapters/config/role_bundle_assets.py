"""Read fixed package assets and inspect new paths without following links."""

from __future__ import annotations

import json
import os
import stat
from importlib import resources
from pathlib import Path
from typing import Any

import yaml
from pydantic import TypeAdapter

from agent_fleet.domain.config import ConfigSnapshot, FleetSpec
from agent_fleet.domain.models import AgentRole
from agent_fleet.domain.role_bundles import RoleBundleDefinition
from agent_fleet.domain.role_templates import ROLE_CATALOG_PATH, ROLE_TOOL_CEILINGS


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate bundle asset key")
        result[key] = value
    return result


class PackagedRoleBundles:
    def definitions(self) -> tuple[RoleBundleDefinition, ...]:
        resource = resources.files("agent_fleet").joinpath("assets/role-bundles/catalog.json")
        with resource.open("rb") as stream:
            raw = stream.read(65_537)
        if len(raw) > 65_536:
            raise ValueError("packaged role bundles exceed their limit")
        data = json.loads(raw, object_pairs_hook=_unique_pairs)
        definitions = TypeAdapter(tuple[RoleBundleDefinition, ...]).validate_python(data)
        if len(definitions) != 4 or len({item.bundle_id for item in definitions}) != 4:
            raise ValueError("packaged role bundle catalog is incomplete")
        return definitions

    def render(
        self,
        bundle: RoleBundleDefinition,
        spec: FleetSpec,
        snapshot: ConfigSnapshot,
        *,
        workflow_id: str,
        scopes: tuple[str, ...],
        command_ids: tuple[str, ...],
    ) -> dict[str, str]:
        files = {item.path: item.content for item in snapshot.files}
        catalog: dict[str, Any] = (
            yaml.safe_load(files[ROLE_CATALOG_PATH])
            if ROLE_CATALOG_PATH in files
            else {"apiVersion": "agentfleet.dev/v1alpha1", "kind": "RoleCatalog", "roles": {}}
        )
        for role in bundle.roles:
            reference = f"agents/{role.role_id}.md"
            if role.role_id in catalog["roles"] or reference in files:
                raise ValueError("bundle role or guidance already exists")
            base = spec.spec.agents.get(role.execution_kind)
            if base is None:
                raise ValueError("bundle needs a declared base role")
            tools = sorted(
                (set(base.allowed_tools) & ROLE_TOOL_CEILINGS[AgentRole(role.execution_kind)])
                - {"fixture.record_side_effect", "workspace.delete_path"}
            )
            catalog["roles"][role.role_id] = {
                "baseRole": role.execution_kind,
                "description": role.description,
                "instructions": reference,
                "allowedPaths": list(scopes),
                "allowedTools": tools,
            }
            files[reference] = f"# {role.role_id}\n\n{role.guidance}\n"
        skill_reference = f"skills/bundle-{bundle.bundle_id}.yaml"
        if skill_reference in files:
            raise ValueError("bundle verification skill already exists")
        files[ROLE_CATALOG_PATH] = yaml.safe_dump(catalog, sort_keys=False)
        files[skill_reference] = yaml.safe_dump(
            {
                "apiVersion": "agentfleet.dev/v1alpha1",
                "kind": "VerificationSkill",
                "metadata": {"name": f"bundle-{bundle.bundle_id}"},
                "appliesToPaths": list(scopes),
                "requiredCommandIds": list(command_ids),
            },
            sort_keys=False,
        )
        workflow_reference = spec.spec.workflows[workflow_id].definition
        workflow = yaml.safe_load(files[workflow_reference])
        skills = workflow.setdefault("verificationSkills", [])
        if skill_reference in skills:
            raise ValueError("bundle skill is already selected")
        skills.append(skill_reference)
        files[workflow_reference] = yaml.safe_dump(workflow, sort_keys=False)
        return files

    def assert_new_paths_absent(self, root: Path, paths: tuple[str, ...]) -> None:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        root_fd = os.open(root, flags)
        try:
            for path in paths:
                parts = path.split("/")
                if any(part in {"", ".", ".."} for part in parts) or "\\" in path:
                    raise ValueError("bundle path is not canonical")
                current = os.dup(root_fd)
                try:
                    for index, part in enumerate(parts):
                        try:
                            info = os.stat(part, dir_fd=current, follow_symlinks=False)
                        except FileNotFoundError:
                            break
                        if index == len(parts) - 1 or not stat.S_ISDIR(info.st_mode):
                            raise ValueError("bundle target already exists or has an unsafe parent")
                        child = os.open(part, flags, dir_fd=current)
                        os.close(current)
                        current = child
                finally:
                    os.close(current)
        finally:
            os.close(root_fd)
