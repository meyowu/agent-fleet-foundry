"""Thin Typer/Rich presentation layer."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any, cast

import typer
from pydantic import JsonValue
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from agent_fleet import __version__
from agent_fleet.bootstrap import build_container
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.ids import IdPrefix, new_id
from agent_fleet.domain.models import (
    ApprovalChoice,
    FakeScenario,
    JsonEnvelope,
    JsonError,
    RunStatus,
    jsonable,
)
from agent_fleet.domain.security import Redactor
from agent_fleet.domain.trust import TrustMode

app = typer.Typer(
    name="fleet",
    help=(
        "Local-first Agent Fleet control plane with exact fake, Docker, or explicit "
        "local-unsafe execution boundaries."
    ),
    no_args_is_help=True,
)
patch_app = typer.Typer(help="Inspect or explicitly apply candidate patches.")
app.add_typer(patch_app, name="patch")
permissions_app = typer.Typer(help="Inspect and manage exact user-owned permission scopes.")
app.add_typer(permissions_app, name="permissions")
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
            "phase": "4",
            "runtime": "fake",
            "runtimes": ["fake", "pydantic-ai"],
            "sandbox": "fake",
            "sandboxes": ["docker", "fake", "local-unsafe"],
        },
    )


@app.command()
def doctor(
    json_output: JsonFlag = False,
    path: Annotated[
        Path, typer.Option("--path", help="Path to inspect for optional Git context.")
    ] = Path("."),
    sandbox: Annotated[
        str | None,
        typer.Option(
            "--sandbox",
            help="Sandbox to inspect; omitted uses registered project state or fake.",
        ),
    ] = None,
    docker_image: Annotated[
        str | None,
        typer.Option("--docker-image", help="Preloaded local image for Docker preflight."),
    ] = None,
) -> None:
    """Diagnose required local foundations and future optional capabilities."""

    redactor = _environment_redactor()

    def operation() -> tuple[JsonValue, list[str]]:
        report = asyncio.run(
            build_container(redactor=redactor).doctor.inspect(
                path,
                sandbox_name=sandbox,
                docker_image=docker_image,
            )
        )
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
    sandbox: Annotated[
        str,
        typer.Option("--sandbox", help="Sandbox provider: fake, docker, or local-unsafe."),
    ] = "fake",
    docker_image: Annotated[
        str | None,
        typer.Option("--docker-image", help="Existing local image required by Docker."),
    ] = None,
    allow_unsafe_local: Annotated[
        bool,
        typer.Option(
            "--allow-unsafe-local",
            help="Separately confirm direct host execution for local-unsafe.",
        ),
    ] = False,
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
    trust_mode: Annotated[
        str | None,
        typer.Option("--trust-mode", help="Reviewed policy; omitted preserves existing settings."),
    ] = None,
    allow_paths: Annotated[
        list[str] | None,
        typer.Option(
            "--allow-path",
            help="Reviewed path ceiling; repeat. Default: existing scope, else repository.",
        ),
    ] = None,
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
        policy_preview = container.permissions.review_initialization(
            path,
            mode=_parse_trust_mode(trust_mode) if trust_mode is not None else None,
            allowed_paths=tuple(allow_paths) if allow_paths is not None else None,
        )
        reviewed_mode = TrustMode(cast(str, policy_preview["trust_mode"]))
        reviewed_paths = tuple(cast(list[str], policy_preview["allowed_paths"]))
        preview_data = container.projects.preview(
            path,
            runtime_name=runtime,
            provider_model=provider_model,
            credential_ref=credential_ref,
            sandbox_name=sandbox,
            docker_image=docker_image,
        )
        preview_data["proposed_user_policy"] = policy_preview
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
                    (f"Sandbox: {sandbox} (security_level={preview_data['security_level']})"),
                    access_summary,
                    security_warning,
                    f"User trust mode: {reviewed_mode.value}; "
                    f"reviewed paths: {', '.join(reviewed_paths)}",
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
        initialized = asyncio.run(
            container.bootstrap.initialize(
                path,
                runtime_name=runtime,
                provider_model=provider_model,
                credential_ref=credential_ref,
                sandbox_name=sandbox,
                docker_image=docker_image,
                allow_unsafe_local=allow_unsafe_local,
                expected_proposal_hash=proposal_hash,
                trust_mode=reviewed_mode,
                allowed_paths=reviewed_paths,
                expected_trust_revision=cast(int, policy_preview["policy_revision"]),
            )
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
    sandbox: Annotated[
        str | None,
        typer.Option(
            "--sandbox",
            help="Optional exact match for the sandbox reviewed during fleet init.",
        ),
    ] = None,
    allow_unsafe_local: Annotated[
        bool,
        typer.Option(
            "--allow-unsafe-local",
            help="Separately confirm direct host execution for this local-unsafe run.",
        ),
    ] = False,
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
    """Run the reviewed project through its exact registered sandbox boundary."""

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
                allow_unsafe_local=allow_unsafe_local,
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
    for_run: Annotated[
        bool, typer.Option("--run", help="Allow matching scope within this run.")
    ] = False,
    always: Annotated[
        bool, typer.Option("--always", help="Persist only the exact project scope.")
    ] = False,
    scope: Annotated[
        str | None, typer.Option("--scope", help="Required value for --always: project.")
    ] = None,
    json_output: JsonFlag = False,
) -> None:
    """Approve an exact request once, for its run, or for this project."""

    redactor = _environment_redactor()

    def operation() -> JsonValue:
        if (
            sum((once, for_run, always)) != 1
            or (always and scope != "project")
            or (not always and scope is not None)
        ):
            raise FleetError(
                ErrorCode.APPROVAL_INVALID,
                "Choose exactly one of --once, --run, or --always --scope project.",
                "Inspect the request and select its precise authorization duration.",
            )
        choice = (
            ApprovalChoice.ALLOW_ONCE
            if once
            else ApprovalChoice.ALLOW_RUN
            if for_run
            else ApprovalChoice.ALLOW_ALWAYS
        )
        grant = build_container(redactor=redactor).approvals.approve(request_id, choice=choice)
        return grant.model_dump(mode="json")

    _present("fleet approve", json_output, operation, redactor=redactor)


@permissions_app.command("list")
def permissions_list(
    project: Annotated[Path, typer.Option("--project")] = Path("."),
    json_output: JsonFlag = False,
) -> None:
    """List the selected project's effective settings and exact rules."""
    redactor = _environment_redactor()
    _present(
        "fleet permissions list",
        json_output,
        lambda: build_container(redactor=redactor).permissions.list_rules(project),
        redactor=redactor,
    )


@permissions_app.command("explain")
def permissions_explain(
    identifier: Annotated[str, typer.Argument(help="Rule ID or approval request ID.")],
    json_output: JsonFlag = False,
) -> None:
    """Explain an exact rule or re-evaluate the policy for a pending request."""
    redactor = _environment_redactor()
    _present(
        "fleet permissions explain",
        json_output,
        lambda: build_container(redactor=redactor).permissions.explain(identifier),
        redactor=redactor,
    )


@permissions_app.command("revoke")
def permissions_revoke(
    identifier: Annotated[str, typer.Argument(help="Exact rule or grant ID to revoke.")],
    json_output: JsonFlag = False,
) -> None:
    """Revoke a scope without deleting its history."""
    redactor = _environment_redactor()
    _present(
        "fleet permissions revoke",
        json_output,
        lambda: build_container(redactor=redactor).permissions.revoke(identifier),
        redactor=redactor,
    )


@permissions_app.command("reset")
def permissions_reset(
    project: Annotated[Path, typer.Option("--project")] = Path("."),
    json_output: JsonFlag = False,
) -> None:
    """Revoke a project's persistent rules, preserving its reviewed path ceiling."""
    redactor = _environment_redactor()
    _present(
        "fleet permissions reset",
        json_output,
        lambda: build_container(redactor=redactor).permissions.reset(project),
        redactor=redactor,
    )


@permissions_app.command("configure")
def permissions_configure(
    mode: Annotated[str, typer.Option("--mode", help="User-owned execution trust mode.")],
    project: Annotated[Path, typer.Option("--project")] = Path("."),
    allow_paths: Annotated[
        list[str] | None,
        typer.Option(
            "--allow-path",
            help="Reviewed path ceiling; repeat. Omitted preserves the current scope.",
        ),
    ] = None,
    json_output: JsonFlag = False,
) -> None:
    """Set the project's user-owned mode and reviewed candidate path ceiling."""
    redactor = _environment_redactor()

    def operation() -> JsonValue:
        parsed_mode = _parse_trust_mode(mode)
        return (
            build_container(redactor=redactor)
            .permissions.configure(
                project,
                mode=parsed_mode,
                allowed_paths=tuple(allow_paths) if allow_paths is not None else None,
            )
            .model_dump(mode="json")
        )

    _present(
        "fleet permissions configure",
        json_output,
        operation,
        redactor=redactor,
    )


def _parse_trust_mode(value: str) -> TrustMode:
    try:
        return TrustMode(value)
    except ValueError:
        raise FleetError(
            ErrorCode.CONFIG_INVALID,
            "The requested trust mode is unsupported.",
            "Choose safe, balanced, or autonomous-sandbox.",
        ) from None


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


@app.command()
def recover(
    run_id: Annotated[str, typer.Argument(help="Exact persisted run to recover")],
    confirm_owner_stopped: Annotated[
        bool,
        typer.Option(
            "--confirm-owner-stopped",
            help="Confirm no other Fleet process still owns this exact run.",
        ),
    ] = False,
    json_output: JsonFlag = False,
) -> None:
    """Fail an interrupted run and reconcile only its persisted resource leases."""

    redactor = _environment_redactor()

    def operation() -> JsonValue:
        if not confirm_owner_stopped:
            raise FleetError(
                ErrorCode.RECOVERY_REQUIRED,
                "Exact-run recovery requires confirmation that its prior owner stopped.",
                "Retry with --confirm-owner-stopped only after checking no Fleet process "
                "still owns this run.",
                details={"run_id": run_id},
            )
        container = build_container(redactor=redactor)
        before = [lease.lease_id for lease in container.state.outstanding_leases(run_id)]
        original_status = container.state.get_run(run_id).status
        result = asyncio.run(container.recovery.recover_run(run_id))
        after = [lease.lease_id for lease in container.state.outstanding_leases(run_id)]
        after_set = set(after)
        return jsonable(
            {
                "run_id": result.run_id,
                "status": result.status.value,
                "recovered": bool(set(before) - after_set)
                or original_status in {RunStatus.RUNNING, RunStatus.APPLYING},
                "recovered_lease_ids": [item for item in before if item not in after_set],
                "outstanding_lease_ids": after,
            }
        )

    _present("fleet recover", json_output, operation, redactor=redactor)


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
    serialized = jsonable(data)
    if not json_output and raw_key and isinstance(serialized, dict):
        safe_raw_value, _ = active_redactor.redact_data(serialized[raw_key])
        console.print(safe_raw_value, markup=False, highlight=False)
        return
    safe_data, _ = active_redactor.redact_data(serialized)
    if json_output:
        _print_json(
            JsonEnvelope(
                ok=True,
                command=command,
                correlation_id=new_id(IdPrefix.CORRELATION),
                data=jsonable(safe_data),
            )
        )
        return
    _print_human(safe_data)


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
    safe_data, _ = active_redactor.redact_data(data)
    safe_warnings, _ = active_redactor.redact_data(warnings)
    if json_output:
        _print_json(
            JsonEnvelope(
                ok=True,
                command=command,
                correlation_id=new_id(IdPrefix.CORRELATION),
                data=jsonable(safe_data),
                warnings=[str(item) for item in safe_warnings],
            )
        )
        return
    _print_human(safe_data)
    for warning in safe_warnings:
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
    runtime_clause = (
        "The configured model provider was contacted from the control plane;"
        if status.get("runtime") == "pydantic-ai"
        else "The fake runtime made no model-provider call;"
    )
    sandbox = status.get("sandbox") or status.get("sandbox_name") or "fake"
    if sandbox == "docker":
        sandbox_clause = (
            "project commands used the isolated Docker sandbox and remain subject to the "
            "reported evidence and proof gaps."
        )
    elif sandbox == "local-unsafe":
        sandbox_clause = (
            "local-unsafe executed project commands directly on the host without isolation."
        )
    else:
        sandbox_clause = "FakeSandbox did not execute project code or provide OS isolation."
    return [f"{runtime_clause} {sandbox_clause}"]


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
