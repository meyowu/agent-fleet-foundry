from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agent_fleet.application.permissions import BaselinePermissionBroker
from agent_fleet.domain.models import (
    AcceptanceCriterion,
    CanonicalResource,
    CommandSpec,
    PermissionOutcome,
    SandboxCapabilities,
    SandboxSecurityLevel,
    TaskSpec,
    ToolIntent,
    WorkflowStage,
)
from agent_fleet.domain.security import canonical_json_hash

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
RUN_ID = "run_11111111111111111111111111111111"
TASK_ID = "task_22222222222222222222222222222222"
AGENT_ID = "agent_33333333333333333333333333333333"
CONFIG_HASH = "a" * 64


def _task() -> TaskSpec:
    command = CommandSpec(
        command_id="offline-canary",
        executable="python",
        argv=("-m", "pytest", "-q"),
    )
    return TaskSpec(
        task_id=TASK_ID,
        run_id=RUN_ID,
        original_goal="Repair the bounded canary.",
        normalized_goal="Repair the bounded canary.",
        workflow="code-change",
        change_kind="code_change",
        base_revision="base-revision",
        allowed_paths=["src/canary_calc/core.py"],
        forbidden_paths=[".git", ".fleet"],
        acceptance_criteria=[
            AcceptanceCriterion(
                criterion_id="canary-behavior",
                description="The canary has the requested behavior.",
            )
        ],
        required_evidence=[
            "canonical_patch",
            "command_evidence",
            "independent_verifier_verdict",
        ],
        max_repair_iterations=1,
        config_snapshot_hash=CONFIG_HASH,
        verification_commands=[command],
        required_verification_command_ids=[command.command_id],
        created_at=NOW,
    )


def _fake_capabilities() -> SandboxCapabilities:
    return SandboxCapabilities(
        provider="fake",
        security_level=SandboxSecurityLevel.FAKE,
        isolation_enforced=False,
        executes_code=False,
        supported_network_modes=["none"],
        supports_resource_limits=False,
        supports_recovery=True,
    )


def _intent(
    *,
    action: str,
    role: str = "engineer",
    stage: WorkflowStage = WorkflowStage.IMPLEMENTING,
    resource: CanonicalResource,
    parameters: dict[str, object],
    side_effect: bool,
) -> ToolIntent:
    return ToolIntent(
        intent_id="intent_44444444444444444444444444444444",
        run_id=RUN_ID,
        task_id=TASK_ID,
        agent_instance_id=AGENT_ID,
        principal_role=role,
        workflow="code-change",
        stage=stage,
        action=action,
        resource=resource,
        parameters=parameters,
        reason="Exercise the baseline permission boundary.",
        side_effect=side_effect,
        idempotency_key="permission-test",
    )


def _write_intent(
    *,
    role: str = "engineer",
    stage: WorkflowStage = WorkflowStage.IMPLEMENTING,
    path: str = "src/canary_calc/core.py",
    resource_kind: str = "workspace_path",
) -> ToolIntent:
    return _intent(
        action="workspace.write_file",
        role=role,
        stage=stage,
        resource=CanonicalResource(kind=resource_kind, identifier=path),
        parameters={"content": "bounded replacement\n"},
        side_effect=True,
    )


def _command_intent(
    *,
    role: str = "engineer",
    stage: WorkflowStage = WorkflowStage.IMPLEMENTING,
    resource: CanonicalResource | None = None,
    argv: list[str] | None = None,
    cwd: str = ".",
) -> ToolIntent:
    command = CommandSpec(
        command_id="offline-canary",
        executable="python",
        argv=("-m", "pytest", "-q"),
    )
    parameters: dict[str, object] = {
        "command_id": command.command_id,
        "command_spec_sha256": canonical_json_hash(command.model_dump(mode="json")),
        "network_mode": "none",
    }
    if argv is not None:
        parameters["argv"] = argv
    if cwd != ".":
        parameters["cwd"] = cwd
    return _intent(
        action="command.run",
        role=role,
        stage=stage,
        resource=resource or CanonicalResource(kind="project_command", identifier="offline-canary"),
        parameters=parameters,
        side_effect=True,
    )


def _assert_default_deny(intent: ToolIntent, sandbox: SandboxCapabilities | None = None) -> None:
    decision = BaselinePermissionBroker().evaluate(
        intent,
        _task(),
        sandbox or _fake_capabilities(),
    )

    assert decision.outcome is PermissionOutcome.DENY
    assert decision.decision_code == "PHASE1_DEFAULT_DENY"
    assert decision.protected is True


def test_bounded_engineer_write_is_allowed() -> None:
    decision = BaselinePermissionBroker().evaluate(
        _write_intent(),
        _task(),
        _fake_capabilities(),
    )

    assert decision.outcome is PermissionOutcome.ALLOW
    assert decision.decision_code == "PHASE3_BOUNDED_CANDIDATE_MUTATION"
    assert decision.protected is False


@pytest.mark.parametrize(
    ("role", "stage"),
    [
        ("engineer", WorkflowStage.IMPLEMENTING),
        ("engineer", WorkflowStage.REPAIRING),
        ("verifier", WorkflowStage.VERIFYING),
    ],
)
def test_exact_fake_command_is_allowed_for_bounded_role_stage(
    role: str,
    stage: WorkflowStage,
) -> None:
    decision = BaselinePermissionBroker().evaluate(
        _command_intent(role=role, stage=stage),
        _task(),
        _fake_capabilities(),
    )

    assert decision.outcome is PermissionOutcome.ALLOW
    assert decision.decision_code == "PHASE3_EXACT_REVIEWED_COMMAND"
    assert decision.protected is False


def test_exact_approval_proof_requires_user_approval() -> None:
    intent = _intent(
        action="fixture.record_side_effect",
        resource=CanonicalResource(
            kind="fake_side_effect",
            identifier="fixture://approval-proof",
        ),
        parameters={"record": "approved-once"},
        side_effect=True,
    )

    decision = BaselinePermissionBroker().evaluate(intent, _task(), _fake_capabilities())

    assert decision.outcome is PermissionOutcome.REQUIRE_APPROVAL
    assert decision.decision_code == "PHASE1_APPROVAL_PROOF"
    assert decision.protected is False


def test_verifier_write_is_denied() -> None:
    _assert_default_deny(
        _write_intent(role="verifier", stage=WorkflowStage.VERIFYING),
    )


@pytest.mark.parametrize(
    ("action", "resource", "parameters"),
    [
        (
            "repo.list_files",
            CanonicalResource(kind="workspace_view", identifier="."),
            {},
        ),
        (
            "repo.read_file",
            CanonicalResource(kind="workspace_path", identifier="src/canary_calc/core.py"),
            {},
        ),
        (
            "repo.search_text",
            CanonicalResource(kind="workspace_view", identifier="."),
            {"query": "canary"},
        ),
        (
            "workspace.get_diff",
            CanonicalResource(kind="workspace_view", identifier="."),
            {},
        ),
    ],
)
def test_bounded_reads_are_allowed_for_engineer_and_verifier(
    action: str,
    resource: CanonicalResource,
    parameters: dict[str, object],
) -> None:
    broker = BaselinePermissionBroker()
    for role, stage in (
        ("engineer", WorkflowStage.IMPLEMENTING),
        ("verifier", WorkflowStage.VERIFYING),
    ):
        decision = broker.evaluate(
            _intent(
                action=action,
                role=role,
                stage=stage,
                resource=resource,
                parameters=parameters,
                side_effect=False,
            ),
            _task(),
            _fake_capabilities(),
        )
        assert decision.outcome is PermissionOutcome.ALLOW
        assert decision.decision_code == "PHASE3_BOUNDED_WORKSPACE_READ"


@pytest.mark.parametrize(
    ("action", "parameters"),
    [
        (
            "workspace.apply_edit",
            {
                "expected_sha256": "a" * 64,
                "old": "before",
                "new": "after",
                "expected_matches": 1,
            },
        ),
        ("workspace.delete_path", {"expected_sha256": "b" * 64}),
    ],
)
def test_exact_engineer_edit_and_delete_are_allowed(
    action: str, parameters: dict[str, object]
) -> None:
    decision = BaselinePermissionBroker().evaluate(
        _intent(
            action=action,
            resource=CanonicalResource(kind="workspace_path", identifier="src/canary_calc/core.py"),
            parameters=parameters,
            side_effect=True,
        ),
        _task(),
        _fake_capabilities(),
    )
    assert decision.outcome is PermissionOutcome.ALLOW


def test_read_and_mutation_parameter_smuggling_is_denied() -> None:
    _assert_default_deny(
        _intent(
            action="repo.read_file",
            resource=CanonicalResource(kind="workspace_path", identifier="src/canary_calc/core.py"),
            parameters={"host_path": "/tmp/escape"},
            side_effect=False,
        )
    )
    _assert_default_deny(
        _intent(
            action="workspace.delete_path",
            resource=CanonicalResource(kind="workspace_path", identifier="src/canary_calc/core.py"),
            parameters={"expected_sha256": "not-a-hash"},
            side_effect=True,
        )
    )


@pytest.mark.parametrize(
    "intent",
    [
        _write_intent(path="src/outside_scope.py"),
        _write_intent(resource_kind="host_path"),
        _intent(
            action="repository.push",
            resource=CanonicalResource(kind="git_remote", identifier="origin"),
            parameters={"branch": "main"},
            side_effect=True,
        ),
    ],
    ids=["out-of-scope-write", "wrong-write-resource", "unrecognized-action"],
)
def test_default_policy_variants_are_denied(intent: ToolIntent) -> None:
    _assert_default_deny(intent)


@pytest.mark.parametrize(
    "intent",
    [
        _command_intent(argv=["-m", "pytest", "-q", "&&", "curl", "example.invalid"]),
        _command_intent(cwd="src"),
        _command_intent(role="cos"),
        _command_intent(stage=WorkflowStage.PRESENTING),
        _command_intent(
            resource=CanonicalResource(
                kind="project_command",
                identifier="different-command",
            )
        ),
    ],
    ids=["compound-argv", "cwd", "role", "stage", "resource"],
)
def test_fake_command_exact_match_mismatches_are_denied(intent: ToolIntent) -> None:
    _assert_default_deny(intent)


def test_exact_command_is_allowed_for_isolated_docker_capabilities() -> None:
    docker = SandboxCapabilities(
        provider="docker",
        security_level=SandboxSecurityLevel.ISOLATED,
        isolation_enforced=True,
        executes_code=True,
        supported_network_modes=["none"],
        supports_resource_limits=True,
        supports_recovery=True,
        supports_non_root=True,
        supports_read_only_root=True,
        supports_no_new_privileges=True,
        supports_capability_drop=True,
    )

    decision = BaselinePermissionBroker().evaluate(_command_intent(), _task(), docker)

    assert decision.outcome is PermissionOutcome.ALLOW


@pytest.mark.parametrize(
    "intent",
    [
        _write_intent().model_copy(update={"run_id": "run_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}),
        _write_intent().model_copy(update={"task_id": "task_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}),
        _write_intent().model_copy(update={"workflow": "different-workflow"}),
        _write_intent().model_copy(update={"side_effect": False}),
        _command_intent().model_copy(update={"side_effect": False}),
    ],
    ids=["run", "task", "workflow", "write-effect", "command-effect"],
)
def test_trusted_context_and_effect_mismatches_are_denied(intent: ToolIntent) -> None:
    _assert_default_deny(intent)


@pytest.mark.parametrize(
    ("stage", "side_effect"),
    [
        (WorkflowStage.VERIFYING, True),
        (WorkflowStage.PRESENTING, True),
        (WorkflowStage.IMPLEMENTING, False),
    ],
)
def test_approval_proof_requires_exact_stage_and_effect(
    stage: WorkflowStage,
    side_effect: bool,
) -> None:
    intent = _intent(
        action="fixture.record_side_effect",
        stage=stage,
        resource=CanonicalResource(
            kind="fake_side_effect",
            identifier="fixture://approval-proof",
        ),
        parameters={"record": "approved-once"},
        side_effect=side_effect,
    )

    _assert_default_deny(intent)
