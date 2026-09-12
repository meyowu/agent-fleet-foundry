from __future__ import annotations

import os
import socket
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from live_provider_support import (
    SELECTION_ENV,
    parse_live_canary_selection,
    resolve_live_canary_credentials,
)
from pydantic_ai.models import override_allow_model_requests

from agent_fleet.adapters.repository.git import GitRepositoryAdapter
from agent_fleet.adapters.system import UuidIdGenerator
from agent_fleet.bootstrap import ApplicationContainer, build_container
from agent_fleet.domain.models import FakeScenario, Run

_LIVE_PROVIDER_FLAG = "AGENT_FLEET_ENABLE_LIVE_PROVIDER_TESTS"
_DOCKER_TEST_FLAG = "AGENT_FLEET_ENABLE_DOCKER_TESTS"
_DOCKER_TEST_IMAGE = "AGENT_FLEET_DOCKER_TEST_IMAGE"


def _live_provider_inputs_are_ready() -> bool:
    if os.environ.get(_LIVE_PROVIDER_FLAG) != "1":
        return False
    if os.environ.get(_DOCKER_TEST_FLAG) != "1" or not os.environ.get(_DOCKER_TEST_IMAGE):
        return False
    try:
        selection = parse_live_canary_selection(os.environ.get(SELECTION_ENV, ""))
        resolve_live_canary_credentials(selection, os.environ)
    except ValueError:
        return False
    return True


@pytest.fixture
def real_docker_image(request: pytest.FixtureRequest) -> str:
    if request.node.get_closest_marker("docker_integration") is None:
        raise AssertionError("real_docker_image is only valid for docker_integration tests")
    image = os.environ.get(_DOCKER_TEST_IMAGE, "")
    if os.environ.get(_DOCKER_TEST_FLAG) != "1":
        pytest.skip(
            "real Docker tests require AGENT_FLEET_ENABLE_DOCKER_TESTS=1 and "
            "AGENT_FLEET_DOCKER_TEST_IMAGE"
        )
    if not image:
        pytest.fail("AGENT_FLEET_ENABLE_DOCKER_TESTS=1 requires AGENT_FLEET_DOCKER_TEST_IMAGE")
    return image


@pytest.fixture(autouse=True)
def enforce_external_request_boundary(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """Deny ordinary network/model requests; open only the explicit live canary."""

    is_live_provider_test = request.node.get_closest_marker("live_provider") is not None
    is_docker_test = request.node.get_closest_marker("docker_integration") is not None
    if not is_docker_test:
        monkeypatch.setattr("agent_fleet.bootstrap._FIXED_DOCKER_EXECUTABLES", ())
    if is_live_provider_test:
        if not is_docker_test:
            pytest.fail("live provider canary must also declare the real Docker boundary")
        if not _live_provider_inputs_are_ready():
            if os.environ.get(_LIVE_PROVIDER_FLAG) == "1":
                pytest.fail("explicit live opt-in requires all provider and Docker inputs")
            pytest.skip(
                "live provider canary requires both live and Docker opt-ins, a local image, "
                "strict role selection and each configured credential value"
            )
        with override_allow_model_requests(True):
            yield
        return

    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_sendmsg = getattr(socket.socket, "sendmsg", None)

    def deny_network(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("ordinary tests must not perform network access")

    def guarded_connect(sock: socket.socket, address: object) -> object:
        if sock.family in {socket.AF_INET, socket.AF_INET6}:
            deny_network()
        return original_connect(sock, address)  # type: ignore[arg-type]

    def guarded_connect_ex(sock: socket.socket, address: object) -> int:
        if sock.family in {socket.AF_INET, socket.AF_INET6}:
            deny_network()
        return original_connect_ex(sock, address)  # type: ignore[arg-type]

    monkeypatch.setattr(socket, "create_connection", deny_network)
    monkeypatch.setattr(socket, "getaddrinfo", deny_network)
    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)
    monkeypatch.setattr(socket.socket, "sendto", deny_network)
    if original_sendmsg is not None:
        monkeypatch.setattr(socket.socket, "sendmsg", deny_network)

    with override_allow_model_requests(False):
        yield


@dataclass
class FleetHarness:
    root: Path
    state_root: Path
    repository_root: Path
    container: ApplicationContainer

    async def start(self, scenario: FakeScenario = FakeScenario.SUCCESS) -> Run:
        return await self.container.workflow.start(
            project_path=self.repository_root,
            goal="Fix the canary behavior",
            runtime_name="fake",
            sandbox_name="fake",
            fake_scenario=scenario,
        )

    def git(self, *argv: str) -> str:
        result = subprocess.run(
            ["git", *argv],
            cwd=self.repository_root,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout


@pytest.fixture
def harness(tmp_path: Path) -> FleetHarness:
    repository_root = GitRepositoryAdapter(tmp_path, UuidIdGenerator()).create_canary_fixture(
        tmp_path / "target-repository"
    )
    state_root = tmp_path / "fleet-state"
    container = build_container(state_root)
    container.projects._initialize_without_canary(
        repository_root,
        runtime_name="fake",
        sandbox_name="fake",
    )
    return FleetHarness(tmp_path, state_root, repository_root, container)
