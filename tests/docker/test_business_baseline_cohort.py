"""Opt-in six-repository public CLI baseline journeys with actual Docker evidence."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import pytest
from baseline_cohort_fixtures import CASES, BaselineCase, create_repository, fixture_git

from agent_fleet.adapters.sandbox.docker import DockerSandboxProvider
from agent_fleet.bootstrap import build_baseline_container, build_container
from agent_fleet.domain.baseline import BaselineReview, reconstruct_command, snapshot_model
from agent_fleet.domain.baseline_resources import (
    BaselineCommandPayload,
    BaselineControlInspection,
    BaselineExecutionHandle,
    BaselineSandboxInspection,
    BaselineWorkspacePayload,
)

pytestmark = [pytest.mark.docker_integration, pytest.mark.asyncio]

_CLI_WATCHDOG_SECONDS = 360

_OFFLINE_ENTRY = """
import socket
from pydantic_ai.models import override_allow_model_requests
from agent_fleet.cli.app import main
original = socket.socket.connect
def connect(sock, address):
    if sock.family in (socket.AF_INET, socket.AF_INET6):
        raise AssertionError('Baseline cohort forbids Internet and provider requests')
    return original(sock, address)
socket.socket.connect = connect
with override_allow_model_requests(False):
    main()
"""


class _OwnerQuiescence(StrEnum):
    KNOWN = "known"
    UNKNOWN = "unknown"


@dataclass
class _CliOwnerState:
    quiescence: _OwnerQuiescence = _OwnerQuiescence.KNOWN

    def mark_unknown(self) -> None:
        self.quiescence = _OwnerQuiescence.UNKNOWN


@pytest.fixture
def cohort_image() -> str:
    image = os.environ.get("AGENT_FLEET_BASELINE_COHORT_IMAGE", "")
    if os.environ.get("AGENT_FLEET_ENABLE_DOCKER_TESTS") != "1" or not image:
        pytest.skip("six-repository cohort needs Docker opt-in and a prepared Python/Node image")
    return image


def _cli(
    target: Path,
    state: Path,
    *arguments: str,
    owner_state: _CliOwnerState,
) -> tuple[int, dict[str, Any]]:
    environment = {
        key: os.environ[key] for key in ("PATH", "TMPDIR", "LANG", "LC_ALL") if key in os.environ
    }
    environment.update(
        AGENT_FLEET_HOME=str(state),
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONNOUSERSITE="1",
        NO_COLOR="1",
    )
    process = subprocess.Popen(
        [sys.executable, "-B", "-c", _OFFLINE_ENTRY, *arguments],
        cwd=target,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=_CLI_WATCHDOG_SECONDS)
    except BaseException:
        # Inner Docker/Git clients use separate sessions. Kill/reap only the exact
        # owned CLI group, but do not infer whole-child quiescence from its absence.
        owner_state.mark_unknown()
        os.killpg(process.pid, signal.SIGKILL)
        process.communicate(timeout=10)
        raise
    if process.returncode < 0:
        # communicate also returns normally for a child reaped after a signal.
        # Its detached descendants remain unproven even if it emitted valid JSON.
        owner_state.mark_unknown()
        pytest.fail("cohort CLI terminated by signal; descendant quiescence unknown", pytrace=False)
    assert len(stdout.encode()) + len(stderr.encode()) <= 2_097_152
    # A business-test traceback is valid retained data inside the JSON stdout.
    # An unhandled CLI traceback is not a structured observation.
    assert "Traceback" not in stderr, stderr
    document = json.loads(stdout)
    assert isinstance(document, dict), stdout + stderr
    return process.returncode, document


def _data(
    target: Path,
    state: Path,
    *arguments: str,
    expected: int = 0,
    owner_state: _CliOwnerState,
) -> dict[str, Any]:
    code, document = _cli(target, state, *arguments, "--json", owner_state=owner_state)
    assert code == expected, document
    data = document["data"]
    assert isinstance(data, dict)
    return data


def _recover_after_completed_cli(
    target: Path,
    state: Path,
    baseline_id: str,
    owner_state: _CliOwnerState,
) -> None:
    if owner_state.quiescence is _OwnerQuiescence.UNKNOWN:
        return
    current = _data(target, state, "baseline", "show", baseline_id, owner_state=owner_state)
    scope = current["recovery_scope_sha256"]
    if scope is None or (current["report"] or {}).get("cleanup_complete", False):
        return
    recovery_code, recovery_document = _cli(
        target,
        state,
        "baseline",
        "recover",
        baseline_id,
        "--owner-stopped",
        "--cleanup-sha256",
        scope,
        "--json",
        owner_state=owner_state,
    )
    assert recovery_code in {0, 1, 3}, recovery_document
    recovered = recovery_document["data"]
    assert recovered["report"]["cleanup_complete"]


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.identity)
async def test_six_repository_baseline_is_observed_not_inferred(
    tmp_path: Path, cohort_image: str, case: BaselineCase
) -> None:
    target = create_repository(tmp_path / case.identity, case)
    state_root = tmp_path / "state"
    owner_state = _CliOwnerState()
    initial_head = fixture_git(target, "rev-parse", "HEAD")
    readiness = _data(target, state_root, "readiness", str(target), owner_state=owner_state)
    assert readiness["environment_status"] == "unverified"
    assert readiness["baseline_status"] == "not_checked"
    assert readiness["commands_executed"] == 0
    assert readiness["execution_authorized"] is False
    assert not state_root.exists() and not (target / ".fleet").exists()
    assert fixture_git(target, "rev-parse", "HEAD") == initial_head
    assert fixture_git(target, "status", "--porcelain") == ""

    # Composition creates no project: only the public CLI below registers it.
    container = build_container(state_root)
    provider = container.sandboxes.get("docker")
    assert isinstance(provider, DockerSandboxProvider)
    installation = provider.recovery_scope_id
    baseline_id: str | None = None
    try:
        initialized = _data(
            target,
            state_root,
            "init",
            str(target),
            "--runtime",
            "fake",
            "--sandbox",
            "docker",
            "--docker-image",
            cohort_image,
            "--trust-mode",
            "safe",
            "--allow-path",
            ".",
            "--yes",
            owner_state=owner_state,
        )
        assert initialized["bootstrap_verified"] is True
        assert initialized["bootstrap_cleanup_complete"] is True
        assert initialized["bootstrap_outstanding_lease_count"] == 0
        fixture_git(target, "add", ".fleet")
        fixture_git(target, "commit", "-m", "Reviewed fixture Fleet configuration")
        before_head = fixture_git(target, "rev-parse", "HEAD")
        before_files = {
            name: (target / name).read_bytes()
            for name in fixture_git(target, "ls-files").splitlines()
        }

        planned = _data(
            target,
            state_root,
            "baseline",
            "plan",
            str(target),
            "--command",
            case.command_id,
            owner_state=owner_state,
        )
        review = planned["review"]
        baseline_id = review["baseline_id"]
        assert review["status"] == "ready"
        command = reconstruct_command(
            BaselineReview.model_validate_json(json.dumps(review)).command
        )
        assert command.command_id == case.command_id
        assert (command.executable, command.argv) == (
            ("python", ("-m", "pytest")) if case.ecosystem == "python" else ("npm", ("run", "test"))
        )
        assert command.logical_cwd == "."
        assert command.environment == {}
        assert command.network_requirement == "none"
        assert planned["report"] is None
        assert planned["observation"] is None
        assert planned["execution"]["status"] == "planned"
        denied, _ = _cli(
            target,
            state_root,
            "baseline",
            "run",
            review["review_id"],
            "--json",
            owner_state=owner_state,
        )
        assert denied == 2
        before_run = _data(
            target, state_root, "baseline", "show", baseline_id, owner_state=owner_state
        )
        assert before_run == planned
        assert (
            await provider._list_exact(
                provider._require_executable(), {"agent-fleet.installation": installation}
            )
            == []
        )

        observed = _data(
            target,
            state_root,
            "baseline",
            "run",
            review["review_id"],
            "--allow-once",
            "--review-sha256",
            planned["review_sha256"],
            expected=0 if case.exit_code == 0 else 1,
            owner_state=owner_state,
        )
        report = observed["report"]
        assert report["status"] == "observed"
        assert report["completion_assurance"] == "baseline_observation_only"
        assert report["target_applied"] is False
        assert report["observed_exit_code"] == case.exit_code
        assert report["cleanup_complete"] is True
        assert report["proof_gaps"] == []
        assert (
            _data(target, state_root, "baseline", "show", baseline_id, owner_state=owner_state)
            == observed
        )
        replay_code, replay_document = _cli(
            target,
            state_root,
            "baseline",
            "run",
            review["review_id"],
            "--allow-once",
            "--review-sha256",
            planned["review_sha256"],
            "--json",
            owner_state=owner_state,
        )
        assert replay_code == (0 if case.exit_code == 0 else 1)
        assert replay_document["data"] == observed
        assert (
            _data(target, state_root, "baseline", "show", baseline_id, owner_state=owner_state)
            == observed
        )

        reopened = build_baseline_container(state_root)
        observation = reopened.store.observation(baseline_id)
        assert observation is not None and observation.conclusive
        assert observed["observation"] == observation.model_dump(mode="json", by_alias=True)
        assert case.output_marker in (
            observed["observation"]["stdout"] + observed["observation"]["stderr"]
        )
        assert observation.exit_code == case.exit_code
        assert case.output_marker in observation.stdout + observation.stderr
        assert observation.approved_source_sha256 == review["approved_source_sha256"]
        assert observation.materialized_source_sha256 == observation.post_source_sha256
        assert observation.command_sha256 == report["command_sha256"] == review["command"]["sha256"]
        assert observation.review_sha256 == planned["review_sha256"]
        assert report["observation"]["record_sha256"] == observation.digest
        assert not any(
            (
                observation.timed_out,
                observation.cancelled,
                observation.capture_truncated,
                observation.redaction_truncated,
                observation.decoding_replaced,
            )
        )
        handle = snapshot_model(
            observation.native_handle, "native-handle-v1", BaselineExecutionHandle
        )
        inspection = snapshot_model(
            observation.inspection, "sandbox-inspection-v1", BaselineSandboxInspection
        )
        assert handle.native_resource_id == inspection.native_resource_id
        assert handle.owner.baseline_id == baseline_id
        assert dict(handle.labels)["agent-fleet.installation"] == installation
        assert inspection.workspace_read_only
        controls = snapshot_model(
            inspection.legacy_control_inspection, "sandbox-inspection-v1", BaselineControlInspection
        )
        assert controls.ready and controls.non_root and controls.read_only_root
        assert controls.no_new_privileges and controls.capabilities_dropped
        assert controls.resource_limits_enforced and controls.exact_mounts
        assert controls.image_identity is not None and controls.daemon_identity is not None
        snapshot = reopened.store.baseline_resource_snapshot(baseline_id)
        assert snapshot.claim.authorization_id == observation.authorization_id
        assert snapshot.claim.claim_id == observation.claim_id
        assert len(snapshot.leases) == 3
        assert all(lease.status == "released" and lease.receipt_sha256 for lease in snapshot.leases)
        assert (
            sorted(lease.receipt_sha256 for lease in snapshot.leases if lease.receipt_sha256)
            == report["cleanup_receipt_sha256s"]
        )
        command_leases = [
            lease for lease in snapshot.leases if isinstance(lease.payload, BaselineCommandPayload)
        ]
        assert len(command_leases) == 1
        for lease in snapshot.leases:
            if isinstance(lease.payload, BaselineWorkspacePayload):
                assert not await asyncio.to_thread(Path(lease.payload.workspace.path).exists)
        assert fixture_git(target, "rev-parse", "HEAD") == before_head
        assert fixture_git(target, "status", "--porcelain") == ""
        assert {name: (target / name).read_bytes() for name in before_files} == before_files
        assert (
            await provider._list_exact(
                provider._require_executable(), {"agent-fleet.installation": installation}
            )
            == []
        )
    finally:
        if baseline_id is not None:
            _recover_after_completed_cli(target, state_root, baseline_id, owner_state)
