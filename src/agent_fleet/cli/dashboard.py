"""Thin foreground launcher for the read-only local dashboard."""

from __future__ import annotations

from contextlib import suppress
from pathlib import Path
from typing import Annotated

import typer

from agent_fleet.adapters.dashboard.http import DashboardServer
from agent_fleet.adapters.persistence.dashboard import SqliteDashboardReader
from agent_fleet.application.dashboard import DashboardService
from agent_fleet.bootstrap import ApplicationContainer, build_container, resolve_state_root
from agent_fleet.domain.errors import FleetError


def dashboard_service(container: ApplicationContainer) -> DashboardService:
    return DashboardService(
        state=container.state,
        reader=SqliteDashboardReader(container.state_root / "state.db"),
        inspection=container.inspection,
        conversations=container.conversation_store,
        organization=container.organization,
        artifacts=container.artifacts,
        repository=container.repository,
        clock=container.workflow.clock,
        redactor=container.redactor,
        plan_reviews=container.plan_reviews,
    )


def register_dashboard_command(app: typer.Typer) -> None:
    @app.command("dashboard")
    def dashboard(
        path: Annotated[
            Path, typer.Argument(help="Exact registered repository to observe.")
        ] = Path("."),
        port: Annotated[
            int, typer.Option(min=0, max=65535, help="Loopback port; 0 selects a free port.")
        ] = 0,
    ) -> None:
        """Observe local agents and evidence. No execution or approval from the browser."""
        root = resolve_state_root()
        if not (root / "state.db").is_file():
            typer.echo(
                "No registered Fleet state. Initialize a project in the terminal first.", err=True
            )
            raise typer.Exit(1)
        try:
            container = build_container(root, migrate=False)
            service = dashboard_service(container)
            project = service.open_project(path)
            # Validate query-only support before opening a listening socket.
            service.catalog(project)
            with DashboardServer(service, project, port=port) as server:
                typer.echo(f"Fleet local observer: {server.origin}")
                typer.echo(f"Access token (paste in browser): {server.token}")
                typer.echo("Read-only. Keep this terminal open; Ctrl-C stops and revokes access.")
                with suppress(KeyboardInterrupt):
                    server.serve_forever(poll_interval=0.2)
        except FleetError as error:
            typer.echo(
                f"Dashboard unavailable ({error.code.value}); inspect local state in the terminal.",
                err=True,
            )
            raise typer.Exit(1) from None
        except OSError:
            typer.echo(
                "Dashboard could not open the local listener or state. No task was changed.",
                err=True,
            )
            raise typer.Exit(1) from None
