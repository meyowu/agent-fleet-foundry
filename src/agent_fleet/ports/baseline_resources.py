"""Trusted additive resource ports for the separate baseline controller."""

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from agent_fleet.domain.baseline import BaselineReview, BaselineSourceManifest
from agent_fleet.domain.baseline_resources import (
    BaselineCommandScope,
    BaselineExecRequest,
    BaselineExecResult,
    BaselineExecutionHandle,
    BaselineExecutionRecoveryRequest,
    BaselineResourceOwner,
    BaselineSandboxHandle,
    BaselineSandboxInspection,
    BaselineSandboxSpec,
    BaselineWorkspace,
)
from agent_fleet.domain.models import (
    PermissionDecision,
    SandboxCapabilities,
    SandboxCleanupResult,
    SandboxConfiguration,
    SandboxPreflight,
    SandboxRequirements,
)
from agent_fleet.ports.baseline import BaselineStore


@runtime_checkable
class BaselineRepositoryPort(Protocol):
    def baseline_source_manifest(self, root: Path, commit: str) -> BaselineSourceManifest: ...

    def prepare_baseline_workspace(
        self, owner: BaselineResourceOwner, base_revision: str, *, approved_source_sha256: str
    ) -> BaselineWorkspace: ...

    def materialize_baseline_workspace(
        self, root: Path, workspace: BaselineWorkspace
    ) -> BaselineWorkspace: ...

    def baseline_workspace_fingerprint(self, workspace: BaselineWorkspace) -> str: ...

    def cleanup_baseline_workspace(self, root: Path, workspace: BaselineWorkspace) -> None: ...


@runtime_checkable
class BaselineSandboxProvider(Protocol):
    @property
    def capabilities(self) -> SandboxCapabilities: ...

    async def preflight(
        self, configuration: SandboxConfiguration, requirements: SandboxRequirements
    ) -> SandboxPreflight: ...

    async def create_baseline(
        self, spec: BaselineSandboxSpec, *, sandbox_id: str
    ) -> BaselineSandboxHandle: ...

    async def inspect_baseline(
        self, handle: BaselineSandboxHandle
    ) -> BaselineSandboxInspection: ...

    async def exec_baseline(
        self,
        handle: BaselineSandboxHandle,
        request: BaselineExecRequest,
        *,
        on_creation_dispatched: Callable[[], None],
        on_resource_created: Callable[[BaselineExecutionHandle], None],
    ) -> BaselineExecResult: ...

    async def cleanup_baseline_execution(
        self, handle: BaselineExecutionHandle
    ) -> SandboxCleanupResult: ...

    async def reconcile_baseline_execution(
        self, sandbox: BaselineSandboxHandle, request: BaselineExecutionRecoveryRequest
    ) -> SandboxCleanupResult: ...

    async def terminate_baseline(self, handle: BaselineSandboxHandle) -> SandboxCleanupResult: ...


@runtime_checkable
class BaselineCommandBroker(Protocol):
    def evaluate_baseline(
        self, scope: BaselineCommandScope, sandbox: SandboxCapabilities
    ) -> PermissionDecision: ...


class BaselineAdmissionGuard(Protocol):
    def assert_current(self) -> None: ...


@dataclass(frozen=True)
class BaselineResourceDependencies:
    store: BaselineStore
    repository: BaselineRepositoryPort


@dataclass(frozen=True)
class BaselineGatewayDependencies:
    store: BaselineStore
    repository: BaselineRepositoryPort
    guard: Callable[[BaselineReview], AbstractContextManager[BaselineAdmissionGuard]]
