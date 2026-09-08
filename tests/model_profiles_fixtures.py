"""Model-profile fixtures use real persistence and guarded adapter preflight offline."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent_fleet.adapters.persistence.model_profiles import SqliteModelProfileStore
from agent_fleet.adapters.persistence.sqlite import SUPPORTED_SCHEMA_VERSION, SqliteStateStore
from agent_fleet.adapters.repository.git import GitRepositoryAdapter
from agent_fleet.adapters.runtime.fake import FakeRuntimeAdapter
from agent_fleet.adapters.runtime.pydantic_ai import PydanticAIRuntimeAdapter
from agent_fleet.adapters.secrets.environment import EnvironmentSecretStore
from agent_fleet.adapters.system import SystemClock, UuidIdGenerator
from agent_fleet.application.model_profiles import ModelProfileService
from agent_fleet.application.runtime import RuntimeRegistry
from agent_fleet.domain.ids import IdPrefix
from agent_fleet.domain.model_profiles import ModelProfile, RunModelBindings
from agent_fleet.domain.models import Project, Run, RuntimeConfiguration
from agent_fleet.domain.security import Redactor


def model_configuration(
    model: str = "openai:fixture-model", reference: str = "env:FIXTURE_KEY"
) -> RuntimeConfiguration:
    return RuntimeConfiguration(
        runtime_name="pydantic-ai", provider_model=model, credential_ref=reference
    )


@dataclass
class ProfileHarness:
    state: SqliteStateStore
    store: SqliteModelProfileStore
    service: ModelProfileService
    project: Project
    environment: dict[str, str]

    def add(self, name: str, configuration: RuntimeConfiguration | None = None) -> ModelProfile:
        profile = ModelProfile(
            name=name, revision=1, configuration=configuration or RuntimeConfiguration()
        )
        self.store.save_profile(profile, expected_revision=0)
        return profile

    def run(self) -> Run:
        now = self.state.clock.now()
        run = Run(
            run_id=self.state.ids.new(IdPrefix.RUN),
            project_id=self.project.project_id,
            correlation_id=self.state.ids.new(IdPrefix.CORRELATION),
            goal="Explain the fixture",
            base_revision="a" * 40,
            target_status_fingerprint="3" * 64,
            created_at=now,
            updated_at=now,
        )
        self.state.create_run(run)
        return run

    def resolve(self, run: Run | None = None) -> RunModelBindings:
        return self.service.resolve(
            self.project,
            root_run_id=(run or self.run()).run_id,
            roles=("cos", "engineer", "verifier"),
            legacy_configuration=RuntimeConfiguration(),
        )

    def reopen(self) -> SqliteModelProfileStore:
        return SqliteModelProfileStore(self.state)


def make_profile_harness(tmp_path: Path, *, real_repository: bool = False) -> ProfileHarness:
    state_root = tmp_path / "state"
    clock, ids, redactor = SystemClock(), UuidIdGenerator(), Redactor()
    state = SqliteStateStore(state_root / "state.db", clock, ids, redactor)
    assert state.migrate() == SUPPORTED_SCHEMA_VERSION
    repository = GitRepositoryAdapter(state_root, ids)
    root = tmp_path / "project"
    info = None
    if real_repository:
        GitRepositoryAdapter(tmp_path, ids).create_canary_fixture(root)
        info = repository.inspect(root)
    now = clock.now()
    project = Project(
        project_id=ids.new(IdPrefix.PROJECT),
        canonical_root=info.root if info else str(root),
        identity_hash=info.identity_hash if info else "1" * 64,
        fleet_spec_hash="2" * 64,
        created_at=now,
        updated_at=now,
    )
    state.save_project(project)
    store = SqliteModelProfileStore(state)
    environment: dict[str, str] = {}
    secrets = EnvironmentSecretStore(redactor, environment)
    runtimes = RuntimeRegistry(
        {
            "fake": FakeRuntimeAdapter(),
            "pydantic-ai": PydanticAIRuntimeAdapter(secrets, redactor),
        }
    )
    service = ModelProfileService(
        store=store,
        state=state,
        repository=repository,
        runtimes=runtimes,
        secrets=secrets,
        redactor=redactor,
        clock=clock,
    )
    return ProfileHarness(state, store, service, project, environment)
