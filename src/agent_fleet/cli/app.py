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
    help=(
        "Local-first Agent Fleet control plane (Phase 2: fake or explicit BYOK "
        "PydanticAI runtime; FakeSandbox only)."
    ),
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
        lambda: {
            "version": __version__,
            "phase": "2",
            "runtime": "fake",
            "runtimes": ["fake", "pydantic-ai"],
            "sandbox": "fake",
        },
    )


@app.command()
def doctor(
    json_output: JsonFlag = False,
    path: Annotated[
        Path, typer.Option("--path", help="Path to inspect for optional Git context.")
    ] = Path("."),
) -> None:
    """Diagnose required local foundations and future optional capabilities."""

    redactor = _environment_redactor()

    def operation() -> tuple[JsonValue, list[str]]:
        report = build_container(redactor=redactor).doctor.inspect(path)
        return report.model_dump(mode="json"), report.warnings

    _present_with_warnings("fleet doctor", json_output, operation, redactor=redactor)


@app.command("init")
def init_command(
    path: Annotated[Path, typer.Argument(help="Git repository to initialize")] = Path("."),
    runtime: Annotated[
        str,
        typer.Option("--runtime", help="Runtime adapter: fake or pydantic-ai."),
    ] = "fake",
    provider_model: Annotated[
        str | None,
        typer.Option(
            "--provider-model",
            help="Explicit provider:model identifier required by pydantic-ai.",
        ),
    ] = None,
    credential_ref: Annotated[
        str | None,
        typer.Option(
            "--credential-ref",
            help="Explicit env:NAME credential reference; never a raw secret.",
        ),
    ] = None,
    sandbox: Annotated[str, typer.Option("--sandbox")] = "fake",
    yes: Annotated[
        bool,
        typer.Option(
            "--yes",
            help="Apply noninteractively; use --preview first to review the exact proposal.",
        ),
    ] = False,
    preview: Annotated[
        bool,
        typer.Option(
            "--preview", help="Profile and show the complete proposal without writing state."
        ),
    ] = False,
    json_output: JsonFlag = False,
) -> None:
    """Register a Git repository and apply a validated minimal `.fleet/` tree."""

    redactor = _environment_redactor()

    def operation() -> tuple[JsonValue, list[str]]:
        if preview and yes:
            raise FleetError(
                ErrorCode.CONFIG_INVALID,
                "Initialization preview and apply confirmation are mutually exclusive.",
                "Use `--preview` to inspect without writes, or `--yes` to apply.",
            )
        container = build_container(migrate=False, redactor=redactor)
        preview_data = container.projects.preview(
            path,
            runtime_name=runtime,
            provider_model=provider_model,
            credential_ref=credential_ref,
            sandbox_name=sandbox,
        )
        if preview:
            return _initialization_result(preview_data)
        if json_output and not yes:
            raise FleetError(
                ErrorCode.CONFIG_INVALID,
                "Machine-readable initialization requires explicit --yes.",
                "Review the proposed files in human mode, then retry JSON mode with --yes.",
            )
        if not yes:
            proposal_patch = preview_data["proposal_patch"]
            security_warning = preview_data["security_warning"]
            if not isinstance(proposal_patch, str) or not isinstance(security_warning, str):
                raise RuntimeError("invalid project preview")
            access_summary = (
                "Provider access: disabled; no model call will occur."
                if runtime == "fake"
                else (
                    "Provider access: the control plane may contact the selected provider only "
                    "after confirmation and credential validation."
                )
            )
            summary = "\n".join(
                [
                    f"Runtime: {runtime}",
                    f"Provider model: {provider_model or 'none'}",
                    (
                        "Credential reference: supplied; its value was not read during preview."
                        if credential_ref is not None
                        else "Credential reference: none"
                    ),
                    f"Sandbox: {sandbox} (security_level=fake)",
                    access_summary,
                    security_warning,
                ]
            )
            console.print(Panel.fit(summary, title="Execution and access boundary"))
            console.print(
                Panel(proposal_patch, title="Exact .fleet proposal patch"),
                markup=False,
                highlight=False,
            )
            if not typer.confirm("Apply exactly this validated .fleet proposal?"):
                raise typer.Abort()
        proposal_hash = preview_data.get("proposal_sha256")
        if not isinstance(proposal_hash, str):
            raise RuntimeError("invalid project proposal identity")
        initialized = container.projects.initialize(
            path,
            runtime_name=runtime,
            provider_model=provider_model,
            credential_ref=credential_ref,
            sandbox_name=sandbox,
            expected_proposal_hash=proposal_hash,
        )
        return _initialization_result(initialized)

    _present_with_warnings("fleet init", json_output, operation, redactor=redactor)


@app.command()
def run(
    goal: Annotated[str, typer.Argument(help="Bounded code-change goal")],
    project: Annotated[Path, typer.Option("--project")] = Path("."),
    runtime: Annotated[
        str | None,
        typer.Option(
            "--runtime",
            help="Must match the reviewed project runtime; omitted uses project state.",
        ),
    ] = None,
    provider_model: Annotated[
        str | None,
        typer.Option(
            "--provider-model",
            help="Must match the provider:model reviewed during fleet init.",
        ),
    ] = None,
    credential_ref: Annotated[
        str | None,
        typer.Option(
            "--credential-ref",
            help="Must match the env:NAME reference reviewed during fleet init.",
        ),
    ] = None,
    sandbox: Annotated[str, typer.Option("--sandbox")] = "fake",
    fake_scenario: Annotated[
        FakeScenario | None,
        typer.Option(
            "--fake-scenario",
            help=(
                "Explicit fake-runtime test script: success, fail, repair, approval, "
                "inconclusive, verifier_mutation, direct, or single_engineer."
            ),
        ),
    ] = None,
    json_output: JsonFlag = False,
) -> None:
    """Run the reviewed project runtime through FakeSandbox evidence boundaries."""

    redactor = _environment_redactor()

    def operation() -> tuple[JsonValue, list[str]]:
        container = build_container(redactor=redactor)
        result = asyncio.run(
            container.workflow.start(
                project_path=project,
                goal=goal,
                runtime_name=runtime,
                provider_model=provider_model,
                credential_ref=credential_ref,
                sandbox_name=sandbox,
                fake_scenario=fake_scenario,
            )
        )
        data = container.inspection.status(result.run_id)
        return jsonable(data), _runtime_warnings(data)

    _present_with_warnings("fleet run", json_output, operation, redactor=redactor)


@app.command()
def status(run_id: Annotated[str, typer.Argument()], json_output: JsonFlag = False) -> None:
    """Show one persisted run state."""

    redactor = _environment_redactor()

    _present(
        "fleet status",
        json_output,
        lambda: jsonable(build_container(redactor=redactor).inspection.status(run_id)),
        redactor=redactor,
    )


@app.command()
def logs(run_id: Annotated[str, typer.Argument()], json_output: JsonFlag = False) -> None:
    """Read ordered append-only run events."""

    redactor = _environment_redactor()

    _present(
        "fleet logs",
        json_output,
        lambda: jsonable(build_container(redactor=redactor).inspection.logs(run_id)),
        redactor=redactor,
    )


@app.command()
def artifacts(run_id: Annotated[str, typer.Argument()], json_output: JsonFlag = False) -> None:
    """List persisted artifact metadata and hashes for a run."""

    redactor = _environment_redactor()

    _present(
        "fleet artifacts",
        json_output,
        lambda: jsonable(build_container(redactor=redactor).inspection.artifacts_for_run(run_id)),
        redactor=redactor,
    )


@patch_app.command("show")
def patch_show(run_id: Annotated[str, typer.Argument()], json_output: JsonFlag = False) -> None:
    """Show the canonical Git patch recorded for a run."""

    redactor = _environment_redactor()

    _present(
        "fleet patch show",
        json_output,
        lambda: {
            "run_id": run_id,
            "patch": build_container(redactor=redactor).patches.show(run_id),
        },
        raw_key="patch",
        redactor=redactor,
    )


@patch_app.command("apply")
def patch_apply(run_id: Annotated[str, typer.Argument()], json_output: JsonFlag = False) -> None:
    """Explicitly apply a reviewed patch after identity/base/status checks."""

    redactor = _environment_redactor()

    def operation() -> JsonValue:
        container = build_container(redactor=redactor)
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

    _present("fleet patch apply", json_output, operation, redactor=redactor)


@app.command()
def approve(
    request_id: Annotated[str, typer.Argument()],
    once: Annotated[bool, typer.Option("--once", help="Issue one exact, short-lived use.")] = False,
    json_output: JsonFlag = False,
) -> None:
    """Approve one exact persisted Phase 1 intent."""

    redactor = _environment_redactor()

    def operation() -> JsonValue:
        if not once:
            raise FleetError(
                ErrorCode.APPROVAL_INVALID,
                "Phase 1 approvals require the explicit --once flag.",
                "Retry with `fleet approve <request-id> --once`.",
            )
        grant = build_container(redactor=redactor).approvals.approve_once(request_id)
        return grant.model_dump(mode="json")

    _present("fleet approve", json_output, operation, redactor=redactor)


@app.command()
def deny(
    request_id: Annotated[str, typer.Argument()],
    reason: Annotated[str | None, typer.Option("--reason")] = None,
    json_output: JsonFlag = False,
) -> None:
    """Deny one pending persisted intent."""

    redactor = _environment_redactor()

    def operation() -> JsonValue:
        build_container(redactor=redactor).approvals.deny(request_id, reason)
        return {"request_id": request_id, "resolution": "denied"}

    _present("fleet deny", json_output, operation, redactor=redactor)


@app.command()
def resume(run_id: Annotated[str, typer.Argument()], json_output: JsonFlag = False) -> None:
    """Resume a durable approved fake workflow without duplicating its logical action."""

    redactor = _environment_redactor()

    def operation() -> tuple[JsonValue, list[str]]:
        container = build_container(redactor=redactor)
        result = asyncio.run(container.workflow.resume(run_id))
        data = container.inspection.status(result.run_id)
        return jsonable(data), _runtime_warnings(data)

    _present_with_warnings("fleet resume", json_output, operation, redactor=redactor)


@app.command()
def cancel(run_id: Annotated[str, typer.Argument()], json_output: JsonFlag = False) -> None:
    """Cancel a non-completed run and clean only Fleet-owned resources."""

    redactor = _environment_redactor()

    def operation() -> JsonValue:
        container = build_container(redactor=redactor)
        result = asyncio.run(container.cancellation.cancel(run_id))
        return jsonable(container.inspection.status(result.run_id))

    _present("fleet cancel", json_output, operation, redactor=redactor)


def _present(
    command: str,
    json_output: bool,
    operation: Callable[[], Any],
    *,
    raw_key: str | None = None,
    redactor: Redactor | None = None,
) -> None:
    active_redactor = redactor or _environment_redactor()
    try:
        data = operation()
    except FleetError as error:
        _present_error(command, error, json_output, active_redactor)
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
    *,
    redactor: Redactor | None = None,
) -> None:
    active_redactor = redactor or _environment_redactor()
    try:
        data, warnings = operation()
    except FleetError as error:
        _present_error(command, error, json_output, active_redactor)
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


def _present_error(
    command: str,
    error: FleetError,
    json_output: bool,
    redactor: Redactor,
) -> None:
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


def _environment_redactor() -> Redactor:
    return Redactor(
        [item for item in os.environ.get("AGENT_FLEET_REDACT_VALUES", "").split(",") if item]
    )


def _runtime_warnings(status: dict[str, object]) -> list[str]:
    if status.get("runtime") == "pydantic-ai":
        return [
            "The configured model provider was contacted from the control plane; "
            "FakeSandbox did not execute project code or provide OS isolation."
        ]
    return ["Fake runtime/sandbox: no model call, project execution, or OS isolation occurred."]


def _initialization_result(data: dict[str, object]) -> tuple[JsonValue, list[str]]:
    """Move all init/preview warnings into the standard envelope/presentation channel."""

    warnings: list[str] = []
    profile_warnings = data.get("warnings")
    if isinstance(profile_warnings, list):
        warnings.extend(item for item in profile_warnings if isinstance(item, str))
    for key in ("security_warning", "warning"):
        value = data.get(key)
        if isinstance(value, str):
            warnings.append(value)
    if not any("sandbox" in warning.casefold() for warning in warnings):
        warnings.extend(_runtime_warnings(data))
    normalized = {
        key: value
        for key, value in data.items()
        if key not in {"warnings", "security_warning", "warning"}
    }
    return jsonable(normalized), list(dict.fromkeys(warnings))


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
    if code in {
        ErrorCode.CONFIG_INVALID,
        ErrorCode.CREDENTIAL_INVALID,
        ErrorCode.CREDENTIAL_MISSING,
        ErrorCode.PATH_OUTSIDE_SCOPE,
        ErrorCode.PROVIDER_UNSUPPORTED,
        ErrorCode.RUNTIME_CAPABILITY_MISSING,
        ErrorCode.SANDBOX_UNAVAILABLE,
    }:
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
    if code in {
        ErrorCode.PROVIDER_FAILED,
        ErrorCode.RUNTIME_BUDGET_EXCEEDED,
        ErrorCode.RUNTIME_OUTPUT_INVALID,
        ErrorCode.RUNTIME_RETRY_EXHAUSTED,
        ErrorCode.RUNTIME_TIMEOUT,
        ErrorCode.RUNTIME_UNAVAILABLE,
    }:
        return 5
    return 1


def main() -> None:
    app()


if __name__ == "__main__":
    main()
