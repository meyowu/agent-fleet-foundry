"""Read-only bundle rendering is not publication or an execution permission."""

import gc
from pathlib import Path
from typing import Any

import pytest
from conftest import FleetHarness
from pydantic import ValidationError

from agent_fleet.adapters.config.role_bundle_assets import PackagedRoleBundles
from agent_fleet.adapters.config.yaml import YamlConfigurationAdapter
from agent_fleet.application.role_bundles import RoleBundleService
from agent_fleet.domain.errors import FleetError
from agent_fleet.domain.role_bundles import RoleBundlePreview
from agent_fleet.domain.security import Redactor


def service(harness: FleetHarness, redactor: Redactor | None = None) -> RoleBundleService:
    return RoleBundleService(
        harness.container.repository,
        YamlConfigurationAdapter(redactor),
        PackagedRoleBundles(),
        redactor or Redactor(),
    )


def inventory(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink()
    }


@pytest.mark.parametrize("bundle", [item.bundle_id for item in PackagedRoleBundles().definitions()])
def test_preview_keeps_target_state_and_exact_commands(harness: FleetHarness, bundle: str) -> None:
    app = service(harness)
    # The legacy harness leaves SQLite connections awaiting collection. Finish
    # their WAL checkpoints before measuring this independent, store-free service.
    gc.collect()
    original = inventory(harness.root)
    preview = app.preview(
        bundle,
        harness.repository_root,
        workflow_id="code-change",
        scopes=("src/canary_calc",),
        command_ids=("python-test",),
    )
    gc.collect()
    assert inventory(harness.root) == original
    assert preview.execution_authorized is preview.publication_authorized is False
    assert len(preview.adoption_brief.encode()) <= 16_384
    assert "\n" not in preview.adoption_brief
    assert "NEW FleetPatch" in preview.adoption_brief
    assert preview.commands[0].definition.command_id == "python-test"
    assert preview.configuration_sha256 != preview.proposed_configuration_sha256
    assert all(change.path != ".fleet/fleet.yaml" for change in preview.changes)
    assert preview == RoleBundlePreview.model_validate_json(preview.model_dump_json())


@pytest.mark.parametrize("scope", ["..", ".git", ".fleet", "src/../secret", "/tmp", "src\\escape"])
def test_preview_rejects_protected_scope(harness: FleetHarness, scope: str) -> None:
    with pytest.raises(FleetError):
        service(harness).preview(
            "general-change",
            harness.repository_root,
            workflow_id="code-change",
            scopes=(scope,),
            command_ids=("python-test",),
        )


@pytest.mark.parametrize("field", ["bundle", "workflow", "command"])
def test_preview_rejects_unknown_selection(harness: FleetHarness, field: str) -> None:
    with pytest.raises(FleetError):
        service(harness).preview(
            "unknown" if field == "bundle" else "general-change",
            harness.repository_root,
            workflow_id="unknown" if field == "workflow" else "code-change",
            scopes=("src/canary_calc",),
            command_ids=("unknown" if field == "command" else "python-test",),
        )


@pytest.mark.parametrize("value", [0, True, "false", None])
def test_preview_never_coerces_authority(harness: FleetHarness, value: object) -> None:
    preview = service(harness).preview(
        "general-change",
        harness.repository_root,
        workflow_id="code-change",
        scopes=("src/canary_calc",),
        command_ids=("python-test",),
    )
    for field in ("execution_authorized", "publication_authorized"):
        with pytest.raises(ValidationError):
            RoleBundlePreview.model_validate(preview.model_dump() | {field: value})


@pytest.mark.parametrize("symbolic", [False, True])
def test_preview_rejects_unreferenced_physical_collision(
    harness: FleetHarness,
    symbolic: bool,
) -> None:
    target = harness.repository_root / ".fleet/agents/general-engineer.md"
    if symbolic:
        target.symlink_to(harness.root / "outside-unused")
    else:
        target.write_text("Unreferenced user-owned content.\n")
    with pytest.raises(FleetError):
        service(harness).preview(
            "general-change",
            harness.repository_root,
            workflow_id="code-change",
            scopes=("src/canary_calc",),
            command_ids=("python-test",),
        )
    assert target.is_symlink() if symbolic else target.read_text().startswith("Unreferenced")


def test_registered_secret_is_not_returned_or_attached_as_cause(harness: FleetHarness) -> None:
    with pytest.raises(FleetError) as caught:
        service(harness, Redactor(["general-engineer"])).preview(
            "general-change",
            harness.repository_root,
            workflow_id="code-change",
            scopes=("src/canary_calc",),
            command_ids=("python-test",),
        )
    assert "general-engineer" not in str(caught.value)
    assert caught.value.__context__ is caught.value.__cause__ is None


@pytest.mark.parametrize(
    ("scopes", "commands"),
    [
        ((), ("python-test",)),
        (("src", "src"), ("python-test",)),
        (("SRC", "src"), ("python-test",)),
        (("src",), ("python-test", "python-test")),
        (("src",), ()),
        (("src",) * 33, ("python-test",)),
        (["src"], ("python-test",)),
        (("src",), ["python-test"]),
        ((1,), ("python-test",)),
        (("src",), (1,)),
    ],
)
def test_selections_are_canonical_bounded_and_immutable(
    harness: FleetHarness, scopes: Any, commands: Any
) -> None:
    with pytest.raises(FleetError):
        service(harness).preview(
            "general-change",
            harness.repository_root,
            workflow_id="code-change",
            scopes=scopes,
            command_ids=commands,
        )


def test_oversized_adoption_brief_is_rejected_not_truncated(harness: FleetHarness) -> None:
    target = harness.repository_root / ".fleet/agents/roles.yaml"
    # Existing catalog content must survive rendering, but cannot be silently
    # omitted to squeeze a review into the Session input limit.
    import yaml

    target.write_text(
        yaml.safe_dump(
            {
                "apiVersion": "agentfleet.dev/v1alpha1",
                "kind": "RoleCatalog",
                "roles": {
                    f"existing-{number}": {
                        "baseRole": "engineer",
                        "description": "界" * 100,
                        "instructions": "agents/engineer.md",
                        "allowedPaths": ["src"],
                    }
                    for number in range(20)
                },
            }
        ),
        encoding="utf-8",
    )
    before = target.read_bytes()
    with pytest.raises(FleetError):
        service(harness).preview(
            "general-change",
            harness.repository_root,
            workflow_id="code-change",
            scopes=("src/canary_calc",),
            command_ids=("python-test",),
        )
    assert target.read_bytes() == before
