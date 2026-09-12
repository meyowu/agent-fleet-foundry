"""Optional real-terminal onboarding through public preview and Docker bootstrap."""

from __future__ import annotations

import codecs
import errno
import os
import re
import selectors
import signal
import subprocess
import sys
import time
from collections.abc import Sequence
from importlib.resources import files
from pathlib import Path
from typing import cast

import pytest
from test_real_docker import _cleanup_real_installation_scope

from agent_fleet.adapters.repository.git import GitRepositoryAdapter
from agent_fleet.adapters.repository.profile import StaticRepositoryProfiler
from agent_fleet.adapters.sandbox.docker import DockerSandboxProvider
from agent_fleet.adapters.system import UuidIdGenerator
from agent_fleet.application.sandboxes import requirements_for_configuration
from agent_fleet.bootstrap import ApplicationContainer, build_container
from agent_fleet.domain.bootstrap import BootstrapPolicyMode, BootstrapReport
from agent_fleet.domain.evidence import CommandEvidence, EvidenceStrength
from agent_fleet.domain.models import (
    RunStatus,
    SandboxConfiguration,
    SandboxSecurityLevel,
    TaskSpec,
)
from agent_fleet.domain.offline_canary import BOOTSTRAP_SANDBOX_PROBE_MARKER, BROKEN_CANARY

pytestmark = pytest.mark.asyncio

_TEST_SOURCE_ROOT = Path(__file__).resolve().parents[2]

_PUBLIC_CANARY_PATHS = (
    ".gitignore",
    "README.md",
    "pyproject.toml",
    "src/canary_calc/__init__.py",
    "src/canary_calc/core.py",
    "tests/test_core.py",
)


def _prepare_terminal_fixture(root: Path, *, public_learning: bool) -> Path:
    repository = GitRepositoryAdapter(root, UuidIdGenerator())
    target = repository.create_canary_fixture(root / "target")
    if public_learning:
        assets = files("agent_fleet").joinpath("assets/canary")
        for relative in _PUBLIC_CANARY_PATHS:
            payload = assets.joinpath(relative).read_bytes()
            (target / relative).write_bytes(payload)
            assert (target / relative).read_bytes() == payload
        repository._run(["git", "add", "--", *_PUBLIC_CANARY_PATHS], cwd=target)
        repository._run(
            ["git", "commit", "--no-gpg-sign", "--no-verify", "-m", "Public canary baseline"],
            cwd=target,
        )
    return target


def _assert_command_outcomes(
    command_ids: set[str],
    outcomes: Sequence[tuple[str | None, str, int | None]],
    *,
    expect_success: bool,
) -> None:
    assert command_ids == ({"python-test"} if expect_success else {"python-build", "python-test"})
    expected = {
        (
            role,
            command_id,
            0 if expect_success else {"python-build": 1, "python-test": 2}[command_id],
        )
        for role in ("engineer", "verifier")
        for command_id in command_ids
    }
    assert len(outcomes) == len(expected)
    assert set(outcomes) == expected


@pytest.mark.parametrize("public_learning", [False, True])
async def test_terminal_fixture_profiles_match_the_actual_project_bytes(
    tmp_path: Path, public_learning: bool
) -> None:
    target = _prepare_terminal_fixture(tmp_path, public_learning=public_learning)
    profile = StaticRepositoryProfiler().profile(target).profile
    assert {command.name for command in profile.commands} == (
        {"python-test"} if public_learning else {"python-build", "python-test"}
    )
    if public_learning:
        assets = files("agent_fleet").joinpath("assets/canary")
        tracked_assets = GitRepositoryAdapter(tmp_path, UuidIdGenerator())._run(
            ["git", "ls-files", "--", "src/agent_fleet/assets/canary"],
            cwd=_TEST_SOURCE_ROOT,
        )
        assert set(_PUBLIC_CANARY_PATHS) == {
            path.removeprefix("src/agent_fleet/assets/canary/")
            for path in tracked_assets.splitlines()
        }
        assert all(
            (target / path).read_bytes() == assets.joinpath(path).read_bytes()
            for path in _PUBLIC_CANARY_PATHS
        )
    else:
        assert "build-backend = 'builtins'" in (target / "pyproject.toml").read_text()
        assert "pythonpath" not in (target / "pyproject.toml").read_text()
    assert (target / "src/canary_calc/core.py").read_text() == BROKEN_CANARY
    assert not (target / ".fleet").exists()


@pytest.mark.parametrize("expect_success", [False, True])
async def test_terminal_outcome_oracle_requires_every_exact_role_command_exit(
    expect_success: bool,
) -> None:
    commands = {"python-test"} if expect_success else {"python-build", "python-test"}
    outcomes = [
        (role, command, 0 if expect_success else {"python-build": 1, "python-test": 2}[command])
        for role in ("engineer", "verifier")
        for command in sorted(commands)
    ]
    _assert_command_outcomes(commands, outcomes, expect_success=expect_success)
    for invalid in (
        outcomes[:-1],
        [*outcomes, outcomes[0]],
        [("engineer", command, code) for _, command, code in outcomes],
        [(role, command, 99) for role, command, _ in outcomes],
    ):
        with pytest.raises(AssertionError):
            _assert_command_outcomes(commands, invalid, expect_success=expect_success)


# Keep the real CLI, registry, public bootstrap and Docker adapter. This process
# boundary only prohibits accidental live provider/Internet requests; it does
# not inject a fake sandbox or shortcut project registration.
_OFFLINE_ENTRY = """
import socket
from pydantic_ai.models import override_allow_model_requests
from agent_fleet.cli.app import main
original_connect = socket.socket.connect
def local_only(sock, address):
    if sock.family in (socket.AF_INET, socket.AF_INET6):
        raise AssertionError('This onboarding acceptance permits no Internet requests')
    return original_connect(sock, address)
socket.socket.connect = local_only
with override_allow_model_requests(False):
    main()
"""


class _Terminal:
    def __init__(
        self,
        repository: Path,
        state_root: Path,
        arguments: tuple[str, ...] = (),
    ) -> None:
        import pty

        self.master, slave = pty.openpty()
        environment = {
            name: os.environ[name]
            for name in ("PATH", "TMPDIR", "TMP", "TEMP", "LANG", "LC_ALL")
            if name in os.environ
        }
        environment.update(
            AGENT_FLEET_HOME=str(state_root), NO_COLOR="1", COLUMNS="240", PYTHONUNBUFFERED="1"
        )
        try:
            self.process = subprocess.Popen(
                [sys.executable, "-u", "-c", _OFFLINE_ENTRY, *arguments],
                cwd=repository,
                env=environment,
                stdin=slave,
                stdout=slave,
                stderr=slave,
            )
        except BaseException:
            os.close(self.master)
            raise
        finally:
            os.close(slave)
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.master, selectors.EVENT_READ)
        self.decoder = codecs.getincrementaldecoder("utf-8")()
        self.output = ""

    def _read(self) -> None:
        for key, _ in self.selector.select(0.1):
            try:
                chunk = os.read(key.fd, 16_384)
            except OSError as error:
                if error.errno != errno.EIO:
                    raise
                chunk = b""
            self.output += self.decoder.decode(chunk)
            assert len(self.output) <= 524_288, "Terminal output exceeded the acceptance bound"

    def until(self, text: str, *, after: int = 0, timeout: int = 120) -> None:
        deadline = time.monotonic() + timeout
        while text not in self.output[after:]:
            self._read()
            assert time.monotonic() < deadline, self.output
            if self.process.poll() is not None and text not in self.output[after:]:
                pytest.fail(f"Terminal exited before {text!r}: {self.output}")

    def send(self, text: str) -> None:
        os.write(self.master, (text + "\n").encode("utf-8"))

    def approve_exact(self, approval_id: str) -> None:
        # An explicit request ID authorizes directly; only implicit selection
        # produces the separate process-local confirmation proposal.
        offset = len(self.output)
        self.send(f"/approve {approval_id} --run")
        self.until('"grant_id":', after=offset)

    def until_run_status(
        self,
        container: ApplicationContainer,
        run_id: str,
        statuses: set[RunStatus],
        *,
        timeout: int = 180,
        previous_approval_id: str | None = None,
    ) -> RunStatus:
        deadline = time.monotonic() + timeout
        while True:
            self._read()
            run = container.state.get_run(run_id)
            if _resumed_status_matches(
                run.status, run.pending_approval_id, statuses, previous_approval_id
            ):
                return run.status
            assert time.monotonic() < deadline, self.output
            if self.process.poll() is not None:
                pytest.fail(f"Terminal exited before run settled: {self.output}")

    def finish(self, *, timeout: int = 30) -> int:
        deadline = time.monotonic() + timeout
        while self.process.poll() is None:
            self._read()
            if time.monotonic() >= deadline:
                raise AssertionError(f"Terminal did not exit after owned cleanup: {self.output}")
        self._read()
        return self.process.wait(timeout=1)

    def close(self) -> None:
        try:
            if self.process.poll() is None:
                self.process.send_signal(signal.SIGINT)
                try:
                    self.finish()
                except AssertionError:
                    # Only this exact test-owned CLI process; provider cleanup
                    # below still requires its installation and complete labels.
                    self.process.kill()
                    self.process.wait(timeout=5)
        finally:
            self.selector.close()
            os.close(self.master)


def _resumed_status_matches(
    status: RunStatus,
    pending_approval_id: str | None,
    statuses: set[RunStatus],
    previous_approval_id: str | None,
) -> bool:
    return status in statuses and not (
        status is RunStatus.PAUSED_FOR_APPROVAL
        and previous_approval_id is not None
        and pending_approval_id == previous_approval_id
    )


@pytest.mark.parametrize(
    ("status", "pending", "expected"),
    [
        (RunStatus.PAUSED_FOR_APPROVAL, "perm_old", False),
        (RunStatus.PAUSED_FOR_APPROVAL, "perm_new", True),
        (RunStatus.READY_FOR_REVIEW, None, True),
        (RunStatus.RUNNING, None, False),
        (RunStatus.FAILED, None, False),
    ],
)
async def test_resumed_status_does_not_reuse_the_just_approved_pause(
    status: RunStatus, pending: str | None, expected: bool
) -> None:
    statuses = {RunStatus.PAUSED_FOR_APPROVAL, RunStatus.READY_FOR_REVIEW}
    assert _resumed_status_matches(status, pending, statuses, "perm_old") is expected
    assert _resumed_status_matches(RunStatus.PAUSED_FOR_APPROVAL, "perm_old", statuses, None)


async def test_exact_approval_driver_accepts_direct_grant_without_confirmation() -> None:
    class DirectGrant:
        output = 'old "grant_id": "old"'
        sent: list[str]

        def __init__(self) -> None:
            self.sent = []

        def send(self, command: str) -> None:
            assert command == "/approve perm_selected --run"
            self.sent.append(command)
            self.output += '\n{"grant_id": "selected-grant"}'

        def until(self, text: str, *, after: int = 0) -> None:
            assert text == '"grant_id":'
            assert self.output[after:] == '\n{"grant_id": "selected-grant"}'
            assert text in self.output[after:]

    terminal = DirectGrant()
    _Terminal.approve_exact(cast(_Terminal, terminal), "perm_selected")
    assert terminal.sent == ["/approve perm_selected --run"]


@pytest.mark.docker_integration
@pytest.mark.parametrize(
    ("exercise_run", "public_learning"),
    [(False, False), (True, False), (True, True)],
    ids=["onboarding-only", "same-process-invalid-environment", "same-process-public-learning"],
)
async def test_bare_terminal_public_onboarding_publishes_only_real_isolated_evidence(
    tmp_path: Path,
    real_docker_image: str,
    exercise_run: bool,
    public_learning: bool,
) -> None:
    target = _prepare_terminal_fixture(tmp_path, public_learning=public_learning)
    state_root = tmp_path / "state"
    container = build_container(state_root)
    source_before = {
        relative: (target / relative).read_bytes()
        for relative in container.repository._run(["git", "ls-files"], cwd=target).splitlines()
    }
    provider = container.sandboxes.get("docker")
    assert isinstance(provider, DockerSandboxProvider)
    scope = provider.recovery_scope_id
    configuration = SandboxConfiguration(provider="docker", image=real_docker_image)
    # Read-only fixture preflight pins the exact daemon/image for both evidence
    # comparison and failure-safe cleanup; no canary or project is registered.
    preflight = await provider.preflight(
        configuration, requirements_for_configuration(configuration)
    )
    assert preflight.ready and preflight.image_identity is not None
    terminal = _Terminal(
        target,
        state_root,
        ("chat", ".", "--review-plan") if exercise_run else (),
    )
    run_id: str | None = None
    required_command_ids: set[str] = set()
    try:
        terminal.until("Review initialization for this repository?")
        terminal.send(f"yes\nfake\n{real_docker_image}\nsafe\nsrc")
        terminal.until("Type initialize ")
        terminal.until("to authorize this exact proposal")
        matches = re.findall(r"Type initialize ([0-9a-f]{16}) to authorize", terminal.output)
        assert len(matches) == 1, terminal.output
        assert "+++ b/.fleet/fleet.yaml" in terminal.output
        assert not (target / ".fleet").exists()
        assert container.state.get_project_by_root(str(target.resolve())) is None
        assert not (state_root / "bootstrap").exists()
        assert container.state.outstanding_leases() == []
        terminal.send(f"initialize {matches[0]}")
        terminal.until("Type a goal", timeout=180)
        assert '"bootstrap_verified": true' in terminal.output
        assert '"bootstrap_cleanup_complete": true' in terminal.output
        assert '"bootstrap_outstanding_lease_count": 0' in terminal.output
        if exercise_run:
            goal_offset = len(terminal.output)
            terminal.send("Fix the canary behavior and independently verify the reviewed command.")
            terminal.until("paused_for_plan /", after=goal_offset, timeout=180)
            conversation = container.conversations.select(target)
            selected_run_id = conversation["run_id"]
            assert isinstance(selected_run_id, str)
            run_id = selected_run_id
            planned_run = container.state.get_run(run_id)
            assert planned_run.task_spec_artifact_id is not None
            task = TaskSpec.model_validate_json(
                container.artifacts.read_bounded_text(planned_run.task_spec_artifact_id)
            )
            required_command_ids = set(task.required_verification_command_ids)
            assert required_command_ids == (
                {"python-test"} if public_learning else {"python-build", "python-test"}
            )
            plan_offset = len(terminal.output)
            terminal.send("/plan approve")
            terminal.until('"confirmation_code":', after=plan_offset)
            plan_match = re.search(
                r'"confirmation_code": "([0-9a-f]{16})"', terminal.output[plan_offset:]
            )
            assert plan_match is not None, terminal.output
            terminal.send(f"/confirm {plan_match.group(1)}")
            terminal.until('"status": "approved"', after=plan_offset)
            terminal.send("/resume")
            approval_ids: list[str] = []
            for _ in range(8):
                status = terminal.until_run_status(
                    container,
                    run_id,
                    {RunStatus.PAUSED_FOR_APPROVAL, RunStatus.READY_FOR_REVIEW},
                    previous_approval_id=approval_ids[-1] if approval_ids else None,
                )
                if status is RunStatus.READY_FOR_REVIEW:
                    break
                run = container.state.get_run(run_id)
                assert run.pending_approval_id is not None
                assert run.pending_approval_id not in approval_ids
                approval_ids.append(run.pending_approval_id)
                terminal.approve_exact(run.pending_approval_id)
                terminal.send("/resume")
            else:
                raise AssertionError("The same-process terminal approval journey did not settle")
            assert len(approval_ids) == len(set(approval_ids)) == 2 * len(required_command_ids)
            terminal.until("ready_for_review / presenting", after=goal_offset)
        terminal.send("/exit")
        assert terminal.finish() == 0, terminal.output
        assert "Traceback" not in terminal.output

        reopened = build_container(state_root)
        project = reopened.state.get_project_by_root(str(target.resolve()))
        assert project is not None and project.bootstrap_verified
        assert project.runtime_name == "fake" and project.credential_ref is None
        assert project.sandbox_name == "docker"
        assert project.sandbox_image_identity == preflight.image_identity
        assert project.sandbox_daemon_identity == preflight.daemon_identity
        assert project.bootstrap_report_artifact_id is not None
        metadata = reopened.state.get_artifact(project.bootstrap_report_artifact_id)
        assert metadata.sha256 == project.bootstrap_report_sha256
        report = BootstrapReport.model_validate_json(
            reopened.artifacts.read_bounded_text(metadata.artifact_id)
        )
        assert report.policy_mode is BootstrapPolicyMode.VERIFIED and report.publish_allowed
        assert report.completion_decision.verified_complete
        assert report.sandbox_capabilities.security_level is SandboxSecurityLevel.ISOLATED
        assert report.sandbox_preflight.image_identity == preflight.image_identity
        assert report.sandbox_preflight.daemon_identity == preflight.daemon_identity
        assert report.sandbox_preflight.recovery_scope_id == scope
        assert report.cleanup_complete and report.outstanding_lease_count == 0
        assert report.proof_gaps == []
        commands = [
            CommandEvidence.model_validate_json(
                reopened.artifacts.read_bounded_text(reference.artifact_id)
            )
            for reference in report.command_evidence
        ]
        assert len(commands) == 2
        assert {item.principal_role for item in commands} == {"engineer", "verifier"}
        assert len({item.agent_instance_id for item in commands}) == 2
        assert all(
            item.sandbox_provider == "docker"
            and item.sandbox_security_level is SandboxSecurityLevel.ISOLATED
            and item.strength is not EvidenceStrength.SIMULATED
            and item.exit_code == 0
            and not item.timed_out
            and not item.output_truncated
            and item.sandbox_image_identity == preflight.image_identity
            and item.sandbox_daemon_identity == preflight.daemon_identity
            for item in commands
        )
        transcripts = [
            reopened.artifacts.read_bounded_text(reference.artifact_id)
            for reference in report.command_transcripts
        ]
        assert len(transcripts) == 2
        assert all(text.count(BOOTSTRAP_SANDBOX_PROBE_MARKER) == 1 for text in transcripts)
        assert (target / "src/canary_calc/core.py").read_text() == BROKEN_CANARY
        assert all((target / path).read_bytes() == data for path, data in source_before.items())
        assert (target / ".fleet/fleet.yaml").is_file()
        conversation = reopened.conversations.select(target)
        if exercise_run:
            assert run_id is not None
            assert conversation["run_id"] == run_id and conversation["active_turn_id"] is None
            run = reopened.state.get_run(run_id)
            assert run.status is RunStatus.READY_FOR_REVIEW
            assert run.verified_complete is public_learning
            inspection_status = reopened.inspection.status(run_id)
            evidence = inspection_status["evidence"]
            assert isinstance(evidence, dict)
            run_commands = evidence["command_results"]
            assert isinstance(run_commands, list)
            assert [item["evidence_artifact_id"] for item in run_commands] == (
                run.command_evidence_artifact_ids
            )
            typed_commands = [
                CommandEvidence.model_validate_json(
                    reopened.artifacts.read_bounded_text(item["evidence_artifact_id"])
                )
                for item in run_commands
            ]
            for public, command in zip(run_commands, typed_commands, strict=True):
                assert command.evidence_id == public["evidence_artifact_id"]
                assert command.agent_instance_id == public["agent_instance_id"]
                assert command.command_id == public["command_id"]
                assert command.exit_code == public["exit_code"]
                assert command.run_id == run_id
                assert command.sandbox_provider == "docker"
                assert command.sandbox_security_level is SandboxSecurityLevel.ISOLATED
                assert command.strength is not EvidenceStrength.SIMULATED
                assert not command.timed_out and not command.output_truncated
                assert command.sandbox_image_identity == preflight.image_identity
                assert command.sandbox_daemon_identity == preflight.daemon_identity
                transcript = reopened.artifacts.read_bounded_text(command.transcript_artifact_id)
                if public_learning:
                    assert "5 passed" in transcript
                elif command.command_id == "python-build":
                    assert "No module named build" in transcript
                else:
                    assert "ModuleNotFoundError" in transcript and "canary_calc" in transcript
            _assert_command_outcomes(
                required_command_ids,
                [(item.principal_role, item.command_id, item.exit_code) for item in typed_commands],
                expect_success=public_learning,
            )
            assert len({item.agent_instance_id for item in typed_commands}) == 2
            assert evidence["verified_complete"] is public_learning
            assert evidence["effective_verdict"] == ("pass" if public_learning else "fail")
            assert evidence["completion_reason_codes"] == (
                [] if public_learning else ["COMMAND_EXECUTION_FAILED", "CRITERION_NOT_PASSING"]
            )
            assert evidence["proof_gaps"] == []
        else:
            assert run_id is None
            assert conversation["run_id"] is None and conversation["active_turn_id"] is None
        assert reopened.state.outstanding_leases() == []
        assert (
            await provider._list_exact(
                provider._require_executable(), {"agent-fleet.installation": scope}
            )
            == []
        )
    finally:
        terminal.close()
        await _cleanup_real_installation_scope(provider, scope)
