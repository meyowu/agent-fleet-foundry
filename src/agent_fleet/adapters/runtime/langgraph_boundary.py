"""Pinned, lazy LangGraph and raw Responses boundaries; no Gateway execution."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, TypeVar

from openai import APITimeoutError, OpenAIError
from pydantic import BaseModel, ValidationError

from agent_fleet.adapters.runtime.failure_diagnostics import runtime_failure_details
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import RuntimeToolCall, UsageRecord
from agent_fleet.domain.runtime_diagnostics import RuntimeFailureCategory
from agent_fleet.domain.security import Redactor

MAX_ENVELOPE_BYTES = 2 * 1024 * 1024
_T = TypeVar("_T")


class _ResponsePolicyFailure(StrEnum):
    ENVELOPE = "The LangGraph response envelope did not satisfy the trusted contract."
    MODEL = "The LangGraph response model did not match the selected model."
    STATUS = "The LangGraph response status was not completed."
    ERROR = "The LangGraph response reported an error."
    USAGE = "The LangGraph response usage did not satisfy the trusted contract."


def boundary_error(
    code: ErrorCode = ErrorCode.RUNTIME_OUTPUT_INVALID,
    *,
    category: str = "structured_output",
    cause: str = "unknown",
    response_failure: _ResponsePolicyFailure | None = None,
) -> FleetError:
    return FleetError(
        code,
        response_failure.value
        if response_failure is not None
        else "The bounded LangGraph invocation did not satisfy its trusted contract.",
        "Inspect retained Fleet evidence; no automatic replay is authorized.",
        details={"runtime_diagnostic": {"category": category, "cause_category": cause}},
    )


def detach_error(error: FleetError) -> FleetError:
    error.__cause__ = None
    error.__context__ = None
    error.__traceback__ = None
    if hasattr(error, "__notes__"):
        del error.__notes__
    return error


def safe_error(error: Exception) -> FleetError:
    if isinstance(error, FleetError):
        return error
    if isinstance(error, (TimeoutError, APITimeoutError)):
        return boundary_error(ErrorCode.RUNTIME_TIMEOUT, category="provider_timeout")
    if isinstance(error, ValidationError):
        return boundary_error(category="output_schema", cause="schema_validation")
    if isinstance(error, OpenAIError):
        return FleetError(
            ErrorCode.PROVIDER_FAILED,
            "The explicitly selected OpenAI request failed.",
            "Inspect retained request accounting before any explicit retry.",
            details=runtime_failure_details(error, RuntimeFailureCategory.PROVIDER_SDK),
        )
    return boundary_error(ErrorCode.PROVIDER_FAILED, category="request_construction")


def require_langgraph_policy() -> None:
    """Fail before candidate imports or secret resolution, without global mutation."""
    if any(name.startswith(("LANGGRAPH_", "LANGSMITH_", "LANGCHAIN_")) for name in os.environ):
        raise boundary_error(ErrorCode.PROVIDER_FAILED, category="request_construction")
    namespaces = ("langgraph", "langchain_core", "langsmith")
    names = set(namespaces) | {
        name
        for name in logging.Logger.manager.loggerDict
        if any(name.startswith(prefix + ".") for prefix in namespaces)
    }
    if any(logging.getLogger(name).isEnabledFor(logging.INFO) for name in names):
        raise boundary_error(ErrorCode.PROVIDER_FAILED, category="request_construction")
    from langchain_core import globals as lc_globals
    from langchain_core.tracers import context as trace_context
    from langsmith._internal import _context as ls_context
    from langsmith.run_helpers import get_tracing_context

    tracing = get_tracing_context()
    if (
        lc_globals.get_debug()
        or lc_globals.get_verbose()
        or trace_context._configure_hooks != [(trace_context.run_collector_var, False, None, None)]
        or trace_context.tracing_v2_callback_var.get() is not None
        or trace_context.run_collector_var.get() is not None
        or tracing["enabled"] not in (None, False)
        or any(
            tracing.get(name) is not None
            for name in (
                "parent",
                "client",
                "project_name",
                "tags",
                "metadata",
                "replicas",
                "distributed_parent_id",
            )
        )
        or any(
            getattr(ls_context, name) is not None
            for name in (
                "_GLOBAL_TRACING_ENABLED",
                "_GLOBAL_CLIENT",
                "_GLOBAL_PROJECT_NAME",
                "_GLOBAL_TAGS",
                "_GLOBAL_METADATA",
            )
        )
    ):
        raise boundary_error(ErrorCode.PROVIDER_FAILED, category="request_construction")


def checked_json(value: object, redactor: Redactor) -> str:
    def project(item: object, depth: int = 0) -> Any:
        if depth > 80:
            raise boundary_error(ErrorCode.RUNTIME_BUDGET_EXCEEDED, category="usage_limit")
        if isinstance(item, BaseModel):
            return project(item.model_dump(mode="json", warnings="error"), depth + 1)
        if isinstance(item, dict):
            return {key: project(child, depth + 1) for key, child in item.items()}
        if isinstance(item, (list, tuple)):
            return [project(child, depth + 1) for child in item]
        return item

    encoded = json.dumps(project(value), ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    if len(encoded.encode()) > MAX_ENVELOPE_BYTES:
        raise boundary_error(ErrorCode.RUNTIME_BUDGET_EXCEEDED, category="usage_limit")
    if redactor.contains_secret(encoded):
        raise boundary_error(ErrorCode.COMMAND_DENIED)
    return encoded


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    del value
    raise ValueError("Nonfinite JSON")


def parse_json(encoded: bytes | str, redactor: Redactor) -> Any:
    if len(encoded if isinstance(encoded, bytes) else encoded.encode()) > MAX_ENVELOPE_BYTES:
        raise boundary_error(ErrorCode.RUNTIME_BUDGET_EXCEEDED, category="usage_limit")
    if redactor.contains_secret(encoded):
        raise boundary_error(ErrorCode.COMMAND_DENIED)
    mapped = False
    parsed: Any = None
    try:
        parsed = json.loads(
            encoded, object_pairs_hook=_unique_object, parse_constant=_reject_constant
        )
        checked_json(parsed, redactor)
    except (ValueError, TypeError, RecursionError, UnicodeError):
        mapped = True
    if mapped:
        raise boundary_error(cause="schema_validation") from None
    return parsed


def action_wire_schema(original: dict[str, Any], redactor: Redactor) -> dict[str, Any]:
    """The reviewed flat, closed, all-required action subset only; never a fallback."""
    schema = parse_json(checked_json(original, redactor), redactor)
    properties = schema.get("properties")
    if (
        schema.get("type") != "object"
        or schema.get("additionalProperties") is not False
        or not isinstance(properties, dict)
        or set(schema.get("required", [])) != set(properties)
        or set(schema)
        - {"type", "properties", "required", "additionalProperties", "title", "description"}
    ):
        raise boundary_error(ErrorCode.PROVIDER_FAILED, category="request_construction")
    for value in properties.values():
        if (
            not isinstance(value, dict)
            or value.get("type") not in {"string", "integer", "boolean"}
            or ("enum" in value and (type(value["enum"]) is not list or not value["enum"]))
            or set(value)
            - {
                "type",
                "title",
                "description",
                "enum",
                "minLength",
                "maxLength",
                "pattern",
                "minimum",
                "maximum",
            }
        ):
            raise boundary_error(ErrorCode.PROVIDER_FAILED, category="request_construction")
        lengths = [
            f"{name}={value.pop(name)}" for name in ("minLength", "maxLength") if name in value
        ]
        if lengths:
            value["description"] = " ".join([value.get("description", ""), *lengths]).strip()
    schema["required"] = list(properties)
    return dict(schema)


@dataclass(frozen=True, slots=True)
class PendingCall:
    call: RuntimeToolCall
    arguments_json: str


@dataclass(frozen=True, slots=True)
class RawResponse:
    usage: UsageRecord
    calls: tuple[PendingCall, ...]
    continuation: tuple[dict[str, Any], ...]


def raw_response(encoded: bytes, model: str, redactor: Redactor) -> RawResponse:
    """Validate the raw JSON before invoking any SDK response-model parser."""
    data = parse_json(encoded, redactor)
    if (
        not isinstance(data, dict)
        or data.get("object") != "response"
        or type(data.get("id")) is not str
        or not 1 <= len(data["id"]) <= 256
    ):
        raise boundary_error(
            ErrorCode.PROVIDER_FAILED,
            category="provider_sdk",
            cause="response_policy",
            response_failure=_ResponsePolicyFailure.ENVELOPE,
        )
    if data.get("model") != model:
        raise boundary_error(
            ErrorCode.PROVIDER_FAILED,
            category="provider_sdk",
            cause="response_policy",
            response_failure=_ResponsePolicyFailure.MODEL,
        )
    if data.get("status") != "completed":
        raise boundary_error(
            ErrorCode.PROVIDER_FAILED,
            category="provider_sdk",
            cause="response_policy",
            response_failure=_ResponsePolicyFailure.STATUS,
        )
    if data.get("error") is not None:
        raise boundary_error(
            ErrorCode.PROVIDER_FAILED,
            category="provider_sdk",
            cause="response_policy",
            response_failure=_ResponsePolicyFailure.ERROR,
        )
    if (
        (data.get("background") is not None and data.get("background") is not False)
        or (data.get("store") is not None and data.get("store") is not False)
        or (
            data.get("parallel_tool_calls") is not None
            and data.get("parallel_tool_calls") is not False
        )
        or data.get("conversation") is not None
        or data.get("previous_response_id") is not None
    ):
        raise boundary_error(
            ErrorCode.PROVIDER_FAILED,
            category="provider_sdk",
            cause="response_policy",
            response_failure=_ResponsePolicyFailure.ENVELOPE,
        )
    raw = data.get("usage")
    details = {
        "input_tokens_details": {"cached_tokens", "cache_write_tokens"},
        "output_tokens_details": {"reasoning_tokens"},
    }
    counters = {"input_tokens", "output_tokens", "total_tokens"}
    if (
        type(raw) is not dict
        or not counters <= set(raw) <= counters | set(details)
        or any(
            type(raw[key]) is not int
            or not 0 <= raw[key] <= (4_000_000_000 if key == "total_tokens" else 2_000_000_000)
            for key in counters
        )
        or raw["total_tokens"] < raw["input_tokens"] + raw["output_tokens"]
    ):
        raise boundary_error(
            ErrorCode.PROVIDER_FAILED,
            category="provider_sdk",
            cause="response_policy",
            response_failure=_ResponsePolicyFailure.USAGE,
        )
    for name, fields in details.items():
        if name in raw and (
            type(raw[name]) is not dict
            or set(raw[name]) - fields
            or any(
                type(value) is not int or not 0 <= value <= 2_000_000_000
                for value in raw[name].values()
            )
        ):
            raise boundary_error(
                ErrorCode.PROVIDER_FAILED,
                category="provider_sdk",
                cause="response_policy",
                response_failure=_ResponsePolicyFailure.USAGE,
            )
    usage = UsageRecord(requests=1, **{key: raw[key] for key in counters})
    output = data.get("output")
    if type(output) is not list or not 1 <= len(output) <= 256:
        raise boundary_error()
    calls: list[PendingCall] = []
    continuation: list[dict[str, Any]] = []
    for item in output:
        if type(item) is not dict:
            raise boundary_error()
        kind = item.get("type")
        if kind == "function_call":
            if (
                set(item)
                - {
                    "type",
                    "id",
                    "call_id",
                    "name",
                    "arguments",
                    "status",
                    "namespace",
                    "caller",
                    "async",
                }
                or item.get("namespace") is not None
                or item.get("caller") is not None
                or (item.get("async") is not None and item.get("async") is not False)
                or item.get("status") not in (None, "completed")
                or any(type(item.get(key)) is not str for key in ("call_id", "name", "arguments"))
            ):
                raise boundary_error()
            arguments = parse_json(item["arguments"], redactor)
            if type(arguments) is not dict:
                raise boundary_error(category="tool_arguments", cause="schema_validation")
            call = RuntimeToolCall(call_id=item["call_id"], name=item["name"], arguments=arguments)
            if call.call_id != item["call_id"] or call.name != item["name"]:
                raise boundary_error()
            calls.append(PendingCall(call, item["arguments"]))
            continuation.append(
                {
                    "type": "function_call",
                    "call_id": call.call_id,
                    "name": call.name,
                    "arguments": item["arguments"],
                }
            )
        elif kind == "reasoning":
            if (
                set(item) - {"type", "id", "summary", "status"}
                or type(item.get("id")) is not str
                or not 1 <= len(item["id"]) <= 256
                or item.get("summary") != []
                or item.get("status") not in (None, "completed")
            ):
                raise boundary_error()
            continuation.append(item)
        else:
            # No free-text terminal, hosted/native execution, or hidden continuation.
            raise boundary_error()
    if not calls or len({call.call.call_id for call in calls}) != len(calls):
        raise boundary_error()
    return RawResponse(usage, tuple(calls), tuple(continuation))


class ExecutionOwner:
    """Retain actual node and native-exit tasks, independently of graph success."""

    def __init__(self) -> None:
        self.stop = asyncio.Event()
        self.nodes: set[asyncio.Task[Any]] = set()
        self.exits: set[asyncio.Task[Any]] = set()

    def check(self) -> None:
        if self.stop.is_set():
            raise asyncio.CancelledError

    async def node(self, action: Callable[[], Awaitable[_T]]) -> _T:
        task = asyncio.current_task()
        assert task is not None
        self.nodes.add(task)
        self.check()
        mapped: FleetError | None = None
        try:
            return await action()
        except Exception as error:
            mapped = safe_error(error)
        except asyncio.CancelledError:
            pass
        if mapped is None:
            raise asyncio.CancelledError() from None
        raise detach_error(mapped) from None

    def retain_exit(self, error: asyncio.CancelledError) -> None:
        # Only node-safe cancellation reaches the pinned graph; it can append
        # its own exit Task. Never stringify or expose cancellation arguments.
        self.exits.update(value for value in error.args if isinstance(value, asyncio.Task))

    async def drain(self) -> None:
        pending = {task for task in self.nodes | self.exits if not task.done()}
        if pending:
            await asyncio.wait(pending)
        for task in self.nodes | self.exits:
            if not task.done():
                raise boundary_error(ErrorCode.PROVIDER_FAILED, cause="client_cleanup")
            if not task.cancelled():
                task.exception()
