from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from collections.abc import Callable, Iterator, Mapping
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, cast

import pydantic_ai.models as pydantic_ai_models
import pytest
from conftest import FleetHarness
from live_provider_support import (
    PROFILE_LIMITS,
    ROOT_LIMITS,
    SELECTION_ENV,
    SELECTION_ROLES,
    LiveCanarySelection,
    default_live_canary_selection,
    parse_live_canary_selection,
    resolve_live_canary_credentials,
)
from pydantic import ValidationError
from typer.testing import CliRunner

from agent_fleet.adapters.runtime.fake import FakeRuntimeAdapter
from agent_fleet.application.runtime import RuntimeRegistry
from agent_fleet.cli.app import app
from agent_fleet.domain.budgets import (
    ModelRequestReservation,
    RunBudgetLimits,
    RunBudgetSnapshot,
    RuntimeAttemptStatus,
)
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.ids import IdPrefix
from agent_fleet.domain.models import (
    AgentInvocation,
    AgentInvocationResult,
    AgentRole,
    FakeScenario,
    Run,
    RunStatus,
    RuntimeConfiguration,
    RuntimeCredentialCheck,
    RuntimePreflight,
    UsageRecord,
)
from agent_fleet.ports.runtime import EMPTY_RUNTIME_TOOL_CATALOG, RuntimeInvocationServices
from agent_fleet.ports.runtime_accounting import RuntimeAccounting

ADMITTED = (
    ("pydantic-ai", "openai"),
    ("pydantic-ai", "openai-chat"),
    ("pydantic-ai", "anthropic"),
    ("pydantic-ai", "google"),
    ("openai-agents", "openai"),
    ("langgraph", "openai"),
)
OFFLINE_KEY = "selection-offline-key-1234567890"
UNSAFE_CREDENTIAL_DESTINATIONS = (
    "SSLKEYLOGFILE",
    "SSL_CERT_FILE",
    "REQUESTS_CA_BUNDLE",
    "LD_PRELOAD",
    "DYLD_INSERT_LIBRARIES",
    "BASH_ENV",
    "NODE_OPTIONS",
    "GIT_SSH_COMMAND",
    "GIT_EXEC_PATH",
    "GIT_ASKPASS",
    "DOCKER_HOST",
    "DOCKER_CONFIG",
    "GIT_CONFIG_GLOBAL",
    "LANGSMITH_ENDPOINT",
    "LANGCHAIN_TRACING_V2",
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "OPENAI_ORG_ID",
    "AZURE_OPENAI_ENDPOINT",
    "GOOGLE_CLOUD_QUOTA_PROJECT",
)

_MIXED_KEYS = {
    "FLEET_SELECTION_COS_KEY": "offline-cos-key-1234567890",
    "FLEET_SELECTION_ENGINEER_KEY": "offline-engineer-key-1234567890",
    "FLEET_SELECTION_VERIFIER_KEY": "offline-verifier-key-1234567890",
}


class _LiveCanaryProfileSetup(Protocol):
    primary_profiles: dict[str, str]
    default_profile: str | None
    selection_revision: int


class _LiveCanaryProfileFixture(Protocol):
    CANARY_INITIALIZED_ROLES: tuple[str, ...]

    def configure_live_canary_profiles(
        self,
        selection: LiveCanarySelection,
        repository: Path,
        invoke: Callable[[list[str]], object],
        *,
        complete_role_closure: bool,
    ) -> _LiveCanaryProfileSetup: ...


def _load_live_canary_profile_fixture() -> _LiveCanaryProfileFixture:
    path = Path(__file__).parents[1] / "live" / "test_provider_smoke.py"
    spec = importlib.util.spec_from_file_location("_live_canary_profile_fixture", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("live canary profile fixture is not importable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return cast(_LiveCanaryProfileFixture, module)


_LIVE_PROFILE_FIXTURE = _load_live_canary_profile_fixture()
CANARY_INITIALIZED_ROLES = _LIVE_PROFILE_FIXTURE.CANARY_INITIALIZED_ROLES


def _payload(
    runtime: str = "pydantic-ai",
    provider: str = "openai",
    reference: str = "env:FLEET_SELECTION_OFFLINE_KEY",
) -> dict[str, object]:
    role = {
        "runtime_name": runtime,
        "provider_model": f"{provider}:selection-test-model",
        "credential_ref": reference,
    }
    return {"schema_version": 1, **{name: dict(role) for name in SELECTION_ROLES}}


def _mixed_selection() -> LiveCanarySelection:
    return parse_live_canary_selection(
        json.dumps(
            {
                "schema_version": 1,
                "cos": {
                    "runtime_name": "pydantic-ai",
                    "provider_model": "openai:selection-cos",
                    "credential_ref": "env:FLEET_SELECTION_COS_KEY",
                },
                "engineer": {
                    "runtime_name": "openai-agents",
                    "provider_model": "openai:selection-engineer",
                    "credential_ref": "env:FLEET_SELECTION_ENGINEER_KEY",
                },
                "verifier": {
                    "runtime_name": "langgraph",
                    "provider_model": "openai:selection-verifier",
                    "credential_ref": "env:FLEET_SELECTION_VERIFIER_KEY",
                },
            }
        )
    )


def _public_json_invoker(
    harness: FleetHarness,
) -> Callable[[list[str]], object]:
    runner = CliRunner()
    environment = {"AGENT_FLEET_HOME": str(harness.state_root)}

    def invoke(arguments: list[str]) -> object:
        result = runner.invoke(app, arguments, env=environment)
        assert result.exit_code == 0, result.output
        envelope = json.loads(result.stdout)
        assert envelope["ok"] is True
        return envelope["data"]

    return invoke


class _OfflineAccounting:
    """Record one controlled response instead of claiming a fake-runtime attempt."""

    def __init__(self, wrapped: RuntimeAccounting) -> None:
        self.wrapped = wrapped

    @property
    def attempt_id(self) -> str:
        return self.wrapped.attempt_id

    def reserve_request(
        self,
        request_sequence: int,
        *,
        requested_tokens: int,
    ) -> ModelRequestReservation:
        return self.wrapped.reserve_request(
            request_sequence,
            requested_tokens=requested_tokens,
        )

    def record_response(
        self,
        reservation: ModelRequestReservation,
        usage: UsageRecord,
    ) -> RunBudgetSnapshot:
        return self.wrapped.record_response(reservation, usage)

    def record_unknown(self, reservation: ModelRequestReservation) -> None:
        self.wrapped.record_unknown(reservation)

    def reserve_tool_batch(self, batch_sequence: int, call_ids: tuple[str, ...]) -> None:
        self.wrapped.reserve_tool_batch(batch_sequence, call_ids)

    def record_simulated_step(self) -> None:
        reservation = self.wrapped.reserve_request(1, requested_tokens=100)
        self.wrapped.record_response(
            reservation,
            UsageRecord(requests=1, input_tokens=10, output_tokens=10, total_tokens=20),
        )

    def remaining_active_seconds(self) -> float:
        return self.wrapped.remaining_active_seconds()

    def finish(
        self,
        status: RuntimeAttemptStatus,
        *,
        error_code: ErrorCode | None = None,
    ) -> RunBudgetSnapshot:
        return self.wrapped.finish(status, error_code=error_code)


class _OfflineSelectedRuntime(FakeRuntimeAdapter):
    """Use deterministic typed outputs while retaining the selected routing identity."""

    def __init__(
        self,
        runtime_name: str,
        trace: list[tuple[str, RuntimeConfiguration]],
    ) -> None:
        self.runtime_name = runtime_name
        self.trace = trace

    def preflight(
        self,
        configuration: RuntimeConfiguration,
        *,
        credential_check: RuntimeCredentialCheck,
    ) -> RuntimePreflight:
        del credential_check
        return (
            super()
            .preflight(RuntimeConfiguration(), credential_check=RuntimeCredentialCheck.NONE)
            .model_copy(update={"runtime_name": configuration.runtime_name})
        )

    async def invoke(
        self,
        request: AgentInvocation,
        services: RuntimeInvocationServices,
    ) -> AgentInvocationResult:
        assert services.configuration.runtime_name == self.runtime_name
        self.trace.append((request.role, services.configuration))
        request = request.model_copy(
            update={"input": {**request.input, "fake_scenario": FakeScenario.SUCCESS.value}}
        )
        controlled_services = replace(
            services,
            configuration=RuntimeConfiguration(),
            tools=(EMPTY_RUNTIME_TOOL_CATALOG if request.role == AgentRole.COS else services.tools),
            accounting=(
                _OfflineAccounting(services.accounting) if services.accounting is not None else None
            ),
        )
        return await super().invoke(request, controlled_services)


def _install_offline_selected_runtimes(
    harness: FleetHarness,
) -> list[tuple[str, RuntimeConfiguration]]:
    trace: list[tuple[str, RuntimeConfiguration]] = []
    registry = RuntimeRegistry(
        {
            "fake": FakeRuntimeAdapter(),
            **{
                runtime: _OfflineSelectedRuntime(runtime, trace)
                for runtime in ("pydantic-ai", "openai-agents", "langgraph")
            },
        }
    )
    harness.container.workflow.runtimes = registry
    harness.container.model_profiles.runtimes = registry
    return trace


def _configure_mixed_profiles(
    harness: FleetHarness,
    monkeypatch: pytest.MonkeyPatch,
    *,
    complete_role_closure: bool,
) -> tuple[LiveCanarySelection, _LiveCanaryProfileSetup]:
    for name, value in _MIXED_KEYS.items():
        monkeypatch.setenv(name, value)
    selection = _mixed_selection()
    invoke = _public_json_invoker(harness)
    setup = _LIVE_PROFILE_FIXTURE.configure_live_canary_profiles(
        selection,
        harness.repository_root,
        invoke,
        complete_role_closure=complete_role_closure,
    )
    return selection, setup


def _initialized_roles(harness: FleetHarness) -> tuple[str, ...]:
    spec, snapshot = harness.container.workflow.config.load_snapshot(
        harness.repository_root / ".fleet" / "fleet.yaml"
    )
    templates = harness.container.workflow.config.role_templates(spec, snapshot)
    return tuple(sorted(set(spec.spec.agents) | set(templates)))


@pytest.mark.parametrize(("runtime", "provider"), ADMITTED)
def test_every_existing_provider_harness_admission_is_accepted(runtime: str, provider: str) -> None:
    selection = parse_live_canary_selection(json.dumps(_payload(runtime, provider)))
    for selected in selection.roles.values():
        assert selected.configuration().runtime_name == runtime
        assert selected.configuration().provider_model == f"{provider}:selection-test-model"
        assert selected.configuration().model_dump(mode="json") == {
            "runtime_name": runtime,
            "provider_model": f"{provider}:selection-test-model",
            "credential_ref": "env:FLEET_SELECTION_OFFLINE_KEY",
            **PROFILE_LIMITS,
        }


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.update(schema_version=2),
        lambda value: value.update(schema_version=1.0),
        lambda value: value.update(schema_version=True),
        lambda value: value.update(extra="not-allowed"),
        lambda value: value.pop("verifier"),
        lambda value: value["cos"].update(endpoint="https://invalid.example"),
        lambda value: value["engineer"].update(max_requests=99),
        lambda value: value["cos"].update(runtime_name="fake"),
        lambda value: value["cos"].update(runtime_name="unknown"),
        lambda value: value["cos"].update(runtime_name="openai-agents", provider_model="google:x"),
        lambda value: value["cos"].update(credential_ref="key-is-not-a-reference"),
        lambda value: value["cos"].update(credential_ref="env:PATH"),
        lambda value: value["cos"].update(credential_ref="env:OPENAI_API_KEY"),
        lambda value: value["cos"].update(credential_ref="env:AGENT_FLEET_NEW_CONTROL"),
    ],
)
def test_invalid_selection_shapes_are_rejected(mutate: object) -> None:
    payload = _payload()
    mutate(payload)  # type: ignore[operator]
    with pytest.raises((ValidationError, ValueError)):
        parse_live_canary_selection(json.dumps(payload))


@pytest.mark.parametrize(
    "payload",
    [
        b"not-json",
        b'{"schema_version":1,"schema_version":1}',
        b"{}" + b" " * (16 * 1024),
    ],
    ids=("malformed", "duplicate", "oversized"),
)
def test_malformed_duplicate_or_oversized_json_is_rejected(payload: bytes) -> None:
    with pytest.raises((ValidationError, ValueError)):
        parse_live_canary_selection(payload)


def test_default_is_exact_legacy_selection_and_canonical() -> None:
    selection = default_live_canary_selection()
    assert selection == parse_live_canary_selection(selection.canonical_json)
    assert selection.canonical_json == json.dumps(
        selection.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def test_shared_public_profile_setup_preserves_legacy_single_default(
    harness: FleetHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FLEET_OPENAI_TEST_KEY", OFFLINE_KEY)
    selection = default_live_canary_selection()
    setup = _LIVE_PROFILE_FIXTURE.configure_live_canary_profiles(
        selection,
        harness.repository_root,
        _public_json_invoker(harness),
        complete_role_closure=True,
    )
    project = harness.container.model_profiles.project(harness.repository_root)
    persisted = harness.container.model_profiles.store.get_selection(project.project_id)

    assert setup.primary_profiles == dict.fromkeys(SELECTION_ROLES, "live-canary")
    assert setup.default_profile == "live-canary"
    assert setup.selection_revision == 1
    assert persisted is not None
    assert persisted.revision == 1
    assert persisted.default_profile == "live-canary"
    assert persisted.role_overrides == {}
    assert len(selection.sha256) == 64
    assert all(
        selected.runtime_name == "pydantic-ai"
        and selected.provider_model == "openai:gpt-5-nano"
        and selected.credential_ref == "env:FLEET_OPENAI_TEST_KEY"
        for selected in selection.roles.values()
    )


def test_custom_dedicated_fleet_reference_is_admitted() -> None:
    selection = parse_live_canary_selection(
        json.dumps(_payload(reference="env:FLEET_CUSTOM_LIVE_KEY_2"))
    )
    assert {item.credential_ref for item in selection.roles.values()} == {
        "env:FLEET_CUSTOM_LIVE_KEY_2"
    }


@pytest.mark.parametrize("name", UNSAFE_CREDENTIAL_DESTINATIONS)
def test_non_fleet_credential_destinations_are_rejected_by_namespace(name: str) -> None:
    with pytest.raises(ValidationError, match="dedicated FLEET_ variable"):
        parse_live_canary_selection(json.dumps(_payload(reference=f"env:{name}")))


def test_cross_provider_reference_and_equal_value_are_rejected_safely() -> None:
    payload = _payload()
    payload["engineer"] = {
        "runtime_name": "pydantic-ai",
        "provider_model": "anthropic:selection-test-model",
        "credential_ref": "env:FLEET_SELECTION_OFFLINE_KEY",
    }
    with pytest.raises(ValidationError, match="cross-provider credential isolation failed"):
        parse_live_canary_selection(json.dumps(payload))

    payload["engineer"]["credential_ref"] = "env:FLEET_SELECTION_ANTHROPIC_KEY"  # type: ignore[index]
    selection = parse_live_canary_selection(json.dumps(payload))
    with pytest.raises(ValueError, match="cross-provider credential isolation failed"):
        resolve_live_canary_credentials(
            selection,
            {
                "FLEET_SELECTION_OFFLINE_KEY": OFFLINE_KEY,
                "FLEET_SELECTION_ANTHROPIC_KEY": OFFLINE_KEY,
            },
        )


class _SelectedOnlyEnvironment(Mapping[str, str]):
    def __init__(self, value: str) -> None:
        self._value = value

    def __getitem__(self, name: str) -> str:
        if name != "FLEET_SELECTION_OFFLINE_KEY":
            raise AssertionError(f"unexpected environment lookup: {name}")
        return self._value

    def __iter__(self) -> Iterator[str]:
        yield "FLEET_SELECTION_OFFLINE_KEY"

    def __len__(self) -> int:
        return 1


def test_resolution_reads_only_selected_refs_and_missing_ref_fails() -> None:
    selection = parse_live_canary_selection(json.dumps(_payload()))
    assert resolve_live_canary_credentials(selection, _SelectedOnlyEnvironment(OFFLINE_KEY)) == {
        "FLEET_SELECTION_OFFLINE_KEY": OFFLINE_KEY
    }
    with pytest.raises(ValueError, match="not ready"):
        resolve_live_canary_credentials(selection, {})


@pytest.mark.parametrize(("runtime", "provider"), ADMITTED)
def test_public_cli_set_bind_and_persisted_run_binding_are_real_offline_operations(
    harness: FleetHarness,
    monkeypatch: pytest.MonkeyPatch,
    runtime: str,
    provider: str,
) -> None:
    reference = "env:FLEET_SELECTION_OFFLINE_KEY"
    monkeypatch.setenv("FLEET_SELECTION_OFFLINE_KEY", OFFLINE_KEY)
    runner = CliRunner()
    environment = {"AGENT_FLEET_HOME": str(harness.state_root)}
    profile_name = "live-canary-offline"
    model = f"{provider}:selection-test-model"
    configured = runner.invoke(
        app,
        [
            "models",
            "set",
            profile_name,
            "--runtime",
            runtime,
            "--provider-model",
            model,
            "--credential-ref",
            reference,
            *[
                argument
                for name, value in PROFILE_LIMITS.items()
                for argument in ("--" + name.replace("_", "-"), str(value))
            ],
            "--json",
        ],
        env=environment,
    )
    assert configured.exit_code == 0, configured.output
    bound = runner.invoke(
        app,
        [
            "models",
            "bind",
            profile_name,
            "--path",
            str(harness.repository_root),
            "--default",
            "--json",
        ],
        env=environment,
    )
    assert bound.exit_code == 0, bound.output

    container = harness.container
    project = container.state.get_project_by_root(str(harness.repository_root.resolve()))
    assert project is not None
    selected = container.model_profiles.store.get_selection(project.project_id)
    assert selected is not None and selected.default_profile == profile_name
    profile = container.model_profiles.store.get_profile(profile_name)
    assert profile is not None and profile.revision == 1
    assert profile.configuration.runtime_name == runtime
    assert profile.configuration.provider_model == model

    info = container.repository.inspect(harness.repository_root)
    now = datetime.now(UTC)
    run_id = container.state.ids.new(IdPrefix.RUN)
    run = Run(
        run_id=run_id,
        project_id=project.project_id,
        correlation_id=container.state.ids.new(IdPrefix.CORRELATION),
        goal="persist exact offline-selected bindings",
        base_revision=info.head_revision,
        target_status_fingerprint=info.status_fingerprint,
        runtime_name=runtime,
        provider_model=model,
        credential_ref=reference,
        status=RunStatus.CREATED,
        created_at=now,
        updated_at=now,
    )
    container.state.create_run(run)
    resolved = container.model_profiles.resolve(
        project,
        root_run_id=run_id,
        roles=SELECTION_ROLES,
        legacy_configuration=profile.configuration,
    )
    container.model_profiles.save_bindings(resolved)
    restored = container.model_profiles.for_run(
        project,
        root_run_id=run_id,
        expected_sha256=resolved.bindings_sha256,
        required_roles=SELECTION_ROLES,
    )
    assert restored == resolved
    assert all(
        binding.profile_name == profile_name
        and binding.profile_revision == 1
        and binding.configuration.runtime_name == runtime
        and binding.configuration.provider_model == model
        for binding in restored.roles.values()
    )
    assert SELECTION_ENV not in json.dumps(restored.safe_projection())


@pytest.mark.asyncio
async def test_mixed_public_profiles_admit_complete_default_fleet_workflow_offline(
    harness: FleetHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selection, setup = _configure_mixed_profiles(
        harness,
        monkeypatch,
        complete_role_closure=True,
    )
    initialized_roles = _initialized_roles(harness)
    assert initialized_roles == CANARY_INITIALIZED_ROLES
    assert setup.default_profile == setup.primary_profiles["cos"]
    assert setup.selection_revision == 4

    project = harness.container.model_profiles.project(harness.repository_root)
    persisted = harness.container.model_profiles.store.get_selection(project.project_id)
    assert persisted is not None
    assert persisted.revision == 4
    assert persisted.default_profile == setup.primary_profiles["cos"]
    assert persisted.role_overrides == setup.primary_profiles

    trace = _install_offline_selected_runtimes(harness)
    original_source = (harness.repository_root / "src/canary_calc/core.py").read_bytes()
    assert pydantic_ai_models.ALLOW_MODEL_REQUESTS is False
    run = await harness.container.workflow.start(
        project_path=harness.repository_root,
        goal="Exercise mixed canary profile admission without a live provider",
        runtime_name=None,
        sandbox_name=None,
        fake_scenario=None,
        budget_limits=RunBudgetLimits.model_validate(ROOT_LIMITS),
    )

    assert run.status is RunStatus.READY_FOR_REVIEW
    assert run.verified_complete is False
    assert run.model_bindings_sha256 is not None
    bindings = harness.container.model_profiles.for_run(
        project,
        root_run_id=run.run_id,
        expected_sha256=run.model_bindings_sha256,
        required_roles=initialized_roles,
    )
    assert bindings.selection_revision == 4
    assert tuple(sorted(bindings.roles)) == initialized_roles
    for role, binding in bindings.roles.items():
        selected = selection.roles.get(role, selection.cos)
        expected_profile = setup.primary_profiles.get(role, setup.default_profile)
        assert expected_profile is not None
        assert binding.profile_name == expected_profile
        assert binding.profile_revision == 1
        assert binding.source == ("override" if role in selection.roles else "default")
        assert binding.configuration == selected.configuration()

    assert [(role, configuration.runtime_name) for role, configuration in trace] == [
        ("cos", "pydantic-ai"),
        ("engineer", "openai-agents"),
        ("verifier", "langgraph"),
    ]
    assert {role for role, _ in trace} == set(SELECTION_ROLES)
    status = harness.container.inspection.status(run.run_id)
    budget = cast(dict[str, object], status["runtime_budget"])
    assert budget["limits"] == ROOT_LIMITS
    assert (harness.repository_root / "src/canary_calc/core.py").read_bytes() == original_source
    assert not harness.container.state.outstanding_leases(run.run_id)


@pytest.mark.asyncio
async def test_mixed_role_overrides_without_default_fail_real_workflow_admission(
    harness: FleetHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, setup = _configure_mixed_profiles(
        harness,
        monkeypatch,
        complete_role_closure=False,
    )
    initialized_roles = _initialized_roles(harness)
    assert initialized_roles == CANARY_INITIALIZED_ROLES
    assert setup.default_profile is None
    assert setup.selection_revision == 3

    project = harness.container.model_profiles.project(harness.repository_root)
    persisted = harness.container.model_profiles.store.get_selection(project.project_id)
    assert persisted is not None
    assert persisted.revision == 3
    assert persisted.default_profile is None
    assert persisted.role_overrides == setup.primary_profiles
    trace = _install_offline_selected_runtimes(harness)

    with pytest.raises(FleetError) as caught:
        await harness.container.workflow.start(
            project_path=harness.repository_root,
            goal="Reject an incomplete mixed canary role selection",
            runtime_name=None,
            sandbox_name=None,
            fake_scenario=None,
            budget_limits=RunBudgetLimits.model_validate(ROOT_LIMITS),
        )
    assert caught.value.code is ErrorCode.CONFIG_INVALID
    assert trace == []
    with sqlite3.connect(harness.container.state.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM run_model_bindings").fetchone()[0] == 0
    assert not harness.container.state.outstanding_leases()
