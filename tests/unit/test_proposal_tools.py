from __future__ import annotations

import asyncio
import builtins
import json
import os
import socket
import subprocess
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Never

import pytest

from agent_fleet.application.proposal_tools import ProposalHashToolCatalog
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import RuntimeToolCall, RuntimeToolOutcome
from agent_fleet.domain.security import Redactor, sha256_bytes
from agent_fleet.ports.runtime import RuntimeToolCatalog

_VISIBLE = frozenset({".fleet/README.md"})


def _call(
    content: str = "Reviewed complete proposal text\n",
    *,
    call_id: str = "hash-1",
    operation: str = "replace",
    path: str = ".fleet/README.md",
) -> RuntimeToolCall:
    return RuntimeToolCall(
        call_id=call_id,
        name="fleet_content_sha256",
        arguments={"operation": operation, "path": path, "content": content},
    )


def test_exactly_one_pure_target_bound_tool_is_exposed() -> None:
    catalog: RuntimeToolCatalog = ProposalHashToolCatalog(Redactor(), visible_paths=_VISIBLE)
    (definition,) = catalog.definitions
    assert definition.name == "fleet_content_sha256" and not definition.side_effect
    assert definition.parameters_json_schema == {
        "type": "object",
        "properties": {
            "operation": {"type": "string", "enum": ["add", "replace"]},
            "path": {"type": "string", "minLength": 8, "maxLength": 4096, "pattern": r"^\.fleet/"},
            "content": {"type": "string", "maxLength": 32768},
        },
        "required": ["operation", "path", "content"],
        "additionalProperties": False,
    }
    definition.parameters_json_schema["additionalProperties"] = True
    assert catalog.definitions[0].parameters_json_schema["additionalProperties"] is False
    assert catalog.records == ()


@pytest.mark.asyncio
@pytest.mark.parametrize("content", ["", "ASCII\n", "验证 café 🔎\r\n", "e\u0301", "\x00\t\n"])
async def test_exact_utf8_content_hash_and_size(content: str) -> None:
    catalog = ProposalHashToolCatalog(Redactor(), visible_paths=_VISIBLE)
    result = await catalog.execute(_call(content))
    assert result.content == {
        "operation": "replace",
        "path": ".fleet/README.md",
        "sha256": sha256_bytes(content.encode()),
        "size_bytes": len(content.encode()),
    }
    assert result.outcome is RuntimeToolOutcome.SUCCEEDED
    assert result.artifact_ids == ()
    (record,) = catalog.records
    assert record.call_id == "hash-1" and record.name == "fleet_content_sha256"
    assert record.outcome is RuntimeToolOutcome.SUCCEEDED
    assert not record.side_effect and not record.side_effect_committed
    assert record.artifact_ids == ()


@pytest.mark.asyncio
async def test_existing_json_ceiling_is_enforced_at_exact_byte_boundary() -> None:
    overhead = len(
        json.dumps(_call("").arguments, ensure_ascii=False, separators=(",", ":")).encode()
    )
    remaining = 65536 - overhead
    content = "🔎" * (remaining // 4) + "a" * (remaining % 4)
    call = _call(content)
    assert (
        len(json.dumps(call.arguments, ensure_ascii=False, separators=(",", ":")).encode()) == 65536
    )
    catalog = ProposalHashToolCatalog(Redactor(), visible_paths=_VISIBLE)
    result = await catalog.execute(call)
    assert result.content["size_bytes"] == remaining
    invalid = call.model_copy(update={"arguments": {**call.arguments, "content": content + "a"}})
    with pytest.raises(FleetError):
        await catalog.execute(invalid)
    assert len(catalog.records) == 1


class ExplosiveString(str):
    def encode(self, encoding: str = "utf-8", errors: str = "strict") -> Never:
        raise AssertionError("A string subclass must never be encoded")


class ExplosiveDict(dict[str, object]):
    def items(self) -> Never:
        raise AssertionError("A dictionary subclass must never be traversed")


class ExplosiveCall(RuntimeToolCall):
    def model_dump(self, **kwargs: object) -> Never:
        raise AssertionError("A call subclass must never be serialized")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"content": "text", "extra": "/outside"},
        {"content": b"bytes"},
        {"content": ["nested"]},
        {"content": {"nested": "value"}},
        {"content": None},
        {"content": float("nan")},
        {"content": "\ud800"},
        {"content": "a" * 32769},
        {"content": "🔎" * 32768},
        {"content": "\x00" * 12000},
        {"content": ExplosiveString("text")},
        ExplosiveDict(content="text"),
        {ExplosiveString("content"): "text"},
    ],
    ids=[
        "empty",
        "extra",
        "bytes",
        "list",
        "dict",
        "null",
        "nan",
        "surrogate",
        "characters",
        "utf8-bytes",
        "json-escapes",
        "str-subclass",
        "dict-subclass",
        "key-subclass",
    ],
)
async def test_malformed_or_overbounded_constructed_arguments_fail_closed(
    arguments: object,
) -> None:
    # Supply the new valid target fields so each historical malformed-content
    # case still reaches its original safety boundary, not a missing-key check.
    if type(arguments) is dict:
        arguments = {"operation": "replace", "path": ".fleet/README.md", **arguments}
    catalog = ProposalHashToolCatalog(Redactor(), visible_paths=_VISIBLE)
    call = _call().model_copy(update={"arguments": arguments})
    with pytest.raises(FleetError) as caught:
        await catalog.execute(call)
    assert caught.value.code is ErrorCode.COMMAND_DENIED
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert catalog.records == () and catalog._completed == {}


@pytest.mark.asyncio
async def test_cycles_and_call_schema_subclasses_are_not_traversed() -> None:
    cycle: dict[str, object] = {}
    cycle["content"] = cycle
    cycle.update(operation="replace", path=".fleet/README.md")
    calls = [
        _call().model_copy(update={"arguments": cycle}),
        RuntimeToolCall.model_construct(),  # type: ignore[call-arg]
        _call().model_copy(update={"extra": "untrusted"}),
        _call().model_copy(update={"call_id": "../unsafe"}),
        _call().model_copy(update={"name": "workspace_write_file"}),
        ExplosiveCall.model_validate(_call().model_dump(mode="json")),
    ]
    catalog = ProposalHashToolCatalog(Redactor(), visible_paths=_VISIBLE)
    for call in calls:
        with pytest.raises(FleetError) as caught:
            await catalog.execute(call)
        assert caught.value.__context__ is None
    assert catalog.records == () and catalog._completed == {}


@pytest.mark.asyncio
async def test_repeat_uses_one_budget_unit_and_returns_detached_original_result() -> None:
    catalog = ProposalHashToolCatalog(Redactor(), visible_paths=_VISIBLE, max_calls=1)
    call = _call()
    catalog.validate(call)
    assert catalog.records == ()
    original = await catalog.execute(call)
    original.content["sha256"] = "caller-mutated"
    original.content["operation"] = "add"
    original.content["path"] = ".fleet/agents/caller.yaml"
    catalog.validate(call)
    repeated = await catalog.execute(call)
    assert repeated.content["sha256"] == sha256_bytes(str(call.arguments["content"]).encode())
    assert repeated.content["operation"] == "replace"
    assert repeated.content["path"] == ".fleet/README.md"
    assert len(catalog.records) == 1
    assert len(catalog._completed) == 1
    with pytest.raises(FleetError) as caught:
        await catalog.execute(_call(call_id="hash-2"))
    assert caught.value.code is ErrorCode.RUNTIME_BUDGET_EXCEEDED


@pytest.mark.asyncio
async def test_call_id_collision_never_replaces_original_result() -> None:
    catalog = ProposalHashToolCatalog(Redactor(), visible_paths=_VISIBLE)
    original = await catalog.execute(_call("original content"))
    with pytest.raises(FleetError) as caught:
        await catalog.execute(_call("changed content"))
    assert caught.value.code is ErrorCode.COMMAND_DENIED
    assert await catalog.execute(_call("original content")) == original
    assert len(catalog.records) == 1


@pytest.mark.asyncio
async def test_request_hash_binds_captured_scalars_despite_caller_dict_mutation() -> None:
    call = _call("original captured content")

    class MutatingRedactor(Redactor):
        def contains_secret_data(self, value: object) -> bool:
            call.arguments["content"] = "caller changed its mutable dictionary"
            call.arguments["operation"] = "add"
            call.arguments["path"] = ".fleet/agents/caller.yaml"
            return super().contains_secret_data(value)

    catalog = ProposalHashToolCatalog(MutatingRedactor(), visible_paths=_VISIBLE)
    result = await catalog.execute(call)
    assert result.content["sha256"] == sha256_bytes(b"original captured content")
    assert result.content["operation"] == "replace"
    assert result.content["path"] == ".fleet/README.md"
    with pytest.raises(FleetError):
        await catalog.execute(call)
    assert len(catalog.records) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("when", ["before", "repeat", "digest-before", "digest-repeat"])
async def test_registered_secrets_are_scanned_fresh_even_on_cache_hit(when: str) -> None:
    content = "UNIQUE-PROPOSAL-CONTENT-NOT-A-CALL-ID"
    redactor = Redactor()
    catalog = ProposalHashToolCatalog(redactor, visible_paths=_VISIBLE)
    call = _call(content)
    if when not in {"before", "digest-before"}:
        await catalog.execute(call)
    secret = sha256_bytes(content.encode()) if when.startswith("digest-") else content
    redactor.register_secret(secret)
    with pytest.raises(FleetError) as caught:
        await catalog.execute(call)
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert secret not in "".join(traceback.format_exception(caught.value))
    assert len(catalog.records) == (0 if when in {"before", "digest-before"} else 1)


@pytest.mark.asyncio
async def test_registered_secret_in_call_identity_is_never_recorded() -> None:
    secret = "registered-call-identity"
    catalog = ProposalHashToolCatalog(Redactor([secret]), visible_paths=_VISIBLE)
    with pytest.raises(FleetError) as caught:
        await catalog.execute(_call(call_id=secret))
    assert secret not in str(caught.value)
    assert catalog.records == () and catalog._completed == {}


@pytest.mark.asyncio
async def test_raw_content_is_absent_from_result_records_and_completed_cache() -> None:
    content = "UNIQUE-LONG-CONTENT-SENTINEL-ONLY-FOR-HASHING"
    catalog = ProposalHashToolCatalog(Redactor(), visible_paths=_VISIBLE)
    result = await catalog.execute(_call(content))
    assert content not in result.model_dump_json()
    assert content not in repr(catalog.records)
    assert content not in repr(catalog._completed)
    assert "arguments" not in repr(catalog._completed)
    request_hash, stored_result = catalog._completed["hash-1"]
    assert len(request_hash) == 64 and stored_result == result


@pytest.mark.parametrize("limit", [-1, 129, True, 1.0, "32"])
def test_constructor_requires_bounded_plain_integer_budget(limit: Any) -> None:
    with pytest.raises(FleetError) as caught:
        ProposalHashToolCatalog(Redactor(), visible_paths=_VISIBLE, max_calls=limit)
    assert caught.value.code is ErrorCode.CONFIG_INVALID


@pytest.mark.asyncio
async def test_zero_budget_is_explicitly_exhausted() -> None:
    catalog = ProposalHashToolCatalog(Redactor(), visible_paths=_VISIBLE, max_calls=0)
    with pytest.raises(FleetError) as caught:
        await catalog.execute(_call())
    assert caught.value.code is ErrorCode.RUNTIME_BUDGET_EXCEEDED
    assert catalog.records == ()


@pytest.mark.asyncio
async def test_hash_tool_needs_no_io_or_external_authority(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> Never:
        raise AssertionError("Pure hash computation must not perform I/O")

    with monkeypatch.context() as isolated:
        for owner, attribute in (
            (builtins, "open"),
            (os, "open"),
            (Path, "open"),
            (socket, "socket"),
            (subprocess, "Popen"),
        ):
            isolated.setattr(owner, attribute, forbidden)
        catalog = ProposalHashToolCatalog(Redactor(), visible_paths=_VISIBLE)
        catalog.validate(_call())
        result = await catalog.execute(_call())
        assert result == await catalog.execute(_call())
    assert result.content["size_bytes"] == 32


def test_threaded_calls_cannot_race_past_local_budget() -> None:
    catalog = ProposalHashToolCatalog(Redactor(), visible_paths=_VISIBLE, max_calls=1)

    def invoke(index: int) -> str:
        try:
            asyncio.run(catalog.execute(_call("a" * 32768, call_id=f"hash-{index}")))
            return "success"
        except FleetError as error:
            return error.code.value

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(invoke, range(2)))
    assert sorted(outcomes) == sorted(["success", ErrorCode.RUNTIME_BUDGET_EXCEEDED.value])
    assert len(catalog.records) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        ".fleet/README.md",
        ".fleet/project/charter.md",
        ".fleet/project/architecture.md",
        ".fleet/project/verification.yaml",
        ".fleet/agents/engineer.yaml",
        ".fleet/agents/团队/审查.md",
        ".fleet/workflows/backend.yaml",
        ".fleet/skills/backend-integration.yaml",
    ],
)
async def test_allowed_target_add_and_visible_replace_bind_result(path: str) -> None:
    for operation, visible in (("add", frozenset()), ("replace", frozenset({path}))):
        catalog = ProposalHashToolCatalog(Redactor(), visible_paths=visible)
        result = await catalog.execute(_call(operation=operation, path=path))
        assert result.content["operation"] == operation and result.content["path"] == path
        assert result.content["sha256"] == sha256_bytes(b"Reviewed complete proposal text\n")
        assert len(catalog.records) == 1 and not catalog.records[0].side_effect


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "src/calculator.py",
        "README.md",
        ".fleet/fleet.yaml",
        ".fleet/trust/rules.yaml",
        ".fleet/project/secrets.yaml",
        ".fleet/agents/.env",
        ".fleet/workflows/.env.prod",
        ".fleet/agents/key.pem",
        ".fleet/agents/../README.md",
        ".fleet/agents//one.yaml",
        ".fleet/agents/./one.yaml",
        ".fleet/agents/a.yaml/",
        ".fleet/agents/a\\b.yaml",
        "/.fleet/agents/a.yaml",
        "other/agents/a.yaml",
        ".FLEET/agents/a.yaml",
        ".fleet/agents",
        ".fleet/skills/README.md",
        ".fleet/skills/nested/one.yaml",
        ".fleet/skills/.hidden.yaml",
        ".fleet/project/other.md",
        ".fleet/agents/\x00bad.yaml",
        ".fleet/agents/\nbad.yaml",
        ".fleet/agents/\ud800.yaml",
        ".fleet/agents/" + "a/" * 16 + "one.yaml",
        ".fleet/agents/" + "a" * 4096,
        ".fleet/agents/" + "🔎" * 1100,
    ],
)
async def test_invalid_protected_or_business_paths_fail_before_hashing(path: str) -> None:
    catalog = ProposalHashToolCatalog(Redactor(), visible_paths=_VISIBLE)
    call = _call().model_copy(
        update={"arguments": {"operation": "add", "path": path, "content": "text"}}
    )
    with pytest.raises(FleetError) as caught:
        await catalog.execute(call)
    assert caught.value.code is ErrorCode.COMMAND_DENIED
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert catalog.records == () and catalog._completed == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "arguments",
    [
        {"content": "legacy-unbound"},
        {"operation": "delete", "path": ".fleet/README.md", "content": "text"},
        {"operation": True, "path": ".fleet/README.md", "content": "text"},
        {"operation": ExplosiveString("replace"), "path": ".fleet/README.md", "content": "text"},
        {"operation": "replace", "path": ExplosiveString(".fleet/README.md"), "content": "text"},
        {"operation": "replace", "path": None, "content": "text"},
        {"operation": "replace", "path": [".fleet/README.md"], "content": "text"},
    ],
)
async def test_target_fields_are_required_plain_scalars(arguments: object) -> None:
    catalog = ProposalHashToolCatalog(Redactor(), visible_paths=_VISIBLE)
    with pytest.raises(FleetError) as caught:
        await catalog.execute(_call().model_copy(update={"arguments": arguments}))
    assert caught.value.code is ErrorCode.COMMAND_DENIED
    assert caught.value.__context__ is None and catalog.records == ()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "path"),
    [
        ("replace", ".fleet/agents/omitted.yaml"),
        ("replace", ".fleet/agents/Visible.yaml"),
        ("add", ".fleet/agents/visible.yaml"),
        ("add", ".fleet/agents/Visible.yaml"),
    ],
)
async def test_replace_needs_exact_visible_target_and_add_rejects_known_collision(
    operation: str,
    path: str,
) -> None:
    catalog = ProposalHashToolCatalog(
        Redactor(), visible_paths=frozenset({".fleet/agents/visible.yaml"})
    )
    with pytest.raises(FleetError):
        await catalog.execute(_call(operation=operation, path=path))
    assert catalog.records == ()


@pytest.mark.asyncio
async def test_visible_ineligible_file_does_not_disable_ordinary_context() -> None:
    visible = _VISIBLE | {".fleet/skills/README.md"}
    catalog = ProposalHashToolCatalog(Redactor(), visible_paths=visible)
    result = await catalog.execute(_call())
    assert result.content["path"] == ".fleet/README.md"
    with pytest.raises(FleetError):
        await catalog.execute(_call(path=".fleet/skills/README.md", call_id="invalid-target"))
    assert len(catalog.records) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", ["path", "operation-and-path"])
async def test_same_call_identity_cannot_change_valid_target_or_operation(changed: str) -> None:
    catalog = ProposalHashToolCatalog(
        Redactor(), visible_paths=_VISIBLE | {".fleet/project/charter.md"}
    )
    original = await catalog.execute(_call())
    other = (
        _call(path=".fleet/project/charter.md")
        if changed == "path"
        else _call(operation="add", path=".fleet/agents/new.yaml")
    )
    # The target is valid with a new call identity; only the attempted rebinding fails.
    catalog.validate(other.model_copy(update={"call_id": "new-identity"}))
    with pytest.raises(FleetError):
        await catalog.execute(other)
    assert await catalog.execute(_call()) == original and len(catalog.records) == 1


@pytest.mark.asyncio
async def test_current_registered_target_secret_blocks_cache_replay_without_disclosure() -> None:
    redactor = Redactor()
    catalog = ProposalHashToolCatalog(redactor, visible_paths=_VISIBLE)
    await catalog.execute(_call())
    redactor.register_secret(".fleet/README.md")
    with pytest.raises(FleetError) as caught:
        await catalog.execute(_call())
    assert ".fleet/README.md" not in "".join(traceback.format_exception(caught.value))
    assert len(catalog.records) == 1


class ExplosiveFrozenSet(frozenset[str]):
    def __iter__(self) -> Never:
        raise AssertionError("A context-set subclass must not be traversed")


@pytest.mark.parametrize(
    "visible",
    [
        None,
        set(_VISIBLE),
        list(_VISIBLE),
        ExplosiveFrozenSet(_VISIBLE),
        frozenset({ExplosiveString(".fleet/README.md")}),
        frozenset({1}),
        frozenset({"src/calculator.py"}),
        frozenset({".fleet/agents/../README.md"}),
        frozenset({".fleet/agents/.env"}),
        frozenset({".fleet/agents/\ud800.yaml"}),
        frozenset({".fleet/agents/" + "a" * 4096}),
        frozenset({".fleet/agents/one.yaml", ".fleet/agents/One.yaml"}),
        frozenset(f".fleet/agents/{index}.yaml" for index in range(257)),
    ],
)
def test_context_requires_bounded_exact_immutable_canonical_paths(visible: Any) -> None:
    with pytest.raises(FleetError) as caught:
        ProposalHashToolCatalog(Redactor(), visible_paths=visible)
    assert caught.value.code is ErrorCode.CONFIG_INVALID
    assert caught.value.__cause__ is None and caught.value.__context__ is None


def test_maximum_visible_context_and_call_limit_remain_accepted() -> None:
    visible = frozenset(f".fleet/agents/{index}.yaml" for index in range(256))
    catalog = ProposalHashToolCatalog(Redactor(), visible_paths=visible, max_calls=128)
    catalog.validate(_call(path=".fleet/agents/255.yaml"))
    assert catalog.records == ()
