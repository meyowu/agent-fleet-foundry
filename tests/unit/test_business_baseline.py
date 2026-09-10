from __future__ import annotations

import json
from pathlib import Path
from typing import Never

import pytest
from business_baseline_fixtures import baseline_fixture
from pydantic import ValidationError

from agent_fleet.domain.baseline import (
    BaselineCanonicalSnapshot,
    BaselineReview,
    canonical,
    freeze_command,
    freeze_snapshot,
    reconstruct_command,
    reconstruct_sandbox,
)
from agent_fleet.domain.models import CommandSpec


def test_snapshots_own_bytes_and_json_round_trip(tmp_path: Path) -> None:
    fixture = baseline_fixture(tmp_path)
    assert BaselineReview.from_canonical(fixture.review.canonical_bytes()) == fixture.review
    command = reconstruct_command(fixture.review.command)
    command.environment["CI"] = "mutated"
    assert reconstruct_command(fixture.review.command).environment == {}
    spec = reconstruct_sandbox(fixture.spec.sandbox)
    spec.environment["CI"] = "mutated"
    assert reconstruct_sandbox(fixture.spec.sandbox).environment == {}
    wire = json.loads(fixture.review.command.model_dump_json(by_alias=True))
    assert type(wire["canonical_json"]) is str and "canonical_utf8" not in wire
    with pytest.raises(ValidationError):
        fixture.review.command.__setattr__("canonical_utf8", b"{}")


@pytest.mark.parametrize(
    "raw",
    [
        b'{"a":1,"a":2}',
        b'{"a":NaN}',
        b'{"a":Infinity}',
        b"\xff",
        b"{",
        b'{"command_id":"test","executable":"sh"}',
        b'{"command_id":"test","executable":"python","extra":"no"}',
    ],
)
def test_command_rejects_ambiguous_or_unsafe_json(raw: bytes) -> None:
    with pytest.raises((ValueError, ValidationError)):
        freeze_command(raw)


@pytest.mark.parametrize(
    "changes",
    [
        {"timeout_seconds": 181},
        {"max_output_bytes": 64_001},
        {"environment": {"CI": "1"}},
        {"network_requirement": "required"},
    ],
)
def test_baseline_command_ceiling(changes: dict[str, object]) -> None:
    data = CommandSpec(command_id="test", executable="python").model_dump(mode="json")
    data.update(changes)
    with pytest.raises(ValueError):
        freeze_command(canonical(data))


@pytest.mark.parametrize("mutation", ["hash", "tag", "bytes", "mutable"])
def test_snapshot_corruption_rejected(mutation: str) -> None:
    snapshot = freeze_command(
        CommandSpec(command_id="test", executable="python").model_dump_json().encode()
    )
    if mutation == "tag":
        wrong = freeze_snapshot("capabilities-v1", json.loads(snapshot.canonical_utf8))
        with pytest.raises(ValueError):
            reconstruct_command(wrong)
        return
    data: dict[str, object] = {
        "schema_tag": "command-v1",
        "canonical_utf8": snapshot.canonical_utf8,
        "sha256": snapshot.sha256,
    }
    if mutation == "hash":
        data["sha256"] = "0" * 64
    elif mutation == "bytes":
        data["canonical_utf8"] = b" " + snapshot.canonical_utf8
    else:
        data["canonical_utf8"] = bytearray(snapshot.canonical_utf8)
    with pytest.raises(ValidationError):
        BaselineCanonicalSnapshot.model_validate(data)


def test_plain_json_rejects_callbacks_and_structural_overflow() -> None:
    class Hostile(dict[str, object]):
        def items(self) -> Never:
            raise AssertionError("must not execute callbacks")

    with pytest.raises(ValueError):
        canonical(Hostile())
    nested: object = None
    for _ in range(26):
        nested = [nested]
    with pytest.raises(ValueError):
        canonical(nested)
