from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from conftest import FleetHarness
from live_provider_support import (
    PROFILE_LIMITS,
    ROOT_LIMITS,
    CanaryEvidence,
    _root_run_id,
    capture_disposable_evidence,
    cleanup_disposable_state,
    credential_forms,
    default_live_canary_selection,
    require_secret_free,
    write_safe_json,
)
from pydantic import ValidationError

from agent_fleet.domain.ids import IdPrefix
from agent_fleet.domain.model_profiles import ResolvedModelBinding, configuration_hash
from agent_fleet.domain.models import (
    ArtifactKind,
    Run,
    RunStatus,
    RuntimeConfiguration,
    WorkspaceKind,
)

_SYNTHETIC_SECRET = "canary-offline-secret+/with-symbols"


def test_canary_profile_freezes_one_correction_without_increasing_budgets() -> None:
    assert PROFILE_LIMITS == {
        "max_requests": 8,
        "max_tool_calls": 12,
        "max_total_tokens": 32_768,
        "timeout_seconds": 120,
        "max_retries": 1,
    }
    assert ROOT_LIMITS == {
        "max_agent_invocations": 12,
        "max_model_requests": 24,
        "max_tool_calls": 32,
        "max_total_tokens": 65_536,
        "max_active_seconds": 600,
    }
    configuration = RuntimeConfiguration(
        runtime_name="pydantic-ai",
        provider_model="openai:gpt-5-nano",
        credential_ref="env:OFFLINE_CANARY_PROFILE_KEY",
        **PROFILE_LIMITS,
    )
    binding = ResolvedModelBinding(
        role_id="cos",
        source="default",
        profile_name="live-canary",
        profile_revision=1,
        configuration=configuration,
        configuration_sha256=configuration_hash(configuration),
    )
    restored = ResolvedModelBinding.model_validate_json(binding.model_dump_json())
    assert restored.configuration == configuration
    assert restored.configuration.provider_model == "openai:gpt-5-nano"
    with pytest.raises(ValidationError, match="frozen"):
        restored.configuration.max_retries = 2  # type: ignore[misc]


def _leased_run(harness: FleetHarness, status: RunStatus) -> tuple[Run, Path]:
    container = harness.container
    project = container.state.get_project_by_root(str(harness.repository_root.resolve()))
    assert project is not None
    info = container.repository.inspect(harness.repository_root)
    now = datetime.now(UTC)
    run = Run(
        run_id=container.state.ids.new(IdPrefix.RUN),
        project_id=project.project_id,
        correlation_id=container.state.ids.new(IdPrefix.CORRELATION),
        goal="offline canary cleanup retention",
        status=status,
        base_revision=info.head_revision,
        target_status_fingerprint=info.status_fingerprint,
        created_at=now,
        updated_at=now,
    )
    container.state.create_run(run)
    workspace = container.repository.create_workspace(
        harness.repository_root, run.run_id, run.base_revision, WorkspaceKind.CANDIDATE
    )
    container.recovery.resources.lease_workspace(workspace)
    container.artifacts.create_text(
        kind=ArtifactKind.RUN_SUMMARY,
        project_id=project.project_id,
        run_id=run.run_id,
        content="Retain original canary evidence even when cleanup changes its status.",
        producer="offline-canary-test",
    )
    return run, Path(workspace.path)


def test_cleanup_before_init_does_not_create_state(tmp_path: Path) -> None:
    root = tmp_path / "not-created"
    assert cleanup_disposable_state(root, owner_stopped=True) == {
        "complete": True,
        "actions": [],
        "errors": [],
        "outstanding_leases": [],
    }
    assert not root.exists()
    with pytest.raises(ValueError, match="stopped execution owner"):
        cleanup_disposable_state(root, owner_stopped=False)


def test_evidence_binds_safe_selection_identity(tmp_path: Path) -> None:
    selection = default_live_canary_selection()
    directory = tmp_path / "private"
    directory.mkdir(mode=0o700)
    recorder = CanaryEvidence(
        state_root=tmp_path / "absent-state",
        repository=tmp_path / "absent-repository",
        forms=credential_forms(_SYNTHETIC_SECRET),
        directory=directory,
        selected_model=selection.cos.provider_model,
        selection_sha256=selection.sha256,
        selected_roles=cast(dict[str, object], selection.safe_projection()["roles"]),
        passed=True,
    )
    recorder.finish()
    evidence = json.loads((directory / "canary-evidence.json").read_text())
    assert evidence["assertions_passed"] is True
    assert evidence["selection_sha256"] == selection.sha256
    assert evidence["selected_roles"] == selection.safe_projection()["roles"]
    assert "credential_ref" not in json.dumps(evidence)


@pytest.mark.parametrize(
    ("status", "action", "final_status"),
    [
        (RunStatus.PAUSED_FOR_APPROVAL, "cancel", RunStatus.CANCELLED),
        (RunStatus.RUNNING, "recover", RunStatus.FAILED),
        (RunStatus.FAILED, "recover", RunStatus.FAILED),
    ],
)
def test_exact_cleanup_retains_pre_cleanup_evidence(
    harness: FleetHarness, status: RunStatus, action: str, final_status: RunStatus
) -> None:
    run, workspace = _leased_run(harness, status)
    original = capture_disposable_evidence(harness.state_root)
    assert original["errors"] == []
    serialized_original = json.dumps(original)
    assert f'"status": "{status.value}"' in serialized_original
    assert "Retain original canary evidence" in serialized_original
    summary = cleanup_disposable_state(harness.state_root, owner_stopped=True)
    assert summary["complete"] is True, summary
    assert summary["actions"] == [
        {
            "run_id": run.run_id,
            "original_status": status.value,
            "action": action,
            "status_after_cleanup": final_status.value,
        }
    ]
    assert not workspace.exists()
    assert harness.container.state.get_run(run.run_id).status is final_status
    assert harness.container.state.list_artifacts(run.run_id)
    repeated = cleanup_disposable_state(harness.state_root, owner_stopped=True)
    assert repeated["complete"] is True
    assert not harness.container.state.outstanding_leases()
    assert original == json.loads(serialized_original)


@pytest.mark.asyncio
async def test_successful_ready_review_is_not_cancelled(harness: FleetHarness) -> None:
    run = await harness.start()
    assert run.status is RunStatus.READY_FOR_REVIEW
    # Invoke outside this test's event loop: clean ready states do not need async cleanup.
    summary = cleanup_disposable_state(harness.state_root, owner_stopped=True)
    assert summary["complete"] is True
    assert harness.container.state.get_run(run.run_id).status is RunStatus.READY_FOR_REVIEW


def test_cleanup_failure_is_separate_and_contains_no_raw_error(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, workspace = _leased_run(harness, RunStatus.PAUSED_FOR_APPROVAL)
    monkeypatch.setattr("live_provider_support.build_container", lambda _: harness.container)

    async def fail_cleanup(_: str) -> Run:
        raise RuntimeError(_SYNTHETIC_SECRET)

    monkeypatch.setattr(harness.container.cancellation, "cancel", fail_cleanup)
    directory = harness.root / "safe-evidence"
    directory.mkdir(mode=0o700)
    recorder = CanaryEvidence(
        harness.state_root, harness.repository_root, credential_forms(_SYNTHETIC_SECRET), directory
    )
    with pytest.raises(RuntimeError, match="canary teardown failed"):
        recorder.finish()
    original = json.loads((directory / "canary-evidence.json").read_text())
    cleanup = json.loads((directory / "cleanup.json").read_text())
    assert original["assertions_passed"] is False
    assert original["runs"][0]["status"]["status"] == "paused_for_approval"
    assert cleanup["complete"] is False and cleanup["outstanding_leases"]
    assert cleanup["errors"] == [{"run_id": run.run_id, "code": "CANARY_OBSERVATION_FAILED"}]
    assert workspace.exists()
    assert _SYNTHETIC_SECRET not in json.dumps(cleanup)
    original_bytes = (directory / "canary-evidence.json").read_bytes()
    recorder.finish()
    assert (directory / "canary-evidence.json").read_bytes() == original_bytes


def test_export_is_private_exclusive_and_rejects_symlinks(tmp_path: Path) -> None:
    directory = tmp_path / "private"
    directory.mkdir(mode=0o700)
    forms = credential_forms(_SYNTHETIC_SECRET)
    write_safe_json(directory, "cleanup.json", {"complete": True}, forms)
    output = directory / "cleanup.json"
    assert output.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        write_safe_json(directory, "cleanup.json", {"complete": False}, forms)
    assert json.loads(output.read_text()) == {"complete": True}
    (directory / "canary-evidence.json").symlink_to(tmp_path / "outside")
    with pytest.raises(OSError):
        write_safe_json(directory, "canary-evidence.json", {}, forms)
    assert not (tmp_path / "outside").exists()
    alias = tmp_path / "alias"
    alias.symlink_to(directory, target_is_directory=True)
    with pytest.raises(OSError):
        write_safe_json(alias, "cleanup.json", {}, forms)


def test_internal_child_cleanup_selects_parent_and_rejects_cycles(
    harness: FleetHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent, _ = _leased_run(harness, RunStatus.RUNNING)
    child = "run_" + "a" * 32

    def binding(run_id: str) -> SimpleNamespace | None:
        return SimpleNamespace(parent_run_id=parent.run_id) if run_id == child else None

    monkeypatch.setattr(harness.container.graphs, "child_binding", binding)
    assert _root_run_id(harness.container, child) == parent.run_id
    monkeypatch.setattr(
        harness.container.graphs,
        "child_binding",
        lambda run_id: SimpleNamespace(parent_run_id=run_id),
    )
    with pytest.raises(RuntimeError, match="parent cycle"):
        _root_run_id(harness.container, child)


def test_export_rejects_nonprivate_directory_and_unknown_filename(tmp_path: Path) -> None:
    directory = tmp_path / "public"
    directory.mkdir(mode=0o755)
    with pytest.raises(ValueError, match="user-owned and private"):
        write_safe_json(directory, "cleanup.json", {}, ())
    with pytest.raises(ValueError, match="unsupported"):
        write_safe_json(directory, "../outside", {}, ())
    assert not list(directory.iterdir())


@pytest.mark.parametrize("form", credential_forms(_SYNTHETIC_SECRET))
def test_every_secret_form_is_rejected_before_export(tmp_path: Path, form: bytes) -> None:
    forms = credential_forms(_SYNTHETIC_SECRET)
    with pytest.raises(RuntimeError, match="registered credential form"):
        require_secret_free(form, forms)
    directory = tmp_path / "private"
    directory.mkdir(mode=0o700)
    with pytest.raises(RuntimeError, match="registered credential form"):
        write_safe_json(directory, "canary-evidence.json", {"unsafe": form.decode()}, forms)
    assert not list(directory.iterdir())


def test_detected_tree_secret_still_cleans_and_exports_only_safe_failure(
    harness: FleetHarness,
) -> None:
    _, workspace = _leased_run(harness, RunStatus.PAUSED_FOR_APPROVAL)
    (harness.state_root / "injected-secret").write_text(_SYNTHETIC_SECRET)
    directory = harness.root / "private"
    directory.mkdir(mode=0o700)
    recorder = CanaryEvidence(
        harness.state_root, harness.repository_root, credential_forms(_SYNTHETIC_SECRET), directory
    )
    with pytest.raises(RuntimeError, match="canary teardown failed"):
        recorder.finish()
    assert not workspace.exists()
    assert json.loads((directory / "canary-evidence.json").read_text()) == {
        "assertions_passed": False,
        "error": "CANARY_SECRET_SCAN_FAILED",
    }
    assert json.loads((directory / "cleanup.json").read_text())["complete"] is True
