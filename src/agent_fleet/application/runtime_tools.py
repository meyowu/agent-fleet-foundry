"""Role-bound runtime tools that always cross the project ToolGateway."""

from __future__ import annotations

from pydantic import Field

from agent_fleet.application.gateway import ToolGateway
from agent_fleet.domain.errors import (
    ApprovalDeniedError,
    ApprovalRequiredError,
    ErrorCode,
    FleetError,
)
from agent_fleet.domain.models import (
    AgentInstance,
    AgentRole,
    CanonicalResource,
    FakeScenario,
    Run,
    RuntimeToolCall,
    RuntimeToolDefinition,
    RuntimeToolExecutionRecord,
    RuntimeToolOutcome,
    RuntimeToolResult,
    SandboxHandle,
    ScriptedAction,
    StrictModel,
    TaskSpec,
    Workspace,
)
from agent_fleet.domain.security import Redactor, canonical_json_hash
from agent_fleet.ports.runtime import RuntimeToolCatalog


class _WriteFileArguments(StrictModel):
    path: str = Field(min_length=1, max_length=4096)
    content: str = Field(max_length=200_000)
    reason: str = Field(min_length=1, max_length=4096)


class _VerificationArguments(StrictModel):
    reason: str = Field(min_length=1, max_length=4096)


class _ApprovalProbeArguments(StrictModel):
    record: str = Field(pattern=r"^approved-once$")
    reason: str = Field(min_length=1, max_length=4096)


_WRITE_FILE = RuntimeToolDefinition(
    name="workspace_write_file",
    description=(
        "Replace one TaskSpec-authorized repository-relative candidate file with the supplied "
        "UTF-8 content. The control plane validates scope and permission."
    ),
    parameters_json_schema=_WriteFileArguments.model_json_schema(),
    side_effect=True,
)
_RUN_VERIFICATION = RuntimeToolDefinition(
    name="run_verification",
    description=(
        "Request the control-plane-declared verification command. In Phase 2 the fake sandbox "
        "records simulated evidence and does not execute project code."
    ),
    parameters_json_schema=_VerificationArguments.model_json_schema(),
    side_effect=False,
)
_APPROVAL_PROBE = RuntimeToolDefinition(
    name="record_approval_probe",
    description="Exercise the deterministic one-use approval fixture for offline tests.",
    parameters_json_schema=_ApprovalProbeArguments.model_json_schema(),
    side_effect=True,
)


class GatewayRuntimeToolCatalog(RuntimeToolCatalog):
    """Translate narrow model calls into identity-bound `ScriptedAction` values.

    The catalog deliberately has no generic action/resource parameters. Run, task,
    agent, workflow, stage, workspace, and sandbox identity are constructor-bound by
    the application and never accepted from model arguments.
    """

    def __init__(
        self,
        *,
        gateway: ToolGateway,
        redactor: Redactor,
        run: Run,
        task: TaskSpec,
        agent: AgentInstance,
        workspace: Workspace,
        sandbox_handle: SandboxHandle,
        max_calls: int,
    ) -> None:
        if max_calls < 0:
            raise ValueError("runtime tool budget cannot be negative")
        self._gateway = gateway
        self._redactor = redactor
        self._run = run
        self._task = task
        self._agent = agent
        self._workspace = workspace
        self._sandbox_handle = sandbox_handle
        self._max_calls = max_calls
        self._records: list[RuntimeToolExecutionRecord] = []
        self._completed: dict[str, tuple[RuntimeToolCall, RuntimeToolResult]] = {}

    @property
    def definitions(self) -> tuple[RuntimeToolDefinition, ...]:
        if self._agent.role == AgentRole.ENGINEER:
            definitions = [_WRITE_FILE, _RUN_VERIFICATION]
            if self._run.fake_scenario is FakeScenario.APPROVAL:
                definitions.append(_APPROVAL_PROBE)
            return tuple(definitions)
        if self._agent.role == AgentRole.VERIFIER:
            return (_RUN_VERIFICATION,)
        return ()

    @property
    def records(self) -> tuple[RuntimeToolExecutionRecord, ...]:
        return tuple(self._records)

    def validate(self, call: RuntimeToolCall) -> None:
        previous = self._completed.get(call.call_id)
        if previous is not None:
            previous_call, _ = previous
            if previous_call != call:
                raise FleetError(
                    ErrorCode.COMMAND_DENIED,
                    "A runtime tool call ID was reused with different arguments.",
                    "Start a fresh invocation; tool call identities are immutable.",
                )
            return
        if len(self._records) >= self._max_calls:
            raise FleetError(
                ErrorCode.RUNTIME_BUDGET_EXCEEDED,
                "The runtime tool-call budget was exhausted.",
                "Reduce the task scope or start a new run with a reviewed bounded budget.",
                details={"max_tool_calls": self._max_calls},
            )
        if self._redactor.contains_secret_data(call.model_dump(mode="json")):
            raise FleetError(
                ErrorCode.COMMAND_DENIED,
                "A registered secret was detected in a runtime tool call.",
                "Remove secret material; Fleet did not persist or execute the call.",
            )
        self._translate(call)

    async def execute(self, call: RuntimeToolCall) -> RuntimeToolResult:
        previous = self._completed.get(call.call_id)
        if previous is not None:
            previous_call, previous_result = previous
            if previous_call != call:
                raise FleetError(
                    ErrorCode.COMMAND_DENIED,
                    "A runtime tool call ID was reused with different arguments.",
                    "Start a fresh invocation; tool call identities are immutable.",
                )
            return previous_result
        self.validate(call)
        scripted, side_effect = self._translate(call)
        try:
            gateway_result = await self._gateway.execute(
                run=self._run,
                task=self._task,
                agent=self._agent,
                workspace=self._workspace,
                sandbox_handle=self._sandbox_handle,
                scripted=scripted,
            )
        except ApprovalRequiredError:
            self._record(call, RuntimeToolOutcome.APPROVAL_REQUIRED, side_effect, False, ())
            raise
        except ApprovalDeniedError:
            self._record(call, RuntimeToolOutcome.DENIED, side_effect, False, ())
            raise
        except FleetError:
            self._record(call, RuntimeToolOutcome.DENIED, side_effect, False, ())
            raise

        artifact_ids = tuple(
            value
            for key, value in sorted(gateway_result.items())
            if key.endswith("_artifact_id") and isinstance(value, str) and value.startswith("art_")
        )
        result = RuntimeToolResult(
            call_id=call.call_id,
            name=call.name,
            outcome=RuntimeToolOutcome.SUCCEEDED,
            content=gateway_result,
            artifact_ids=artifact_ids,
        )
        self._record(
            call,
            RuntimeToolOutcome.SUCCEEDED,
            side_effect,
            side_effect,
            artifact_ids,
        )
        self._completed[call.call_id] = (call, result)
        return result

    def _translate(self, call: RuntimeToolCall) -> tuple[ScriptedAction, bool]:
        identity_prefix = (
            f"{self._run.run_id}:{self._agent.role}:{self._run.stage}:"
            f"{self._agent.iteration}:{call.name}"
        )
        if call.name == _WRITE_FILE.name:
            write_arguments = _WriteFileArguments.model_validate(call.arguments)
            scripted = ScriptedAction(
                action="workspace.write_file",
                resource=CanonicalResource(kind="workspace_path", identifier=write_arguments.path),
                parameters={"content": write_arguments.content},
                reason=write_arguments.reason,
                side_effect=True,
                idempotency_key=(f"{identity_prefix}:{canonical_json_hash(call.arguments)[:24]}"),
            )
            return scripted, True
        if call.name == _RUN_VERIFICATION.name:
            verification_arguments = _VerificationArguments.model_validate(call.arguments)
            scripted = ScriptedAction(
                action="command.run",
                resource=CanonicalResource(
                    kind="fake_command", identifier="verification://offline-canary"
                ),
                parameters={
                    "executable": "python",
                    "argv": ["-m", "pytest", "-q"],
                    "cwd": ".",
                },
                reason=verification_arguments.reason,
                side_effect=False,
                idempotency_key=f"{identity_prefix}:declared-offline-canary",
            )
            return scripted, False
        if call.name == _APPROVAL_PROBE.name:
            approval_arguments = _ApprovalProbeArguments.model_validate(call.arguments)
            scripted = ScriptedAction(
                action="fixture.record_side_effect",
                resource=CanonicalResource(
                    kind="fake_side_effect", identifier="fixture://approval-proof"
                ),
                parameters={"record": approval_arguments.record},
                reason=approval_arguments.reason,
                side_effect=True,
                idempotency_key=f"{self._run.run_id}:approval-proof",
            )
            return scripted, True
        raise FleetError(
            ErrorCode.COMMAND_DENIED,
            f"Runtime tool {call.name!r} is not recognized.",
            "Use only the exact tool definitions supplied by the control plane.",
        )

    def _record(
        self,
        call: RuntimeToolCall,
        outcome: RuntimeToolOutcome,
        side_effect: bool,
        side_effect_committed: bool,
        artifact_ids: tuple[str, ...],
    ) -> None:
        self._records.append(
            RuntimeToolExecutionRecord(
                call_id=call.call_id,
                name=call.name,
                outcome=outcome,
                side_effect=side_effect,
                side_effect_committed=side_effect_committed,
                artifact_ids=artifact_ids,
            )
        )
