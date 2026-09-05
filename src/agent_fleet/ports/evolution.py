from __future__ import annotations

from typing import Literal, Protocol

from agent_fleet.domain.evolution import (
    FleetPatchProposalRecord,
    OrganizationAdmission,
    OrganizationHead,
    OrganizationOperation,
    OrganizationVersion,
)
from agent_fleet.domain.models import Project
from agent_fleet.domain.organization_tree import (
    OrganizationTree,
    PreparedPublication,
    PublicationObservation,
)
from agent_fleet.domain.repository_boundary import OrganizationRepositoryBoundary


class OrganizationStore(Protocol):
    def get_head(self, project_id: str) -> OrganizationHead | None: ...
    def register_baseline(
        self, project: Project, tree: OrganizationTree, config_snapshot_sha256: str
    ) -> OrganizationHead: ...
    def get_tree(self, tree_sha256: str) -> OrganizationTree: ...
    def save_proposal(
        self, record: FleetPatchProposalRecord, before: OrganizationTree, after: OrganizationTree
    ) -> FleetPatchProposalRecord: ...
    def get_proposal(self, proposal_id: str) -> FleetPatchProposalRecord: ...
    def list_proposals(
        self, project_id: str, *, limit: int = 50
    ) -> tuple[FleetPatchProposalRecord, ...]: ...
    def get_version(self, project_id: str, version: int) -> OrganizationVersion: ...
    def prepare_operation(
        self,
        project: Project,
        proposal_id: str,
        publication: PreparedPublication,
        *,
        authorization: Literal["apply", "rollback"],
        repository_before: OrganizationRepositoryBoundary,
    ) -> OrganizationOperation: ...
    def get_operation(self, operation_id: str) -> OrganizationOperation: ...
    def operation_for_proposal(self, proposal_id: str) -> OrganizationOperation | None: ...
    def commit_operation(
        self, operation_id: str, project: Project, observation: PublicationObservation
    ) -> OrganizationVersion: ...
    def abort_operation(
        self, operation_id: str, observation: PublicationObservation
    ) -> OrganizationOperation: ...
    def require_recovery(self, operation_id: str) -> OrganizationOperation: ...
    def admission_for_run(self, run_id: str) -> OrganizationAdmission | None: ...
    def assert_current(self, admission: OrganizationAdmission) -> OrganizationHead: ...
