"""User-controller-only baseline persistence; never an agent tool capability."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from agent_fleet.domain.baseline import (
    BaselineAuthorization,
    BaselineCommandObservation,
    BaselineExecution,
    BaselineObservationRef,
    BaselineReportRef,
    BaselineReview,
)
from agent_fleet.domain.baseline_resources import (
    BaselineCleanupClaim,
    BaselineCleanupReceipt,
    BaselineDispatchClaim,
    BaselineExecRequest,
    BaselineExecutionHandle,
    BaselineOwnerClaim,
    BaselineResourceLease,
    BaselineResourceSnapshot,
    BaselineSandboxHandle,
    BaselineShow,
    BaselineStoppedOwnerReview,
    BaselineWorkspace,
)
from agent_fleet.domain.session_review import BaselineSessionBinding


@dataclass(frozen=True)
class BaselineSessionAdmission:
    """Trusted controller callback: RAM only, run inside the claim transaction."""

    binding: BaselineSessionBinding
    validate_selection: Callable[[], None]


class BaselineStore(Protocol):
    def create_review(self, review: BaselineReview) -> BaselineExecution: ...
    def review(self, review_id: str) -> BaselineReview: ...
    def authorize(
        self,
        review_id: str,
        review_sha256: str,
        *,
        session: BaselineSessionAdmission | None = None,
    ) -> BaselineAuthorization: ...
    def revoke(self, review_id: str) -> BaselineExecution: ...
    def show(self, identity: str) -> BaselineShow: ...
    def claim_baseline(
        self,
        review_id: str,
        review_sha256: str,
        authorization_id: str,
        expected_revision: int,
        *,
        session: BaselineSessionAdmission | None = None,
    ) -> BaselineOwnerClaim: ...
    def owner_claim(self, baseline_id: str) -> BaselineOwnerClaim: ...
    def reserve_baseline_lease(
        self, claim: BaselineOwnerClaim, lease: BaselineResourceLease
    ) -> BaselineResourceLease: ...
    def activate_baseline_lease(
        self,
        claim: BaselineOwnerClaim,
        lease_id: str,
        expected_revision: int,
        resource: BaselineWorkspace | BaselineSandboxHandle,
    ) -> BaselineResourceLease: ...
    def claim_baseline_dispatch(
        self,
        claim: BaselineOwnerClaim,
        expected_snapshot_sha256: str,
        request: BaselineExecRequest,
        lease: BaselineResourceLease,
    ) -> BaselineDispatchClaim: ...
    def mark_baseline_creation_dispatched(
        self, claim: BaselineOwnerClaim, lease_id: str, expected_revision: int
    ) -> BaselineResourceLease: ...
    def activate_baseline_execution(
        self,
        claim: BaselineOwnerClaim,
        lease_id: str,
        expected_revision: int,
        handle: BaselineExecutionHandle,
    ) -> BaselineResourceLease: ...
    def baseline_resource_snapshot(self, baseline_id: str) -> BaselineResourceSnapshot: ...
    def begin_baseline_cleanup(
        self, claim: BaselineOwnerClaim, expected: BaselineResourceSnapshot
    ) -> BaselineCleanupClaim: ...
    def claim_baseline_cleanup(
        self, expected: BaselineResourceSnapshot, stopped_owner: BaselineStoppedOwnerReview
    ) -> BaselineCleanupClaim: ...
    def validate_cleanup(self, claim: BaselineCleanupClaim) -> BaselineResourceSnapshot: ...
    def finalize_baseline_lease(
        self,
        cleanup_claim: BaselineCleanupClaim,
        lease_id: str,
        expected_revision: int,
        receipt: BaselineCleanupReceipt,
    ) -> BaselineResourceLease: ...
    def record_command_observation(
        self, claim: BaselineOwnerClaim, expected_revision: int, canonical_utf8: bytes
    ) -> BaselineObservationRef: ...
    def observation(self, baseline_id: str) -> BaselineCommandObservation | None: ...
    def publish_baseline_report(
        self, cleanup_claim: BaselineCleanupClaim, expected_revision: int, canonical_utf8: bytes
    ) -> BaselineReportRef: ...
