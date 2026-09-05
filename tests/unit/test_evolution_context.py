from __future__ import annotations

import json
from pathlib import PurePosixPath

import pytest

from agent_fleet.application.evolution_context import (
    MAX_EVOLUTION_CONTEXT_BYTES,
    build_evolution_context,
    validate_context_proposal,
)
from agent_fleet.domain.errors import FleetError
from agent_fleet.domain.evolution import OrganizationAdmission
from agent_fleet.domain.models import FleetPatch, FleetPatchFileChange, FleetPatchOperation
from agent_fleet.domain.organization_tree import (
    OrganizationDirectory,
    OrganizationFile,
    OrganizationTree,
)
from agent_fleet.domain.security import Redactor, sha256_bytes


def _tree(files: dict[str, str]) -> OrganizationTree:
    directories = {"."}
    for path in files:
        directories.update(str(parent) for parent in PurePosixPath(path).parents)
    return OrganizationTree(
        files=tuple(
            OrganizationFile(
                path=path, content=content, sha256=sha256_bytes(content.encode()), mode=0o600
            )
            for path, content in sorted(files.items())
        ),
        directories=tuple(
            OrganizationDirectory(path=path, mode=0o700) for path in sorted(directories)
        ),
    )


def _admission(tree: OrganizationTree) -> OrganizationAdmission:
    return OrganizationAdmission(
        project_id="prj_" + "1" * 32,
        revision=3,
        tree_sha256=tree.sha256,
        config_snapshot_sha256="a" * 64,
    )


def _patch(tree: OrganizationTree, path: str = "agents/engineer.md") -> FleetPatch:
    before = next(item for item in tree.files if item.path == path)
    return FleetPatch(
        fleet_patch_id="fpatch_" + "2" * 32,
        project_id="prj_" + "1" * 32,
        base_fleet_spec_sha256="a" * 64,
        changes=[
            FleetPatchFileChange(
                operation=FleetPatchOperation.REPLACE,
                path=".fleet/" + path,
                before_sha256=before.sha256,
                after_sha256=sha256_bytes(b"reviewed change\n"),
                content="reviewed change\n",
            )
        ],
        rationale="Propose a reviewed organization change.",
    )


def test_context_preserves_complete_visible_content_and_excludes_protected_spec() -> None:
    tree = _tree({"agents/engineer.md": "Guide.\n", "fleet.yaml": "protected: not model context\n"})
    context = build_evolution_context(tree, _admission(tree), "fpatch_" + "2" * 32, Redactor())
    assert context.visible_paths == frozenset({".fleet/agents/engineer.md"})
    assert "protected: not model context" not in json.dumps(context.input)
    assert context.input["organization_revision"] == 3
    assert context.input["organization_tree_sha256"] == tree.sha256
    validate_context_proposal(_patch(tree), context, Redactor())


@pytest.mark.parametrize(
    "field,value",
    [
        ("fleet_patch_id", "fpatch_" + "3" * 32),
        ("project_id", "prj_" + "3" * 32),
        ("base_fleet_spec_sha256", "b" * 64),
        ("rollback_of", "fpatch_" + "4" * 32),
    ],
)
def test_model_cannot_choose_proposal_identity_or_rollback(field: str, value: str) -> None:
    tree = _tree({"agents/engineer.md": "Guide.\n"})
    context = build_evolution_context(tree, _admission(tree), "fpatch_" + "2" * 32, Redactor())
    with pytest.raises(FleetError):
        validate_context_proposal(
            _patch(tree).model_copy(update={field: value}), context, Redactor()
        )


def test_omitted_large_file_cannot_be_replaced_even_with_correct_hash() -> None:
    tree = _tree({"agents/engineer.md": "x" * 40_000, "workflows/code-change.yaml": "workflow\n"})
    context = build_evolution_context(tree, _admission(tree), "fpatch_" + "2" * 32, Redactor())
    assert context.input["omitted_file_count"] == 1
    assert ".fleet/agents/engineer.md" not in context.visible_paths
    with pytest.raises(FleetError, match="omitted"):
        validate_context_proposal(_patch(tree), context, Redactor())


def test_context_byte_limit_counts_utf8_and_json_escaping_and_preserves_workflow_priority() -> None:
    tree = _tree(
        {
            **{f"agents/role-{index:02d}.md": '😀\n"' * 4_000 for index in range(12)},
            "workflows/code-change.yaml": "workflow content\n",
        }
    )
    context = build_evolution_context(tree, _admission(tree), "fpatch_" + "2" * 32, Redactor())
    assert (
        len(json.dumps(context.input, ensure_ascii=False, separators=(",", ":")).encode())
        <= MAX_EVOLUTION_CONTEXT_BYTES
    )
    assert context.input["omitted_file_count"] != 0
    assert ".fleet/workflows/code-change.yaml" in context.visible_paths


def test_fresh_registered_secret_blocks_context_and_proposal() -> None:
    tree = _tree({"agents/engineer.md": "Do not disclose sentinel-context-secret.\n"})
    with pytest.raises(FleetError, match="registered secret"):
        build_evolution_context(
            tree, _admission(tree), "fpatch_" + "2" * 32, Redactor(["sentinel-context-secret"])
        )
    context = build_evolution_context(tree, _admission(tree), "fpatch_" + "2" * 32, Redactor())
    with pytest.raises(FleetError, match="registered secret"):
        validate_context_proposal(_patch(tree), context, Redactor(["reviewed change"]))


def test_context_rejects_a_different_admitted_tree() -> None:
    tree = _tree({"agents/engineer.md": "Guide.\n"})
    with pytest.raises(FleetError, match="generation"):
        build_evolution_context(
            tree,
            _admission(tree).model_copy(update={"tree_sha256": "c" * 64}),
            "fpatch_" + "2" * 32,
            Redactor(),
        )
