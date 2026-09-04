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
    SANDBOX_UNAVAILABLE = "SANDBOX_UNAVAILABLE"
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
