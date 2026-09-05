from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_fleet.adapters.sandbox.fake import FakeExecScript, FakeSandboxProvider
from agent_fleet.adapters.system import SystemClock, UuidIdGenerator
from agent_fleet.domain.ids import IdPrefix
from agent_fleet.domain.models import (
    ExecRequest,
    SandboxCapabilities,
    SandboxSecurityLevel,
    SandboxSpec,
    WorkflowStage,
)


def _request(ids: UuidIdGenerator, *, max_output_bytes: int = 64_000) -> ExecRequest:
    return ExecRequest(
        execution_id=ids.new(IdPrefix.EXECUTION),
        intent_id=ids.new(IdPrefix.INTENT),
        task_id=ids.new(IdPrefix.TASK),
        agent_instance_id=ids.new(IdPrefix.AGENT),
        stage=WorkflowStage.VERIFYING,
        executable="python",
        argv=["-m", "pytest", "-q"],
        cwd=".",
        max_output_bytes=max_output_bytes,
        command_spec_hash="1" * 64,
    )


def test_fake_sandbox_capabilities_are_explicit_and_exact() -> None:
    sandbox = FakeSandboxProvider(SystemClock(), UuidIdGenerator())

    assert sandbox.capabilities == SandboxCapabilities(
        provider="fake",
        security_level=SandboxSecurityLevel.FAKE,
        isolation_enforced=False,
        executes_code=False,
        supported_network_modes=["none"],
        supports_resource_limits=False,
        supports_recovery=True,
    )
    assert sandbox.security_level is SandboxSecurityLevel.FAKE
    assert sandbox.capabilities.supported_network_modes == ("none",)
    with pytest.raises(ValidationError, match="frozen"):
        sandbox.capabilities.executes_code = True  # type: ignore[misc]


@pytest.mark.parametrize(
    "overrides",
    [
        {"security_level": SandboxSecurityLevel.ISOLATED},
        {"isolation_enforced": True},
        {"executes_code": True},
        {"supported_network_modes": ["approved-unrestricted"]},
        {"supports_resource_limits": True},
        {"supports_recovery": False},
    ],
)
def test_fake_sandbox_rejects_incoherent_capability_claims(
    overrides: dict[str, object],
) -> None:
    values: dict[str, object] = {
        "provider": "fake",
        "security_level": SandboxSecurityLevel.FAKE,
        "isolation_enforced": False,
        "executes_code": False,
        "supported_network_modes": ["none"],
        "supports_resource_limits": False,
        "supports_recovery": True,
    }
    values.update(overrides)

    with pytest.raises(ValidationError, match="fake sandbox capability descriptor"):
        SandboxCapabilities.model_validate(values)


def test_isolated_sandbox_requires_coherent_security_capabilities() -> None:
    with pytest.raises(ValidationError, match="isolated sandbox capabilities require"):
        SandboxCapabilities(
            provider="hosted",
            security_level=SandboxSecurityLevel.ISOLATED,
            isolation_enforced=True,
            executes_code=False,
            supported_network_modes=["approved-unrestricted"],
            supports_resource_limits=True,
            supports_recovery=True,
        )


@pytest.mark.asyncio
async def test_fake_sandbox_records_canonical_exec_and_failure(tmp_path: Path) -> None:
    ids = UuidIdGenerator()
    sandbox = FakeSandboxProvider(
        SystemClock(),
        ids,
        scripts=[
            FakeExecScript(exit_code=124, stderr="timeout", timed_out=True),
            FakeExecScript(exit_code=2, stderr="scripted failure"),
        ],
    )
    run_id = ids.new(IdPrefix.RUN)
    handle = await sandbox.create(run_id, SandboxSpec(workspace_host_path=str(tmp_path)))
    request = _request(ids)
    result = await sandbox.exec(handle, request)
    assert sandbox.security_level is SandboxSecurityLevel.FAKE
    assert sandbox.requests == [request]
    assert result.exit_code == 124
    assert result.timed_out is True
    failure_request = _request(ids)
    failure = await sandbox.exec(handle, failure_request)
    assert failure.exit_code == 2
    assert failure.timed_out is False
    await sandbox.terminate(handle)
    assert handle.sandbox_id in sandbox.terminated


@pytest.mark.asyncio
async def test_fake_sandbox_reports_output_truncation(tmp_path: Path) -> None:
    ids = UuidIdGenerator()
    sandbox = FakeSandboxProvider(
        SystemClock(),
        ids,
        scripts=[FakeExecScript(stdout="abcdefgh", stderr="12345")],
    )
    handle = await sandbox.create(
        ids.new(IdPrefix.RUN),
        SandboxSpec(workspace_host_path=str(tmp_path)),
    )
    request = _request(ids, max_output_bytes=4)

    result = await sandbox.exec(handle, request)

    assert result.stdout == "abcd"
    assert result.stderr == ""
    assert result.output_truncated is True


@pytest.mark.asyncio
async def test_fake_sandbox_truncates_output_by_utf8_bytes(tmp_path: Path) -> None:
    ids = UuidIdGenerator()
    sandbox = FakeSandboxProvider(
        SystemClock(),
        ids,
        scripts=[FakeExecScript(stdout="💥" * 5, stderr="a💥b")],
    )
    handle = await sandbox.create(
        ids.new(IdPrefix.RUN),
        SandboxSpec(workspace_host_path=str(tmp_path)),
    )
    request = _request(ids, max_output_bytes=5)

    result = await sandbox.exec(handle, request)

    assert result.stdout == "💥"
    assert result.stderr == "a"
    assert (
        len(result.stdout.encode("utf-8")) + len(result.stderr.encode("utf-8"))
        <= request.max_output_bytes
    )
    assert result.output_truncated is True
