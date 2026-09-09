"""Pure, bounded digest computation for model-proposed organization content."""

from __future__ import annotations

from contextlib import suppress
from threading import RLock

from pydantic import ValidationError

from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.fleet_patch import (
    FleetPatchFileChange,
    validate_organization_proposal_path,
)
from agent_fleet.domain.models import (
    RuntimeToolCall,
    RuntimeToolDefinition,
    RuntimeToolExecutionRecord,
    RuntimeToolOutcome,
    RuntimeToolResult,
)
from agent_fleet.domain.organization_tree import MAX_FILES, validate_organization_path
from agent_fleet.domain.security import Redactor, canonical_json_hash, sha256_bytes
from agent_fleet.ports.runtime import RuntimeToolCatalog

_TOOL_NAME = "fleet_content_sha256"
_MAX_CONTENT_BYTES = 65_536
_MAX_CONTENT_CHARACTERS = 32_768
_DEFINITION = RuntimeToolDefinition(
    name=_TOOL_NAME,
    description=(
        "Only for a lasting organization FleetPatch: compute the SHA-256 and UTF-8 byte "
        "size of complete content for an exact allowed .fleet/ path and add/replace "
        "operation. Never use this for business source code or ordinary ScopeDecision. "
        "This pure utility never reads or writes files or proves target existence. "
        "Content is limited to 65536 UTF-8 bytes and the runtime's 65536-byte argument "
        "JSON ceiling."
    ),
    parameters_json_schema={
        "type": "object",
        "properties": {
            "operation": {"type": "string", "enum": ["add", "replace"]},
            "path": {
                "type": "string",
                "minLength": 8,
                "maxLength": 4096,
                "pattern": r"^\.fleet/",
            },
            "content": {"type": "string", "maxLength": _MAX_CONTENT_CHARACTERS},
        },
        "required": ["operation", "path", "content"],
        "additionalProperties": False,
    },
    side_effect=False,
)


def _invalid() -> FleetError:
    return FleetError(
        ErrorCode.COMMAND_DENIED,
        "The proposal hash request is invalid, unsafe, or conflicts with its prior identity.",
        "Use an exact add/replace organization target and bounded content with a unique "
        "call identity; ordinary task scoping needs no hash. Omit secret material.",
    )


class ProposalHashToolCatalog(RuntimeToolCatalog):
    """A computation-only catalog, independent of resource or permission authority."""

    def __init__(
        self, redactor: Redactor, *, visible_paths: frozenset[str], max_calls: int = 32
    ) -> None:
        if type(max_calls) is not int or not 0 <= max_calls <= 128:
            raise FleetError(
                ErrorCode.CONFIG_INVALID,
                "The proposal hash-call limit must be an integer between zero and 128.",
                "Use a bounded trusted invocation configuration.",
            )
        valid_paths = False
        if type(visible_paths) is frozenset and len(visible_paths) <= MAX_FILES:
            with suppress(ValueError, TypeError, UnicodeError):
                for path in visible_paths:
                    if type(path) is not str or not 8 <= len(path) <= 4096:
                        raise ValueError
                    # Complete visible context can include an existing file that
                    # is not an eligible FleetPatch target. Validate canonical
                    # context paths here; enforce mutable targets per request.
                    FleetPatchFileChange.validate_path(path)
                    validate_organization_path(path.removeprefix(".fleet/"))
                valid_paths = len({path.casefold() for path in visible_paths}) == len(visible_paths)
        if not valid_paths:
            raise FleetError(
                ErrorCode.CONFIG_INVALID,
                "The proposal hash targets do not match a bounded organization context.",
                "Use the immutable complete visible paths from the admitted context.",
            )
        self._redactor = redactor
        self._visible_paths = visible_paths
        self._visible_folded_paths = frozenset(path.casefold() for path in visible_paths)
        self._max_calls = max_calls
        self._lock = RLock()
        self._completed: dict[str, tuple[str, RuntimeToolResult]] = {}
        self._records: list[RuntimeToolExecutionRecord] = []

    @property
    def definitions(self) -> tuple[RuntimeToolDefinition, ...]:
        return (_DEFINITION.model_copy(deep=True),)

    @property
    def records(self) -> tuple[RuntimeToolExecutionRecord, ...]:
        with self._lock:
            return tuple(self._records)

    def _request(self, call: RuntimeToolCall) -> tuple[str, str, bytes, str, str]:
        # Do not serialize or compare a subclass/model_construct payload before
        # checking its exact plain schema shape and cheap allocation bounds.
        if type(call) is not RuntimeToolCall:
            raise _invalid()
        fields = vars(call)
        if (
            len(fields) != 3
            or any(type(key) is not str for key in fields)
            or set(fields) != {"call_id", "name", "arguments"}
        ):
            raise _invalid()
        call_id, name, arguments = fields["call_id"], fields["name"], fields["arguments"]
        if (
            type(call_id) is not str
            or not 1 <= len(call_id) <= 128
            or type(name) is not str
            or name != _TOOL_NAME
            or type(arguments) is not dict
            or len(arguments) != 3
            or any(type(key) is not str for key in arguments)
            or set(arguments) != {"operation", "path", "content"}
        ):
            raise _invalid()
        operation, path, content = (
            arguments["operation"],
            arguments["path"],
            arguments["content"],
        )
        if (
            type(operation) is not str
            or operation not in {"add", "replace"}
            or type(path) is not str
            or type(content) is not str
            or len(content) > _MAX_CONTENT_CHARACTERS
        ):
            raise _invalid()
        target_valid = False
        with suppress(FleetError):
            validate_organization_proposal_path(path)
            target_valid = (
                path in self._visible_paths
                if operation == "replace"
                else path.casefold() not in self._visible_folded_paths
            )
        if not target_valid:
            raise _invalid()
        encoded: bytes | None = None
        with suppress(UnicodeError):
            encoded = content.encode("utf-8")
        if encoded is None or len(encoded) > _MAX_CONTENT_BYTES:
            raise _invalid()
        # Bind every captured scalar, never the caller-mutable arguments mapping.
        payload = {
            "call_id": call_id,
            "name": name,
            "arguments": {"operation": operation, "path": path, "content": content},
        }
        # Every call, including exact repeats, sees the current registered secrets.
        if self._redactor.contains_secret_data(payload):
            raise _invalid()
        validated: RuntimeToolCall | None = None
        with suppress(ValidationError, ValueError, TypeError):
            validated = RuntimeToolCall.model_validate(payload)
        if validated is None:
            raise _invalid()
        request_hash = canonical_json_hash(payload)
        if self._redactor.contains_secret(request_hash):
            raise _invalid()
        previous = self._completed.get(call_id)
        if previous is not None:
            if previous[0] != request_hash or self._redactor.contains_secret_data(
                previous[1].model_dump(mode="json")
            ):
                raise _invalid()
        elif len(self._completed) >= self._max_calls:
            raise FleetError(
                ErrorCode.RUNTIME_BUDGET_EXCEEDED,
                "The proposal hash-call budget is exhausted.",
                "Reduce the number of proposed files within the reviewed invocation budget.",
            )
        return call_id, request_hash, encoded, operation, path

    def validate(self, call: RuntimeToolCall) -> None:
        with self._lock:
            self._request(call)

    async def execute(self, call: RuntimeToolCall) -> RuntimeToolResult:
        # No await or external call occurs inside this pure computation boundary.
        with self._lock:
            call_id, request_hash, encoded, operation, path = self._request(call)
            previous = self._completed.get(call_id)
            if previous is not None:
                if self._redactor.contains_secret_data(previous[1].model_dump(mode="json")):
                    raise _invalid()
                return previous[1].model_copy(deep=True)
            result = RuntimeToolResult(
                call_id=call_id,
                name=_TOOL_NAME,
                content={
                    "operation": operation,
                    "path": path,
                    "sha256": sha256_bytes(encoded),
                    "size_bytes": len(encoded),
                },
            )
            if self._redactor.contains_secret_data(result.model_dump(mode="json")):
                raise _invalid()
            self._completed[call_id] = (request_hash, result)
            self._records.append(
                RuntimeToolExecutionRecord(
                    call_id=call_id,
                    name=_TOOL_NAME,
                    outcome=RuntimeToolOutcome.SUCCEEDED,
                    side_effect=False,
                    side_effect_committed=False,
                )
            )
            return result.model_copy(deep=True)
