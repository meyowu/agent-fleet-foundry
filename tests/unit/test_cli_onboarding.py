"""Bounded CLI setup without real providers, Docker or hidden execution."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from pydantic import JsonValue

from agent_fleet.application.conversations import ChatExecutionOptions, SessionBootstrapOptions
from agent_fleet.cli.onboarding import onboard
from agent_fleet.domain.errors import ErrorCode, FleetError

type View = dict[str, JsonValue]


class SetupInput:
    def __init__(self, lines: list[str | None]) -> None:
        self.lines = list(lines)

    async def read_line(self) -> str | None:
        return self.lines.pop(0) if self.lines else None


class SetupClient:
    def __init__(self, *, hold: bool = False, fail: bool = False) -> None:
        self.hold = hold
        self.fail = fail
        self.calls: list[str] = []
        self.options: SessionBootstrapOptions | None = None
        self.entered = asyncio.Event()
        self.cleanup_started = asyncio.Event()
        self.cleanup_release = asyncio.Event()

    def preview_initialization(
        self, project_path: Path, *, options: SessionBootstrapOptions
    ) -> View:
        self.calls.append("public-preview")
        self.options = options
        return {
            "proposal_patch": "--- .fleet/fleet.yaml\n+++ .fleet/fleet.yaml\n+exact proposal\n",
            "proposal_sha256": "b" * 64,
            "confirmation_code": "a" * 16,
            "proposed_user_policy": {"policy_revision": 7},
        }

    async def initialize(self, *, code: str) -> View:
        assert code == "a" * 16
        self.calls.append("public-bootstrap")
        self.entered.set()
        if self.fail:
            raise FleetError(
                ErrorCode.SANDBOX_UNAVAILABLE, "No local image.", "Load it explicitly."
            )
        if self.hold:
            try:
                await asyncio.Event().wait()
            finally:
                self.cleanup_started.set()
                await self.cleanup_release.wait()
        return {"bootstrap_report": "fixture control result, not Docker acceptance"}

    def select(
        self, project_path: Path, *, conversation_id: str | None = None, create_new: bool = False
    ) -> View:
        self.calls.append("select")
        return {"conversation_id": "conv_" + "c" * 32}


def answers() -> list[str | None]:
    return ["yes", "fake", "fleet-local:prepared", "safe", ".", "initialize " + "a" * 16]


@pytest.mark.asyncio
async def test_wizard_requires_exact_nonce_and_preserves_reviewed_settings() -> None:
    client = SetupClient()
    output: list[str] = []
    result = await onboard(
        client, Path("."), ChatExecutionOptions(), SetupInput(answers()), emit=output.append
    )
    assert result == {"conversation_id": "conv_" + "c" * 32}
    assert client.calls == ["public-preview", "public-bootstrap", "select"]
    assert client.options is not None
    assert client.options.runtime_name == "fake"
    assert client.options.docker_image == "fleet-local:prepared"
    assert client.options.trust_mode.value == "safe" and client.options.allowed_paths == (".",)
    assert any("+exact proposal" in item for item in output)
    assert any("No image is pulled/built" in item for item in output)


@pytest.mark.asyncio
@pytest.mark.parametrize("at", range(6))
async def test_eof_at_each_setup_prompt_never_initializes(at: int) -> None:
    client = SetupClient()
    result = await onboard(
        client, Path("."), ChatExecutionOptions(), SetupInput(answers()[:at]), emit=lambda _: None
    )
    assert (
        result is None and "public-bootstrap" not in client.calls and "select" not in client.calls
    )


@pytest.mark.asyncio
async def test_wrong_code_and_unbounded_input_fail_before_bootstrap() -> None:
    client = SetupClient()
    result = await onboard(
        client,
        Path("."),
        ChatExecutionOptions(),
        SetupInput([*answers()[:-1], "yes"]),
        emit=lambda _: None,
    )
    assert result is None and client.calls == ["public-preview"]
    with pytest.raises(FleetError):
        await onboard(
            client, Path("."), ChatExecutionOptions(), SetupInput(["x" * 4097]), emit=lambda _: None
        )
    assert "public-bootstrap" not in client.calls


@pytest.mark.asyncio
async def test_explicit_byok_reference_is_passed_without_any_provider_call() -> None:
    client = SetupClient()
    lines = ["yes", "pydantic-ai", "openai:chosen-model", "env:CHOSEN_KEY", *answers()[2:]]
    await onboard(client, Path("."), ChatExecutionOptions(), SetupInput(lines), emit=lambda _: None)
    assert client.options is not None
    assert client.options.provider_model == "openai:chosen-model"
    assert client.options.credential_ref == "env:CHOSEN_KEY"


@pytest.mark.asyncio
async def test_interrupt_retains_bootstrap_cleanup_before_returning() -> None:
    client = SetupClient(hold=True)
    interrupt = asyncio.Event()
    task = asyncio.create_task(
        onboard(
            client,
            Path("."),
            ChatExecutionOptions(),
            SetupInput(answers()),
            emit=lambda _: None,
            interrupt=interrupt,
        )
    )
    await asyncio.wait_for(client.entered.wait(), 3)
    interrupt.set()
    await asyncio.wait_for(client.cleanup_started.wait(), 3)
    assert not task.done()
    client.cleanup_release.set()
    assert await asyncio.wait_for(task, 3) is None
    assert "select" not in client.calls


@pytest.mark.asyncio
async def test_public_bootstrap_failure_does_not_select_a_conversation() -> None:
    client = SetupClient(fail=True)
    with pytest.raises(FleetError) as error:
        await onboard(
            client, Path("."), ChatExecutionOptions(), SetupInput(answers()), emit=lambda _: None
        )
    assert error.value.code is ErrorCode.SANDBOX_UNAVAILABLE
    assert client.calls == ["public-preview", "public-bootstrap"]
