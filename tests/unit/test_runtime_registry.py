from __future__ import annotations

from typing import cast

import pytest

from agent_fleet.application.runtime import RuntimeRegistry
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import (
    RuntimeCapability,
    RuntimeConfiguration,
    RuntimeCredentialCheck,
    RuntimeCredentialStatus,
    RuntimePreflight,
)
from agent_fleet.ports.runtime import RuntimeAdapter


class StubRuntime:
    def __init__(
        self,
        capabilities: frozenset[RuntimeCapability],
        preflight: RuntimePreflight,
    ) -> None:
        self._capabilities = capabilities
        self._preflight = preflight
        self.preflight_calls: list[RuntimeCredentialCheck] = []

    @property
    def capabilities(self) -> frozenset[RuntimeCapability]:
        return self._capabilities

    def preflight(
        self,
        configuration: RuntimeConfiguration,
        *,
        credential_check: RuntimeCredentialCheck,
    ) -> RuntimePreflight:
        del configuration
        self.preflight_calls.append(credential_check)
        return self._preflight


def _registry(runtime: StubRuntime) -> RuntimeRegistry:
    # Invoke is irrelevant to selection tests; the cast keeps this stub deliberately narrow.
    return RuntimeRegistry({"fake": cast(RuntimeAdapter, runtime)})


def test_missing_capability_fails_before_adapter_preflight() -> None:
    runtime = StubRuntime(
        frozenset({RuntimeCapability.STRUCTURED_OUTPUT}),
        RuntimePreflight(
            runtime_name="fake",
            ready=True,
            capabilities=frozenset({RuntimeCapability.STRUCTURED_OUTPUT}),
            credential_status=RuntimeCredentialStatus.NOT_REQUIRED,
            diagnostic="Fake runtime is ready.",
        ),
    )

    with pytest.raises(FleetError) as captured:
        _registry(runtime).require(
            RuntimeConfiguration(),
            required_capabilities={
                RuntimeCapability.STRUCTURED_OUTPUT,
                RuntimeCapability.TOOL_CALLING,
            },
            credential_check=RuntimeCredentialCheck.RESOLVE,
        )

    assert captured.value.code is ErrorCode.RUNTIME_CAPABILITY_MISSING
    assert runtime.preflight_calls == []


def test_missing_credential_maps_to_stable_error() -> None:
    capabilities = frozenset({RuntimeCapability.STRUCTURED_OUTPUT, RuntimeCapability.TOOL_CALLING})
    runtime = StubRuntime(
        capabilities,
        RuntimePreflight(
            runtime_name="fake",
            ready=False,
            capabilities=capabilities,
            credential_status=RuntimeCredentialStatus.MISSING,
            diagnostic="The selected credential is not configured.",
        ),
    )

    with pytest.raises(FleetError) as captured:
        _registry(runtime).require(
            RuntimeConfiguration(),
            required_capabilities=capabilities,
            credential_check=RuntimeCredentialCheck.RESOLVE,
        )

    assert captured.value.code is ErrorCode.CREDENTIAL_MISSING
    assert captured.value.details == {
        "runtime": "fake",
        "credential_status": "missing",
    }
    assert runtime.preflight_calls == [RuntimeCredentialCheck.RESOLVE]


def test_unknown_runtime_never_falls_back() -> None:
    capabilities = frozenset({RuntimeCapability.STRUCTURED_OUTPUT, RuntimeCapability.TOOL_CALLING})
    runtime = StubRuntime(
        capabilities,
        RuntimePreflight(
            runtime_name="fake",
            ready=True,
            capabilities=capabilities,
            credential_status=RuntimeCredentialStatus.NOT_REQUIRED,
            diagnostic="Fake runtime is ready.",
        ),
    )

    with pytest.raises(FleetError) as captured:
        _registry(runtime).get("missing")

    assert captured.value.code is ErrorCode.RUNTIME_UNAVAILABLE
    assert runtime.preflight_calls == []
