"""Application-owned exact sandbox selection and capability matching."""

from __future__ import annotations

from collections.abc import Mapping

from agent_fleet.domain.config import SandboxRequest
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import (
    SandboxCapabilities,
    SandboxConfiguration,
    SandboxPreflight,
    SandboxRequirements,
)
from agent_fleet.domain.security import canonical_json_hash
from agent_fleet.ports.baseline_resources import BaselineSandboxProvider
from agent_fleet.ports.sandbox import SandboxProvider


class SandboxRegistry:
    """Select sandbox providers by exact name without implicit fallback."""

    def __init__(
        self,
        providers: Mapping[str, SandboxProvider],
        *,
        baseline_providers: Mapping[str, BaselineSandboxProvider] | None = None,
    ) -> None:
        if not providers:
            raise ValueError("at least one sandbox provider must be registered")
        self._providers = dict(providers)
        self._baseline_providers = dict(baseline_providers or {})
        for name, baseline in self._baseline_providers.items():
            if name != "docker" or id(self._providers.get(name)) != id(baseline):
                raise ValueError("baseline capability must explicitly bind the same Docker adapter")
        for name, provider in self._providers.items():
            if name != provider.capabilities.provider:
                raise ValueError(
                    f"sandbox registry key {name!r} does not match provider capability identity"
                )

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._providers))

    def require_baseline(
        self, configuration: SandboxConfiguration, requirements: SandboxRequirements
    ) -> BaselineSandboxProvider:
        from agent_fleet.domain.baseline import validate_configuration

        try:
            validate_configuration(configuration)
        except ValueError:
            raise FleetError(
                ErrorCode.SANDBOX_CAPABILITY_MISSING,
                "Baseline execution requires its bounded read-only Docker capability.",
                "Review explicit isolated prerequisites; there is no unsafe or fake fallback.",
            ) from None
        ordinary = self.require(configuration, requirements)
        selected = self._baseline_providers.get(configuration.provider)
        if (
            selected is None
            or id(ordinary) != id(selected)
            or not isinstance(selected, BaselineSandboxProvider)
        ):
            raise FleetError(
                ErrorCode.SANDBOX_CAPABILITY_MISSING,
                "The exact Docker baseline capability is not registered.",
                "Use the model-free baseline composition before approving any command.",
            )
        return selected

    def get(self, provider_name: str) -> SandboxProvider:
        provider = self._providers.get(provider_name)
        if provider is None:
            raise FleetError(
                ErrorCode.SANDBOX_UNAVAILABLE,
                f"Sandbox provider {provider_name!r} is not registered.",
                f"Select one of the available sandboxes: {', '.join(self.names)}.",
                details={
                    "sandbox": provider_name,
                    "available_sandboxes": list(self.names),
                },
            )
        return provider

    def require(
        self,
        configuration: SandboxConfiguration,
        requirements: SandboxRequirements,
    ) -> SandboxProvider:
        provider = self.get(configuration.provider)
        missing = missing_requirements(provider.capabilities, requirements)
        if missing:
            raise FleetError(
                ErrorCode.SANDBOX_CAPABILITY_MISSING,
                "The selected sandbox does not satisfy the reviewed execution requirements.",
                "Select a sandbox with the required isolation capabilities or review the task.",
                details={
                    "sandbox": configuration.provider,
                    "missing_capabilities": missing,
                    "network_mode": requirements.network_mode,
                },
            )
        if configuration.network_mode not in provider.capabilities.supported_network_modes:
            raise FleetError(
                ErrorCode.SANDBOX_CAPABILITY_MISSING,
                "The selected sandbox does not support the configured network mode.",
                "Use the reviewed supported network mode. A different protected setup "
                "requires a separate registration with the existing project/state preserved.",
                details={
                    "sandbox": configuration.provider,
                    "network_mode": configuration.network_mode,
                },
            )
        return provider

    async def preflight(
        self,
        configuration: SandboxConfiguration,
        requirements: SandboxRequirements,
    ) -> SandboxPreflight:
        provider = self.require(configuration, requirements)
        result = await provider.preflight(configuration, requirements)
        expected_configuration_hash = canonical_json_hash(configuration.model_dump(mode="json"))
        expected_requirements_hash = canonical_json_hash(requirements.model_dump(mode="json"))
        if (
            not result.ready
            or result.provider != configuration.provider
            or result.capabilities != provider.capabilities
            or result.configuration_hash != expected_configuration_hash
            or result.requirements_hash != expected_requirements_hash
        ):
            raise FleetError(
                ErrorCode.SANDBOX_UNAVAILABLE,
                "The sandbox provider returned an invalid preflight result.",
                "Inspect the selected provider and retry without executing project code.",
                details={"sandbox": configuration.provider},
            )
        return result


def requirements_for_configuration(
    configuration: SandboxConfiguration,
) -> SandboxRequirements:
    if configuration.provider == "docker":
        return SandboxRequirements(
            isolation_required=True,
            code_execution_required=True,
            resource_limits_required=True,
            non_root_required=True,
            read_only_root_required=True,
            no_new_privileges_required=True,
            capability_drop_required=True,
            network_mode=configuration.network_mode,
        )
    if configuration.provider == "local-unsafe":
        return SandboxRequirements(
            code_execution_required=True,
            network_mode=configuration.network_mode,
        )
    return SandboxRequirements(network_mode=configuration.network_mode)


def configuration_from_request(request: SandboxRequest) -> SandboxConfiguration:
    return SandboxConfiguration(
        provider=request.provider,
        network_mode=request.network_mode,
        image=request.image,
        cpu_limit=request.cpu_limit,
        memory_mb=request.memory_mb,
        pids_limit=request.pids_limit,
        shm_mb=request.shm_mb,
        tmpfs_mb=request.tmpfs_mb,
    )


def missing_requirements(
    capabilities: SandboxCapabilities,
    requirements: SandboxRequirements,
) -> list[str]:
    checks = {
        "isolation": (requirements.isolation_required, capabilities.isolation_enforced),
        "code_execution": (
            requirements.code_execution_required,
            capabilities.executes_code,
        ),
        "resource_limits": (
            requirements.resource_limits_required,
            capabilities.supports_resource_limits,
        ),
        "non_root": (requirements.non_root_required, capabilities.supports_non_root),
        "read_only_root": (
            requirements.read_only_root_required,
            capabilities.supports_read_only_root,
        ),
        "no_new_privileges": (
            requirements.no_new_privileges_required,
            capabilities.supports_no_new_privileges,
        ),
        "capability_drop": (
            requirements.capability_drop_required,
            capabilities.supports_capability_drop,
        ),
        f"network:{requirements.network_mode}": (
            True,
            requirements.network_mode in capabilities.supported_network_modes,
        ),
    }
    return sorted(name for name, (required, present) in checks.items() if required and not present)
