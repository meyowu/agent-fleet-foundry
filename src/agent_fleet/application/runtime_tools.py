"""Role-bound runtime tools that always cross the project ToolGateway."""

from __future__ import annotations

from pathlib import PurePosixPath

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
    CommandSpec,
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


class _ReasonArguments(StrictModel):
    reason: str = Field(min_length=1, max_length=4096)


class _PathArguments(StrictModel):
    path: str = Field(min_length=1, max_length=4096)
    reason: str = Field(min_length=1, max_length=4096)


class _SearchArguments(StrictModel):
    query: str = Field(min_length=1, max_length=4096)
    reason: str = Field(min_length=1, max_length=4096)


class _EditArguments(StrictModel):
    path: str = Field(min_length=1, max_length=4096)
    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    old: str = Field(min_length=1, max_length=200_000)
    new: str = Field(max_length=200_000)
    expected_matches: int = Field(ge=1, le=1000)
    reason: str = Field(min_length=1, max_length=4096)


class _DeleteArguments(StrictModel):
    path: str = Field(min_length=1, max_length=4096)
    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason: str = Field(min_length=1, max_length=4096)


class _VerificationArguments(StrictModel):
    command_id: str = Field(
        min_length=1,
        max_length=100,
        description="The exact command_id of one verification command admitted by the TaskSpec.",
    )
    reason: str = Field(
        min_length=1,
        max_length=4096,
        description="Why this admitted command is needed; this does not replace command_id.",
    )


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
_LIST_FILES = RuntimeToolDefinition(
    name="repo_list_files",
    description=(
        "List bounded regular files visible inside the TaskSpec scope. Protected paths and "
        "symlink targets are never returned."
    ),
    parameters_json_schema=_ReasonArguments.model_json_schema(),
    side_effect=False,
)
_READ_FILE = RuntimeToolDefinition(
    name="repo_read_file",
    description=(
        "Read one bounded UTF-8 regular file by repository-relative path without following "
        "symlinks. TaskSpec.allowed_paths and forbidden_paths constrain reads too. Never pass "
        "a directory, .fleet, .git, or another protected or out-of-scope path. Use "
        "workspace_get_diff for changed-path inspection."
    ),
    parameters_json_schema=_PathArguments.model_json_schema(),
    side_effect=False,
)
_SEARCH_TEXT = RuntimeToolDefinition(
    name="repo_search_text",
    description=(
        "Search for a literal bounded string only within regular files visible to the TaskSpec."
    ),
    parameters_json_schema=_SearchArguments.model_json_schema(),
    side_effect=False,
)
_APPLY_EDIT = RuntimeToolDefinition(
    name="workspace_apply_edit",
    description=(
        "Apply an exact text replacement to one TaskSpec-authorized candidate file only when "
        "its content hash and match count still agree."
    ),
    parameters_json_schema=_EditArguments.model_json_schema(),
    side_effect=True,
)
_DELETE_FILE = RuntimeToolDefinition(
    name="workspace_delete_file",
    description=(
        "Delete one TaskSpec-authorized regular candidate file only when its content hash still "
        "agrees."
    ),
    parameters_json_schema=_DeleteArguments.model_json_schema(),
    side_effect=True,
)
_GET_DIFF = RuntimeToolDefinition(
    name="workspace_get_diff",
    description=(
        "Return the canonical candidate patch and changed-path summary for scope inspection. "
        "Use this or the supplied patch instead of reading directories or protected paths. "
        "Patch inspection alone is not independently executed behavioral proof."
    ),
    parameters_json_schema=_ReasonArguments.model_json_schema(),
    side_effect=False,
)
_APPROVAL_PROBE = RuntimeToolDefinition(
    name="record_approval_probe",
    description="Exercise the deterministic one-use approval fixture for offline tests.",
    parameters_json_schema=_ApprovalProbeArguments.model_json_schema(),
    side_effect=True,
)


def _capture_read_scopes(paths: list[str]) -> tuple[str, ...] | None:
    """Capture only a bounded, canonical subset suitable for a portable hint."""
    if not paths or len(paths) > 32 or sum(len(path) for path in paths) > 4096:
        return None
    for path in paths:
        if (
            not path
            or not path.isascii()
            or any(ord(character) < 32 or ord(character) == 127 for character in path)
            or any(character in path for character in "\\*?[]")
        ):
            return None
        parsed = PurePosixPath(path)
        if (
            path == "."
            or parsed.is_absolute()
            or str(parsed) != path
            or ".." in parsed.parts
            or len(parsed.parts) > 64
        ):
            return None
    return tuple(paths)


def _read_scope_pattern(scopes: tuple[str, ...] | None, redactor: Redactor) -> str | None:
    # Scan raw values before regex encoding can conceal a registered secret.
    # Recheck on every advertisement, including after late secret registration.
    if scopes is None or redactor.contains_secret_data(scopes):
        return None
    alternatives: list[str] = []
    prefix, suffix = r"(?:^(?:", r")(?:/|$)|[^\x00-\x7F])"
    size = len(prefix) + len(suffix)
    for scope in scopes:
        fragments: list[str] = []
        for character in scope:
            if "a" <= character.lower() <= "z":
                fragment = f"[{character.lower()}{character.upper()}]"
            elif character in ".^$+{}()|":
                fragment = "\\" + character
            else:
                fragment = character
            size += len(fragment)
            if size > 8192:
                return None
            fragments.append(fragment)
        if alternatives:
            size += 1
            if size > 8192:
                return None
        alternatives.append("".join(fragments))
    # Non-ASCII input deliberately escapes this hint: Unicode casefold aliases
    # (including Kelvin sign and long s) must reach the existing path predicate.
    return prefix + "|".join(alternatives) + suffix


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
        allowed_tools: tuple[str, ...] | None = None,
    ) -> None:
        if max_calls < 0:
            raise ValueError("runtime tool budget cannot be negative")
        self._gateway = gateway
        self._redactor = redactor
        self._run = run
        self._task = task
        self._read_scopes = _capture_read_scopes(task.allowed_paths)
        self._agent = agent
        self._workspace = workspace
        self._sandbox_handle = sandbox_handle
        self._max_calls = max_calls
        self._allowed_tools = allowed_tools
        self._records: list[RuntimeToolExecutionRecord] = []
        self._completed: dict[str, tuple[RuntimeToolCall, RuntimeToolResult]] = {}

    @property
    def definitions(self) -> tuple[RuntimeToolDefinition, ...]:
        definitions = self._kind_definitions()
        if self._allowed_tools is None:
            return definitions
        actions = {
            "repo_list_files": "repo.list_files",
            "repo_read_file": "repo.read_file",
            "repo_search_text": "repo.search_text",
            "workspace_get_diff": "workspace.get_diff",
            "workspace_write_file": "workspace.write_file",
            "workspace_apply_edit": "workspace.apply_edit",
            "workspace_delete_file": "workspace.delete_path",
            "run_verification": "command.run",
            "record_approval_probe": "fixture.record_side_effect",
        }
        return tuple(item for item in definitions if actions[item.name] in self._allowed_tools)

    def _kind_definitions(self) -> tuple[RuntimeToolDefinition, ...]:
        read_tools = [_LIST_FILES, self._read_file_definition(), _SEARCH_TEXT, _GET_DIFF]
        if self._agent.effective_kind in {AgentRole.RESEARCHER, AgentRole.ARCHITECT}:
            return tuple(read_tools)
        run_verification = self._run_verification_definition()
        verification_tools = () if run_verification is None else (run_verification,)
        if self._agent.effective_kind == AgentRole.ENGINEER:
            definitions = [
                *read_tools,
                _WRITE_FILE,
                _APPLY_EDIT,
                _DELETE_FILE,
                *verification_tools,
            ]
            if self._run.fake_scenario is FakeScenario.APPROVAL:
                definitions.append(_APPROVAL_PROBE)
            return tuple(definitions)
        if self._agent.effective_kind == AgentRole.VERIFIER:
            return (*read_tools, *verification_tools)
        return ()

    def _read_file_definition(self) -> RuntimeToolDefinition:
        definition = _READ_FILE.model_copy(deep=True)
        pattern = _read_scope_pattern(self._read_scopes, self._redactor)
        if pattern is not None:
            properties = definition.parameters_json_schema["properties"]
            assert isinstance(properties, dict)
            path = properties["path"]
            assert isinstance(path, dict)
            path["pattern"] = pattern
        return definition

    @property
    def records(self) -> tuple[RuntimeToolExecutionRecord, ...]:
        return tuple(self._records)

    def validate(self, call: RuntimeToolCall) -> None:
        # Keep recognized built-in writer/verifier attempts on the Broker path
        # so rejected mutations retain an exact denied intent and audit decision.
        # Custom ceilings and read-only specialists still reject unexposed tools.
        if (
            self._allowed_tools is not None
            or self._agent.effective_kind in {AgentRole.RESEARCHER, AgentRole.ARCHITECT}
        ) and call.name not in {definition.name for definition in self.definitions}:
            raise FleetError(
                ErrorCode.COMMAND_DENIED,
                "Read-only specialists may use only bounded repository observation tools.",
                "Use the exact read-only catalog; specialists cannot write, execute or approve.",
            )
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
        if call.name == _LIST_FILES.name:
            list_arguments = _ReasonArguments.model_validate(call.arguments)
            return (
                ScriptedAction(
                    action="repo.list_files",
                    resource=CanonicalResource(kind="workspace_view", identifier="."),
                    parameters={},
                    reason=list_arguments.reason,
                    side_effect=False,
                    idempotency_key=(
                        f"{identity_prefix}:{canonical_json_hash(call.arguments)[:24]}"
                    ),
                ),
                False,
            )
        if call.name == _READ_FILE.name:
            read_arguments = _PathArguments.model_validate(call.arguments)
            return (
                ScriptedAction(
                    action="repo.read_file",
                    resource=CanonicalResource(
                        kind="workspace_path", identifier=read_arguments.path
                    ),
                    parameters={},
                    reason=read_arguments.reason,
                    side_effect=False,
                    idempotency_key=(
                        f"{identity_prefix}:{canonical_json_hash(call.arguments)[:24]}"
                    ),
                ),
                False,
            )
        if call.name == _SEARCH_TEXT.name:
            search_arguments = _SearchArguments.model_validate(call.arguments)
            return (
                ScriptedAction(
                    action="repo.search_text",
                    resource=CanonicalResource(kind="workspace_view", identifier="."),
                    parameters={"query": search_arguments.query},
                    reason=search_arguments.reason,
                    side_effect=False,
                    idempotency_key=(
                        f"{identity_prefix}:{canonical_json_hash(call.arguments)[:24]}"
                    ),
                ),
                False,
            )
        if call.name == _GET_DIFF.name:
            diff_arguments = _ReasonArguments.model_validate(call.arguments)
            return (
                ScriptedAction(
                    action="workspace.get_diff",
                    resource=CanonicalResource(kind="workspace_view", identifier="."),
                    parameters={},
                    reason=diff_arguments.reason,
                    side_effect=False,
                    idempotency_key=(
                        f"{identity_prefix}:{canonical_json_hash(call.arguments)[:24]}"
                    ),
                ),
                False,
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
        if call.name == _APPLY_EDIT.name:
            edit_arguments = _EditArguments.model_validate(call.arguments)
            scripted = ScriptedAction(
                action="workspace.apply_edit",
                resource=CanonicalResource(kind="workspace_path", identifier=edit_arguments.path),
                parameters={
                    "expected_sha256": edit_arguments.expected_sha256,
                    "old": edit_arguments.old,
                    "new": edit_arguments.new,
                    "expected_matches": edit_arguments.expected_matches,
                },
                reason=edit_arguments.reason,
                side_effect=True,
                idempotency_key=(f"{identity_prefix}:{canonical_json_hash(call.arguments)[:24]}"),
            )
            return scripted, True
        if call.name == _DELETE_FILE.name:
            delete_arguments = _DeleteArguments.model_validate(call.arguments)
            scripted = ScriptedAction(
                action="workspace.delete_path",
                resource=CanonicalResource(kind="workspace_path", identifier=delete_arguments.path),
                parameters={"expected_sha256": delete_arguments.expected_sha256},
                reason=delete_arguments.reason,
                side_effect=True,
                idempotency_key=(f"{identity_prefix}:{canonical_json_hash(call.arguments)[:24]}"),
            )
            return scripted, True
        if call.name == "run_verification":
            verification_arguments = _VerificationArguments.model_validate(call.arguments)
            command = self._command(verification_arguments.command_id)
            command_hash = canonical_json_hash(command.model_dump(mode="json"))
            configuration = self._run.sandbox_configuration
            if configuration is None:
                raise FleetError(
                    ErrorCode.CONFIG_INVALID,
                    "Run sandbox configuration is unavailable.",
                    "Recover the Run from its immutable Project configuration.",
                )
            scripted = ScriptedAction(
                action="command.run",
                resource=CanonicalResource(kind="project_command", identifier=command.command_id),
                parameters={
                    "command_id": command.command_id,
                    "command_spec_sha256": command_hash,
                    "network_mode": configuration.network_mode,
                },
                reason=verification_arguments.reason,
                side_effect=True,
                idempotency_key=(
                    f"{identity_prefix}:{command.command_id}:{command_hash[:24]}:"
                    f"{self._run.patch_sha256 or 'candidate-current'}"
                ),
            )
            return scripted, True
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

    def _commands(self) -> tuple[CommandSpec, ...]:
        if self._task.verification_commands:
            return tuple(self._task.verification_commands)
        if self._run.sandbox_name == "fake":
            return (
                CommandSpec(
                    command_id="offline-canary",
                    executable="python",
                    argv=("-m", "pytest", "-q"),
                ),
            )
        return ()

    def _command(self, command_id: str) -> CommandSpec:
        for command in self._commands():
            if command.command_id == command_id:
                return command
        raise FleetError(
            ErrorCode.COMMAND_NOT_REVIEWED,
            f"Verification command {command_id!r} is not bound to the TaskSpec.",
            "Use one of the exact command IDs supplied by the control plane.",
            details={"command_id": command_id},
        )

    def _run_verification_definition(self) -> RuntimeToolDefinition | None:
        command_ids = [command.command_id for command in self._commands()]
        if not command_ids:
            return None
        schema = _VerificationArguments.model_json_schema()
        command_property = schema.get("properties", {}).get("command_id")
        if isinstance(command_property, dict):
            command_property["enum"] = command_ids
        return RuntimeToolDefinition(
            name="run_verification",
            description=(
                "Run one exact TaskSpec-bound verification command through the configured "
                "sandbox. Supply both its exact command_id and a reason; mentioning an ID "
                "inside reason is not supplying command_id. The control plane supplies "
                "executable, argv, cwd, environment, "
                "limits, identity, and permission context. The returned "
                "content.command_evidence_artifact_id names the CommandEvidence receipt; pair "
                "only that ID with this command_id in criterion mappings. The generic artifact_ids "
                "collection includes auxiliary artifacts; content.transcript_artifact_id is not "
                "a CommandEvidence receipt."
            ),
            parameters_json_schema=schema,
            side_effect=True,
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
