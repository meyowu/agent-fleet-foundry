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
from pathlib import Path

import pytest
from test_real_docker import _cleanup_real_installation_scope

from agent_fleet.adapters.repository.git import GitRepositoryAdapter
from agent_fleet.adapters.sandbox.docker import DockerSandboxProvider
from agent_fleet.adapters.system import UuidIdGenerator
from agent_fleet.application.sandboxes import requirements_for_configuration
from agent_fleet.bootstrap import build_container
from agent_fleet.domain.bootstrap import BootstrapPolicyMode, BootstrapReport
from agent_fleet.domain.evidence import CommandEvidence, EvidenceStrength
from agent_fleet.domain.models import SandboxConfiguration, SandboxSecurityLevel
from agent_fleet.domain.offline_canary import BOOTSTRAP_SANDBOX_PROBE_MARKER, BROKEN_CANARY

pytestmark = [pytest.mark.docker_integration, pytest.mark.asyncio]

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
    def __init__(self, repository: Path, state_root: Path) -> None:
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
                [sys.executable, "-u", "-c", _OFFLINE_ENTRY],
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


async def test_bare_terminal_public_onboarding_publishes_only_real_isolated_evidence(
    tmp_path: Path, real_docker_image: str
) -> None:
    target = GitRepositoryAdapter(tmp_path, UuidIdGenerator()).create_canary_fixture(
        tmp_path / "target"
    )
    state_root = tmp_path / "state"
    container = build_container(state_root)
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
    terminal = _Terminal(target, state_root)
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
        assert (target / ".fleet/fleet.yaml").is_file()
        conversation = reopened.conversations.select(target)
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
