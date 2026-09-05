from __future__ import annotations

import json
import traceback
from collections import UserDict
from typing import Never

import pytest
from pydantic import ValidationError

from agent_fleet.domain import fleet_patch, models
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


def test_original_imports_are_canonical_models_with_compatible_wire_output() -> None:
    for name in (
        "FleetPatch",
        "FleetPatchFileChange",
        "FleetPatchOperation",
        "FleetPatchPath",
        "FleetPatchContent",
        "FleetPatchRationale",
    ):
        assert getattr(fleet_patch, name) is getattr(models, name)
    patch = _patch([_change(".fleet/agents/engineer.md")])
    expected = {
        "api_version": "agentfleet.dev/v1alpha1",
        "kind": "FleetPatch",
        "fleet_patch_id": PATCH_ID,
        "project_id": PROJECT_ID,
        "base_fleet_spec_sha256": CURRENT_HASH,
        "changes": [
            {
                "operation": "replace",
                "path": ".fleet/agents/engineer.md",
                "before_sha256": BEFORE_HASH,
                "after_sha256": AFTER_HASH,
                "content": CONTENT,
            }
        ],
        "rationale": "Update only reviewable organization files.",
        "rollback_of": None,
    }
    assert patch.model_dump_json() == json.dumps(expected, separators=(",", ":"))
    assert (
        parse_and_validate_fleet_patch(
            expected, current_fleet_spec_sha256=CURRENT_HASH, redactor=NO_SECRETS
        )
        == patch
    )


@pytest.mark.parametrize("name", ["backend-integration", "Python_3.13", "0", "A" * 100])
def test_canonical_declarative_skill_paths_are_reviewable(name: str) -> None:
    patch = _patch([_change(f".fleet/skills/{name}.yaml")])
    validate_fleet_patch(patch, current_fleet_spec_sha256=CURRENT_HASH, redactor=NO_SECRETS)
    assert (
        parse_and_validate_fleet_patch(
            patch.model_dump(mode="json"),
            current_fleet_spec_sha256=CURRENT_HASH,
            redactor=NO_SECRETS,
        )
        == patch
    )


@pytest.mark.parametrize(
    "path",
    [
        ".fleet/skills",
        ".fleet/Skills/backend.yaml",
        ".fleet/skills/backend.yml",
        ".fleet/skills/backend.YAML",
        ".fleet/skills/.hidden.yaml",
        ".fleet/skills/-backend.yaml",
        ".fleet/skills/_backend.yaml",
        ".fleet/skills/backend test.yaml",
        ".fleet/skills/backend*.yaml",
        ".fleet/skills/backend/nested.yaml",
        ".fleet/skills/验证.yaml",
        ".fleet/skills/" + "a" * 101 + ".yaml",
    ],
)
def test_skill_path_allowance_is_exact_and_bounded(path: str) -> None:
    with pytest.raises(FleetError, match="protected path"):
        validate_fleet_patch(
            _patch([_change(path)]),
            current_fleet_spec_sha256=CURRENT_HASH,
            redactor=NO_SECRETS,
        )


@pytest.mark.parametrize("control", [*range(32), 127])
def test_all_ascii_path_controls_are_rejected(control: int) -> None:
    path = f".fleet/agents/engineer{chr(control)}.md"
    with pytest.raises(ValidationError):
        _change(path)
    payload = _patch([_change(".fleet/agents/engineer.md")]).model_dump(mode="json")
    payload["changes"][0]["path"] = path
    with pytest.raises(FleetError, match="required schema") as captured:
        parse_and_validate_fleet_patch(
            payload, current_fleet_spec_sha256=CURRENT_HASH, redactor=NO_SECRETS
        )
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("ancestor", ["Folder", "Straße"])
def test_casefold_ancestor_collisions_are_rejected_in_either_order(
    reverse: bool, ancestor: str
) -> None:
    changes = [
        _change(f".fleet/agents/{ancestor}"),
        _change(f".fleet/agents/{ancestor.casefold()}/child.md"),
    ]
    if reverse:
        changes.reverse()
    with pytest.raises(FleetError, match="ancestor collision"):
        validate_fleet_patch(
            _patch(changes), current_fleet_spec_sha256=CURRENT_HASH, redactor=NO_SECRETS
        )


def test_sibling_paths_with_shared_prefix_are_not_ancestor_collisions() -> None:
    validate_fleet_patch(
        _patch([_change(".fleet/agents/Foo"), _change(".fleet/agents/foobar/child.md")]),
        current_fleet_spec_sha256=CURRENT_HASH,
        redactor=NO_SECRETS,
    )


class UnreachableRedactor(Redactor):
    def contains_secret_data(self, value: object) -> bool:
        raise AssertionError("Malformed JSON must be rejected before the secret scan")


class ExplosiveList(list[object]):
    def __iter__(self) -> Never:
        raise AssertionError("List subclasses must not be traversed")


class ExplosiveString(str):
    def encode(self, encoding: str = "utf-8", errors: str = "strict") -> Never:
        raise AssertionError("String subclasses must not be encoded")


@pytest.mark.parametrize(
    "value",
    [
        ExplosiveDict(),
        ExplosiveList(),
        ExplosiveString("not plain JSON"),
        b"not text",
        ("not", "a", "list"),
        {"not", "a", "list"},
        float("nan"),
        float("inf"),
        float("-inf"),
        "\ud800",
        "\udfff",
    ],
    ids=[
        "dict-subclass",
        "list-subclass",
        "str-subclass",
        "bytes",
        "tuple",
        "set",
        "nan",
        "infinity",
        "negative-infinity",
        "high-surrogate",
        "low-surrogate",
    ],
)
def test_nested_non_json_values_are_rejected_before_secret_scan(value: object) -> None:
    with pytest.raises(FleetError, match="plain JSON object") as captured:
        parse_and_validate_fleet_patch(
            {"untrusted": value},
            current_fleet_spec_sha256=CURRENT_HASH,
            redactor=UnreachableRedactor(),
        )
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


@pytest.mark.parametrize(
    "key", [ExplosiveString("key"), "\ud800", 1], ids=["str-subclass", "surrogate", "integer"]
)
def test_non_json_keys_are_rejected_before_secret_scan(key: object) -> None:
    with pytest.raises(FleetError, match="plain JSON object"):
        parse_and_validate_fleet_patch(
            {key: "value"},
            current_fleet_spec_sha256=CURRENT_HASH,
            redactor=UnreachableRedactor(),
        )


def test_plain_json_depth_and_node_boundaries_are_exact() -> None:
    nested: object = "leaf"
    for _ in range(fleet_patch.MAX_RAW_FLEET_PATCH_DEPTH):
        nested = [nested]
    assert fleet_patch._is_builtin_json_value(nested)
    assert not fleet_patch._is_builtin_json_value([nested])
    assert fleet_patch._is_builtin_json_value([None] * 9_999)
    assert not fleet_patch._is_builtin_json_value([None] * 10_000)


def test_plain_json_string_budget_counts_utf8_bytes_and_mapping_keys() -> None:
    assert fleet_patch._is_builtin_json_value("a" * 4_000_000)
    assert not fleet_patch._is_builtin_json_value("a" * 4_000_001)
    assert fleet_patch._is_builtin_json_value({"é": "é" * 1_999_999})
    assert not fleet_patch._is_builtin_json_value({"é": "é" * 2_000_000})
    assert not fleet_patch._is_builtin_json_value({"a" * 4_000_001: None})


@pytest.mark.parametrize("value", ["a" * 4_000_001, [None] * 10_000])
def test_aggregate_overflow_fails_before_secret_scan(value: object) -> None:
    with pytest.raises(FleetError, match="plain JSON object"):
        parse_and_validate_fleet_patch(
            {"untrusted": value},
            current_fleet_spec_sha256=CURRENT_HASH,
            redactor=UnreachableRedactor(),
        )


def test_typed_aggregate_budget_is_not_only_a_per_file_limit() -> None:
    patch = _patch(
        [_change(f".fleet/agents/role-{index}.md", content="a" * 1_000_000) for index in range(4)]
    )
    with pytest.raises(FleetError, match="plain JSON object"):
        validate_fleet_patch(
            patch,
            current_fleet_spec_sha256=CURRENT_HASH,
            redactor=UnreachableRedactor(),
        )


def test_valid_proposal_at_exact_aggregate_string_budget_is_accepted() -> None:
    changes = [
        _change(f".fleet/agents/role-{index}.md", content="a" * 1_000_000) for index in range(3)
    ]
    changes.append(_change(".fleet/agents/last.md", content=""))
    patch = _patch(changes)
    payload = patch.model_dump(mode="json")
    string_bytes = sum(len(key.encode()) for key in payload)
    string_bytes += sum(len(value.encode()) for value in payload.values() if isinstance(value, str))
    for change in payload["changes"]:
        string_bytes += sum(len(key.encode()) for key in change)
        string_bytes += sum(
            len(value.encode()) for value in change.values() if isinstance(value, str)
        )
    changes[-1] = _change(".fleet/agents/last.md", content="a" * (4_000_000 - string_bytes))
    patch = _patch(changes)
    validate_fleet_patch(patch, current_fleet_spec_sha256=CURRENT_HASH, redactor=NO_SECRETS)
    assert (
        parse_and_validate_fleet_patch(
            patch.model_dump(mode="json"),
            current_fleet_spec_sha256=CURRENT_HASH,
            redactor=NO_SECRETS,
        )
        == patch
    )


def test_unicode_content_and_inverse_reference_preserve_valid_wire_values() -> None:
    rollback_of = "fpatch_" + "3" * 32
    patch = _patch([_change(".fleet/agents/engineer.md", content="验证 backend 🔎\n")]).model_copy(
        update={"rollback_of": rollback_of}
    )
    parsed = parse_and_validate_fleet_patch(
        patch.model_dump(mode="json"),
        current_fleet_spec_sha256=CURRENT_HASH,
        redactor=NO_SECRETS,
    )
    assert parsed.model_dump_json() == patch.model_dump_json()
    assert parsed.rollback_of == rollback_of


@pytest.mark.parametrize(
    "update",
    [
        {"content": "changed without its reviewed hash"},
        {"after_sha256": "c" * 64},
        {"before_sha256": None},
        {"path": ".fleet/agents/bad\x1f.md"},
        {"operation": "replace"},
        {"content": "\ud800"},
        {"content": ExplosiveString("untrusted")},
    ],
)
def test_typed_validation_reparses_mutated_change_fields(update: dict[str, object]) -> None:
    change = _change(".fleet/agents/engineer.md").model_copy(update=update)
    patch = _patch([_change(".fleet/agents/engineer.md")]).model_copy(update={"changes": [change]})
    with pytest.raises(FleetError) as captured:
        validate_fleet_patch(patch, current_fleet_spec_sha256=CURRENT_HASH, redactor=NO_SECRETS)
    assert captured.value.code is ErrorCode.CONFIG_INVALID
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


def test_typed_validation_rejects_mutated_base_and_protected_path() -> None:
    patch = _patch([_change(".fleet/agents/engineer.md")])
    with pytest.raises(FleetError, match="base hash"):
        validate_fleet_patch(
            patch.model_copy(update={"base_fleet_spec_sha256": BEFORE_HASH}),
            current_fleet_spec_sha256=CURRENT_HASH,
            redactor=NO_SECRETS,
        )
    patch.changes[0].path = ".fleet/fleet.yaml"
    with pytest.raises(FleetError, match="protected path"):
        validate_fleet_patch(patch, current_fleet_spec_sha256=CURRENT_HASH, redactor=NO_SECRETS)


def test_typed_validation_does_not_serialize_malformed_values() -> None:
    cycle: list[object] = []
    cycle.append(cycle)
    patch = _patch([_change(".fleet/agents/engineer.md")]).model_copy(update={"changes": cycle})
    with pytest.raises(FleetError, match="required schema") as captured:
        validate_fleet_patch(
            patch, current_fleet_spec_sha256=CURRENT_HASH, redactor=UnreachableRedactor()
        )
    assert captured.value.__context__ is None


class ExplosiveFleetPatch(FleetPatch):
    def model_dump(self, **kwargs: object) -> Never:
        raise AssertionError("Model subclasses must not be serialized")


def test_typed_validation_rejects_model_subclass_without_serialization() -> None:
    patch = ExplosiveFleetPatch.model_validate(
        _patch([_change(".fleet/agents/engineer.md")]).model_dump(mode="json")
    )
    with pytest.raises(FleetError, match="required schema"):
        validate_fleet_patch(
            patch, current_fleet_spec_sha256=CURRENT_HASH, redactor=UnreachableRedactor()
        )


def test_typed_secret_scan_precedes_mutated_content_hash_validation() -> None:
    secret = "REGISTERED-TYPED-SECRET-WITHOUT-CORRECT-HASH"
    patch = _patch([_change(".fleet/agents/engineer.md")])
    patch.changes[0].content = secret
    with pytest.raises(FleetError, match="registered secret") as captured:
        validate_fleet_patch(
            patch, current_fleet_spec_sha256=CURRENT_HASH, redactor=Redactor([secret])
        )
    assert captured.value.__context__ is None
    assert secret not in "".join(traceback.format_exception(captured.value))


def test_raw_schema_failure_has_no_input_in_exception_context() -> None:
    sentinel = "UNREGISTERED-INVALID-INPUT-MUST-NOT-BE-ECHOED"
    payload = _patch([_change(".fleet/agents/engineer.md")]).model_dump(mode="json")
    payload["project_id"] = sentinel
    with pytest.raises(FleetError, match="required schema") as captured:
        parse_and_validate_fleet_patch(
            payload, current_fleet_spec_sha256=CURRENT_HASH, redactor=NO_SECRETS
        )
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
    assert sentinel not in "".join(traceback.format_exception(captured.value))


def test_registered_secret_in_unknown_key_is_rejected_before_schema() -> None:
    secret = "REGISTERED-UNKNOWN-KEY-SECRET"
    payload = _patch([_change(".fleet/agents/engineer.md")]).model_dump(mode="json")
    payload[secret] = "unexpected"
    with pytest.raises(FleetError, match="registered secret") as captured:
        parse_and_validate_fleet_patch(
            payload, current_fleet_spec_sha256=CURRENT_HASH, redactor=Redactor([secret])
        )
    assert captured.value.__context__ is None
    assert secret not in "".join(traceback.format_exception(captured.value))
