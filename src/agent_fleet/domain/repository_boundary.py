"""Repository state that organization publication must leave unchanged."""

from __future__ import annotations

from agent_fleet.domain.models import FrozenStrictModel, RepositoryInfo, Sha256


class OrganizationRepositoryBoundary(FrozenStrictModel):
    repository: RepositoryInfo
    index_sha256: Sha256
    non_organization_status_sha256: Sha256

    def unchanged_outside_organization(self, after: OrganizationRepositoryBoundary) -> bool:
        return (
            self.repository.root == after.repository.root
            and self.repository.identity_hash == after.repository.identity_hash
            and self.repository.head_revision == after.repository.head_revision
            and self.index_sha256 == after.index_sha256
            and self.non_organization_status_sha256 == after.non_organization_status_sha256
        )
