"""The new Broker path never inherits ordinary role rules or trust-mode consent."""

from datetime import timedelta
from pathlib import Path

import pytest
from business_baseline_fixtures import baseline_fixture

from agent_fleet.adapters.config.yaml import YamlConfigurationAdapter
from agent_fleet.adapters.repository.git import GitRepositoryAdapter
from agent_fleet.adapters.trust.filesystem import FilesystemTrustStore
from agent_fleet.application.baseline import bounded_configuration
from agent_fleet.application.permission_policy import (
    PermissionPolicyService,
    PolicyPermissionBroker,
)
from agent_fleet.domain.baseline import reconstruct_command, snapshot_model
from agent_fleet.domain.baseline_resources import BaselineCommandScope
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import (
    CanonicalResource,
    PermissionOutcome,
    SandboxCapabilities,
    SandboxConfiguration,
    SandboxSecurityLevel,
    WorkflowStage,
    WorkspaceKind,
)
from agent_fleet.domain.security import Redactor, canonical_json_hash
from agent_fleet.domain.trust import (
    ExactPermissionScope,
    ProjectTrustSettings,
    TrustMode,
    UserTrustPolicy,
    UserTrustRule,
)


@pytest.mark.parametrize("mode", list(TrustMode))
@pytest.mark.parametrize("consent", [False, True])
@pytest.mark.parametrize("rule_state", ["allow", "active", "future", "expired", "revoked"])
def test_baseline_user_deny_and_exact_consent_are_separate_from_ordinary_trust(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: TrustMode,
    consent: bool,
    rule_state: str,
) -> None:
    h = baseline_fixture(tmp_path)
    policy_service = PermissionPolicyService(
        h.state,
        FilesystemTrustStore(tmp_path / "trust", Redactor()),
        YamlConfigurationAdapter(),
        GitRepositoryAdapter(tmp_path, h.state.ids),
        h.state.clock,
        h.state.ids,
        Redactor(),
        baseline=h.store,
    )
    now = h.state.clock.now()
    command = reconstruct_command(h.review.command)
    # This real legacy scope is intentionally a different role/stage. Baseline
    # conservatively protects every active same-project command deny, not just
    # scopes that could be matched by an invented baseline Agent or Workflow.
    scope = ExactPermissionScope(
        project_id=h.project.project_id,
        repository_identity=h.project.identity_hash,
        principal_role="verifier",
        workflow="code-change",
        stage=WorkflowStage.VERIFYING,
        action="command.run",
        resource=CanonicalResource(kind="project_command", identifier=command.command_id),
        parameters={
            "command_id": command.command_id,
            "command_spec_sha256": canonical_json_hash(command.model_dump(mode="json")),
            "network_mode": "none",
        },
        command=command,
        workspace_kind=WorkspaceKind.VERIFICATION,
        sandbox_provider="docker",
        sandbox_security_level=SandboxSecurityLevel.ISOLATED,
        network_mode="none",
    )
    rule = UserTrustRule(
        rule_id="rule_" + "1" * 32,
        scope=scope,
        effect="allow" if rule_state == "allow" else "deny",
        created_at=now + timedelta(days=1) if rule_state == "future" else now - timedelta(days=2),
        expires_at=now - timedelta(days=1) if rule_state == "expired" else None,
        revoked_at=now - timedelta(days=1) if rule_state == "revoked" else None,
    )
    settings = ProjectTrustSettings(
        project_id=h.project.project_id,
        repository_identity=h.project.identity_hash,
        trust_mode=mode,
        allowed_paths=(".",),
    )
    policy = UserTrustPolicy(projects=[settings], rules=[rule])
    # Pure Broker projection: real context binding is exercised by the public
    # Git/SQLite journey. Here replace only its trusted input loader.
    monkeypatch.setattr(policy_service, "baseline_context", lambda _: (policy, settings))
    assert h.review.capabilities is not None
    capabilities = snapshot_model(h.review.capabilities, "capabilities-v1", SandboxCapabilities)
    claim = h.claim() if consent else None
    decision = PolicyPermissionBroker(policy_service).evaluate_baseline(
        BaselineCommandScope(review=h.review, claim=claim, approved=consent),
        capabilities,
    )
    expected = (
        PermissionOutcome.DENY
        if rule_state == "active"
        else PermissionOutcome.ALLOW
        if consent
        else PermissionOutcome.REQUIRE_APPROVAL
    )
    assert decision.outcome is expected
    assert decision.protected == (rule_state == "active")


@pytest.mark.parametrize("damage", ["tree", "fake", "isolation", "executes", "limits", "recovery"])
def test_baseline_hard_ceilings_cannot_be_overridden_by_consumed_consent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    damage: str,
) -> None:
    h = baseline_fixture(tmp_path)
    policy_service = PermissionPolicyService(
        h.state,
        FilesystemTrustStore(tmp_path / "trust", Redactor()),
        YamlConfigurationAdapter(),
        GitRepositoryAdapter(tmp_path, h.state.ids),
        h.state.clock,
        h.state.ids,
        Redactor(),
        baseline=h.store,
    )
    settings = ProjectTrustSettings(
        project_id=h.project.project_id,
        repository_identity=h.project.identity_hash,
        allowed_paths=("src",) if damage == "tree" else (".",),
    )
    monkeypatch.setattr(policy_service, "baseline_context", lambda _: (UserTrustPolicy(), settings))
    assert h.review.capabilities is not None
    original = snapshot_model(h.review.capabilities, "capabilities-v1", SandboxCapabilities)
    changes: dict[str, object] = {
        "fake": {
            "provider": "fake",
            "security_level": "fake",
            "isolation_enforced": False,
            "executes_code": False,
        },
        "isolation": {"isolation_enforced": False},
        "executes": {"executes_code": False},
        "limits": {"supports_resource_limits": False},
        "recovery": {"supports_recovery": False},
    }
    capabilities = original
    if damage == "fake":
        capabilities = SandboxCapabilities.phase1_fake()
    elif damage != "tree":
        update = changes[damage]
        assert isinstance(update, dict)
        # Deliberately unchecked model_copy simulates a mutated legacy descriptor;
        # the Broker must still deny it, not rely on constructor-only validation.
        capabilities = original.model_copy(update=update)
    decision = PolicyPermissionBroker(policy_service).evaluate_baseline(
        BaselineCommandScope(review=h.review, claim=h.claim(), approved=True),
        capabilities,
    )
    assert decision.outcome is PermissionOutcome.DENY and decision.protected


@pytest.mark.parametrize("provider", ["fake", "local-unsafe"])
def test_baseline_never_admits_non_docker_configuration(provider: str) -> None:
    with pytest.raises(FleetError) as denied:
        bounded_configuration(
            SandboxConfiguration.model_validate(
                {
                    "provider": provider,
                    "network_mode": "approved-unrestricted"
                    if provider == "local-unsafe"
                    else "none",
                }
            )
        )
    assert denied.value.code is ErrorCode.SANDBOX_CAPABILITY_MISSING
