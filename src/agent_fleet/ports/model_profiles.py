"""Trusted profile persistence; no provider or repository-controlled settings."""

from typing import Protocol

from agent_fleet.domain.model_profiles import (
    ModelConfigurationAudit,
    ModelProfile,
    ProjectModelSelection,
    RunModelBindings,
)


class ModelProfileStore(Protocol):
    def get_profile(self, name: str) -> ModelProfile | None: ...

    def profile_revision(self, name: str) -> int: ...

    def list_profiles(self) -> tuple[ModelProfile, ...]: ...

    def save_profile(self, profile: ModelProfile, *, expected_revision: int) -> None: ...

    def remove_profile(self, name: str, *, expected_revision: int) -> int: ...

    def get_selection(self, project_id: str) -> ProjectModelSelection | None: ...

    def save_selection(
        self, selection: ProjectModelSelection, *, expected_revision: int
    ) -> None: ...

    def save_bindings(self, bindings: RunModelBindings) -> None: ...

    def get_bindings(self, project_id: str, root_run_id: str) -> RunModelBindings | None: ...

    def list_audit(
        self, *, after_sequence: int = 0, limit: int = 100
    ) -> tuple[ModelConfigurationAudit, ...]: ...
