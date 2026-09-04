from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from agent_fleet.domain.models import (
    AgentInvocation,
    AgentInvocationResult,
    ArtifactKind,
    ImplementationReport,
    Project,
    Run,
    RuntimeConfiguration,
    RuntimeProviderMetadata,
    RuntimeToolCall,
    RuntimeToolDefinition,
    RuntimeToolExecutionRecord,
    RuntimeToolOutcome,
    RuntimeToolResult,
    ScopeDecision,
    UsageRecord,
    WorkflowStage,
)


def _scope_decision() -> ScopeDecision:
    return ScopeDecision(
        normalized_goal="Fix division by zero",
        workflow="code-change",
        change_kind="code_change",
        fleet_strategy="engineer_verifier",
        allowed_paths=["src/canary_calc/core.py"],
        forbidden_paths=[".git", ".fleet"],
        acceptance_criteria=[
            {
                "criterion_id": "division-zero",
                "description": "A zero denominator raises the stable ValueError.",
            }
        ],
        required_evidence=[
            "canonical_patch",
            "command_evidence",
            "independent_verifier_verdict",
        ],
    )


def _invocation(**input_values: object) -> AgentInvocation:
    return AgentInvocation(
        run_id="run_" + "1" * 32,
        task_id="task_" + "2" * 32,
        agent_instance_id="agent_" + "3" * 32,
        role="engineer",
        stage=WorkflowStage.IMPLEMENTING,
        iteration=0,
        max_steps=10,
        input=input_values,
    )


def test_runtime_configuration_is_bounded_and_coherent() -> None:
    assert RuntimeConfiguration().runtime_name == "fake"
    configured = RuntimeConfiguration(
        runtime_name="pydantic-ai",
        provider_model="openai:gpt-5",
        credential_ref="env:OPENAI_API_KEY",
        max_requests=2,
        max_tool_calls=4,
        max_total_tokens=4096,
        timeout_seconds=30,
        max_retries=0,
    )
    assert configured.provider_model == "openai:gpt-5"

    invalid_values = (
        {"runtime_name": "fake", "provider_model": "openai:gpt-5"},
        {"runtime_name": "fake", "credential_ref": "env:OPENAI_API_KEY"},
        {"runtime_name": "pydantic-ai"},
        {
            "runtime_name": "pydantic-ai",
            "provider_model": "gpt-5",
            "credential_ref": "env:OPENAI_API_KEY",
        },
        {
            "runtime_name": "pydantic-ai",
            "provider_model": "openai:",
            "credential_ref": "env:OPENAI_API_KEY",
        },
    )
    for value in invalid_values:
        with pytest.raises(ValidationError):
            RuntimeConfiguration.model_validate(value)


def test_persisted_runtime_fields_default_to_fake_and_enforce_coherence() -> None:
    now = datetime(2026, 9, 4, tzinfo=UTC)
    project_data = {
        "project_id": "prj_" + "1" * 32,
        "canonical_root": "/logical/project-identity-only",
        "identity_hash": "a" * 64,
        "created_at": now,
        "updated_at": now,
    }
    project = Project.model_validate(project_data)
    assert project.runtime_name == "fake"
    assert project.provider_model is None
    assert project.credential_ref is None

    provider_project = Project.model_validate(
        {
            **project_data,
            "runtime_name": "pydantic-ai",
            "provider_model": "openai:gpt-5",
            "credential_ref": "env:OPENAI_API_KEY",
        }
    )
    assert provider_project.runtime_name == "pydantic-ai"

    run_data = {
        "run_id": "run_" + "2" * 32,
        "project_id": project.project_id,
        "correlation_id": "corr_" + "3" * 32,
        "goal": "Fix the canary",
        "base_revision": "abc123",
        "target_status_fingerprint": "b" * 64,
        "created_at": now,
        "updated_at": now,
    }
    restored_run = Run.model_validate(run_data)
    assert restored_run.runtime_name == "fake"
    assert restored_run.runtime_usage_artifact_ids == []
    assert ArtifactKind.RUNTIME_USAGE.value == "runtime_usage"
    with pytest.raises(ValidationError, match="requires provider_model and credential_ref"):
        Run.model_validate({**run_data, "runtime_name": "pydantic-ai"})


def test_scope_decision_rejects_extra_fields_and_incoherent_authority() -> None:
    decision = _scope_decision()
    assert decision.allowed_paths == ["src/canary_calc/core.py"]

    with pytest.raises(ValidationError):
        ScopeDecision.model_validate({**decision.model_dump(), "host_path": "/tmp/project"})
    with pytest.raises(ValidationError, match="cannot allow protected path"):
        ScopeDecision.model_validate(
            {**decision.model_dump(), "allowed_paths": [".fleet/fleet.yaml"]}
        )
    with pytest.raises(ValidationError, match="requires independent verifier evidence"):
        ScopeDecision.model_validate(
            {
                **decision.model_dump(),
                "required_evidence": ["canonical_patch", "command_evidence"],
            }
        )
    with pytest.raises(ValidationError, match="read-only"):
        ScopeDecision.model_validate(
            {
                **decision.model_dump(),
                "change_kind": "read_only",
                "fleet_strategy": "direct",
            }
        )


def test_runtime_input_rejects_hidden_host_paths_credentials_and_oversize() -> None:
    with pytest.raises(ValidationError, match="absolute host path"):
        _invocation(note="/Users/example/private/repository")
    with pytest.raises(ValidationError, match="execution capability"):
        _invocation(nested={"provider_api_key": "secret"})
    with pytest.raises(ValidationError, match="oversized string"):
        _invocation(context="x" * 32_769)


def test_usage_and_provider_metadata_are_provider_neutral_and_strict() -> None:
    usage = UsageRecord(
        requests=1,
        input_tokens=100,
        output_tokens=25,
        total_tokens=125,
        tool_calls=2,
        provider_cost=Decimal("0.0042"),
        provider_currency="USD",
    )
    restored = UsageRecord.model_validate_json(usage.model_dump_json())
    assert restored == usage

    with pytest.raises(ValidationError, match="at least one"):
        UsageRecord()
    with pytest.raises(ValidationError, match="reported together"):
        UsageRecord(provider_cost=Decimal("1.00"))
    with pytest.raises(ValidationError):
        RuntimeProviderMetadata.model_validate(
            {"provider": "openai", "raw_response": {"authorization": "secret"}}
        )


def test_runtime_output_union_round_trips_without_script_or_sdk_objects() -> None:
    report = ImplementationReport(
        summary="Implemented bounded behavior.",
        intended_changed_paths=["src/canary_calc/core.py"],
        tests_added_or_changed=[],
        criterion_results=["division-zero: candidate produced"],
        evidence_artifact_ids=[],
        unresolved_limitations=["Fake sandbox did not execute project code."],
        verifier_focus=["Check the stable exception message."],
    )
    result = AgentInvocationResult(
        output=report,
        usage=UsageRecord(requests=1),
        provider_metadata=RuntimeProviderMetadata(provider="openai", model="openai:gpt-5"),
    )
    restored = AgentInvocationResult.model_validate_json(result.model_dump_json())
    assert isinstance(restored.output, ImplementationReport)
    assert restored == result

    with pytest.raises(ValidationError):
        AgentInvocationResult.model_validate(
            {"output": {"actions": [], "report": report.model_dump(mode="json")}}
        )


def test_runtime_tool_surface_is_strict_bounded_and_excludes_raw_records() -> None:
    definition = RuntimeToolDefinition(
        name="workspace_write_file",
        description="Write one TaskSpec-authorized logical path.",
        parameters_json_schema={"type": "object", "properties": {}},
        side_effect=True,
    )
    call = RuntimeToolCall(
        call_id="call_1",
        name=definition.name,
        arguments={"path": "src/example.py", "content": "safe"},
    )
    result = RuntimeToolResult(call_id=call.call_id, name=call.name, content={"ok": True})
    record = RuntimeToolExecutionRecord(
        call_id=call.call_id,
        name=call.name,
        outcome=RuntimeToolOutcome.SUCCEEDED,
        side_effect=True,
        side_effect_committed=True,
    )
    assert result.content == {"ok": True}
    assert "arguments" not in record.model_dump()

    with pytest.raises(ValidationError, match="must describe an object"):
        RuntimeToolDefinition(
            name="bad_tool",
            description="Invalid schema.",
            parameters_json_schema={"type": "string"},
        )
    with pytest.raises(ValidationError, match="only a side-effecting tool"):
        RuntimeToolExecutionRecord(
            call_id="call_2",
            name="run_verification",
            outcome=RuntimeToolOutcome.SUCCEEDED,
            side_effect=False,
            side_effect_committed=True,
        )
