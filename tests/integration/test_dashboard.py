"""Real observer projections and HTTP parsing without opening outbound sockets."""

from __future__ import annotations

import asyncio
import json
import socket
import sqlite3
import threading
import time
from contextlib import suppress
from pathlib import Path
from typing import Any

import pytest
from conftest import FleetHarness
from typer.testing import CliRunner

from agent_fleet.adapters.dashboard.http import DashboardHandler, DashboardServer
from agent_fleet.adapters.runtime.fake import FakeRuntimeAdapter
from agent_fleet.application.runtime import RuntimeRegistry
from agent_fleet.bootstrap import build_container
from agent_fleet.cli.app import app
from agent_fleet.cli.dashboard import dashboard_service
from agent_fleet.domain.errors import FleetError
from agent_fleet.domain.models import (
    AgentInvocation,
    AgentInvocationResult,
    FakeScenario,
    RuntimeConfiguration,
)
from agent_fleet.ports.runtime import RuntimeInvocationServices

pytestmark = pytest.mark.integration


def _exchange(server: DashboardServer, request: str, *, stream: bool = False) -> bytes:
    """Exercise the actual HTTP handler over AF_UNIX; ordinary IP denial stays intact."""
    client, accepted = socket.socketpair()
    client.settimeout(10)
    accepted.settimeout(3)

    def serve() -> None:
        with accepted:
            DashboardHandler(accepted, ("127.0.0.1", 1), server)

    worker = threading.Thread(target=serve)
    worker.start()
    try:
        client.sendall(request.encode())
        chunks = bytearray()
        while chunk := client.recv(65536):
            chunks.extend(chunk)
            if stream and b"event: snapshot\ndata: " in chunks and chunks.endswith(b"\n\n"):
                server.stopping.set()
        return bytes(chunks)
    finally:
        server.stopping.set()
        client.close()
        worker.join(timeout=5)
        assert not worker.is_alive()


def _request(server: DashboardServer, path: str, *, headers: str = "", method: str = "GET") -> str:
    return (
        f"{method} {path} HTTP/1.1\r\n"
        f"Host: {server.origin.removeprefix('http://')}\r\n"
        f"Authorization: Bearer {server.token}\r\n{headers}\r\n"
    )


def test_cli_help_and_missing_state_never_initialize(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = tmp_path / "missing-state"
    monkeypatch.setenv("AGENT_FLEET_HOME", str(state))
    runner = CliRunner()
    assert runner.invoke(app, ["dashboard", "--help"]).exit_code == 0
    assert runner.invoke(app, ["dashboard"]).exit_code == 1
    assert not state.exists()


@pytest.mark.parametrize(
    ("path", "headers", "method", "status"),
    [
        ("/api/catalog", "", "GET", 200),
        ("/", "", "GET", 200),
        ("/dashboard.js", "", "GET", 200),
        ("/dashboard.css", "", "GET", 200),
        ("/api/catalog", "Origin: https://attacker.invalid\r\n", "GET", 403),
        ("/api/catalog", "Origin: null\r\n", "GET", 403),
        ("/api/catalog", "Host: attacker.invalid\r\n", "GET", 400),
        ("/api/catalog", "Authorization: Bearer second\r\n", "GET", 400),
        ("/api/catalog", "Content-Length: 1\r\n", "GET", 400),
        ("/api/catalog", "Transfer-Encoding: chunked\r\n", "GET", 400),
        ("/api/catalog", "Sec-Fetch-Site: cross-site\r\n", "GET", 403),
        ("/api/catalog?before=1&before=2", "", "GET", 400),
        ("/api/catalog?unknown=x", "", "GET", 400),
        ("/api/catalog?before=-1", "", "GET", 409),
        ("/api/runs/not-a-run", "", "GET", 400),
        ("/%2e%2e/state.db", "", "GET", 400),
        ("http://attacker.invalid/api/catalog", "", "GET", 400),
        ("/state.db", "", "GET", 404),
        ("/api/catalog", "", "POST", 405),
        ("/api/catalog", "", "DELETE", 405),
        ("/api/catalog", "", "OPTIONS", 405),
    ],
)
def test_http_boundary(
    harness: FleetHarness,
    path: str,
    headers: str,
    method: str,
    status: int,
) -> None:
    service = dashboard_service(harness.container)
    project = service.open_project(harness.repository_root)
    with DashboardServer(service, project) as server:
        assert server.server_address[0] == "127.0.0.1"
        token = server.token
        response = _exchange(server, _request(server, path, headers=headers, method=method))
        assert response.startswith(f"HTTP/1.0 {status} ".encode())
        assert b"Cache-Control: no-store" in response
        assert b"frame-ancestors 'none'" in response
        assert b"Access-Control-Allow-Origin" not in response
        assert token.encode() not in response
    assert server.token == ""


@pytest.mark.parametrize("bad_token", ["", "wrong-token"])
def test_authentication_is_required(harness: FleetHarness, bad_token: str) -> None:
    service = dashboard_service(harness.container)
    with DashboardServer(service, service.open_project(harness.repository_root)) as server:
        request = _request(server, "/api/catalog").replace(server.token, bad_token)
        assert _exchange(server, request).startswith(b"HTTP/1.0 401 ")


def test_absolute_header_deadline_and_shutdown_interrupt_owned_connections(
    harness: FleetHarness,
) -> None:
    service = dashboard_service(harness.container)
    with DashboardServer(service, service.open_project(harness.repository_root)) as server:
        client, accepted = socket.socketpair()
        client.settimeout(1)
        try:
            server.process_request(accepted, ("127.0.0.1", 1))
            client.sendall(b"GET / HTTP/1.1\r\nHost: ")
            started = time.monotonic()
            while time.monotonic() - started < 4:
                with suppress(OSError):
                    client.sendall(b"x")
                time.sleep(0.15)
            assert not server.connections
            assert time.monotonic() - started < 5
        finally:
            client.close()
        client, accepted = socket.socketpair()
        try:
            server.process_request(accepted, ("127.0.0.1", 1))
            client.sendall(b"GET / HTTP/1.1\r\nHost: ")
            started = time.monotonic()
            server.server_close()
            assert time.monotonic() - started < 1
            assert not server.connections and server.token == ""
        finally:
            client.close()


def test_header_size_is_rejected_before_standard_parser(harness: FleetHarness) -> None:
    service = dashboard_service(harness.container)
    with DashboardServer(service, service.open_project(harness.repository_root)) as server:
        request = _request(server, "/", headers=f"X-Big: {'x' * 5000}\r\n")
        response = _exchange(server, request)
        assert response.startswith(b"HTTP/1.0 431 ")


@pytest.mark.asyncio
async def test_real_evidence_stream_and_artifact_are_scoped_redacted_and_non_mutating(
    harness: FleetHarness,
) -> None:
    run = await harness.start(FakeScenario.PARALLEL_ENGINEERS)
    container = build_container(harness.state_root, migrate=False)
    service = dashboard_service(container)
    project = service.open_project(harness.repository_root)
    with sqlite3.connect(harness.state_root / "state.db") as connection:
        before = tuple(connection.iterdump())
    frame: dict[str, Any] = service.frame(project, run.run_id)
    assert len(frame["runs"]) == 3
    assert len(frame["graph_nodes"]) == 2
    assert {agent["role"] for agent in frame["agents"]} >= {"engineer", "verifier"}
    assert frame["evidence"]["verified_complete"] is False
    with DashboardServer(service, project) as server:
        response = _exchange(
            server, _request(server, f"/api/runs/{run.run_id}/events"), stream=True
        )
        body = response.split(b"\r\n\r\n", 1)[1]
        assert b"event: snapshot\ndata: " in body
        payload = json.loads(body.split(b"data: ", 1)[1].split(b"\n\n", 1)[0])
        assert payload["root_run_id"] == run.run_id
        assert payload["cursors"] == frame["cursors"]
        assert not any(key in body for key in (b"credential_ref", b"active_claim_id"))
    assert run.patch_artifact_id is not None
    artifact = service.artifact(project, run.run_id, run.patch_artifact_id)
    assert artifact["sha256"] == run.patch_sha256
    assert "diff --git" in str(artifact["content"])
    assert run.config_snapshot_artifact_id is not None
    with pytest.raises(FleetError):
        service.artifact(project, run.run_id, run.config_snapshot_artifact_id)
    with sqlite3.connect(harness.state_root / "state.db") as connection:
        assert tuple(connection.iterdump()) == before
    container.redactor.register_secrets(["test-credential-secret"])
    cleaned = service._clean(
        {
            "credential_ref": "env:KEY",
            "prompt": "private",
            "active_claim_id": "claim",
            "text": "test-credential-secret env:OTHER_KEY \u001b[2J <script>alert(1)</script>",
        }
    )
    encoded = json.dumps(cleaned)
    assert "test-credential-secret" not in encoded and "env:OTHER_KEY" not in encoded
    assert "active_claim_id" not in encoded and "private" not in encoded
    # Content is not HTML-escaped twice; frontend must render via textContent.
    assert "<script>" in encoded and "\\u001b" in encoded


@pytest.mark.asyncio
async def test_plan_pause_projection_and_required_model_bindings(harness: FleetHarness) -> None:
    container = harness.container
    container.model_profiles.set("observer-test", configuration=RuntimeConfiguration())
    project = container.model_profiles.project(harness.repository_root)
    container.model_profiles.bind(
        project, default=True, profile="observer-test", expected_revision=0
    )
    run = await harness.container.workflow.start(
        project_path=harness.repository_root,
        goal="Fix canary behavior",
        runtime_name="fake",
        sandbox_name="fake",
        fake_scenario=FakeScenario.SUCCESS,
        review_plan=True,
    )
    service = dashboard_service(harness.container)
    frame: dict[str, Any] = service.frame(service.open_project(harness.repository_root), run.run_id)
    assert frame["runs"][0]["status"] == "paused_for_plan"
    assert frame["plan_review"]["status"] == "pending"
    assert all(agent["role"] == "cos" for agent in frame["agents"])
    assert frame["models"]["bindings_sha256"] == run.model_bindings_sha256
    assert frame["agents"][0]["profile"] == "observer-test"
    assert frame["agents"][0]["runtime"] == "fake"


@pytest.mark.asyncio
async def test_observer_can_show_cos_before_review_checkpoint_exists(harness: FleetHarness) -> None:
    entered, release = asyncio.Event(), asyncio.Event()

    class WaitingCoS(FakeRuntimeAdapter):
        async def invoke(
            self, request: AgentInvocation, services: RuntimeInvocationServices
        ) -> AgentInvocationResult:
            if request.role == "cos":
                entered.set()
                await release.wait()
            return await super().invoke(request, services)

    container = harness.container
    container.workflow.runtimes = RuntimeRegistry({"fake": WaitingCoS()})
    task = asyncio.create_task(
        container.workflow.start(
            project_path=harness.repository_root,
            goal="Observe the actual planning agent",
            runtime_name="fake",
            sandbox_name="fake",
            fake_scenario=FakeScenario.SUCCESS,
            review_plan=True,
        )
    )
    try:
        await asyncio.wait_for(entered.wait(), 10)
        service = dashboard_service(container)
        project = service.open_project(harness.repository_root)
        catalog: dict[str, Any] = service.catalog(project)
        frame: dict[str, Any] = service.frame(project, catalog["runs"][0]["run_id"])
        assert frame["plan_review"] == {"status": "not_reached"}
        assert frame["agents"][0]["role"] == "cos"
        assert frame["agents"][0]["status"] == "running"
        assert frame["evidence"] is None
    finally:
        release.set()
        await task


@pytest.mark.asyncio
async def test_live_child_discovery_after_exact_plan_resume(harness: FleetHarness) -> None:
    entered, release = asyncio.Event(), asyncio.Event()

    class WaitingWriters(FakeRuntimeAdapter):
        writers = 0

        async def invoke(
            self, request: AgentInvocation, services: RuntimeInvocationServices
        ) -> AgentInvocationResult:
            if request.role == "engineer":
                self.writers += 1
                if self.writers == 2:
                    entered.set()
                await release.wait()
            return await super().invoke(request, services)

    container = harness.container
    container.workflow.runtimes = RuntimeRegistry({"fake": WaitingWriters()})
    run = await container.workflow.start(
        project_path=harness.repository_root,
        goal="Observe the real graph growing",
        runtime_name="fake",
        sandbox_name="fake",
        fake_scenario=FakeScenario.PARALLEL_ENGINEERS,
        review_plan=True,
    )
    service = dashboard_service(container)
    project = service.open_project(harness.repository_root)
    before: dict[str, Any] = service.frame(project, run.run_id)
    assert len(before["runs"]) == 1
    checkpoint = container.plan_reviews.inspect(run)
    container.plan_reviews.approve(run, checkpoint.checkpoint_sha256)
    resumed = asyncio.create_task(container.workflow.resume(run.run_id))
    try:
        await asyncio.wait_for(entered.wait(), 20)
        during: dict[str, Any] = service.frame(project, run.run_id, cursors=before["cursors"])
        assert len(during["runs"]) == 3
        assert len(during["cursors"]) == 3
        assert len([agent for agent in during["agents"] if agent["status"] == "running"]) == 2
        assert not during["resync"]
        for child in during["runs"][1:]:
            assert child["parent_run_id"] == run.run_id
    finally:
        release.set()
        await resumed
