from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

from agent_fleet.adapters.config import yaml as configuration
from agent_fleet.adapters.config.yaml import YamlConfigurationAdapter
from agent_fleet.domain.config import ConfigSnapshot, ConfigSnapshotFile
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import AgentRole
from agent_fleet.domain.role_templates import MAX_ROLE_GUIDANCE_BYTES, ROLE_CATALOG_PATH
from agent_fleet.domain.security import Redactor, sha256_bytes


def role_files() -> dict[str, str]:
    files = YamlConfigurationAdapter().default_files("role-catalog")
    files[ROLE_CATALOG_PATH] = yaml.safe_dump(
        {
            "apiVersion": "agentfleet.dev/v1alpha1",
            "kind": "RoleCatalog",
            "roles": {
                "backend_engineer": {
                    "baseRole": "engineer",
                    "description": "Implement bounded backend changes",
                    "instructions": "agents/backend.md",
                    "modelProfile": "coding",
                    "allowedTools": ["repo.read_file", "workspace.write_file"],
                    "maxSteps": 8,
                    "allowedPaths": ["src/backend"],
                },
                "security_reviewer": {
                    "baseRole": "researcher",
                    "description": "Read-only security analysis",
                    "instructions": "agents/security.md",
                },
            },
        }
    )
    files["agents/backend.md"] = "Use existing transaction boundaries.\n"
    files["agents/security.md"] = "Explain risks with exact evidence.\n"
    return files


def test_absent_catalog_preserves_original_reference_closure_exactly() -> None:
    adapter = YamlConfigurationAdapter()
    files = adapter.default_files("legacy-role-catalog")
    spec, snapshot = adapter.snapshot_from_files(files)
    # The original generated closure excludes README and has no catalog field.
    original = ConfigSnapshot(
        files=[
            ConfigSnapshotFile(path=path, content=body, sha256=sha256_bytes(body.encode()))
            for path, body in sorted(files.items())
            if path != "README.md"
        ]
    )
    assert snapshot.model_dump_json(indent=2) == original.model_dump_json(indent=2)
    assert adapter.snapshot_hash(snapshot) == adapter.snapshot_hash(original)
    resolved = adapter.role_templates(spec, snapshot)
    assert set(resolved) == {item.value for item in AgentRole}
    assert resolved["cos"].role_id == "cos"
    assert resolved["engineer"].execution_kind is AgentRole.ENGINEER
    assert resolved["engineer"].instructions == files["agents/engineer.md"]


def test_custom_roles_are_distinct_principals_with_bounded_inherited_semantics() -> None:
    adapter = YamlConfigurationAdapter()
    files = role_files()
    spec, snapshot = adapter.snapshot_from_files(files)
    roles = adapter.role_templates(spec, snapshot)
    writer = roles["backend_engineer"]
    assert writer.role_id == "backend_engineer"
    assert writer.execution_kind is AgentRole.ENGINEER
    assert writer.max_steps == 8
    assert writer.allowed_tools == ("repo.read_file", "workspace.write_file")
    assert writer.allowed_paths == ("src/backend",)
    assert writer.model_profile == "coding"
    assert writer.delegation_allowed
    assert writer.instructions == files["agents/engineer.md"] + "\n\n" + files["agents/backend.md"]
    assert roles["security_reviewer"].execution_kind is AgentRole.RESEARCHER
    assert "command.run" not in roles["security_reviewer"].allowed_tools
    assert "workspace.write_file" not in roles["security_reviewer"].allowed_tools
    assert "backend_engineer" not in spec.spec.agents  # protected root bytes are unchanged
    assert {ROLE_CATALOG_PATH, "agents/backend.md", "agents/security.md"} <= {
        item.path for item in snapshot.files
    }


def test_role_guidance_and_catalog_are_in_the_authoritative_snapshot() -> None:
    adapter = YamlConfigurationAdapter()
    files = role_files()
    _, first = adapter.snapshot_from_files(files)
    files["agents/backend.md"] += "Preserve idempotency.\n"
    _, second = adapter.snapshot_from_files(files)
    assert adapter.snapshot_hash(first) != adapter.snapshot_hash(second)
    changed = yaml.safe_load(files[ROLE_CATALOG_PATH])
    changed["roles"]["backend_engineer"]["maxSteps"] = 7
    files[ROLE_CATALOG_PATH] = yaml.safe_dump(changed)
    _, third = adapter.snapshot_from_files(files)
    assert adapter.snapshot_hash(second) != adapter.snapshot_hash(third)
    del files[ROLE_CATALOG_PATH]
    _, removed = adapter.snapshot_from_files(files)
    _, legacy = adapter.snapshot_from_files(adapter.default_files("role-catalog"))
    assert removed == legacy  # unreferenced notes do not become instructions


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("baseRole", "cos"),
        ("baseRole", "root"),
        ("allowedTools", ["host.sudo"]),
        ("allowedTools", ["repo.read_file", "repo.read_file"]),
        ("maxSteps", 21),
        ("maxSteps", 0),
        ("instructions", "../outside.md"),
        ("instructions", "agents/../../outside.md"),
        ("instructions", "agents/body.yaml"),
        ("instructions", "agents/missing.md"),
        ("instructions", "project/architecture.md"),
        ("modelProfile", "env:SECRET_KEY"),
        ("modelProfile", "x" * 65),
        ("allowedPaths", [".git/config"]),
        ("allowedPaths", ["src", "SRC"]),
        ("allowedPaths", []),
        ("description", "unsafe\x1b[31m"),
        ("credentialRef", "env:SECRET_KEY"),
    ],
)
def test_catalog_rejects_invalid_or_expanding_requests(field: str, value: Any) -> None:
    adapter = YamlConfigurationAdapter()
    files = role_files()
    data = yaml.safe_load(files[ROLE_CATALOG_PATH])
    data["roles"]["backend_engineer"][field] = value
    files[ROLE_CATALOG_PATH] = yaml.safe_dump(data)
    with pytest.raises(FleetError) as caught:
        adapter.snapshot_from_files(files)
    assert caught.value.code is ErrorCode.CONFIG_INVALID


@pytest.mark.parametrize("role_id", ["engineer", "verifier", "cos", "software-engineer", "../../x"])
def test_catalog_cannot_replace_or_alias_builtin_identities(role_id: str) -> None:
    adapter = YamlConfigurationAdapter()
    files = role_files()
    data = yaml.safe_load(files[ROLE_CATALOG_PATH])
    data["roles"][role_id] = data["roles"].pop("backend_engineer")
    files[ROLE_CATALOG_PATH] = yaml.safe_dump(data)
    with pytest.raises(FleetError):
        adapter.snapshot_from_files(files)


def test_custom_role_cannot_exceed_narrower_declared_base_or_delegate_itself() -> None:
    adapter = YamlConfigurationAdapter()
    files = role_files()
    root = yaml.safe_load(files["fleet.yaml"])
    root["spec"]["agents"]["engineer"]["allowedTools"] = ["repo.read_file"]
    files["fleet.yaml"] = yaml.safe_dump(root)
    with pytest.raises(FleetError, match="role catalog"):
        adapter.snapshot_from_files(files)
    root["spec"]["agents"]["engineer"]["allowedTools"].append("workspace.write_file")
    root["spec"]["agents"]["cos"]["mayDelegateTo"] = ["verifier"]
    files["fleet.yaml"] = yaml.safe_dump(root)
    spec, snapshot = adapter.snapshot_from_files(files)
    assert not adapter.role_templates(spec, snapshot)["backend_engineer"].delegation_allowed


def test_registered_secrets_and_oversized_combined_guidance_are_rejected() -> None:
    secret = "DISPOSABLE_ROLE_CATALOG_SECRET"
    adapter = YamlConfigurationAdapter(Redactor([secret]))
    files = role_files()
    files["agents/backend.md"] = secret
    with pytest.raises(FleetError) as caught:
        adapter.snapshot_from_files(files)
    assert secret not in str(caught.value)
    files["agents/backend.md"] = "x" * MAX_ROLE_GUIDANCE_BYTES
    with pytest.raises(FleetError, match="role catalog"):
        adapter.snapshot_from_files(files)


def test_role_catalog_has_bounded_size_and_strict_yaml() -> None:
    adapter = YamlConfigurationAdapter()
    files = role_files()
    data = yaml.safe_load(files[ROLE_CATALOG_PATH])
    template = copy.deepcopy(data["roles"]["backend_engineer"])
    data["roles"] = {f"worker_{index}": template for index in range(33)}
    files[ROLE_CATALOG_PATH] = yaml.safe_dump(data)  # aliases are independently forbidden
    with pytest.raises(FleetError):
        adapter.snapshot_from_files(files)
    files[ROLE_CATALOG_PATH] = "kind: RoleCatalog\nkind: RoleCatalog\n"
    with pytest.raises(FleetError, match="unique"):
        adapter.snapshot_from_files(files)


def test_real_filesystem_loader_includes_catalog_and_rejects_symlink(tmp_path: Path) -> None:
    adapter = YamlConfigurationAdapter()
    root = tmp_path / ".fleet"
    files = role_files()
    adapter.apply(root, files)
    spec, disk = adapter.load_snapshot(root / "fleet.yaml")
    assert disk == adapter.snapshot_from_files(files)[1]
    assert adapter.role_templates(spec, disk)["backend_engineer"].model_profile == "coding"
    (root / ROLE_CATALOG_PATH).unlink()
    outside = tmp_path / "outside.yaml"
    outside.write_text(files[ROLE_CATALOG_PATH], encoding="utf-8")
    (root / ROLE_CATALOG_PATH).symlink_to(outside)
    with pytest.raises(FleetError) as caught:
        adapter.load_snapshot(root / "fleet.yaml")
    assert caught.value.code is ErrorCode.PATH_OUTSIDE_SCOPE


def test_catalog_appearing_during_load_cannot_be_silently_omitted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = YamlConfigurationAdapter()
    root = tmp_path / ".fleet"
    adapter.apply(root, adapter.default_files("catalog-race"))
    original = configuration._optional_role_catalog_present
    calls = 0

    def probe(descriptor: int) -> bool:
        nonlocal calls
        calls += 1
        if calls == 2:
            (root / ROLE_CATALOG_PATH).write_text(
                "apiVersion: agentfleet.dev/v1alpha1\nkind: RoleCatalog\nroles: {}\n",
                encoding="utf-8",
            )
        return original(descriptor)

    monkeypatch.setattr(configuration, "_optional_role_catalog_present", probe)
    with pytest.raises(FleetError, match="changed during"):
        adapter.load_snapshot(root / "fleet.yaml")
