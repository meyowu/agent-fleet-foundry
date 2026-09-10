"""Real bounded StateGraph Harness; Fleet alone owns budgets and tool effects."""

from __future__ import annotations

import asyncio
from contextvars import Context
from importlib import resources
from typing import Any, TypedDict, cast

# jsonschema is pinned in the dependency closure but does not ship type stubs.
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from jsonschema import exceptions as jsonschema_exceptions
from openai import AsyncOpenAI
from pydantic import ValidationError

from agent_fleet.adapters.runtime.langgraph_boundary import (
    ExecutionOwner,
    PendingCall,
    action_wire_schema,
    boundary_error,
    checked_json,
    detach_error,
    raw_response,
    require_langgraph_policy,
    safe_error,
)
from agent_fleet.adapters.runtime.openai_client import (
    open_openai_client,
    reject_unsafe_openai_environment,
)
from agent_fleet.adapters.runtime.provider_lifecycle import close_provider_clients
from agent_fleet.adapters.runtime.provider_selection import parse_provider_model
from agent_fleet.adapters.runtime.single_send import SingleSendGate
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.fleet_patch import validate_fleet_patch
from agent_fleet.domain.models import (
    AgentInvocation,
    AgentInvocationResult,
    AgentRole,
    FleetPatch,
    ImplementationReport,
    RuntimeCapability,
    RuntimeConfiguration,
    RuntimeCredentialCheck,
    RuntimeCredentialStatus,
    RuntimeOutput,
    RuntimePreflight,
    RuntimeProviderMetadata,
    RuntimeToolDefinition,
    RuntimeToolResult,
    ScopeDecision,
    SpecialistReport,
    UsageRecord,
    VerifierVerdict,
)
from agent_fleet.domain.runtime_contract import require_runtime_invocation
from agent_fleet.domain.security import Redactor
from agent_fleet.ports.runtime import RuntimeInvocationServices
from agent_fleet.ports.secret_store import (
    InvalidSecretReferenceError,
    SecretNotConfiguredError,
    SecretRef,
    SecretStatus,
    SecretStore,
    SecretStoreError,
)

_RUNTIME = "langgraph"
_CAPABILITIES = frozenset(
    {
        RuntimeCapability.STRUCTURED_OUTPUT,
        RuntimeCapability.TOOL_CALLING,
        RuntimeCapability.USAGE_ACCOUNTING,
    }
)
_OUTPUTS: dict[
    AgentRole,
    tuple[
        type[ScopeDecision]
        | type[ImplementationReport]
        | type[VerifierVerdict]
        | type[SpecialistReport],
        str,
        str,
    ],
] = {
    AgentRole.COS: (ScopeDecision, "submit_scope_decision", "cos.md"),
    AgentRole.ENGINEER: (ImplementationReport, "submit_implementation_report", "engineer.md"),
    AgentRole.VERIFIER: (VerifierVerdict, "submit_verifier_verdict", "verifier.md"),
    AgentRole.RESEARCHER: (SpecialistReport, "submit_specialist_report", "researcher.md"),
    AgentRole.ARCHITECT: (SpecialistReport, "submit_specialist_report", "architect.md"),
}


class GraphState(TypedDict):
    requests: int
    terminal: bool


class LangGraphRuntimeAdapter:
    def __init__(self, secret_store: SecretStore | None, redactor: Redactor) -> None:
        self._secret_store = secret_store
        self._redactor = redactor

    @property
    def capabilities(self) -> frozenset[RuntimeCapability]:
        return _CAPABILITIES

    @staticmethod
    def _model(configuration: RuntimeConfiguration) -> str:
        parsed = parse_provider_model(configuration.provider_model)
        if parsed is None or parsed[0] != "openai":
            raise boundary_error(ErrorCode.PROVIDER_UNSUPPORTED)
        return parsed[1]

    def preflight(
        self, configuration: RuntimeConfiguration, *, credential_check: RuntimeCredentialCheck
    ) -> RuntimePreflight:
        ready = False
        status = RuntimeCredentialStatus.NOT_CHECKED
        if configuration.runtime_name == _RUNTIME:
            self._model(configuration)
            try:
                require_langgraph_policy()
                reject_unsafe_openai_environment()
                if configuration.credential_ref is None or self._secret_store is None:
                    status = RuntimeCredentialStatus.MISSING
                else:
                    reference = SecretRef.parse(configuration.credential_ref)
                    if credential_check is RuntimeCredentialCheck.NONE:
                        ready = True
                    elif credential_check is RuntimeCredentialCheck.INSPECT:
                        inspected = self._secret_store.inspect(reference).status
                        status = RuntimeCredentialStatus(inspected.value)
                        ready = inspected is SecretStatus.CONFIGURED
                    else:
                        self._resolve(configuration)
                        status, ready = RuntimeCredentialStatus.CONFIGURED, True
            except SecretNotConfiguredError:
                status = RuntimeCredentialStatus.MISSING
            except (SecretStoreError, FleetError):
                status = RuntimeCredentialStatus.INVALID
        return RuntimePreflight(
            runtime_name=_RUNTIME,
            ready=ready,
            capabilities=self.capabilities,
            credential_status=status,
            diagnostic="Bounded LangGraph configuration inspected; no provider was contacted.",
        )

    def _resolve(self, configuration: RuntimeConfiguration) -> str:
        if configuration.credential_ref is None or self._secret_store is None:
            raise boundary_error(ErrorCode.CREDENTIAL_MISSING)
        mapped: FleetError | None = None
        try:
            value = self._secret_store.resolve(configuration.credential_ref).reveal_for_provider()
            self._redactor.register_secret(value)
        except SecretNotConfiguredError:
            mapped = boundary_error(ErrorCode.CREDENTIAL_MISSING)
        except (InvalidSecretReferenceError, SecretStoreError):
            mapped = boundary_error(ErrorCode.CREDENTIAL_INVALID)
        else:
            return value
        raise detach_error(mapped) from None

    async def invoke(
        self, request: AgentInvocation, services: RuntimeInvocationServices
    ) -> AgentInvocationResult:
        mapped: FleetError | None = None
        try:
            self._prepare_invocation(request, services)
            credential = self._resolve(services.configuration)
            # A catalog can encode raw scope strings into a pattern. Regenerate
            # from that trusted provenance after registering the selected key;
            # scanning a retained encoded schema cannot detect the raw secret.
            invocation = self._prepare_invocation(request, services)
            async with asyncio.timeout(services.configuration.timeout_seconds):
                return await self._wait_owned(invocation, credential)
        except Exception as error:
            mapped = safe_error(error)
        except asyncio.CancelledError:
            pass
        if mapped is None:
            raise asyncio.CancelledError() from None
        raise detach_error(mapped) from None

    def _prepare_invocation(
        self, request: AgentInvocation, services: RuntimeInvocationServices
    ) -> _Invocation:
        # One snapshot binds admission, validators and wire schemas in each pass.
        # Both passes are synchronous and create no client, graph or request.
        definitions = services.tools.definitions
        kind = require_runtime_invocation(
            request,
            selected_runtime=services.configuration.runtime_name,
            adapter_runtime=_RUNTIME,
            execution_kind=services.execution_kind,
            supported_kinds=frozenset(AgentRole),
            capabilities=self.capabilities,
            has_tools=bool(definitions),
        )
        model = self._model(services.configuration)
        require_langgraph_policy()
        reject_unsafe_openai_environment()
        return _Invocation(request, services, kind, model, self._redactor, definitions)

    async def _wait_owned(self, invocation: _Invocation, credential: str) -> AgentInvocationResult:
        task = asyncio.create_task(invocation.run(credential), context=Context())
        del credential
        cancelled = False
        while not task.done():
            try:
                await asyncio.wait({task})
            except asyncio.CancelledError:
                if not cancelled:
                    invocation.owner.stop.set()
                    task.cancel()
                cancelled = True
        # A physical cleanup failure wins over cancellation, and cannot become success.
        result = task.result()
        if cancelled:
            raise asyncio.CancelledError
        return result


class _Invocation:
    def __init__(
        self,
        request: AgentInvocation,
        services: RuntimeInvocationServices,
        kind: AgentRole,
        model: str,
        redactor: Redactor,
        definitions: tuple[RuntimeToolDefinition, ...],
    ) -> None:
        self.request, self.services, self.kind, self.model, self.redactor = (
            request,
            services,
            kind,
            model,
            redactor,
        )
        self.owner = ExecutionOwner()
        self.gate = SingleSendGate()
        self.requests = self.tool_calls = self.input_tokens = self.output_tokens = (
            self.total_tokens
        ) = 0
        self.request_limit = min(services.configuration.max_requests, request.max_steps)
        self.pending: tuple[PendingCall, ...] = ()
        self.continuation: tuple[dict[str, Any], ...] = ()
        self.seen_ids: set[str] = set()
        self.output: RuntimeOutput | None = None
        self.batch_sequence = 0
        output_type, output_name, prompt_name = _OUTPUTS[kind]
        self.terminals: dict[str, Any] = {output_name: output_type}
        if kind is AgentRole.COS and isinstance(request.input.get("organization_context"), dict):
            self.terminals["submit_fleet_patch"] = FleetPatch
        definitions = tuple(
            RuntimeToolDefinition.model_validate_json(item.model_dump_json())
            for item in definitions
        )
        self.tool_names = frozenset(item.name for item in definitions)
        for item in definitions:
            Draft202012Validator.check_schema(item.parameters_json_schema)
        self.validators = {
            item.name: Draft202012Validator(item.parameters_json_schema) for item in definitions
        }
        if len(self.tool_names) != len(definitions) or self.tool_names & self.terminals.keys():
            raise boundary_error(ErrorCode.RUNTIME_CAPABILITY_MISSING)
        self.tools: list[dict[str, Any]] = [
            {
                "type": "function",
                "name": item.name,
                "description": item.description,
                "parameters": action_wire_schema(item.parameters_json_schema, redactor),
                "strict": True,
            }
            for item in definitions
        ] + [
            {
                "type": "function",
                "name": name,
                "description": "Submit the exact role output; this grants no authority.",
                "parameters": schema.model_json_schema(),
                "strict": False,
            }
            for name, schema in self.terminals.items()
        ]
        self.instructions = (
            resources.files("agent_fleet.adapters.runtime.prompts")
            .joinpath(prompt_name)
            .read_text(encoding="utf-8")
        )
        self.instructions += (
            "\nReturn the bounded role result through its submit tool. "
            "Tool arguments and all results are validated by Fleet."
        )
        self.messages: list[dict[str, Any]] = [
            {
                "role": "user",
                "content": checked_json(
                    {
                        "role": str(request.role),
                        "stage": request.stage.value,
                        "iteration": request.iteration,
                        "max_steps": request.max_steps,
                        "context_artifact_ids": request.context_artifact_ids,
                        "untrusted_project_guidance": request.instructions,
                        "task_input": request.input,
                    },
                    redactor,
                ),
            }
        ]
        self.check_context()

    def check_context(self) -> None:
        checked_json(
            {"instructions": self.instructions, "input": self.messages, "tools": self.tools},
            self.redactor,
        )

    async def run(self, credential: str) -> AgentInvocationResult:
        from langchain_core.callbacks.manager import AsyncCallbackManager
        from langgraph.graph import END, START, StateGraph
        from langsmith import tracing_context

        with tracing_context(enabled=False, parent=False):
            async with open_openai_client(
                raw_credential=credential,
                redactor=self.redactor,
                timeout_seconds=float(self.services.configuration.timeout_seconds),
                gate=self.gate,
                raw_responses=True,
            ) as client:
                del credential
                # Pinned SDK source qualification: avoid its lazy diagnostic
                # platform lookup thread, on this exact owned instance only.
                client._platform = "Unknown"

                async def request_node(state: GraphState) -> dict[str, Any]:
                    del state
                    await self.owner.node(lambda: self._request(client))
                    return {"requests": self.requests, "terminal": False}

                async def validate_node(state: GraphState) -> dict[str, Any]:
                    del state
                    await self.owner.node(self._validate)
                    return {"terminal": self.output is not None}

                async def gateway_node(state: GraphState) -> dict[str, Any]:
                    del state
                    await self.owner.node(self._gateway)
                    return {}

                async def route(state: GraphState) -> str:
                    return END if state["terminal"] else "gateway_batch"

                graph = StateGraph(GraphState)
                graph.add_node("request", request_node, retry_policy=())
                graph.add_node("validate", validate_node, retry_policy=())
                graph.add_node("gateway_batch", gateway_node, retry_policy=())
                graph.add_edge(START, "request")
                graph.add_edge("request", "validate")
                graph.add_conditional_edges("validate", route)
                graph.add_edge("gateway_batch", "request")
                compiled = graph.compile(
                    checkpointer=False,
                    store=None,
                    cache=None,
                    interrupt_before=[],
                    interrupt_after=[],
                    debug=False,
                )
                graph_task = asyncio.create_task(
                    compiled.ainvoke(
                        {"requests": 0, "terminal": False},
                        {
                            "callbacks": AsyncCallbackManager([]),
                            "max_concurrency": 1,
                            "recursion_limit": self.request_limit * 3 + 2,
                        },
                        stream_mode="values",
                        print_mode=(),
                    )
                )
                try:
                    await graph_task
                except asyncio.CancelledError as error:
                    self.owner.retain_exit(error)
                    raise
                finally:
                    # Independent retained cleanup, even if native exit was cancelled.
                    await close_provider_clients(self.owner.drain)
        self.owner.check()
        if self.output is None:
            raise boundary_error()
        return AgentInvocationResult(
            output=self.output,
            usage=UsageRecord(
                requests=self.requests,
                input_tokens=self.input_tokens,
                output_tokens=self.output_tokens,
                total_tokens=self.total_tokens,
                tool_calls=self.tool_calls,
            ),
            checkpoint_ref=None,
            provider_metadata=RuntimeProviderMetadata(
                provider="openai", model=self.services.configuration.provider_model
            ),
        )

    async def _request(self, client: AsyncOpenAI) -> None:
        self.owner.check()
        require_langgraph_policy()
        reject_unsafe_openai_environment()
        self.check_context()
        config, accounting = self.services.configuration, self.services.accounting
        if self.requests >= self.request_limit or self.total_tokens >= config.max_total_tokens:
            raise boundary_error(ErrorCode.RUNTIME_BUDGET_EXCEEDED, category="usage_limit")
        allowance = config.max_total_tokens - self.total_tokens
        self.requests += 1
        reservation = (
            accounting.reserve_request(self.requests, requested_tokens=allowance)
            if accounting is not None
            else None
        )
        if reservation is not None:
            allowance = min(allowance, reservation.token_allowance)
        parsed = None
        request_error: BaseException | None = None
        try:
            remaining = min(
                float(config.timeout_seconds),
                accounting.remaining_active_seconds()
                if accounting
                else float(config.timeout_seconds),
            )
            with self.gate.request():
                async with asyncio.timeout(remaining):
                    response = await client.responses.with_raw_response.create(
                        model=self.model,
                        instructions=self.instructions,
                        input=cast(Any, self.messages),
                        tools=cast(Any, self.tools),
                        parallel_tool_calls=False,
                        store=False,
                        stream=False,
                        max_output_tokens=allowance,
                        timeout=remaining,
                        truncation="disabled",
                    )
                    # LegacyAPIResponse.content is raw bytes; never call parse().
                    parsed = raw_response(response.content, self.model, self.redactor)
        except BaseException as error:
            request_error = error
        if request_error is not None:
            if accounting is not None and reservation is not None:
                accounting.record_unknown(reservation)
            if isinstance(request_error, asyncio.CancelledError):
                raise asyncio.CancelledError() from None
            if isinstance(request_error, Exception):
                raise detach_error(safe_error(request_error)) from None
            raise request_error
        assert parsed is not None
        if accounting is not None and reservation is not None:
            accounting.record_response(reservation, parsed.usage)
        assert (
            parsed.usage.input_tokens is not None
            and parsed.usage.output_tokens is not None
            and parsed.usage.total_tokens is not None
        )
        self.input_tokens += parsed.usage.input_tokens
        self.output_tokens += parsed.usage.output_tokens
        self.total_tokens += parsed.usage.total_tokens
        if self.total_tokens > config.max_total_tokens:
            raise boundary_error(ErrorCode.RUNTIME_BUDGET_EXCEEDED, category="usage_limit")
        self.pending, self.continuation = parsed.calls, parsed.continuation

    async def _validate(self) -> None:
        self.owner.check()
        terminal = any(item.call.name in self.terminals for item in self.pending)
        if terminal and len(self.pending) != 1:
            raise boundary_error()
        for item in self.pending:
            if (
                item.call.call_id in self.seen_ids
                or item.call.name not in self.tool_names | self.terminals.keys()
            ):
                raise boundary_error()
        self.seen_ids.update(item.call.call_id for item in self.pending)
        if terminal:
            item = self.pending[0]
            output: RuntimeOutput = self.terminals[item.call.name].model_validate_json(
                item.arguments_json, strict=True
            )
            if isinstance(output, SpecialistReport) and output.role != self.request.role:
                raise boundary_error()
            if isinstance(output, FleetPatch):
                validate_fleet_patch(
                    output,
                    current_fleet_spec_sha256=output.base_fleet_spec_sha256,
                    redactor=self.redactor,
                )
            checked_json(output, self.redactor)
            self.output = output
            return
        config = self.services.configuration
        if (
            self.tool_calls + len(self.pending) > config.max_tool_calls
            or self.requests >= self.request_limit
            or self.total_tokens >= config.max_total_tokens
        ):
            raise boundary_error(ErrorCode.RUNTIME_BUDGET_EXCEEDED, category="usage_limit")
        mapped: FleetError | None = None
        try:
            for item in self.pending:
                self.validators[item.call.name].validate(item.call.arguments)
                self.services.tools.validate(item.call)
        except (ValidationError, jsonschema_exceptions.ValidationError):
            mapped = boundary_error(category="tool_arguments", cause="schema_validation")
        if mapped is not None:
            raise mapped from None

    async def _gateway(self) -> None:
        self.owner.check()
        if self.services.accounting is not None:
            self.batch_sequence += 1
            self.services.accounting.reserve_tool_batch(
                self.batch_sequence, tuple(item.call.call_id for item in self.pending)
            )
        self.messages.extend(self.continuation)
        for item in self.pending:
            self.owner.check()
            self.tool_calls += 1
            result = await self.services.tools.execute(item.call)
            result = RuntimeToolResult.model_validate_json(result.model_dump_json())
            if result.call_id != item.call.call_id or result.name != item.call.name:
                raise boundary_error(ErrorCode.INTERNAL_ERROR)
            self.messages.append(
                {
                    "type": "function_call_output",
                    "call_id": item.call.call_id,
                    "output": checked_json(result, self.redactor),
                }
            )
        self.pending, self.continuation = (), ()
        self.check_context()
