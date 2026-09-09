"""Public non-executing repository readiness inspection."""

from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Annotated

import typer
from typer import _click as click
from typer._click.exceptions import UsageError
from typer.core import TyperCommand

from agent_fleet.application.readiness import ReadinessService, admission_error
from agent_fleet.cli.chat import ErrorPresenter, Presenter
from agent_fleet.domain.errors import FleetError
from agent_fleet.domain.models import JsonEnvelope, jsonable
from agent_fleet.domain.security import Redactor

_WARNINGS = [
    "Static inspection only: environment unverified; baseline not checked; "
    "no project commands executed. Exit 0 means static inspection complete, not ready to run."
]


def _wire_size(data: dict[str, object], redactor: Redactor) -> int:
    """Match the existing JSON presenter, including escaping, redaction and newline."""
    safe_data, _ = redactor.redact_data(data)
    safe_warnings, _ = redactor.redact_data(_WARNINGS)
    envelope = JsonEnvelope(
        ok=True,
        command="fleet readiness",
        correlation_id="corr_" + "0" * 32,
        data=jsonable(safe_data),
        warnings=[str(item) for item in safe_warnings],
    )
    return len(
        (json.dumps(envelope.model_dump(mode="json"), sort_keys=True) + "\n").encode("utf-8")
    )


def register_readiness_command(
    app: typer.Typer,
    *,
    service_factory: Callable[[Redactor], ReadinessService],
    redactor_factory: Callable[[], Redactor],
    presenter: Presenter,
    error_presenter: ErrorPresenter,
) -> None:
    class SafeReadinessCommand(TyperCommand):
        def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
            json_requested = "--json" in args
            parsed: list[str] | None = None
            with suppress(UsageError):
                parsed = super().parse_args(ctx, args)
            if parsed is None:
                error_presenter(
                    "fleet readiness", admission_error(), json_requested, redactor_factory()
                )
                raise typer.Exit(code=2)
            return parsed

    @app.command("readiness", cls=SafeReadinessCommand)
    def readiness(
        path: Annotated[Path, typer.Argument(help="Committed Git repository to inspect.")] = Path(
            "."
        ),
        json_output: Annotated[bool, typer.Option("--json")] = False,
    ) -> None:
        """Inspect static declarations only; never prepare an environment or run a baseline."""
        redactor = redactor_factory()
        try:
            report = service_factory(redactor).inspect(path)
            if json_output:
                report = ReadinessService._bounded_report(
                    report.model_dump(mode="python"),
                    wire_size=lambda data: _wire_size(data, redactor),
                )
        except FleetError as error:
            error_presenter("fleet readiness", error, json_output, redactor)
            raise typer.Exit(code=2) from None
        presenter(
            "fleet readiness",
            json_output,
            lambda: (
                jsonable(report.model_dump(mode="json")),
                _WARNINGS,
            ),
            redactor=redactor,
        )
        if not report.inspection_complete:
            raise typer.Exit(code=1)
