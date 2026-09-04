from __future__ import annotations

from pathlib import Path

import pytest

from agent_fleet.adapters.sandbox.fake import FakeExecScript, FakeSandboxProvider
from agent_fleet.adapters.system import SystemClock, UuidIdGenerator
from agent_fleet.domain.ids import IdPrefix
from agent_fleet.domain.models import ExecRequest, SandboxSecurityLevel, SandboxSpec


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
    request = ExecRequest(executable="python", argv=["-m", "pytest", "-q"], cwd=".")
    result = await sandbox.exec(handle, request)
    assert sandbox.security_level is SandboxSecurityLevel.FAKE
    assert sandbox.requests == [request]
    assert result.exit_code == 124
    assert result.timed_out is True
    failure = await sandbox.exec(handle, request)
    assert failure.exit_code == 2
    assert failure.timed_out is False
    await sandbox.terminate(handle)
    assert handle.sandbox_id in sandbox.terminated
