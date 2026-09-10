"""Prepared, preregistered real repositories; no model or sandbox execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from conftest import FleetHarness

from agent_fleet.adapters.persistence.evaluation_execution import SqliteEvaluationExecutionStore
from agent_fleet.adapters.persistence.evaluations import SqliteEvaluationStore
from agent_fleet.domain.budgets import RunBudgetLimits
from agent_fleet.domain.evaluation import EvaluationManifest
from agent_fleet.domain.evaluation_execution import EvaluationSubmission
from agent_fleet.domain.models import CommandSpec, RuntimeConfiguration
from agent_fleet.domain.security import canonical_json_hash


@dataclass
class ExecutionFixture:
    harness: FleetHarness
    manifest: EvaluationManifest
    store: SqliteEvaluationExecutionStore
    arguments: dict[str, Any]

    async def execute(self, repetition: int = 0) -> Any:
        return await self.harness.container.evaluation_execution.execute_reserved(
            self.manifest.campaign_id,
            self.manifest.sha256,
            "repair",
            repetition,
            f"reserved-{repetition}",
            self.harness.repository_root,
        )


def execution_fixture(
    harness: FleetHarness,
    *,
    attempts: int = 1,
    limits: RunBudgetLimits | None = None,
    read_only: bool = False,
    parallel: bool = False,
) -> ExecutionFixture:
    container = harness.container
    profiles = container.model_profiles
    project = profiles.project(harness.repository_root)
    profiles.set("evaluation", configuration=RuntimeConfiguration())
    profiles.bind(project, default=True, profile="evaluation", expected_revision=0)
    profile = profiles.store.get_profile("evaluation")
    assert profile is not None
    spec, snapshot = container.workflow.config.load_snapshot(
        harness.repository_root / ".fleet/fleet.yaml"
    )
    info = container.repository.inspect(harness.repository_root)
    source = container.repository.committed_source(harness.repository_root, info.head_revision)
    verification = container.workflow.config.verification_profile(spec, snapshot)
    commands = []
    for command_id, command in sorted(verification.commands.items()):
        parsed = CommandSpec(
            command_id=command_id,
            executable=command.executable,
            argv=tuple(command.argv),
            logical_cwd=command.cwd,
            timeout_seconds=command.timeout_seconds,
            network_requirement="required" if command.network_required else "none",
        )
        commands.append(
            {
                "command_id": command_id,
                "sha256": canonical_json_hash(parsed.model_dump(mode="json")),
            }
        )
    budget = (limits or RunBudgetLimits()).model_dump()
    manifest = EvaluationManifest.model_validate(
        {
            "manifest_id": "eval_" + "a" * 32,
            "campaign_id": "campaign_" + "b" * 32,
            "revision": 0,
            "frozen_at": container.state.clock.now(),
            "repositories": (
                {
                    "repository_id": "repository",
                    "source_sha256": source.source_sha256,
                    "commit_sha": info.head_revision,
                    "cohort": "development",
                },
            ),
            "cases": (
                {
                    "case_id": "repair",
                    "repository_id": "repository",
                    "task_kind": "read_only" if read_only else "code_change",
                    "requirement": "Explain the canary behavior"
                    if read_only
                    else "Fix the canary behavior",
                    "allowed_paths": ()
                    if read_only
                    else ("src/canary_calc",)
                    if parallel
                    else ("src/canary_calc/core.py",),
                    "required_evidence": ("source_baseline", "answer", "oracle", "cleanup")
                    if read_only
                    else (
                        "source_baseline",
                        "patch",
                        "verification",
                        "apply",
                        "post_apply",
                        "oracle",
                        "cleanup",
                    ),
                    "oracle_sha256": "1" * 64,
                    "scoring_sha256": "2" * 64,
                    "commands": () if read_only else tuple(commands),
                    "image_identity": project.sandbox_image_identity,
                    "dependencies_sha256": source.dependencies_sha256,
                    "profile_id": profile.name,
                    "profile_revision": profile.revision,
                    "profile_sha256": canonical_json_hash(profile.model_dump(mode="json")),
                    "configuration_sha256": container.workflow.config.snapshot_hash(snapshot),
                    "run_budget": budget,
                },
            ),
            "slots": tuple({"case_id": "repair", "repetition": index} for index in range(attempts)),
            "budget": {
                **{key: value * attempts for key, value in budget.items()},
                "max_attempts": attempts,
            },
        }
    )
    ledger = SqliteEvaluationStore(container.state)
    ledger.register(manifest)
    for index in range(attempts):
        ledger.reserve(manifest.campaign_id, "repair", index, f"reserved-{index}")
    store = SqliteEvaluationExecutionStore(container.state)
    return ExecutionFixture(harness, manifest, store, {})


class PreparedStop(Exception):
    pass


async def capture_registration(
    fixture: ExecutionFixture, monkeypatch: pytest.MonkeyPatch, repetition: int = 0
) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def capture(
        submission: EvaluationSubmission, run: Any, admission: Any, bindings: Any, **kwargs: Any
    ) -> Any:
        captured.update(
            submission=submission, run=run, admission=admission, bindings=bindings, **kwargs
        )
        raise PreparedStop

    with monkeypatch.context() as context:
        context.setattr(fixture.harness.container.workflow.evaluations, "register", capture)
        with pytest.raises(PreparedStop):
            await fixture.execute(repetition)
    assert captured
    return captured
