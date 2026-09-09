from __future__ import annotations

from typing import cast

import pytest

from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import AgentInvocation, AgentRole, RuntimeCapability, WorkflowStage
from agent_fleet.domain.runtime_contract import require_runtime_invocation


def invocation(role: str = "engineer") -> AgentInvocation:
    return AgentInvocation(
        run_id="run_" + "1" * 32,
        task_id="task_" + "2" * 32,
        agent_instance_id="agent_" + "3" * 32,
        role=role,
        stage=WorkflowStage.IMPLEMENTING,
        iteration=0,
        max_steps=4,
        input={},
    )


def admit(
    request: AgentInvocation,
    *,
    kind: AgentRole | None = None,
    supported: frozenset[AgentRole] = frozenset(AgentRole),
    capabilities: frozenset[RuntimeCapability] = frozenset(RuntimeCapability),
    has_tools: bool = False,
    cos_tools: bool = True,
    selected: str = "test-runtime",
) -> AgentRole:
    return require_runtime_invocation(
        request,
        selected_runtime=selected,
        adapter_runtime="test-runtime",
        execution_kind=kind,
        supported_kinds=supported,
        capabilities=capabilities,
        has_tools=has_tools,
        cos_tools_supported=cos_tools,
    )


@pytest.mark.parametrize("kind", list(AgentRole))
def test_builtin_resolves_without_mutating_request(kind: AgentRole) -> None:
    request = invocation(kind.value)
    before = request.model_dump_json()
    assert admit(request) is kind
    assert admit(request, kind=kind) is kind
    assert request.model_dump_json() == before


@pytest.mark.parametrize("kind", [kind for kind in AgentRole if kind is not AgentRole.COS])
def test_custom_specialist_requires_explicit_binding(kind: AgentRole) -> None:
    assert admit(invocation("custom-role"), kind=kind) is kind


@pytest.mark.parametrize("kind", list(AgentRole))
def test_unsupported_bound_kind_fails(kind: AgentRole) -> None:
    with pytest.raises(FleetError) as captured:
        admit(invocation(kind.value), supported=frozenset())
    assert captured.value.code is ErrorCode.RUNTIME_CAPABILITY_MISSING


@pytest.mark.parametrize("role", list(AgentRole))
@pytest.mark.parametrize("kind", list(AgentRole))
def test_builtin_cannot_be_rebound(role: AgentRole, kind: AgentRole) -> None:
    if role is kind:
        assert admit(invocation(role.value), kind=kind) is kind
    else:
        with pytest.raises(FleetError) as captured:
            admit(invocation(role.value), kind=kind)
        assert captured.value.code is ErrorCode.RUNTIME_OUTPUT_INVALID


def test_custom_cannot_impersonate_cos_or_omit_binding() -> None:
    with pytest.raises(FleetError) as captured:
        admit(invocation("unbound-role"))
    assert captured.value.code is ErrorCode.RUNTIME_CAPABILITY_MISSING
    with pytest.raises(FleetError) as captured:
        admit(invocation("custom-cos"), kind=AgentRole.COS)
    assert captured.value.code is ErrorCode.RUNTIME_OUTPUT_INVALID


@pytest.mark.parametrize("raw_kind", ["engineer", True, 1, object()])
def test_unvalidated_trusted_kind_fails_closed(raw_kind: object) -> None:
    with pytest.raises(FleetError) as captured:
        admit(invocation(), kind=cast(AgentRole, raw_kind))
    assert captured.value.code is ErrorCode.RUNTIME_OUTPUT_INVALID


@pytest.mark.parametrize("capability", [RuntimeCapability.CHECKPOINT, RuntimeCapability.RESUME])
def test_checkpoint_requires_both_declared_capabilities(capability: RuntimeCapability) -> None:
    request = invocation().model_copy(update={"checkpoint_ref": "art_" + "4" * 32})
    with pytest.raises(FleetError) as captured:
        admit(request, capabilities=frozenset(RuntimeCapability) - {capability})
    assert captured.value.code is ErrorCode.RUNTIME_CAPABILITY_MISSING
    assert captured.value.details == {"missing_capabilities": [capability.value]}
    # This only admits a declaration; it is not native-checkpoint implementation.
    assert admit(request) is AgentRole.ENGINEER


def test_structured_output_is_always_required_but_tools_are_conditional() -> None:
    with pytest.raises(FleetError) as captured:
        admit(invocation(), capabilities=frozenset())
    assert captured.value.details == {"missing_capabilities": ["structured_output"]}
    capabilities = frozenset({RuntimeCapability.STRUCTURED_OUTPUT})
    assert admit(invocation(), capabilities=capabilities) is AgentRole.ENGINEER
    with pytest.raises(FleetError) as captured:
        admit(invocation(), capabilities=capabilities, has_tools=True)
    assert captured.value.details == {"missing_capabilities": ["tool_calling"]}


def test_exact_runtime_selection_and_cos_catalog_constraints() -> None:
    with pytest.raises(FleetError) as captured:
        admit(invocation(), selected="other-runtime")
    assert captured.value.code is ErrorCode.RUNTIME_UNAVAILABLE
    with pytest.raises(FleetError) as captured:
        admit(invocation("cos"), has_tools=True, cos_tools=False)
    assert captured.value.code is ErrorCode.RUNTIME_CAPABILITY_MISSING
    assert admit(invocation("cos"), has_tools=True) is AgentRole.COS
