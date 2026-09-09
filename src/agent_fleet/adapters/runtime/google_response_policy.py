"""Request-local raw Gemini receipts, before the SDK's coercing deserializers.

This is an accepted-body-size limit, not a network allocation limit. No raw
response or provider-issued executable content is retained by this module.
"""

from __future__ import annotations

import base64
import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

import httpx2
from pydantic import BaseModel, ValidationError

from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.security import Redactor

MAX_BODY_BYTES = 2 * 1024 * 1024
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]{0,127}\Z")
_COUNTS = frozenset(
    {
        "promptTokenCount",
        "candidatesTokenCount",
        "totalTokenCount",
        "cachedContentTokenCount",
        "thoughtsTokenCount",
        "toolUsePromptTokenCount",
    }
)
_DETAILS = frozenset(
    {
        "promptTokensDetails",
        "cacheTokensDetails",
        "candidatesTokensDetails",
        "toolUsePromptTokensDetails",
    }
)


def policy_error(*, output: bool = False) -> FleetError:
    return FleetError(
        ErrorCode.RUNTIME_OUTPUT_INVALID if output else ErrorCode.PROVIDER_FAILED,
        "The Google response did not satisfy the admitted response contract.",
        "Inspect retained accounting; do not replay an uncertain request automatically.",
        details={
            "runtime_diagnostic": {
                "category": "output_schema" if output else "provider_sdk",
                "cause_category": "schema_validation" if output else "response_policy",
            }
        },
    )


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON member")
        result[key] = value
    return result


def _nonfinite(value: str) -> None:
    raise ValueError("Nonfinite JSON number")


def bounded_json(body: bytes) -> dict[str, Any]:
    if not 1 <= len(body) <= MAX_BODY_BYTES:
        raise ValueError("JSON size is outside the accepted bound")
    value = json.loads(body, object_pairs_hook=_pairs, parse_constant=_nonfinite)
    # JSON's exponent syntax can otherwise parse to infinity without invoking
    # parse_constant (for example 1e999).
    json.dumps(value, allow_nan=False)
    if type(value) is not dict:
        raise ValueError("JSON root must be an object")
    return value


def count(value: object) -> int:
    if type(value) is not int or not 0 <= value <= 2**53 - 1:
        raise ValueError("Invalid token counter")
    return value


def _usage(value: object) -> tuple[int, int, int, int]:
    if type(value) is not dict or set(value) - _COUNTS - _DETAILS:
        raise ValueError("Unsupported usage shape")
    for key in ("promptTokenCount", "candidatesTokenCount", "totalTokenCount"):
        count(value.get(key))
    for key in set(value) & _COUNTS:
        count(value[key])
    for key in set(value) & _DETAILS:
        details = value[key]
        if type(details) is not list or len(details) > 8:
            raise ValueError("Invalid usage detail list")
        modalities: set[str] = set()
        for detail in details:
            if (
                type(detail) is not dict
                or set(detail) != {"modality", "tokenCount"}
                or detail["modality"] != "TEXT"
                or detail["modality"] in modalities
            ):
                raise ValueError("Unsupported usage detail")
            modalities.add(detail["modality"])
            count(detail["tokenCount"])
    # Optional omitted counts have an explicit additive meaning. Primary counts
    # above never receive a fabricated zero. Cache hits are already in prompt.
    input_tokens = value["promptTokenCount"] + value.get("toolUsePromptTokenCount", 0)
    output_tokens = value["candidatesTokenCount"] + value.get("thoughtsTokenCount", 0)
    total = count(input_tokens + output_tokens)
    if value["totalTokenCount"] != total:
        raise ValueError("Inconsistent usage total")
    cache = value.get("cachedContentTokenCount", 0)
    if cache > value["promptTokenCount"]:
        raise ValueError("Cache exceeds prompt count")
    return input_tokens, output_tokens, total, cache


def _signature(value: object) -> bool:
    if type(value) is not str or not 1 <= len(value) <= 16384:
        return False
    try:
        return bool(base64.b64decode(value, validate=True))
    except ValueError:
        return False


@dataclass
class _Receipt:
    active: bool = True
    names: frozenset[str] = frozenset()
    usage: tuple[int, int, int, int] | None = None
    observed: bool = False


@dataclass
class RawGoogleReceipt:
    model: str
    redactor: Redactor
    terminal_outputs: dict[str, type[BaseModel]]
    _current: ContextVar[_Receipt | None] = field(
        default_factory=lambda: ContextVar("fleet_google_raw_receipt", default=None)
    )

    @contextmanager
    def request(self) -> Iterator[None]:
        if self._current.get() is not None:
            raise policy_error()
        receipt = _Receipt()
        token = self._current.set(receipt)
        try:
            yield
        finally:
            receipt.active = False
            receipt.usage = None
            self._current.reset(token)

    def bind_tools(self, names: frozenset[str]) -> None:
        receipt = self._current.get()
        if receipt is None or not receipt.active or receipt.names:
            raise policy_error()
        receipt.names = names

    def consume(self) -> tuple[int, int, int, int]:
        receipt = self._current.get()
        if receipt is None or not receipt.active or receipt.usage is None:
            raise policy_error()
        usage = receipt.usage
        receipt.usage = None
        return usage

    async def observe(self, response: httpx2.Response) -> None:
        receipt = self._current.get()
        invalid = False
        invalid_output = False
        try:
            if receipt is None or not receipt.active or receipt.observed:
                raise ValueError("No unused request receipt")
            receipt.observed = True
            headers_secret = self.redactor.contains_secret_data(
                list(response.headers.multi_items())
            )
            response.headers.clear()
            response.headers["Content-Type"] = "application/json"
            if headers_secret:
                raise ValueError("Secret in response headers")
            if not 200 <= response.status_code < 300:
                # Do not demand successful-response evidence from an HTTP error.
                return
            raw = await response.aread()
            if self.redactor.contains_secret(raw):
                raise ValueError("Secret in response")
            body = bounded_json(raw)
            if set(body) - {"candidates", "usageMetadata", "modelVersion", "responseId"}:
                raise ValueError("Unsupported response metadata")
            if body.get("modelVersion") != self.model:
                raise ValueError("Response model does not match")
            response_id = body.get("responseId")
            if response_id is not None and (
                type(response_id) is not str or not 1 <= len(response_id) <= 256
            ):
                raise ValueError("Invalid response identity")
            candidates = body.get("candidates")
            if type(candidates) is not list or len(candidates) != 1:
                raise ValueError("Unsupported candidate count")
            candidate = candidates[0]
            if (
                type(candidate) is not dict
                or set(candidate) - {"content", "finishReason", "index"}
                or candidate.get("finishReason") != "STOP"
                or (
                    "index" in candidate
                    and (type(candidate["index"]) is not int or candidate["index"] != 0)
                )
            ):
                raise ValueError("Unsupported candidate")
            content = candidate.get("content")
            if (
                type(content) is not dict
                or set(content) != {"role", "parts"}
                or content["role"] != "model"
            ):
                raise ValueError("Unsupported content")
            parts = content["parts"]
            if type(parts) is not list or not 1 <= len(parts) <= 64:
                raise ValueError("Unsupported parts")
            for part in parts:
                if type(part) is not dict or set(part) - {
                    "text",
                    "thought",
                    "thoughtSignature",
                    "functionCall",
                }:
                    raise ValueError("Native or unsupported part")
                if "thought" in part and type(part["thought"]) is not bool:
                    raise ValueError("Invalid thought flag")
                if "thoughtSignature" in part and not _signature(part["thoughtSignature"]):
                    raise ValueError("Invalid opaque continuation signature")
                if ("text" in part) == ("functionCall" in part):
                    raise ValueError("Part must carry exactly one text or function call")
                if "text" in part:
                    if type(part["text"]) is not str or len(part["text"]) > 262144:
                        raise ValueError("Invalid text")
                    continue
                call = part["functionCall"]
                if (
                    type(call) is not dict
                    or set(call) - {"name", "args", "id"}
                    or type(call.get("name")) is not str
                    or call["name"] not in receipt.names
                    or type(call.get("args")) is not dict
                    or (
                        "id" in call
                        and (type(call["id"]) is not str or not _NAME.fullmatch(call["id"]))
                    )
                ):
                    raise ValueError("Invalid local function call")
                terminal = self.terminal_outputs.get(call["name"])
                if terminal is not None:
                    try:
                        # Google wire schemas omit some original constraints. The
                        # trusted original model, not the transformed schema, wins.
                        terminal.model_validate_json(json.dumps(call["args"]), strict=True)
                    except ValidationError:
                        invalid_output = True
                        raise ValueError("Invalid terminal output") from None
            receipt.usage = _usage(body.get("usageMetadata"))
        except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
            invalid = True
        if invalid:
            raise policy_error(output=invalid_output) from None
