"""Thin explicit model-profile commands; configuration and secrets remain user-owned."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Annotated

import typer
from pydantic import JsonValue, ValidationError
from typer import _click as click
from typer._click.exceptions import UsageError
from typer.core import TyperCommand, TyperGroup

from agent_fleet.application.model_profiles import ModelProfileService
from agent_fleet.cli.chat import ErrorPresenter, Presenter
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import RuntimeConfiguration, jsonable
from agent_fleet.domain.security import Redactor


def _syntax_error() -> FleetError:
    return FleetError(
        ErrorCode.CONFIG_INVALID,
        "The model-profile command or configuration is invalid.",
        "Use fleet models --help. Supply credential references, never credential values.",
    )


def register_models_commands(
    app: typer.Typer,
    *,
    service_factory: Callable[[Redactor], ModelProfileService],
    redactor_factory: Callable[[], Redactor],
    presenter: Presenter,
    error_presenter: ErrorPresenter,
) -> None:
    class SafeModelGroup(TyperGroup):
        def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
            json_requested = "--json" in args
            parsed: list[str] | None = None
            with suppress(UsageError):
                parsed = super().parse_args(ctx, args)
            if parsed is None:
                error_presenter("fleet models", _syntax_error(), json_requested, redactor_factory())
                raise typer.Exit(code=2)
            return parsed

        def resolve_command(
            self, ctx: click.Context, args: list[str]
        ) -> tuple[str | None, click.Command | None, list[str]]:
            resolved: tuple[str | None, click.Command | None, list[str]] | None = None
            json_requested = "--json" in args
            with suppress(UsageError):
                resolved = super().resolve_command(ctx, args)
            if resolved is None:
                error_presenter("fleet models", _syntax_error(), json_requested, redactor_factory())
                raise typer.Exit(code=2)
            return resolved

    class SafeModelCommand(TyperCommand):
        def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
            json_requested = "--json" in args
            parsed: list[str] | None = None
            with suppress(UsageError):
                parsed = super().parse_args(ctx, args)
            if parsed is None:
                error_presenter("fleet models", _syntax_error(), json_requested, redactor_factory())
                raise typer.Exit(code=2)
            return parsed

    group = typer.Typer(
        cls=SafeModelGroup,
        no_args_is_help=True,
        help="Manage explicit user-owned model profiles and exact role bindings.",
    )
    app.add_typer(group, name="models")

    def present(
        command: str, json_output: bool, action: Callable[[ModelProfileService], dict[str, object]]
    ) -> None:
        redactor = redactor_factory()

        def operation() -> tuple[JsonValue, list[str]]:
            result: dict[str, object] | None = None
            with suppress(ValidationError, ValueError, TypeError):
                result = action(service_factory(redactor))
            if result is None:
                raise _syntax_error()
            return jsonable(result), []

        # Presenter owns consistent JSON envelopes, redaction and exit behavior.
        presenter(command, json_output, operation, redactor=redactor)

    @group.command("list", cls=SafeModelCommand)
    def list_profiles(json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
        present("fleet models list", json_output, lambda service: service.list())

    @group.command("show", cls=SafeModelCommand)
    def show_profile(
        name: str, json_output: Annotated[bool, typer.Option("--json")] = False
    ) -> None:
        present("fleet models show", json_output, lambda service: service.show(name))

    @group.command("set", cls=SafeModelCommand)
    def set_profile(
        name: str,
        runtime: Annotated[str, typer.Option("--runtime")],
        provider_model: Annotated[str | None, typer.Option("--provider-model")] = None,
        credential_ref: Annotated[str | None, typer.Option("--credential-ref")] = None,
        revision: Annotated[
            int,
            typer.Option(
                "--revision", min=0, help="Reviewed current revision; 0 creates a profile."
            ),
        ] = 0,
        enabled: Annotated[bool, typer.Option("--enabled/--disabled")] = True,
        max_requests: Annotated[int, typer.Option("--max-requests", min=1, max=100)] = 8,
        max_tool_calls: Annotated[int, typer.Option("--max-tool-calls", min=0, max=256)] = 32,
        max_total_tokens: Annotated[
            int, typer.Option("--max-total-tokens", min=1, max=2_000_000)
        ] = 32_768,
        timeout_seconds: Annotated[int, typer.Option("--timeout-seconds", min=1, max=3600)] = 120,
        max_retries: Annotated[int, typer.Option("--max-retries", min=0, max=3)] = 1,
        json_output: Annotated[bool, typer.Option("--json")] = False,
    ) -> None:
        present(
            "fleet models set",
            json_output,
            lambda service: service.set(
                name,
                expected_revision=revision,
                enabled=enabled,
                configuration=RuntimeConfiguration(
                    runtime_name=runtime,
                    provider_model=provider_model,
                    credential_ref=credential_ref,
                    max_requests=max_requests,
                    max_tool_calls=max_tool_calls,
                    max_total_tokens=max_total_tokens,
                    timeout_seconds=timeout_seconds,
                    max_retries=max_retries,
                ),
            ),
        )

    @group.command("remove", cls=SafeModelCommand)
    def remove_profile(
        name: str,
        revision: Annotated[int, typer.Option("--revision", min=1)],
        json_output: Annotated[bool, typer.Option("--json")] = False,
    ) -> None:
        present(
            "fleet models remove",
            json_output,
            lambda service: service.remove(name, expected_revision=revision),
        )

    @group.command("selection", cls=SafeModelCommand)
    def show_selection(
        path: Annotated[Path, typer.Argument()] = Path("."),
        json_output: Annotated[bool, typer.Option("--json")] = False,
    ) -> None:
        present(
            "fleet models selection",
            json_output,
            lambda service: service.selection(service.project(path)),
        )

    @group.command("bind", cls=SafeModelCommand)
    def bind_profile(
        profile: Annotated[str | None, typer.Argument()] = None,
        path: Annotated[Path, typer.Option("--path")] = Path("."),
        role: Annotated[str | None, typer.Option("--role")] = None,
        default: Annotated[bool, typer.Option("--default")] = False,
        clear: Annotated[bool, typer.Option("--clear")] = False,
        permit: Annotated[list[str] | None, typer.Option("--permit")] = None,
        revoke: Annotated[list[str] | None, typer.Option("--revoke")] = None,
        revision: Annotated[int, typer.Option("--revision", min=0)] = 0,
        json_output: Annotated[bool, typer.Option("--json")] = False,
    ) -> None:
        """Bind a default or role, or explicitly permit/revoke a repository-preferred alias."""
        present(
            "fleet models bind",
            json_output,
            lambda service: service.bind(
                service.project(path),
                expected_revision=revision,
                profile=profile,
                role=role,
                default=default,
                clear=clear,
                permit=permit or (),
                revoke=revoke or (),
            ),
        )
