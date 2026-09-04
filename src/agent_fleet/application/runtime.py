"""Application-owned runtime selection and capability preflight."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import (
    RuntimeCapability,
    RuntimeConfiguration,
    RuntimeCredentialCheck,
    RuntimeCredentialStatus,
    RuntimePreflight,
)
from agent_fleet.ports.runtime import RuntimeAdapter


class RuntimeRegistry:
    """Select adapters by exact name without implicit fallback or provider inference."""

    def __init__(self, adapters: Mapping[str, RuntimeAdapter]) -> None:
        if not adapters:
            raise ValueError("at least one runtime adapter must be registered")
        self._adapters = dict(adapters)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._adapters))

    def get(self, runtime_name: str) -> RuntimeAdapter:
        adapter = self._adapters.get(runtime_name)
        if adapter is None:
            raise FleetError(
                ErrorCode.RUNTIME_UNAVAILABLE,
                f"Runtime {runtime_name!r} is not registered.",
                f"Select one of the available runtimes: {', '.join(self.names)}.",
                details={"runtime": runtime_name, "available_runtimes": list(self.names)},
            )
        return adapter

    def inspect(
        self,
        configuration: RuntimeConfiguration,
        *,
        required_capabilities: Iterable[RuntimeCapability],
        credential_check: RuntimeCredentialCheck,
    ) -> RuntimePreflight:
        adapter = self.get(configuration.runtime_name)
        required = frozenset(required_capabilities)
        missing = required - adapter.capabilities
        if missing:
            return RuntimePreflight(
                runtime_name=configuration.runtime_name,
                ready=False,
                capabilities=adapter.capabilities,
                credential_status=RuntimeCredentialStatus.NOT_CHECKED,
                diagnostic=(
                    "Runtime is missing required capabilities: "
                    + ", ".join(sorted(item.value for item in missing))
                ),
            )
        return adapter.preflight(
            configuration,
            credential_check=credential_check,
        )

    def require(
        self,
        configuration: RuntimeConfiguration,
        *,
        required_capabilities: Iterable[RuntimeCapability],
        credential_check: RuntimeCredentialCheck,
    ) -> RuntimeAdapter:
        adapter = self.get(configuration.runtime_name)
        required = frozenset(required_capabilities)
        missing = required - adapter.capabilities
        if missing:
            missing_values = sorted(item.value for item in missing)
            raise FleetError(
                ErrorCode.RUNTIME_CAPABILITY_MISSING,
                "The selected runtime does not satisfy the FleetSpec capability contract.",
                "Select a compatible runtime or review the requested runtime capabilities.",
                details={
                    "runtime": configuration.runtime_name,
                    "missing_capabilities": missing_values,
                },
            )
        preflight = adapter.preflight(
            configuration,
            credential_check=credential_check,
        )
        if preflight.ready:
            return adapter
        if preflight.credential_status is RuntimeCredentialStatus.MISSING:
            code = ErrorCode.CREDENTIAL_MISSING
        elif preflight.credential_status is RuntimeCredentialStatus.INVALID:
            code = ErrorCode.CREDENTIAL_INVALID
        else:
            code = ErrorCode.RUNTIME_UNAVAILABLE
        raise FleetError(
            code,
            preflight.diagnostic,
            (
                "Provide a valid explicit runtime/model/credential reference and retry; "
                "Fleet did not contact a provider."
            ),
            details={
                "runtime": configuration.runtime_name,
                "credential_status": preflight.credential_status.value,
            },
        )
