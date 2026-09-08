"""Explicit user model selection, full-role preflight and pinned recovery."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from functools import wraps
from pathlib import Path
from typing import Literal

from pydantic import TypeAdapter, ValidationError

from agent_fleet.application.runtime import RuntimeRegistry
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.model_profiles import (
    ModelProfile,
    ProfileName,
    ProjectModelSelection,
    ResolvedModelBinding,
    RunModelBindings,
    configuration_hash,
)
from agent_fleet.domain.models import (
    Project,
    RoleId,
    RuntimeCapability,
    RuntimeConfiguration,
    RuntimeCredentialCheck,
)
from agent_fleet.domain.security import Redactor
from agent_fleet.ports.clock import Clock
from agent_fleet.ports.model_profiles import ModelProfileStore
from agent_fleet.ports.repository import RepositoryPort
from agent_fleet.ports.secret_store import SecretStatus, SecretStore, SecretStoreError
from agent_fleet.ports.state_store import StateStore

_REQUIRED = frozenset({RuntimeCapability.STRUCTURED_OUTPUT, RuntimeCapability.TOOL_CALLING})
type LiteralSource = Literal["override", "repository_preference", "default"]


def _invalid() -> FleetError:
    return FleetError(
        ErrorCode.CONFIG_INVALID,
        "The model profile or exact project selection is invalid, unavailable or unapproved.",
        "Inspect user-owned profiles and explicitly bind an enabled profile; no fallback was used.",
    )


def _boundary[**Params, Result](operation: Callable[Params, Result]) -> Callable[Params, Result]:
    @wraps(operation)
    def call(*args: Params.args, **kwargs: Params.kwargs) -> Result:
        error: FleetError
        try:
            return operation(*args, **kwargs)
        except FleetError as caught:
            error = caught
        except (ValidationError, ValueError, TypeError, KeyError, UnicodeError):
            error = _invalid()
        except SecretStoreError:
            error = FleetError(
                ErrorCode.CREDENTIAL_INVALID,
                "A selected model credential cannot safely establish redaction.",
                "Restore the explicitly referenced credential before inspecting "
                "or running this selection.",
            )
        error.__context__ = None
        raise error from None

    return call


class ModelProfileService:
    def __init__(
        self,
        *,
        store: ModelProfileStore,
        state: StateStore,
        repository: RepositoryPort,
        runtimes: RuntimeRegistry,
        secrets: SecretStore,
        redactor: Redactor,
        clock: Clock,
    ) -> None:
        self.store = store
        self.state = state
        self.repository = repository
        self.runtimes = runtimes
        self.secrets = secrets
        self.redactor = redactor
        self.clock = clock

    def _clean(self, value: object) -> None:
        if self.redactor.contains_secret_data(value):
            raise _invalid()

    def _register(self, configurations: Sequence[RuntimeConfiguration], *, required: bool) -> None:
        # Resolve every selected reference before inspecting any displayable field.
        # A companion profile's key in another profile name/model must not leak.
        references = sorted(
            {value.credential_ref for value in configurations if value.credential_ref}
        )
        for reference in references:
            status = self.secrets.inspect(reference).status
            if status is SecretStatus.MISSING and not required:
                continue
            if status is SecretStatus.MISSING:
                raise FleetError(
                    ErrorCode.CREDENTIAL_MISSING,
                    "A selected model credential is not configured.",
                    "Configure all explicitly selected references before starting "
                    "or resuming this task.",
                )
            if status is SecretStatus.INVALID:
                raise _invalid()
            self.secrets.resolve(reference)
        for configuration in configurations:
            self._clean(configuration.model_dump(mode="json"))

    def _registered_project(self, project: Project) -> Project:
        current = self.state.get_project(project.project_id)
        if (
            current.identity_hash != project.identity_hash
            or current.canonical_root != project.canonical_root
        ):
            raise _invalid()
        return current

    @_boundary
    def prepare_project(self, project: Project) -> bool:
        """Register approved references before parsing repository-controlled configuration.

        Missing unused aliases do not prevent inspection. The complete effective
        selection is required separately by resolve(), before any Run effect.
        """
        project = self._registered_project(project)
        selection = self.store.get_selection(project.project_id)
        if selection is None:
            self._register(
                [
                    RuntimeConfiguration(
                        runtime_name=project.runtime_name,
                        provider_model=project.provider_model,
                        credential_ref=project.credential_ref,
                    )
                ],
                required=False,
            )
            return False
        profiles = [self.store.get_profile(name) for name in selection.permitted_profiles]
        self._register([item.configuration for item in profiles if item], required=False)
        self._clean(selection.model_dump(mode="json"))
        return True

    @_boundary
    def inspect_bindings(
        self, project: Project, *, root_run_id: str, expected_sha256: str
    ) -> RunModelBindings:
        """Read immutable routing safely without requiring absent credentials or a provider."""
        project = self._registered_project(project)
        bindings = self.store.get_bindings(project.project_id, root_run_id)
        if bindings is None or bindings.bindings_sha256 != expected_sha256:
            raise FleetError(
                ErrorCode.RECOVERY_REQUIRED,
                "The required immutable model binding is missing or inconsistent.",
                "Restore the exact recorded binding before inspecting this task.",
            )
        self._register([item.configuration for item in bindings.roles.values()], required=False)
        self._clean(bindings.model_dump(mode="json"))
        return bindings

    @_boundary
    def project(self, path: Path) -> Project:
        self._clean(str(path))
        info = self.repository.inspect(path)
        project = self.state.get_project_by_root(info.root)
        if project is None:
            raise FleetError(
                ErrorCode.PROJECT_NOT_INITIALIZED,
                "The selected repository is not registered.",
                "Initialize this project explicitly before changing its model selections.",
            )
        if project.identity_hash != info.identity_hash:
            raise _invalid()
        return project

    @_boundary
    def list(self) -> dict[str, object]:
        profiles = self.store.list_profiles()
        self._register([profile.configuration for profile in profiles], required=False)
        result: dict[str, object] = {
            "profiles": [profile.safe_projection() for profile in profiles]
        }
        self._clean(result)
        return result

    @_boundary
    def show(self, name: str) -> dict[str, object]:
        profile = self.store.get_profile(name)
        if profile is None:
            raise _invalid()
        self._register([profile.configuration], required=False)
        result = profile.safe_projection()
        self._clean(result)
        return result

    @_boundary
    def set(
        self,
        name: str,
        *,
        configuration: RuntimeConfiguration,
        expected_revision: int = 0,
        enabled: bool = True,
    ) -> dict[str, object]:
        if type(expected_revision) is not int or expected_revision < 0:
            raise _invalid()
        profile = ModelProfile(
            name=name, revision=expected_revision + 1, enabled=enabled, configuration=configuration
        )
        self._register([configuration], required=False)
        self._clean(profile.model_dump(mode="json"))
        self.runtimes.require(
            configuration,
            required_capabilities=_REQUIRED,
            credential_check=RuntimeCredentialCheck.NONE,
        )
        self.store.save_profile(profile, expected_revision=expected_revision)
        return profile.safe_projection()

    @_boundary
    def remove(self, name: str, *, expected_revision: int) -> dict[str, object]:
        profile = self.store.get_profile(name)
        if profile is None:
            raise _invalid()
        self._register([profile.configuration], required=False)
        self._clean(name)
        revision = self.store.remove_profile(name, expected_revision=expected_revision)
        return {
            "name": name,
            "revision": revision,
            "removed": True,
            "historical_bindings_preserved": True,
        }

    @_boundary
    def selection(self, project: Project) -> dict[str, object]:
        project = self._registered_project(project)
        selection = self.store.get_selection(project.project_id)
        if selection is None:
            return {
                "project_id": project.project_id,
                "revision": 0,
                "mode": "legacy",
                "selection": None,
            }
        profiles = [self.store.get_profile(name) for name in selection.permitted_profiles]
        self._register([profile.configuration for profile in profiles if profile], required=False)
        result = selection.model_dump(mode="json")
        self._clean(result)
        return result

    @_boundary
    def bind(
        self,
        project: Project,
        *,
        expected_revision: int,
        profile: str | None = None,
        role: str | None = None,
        default: bool = False,
        clear: bool = False,
        permit: Sequence[str] = (),
        revoke: Sequence[str] = (),
    ) -> dict[str, object]:
        project = self._registered_project(project)
        if (
            type(expected_revision) is not int
            or expected_revision < 0
            or (role is not None and default)
            or (profile is not None and clear)
            or ((profile is not None or clear) and role is None and not default)
            or ((role is not None or default) and profile is None and not clear)
            or (role is None and not default and not permit and not revoke)
        ):
            raise _invalid()
        if role is not None:
            TypeAdapter(RoleId).validate_python(role)
        for name in (*permit, *revoke, *((profile,) if profile is not None else ())):
            TypeAdapter(ProfileName).validate_python(name)
        if set(permit) & set(revoke):
            raise _invalid()
        current = self.store.get_selection(project.project_id)
        if (current.revision if current else 0) != expected_revision:
            raise _invalid()
        roles = dict(current.role_overrides) if current else {}
        default_profile = current.default_profile if current else None
        allowed = set(current.permitted_profiles) if current else set()
        if role is not None:
            if clear:
                roles.pop(role, None)
            elif profile is not None:
                roles[role] = profile
        if default:
            default_profile = profile
        allowed.update(permit)
        if profile is not None:
            allowed.add(profile)
        allowed.difference_update(revoke)
        profiles = [self.store.get_profile(name) for name in sorted(allowed)]
        self._register([item.configuration for item in profiles if item], required=False)
        selection = ProjectModelSelection(
            project_id=project.project_id,
            repository_identity=project.identity_hash,
            revision=expected_revision + 1,
            default_profile=default_profile,
            role_overrides=roles,
            permitted_profiles=tuple(sorted(allowed)),
        )
        self._clean(selection.model_dump(mode="json"))
        self.store.save_selection(selection, expected_revision=expected_revision)
        return selection.model_dump(mode="json")

    def _preflight(self, bindings: RunModelBindings) -> None:
        configurations = {
            binding.configuration_sha256: binding.configuration
            for binding in bindings.roles.values()
        }
        self._register(list(configurations.values()), required=True)
        self._clean(bindings.model_dump(mode="json"))
        for configuration in configurations.values():
            self.runtimes.require(
                configuration,
                required_capabilities=_REQUIRED,
                credential_check=RuntimeCredentialCheck.RESOLVE,
            )

    @_boundary
    def resolve(
        self,
        project: Project,
        *,
        root_run_id: str,
        roles: Sequence[str],
        repository_preferences: Mapping[str, str] | None = None,
        legacy_configuration: RuntimeConfiguration,
    ) -> RunModelBindings:
        project = self._registered_project(project)
        if not 1 <= len(roles) <= 64 or len(set(roles)) != len(roles) or "cos" not in roles:
            raise _invalid()
        for role in roles:
            TypeAdapter(RoleId).validate_python(role)
        preferences = dict(repository_preferences or {})
        if not set(preferences).issubset(roles):
            raise _invalid()
        for name in preferences.values():
            TypeAdapter(ProfileName).validate_python(name)
        selection = self.store.get_selection(project.project_id)
        resolved: dict[str, ResolvedModelBinding] = {}
        cached: dict[str, ModelProfile] = {}
        for role in roles:
            if selection is None:
                if preferences:
                    raise _invalid()
                binding = ResolvedModelBinding(
                    role_id=role,
                    source="legacy",
                    configuration=legacy_configuration,
                    configuration_sha256=configuration_hash(legacy_configuration),
                )
            else:
                alias = selection.role_overrides.get(role)
                source: LiteralSource = "override"
                if alias is None:
                    alias = preferences.get(role)
                    source = "repository_preference"
                if alias is None:
                    alias = selection.default_profile
                    source = "default"
                if alias is None or alias not in selection.permitted_profiles:
                    raise _invalid()
                selected = cached.get(alias) or self.store.get_profile(alias)
                if selected is None or not selected.enabled:
                    raise _invalid()
                cached[alias] = selected
                binding = ResolvedModelBinding(
                    role_id=role,
                    source=source,
                    profile_name=alias,
                    profile_revision=selected.revision,
                    configuration=selected.configuration,
                    configuration_sha256=selected.configuration_sha256,
                )
            resolved[role] = binding
        bindings = RunModelBindings(
            root_run_id=root_run_id,
            project_id=project.project_id,
            repository_identity=project.identity_hash,
            selection_revision=selection.revision if selection else None,
            created_at=self.clock.now(),
            roles=resolved,
        )
        self._preflight(bindings)
        return bindings

    @_boundary
    def save_bindings(self, bindings: RunModelBindings) -> None:
        bindings = RunModelBindings.model_validate_json(bindings.model_dump_json())
        self._preflight(bindings)
        self.store.save_bindings(bindings)

    @_boundary
    def for_run(
        self,
        project: Project,
        *,
        root_run_id: str,
        expected_sha256: str,
        required_roles: Sequence[str],
    ) -> RunModelBindings:
        project = self._registered_project(project)
        bindings = self.store.get_bindings(project.project_id, root_run_id)
        if (
            bindings is None
            or bindings.bindings_sha256 != expected_sha256
            or bindings.repository_identity != project.identity_hash
            or not required_roles
            or not set(required_roles).issubset(bindings.roles)
        ):
            raise FleetError(
                ErrorCode.RECOVERY_REQUIRED,
                "The required immutable model binding is missing or inconsistent.",
                "Restore its exact recorded binding; current model profiles "
                "are not a recovery fallback.",
            )
        self._preflight(bindings)
        return bindings
