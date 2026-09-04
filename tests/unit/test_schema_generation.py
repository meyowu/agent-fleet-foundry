from __future__ import annotations

from pathlib import Path

from agent_fleet.schemas.generate import generate


def test_schema_regeneration_has_no_diff() -> None:
    schema_root = Path(__file__).parents[2] / "src" / "agent_fleet" / "schemas"
    assert generate(schema_root, check=True) == 0
