"""Thin Typer/Rich presentation layer."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

import typer
from pydantic import JsonValue
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from agent_fleet import __version__
from agent_fleet.bootstrap import build_container
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.ids import IdPrefix, new_id
from agent_fleet.domain.models import FakeScenario, JsonEnvelope, JsonError, jsonable
from agent_fleet.domain.security import Redactor

app = typer.Typer(
    name="fleet",
    help="Local deterministic Agent Fleet control plane (Phase 0/1: fake adapters only).",
    no_args_is_help=True,
)
patch_app = typer.Typer(help="Inspect or explicitly apply candidate patches.")
app.add_typer(patch_app, name="patch")
console = Console()
error_console = Console(stderr=True)

JsonFlag = Annotated[bool, typer.Option("--json", help="Emit a stable v1alpha1 JSON envelope.")]


@app.command()
def version(json_output: JsonFlag = False) -> None:
    """Show the installed Agent Fleet package version."""

    _present(
        "fleet version",
        json_output,
        lambda: {"version": __version__, "phase": "0/1", "runtime": "fake"},
    )


@app.command()
def doctor(
    json_output: JsonFlag = False,
    path: Annotated[
        Path, typer.Option("--path", help="Path to inspect for optional Git context.")
    ] = Path("."),
) -> None:
    """Diagnose required local foundations and future optional capabilities."""

    def operation() -> tuple[JsonValue, list[str]]:
        report = build_container().doctor.inspect(path)
        return report.model_dump(mode="json"), report.warnings

    _present_with_warnings("fleet doctor", json_output, operation)


@app.command("init")
def init_command(
    path: Annotated[Path, typer.Argument(help="Git repository to initialize")] = Path("."),
    runtime: Annotated[str, typer.Option("--runtime")] = "fake",
    sandbox: Annotated[str, typer.Option("--sandbox")] = "fake",
    yes: Annotated[
        bool, typer.Option("--yes", help="Apply only the displayed .fleet proposal.")
    ] = False,
    json_output: JsonFlag = False,
) -> None:
    """Register a Git repository and apply a validated minimal `.fleet/` tree."""

    def operation() -> JsonValue:
        container = build_container(migrate=False)
        if json_output and not yes:
            raise FleetError(
                ErrorCode.CONFIG_INVALID,
                "Machine-readable initialization requires explicit --yes.",
                "Review the proposed files in human mode, then retry JSON mode with --yes.",
            )
        if not yes:
            proposed = container.projects.preview(path)
            console.print(Panel.fit("\n".join(proposed), title="Proposed files"))
            if not typer.confirm("Apply this validated .fleet configuration?"):
                raise typer.Abort()
        return jsonable(
            container.projects.initialize(path, runtime_name=runtime, sandbox_name=sandbox)
        )

    _present("fleet init", json_output, operation)


@app.command()
def run(
    goal: Annotated[str, typer.Argument(help="Bounded code-change goal")],
    project: Annotated[Path, typer.Option("--project")] = Path("."),
    runtime: Annotated[str, typer.Option("--runtime")] = "fake",
    sandbox: Annotated[str, typer.Option("--sandbox")] = "fake",
    fake_scenario: Annotated[
        FakeScenario,
        typer.Option(
            "--fake-scenario",
            help=(
                "Deterministic Phase 1 script: success, fail, repair, approval, "
                "inconclusive, or verifier_mutation."
            ),
        ),
    ] = FakeScenario.SUCCESS,
    json_output: JsonFlag = False,
) -> None:
    """Run the deterministic fake workflow and persist its evidence."""

    def operation() -> tuple[JsonValue, list[str]]:
        container = build_container()
        result = asyncio.run(
            container.workflow.start(
                project_path=project,
                goal=goal,
                runtime_name=runtime,
                sandbox_name=sandbox,
                fake_scenario=fake_scenario,
            )
        )
        data = container.inspection.status(result.run_id)
        warnings = [
            "Fake runtime/sandbox: no model call, project execution, or OS isolation occurred."
        ]
        return jsonable(data), warnings

    _present_with_warnings("fleet run", json_output, operation)


@app.command()
def status(run_id: Annotated[str, typer.Argument()], json_output: JsonFlag = False) -> None:
    """Show one persisted run state."""

    _present(
        "fleet status",
        json_output,
        lambda: jsonable(build_container().inspection.status(run_id)),
    )


@app.command()
def logs(run_id: Annotated[str, typer.Argument()], json_output: JsonFlag = False) -> None:
    """Read ordered append-only run events."""

    _present(
        "fleet logs",
        json_output,
        lambda: jsonable(build_container().inspection.logs(run_id)),
    )


@app.command()
def artifacts(run_id: Annotated[str, typer.Argument()], json_output: JsonFlag = False) -> None:
    """List persisted artifact metadata and hashes for a run."""

    _present(
        "fleet artifacts",
        json_output,
        lambda: jsonable(build_container().inspection.artifacts_for_run(run_id)),
    )


@patch_app.command("show")
def patch_show(run_id: Annotated[str, typer.Argument()], json_output: JsonFlag = False) -> None:
    """Show the canonical Git patch recorded for a run."""

    _present(
        "fleet patch show",
        json_output,
        lambda: {"run_id": run_id, "patch": build_container().patches.show(run_id)},
        raw_key="patch",
    )


@patch_app.command("apply")
def patch_apply(run_id: Annotated[str, typer.Argument()], json_output: JsonFlag = False) -> None:
    """Explicitly apply a reviewed patch after identity/base/status checks."""

    def operation() -> JsonValue:
        container = build_container()
        run_result, apply_result = container.patches.apply(run_id)
        return jsonable(
            {
                "run_id": run_result.run_id,
                "status": run_result.status.value,
                "applied": apply_result.applied,
                "base_revision": apply_result.head_revision,
                "changed_paths": apply_result.changed_paths,
            }
        )

    _present("fleet patch apply", json_output, operation)


@app.command()
def approve(
    request_id: Annotated[str, typer.Argument()],
    once: Annotated[bool, typer.Option("--once", help="Issue one exact, short-lived use.")] = False,
    json_output: JsonFlag = False,
) -> None:
    """Approve one exact persisted Phase 1 intent."""

    def operation() -> JsonValue:
        if not once:
            raise FleetError(
                ErrorCode.APPROVAL_INVALID,
                "Phase 1 approvals require the explicit --once flag.",
                "Retry with `fleet approve <request-id> --once`.",
            )
        grant = build_container().approvals.approve_once(request_id)
        return grant.model_dump(mode="json")

    _present("fleet approve", json_output, operation)


@app.command()
def deny(
    request_id: Annotated[str, typer.Argument()],
    reason: Annotated[str | None, typer.Option("--reason")] = None,
    json_output: JsonFlag = False,
) -> None:
    """Deny one pending persisted intent."""

    def operation() -> JsonValue:
        build_container().approvals.deny(request_id, reason)
        return {"request_id": request_id, "resolution": "denied"}

    _present("fleet deny", json_output, operation)


@app.command()
def resume(run_id: Annotated[str, typer.Argument()], json_output: JsonFlag = False) -> None:
    """Resume a durable approved fake workflow without duplicating its logical action."""

    def operation() -> tuple[JsonValue, list[str]]:
        container = build_container()
        result = asyncio.run(container.workflow.resume(run_id))
        return (
            jsonable(container.inspection.status(result.run_id)),
            ["Fake runtime/sandbox remains non-isolating and did not execute project code."],
        )

    _present_with_warnings("fleet resume", json_output, operation)


@app.command()
def cancel(run_id: Annotated[str, typer.Argument()], json_output: JsonFlag = False) -> None:
    """Cancel a non-completed run and clean only Fleet-owned resources."""

    def operation() -> JsonValue:
        container = build_container()
        result = asyncio.run(container.cancellation.cancel(run_id))
        return jsonable(container.inspection.status(result.run_id))

    _present("fleet cancel", json_output, operation)


def _present(
    command: str,
    json_output: bool,
    operation: Callable[[], Any],
    *,
    raw_key: str | None = None,
) -> None:
    try:
        data = operation()
    except FleetError as error:
        _present_error(command, error, json_output)
        raise typer.Exit(code=_exit_code(error.code)) from error
    if json_output:
        _print_json(
            JsonEnvelope(
                ok=True,
                command=command,
                correlation_id=new_id(IdPrefix.CORRELATION),
                data=jsonable(data),
            )
        )
        return
    if raw_key and isinstance(data, dict):
        console.print(data[raw_key], markup=False, highlight=False)
        return
    _print_human(data)


def _present_with_warnings(
    command: str,
    json_output: bool,
    operation: Callable[[], tuple[JsonValue, list[str]]],
) -> None:
    try:
        data, warnings = operation()
    except FleetError as error:
        _present_error(command, error, json_output)
        raise typer.Exit(code=_exit_code(error.code)) from error
    if json_output:
        _print_json(
            JsonEnvelope(
                ok=True,
                command=command,
                correlation_id=new_id(IdPrefix.CORRELATION),
                data=data,
                warnings=warnings,
            )
        )
        return
    _print_human(data)
    for warning in warnings:
        console.print(f"[yellow]Warning:[/yellow] {warning}")


def _present_error(command: str, error: FleetError, json_output: bool) -> None:
    redactor = Redactor(
        [item for item in os.environ.get("AGENT_FLEET_REDACT_VALUES", "").split(",") if item]
    )
    message, _ = redactor.redact_text(error.message)
    remediation, _ = redactor.redact_text(error.remediation)
    details, _ = redactor.redact_data(error.details)
    if json_output:
        _print_json(
            JsonEnvelope(
                ok=False,
                command=command,
                correlation_id=new_id(IdPrefix.CORRELATION),
                data=None,
                error=JsonError(
                    code=error.code.value,
                    message=message,
                    remediation=remediation,
                    details=jsonable(details),
                ),
            )
        )
    else:
        error_console.print(
            Panel.fit(
                f"[bold]{error.code.value}[/bold]\n{message}\n\n{remediation}",
                title="Agent Fleet error",
                border_style="red",
            )
        )


def _print_json(envelope: JsonEnvelope) -> None:
    typer.echo(json.dumps(envelope.model_dump(mode="json"), sort_keys=True))


def _print_human(data: Any) -> None:
    if isinstance(data, list):
        if not data:
            console.print("No records.")
            return
        table = Table(show_header=True)
        first = data[0]
        if isinstance(first, dict):
            keys = list(first.keys())
            for key in keys:
                table.add_column(str(key))
            for row in data:
                table.add_row(*(str(row.get(key, "")) for key in keys))
            console.print(table)
            return
    if isinstance(data, dict):
        table = Table(show_header=False)
        table.add_column("Field", style="cyan")
        table.add_column("Value")
        for key, value in data.items():
            table.add_row(str(key), str(value))
        console.print(table)
        return
    console.print(str(data))


def _exit_code(code: ErrorCode) -> int:
    if code in {ErrorCode.CONFIG_INVALID, ErrorCode.PATH_OUTSIDE_SCOPE}:
        return 2
    if code in {
        ErrorCode.PROJECT_NOT_GIT,
        ErrorCode.PROJECT_NOT_INITIALIZED,
        ErrorCode.PROJECT_DIRTY,
        ErrorCode.PATCH_TARGET_DIVERGED,
    }:
        return 3
    if code in {ErrorCode.APPROVAL_REQUIRED, ErrorCode.APPROVAL_DENIED, ErrorCode.APPROVAL_INVALID}:
        return 4
    return 1


def main() -> None:
    app()


if __name__ == "__main__":
    main()
