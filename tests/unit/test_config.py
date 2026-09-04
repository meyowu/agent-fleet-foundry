from __future__ import annotations

import copy
import os
import traceback
from pathlib import Path

import pytest
import yaml

from agent_fleet.adapters.config.yaml import (
    MAX_CONFIG_BYTES,
    YamlConfigurationAdapter,
    default_fleet_files,
    load_fleet_spec,
    parse_fleet_spec,
    parse_verification_profile,
    validate_fleet_files,
)
from agent_fleet.adapters.repository.profile import StaticRepositoryProfiler
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.security import Redactor


def test_default_fleet_spec_round_trips_strictly() -> None:
    files = default_fleet_files("canary-project")
    spec = validate_fleet_files(files)
    assert spec.spec.runtime.adapter == "fake"
    assert set(spec.spec.agents) == {"cos", "engineer", "verifier"}


def test_phase1_generated_role_labels_remain_loadable() -> None:
    files = default_fleet_files("existing-phase1-project")
    data = yaml.safe_load(files["fleet.yaml"])
    data["spec"]["agents"]["cos"]["role"] = "chief-of-staff"
    data["spec"]["agents"]["engineer"]["role"] = "software-engineer"
    data["spec"]["requestedPermissions"][0]["action"] = "workspace.write"
    files["fleet.yaml"] = yaml.safe_dump(data, sort_keys=False)

    spec = validate_fleet_files(files)

    assert spec.spec.agents["cos"].role == "chief-of-staff"
    assert spec.spec.agents["engineer"].role == "software-engineer"


def test_unrecognized_role_label_mismatch_is_rejected() -> None:
    files = default_fleet_files("invalid-role-project")
    data = yaml.safe_load(files["fleet.yaml"])
    data["spec"]["agents"]["engineer"]["role"] = "architect"
    files["fleet.yaml"] = yaml.safe_dump(data, sort_keys=False)

    with pytest.raises(FleetError, match="must match its role field"):
        validate_fleet_files(files)


@pytest.mark.parametrize(
    "content",
    [
        b"!!python/object/apply:os.system ['whoami']\n",
        b"base: &base {adapter: fake}\ncopy: *base\n",
        b"[]\n",
    ],
)
def test_unsafe_or_nonmapping_yaml_is_rejected(content: bytes) -> None:
    with pytest.raises(FleetError) as captured:
        parse_fleet_spec(content)
    assert captured.value.code is ErrorCode.CONFIG_INVALID


def test_registered_secret_is_rejected_before_yaml_parser_error_without_leak() -> None:
    secret = "FLEET-MALFORMED-YAML-REGISTERED-SECRET"
    adapter = YamlConfigurationAdapter(Redactor([secret]))

    with pytest.raises(FleetError, match="registered secret material") as captured:
        adapter.validate_files(
            {
                "fleet.yaml": f"apiVersion: [{secret}\n",
            }
        )

    rendered = "".join(traceback.format_exception(captured.value))
    assert captured.value.code is ErrorCode.CONFIG_INVALID
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
    assert secret not in str(captured.value)
    assert secret not in rendered


def test_unknown_field_is_rejected() -> None:
    data = yaml.safe_load(default_fleet_files("canary")["fleet.yaml"])
    data["unexpected"] = True
    with pytest.raises(FleetError, match="extra_forbidden"):
        parse_fleet_spec(yaml.safe_dump(data).encode())


def test_deeply_nested_yaml_fails_with_typed_configuration_error() -> None:
    content = ("jobs: " + "[" * 650 + "0" + "]" * 650 + "\n").encode()

    with pytest.raises(FleetError) as captured:
        parse_fleet_spec(content)

    assert captured.value.code is ErrorCode.CONFIG_INVALID


def test_reference_traversal_is_rejected() -> None:
    files = copy.deepcopy(default_fleet_files("canary"))
    data = yaml.safe_load(files["fleet.yaml"])
    data["spec"]["agents"]["engineer"]["instructions"] = "../outside.md"
    files["fleet.yaml"] = yaml.safe_dump(data)
    files["../outside.md"] = "untrusted"
    with pytest.raises(FleetError) as captured:
        validate_fleet_files(files)
    assert captured.value.code is ErrorCode.CONFIG_INVALID


def test_fleet_yaml_symlink_escape_is_rejected(tmp_path: Path) -> None:
    files = default_fleet_files("canary")
    outside = tmp_path / "outside.yaml"
    outside.write_text(files["fleet.yaml"], encoding="utf-8")
    fleet_root = tmp_path / ".fleet"
    fleet_root.mkdir()
    (fleet_root / "fleet.yaml").symlink_to(outside)
    with pytest.raises(FleetError) as captured:
        load_fleet_spec(fleet_root / "fleet.yaml")
    assert captured.value.code is ErrorCode.PATH_OUTSIDE_SCOPE


def test_profile_drives_repository_specific_verification_commands(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        '{"packageManager":"pnpm@9","scripts":{"test":"vitest run","build":"vite build"}}',
        encoding="utf-8",
    )
    (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: '9'\n", encoding="utf-8")
    profile = StaticRepositoryProfiler().profile(tmp_path).profile
    files = default_fleet_files("node-project", profile)
    verification = parse_verification_profile(files["project/verification.yaml"].encode())
    assert verification.commands["node-test"].executable == "pnpm"
    assert verification.commands["node-test"].argv == ["run", "test"]
    assert verification.commands["node-build"].argv == ["run", "build"]

    (tmp_path / "package.json").write_text(
        '{"packageManager":"pnpm@9","scripts":{"build":"vite build"}}',
        encoding="utf-8",
    )
    changed_profile = StaticRepositoryProfiler().profile(tmp_path).profile
    changed_files = default_fleet_files("node-project", changed_profile)
    changed_verification = parse_verification_profile(
        changed_files["project/verification.yaml"].encode()
    )
    assert "node-test" not in changed_verification.commands


def test_config_snapshot_hash_covers_every_referenced_file(tmp_path: Path) -> None:
    adapter = YamlConfigurationAdapter()
    fleet_root = tmp_path / ".fleet"
    adapter.apply(fleet_root, adapter.default_files("snapshot-project"))
    _, initial = adapter.load_snapshot(fleet_root / "fleet.yaml")
    initial_hash = adapter.snapshot_hash(initial)

    verification = fleet_root / "project" / "verification.yaml"
    verification.write_text(
        verification.read_text(encoding="utf-8") + "\n# reviewed change\n",
        encoding="utf-8",
    )
    _, verification_changed = adapter.load_snapshot(fleet_root / "fleet.yaml")
    assert adapter.snapshot_hash(verification_changed) != initial_hash

    verification.write_text(
        next(item.content for item in initial.files if item.path == "project/verification.yaml"),
        encoding="utf-8",
    )
    prompt = fleet_root / "agents" / "engineer.md"
    prompt.write_text(prompt.read_text(encoding="utf-8") + "Changed.\n", encoding="utf-8")
    _, prompt_changed = adapter.load_snapshot(fleet_root / "fleet.yaml")
    assert adapter.snapshot_hash(prompt_changed) != initial_hash


def test_filesystem_config_limit_is_checked_before_content_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = YamlConfigurationAdapter()
    fleet_root = tmp_path / ".fleet"
    adapter.apply(fleet_root, adapter.default_files("oversized-project"))
    oversized = fleet_root / "agents" / "engineer.md"
    oversized.write_bytes(b"x" * (MAX_CONFIG_BYTES + 1))
    original_read_bytes = Path.read_bytes

    def guarded_read_bytes(path: Path) -> bytes:
        if path == oversized:
            raise AssertionError("oversized configuration was read before its size was rejected")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", guarded_read_bytes)

    with pytest.raises(FleetError) as captured:
        adapter.load_snapshot(fleet_root / "fleet.yaml")

    assert captured.value.code is ErrorCode.CONFIG_INVALID


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO support is unavailable")
def test_config_snapshot_rejects_special_file_without_opening_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = YamlConfigurationAdapter()
    fleet_root = tmp_path / ".fleet"
    adapter.apply(fleet_root, adapter.default_files("special-file-project"))
    special = fleet_root / "agents" / "engineer.md"
    special.unlink()
    os.mkfifo(special)
    original_read_bytes = Path.read_bytes

    def guarded_read_bytes(path: Path) -> bytes:
        if path == special:
            raise AssertionError("special configuration file was opened for blocking read")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", guarded_read_bytes)

    with pytest.raises(FleetError) as captured:
        adapter.load_snapshot(fleet_root / "fleet.yaml")

    assert captured.value.code is ErrorCode.CONFIG_INVALID
