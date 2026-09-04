from __future__ import annotations

import traceback
from collections import UserDict
from typing import Never

import pytest
from pydantic import ValidationError

from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.fleet_patch import (
    FleetPatch,
    FleetPatchFileChange,
    FleetPatchOperation,
    parse_and_validate_fleet_patch,
    validate_fleet_patch,
)
from agent_fleet.domain.security import Redactor, sha256_bytes

PATCH_ID = "fpatch_11111111111111111111111111111111"
PROJECT_ID = "prj_22222222222222222222222222222222"
CURRENT_HASH = "a" * 64
BEFORE_HASH = "b" * 64
CONTENT = "updated organization content\n"
AFTER_HASH = sha256_bytes(CONTENT.encode())
NO_SECRETS = Redactor()


class ExplosiveDict(dict[str, object]):
    def items(self) -> Never:
        raise RuntimeError("MAPPING-ITERATION-REGISTERED-SECRET")


def _change(
    path: str,
    *,
    operation: FleetPatchOperation = FleetPatchOperation.REPLACE,
    content: str | None = CONTENT,
) -> FleetPatchFileChange:
    return FleetPatchFileChange(
        operation=operation,
        path=path,
        before_sha256=BEFORE_HASH if operation is not FleetPatchOperation.ADD else None,
        after_sha256=(
            sha256_bytes(content.encode())
            if operation is not FleetPatchOperation.REMOVE and content is not None
            else None
        ),
        content=content,
    )


def _patch(
    changes: list[FleetPatchFileChange],
    *,
    base_hash: str = CURRENT_HASH,
) -> FleetPatch:
    return FleetPatch(
        fleet_patch_id=PATCH_ID,
        project_id=PROJECT_ID,
        base_fleet_spec_sha256=base_hash,
        changes=changes,
        rationale="Update only reviewable organization files.",
    )


@pytest.mark.parametrize(
    "path",
    [
        ".fleet/agents/engineer.md",
        ".fleet/workflows/code-change.yaml",
        ".fleet/project/charter.md",
        ".fleet/project/architecture.md",
        ".fleet/project/verification.yaml",
        ".fleet/README.md",
    ],
)
def test_allowed_organization_paths_validate(path: str) -> None:
    validate_fleet_patch(
        _patch([_change(path)]),
        current_fleet_spec_sha256=CURRENT_HASH,
        redactor=NO_SECRETS,
    )


def test_base_hash_must_match_current_fleet_spec() -> None:
    patch = _patch([_change(".fleet/agents/engineer.md")], base_hash="d" * 64)

    with pytest.raises(FleetError) as captured:
        validate_fleet_patch(
            patch,
            current_fleet_spec_sha256=CURRENT_HASH,
            redactor=NO_SECRETS,
        )

    assert captured.value.code is ErrorCode.CONFIG_INVALID
    assert "base hash does not match" in captured.value.message


def test_duplicate_change_path_is_rejected() -> None:
    path = ".fleet/agents/engineer.md"
    patch = _patch([_change(path), _change(path)])

    with pytest.raises(FleetError) as captured:
        validate_fleet_patch(
            patch,
            current_fleet_spec_sha256=CURRENT_HASH,
            redactor=NO_SECRETS,
        )

    assert captured.value.code is ErrorCode.CONFIG_INVALID
    assert "more than once" in captured.value.message


@pytest.mark.parametrize(
    "path",
    [
        ".fleet/fleet.yaml",
        ".fleet/trust/rules.yaml",
        ".fleet/secrets/provider.env",
        ".fleet/audit/events.jsonl",
        ".fleet/sandbox/hard-limits.yaml",
    ],
)
def test_protected_fleet_paths_are_rejected(path: str) -> None:
    with pytest.raises(FleetError) as captured:
        validate_fleet_patch(
            _patch([_change(path)]),
            current_fleet_spec_sha256=CURRENT_HASH,
            redactor=NO_SECRETS,
        )

    assert captured.value.code is ErrorCode.CONFIG_INVALID
    assert "protected path" in captured.value.message


@pytest.mark.parametrize("operation", [FleetPatchOperation.ADD, FleetPatchOperation.REPLACE])
def test_add_and_replace_require_content(operation: FleetPatchOperation) -> None:
    with pytest.raises(ValidationError, match="require content"):
        _change(".fleet/agents/engineer.md", operation=operation, content=None)


def test_remove_rejects_replacement_content() -> None:
    with pytest.raises(ValidationError, match="cannot contain an after hash or content"):
        _change(
            ".fleet/agents/engineer.md",
            operation=FleetPatchOperation.REMOVE,
            content="unexpected replacement\n",
        )


def test_remove_without_content_is_valid() -> None:
    patch = _patch(
        [
            _change(
                ".fleet/agents/engineer.md",
                operation=FleetPatchOperation.REMOVE,
                content=None,
            )
        ]
    )

    validate_fleet_patch(
        patch,
        current_fleet_spec_sha256=CURRENT_HASH,
        redactor=NO_SECRETS,
    )


def test_casefolded_duplicate_change_path_is_rejected() -> None:
    patch = _patch(
        [
            _change(".fleet/agents/Foo.md"),
            _change(".fleet/agents/foo.md"),
        ]
    )

    with pytest.raises(FleetError, match="more than once"):
        validate_fleet_patch(
            patch,
            current_fleet_spec_sha256=CURRENT_HASH,
            redactor=NO_SECRETS,
        )


@pytest.mark.parametrize(
    ("field", "invalid_id"),
    [
        ("fleet_patch_id", "run_" + "1" * 32),
        ("project_id", "art_" + "2" * 32),
        ("rollback_of", "task_" + "3" * 32),
    ],
)
def test_fleet_patch_ids_require_dedicated_prefixes(field: str, invalid_id: str) -> None:
    values: dict[str, object] = {
        "fleet_patch_id": PATCH_ID,
        "project_id": PROJECT_ID,
        "base_fleet_spec_sha256": CURRENT_HASH,
        "changes": [_change(".fleet/agents/engineer.md")],
        "rationale": "Update the organization.",
    }
    values[field] = invalid_id

    with pytest.raises(ValidationError, match="string_pattern_mismatch"):
        FleetPatch.model_validate(values)


@pytest.mark.parametrize("location", ["content", "path", "rationale"])
def test_registered_secret_anywhere_in_patch_is_rejected(location: str) -> None:
    secret = "FLEET-PATCH-REGISTERED-SECRET"
    path = ".fleet/agents/engineer.md"
    content = CONTENT
    rationale = "Update the organization."
    if location == "content":
        content = f"Never persist {secret}.\n"
    elif location == "path":
        path = f".fleet/agents/{secret}.md"
    else:
        rationale = f"Never persist {secret}."
    patch = _patch([_change(path, content=content)]).model_copy(update={"rationale": rationale})

    with pytest.raises(FleetError, match="registered secret") as captured:
        validate_fleet_patch(
            patch,
            current_fleet_spec_sha256=CURRENT_HASH,
            redactor=Redactor([secret]),
        )
    assert secret not in str(captured.value)


def test_raw_patch_secret_is_rejected_before_schema_errors_without_echo() -> None:
    secret = "FLEET-PATCH-RAW-REGISTERED-SECRET"
    payload = _patch([_change(".fleet/agents/engineer.md")]).model_dump(mode="json")
    payload["changes"][0]["path"] = f"../{secret}"

    with pytest.raises(FleetError, match="registered secret") as captured:
        parse_and_validate_fleet_patch(
            payload,
            current_fleet_spec_sha256=CURRENT_HASH,
            redactor=Redactor([secret]),
        )

    assert secret not in str(captured.value)


def test_mapping_subclass_is_not_traversed_or_allowed_to_leak_traceback() -> None:
    secret = "FLEET-PATCH-MAPPING-REGISTERED-SECRET"
    payload = _patch([_change(".fleet/agents/engineer.md")]).model_dump(mode="json")
    payload["changes"][0]["path"] = f"../{secret}"

    with pytest.raises(FleetError, match="plain JSON object") as captured:
        parse_and_validate_fleet_patch(
            UserDict(payload),
            current_fleet_spec_sha256=CURRENT_HASH,
            redactor=Redactor([secret]),
        )

    rendered = "".join(traceback.format_exception(captured.value))
    assert captured.value.__cause__ is None
    assert secret not in str(captured.value)
    assert secret not in rendered


def test_raw_patch_rejects_non_json_mapping_without_rendering_its_values() -> None:
    payload = UserDict(_patch([_change(".fleet/agents/engineer.md")]).model_dump(mode="json"))

    with pytest.raises(FleetError, match="plain JSON object") as captured:
        parse_and_validate_fleet_patch(
            payload,
            current_fleet_spec_sha256=CURRENT_HASH,
            redactor=NO_SECRETS,
        )

    assert captured.value.__cause__ is None


def test_raw_patch_never_traverses_a_dict_subclass() -> None:
    secret = "MAPPING-ITERATION-REGISTERED-SECRET"

    with pytest.raises(FleetError, match="plain JSON object") as captured:
        parse_and_validate_fleet_patch(
            ExplosiveDict(),
            current_fleet_spec_sha256=CURRENT_HASH,
            redactor=Redactor([secret]),
        )

    rendered = "".join(traceback.format_exception(captured.value))
    assert captured.value.__cause__ is None
    assert secret not in rendered


def test_raw_patch_rejects_excessive_depth_without_recursion_error() -> None:
    payload: object = {"leaf": "value"}
    for _ in range(2_000):
        payload = {"nested": payload}

    with pytest.raises(FleetError, match="plain JSON object") as captured:
        parse_and_validate_fleet_patch(
            payload,
            current_fleet_spec_sha256=CURRENT_HASH,
            redactor=NO_SECRETS,
        )

    assert captured.value.__cause__ is None


def test_raw_patch_rejects_cyclic_builtin_json_container() -> None:
    payload: dict[str, object] = {}
    payload["cycle"] = payload

    with pytest.raises(FleetError, match="plain JSON object") as captured:
        parse_and_validate_fleet_patch(
            payload,
            current_fleet_spec_sha256=CURRENT_HASH,
            redactor=NO_SECRETS,
        )

    assert captured.value.__cause__ is None


def test_raw_patch_parser_normalizes_validation_failures() -> None:
    payload = _patch([_change(".fleet/agents/engineer.md")]).model_dump(mode="json")
    payload["project_id"] = "run_" + "2" * 32

    with pytest.raises(FleetError, match="required schema") as captured:
        parse_and_validate_fleet_patch(
            payload,
            current_fleet_spec_sha256=CURRENT_HASH,
            redactor=NO_SECRETS,
        )

    assert captured.value.code is ErrorCode.CONFIG_INVALID


@pytest.mark.parametrize(
    "path",
    [
        ".fleet/agents//engineer.md",
        ".fleet/agents/./engineer.md",
        ".fleet/agents/engineer.md/",
        ".fleet/agents/../../outside.md",
        "/.fleet/agents/engineer.md",
        ".fleet\\agents\\engineer.md",
        ".fleet/agents/engineer\x00.md",
    ],
)
def test_noncanonical_fleet_patch_path_is_rejected(path: str) -> None:
    with pytest.raises(ValidationError):
        _change(path)


def test_operation_hash_contract_is_strict() -> None:
    path = ".fleet/agents/engineer.md"
    with pytest.raises(ValidationError, match="cannot declare a prior"):
        FleetPatchFileChange(
            operation=FleetPatchOperation.ADD,
            path=path,
            before_sha256=BEFORE_HASH,
            after_sha256=AFTER_HASH,
            content=CONTENT,
        )
    with pytest.raises(ValidationError, match="require a prior"):
        FleetPatchFileChange(
            operation=FleetPatchOperation.REPLACE,
            path=path,
            after_sha256=AFTER_HASH,
            content=CONTENT,
        )
    with pytest.raises(ValidationError, match="does not match"):
        FleetPatchFileChange(
            operation=FleetPatchOperation.REPLACE,
            path=path,
            before_sha256=BEFORE_HASH,
            after_sha256="d" * 64,
            content=CONTENT,
        )
    with pytest.raises(ValidationError, match="cannot contain an after hash"):
        FleetPatchFileChange(
            operation=FleetPatchOperation.REMOVE,
            path=path,
            before_sha256=BEFORE_HASH,
            after_sha256=AFTER_HASH,
        )
