"""Typed, stable Agent Fleet errors."""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    CONFIG_INVALID = "CONFIG_INVALID"
    PROJECT_NOT_GIT = "PROJECT_NOT_GIT"
    PROJECT_NOT_INITIALIZED = "PROJECT_NOT_INITIALIZED"
    PROJECT_DIRTY = "PROJECT_DIRTY"
    RUNTIME_UNAVAILABLE = "RUNTIME_UNAVAILABLE"
    RUNTIME_CAPABILITY_MISSING = "RUNTIME_CAPABILITY_MISSING"
    RUNTIME_OUTPUT_INVALID = "RUNTIME_OUTPUT_INVALID"
    RUNTIME_TIMEOUT = "RUNTIME_TIMEOUT"
    RUNTIME_RETRY_EXHAUSTED = "RUNTIME_RETRY_EXHAUSTED"
    RUNTIME_BUDGET_EXCEEDED = "RUNTIME_BUDGET_EXCEEDED"
    PROVIDER_UNSUPPORTED = "PROVIDER_UNSUPPORTED"
    PROVIDER_FAILED = "PROVIDER_FAILED"
    CREDENTIAL_INVALID = "CREDENTIAL_INVALID"
    CREDENTIAL_MISSING = "CREDENTIAL_MISSING"
    SANDBOX_UNAVAILABLE = "SANDBOX_UNAVAILABLE"
    SANDBOX_CAPABILITY_MISSING = "SANDBOX_CAPABILITY_MISSING"
    SANDBOX_CREATION_FAILED = "SANDBOX_CREATION_FAILED"
    SANDBOX_INSPECTION_FAILED = "SANDBOX_INSPECTION_FAILED"
    SANDBOX_EXECUTION_FAILED = "SANDBOX_EXECUTION_FAILED"
    SANDBOX_TIMEOUT = "SANDBOX_TIMEOUT"
    SANDBOX_OUTPUT_LIMIT = "SANDBOX_OUTPUT_LIMIT"
    SANDBOX_CLEANUP_FAILED = "SANDBOX_CLEANUP_FAILED"
    SANDBOX_REMOTE_DAEMON_DENIED = "SANDBOX_REMOTE_DAEMON_DENIED"
    SANDBOX_IMAGE_UNAVAILABLE = "SANDBOX_IMAGE_UNAVAILABLE"
    UNSAFE_LOCAL_CONFIRMATION_REQUIRED = "UNSAFE_LOCAL_CONFIRMATION_REQUIRED"
    COMMAND_NOT_REVIEWED = "COMMAND_NOT_REVIEWED"
    COMMAND_OUTCOME_AMBIGUOUS = "COMMAND_OUTCOME_AMBIGUOUS"
    BOOTSTRAP_CANARY_FAILED = "BOOTSTRAP_CANARY_FAILED"
    BOOTSTRAP_REPORT_INVALID = "BOOTSTRAP_REPORT_INVALID"
    BOOTSTRAP_TARGET_DRIFTED = "BOOTSTRAP_TARGET_DRIFTED"
    COMMAND_DENIED = "COMMAND_DENIED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    APPROVAL_DENIED = "APPROVAL_DENIED"
    APPROVAL_INVALID = "APPROVAL_INVALID"
    PATH_OUTSIDE_SCOPE = "PATH_OUTSIDE_SCOPE"
    WORKFLOW_INVALID_TRANSITION = "WORKFLOW_INVALID_TRANSITION"
    PATCH_TARGET_DIVERGED = "PATCH_TARGET_DIVERGED"
    ARTIFACT_INTEGRITY_FAILED = "ARTIFACT_INTEGRITY_FAILED"
    STATE_SCHEMA_INCOMPATIBLE = "STATE_SCHEMA_INCOMPATIBLE"
    STATE_UNAVAILABLE = "STATE_UNAVAILABLE"
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class FleetError(Exception):
    """A user-actionable failure with a stable machine code."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        remediation: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.remediation = remediation
        self.details = details or {}


class GraphOwnershipUnavailableError(FleetError):
    """A caller acquired no graph authority and must not mutate its parent."""

    def __init__(self) -> None:
        super().__init__(
            ErrorCode.RECOVERY_REQUIRED,
            "Adaptive graph execution ownership is unavailable.",
            "Inspect the parent graph; do not interrupt another owner or replay uncertain work.",
        )


class ApprovalRequiredError(FleetError):
    def __init__(self, request_id: str) -> None:
        super().__init__(
            ErrorCode.APPROVAL_REQUIRED,
            f"Run paused for approval request {request_id}.",
            f"Run `fleet approve {request_id} --once` or `fleet deny {request_id}`.",
            details={"request_id": request_id},
        )
        self.request_id = request_id


class ApprovalDeniedError(FleetError):
    def __init__(self, request_id: str) -> None:
        super().__init__(
            ErrorCode.APPROVAL_DENIED,
            f"Approval request {request_id} was denied.",
            "Inspect the run logs and start a new run with a different bounded approach.",
            details={"request_id": request_id},
        )
