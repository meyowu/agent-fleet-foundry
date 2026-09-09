"""Exact, process-local human review bindings; never model authorization."""

from typing import Literal

from pydantic import Field

from agent_fleet.domain.conversation import ConversationId
from agent_fleet.domain.evolution import OrganizationHead
from agent_fleet.domain.model_profiles import ProfileName
from agent_fleet.domain.models import (
    ApprovalChoice,
    ApprovalRequestId,
    FrozenStrictModel,
    ProjectId,
    RoleId,
    RunId,
    Sha256,
)


class SessionSelection(FrozenStrictModel):
    project_id: ProjectId
    conversation_id: ConversationId
    conversation_revision: int = Field(ge=0)
    run_id: RunId | None
    inspection_revision: int = Field(default=0, ge=0, strict=True)


class ModelSelectionReview(FrozenStrictModel):
    selection: SessionSelection
    profile_name: ProfileName
    profile_revision: int = Field(ge=1, strict=True)
    configuration_sha256: Sha256
    profile_enabled: Literal[True] = True
    role_id: RoleId | None = None
    expected_selection_revision: int = Field(ge=0, strict=True)
    config_snapshot_sha256: Sha256


class PatchReview(FrozenStrictModel):
    run_id: RunId
    run_sha256: Sha256
    project_sha256: Sha256
    artifact_sha256: Sha256
    organization: OrganizationHead


class OrganizationReview(FrozenStrictModel):
    proposal_id: str = Field(pattern=r"^fpatch_[0-9a-f]{32}$")
    action: Literal["apply", "rollback"]
    proposal_sha256: Sha256
    project_sha256: Sha256
    repository_sha256: Sha256
    organization: OrganizationHead


class ApprovalReview(FrozenStrictModel):
    request_id: ApprovalRequestId
    request_sha256: Sha256
    choice: ApprovalChoice


class PlanReview(FrozenStrictModel):
    run_id: RunId
    checkpoint_sha256: Sha256
