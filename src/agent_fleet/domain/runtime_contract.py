"""Pure invocation admission shared by the explicitly selected Harnesses.

Passing this guard grants no permission and proves no execution outcome. It only
rejects a request the selected adapter cannot interpret before contacting a model.
"""

from __future__ import annotations

from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import AgentInvocation, AgentRole, RuntimeCapability


def require_runtime_invocation(
    request: AgentInvocation,
    *,
    selected_runtime: str,
    adapter_runtime: str,
    execution_kind: AgentRole | None,
    supported_kinds: frozenset[AgentRole],
    capabilities: frozenset[RuntimeCapability],
    has_tools: bool,
    cos_tools_supported: bool = True,
) -> AgentRole:
    """Resolve an admitted execution kind without credentials, I/O or accounting."""

    if selected_runtime != adapter_runtime:
        raise FleetError(
            ErrorCode.RUNTIME_UNAVAILABLE,
            "The invocation does not select this runtime adapter.",
            "Use the exact control-plane-selected runtime; no fallback was attempted.",
        )
    required = {RuntimeCapability.STRUCTURED_OUTPUT}
    if has_tools:
        required.add(RuntimeCapability.TOOL_CALLING)
    if request.checkpoint_ref is not None:
        required.update({RuntimeCapability.CHECKPOINT, RuntimeCapability.RESUME})
    missing = required - capabilities
    if missing:
        raise FleetError(
            ErrorCode.RUNTIME_CAPABILITY_MISSING,
            "The selected runtime lacks an invocation capability.",
            "Review the declared capabilities; no model or tool action was replayed.",
            details={"missing_capabilities": sorted(item.value for item in missing)},
        )

    builtin = next((kind for kind in AgentRole if kind.value == request.role), None)
    kind = builtin if execution_kind is None else execution_kind
    if kind is not None and not isinstance(kind, AgentRole):
        raise FleetError(
            ErrorCode.RUNTIME_OUTPUT_INVALID,
            "The trusted execution kind is not a supported role value.",
            "Use the validated control-plane role template.",
        )
    if (builtin is not None and kind is not builtin) or (builtin is None and kind is AgentRole.COS):
        raise FleetError(
            ErrorCode.RUNTIME_OUTPUT_INVALID,
            "The runtime role and trusted execution kind disagree.",
            "Keep built-in role identities and the Chief of Staff principal unchanged.",
        )
    if kind is None or kind not in supported_kinds:
        raise FleetError(
            ErrorCode.RUNTIME_CAPABILITY_MISSING,
            "The runtime does not support the bound execution kind.",
            "Bind a custom role to an admitted specialist kind before invocation.",
        )
    if kind is AgentRole.COS and has_tools and not cos_tools_supported:
        raise FleetError(
            ErrorCode.RUNTIME_CAPABILITY_MISSING,
            "This runtime does not support tools for the Chief of Staff.",
            "Use its exact supported CoS catalog; no action was executed.",
        )
    return kind
