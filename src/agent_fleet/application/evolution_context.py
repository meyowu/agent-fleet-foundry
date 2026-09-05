"""Bounded organization context and exact identities for untrusted CoS proposals."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import cast

from pydantic import JsonValue

from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.evolution import OrganizationAdmission
from agent_fleet.domain.fleet_patch import validate_fleet_patch
from agent_fleet.domain.models import FleetPatch, FleetPatchOperation
from agent_fleet.domain.organization_tree import OrganizationTree
from agent_fleet.domain.security import Redactor

MAX_EVOLUTION_CONTEXT_BYTES = 128_000
MAX_EVOLUTION_CONTEXT_FILE_BYTES = 32_768


@dataclass(frozen=True)
class EvolutionContext:
    proposal_id: str
    admission: OrganizationAdmission
    visible_paths: frozenset[str]
    input: dict[str, JsonValue]


def build_evolution_context(
    tree: OrganizationTree,
    admission: OrganizationAdmission,
    proposal_id: str,
    redactor: Redactor,
) -> EvolutionContext:
    if tree.sha256 != admission.tree_sha256:
        raise _invalid("Organization context does not match its admitted generation.")
    if redactor.contains_secret_data(tree.model_dump(mode="json")):
        raise _invalid("Organization context contains a registered secret.")
    content: dict[str, JsonValue] = {
        "proposal_id": proposal_id,
        "project_id": admission.project_id,
        "base_fleet_spec_sha256": admission.config_snapshot_sha256,
        "organization_revision": admission.revision,
        "organization_tree_sha256": admission.tree_sha256,
        "files": [],
        "omitted_file_count": 0,
        "instructions": (
            "Organization changes return only a FleetPatch proposal using these exact IDs. "
            "Never apply it or claim it is active. The user must explicitly review and apply. "
            "Do not change fleet.yaml, trust, credentials, sandbox boundaries or permissions. "
            "Only update/delete files whose complete contents appear here. Referenced "
            "verification skills are declarative command requirements, not executable tools. "
            "Adding requirements does not grant permission to execute their commands."
        ),
    }
    visible: set[str] = set()
    files: list[JsonValue] = []
    omitted = 0
    for item in sorted(tree.files, key=lambda entry: (_priority(entry.path), entry.path)):
        if not _potentially_mutable(item.path):
            continue
        entry: dict[str, JsonValue] = {
            "path": ".fleet/" + item.path,
            "sha256": item.sha256,
            "content": item.content,
        }
        candidate = {**content, "files": [*files, entry]}
        # Reserve enough room for the final bounded omission counter.
        if (
            len(item.content.encode("utf-8")) > MAX_EVOLUTION_CONTEXT_FILE_BYTES
            or _size(candidate) > MAX_EVOLUTION_CONTEXT_BYTES - 32
        ):
            omitted += 1
            continue
        files.append(entry)
        visible.add(".fleet/" + item.path)
    content["files"] = files
    content["omitted_file_count"] = omitted
    if _size(content) > MAX_EVOLUTION_CONTEXT_BYTES or redactor.contains_secret_data(content):
        raise _invalid("Organization context is oversized or contains a registered secret.")
    return EvolutionContext(proposal_id, admission, frozenset(visible), content)


def validate_context_proposal(
    patch: FleetPatch, context: EvolutionContext, redactor: Redactor
) -> None:
    validate_fleet_patch(
        patch,
        current_fleet_spec_sha256=context.admission.config_snapshot_sha256,
        redactor=redactor,
    )
    if (
        patch.fleet_patch_id != context.proposal_id
        or patch.project_id != context.admission.project_id
        or patch.rollback_of is not None
    ):
        raise _invalid("CoS proposal does not match the trusted proposal identity.")
    if any(
        change.operation is not FleetPatchOperation.ADD and change.path not in context.visible_paths
        for change in patch.changes
    ):
        raise _invalid("CoS proposal changes a file omitted from its bounded context.")


def _potentially_mutable(path: str) -> bool:
    return path in {
        "README.md",
        "project/charter.md",
        "project/architecture.md",
        "project/verification.yaml",
    } or path.startswith(("agents/", "workflows/", "skills/"))


def _priority(path: str) -> int:
    if path.startswith("workflows/"):
        return 0
    if path == "project/verification.yaml":
        return 1
    if path.startswith("skills/"):
        return 2
    if path.startswith("agents/"):
        return 3
    return 4


def _size(value: object) -> int:
    return len(
        json.dumps(cast(JsonValue, value), ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
    )


def _invalid(message: str) -> FleetError:
    return FleetError(
        ErrorCode.RUNTIME_OUTPUT_INVALID,
        message,
        "Request a smaller reviewable organization change; no configuration was applied.",
    )
