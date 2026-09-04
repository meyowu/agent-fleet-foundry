from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from agent_fleet.domain.models import AgentInvocation, WorkflowStage


def test_runtime_invocation_rejects_host_paths_and_sandbox_handles() -> None:
    common = {
        "run_id": "run_" + "1" * 32,
        "task_id": "task_" + "2" * 32,
        "agent_instance_id": "agent_" + "3" * 32,
        "role": "verifier",
        "stage": WorkflowStage.VERIFYING,
        "iteration": 0,
        "max_steps": 10,
    }
    for protected in (
        "verification_workspace_path",
        "workspace_host_path",
        "workspace_path",
        "candidate_workspace_path",
        "repository_root",
        "repository_path",
        "project_root",
        "host_path",
        "alternate_filesystem_path",
        "alternate_absolute_path",
        "sandbox_handle",
        "sandbox_id",
    ):
        with pytest.raises(ValidationError, match="execution capability"):
            AgentInvocation(**common, input={"nested": {protected: "/tmp/escape"}})


def test_runtime_invocation_accepts_logical_artifact_and_patch_identity() -> None:
    request = AgentInvocation(
        run_id="run_" + "1" * 32,
        task_id="task_" + "2" * 32,
        agent_instance_id="agent_" + "3" * 32,
        role="verifier",
        stage=WorkflowStage.VERIFYING,
        iteration=0,
        max_steps=10,
        input={
            "patch_sha256": "a" * 64,
            "artifact_id": "art_" + "4" * 32,
            "requested_at": datetime(2026, 9, 4, tzinfo=UTC).isoformat(),
        },
    )
    assert request.input["patch_sha256"] == "a" * 64
