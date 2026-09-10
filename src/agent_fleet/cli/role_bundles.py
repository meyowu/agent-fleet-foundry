"""Read-only packaged role previews; adoption is a separate reviewed CoS task."""

from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Annotated

import typer
from typer import _click as click
from typer._click.exceptions import UsageError
from typer.core import TyperCommand, TyperGroup

from agent_fleet.application.role_bundles import RoleBundleService, bundle_error
from agent_fleet.cli.chat import ErrorPresenter, Presenter
from agent_fleet.domain.errors import FleetError
from agent_fleet.domain.models import JsonEnvelope, jsonable
from agent_fleet.domain.role_bundles import MAX_BUNDLE_PREVIEW_BYTES
from agent_fleet.domain.security import Redactor

_WARNINGS = [
    "Preview only: no configuration, trust, model task or execution was changed. "
    "Submit the adoption brief as a new CoS task, then review its FleetPatch before applying."
]


def _bounded_wire(command: str, data: dict[str, object], redactor: Redactor) -> None:
    safe_data, _ = redactor.redact_data(data)
    safe_warnings, _ = redactor.redact_data(_WARNINGS)
    envelope = JsonEnvelope(
        ok=True,
        command=command,
        correlation_id="corr_" + "0" * 32,
        data=jsonable(safe_data),
        warnings=[str(item) for item in safe_warnings],
    )
    size = len(
        (json.dumps(envelope.model_dump(mode="json"), sort_keys=True) + "\n").encode("utf-8")
    )
    if size > MAX_BUNDLE_PREVIEW_BYTES:
        raise bundle_error()


def register_role_bundle_commands(
    app: typer.Typer,
    *,
    service_factory: Callable[[Redactor], RoleBundleService],
    redactor_factory: Callable[[], Redactor],
    presenter: Presenter,
    error_presenter: ErrorPresenter,
) -> None:
    class SafeBundleGroup(TyperGroup):
        def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
            json_requested = "--json" in args
            parsed: list[str] | None = None
            with suppress(UsageError):
                parsed = super().parse_args(ctx, args)
            if parsed is None:
                error_presenter(
                    "fleet role-bundles", bundle_error(), json_requested, redactor_factory()
                )
                raise typer.Exit(code=2)
            return parsed

        def resolve_command(
            self, ctx: click.Context, args: list[str]
        ) -> tuple[str | None, click.Command | None, list[str]]:
            json_requested = "--json" in args
            resolved: tuple[str | None, click.Command | None, list[str]] | None = None
            with suppress(UsageError):
                resolved = super().resolve_command(ctx, args)
            if resolved is None:
                error_presenter(
                    "fleet role-bundles", bundle_error(), json_requested, redactor_factory()
                )
                raise typer.Exit(code=2)
            return resolved

    class SafeBundleCommand(TyperCommand):
        def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
            json_requested = "--json" in args
            parsed: list[str] | None = None
            with suppress(UsageError):
                parsed = super().parse_args(ctx, args)
            if parsed is None:
                error_presenter(
                    "fleet role-bundles", bundle_error(), json_requested, redactor_factory()
                )
                raise typer.Exit(code=2)
            return parsed

    bundle_app = typer.Typer(
        cls=SafeBundleGroup, help="List packaged responsibilities and preview reviewed adoption."
    )
    app.add_typer(bundle_app, name="role-bundles")

    def present(
        command: str, json_output: bool, operation: Callable[[RoleBundleService], dict[str, object]]
    ) -> None:
        redactor = redactor_factory()
        try:
            data = operation(service_factory(redactor))
            _bounded_wire(command, data, redactor)
        except FleetError as error:
            error_presenter(command, error, json_output, redactor)
            raise typer.Exit(code=2) from None
        presenter(command, json_output, lambda: (jsonable(data), _WARNINGS), redactor=redactor)

    @bundle_app.command("list", cls=SafeBundleCommand)
    def list_bundles(
        json_output: Annotated[bool, typer.Option("--json")] = False,
    ) -> None:
        """Show four versioned bundles, without opening a repository or state store."""
        present(
            "fleet role-bundles list",
            json_output,
            lambda service: {
                "bundles": [
                    item.model_dump(mode="json") | {"sha256": item.sha256}
                    for item in service.list()
                ],
                "execution_authorized": False,
                "publication_authorized": False,
            },
        )

    @bundle_app.command("preview", cls=SafeBundleCommand)
    def preview_bundle(
        bundle_id: Annotated[str, typer.Argument(help="Exact packaged bundle ID.")],
        workflow: Annotated[str, typer.Option("--workflow", help="Existing workflow ID.")],
        scopes: Annotated[
            list[str],
            typer.Option("--scope", help="Explicit role and verification scope; repeat as needed."),
        ],
        commands: Annotated[
            list[str],
            typer.Option("--command", help="Existing verification command ID; repeat as needed."),
        ],
        path: Annotated[Path, typer.Option("--path")] = Path("."),
        json_output: Annotated[bool, typer.Option("--json")] = False,
    ) -> None:
        """Show complete proposed files, diff and a bounded new-CoS adoption brief."""
        present(
            "fleet role-bundles preview",
            json_output,
            lambda service: service.preview(
                bundle_id,
                path,
                workflow_id=workflow,
                scopes=tuple(scopes),
                command_ids=tuple(commands),
            ).model_dump(mode="json"),
        )
