"""Per-role configuration is exercised through actual workflow dispatch and recovery."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
from conftest import FleetHarness
from pydantic_ai.models.test import TestModel

from agent_fleet.adapters.repository.git import GitRepositoryAdapter
from agent_fleet.adapters.runtime.fake import FakeRuntimeAdapter
from agent_fleet.adapters.runtime.pydantic_ai import PydanticAIRuntimeAdapter
from agent_fleet.adapters.system import UuidIdGenerator
from agent_fleet.application.runtime import RuntimeRegistry
from agent_fleet.bootstrap import build_container
from agent_fleet.domain.budgets import (
    ModelRequestReservation,
    RunBudgetSnapshot,
    RuntimeAttemptStatus,
)
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import (
    AgentInvocation,
    AgentInvocationResult,
    AgentRole,
    FakeScenario,
    RunStatus,
    RuntimeConfiguration,
    RuntimeCredentialCheck,
    RuntimePreflight,
    UsageRecord,
)
from agent_fleet.domain.trust import TrustMode
from agent_fleet.ports.runtime import EMPTY_RUNTIME_TOOL_CATALOG, RuntimeInvocationServices
from agent_fleet.ports.runtime_accounting import RuntimeAccounting

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


class ProviderAccounting:
    """Scripted provider step records an offline request instead of claiming a fake runtime."""

    def __init__(self, wrapped: RuntimeAccounting) -> None:
        self.wrapped = wrapped

    @property
    def attempt_id(self) -> str:
        return self.wrapped.attempt_id

    def reserve_request(
        self, request_sequence: int, *, requested_tokens: int
    ) -> ModelRequestReservation:
        return self.wrapped.reserve_request(request_sequence, requested_tokens=requested_tokens)

    def record_response(
        self, reservation: ModelRequestReservation, usage: UsageRecord
    ) -> RunBudgetSnapshot:
        return self.wrapped.record_response(reservation, usage)

    def record_unknown(self, reservation: ModelRequestReservation) -> None:
        self.wrapped.record_unknown(reservation)

    def reserve_tool_batch(self, batch_sequence: int, call_ids: tuple[str, ...]) -> None:
        self.wrapped.reserve_tool_batch(batch_sequence, call_ids)

    def record_simulated_step(self) -> None:
        reservation = self.wrapped.reserve_request(1, requested_tokens=100)
        self.wrapped.record_response(
            reservation, UsageRecord(requests=1, input_tokens=10, output_tokens=10, total_tokens=20)
        )

    def remaining_active_seconds(self) -> float:
        return self.wrapped.remaining_active_seconds()

    def finish(
        self, status: RuntimeAttemptStatus, *, error_code: ErrorCode | None = None
    ) -> RunBudgetSnapshot:
        return self.wrapped.finish(status, error_code=error_code)


class RoutedScript(FakeRuntimeAdapter):
    """Offline role outputs with independently recorded selected model configurations."""

    def __init__(self, scenario: FakeScenario = FakeScenario.SUCCESS) -> None:
        self.calls: list[tuple[str, str, RuntimeConfiguration]] = []
        self.scenario = scenario

    def preflight(
        self, configuration: RuntimeConfiguration, *, credential_check: RuntimeCredentialCheck
    ) -> RuntimePreflight:
        return (
            super()
            .preflight(RuntimeConfiguration(), credential_check=credential_check)
            .model_copy(update={"runtime_name": configuration.runtime_name})
        )

    async def invoke(
        self, request: AgentInvocation, services: RuntimeInvocationServices
    ) -> AgentInvocationResult:
        self.calls.append((request.run_id, request.role, services.configuration))
        request = request.model_copy(
            update={"input": {**request.input, "fake_scenario": self.scenario.value}}
        )
        services = replace(
            services,
            configuration=RuntimeConfiguration(),
            accounting=ProviderAccounting(services.accounting) if services.accounting else None,
            tools=EMPTY_RUNTIME_TOOL_CATALOG if request.role == AgentRole.COS else services.tools,
        )
        return await super().invoke(request, services)


def profiles(harness: FleetHarness, monkeypatch: pytest.MonkeyPatch) -> RoutedScript:
    service = harness.container.model_profiles
    project = service.project(harness.repository_root)
    for name in ("planning", "coding", "reviewing"):
        monkeypatch.setenv(f"FLEET_{name.upper()}_TEST_KEY", f"fixture-{name}-secret")
        service.set(
            name,
            configuration=RuntimeConfiguration(
                runtime_name="pydantic-ai",
                provider_model=f"openai:{name}",
                credential_ref=f"env:FLEET_{name.upper()}_TEST_KEY",
            ),
        )
    service.bind(project, default=True, profile="planning", expected_revision=0)
    service.bind(project, role="engineer", profile="coding", expected_revision=1)
    service.bind(project, role="verifier", profile="reviewing", expected_revision=2)
    adapter = RoutedScript()
    harness.container.workflow.runtimes = RuntimeRegistry(
        {"fake": FakeRuntimeAdapter(), "pydantic-ai": adapter}
    )
    return adapter


async def start(harness: FleetHarness) -> object:
    return await harness.container.workflow.start(
        project_path=harness.repository_root,
        goal="Fix the canary",
        runtime_name=None,
        sandbox_name=None,
        fake_scenario=None,
    )


async def test_each_agent_receives_its_own_pinned_model_and_safe_evidence(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = profiles(harness, monkeypatch)
    run = await harness.container.workflow.start(
        project_path=harness.repository_root,
        goal="Fix the canary",
        runtime_name=None,
        sandbox_name=None,
        fake_scenario=None,
    )
    assert run.status is RunStatus.READY_FOR_REVIEW
    assert run.model_bindings_sha256 is not None
    assert [
        (role, config.provider_model, config.credential_ref) for _, role, config in adapter.calls
    ] == [
        ("cos", "openai:planning", "env:FLEET_PLANNING_TEST_KEY"),
        ("engineer", "openai:coding", "env:FLEET_CODING_TEST_KEY"),
        ("verifier", "openai:reviewing", "env:FLEET_REVIEWING_TEST_KEY"),
    ]
    events = harness.container.state.list_events(run.run_id)
    assert len([event for event in events if event.event_type == "runtime.model_selected"]) == 3
    assert len(run.runtime_usage_artifact_ids) == 3
    observations = [
        json.loads(harness.container.artifacts.read_text(item))
        for item in run.runtime_usage_artifact_ids
    ]
    assert [item["selected_model"]["provider_model"] for item in observations] == [
        "openai:planning",
        "openai:coding",
        "openai:reviewing",
    ]
    assert all(item["usage"] is None for item in observations)
    assert "credential_ref" not in json.dumps(observations)
    status = harness.container.inspection.status(run.run_id)
    assert status["model_bindings"] is not None
    assert "_TEST_KEY" not in json.dumps(status)
    assert run.verified_complete is False
    assert not harness.container.state.outstanding_leases(run.run_id)


async def test_profile_mutation_during_pause_does_not_rebind_resume(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = profiles(harness, monkeypatch)
    harness.container.permissions.configure(
        harness.repository_root, mode=TrustMode.SAFE, allowed_paths=(".",)
    )
    paused = await harness.container.workflow.start(
        project_path=harness.repository_root,
        goal="Fix the canary",
        runtime_name=None,
        sandbox_name=None,
        fake_scenario=None,
    )
    assert paused.status is RunStatus.PAUSED_FOR_APPROVAL
    assert paused.pending_approval_id is not None
    harness.container.model_profiles.set(
        "coding", configuration=RuntimeConfiguration(), expected_revision=1
    )
    restarted = build_container(harness.state_root)
    resumed_adapter = RoutedScript()
    restarted.workflow.runtimes = RuntimeRegistry(
        {"fake": FakeRuntimeAdapter(), "pydantic-ai": resumed_adapter}
    )
    restarted.approvals.approve_once(paused.pending_approval_id)
    finished = await restarted.workflow.resume(paused.run_id)
    while finished.status is RunStatus.PAUSED_FOR_APPROVAL:
        assert finished.pending_approval_id is not None
        restarted.approvals.approve_once(finished.pending_approval_id)
        finished = await restarted.workflow.resume(finished.run_id)
    assert finished.status is RunStatus.READY_FOR_REVIEW
    assert finished.model_bindings_sha256 == paused.model_bindings_sha256
    assert resumed_adapter.calls[0][1:] == ("engineer", adapter.calls[-1][2])
    assert resumed_adapter.calls[0][2].provider_model == "openai:coding"


async def test_missing_snapshot_fails_resume_without_replaying_model(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = profiles(harness, monkeypatch)
    harness.container.permissions.configure(
        harness.repository_root, mode=TrustMode.SAFE, allowed_paths=(".",)
    )
    paused = await harness.container.workflow.start(
        project_path=harness.repository_root,
        goal="Fix the canary",
        runtime_name=None,
        sandbox_name=None,
        fake_scenario=None,
    )
    before = len(adapter.calls)
    with sqlite3.connect(harness.container.state.database_path) as connection:
        connection.execute("DELETE FROM run_model_bindings WHERE root_run_id=?", (paused.run_id,))
    with pytest.raises(FleetError) as caught:
        await harness.container.workflow.resume(paused.run_id)
    assert caught.value.code is ErrorCode.RECOVERY_REQUIRED
    assert len(adapter.calls) == before


async def test_missing_selected_key_fails_before_run_registration(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = profiles(harness, monkeypatch)
    monkeypatch.delenv("FLEET_REVIEWING_TEST_KEY")
    with pytest.raises(FleetError) as caught:
        await start(harness)
    assert caught.value.code is ErrorCode.CREDENTIAL_MISSING
    assert adapter.calls == []
    with sqlite3.connect(harness.container.state.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0


async def test_legacy_runs_keep_exact_wire_shape_and_no_model_sidecar(
    harness: FleetHarness,
) -> None:
    run = await harness.start()
    assert run.model_bindings_sha256 is None
    assert "model_bindings_sha256" not in run.model_dump(mode="json")
    assert "model_bindings_sha256" not in run.model_dump_json()
    with sqlite3.connect(harness.container.state.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM run_model_bindings").fetchone()[0] == 0


async def test_mixed_runtime_roles_keep_exact_accounting_identity(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = profiles(harness, monkeypatch)
    harness.container.model_profiles.set(
        "coding", configuration=RuntimeConfiguration(), expected_revision=1
    )
    run = await harness.container.workflow.start(
        project_path=harness.repository_root,
        goal="Fix the canary",
        runtime_name=None,
        sandbox_name=None,
        fake_scenario=None,
    )
    assert run.status is RunStatus.READY_FOR_REVIEW
    assert [role for _, role, _ in adapter.calls] == ["cos", "verifier"]
    budget = harness.container.budgets.snapshot(run.run_id)
    assert budget.model_requests == 2
    assert budget.simulated_steps == 1
    with sqlite3.connect(harness.container.state.database_path) as connection:
        attempts = [
            json.loads(row[0])
            for row in connection.execute("SELECT data_json FROM runtime_attempts ORDER BY rowid")
        ]
    assert [(item["role"], item["runtime_name"]) for item in attempts] == [
        ("cos", "pydantic-ai"),
        ("engineer", "fake"),
        ("verifier", "pydantic-ai"),
    ]
    with sqlite3.connect(harness.container.state.database_path) as connection:
        engineer = next(item for item in attempts if item["role"] == "engineer")
        engineer["runtime_name"] = "pydantic-ai"
        connection.execute(
            "UPDATE runtime_attempts SET data_json=? WHERE attempt_id=?",
            (json.dumps(engineer), engineer["attempt_id"]),
        )
    with pytest.raises(FleetError) as caught:
        harness.container.budgets.snapshot(run.run_id)
    assert caught.value.code is ErrorCode.RECOVERY_REQUIRED


async def test_full_workflow_uses_new_selection_without_obsolete_project_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = GitRepositoryAdapter(tmp_path, UuidIdGenerator()).create_canary_fixture(
        tmp_path / "repository"
    )
    container = build_container(tmp_path / "state")
    container.projects.runtime_registry = RuntimeRegistry(
        {
            "fake": FakeRuntimeAdapter(),
            "pydantic-ai": PydanticAIRuntimeAdapter.for_test_model(TestModel()),
        }
    )
    container.projects._initialize_without_canary(
        repository,
        runtime_name="pydantic-ai",
        provider_model="openai:obsolete-model",
        credential_ref="env:FLEET_OBSOLETE_PROFILE_KEY",
        sandbox_name="fake",
    )
    monkeypatch.setenv("FLEET_OBSOLETE_PROFILE_KEY", "bad")
    container.model_profiles.set("offline", configuration=RuntimeConfiguration())
    project = container.model_profiles.project(repository)
    container.model_profiles.bind(project, default=True, profile="offline", expected_revision=0)
    run = await container.workflow.start(
        project_path=repository,
        goal="Fix the canary",
        runtime_name=None,
        sandbox_name=None,
        fake_scenario=None,
    )
    assert run.status is RunStatus.READY_FOR_REVIEW
    assert run.runtime_name == "fake"
    assert run.credential_ref is None
    assert run.model_bindings_sha256 is not None


@pytest.mark.parametrize(
    "scenario", [FakeScenario.PARALLEL_ENGINEERS, FakeScenario.SPECIALIST, FakeScenario.REPAIR]
)
async def test_graph_specialists_and_repairs_preserve_root_models(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch, scenario: FakeScenario
) -> None:
    adapter = profiles(harness, monkeypatch)
    adapter.scenario = scenario
    run = await harness.container.workflow.start(
        project_path=harness.repository_root,
        goal="Fix the bounded canary",
        runtime_name=None,
        sandbox_name=None,
        fake_scenario=None,
    )
    assert run.status is RunStatus.READY_FOR_REVIEW
    for child_id, role, configuration in adapter.calls:
        assert (
            configuration.provider_model
            == {
                "cos": "openai:planning",
                "engineer": "openai:coding",
                "verifier": "openai:reviewing",
                "researcher": "openai:planning",
                "architect": "openai:planning",
            }[role]
        )
        child = harness.container.state.get_run(child_id)
        assert child.model_bindings_sha256 == run.model_bindings_sha256
    if scenario is FakeScenario.REPAIR:
        assert run.repair_iterations == 1
        assert [role for _, role, _ in adapter.calls].count("engineer") == 2
    elif scenario is FakeScenario.PARALLEL_ENGINEERS:
        assert len({child_id for child_id, role, _ in adapter.calls if role == "engineer"}) == 2
    else:
        assert {role for _, role, _ in adapter.calls} == {
            "cos",
            "researcher",
            "architect",
            "engineer",
            "verifier",
        }
    assert not harness.container.state.outstanding_leases(run.run_id)
