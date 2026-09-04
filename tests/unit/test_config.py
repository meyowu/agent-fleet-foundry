from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml

from agent_fleet.adapters.config.yaml import (
    default_fleet_files,
    load_fleet_spec,
    parse_fleet_spec,
    validate_fleet_files,
)
from agent_fleet.domain.errors import ErrorCode, FleetError


def test_default_fleet_spec_round_trips_strictly() -> None:
    files = default_fleet_files("canary-project")
    spec = validate_fleet_files(files)
    assert spec.spec.runtime.adapter == "fake"
    assert set(spec.spec.agents) == {"cos", "engineer", "verifier"}


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


def test_unknown_field_is_rejected() -> None:
    data = yaml.safe_load(default_fleet_files("canary")["fleet.yaml"])
    data["unexpected"] = True
    with pytest.raises(FleetError, match="extra_forbidden"):
        parse_fleet_spec(yaml.safe_dump(data).encode())


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
