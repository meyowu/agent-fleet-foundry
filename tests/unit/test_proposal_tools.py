from __future__ import annotations

import asyncio
import builtins
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


def _call(
    content: str = "Reviewed complete proposal text\n", *, call_id: str = "hash-1"
) -> RuntimeToolCall:
    return RuntimeToolCall(
        call_id=call_id, name="fleet_content_sha256", arguments={"content": content}
    )


def test_exactly_one_pure_identity_free_tool_is_exposed() -> None:
    catalog: RuntimeToolCatalog = ProposalHashToolCatalog(Redactor())
    (definition,) = catalog.definitions
    assert definition.name == "fleet_content_sha256" and not definition.side_effect
    assert definition.parameters_json_schema == {
        "type": "object",
        "properties": {"content": {"type": "string", "maxLength": 32768}},
        "required": ["content"],
        "additionalProperties": False,
    }
    definition.parameters_json_schema["additionalProperties"] = True
    assert catalog.definitions[0].parameters_json_schema["additionalProperties"] is False
    assert catalog.records == ()


@pytest.mark.asyncio
@pytest.mark.parametrize("content", ["", "ASCII\n", "验证 café 🔎\r\n", "e\u0301", "\x00\t\n"])
async def test_exact_utf8_content_hash_and_size(content: str) -> None:
    catalog = ProposalHashToolCatalog(Redactor())
    result = await catalog.execute(_call(content))
    assert result.content == {
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
    # {"content":""} uses 14 bytes; each emoji takes four UTF-8 bytes.
    content = "🔎" * 16380 + "ab"
    call = _call(content)
    catalog = ProposalHashToolCatalog(Redactor())
    result = await catalog.execute(call)
    assert result.content["size_bytes"] == 65522
    invalid = call.model_copy(update={"arguments": {"content": content + "a"}})
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
        {"content": "text", "path": "/outside"},
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
    catalog = ProposalHashToolCatalog(Redactor())
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
    calls = [
        _call().model_copy(update={"arguments": cycle}),
        RuntimeToolCall.model_construct(),  # type: ignore[call-arg]
        _call().model_copy(update={"extra": "untrusted"}),
        _call().model_copy(update={"call_id": "../unsafe"}),
        _call().model_copy(update={"name": "workspace_write_file"}),
        ExplosiveCall.model_validate(_call().model_dump(mode="json")),
    ]
    catalog = ProposalHashToolCatalog(Redactor())
    for call in calls:
        with pytest.raises(FleetError) as caught:
            await catalog.execute(call)
        assert caught.value.__context__ is None
    assert catalog.records == () and catalog._completed == {}


@pytest.mark.asyncio
async def test_repeat_uses_one_budget_unit_and_returns_detached_original_result() -> None:
    catalog = ProposalHashToolCatalog(Redactor(), max_calls=1)
    call = _call()
    catalog.validate(call)
    assert catalog.records == ()
    original = await catalog.execute(call)
    original.content["sha256"] = "caller-mutated"
    catalog.validate(call)
    repeated = await catalog.execute(call)
    assert repeated.content["sha256"] == sha256_bytes(str(call.arguments["content"]).encode())
    assert len(catalog.records) == 1
    assert len(catalog._completed) == 1
    with pytest.raises(FleetError) as caught:
        await catalog.execute(_call(call_id="hash-2"))
    assert caught.value.code is ErrorCode.RUNTIME_BUDGET_EXCEEDED


@pytest.mark.asyncio
async def test_call_id_collision_never_replaces_original_result() -> None:
    catalog = ProposalHashToolCatalog(Redactor())
    original = await catalog.execute(_call("original content"))
    with pytest.raises(FleetError) as caught:
        await catalog.execute(_call("changed content"))
    assert caught.value.code is ErrorCode.COMMAND_DENIED
    assert await catalog.execute(_call("original content")) == original
    assert len(catalog.records) == 1


@pytest.mark.asyncio
async def test_request_hash_binds_captured_content_despite_caller_dict_mutation() -> None:
    call = _call("original captured content")

    class MutatingRedactor(Redactor):
        def contains_secret_data(self, value: object) -> bool:
            call.arguments["content"] = "caller changed its mutable dictionary"
            return super().contains_secret_data(value)

    catalog = ProposalHashToolCatalog(MutatingRedactor())
    result = await catalog.execute(call)
    assert result.content["sha256"] == sha256_bytes(b"original captured content")
    with pytest.raises(FleetError):
        await catalog.execute(call)
    assert len(catalog.records) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("when", ["before", "repeat", "digest-before", "digest-repeat"])
async def test_registered_secrets_are_scanned_fresh_even_on_cache_hit(when: str) -> None:
    content = "UNIQUE-PROPOSAL-CONTENT-NOT-A-CALL-ID"
    redactor = Redactor()
    catalog = ProposalHashToolCatalog(redactor)
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
    catalog = ProposalHashToolCatalog(Redactor([secret]))
    with pytest.raises(FleetError) as caught:
        await catalog.execute(_call(call_id=secret))
    assert secret not in str(caught.value)
    assert catalog.records == () and catalog._completed == {}


@pytest.mark.asyncio
async def test_raw_content_is_absent_from_result_records_and_completed_cache() -> None:
    content = "UNIQUE-LONG-CONTENT-SENTINEL-ONLY-FOR-HASHING"
    catalog = ProposalHashToolCatalog(Redactor())
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
        ProposalHashToolCatalog(Redactor(), max_calls=limit)
    assert caught.value.code is ErrorCode.CONFIG_INVALID


@pytest.mark.asyncio
async def test_zero_budget_is_explicitly_exhausted() -> None:
    catalog = ProposalHashToolCatalog(Redactor(), max_calls=0)
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
        catalog = ProposalHashToolCatalog(Redactor())
        catalog.validate(_call())
        result = await catalog.execute(_call())
        assert result == await catalog.execute(_call())
    assert result.content["size_bytes"] == 32


def test_threaded_calls_cannot_race_past_local_budget() -> None:
    catalog = ProposalHashToolCatalog(Redactor(), max_calls=1)

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
