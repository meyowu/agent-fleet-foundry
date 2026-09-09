"""Pinned Agents SDK boundaries; no tool executor or provider credentials live here.

The SDK owns its real loop. Fleet owns admission, accounting, and every effect.
Only completed, single-use RAM receipts are reachable from SDK tool invokers.
"""

from __future__ import annotations

import asyncio
import atexit
import json
import logging
import os
import threading
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from typing import Any, cast

from agents import ModelSettings
from agents import _debug as sdk_debug
from agents.agent_output import AgentOutputSchemaBase
from agents.exceptions import MaxTurnsExceeded, ModelBehaviorError, ModelTimeoutError, UserError
from agents.handoffs import Handoff
from agents.items import ModelResponse, TResponseInputItem, TResponseStreamEvent
from agents.models.interface import Model, ModelProvider, ModelTracing
from agents.models.openai_responses import OpenAIResponsesModel
from agents.tool import FunctionTool, Tool
from agents.tool_context import ToolContext
from agents.tracing import setup as trace_setup
from agents.tracing.provider import DefaultTraceProvider
from openai import APITimeoutError, AsyncOpenAI, OpenAIError
from openai.types.responses.response_prompt_param import ResponsePromptParam
from pydantic import BaseModel, ValidationError
from pydantic_core import to_jsonable_python

from agent_fleet.adapters.runtime.failure_diagnostics import runtime_failure_details
from agent_fleet.adapters.runtime.single_send import SingleSendGate
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import RuntimeConfiguration, RuntimeToolCall, UsageRecord
from agent_fleet.domain.runtime_diagnostics import RuntimeFailureCategory
from agent_fleet.domain.security import Redactor
from agent_fleet.ports.runtime_accounting import RuntimeAccounting

_MAX_ENVELOPE_BYTES = 2 * 1024 * 1024
_TRACE_LOCK = threading.Lock()
_TRACE_PROVIDER: DefaultTraceProvider | None = None


def boundary_error(
    code: ErrorCode = ErrorCode.RUNTIME_OUTPUT_INVALID,
    *,
    category: str = "structured_output",
    cause: str = "unknown",
) -> FleetError:
    return FleetError(
        code,
        "The bounded Agents SDK invocation did not satisfy its trusted contract.",
        "Inspect the retained Fleet evidence; no automatic replay is authorized.",
        details={"runtime_diagnostic": {"category": category, "cause_category": cause}},
    )


def safe_error(error: Exception) -> FleetError:
    """Project outside the exception handler; never retain raw SDK error chains."""
    if isinstance(error, FleetError):
        return error
    if isinstance(error, (TimeoutError, APITimeoutError, ModelTimeoutError)):
        return boundary_error(ErrorCode.RUNTIME_TIMEOUT, category="provider_timeout")
    if isinstance(error, MaxTurnsExceeded):
        return boundary_error(ErrorCode.RUNTIME_BUDGET_EXCEEDED, category="usage_limit")
    if isinstance(error, ValidationError):
        return boundary_error(category="output_schema", cause="schema_validation")
    if isinstance(error, ModelBehaviorError):
        return boundary_error()
    if isinstance(error, UserError):
        return boundary_error(ErrorCode.PROVIDER_FAILED, category="request_construction")
    if isinstance(error, OpenAIError):
        return FleetError(
            ErrorCode.PROVIDER_FAILED,
            "The explicitly selected OpenAI request failed.",
            "Inspect request accounting and provider availability before retrying explicitly.",
            details=runtime_failure_details(error, RuntimeFailureCategory.PROVIDER_SDK),
        )
    return boundary_error(ErrorCode.PROVIDER_FAILED, category="request_construction")


def detach_error(error: FleetError) -> FleetError:
    error.__cause__ = None
    error.__context__ = None
    error.__traceback__ = None
    if hasattr(error, "__notes__"):
        del error.__notes__
    return error


def require_sdk_policy() -> None:
    """Reject unsafe logging without changing environment or logger configuration."""
    if any(
        name in os.environ
        for name in ("OPENAI_AGENTS_DONT_LOG_MODEL_DATA", "OPENAI_AGENTS_DONT_LOG_TOOL_DATA")
    ) or not (sdk_debug.DONT_LOG_MODEL_DATA and sdk_debug.DONT_LOG_TOOL_DATA):
        raise boundary_error(ErrorCode.PROVIDER_FAILED, category="request_construction")
    namespaces = ("openai.agents", "openai", "httpx", "httpcore", "httpx2", "httpcore2")
    names = set(namespaces) | {
        name
        for name in logging.Logger.manager.loggerDict
        if any(name.startswith(prefix + ".") for prefix in namespaces)
    }
    if any(logging.getLogger(name).isEnabledFor(logging.INFO) for name in names):
        raise boundary_error(ErrorCode.PROVIDER_FAILED, category="request_construction")


def initialize_no_export_tracing() -> None:
    """One process-level Fleet policy, established before SDK lazy initialization.

    Never call get_trace_provider here: that would construct the default exporter.
    A foreign provider is rejected, not silently reconfigured or shut down.
    """
    global _TRACE_PROVIDER
    # Qualified against the pinned SDK setup protocol: its public setter also
    # takes this non-reentrant lock. Compare/install and shutdown registration
    # must share that lock without calling the setter or lazy getter inside it.
    with _TRACE_LOCK, trace_setup._GLOBAL_TRACE_PROVIDER_LOCK:
        current = trace_setup.GLOBAL_TRACE_PROVIDER
        if current is not None and current is not _TRACE_PROVIDER:
            raise boundary_error(ErrorCode.PROVIDER_FAILED, category="request_construction")
        if _TRACE_PROVIDER is None:
            _TRACE_PROVIDER = DefaultTraceProvider()
            _TRACE_PROVIDER.set_disabled(True)
        if (
            _TRACE_PROVIDER._manual_disabled is not True
            or _TRACE_PROVIDER._multi_processor._processors
        ):
            raise boundary_error(ErrorCode.PROVIDER_FAILED, category="request_construction")
        trace_setup.GLOBAL_TRACE_PROVIDER = _TRACE_PROVIDER
        if not trace_setup._SHUTDOWN_HANDLER_REGISTERED:
            atexit.register(trace_setup._shutdown_global_trace_provider)
            trace_setup._SHUTDOWN_HANDLER_REGISTERED = True


def checked_json(value: object, redactor: Redactor) -> str:
    dumped = json.dumps(
        _json_projection(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    if len(dumped.encode("utf-8")) > _MAX_ENVELOPE_BYTES:
        raise boundary_error(ErrorCode.RUNTIME_BUDGET_EXCEEDED, category="usage_limit")
    if redactor.contains_secret_data(value) or redactor.contains_secret(dumped):
        raise boundary_error(ErrorCode.COMMAND_DENIED)
    return dumped


def _json_projection(value: object, depth: int = 0) -> Any:
    if depth > 80:
        raise boundary_error(ErrorCode.RUNTIME_BUDGET_EXCEEDED, category="usage_limit")
    if isinstance(value, BaseModel):
        # OpenAI response classes use deferred serializers. Their public dump
        # initializes those correctly; generic core serialization can fail first.
        return _json_projection(
            value.model_dump(mode="json", by_alias=True, warnings="error"), depth + 1
        )
    if isinstance(value, dict):
        return {key: _json_projection(child, depth + 1) for key, child in value.items()}
    if isinstance(value, list | tuple):
        return [_json_projection(child, depth + 1) for child in value]
    return to_jsonable_python(value)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON object key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    del value
    raise ValueError("Nonfinite JSON value")


@dataclass(frozen=True, slots=True)
class PendingCall:
    call: RuntimeToolCall
    arguments_json: str

    @classmethod
    def from_raw(cls, raw: object, redactor: Redactor) -> PendingCall:
        if getattr(raw, "type", None) != "function_call":
            raise boundary_error()
        call_id = getattr(raw, "call_id", None)
        name = getattr(raw, "name", None)
        arguments = getattr(raw, "arguments", None)
        if type(call_id) is not str or type(name) is not str or type(arguments) is not str:
            raise boundary_error()
        if (
            getattr(raw, "namespace", None) is not None
            or getattr(raw, "caller", None) is not None
            or getattr(raw, "async_", None) not in (None, False)
        ):
            raise boundary_error()
        checked_json(arguments, redactor)
        try:
            parsed = json.loads(
                arguments, object_pairs_hook=_unique_object, parse_constant=_reject_constant
            )
        except (ValueError, TypeError):
            parsed = None
        if type(parsed) is not dict:
            raise boundary_error(category="tool_arguments", cause="schema_validation")
        checked_json(parsed, redactor)
        return cls(RuntimeToolCall(call_id=call_id, name=name, arguments=parsed), arguments)

    def matches(self, raw: object) -> bool:
        return (
            getattr(raw, "type", None) == "function_call"
            and getattr(raw, "call_id", None) == self.call.call_id
            and getattr(raw, "name", None) == self.call.name
            and getattr(raw, "arguments", None) == self.arguments_json
            and getattr(raw, "namespace", None) is None
            and getattr(raw, "caller", None) is None
            and getattr(raw, "async_", None) in (None, False)
        )


@dataclass(frozen=True, slots=True)
class CompletedReceipt:
    call_id: str
    name: str
    arguments_json: str
    output_json: str


class PassiveResults:
    """Only bounded completed data; no catalog, callable executor, secret or grant."""

    __slots__ = ("_receipts",)

    def __init__(self) -> None:
        self._receipts: dict[str, CompletedReceipt] = {}

    def publish(self, receipts: tuple[CompletedReceipt, ...]) -> None:
        if self._receipts or len({item.call_id for item in receipts}) != len(receipts):
            raise boundary_error(ErrorCode.INTERNAL_ERROR)
        self._receipts = {item.call_id: item for item in receipts}

    @property
    def empty(self) -> bool:
        return not self._receipts

    async def invoke(self, context: ToolContext[Any], arguments: str) -> str:
        receipt = self._receipts.get(context.tool_call_id)
        if (
            receipt is None
            or context.tool_name != receipt.name
            or arguments != receipt.arguments_json
            or context.tool_arguments != receipt.arguments_json
            or context.tool_namespace is not None
            or context.tool_call is None
            or getattr(context.tool_call, "call_id", None) != receipt.call_id
            or getattr(context.tool_call, "name", None) != receipt.name
            or getattr(context.tool_call, "arguments", None) != receipt.arguments_json
        ):
            raise boundary_error(ErrorCode.INTERNAL_ERROR)
        # No await between identity check and consumption, even under SDK concurrency.
        del self._receipts[receipt.call_id]
        return receipt.output_json


class NoModelFallback(ModelProvider):
    def get_model(self, model_name: str | None) -> Model:
        del model_name
        raise boundary_error(ErrorCode.PROVIDER_UNSUPPORTED)


class PinnedResponsesModel(OpenAIResponsesModel):
    """Check the raw pinned SDK projection before it discards identity/status.

    The real superclass performs the one HTTP request. A rejected projection has
    unknown accounting; no token facts are invented from a partially accepted SDK
    response. This override is qualified only for the pinned, nonstreaming SDK.
    """

    def __init__(self, model: str, client: AsyncOpenAI) -> None:
        super().__init__(model, client)
        self._fleet_expected_model = model

    async def _fetch_response(self, *args: Any, **kwargs: Any) -> Any:
        mapped: FleetError | None = None
        response: Any = None
        try:
            response = await super()._fetch_response(*args, **kwargs)
        except ModelBehaviorError:
            # The pinned SDK rejects failed/incomplete HTTP response status in
            # this same fetch path before returning the typed response.
            mapped = boundary_error(
                ErrorCode.PROVIDER_FAILED, category="provider_sdk", cause="response_policy"
            )
        except Exception as error:
            mapped = safe_error(error)
        if mapped is not None:
            raise detach_error(mapped) from None
        if (
            getattr(response, "model", None) != self._fleet_expected_model
            or getattr(response, "status", None) != "completed"
            or getattr(response, "error", None) is not None
        ):
            raise boundary_error(
                ErrorCode.PROVIDER_FAILED, category="provider_sdk", cause="response_policy"
            )
        return response


def raw_usage_record(raw: object) -> UsageRecord:
    detail_fields = {
        "input_tokens_details": {"cached_tokens", "cache_write_tokens"},
        "output_tokens_details": {"reasoning_tokens"},
    }
    shape_valid = type(raw) is dict and set(raw) <= {
        "input_tokens",
        "output_tokens",
        "total_tokens",
        *detail_fields,
    }
    if shape_valid and isinstance(raw, dict):
        for name, fields in detail_fields.items():
            if name not in raw:
                continue
            details = raw[name]
            if (
                type(details) is not dict
                or not set(details) <= fields
                or any(
                    type(value) is not int or not 0 <= value <= 2_000_000_000
                    for value in details.values()
                )
            ):
                shape_valid = False
    values: dict[str, int | None] = {}
    for name, maximum in (
        ("input_tokens", 2_000_000_000),
        ("output_tokens", 2_000_000_000),
        ("total_tokens", 4_000_000_000),
    ):
        value = raw.get(name) if type(raw) is dict else None
        values[name] = value if type(value) is int and 0 <= value <= maximum else None
    if (
        not shape_valid
        or any(value is None for value in values.values())
        or (
            values["total_tokens"] is not None
            and values["total_tokens"]
            < (values["input_tokens"] or 0) + (values["output_tokens"] or 0)
        )
    ):
        values["total_tokens"] = None
    return UsageRecord(
        requests=1,
        input_tokens=values["input_tokens"],
        output_tokens=values["output_tokens"],
        total_tokens=values["total_tokens"],
    )


class RawUsageReceipt:
    """One request-scoped RAM receipt, before SDK scalar coercion; never raw text."""

    def __init__(self) -> None:
        self._active = False
        self._observed = False
        self._usage: UsageRecord | None = None

    @contextmanager
    def request(self) -> Iterator[None]:
        if self._active or self._observed or self._usage is not None:
            raise boundary_error(ErrorCode.INTERNAL_ERROR)
        self._active = True
        try:
            yield
        finally:
            self._active = False
            self._observed = False
            self._usage = None

    async def observe(self, response: Any) -> None:
        if not self._active or self._observed:
            raise boundary_error(ErrorCode.PROVIDER_FAILED, cause="response_policy")
        self._observed = True
        # This is a post-read accepted-body limit, not a bound on HTTPX receive
        # allocation. Incremental transport buffering is outside this slice.
        content = await response.aread()
        if len(content) > _MAX_ENVELOPE_BYTES:
            raise boundary_error(ErrorCode.RUNTIME_BUDGET_EXCEEDED, category="usage_limit")
        if not 200 <= response.status_code < 300:
            # Failed HTTP responses have no usage contract. Preserve the real
            # SDK status exception, projected safely by the fetch boundary;
            # the durable owner still records unknown request consumption.
            return
        try:
            payload = json.loads(
                content, object_pairs_hook=_unique_object, parse_constant=_reject_constant
            )
        except (ValueError, TypeError):
            payload = None
        # Keep only scalar facts. Neither provider error strings nor body bytes
        # become receipt state, logs, persisted artifacts, or SDK continuation.
        self._usage = raw_usage_record(payload.get("usage") if type(payload) is dict else None)
        if self._usage.total_tokens is None:
            # Reject before the SDK's typed parser/serializer can coerce values
            # or emit warnings containing untrusted usage strings. The outer
            # durable owner records this request conservatively as unknown.
            raise boundary_error(
                ErrorCode.PROVIDER_FAILED, category="provider_sdk", cause="response_policy"
            )

    def consume(self) -> UsageRecord:
        if not self._active or self._usage is None:
            raise boundary_error(ErrorCode.PROVIDER_FAILED, cause="response_policy")
        usage = self._usage
        self._usage = None
        return usage


class FleetSDKModel(Model):
    """Count each real SDK request before dispatch; inspect before SDK deduplication."""

    def __init__(
        self,
        wrapped: Model,
        *,
        configuration: RuntimeConfiguration,
        max_steps: int,
        tool_names: frozenset[str],
        terminal_names: frozenset[str],
        redactor: Redactor,
        gate: SingleSendGate,
        raw_usage: RawUsageReceipt,
        accounting: RuntimeAccounting | None,
    ) -> None:
        self.wrapped = wrapped
        self.configuration = configuration
        self.request_limit = min(configuration.max_requests, max_steps)
        self.tool_names = tool_names
        self.terminal_names = terminal_names
        self.redactor = redactor
        self.gate = gate
        self.raw_usage = raw_usage
        self.accounting = accounting
        self.requests = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.total_tokens = 0
        self.pending: tuple[PendingCall, ...] = ()
        self.seen_ids: set[str] = set()

    def _inspect_response(self, response: ModelResponse) -> None:
        checked_json(response.output, self.redactor)
        calls: list[PendingCall] = []
        for raw in response.output:
            kind = getattr(raw, "type", None)
            if kind == "function_call":
                call = PendingCall.from_raw(raw, self.redactor)
                if call.call.name not in self.tool_names or call.call.call_id in self.seen_ids:
                    raise boundary_error()
                self.seen_ids.add(call.call.call_id)
                calls.append(call)
            elif kind == "message":
                content = getattr(raw, "content", None)
                if type(content) is not list or any(
                    getattr(part, "type", None) != "output_text" for part in content
                ):
                    raise boundary_error()
            elif kind != "reasoning":
                raise boundary_error()
        if not calls:
            raise boundary_error()
        terminal = any(item.call.name in self.terminal_names for item in calls)
        if terminal and len(calls) != 1:
            raise boundary_error()
        if not terminal and len(calls) > self.configuration.max_tool_calls:
            raise boundary_error(ErrorCode.RUNTIME_BUDGET_EXCEEDED, category="usage_limit")
        self.pending = tuple(calls)

    async def get_response(
        self,
        system_instructions: str | None,
        input: str | list[TResponseInputItem],
        model_settings: ModelSettings,
        tools: list[Tool],
        output_schema: AgentOutputSchemaBase | None,
        handoffs: list[Handoff],
        tracing: ModelTracing,
        *,
        previous_response_id: str | None,
        conversation_id: str | None,
        prompt: ResponsePromptParam | None,
    ) -> ModelResponse:
        mapped: FleetError | None = None
        try:
            return await self._request(
                system_instructions,
                input,
                model_settings,
                tools,
                output_schema,
                handoffs,
                tracing,
                previous_response_id,
                conversation_id,
                prompt,
            )
        except Exception as error:
            mapped = safe_error(error)
        assert mapped is not None
        raise detach_error(mapped) from None

    async def _request(
        self,
        system_instructions: str | None,
        input: str | list[TResponseInputItem],
        model_settings: ModelSettings,
        tools: list[Tool],
        output_schema: AgentOutputSchemaBase | None,
        handoffs: list[Handoff],
        tracing: ModelTracing,
        previous_response_id: str | None,
        conversation_id: str | None,
        prompt: ResponsePromptParam | None,
    ) -> ModelResponse:
        require_sdk_policy()
        initialize_no_export_tracing()
        if (
            self.pending
            or handoffs
            or output_schema is not None
            or previous_response_id is not None
            or conversation_id is not None
            or prompt is not None
            or tracing is not ModelTracing.DISABLED
            or any(
                not isinstance(tool, FunctionTool)
                or tool.needs_approval is not True
                or tool.strict_json_schema is not (tool.name not in self.terminal_names)
                for tool in tools
            )
            or frozenset(tool.name for tool in tools) != self.tool_names
        ):
            raise boundary_error()
        checked_json(
            {
                "instructions": system_instructions,
                "input": input,
                "settings": model_settings,
                "tools": [
                    {
                        "name": tool.name,
                        "schema": tool.params_json_schema,
                        "description": tool.description,
                    }
                    for tool in cast(list[FunctionTool], tools)
                ],
            },
            self.redactor,
        )
        if (
            self.requests >= self.request_limit
            or self.total_tokens >= self.configuration.max_total_tokens
        ):
            raise boundary_error(ErrorCode.RUNTIME_BUDGET_EXCEEDED, category="usage_limit")
        allowance = self.configuration.max_total_tokens - self.total_tokens
        self.requests += 1
        reservation = (
            self.accounting.reserve_request(self.requests, requested_tokens=allowance)
            if self.accounting is not None
            else None
        )
        if reservation is not None:
            allowance = min(allowance, reservation.token_allowance)
        response: ModelResponse | None = None
        usage: UsageRecord | None = None
        request_error: BaseException | None = None
        try:
            remaining = min(
                float(self.configuration.timeout_seconds),
                self.accounting.remaining_active_seconds()
                if self.accounting
                else float(self.configuration.timeout_seconds),
            )
            with self.gate.request(), self.raw_usage.request():
                async with asyncio.timeout(remaining):
                    response = await self.wrapped.get_response(
                        system_instructions,
                        input,
                        replace(model_settings, max_tokens=allowance, timeout=remaining),
                        tools,
                        output_schema,
                        handoffs,
                        ModelTracing.DISABLED,
                        previous_response_id=None,
                        conversation_id=None,
                        prompt=None,
                    )
                    usage = self.raw_usage.consume()
        except BaseException as error:
            request_error = error
        if request_error is not None:
            if reservation is not None and self.accounting is not None:
                self.accounting.record_unknown(reservation)
            if isinstance(request_error, asyncio.CancelledError):
                raise asyncio.CancelledError() from None
            if isinstance(request_error, Exception):
                raise detach_error(safe_error(request_error)) from None
            raise request_error
        assert response is not None
        assert usage is not None
        if reservation is not None and self.accounting is not None:
            self.accounting.record_response(reservation, usage)
        if usage.total_tokens is None:
            raise boundary_error(
                ErrorCode.PROVIDER_FAILED, category="provider_sdk", cause="response_policy"
            )
        self.input_tokens += usage.input_tokens or 0
        self.output_tokens += usage.output_tokens or 0
        self.total_tokens += usage.total_tokens
        if self.total_tokens > self.configuration.max_total_tokens:
            raise boundary_error(ErrorCode.RUNTIME_BUDGET_EXCEEDED, category="usage_limit")
        self._inspect_response(response)
        return response

    def stream_response(
        self,
        system_instructions: str | None,
        input: str | list[TResponseInputItem],
        model_settings: ModelSettings,
        tools: list[Tool],
        output_schema: AgentOutputSchemaBase | None,
        handoffs: list[Handoff],
        tracing: ModelTracing,
        *,
        previous_response_id: str | None,
        conversation_id: str | None,
        prompt: ResponsePromptParam | None,
    ) -> AsyncIterator[TResponseStreamEvent]:
        raise boundary_error(ErrorCode.RUNTIME_CAPABILITY_MISSING)
