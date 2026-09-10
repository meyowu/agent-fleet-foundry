"""Bounded foreground initialization over the public bootstrap application path."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Protocol

from pydantic import JsonValue, ValidationError

from agent_fleet.application.conversations import ChatExecutionOptions, SessionBootstrapOptions
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.trust import TrustMode

type View = dict[str, JsonValue]


class _Cancelled(Exception):
    """EOF or explicit setup exit; never an application failure."""


class BootstrapClient(Protocol):
    def preview_initialization(
        self, project_path: Path, *, options: SessionBootstrapOptions
    ) -> View: ...

    async def initialize(self, *, code: str) -> View: ...

    def select(
        self, project_path: Path, *, conversation_id: str | None = None, create_new: bool = False
    ) -> View: ...


class LineInput(Protocol):
    async def read_line(self) -> str | None: ...


async def onboard(
    service: BootstrapClient,
    path: Path,
    options: ChatExecutionOptions,
    reader: LineInput,
    *,
    emit: Callable[[str], None],
    create_new: bool = False,
    interrupt: asyncio.Event | None = None,
) -> View | None:
    """Keep cancellation and any public bootstrap cleanup inside this owner."""
    execution = asyncio.create_task(
        _onboard(service, path, options, reader, emit=emit, create_new=create_new)
    )
    interrupted = asyncio.create_task((interrupt or asyncio.Event()).wait())

    async def settle() -> View | None:
        while not execution.done():
            with suppress(asyncio.CancelledError):
                await asyncio.shield(execution)
        return execution.result()

    try:
        await asyncio.wait({execution, interrupted}, return_when=asyncio.FIRST_COMPLETED)
        if execution.done():
            return execution.result()
        execution.cancel()
        with suppress(asyncio.CancelledError):
            await settle()
        return None
    except _Cancelled:
        return None
    finally:
        try:
            if not execution.done():
                execution.cancel()
                with suppress(asyncio.CancelledError):
                    await settle()
        finally:
            interrupted.cancel()
            await asyncio.gather(interrupted, return_exceptions=True)


async def _onboard(
    service: BootstrapClient,
    path: Path,
    options: ChatExecutionOptions,
    reader: LineInput,
    *,
    emit: Callable[[str], None],
    create_new: bool = False,
) -> View | None:
    """Only terminal-authored input can authorize setup; blank/EOF cancels safely."""

    async def ask(prompt: str, *, default: str = "") -> str:
        emit(prompt)
        value = await reader.read_line()
        if value is None or value.strip() == "/exit":
            raise _Cancelled
        if len(value.encode("utf-8")) > 4096:
            raise _invalid()
        return value.strip() or default

    emit(
        "This Git repository is not registered. Setup first shows the full Fleet proposal.\n"
        "Publishing requires a disposable, verified Docker canary using an existing local image.\n"
        "No image is pulled/built and no live model task runs during setup.\n"
        "Only credential references are accepted; never paste an API key here."
    )
    if await ask("Review initialization for this repository? Type yes; Enter cancels.") != "yes":
        return None
    if options.sandbox_name not in {None, "docker"} or options.allow_unsafe_local:
        raise _invalid()
    runtime = options.runtime_name or await ask(
        "Runtime [fake]: fake (scripted learning only), pydantic-ai or openai-agents (BYOK).",
        default="fake",
    )
    if runtime not in {"fake", "pydantic-ai", "openai-agents"}:
        raise _invalid()
    provider_model = options.provider_model
    credential_ref = options.credential_ref
    if runtime in {"pydantic-ai", "openai-agents"}:
        provider_model = provider_model or await ask("Explicit provider:model identifier:")
        credential_ref = credential_ref or await ask(
            "Credential reference [env:OPENAI_API_KEY], never its value:",
            default="env:OPENAI_API_KEY",
        )
    image = await ask("Existing local Docker image (required; no download/build):")
    if not image:
        return None
    mode = await ask("Trust mode [safe]: safe, balanced, or autonomous-sandbox.", default="safe")
    paths = await ask(
        "Reviewed repository-relative path ceiling [.] (comma-separated):", default="."
    )
    try:
        configuration = SessionBootstrapOptions.model_validate(
            {
                "runtime_name": runtime,
                "provider_model": provider_model,
                "credential_ref": credential_ref,
                "docker_image": image,
                "trust_mode": TrustMode(mode),
                "allowed_paths": tuple(path.strip() for path in paths.split(",")),
            }
        )
    except (ValueError, ValidationError):
        raise _invalid() from None
    preview = service.preview_initialization(path, options=configuration)
    emit(
        json.dumps(
            {key: value for key, value in preview.items() if key != "proposal_patch"},
            indent=2,
            ensure_ascii=True,
        )
    )
    patch = preview.get("proposal_patch")
    code = preview.get("confirmation_code")
    if not isinstance(patch, str) or not isinstance(code, str):
        raise _invalid()
    emit(patch)
    if (
        await ask(f"Type initialize {code} to authorize this exact proposal; Enter cancels.")
        != f"initialize {code}"
    ):
        return None
    emit("Running the disposable public bootstrap canary and verifying its evidence...")
    initialized = await service.initialize(code=code)
    emit(json.dumps(initialized, ensure_ascii=True, indent=2))
    return service.select(path, create_new=create_new)


def _invalid() -> FleetError:
    return FleetError(
        ErrorCode.CONFIG_INVALID,
        "Initialization input is invalid; setup accepts bounded explicit Docker/BYOK choices only.",
        "Review fleet init --help and retry; no implicit download, provider call "
        "or host fallback occurred.",
    )
