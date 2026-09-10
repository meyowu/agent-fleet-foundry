"""User-only standalone baseline consent; never a model tool route."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from contextlib import suppress
from pathlib import Path
from typing import Annotated, Any

import typer
from typer import _click as click
from typer._click.exceptions import UsageError
from typer.core import TyperCommand

from agent_fleet.application.baseline import BaselineService, baseline_error, baseline_exit_code
from agent_fleet.cli.chat import ErrorPresenter, Presenter
from agent_fleet.domain.baseline_resources import BaselineShow
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import jsonable
from agent_fleet.domain.security import Redactor


def register_baseline_commands(
    app: typer.Typer,
    *,
    service_factory: Callable[[Redactor], BaselineService],
    redactor_factory: Callable[[], Redactor],
    presenter: Presenter,
    error_presenter: ErrorPresenter,
) -> None:
    baseline = typer.Typer(
        help="Review and observe one existing project command without any model."
    )
    app.add_typer(baseline, name="baseline")

    class SafeBaselineCommand(TyperCommand):
        def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
            parsed: list[str] | None = None
            with suppress(UsageError):
                parsed = super().parse_args(ctx, args)
            if parsed is None:
                error_presenter(
                    "fleet baseline",
                    baseline_error(ErrorCode.CONFIG_INVALID),
                    "--json" in args,
                    redactor_factory(),
                )
                raise typer.Exit(code=2)
            return parsed

    def invoke(
        name: str,
        json_output: bool,
        operation: Callable[[BaselineService], BaselineShow | Coroutine[Any, Any, BaselineShow]],
        *,
        execute: bool = False,
    ) -> None:
        redactor = redactor_factory()
        try:
            result = operation(service_factory(redactor))
            view = asyncio.run(result) if asyncio.iscoroutine(result) else result
        except FleetError as error:
            error_presenter(name, error, json_output, redactor)
            raise typer.Exit(code=3 if error.code is ErrorCode.RECOVERY_REQUIRED else 2) from None
        except (ValueError, TypeError, OSError):
            error_presenter(name, baseline_error(ErrorCode.CONFIG_INVALID), json_output, redactor)
            raise typer.Exit(code=2) from None
        presenter(
            name,
            json_output,
            lambda: (
                jsonable(
                    {
                        "review": view.review.model_dump(mode="json", by_alias=True),
                        "review_sha256": view.review.digest,
                        "execution": view.execution.model_dump(mode="json", by_alias=True),
                        "report": view.report.model_dump(mode="json", by_alias=True)
                        if view.report
                        else None,
                        "recovery_scope_sha256": view.recovery_scope_sha256,
                    }
                ),
                [
                    "Baseline observation only; no model, patch, Verifier verdict "
                    "or target application."
                ],
            ),
            redactor=redactor,
        )
        if execute:
            raise typer.Exit(code=baseline_exit_code(view))
        if view.review.status == "not_ready":
            raise typer.Exit(code=2)

    @baseline.command("plan", cls=SafeBaselineCommand)
    def plan(
        path: Annotated[Path, typer.Argument()] = Path("."),
        *,
        command: Annotated[str, typer.Option("--command")],
        json_output: Annotated[bool, typer.Option("--json")] = False,
    ) -> None:
        """Persist an exact five-minute review; no project command executes."""
        invoke("fleet baseline plan", json_output, lambda service: service.plan(path, command))

    @baseline.command("run", cls=SafeBaselineCommand)
    def run(
        review_id: str,
        allow_once: Annotated[bool, typer.Option("--allow-once")] = False,
        review_sha256: Annotated[str | None, typer.Option("--review-sha256")] = None,
        json_output: Annotated[bool, typer.Option("--json")] = False,
    ) -> None:
        """Consume explicit exact consent once, never replay a spent baseline."""
        invoke(
            "fleet baseline run",
            json_output,
            lambda service: service.run(
                review_id, allow_once=allow_once, review_sha256=review_sha256
            ),
            execute=True,
        )

    @baseline.command("show", cls=SafeBaselineCommand)
    def show(identity: str, json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
        """Read validated immutable review, status and report without repairing state."""
        invoke("fleet baseline show", json_output, lambda service: service.show(identity))

    @baseline.command("revoke", cls=SafeBaselineCommand)
    def revoke(
        review_id: str, json_output: Annotated[bool, typer.Option("--json")] = False
    ) -> None:
        """Revoke an unconsumed review; this does not cancel an owned command."""
        invoke("fleet baseline revoke", json_output, lambda service: service.revoke(review_id))

    @baseline.command("recover", cls=SafeBaselineCommand)
    def recover(
        identity: str,
        owner_stopped: Annotated[bool, typer.Option("--owner-stopped")] = False,
        cleanup_sha256: Annotated[str | None, typer.Option("--cleanup-sha256")] = None,
        json_output: Annotated[bool, typer.Option("--json")] = False,
    ) -> None:
        """Clean only an exact reviewed resource set after proving its owner absent."""
        invoke(
            "fleet baseline recover",
            json_output,
            lambda service: service.recover(
                identity, owner_stopped=owner_stopped, cleanup_sha256=cleanup_sha256
            ),
            execute=True,
        )
