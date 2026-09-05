"""Presentation-only commands for reviewable organization evolution."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Protocol

import typer
from pydantic import JsonValue

from agent_fleet.application.evolution import OrganizationService
from agent_fleet.domain.evolution import OrganizationPublicationResult
from agent_fleet.domain.security import Redactor

JsonFlag = Annotated[bool, typer.Option("--json", help="Emit a stable v1alpha1 JSON envelope.")]


class Presenter(Protocol):
    def __call__(
        self,
        command: str,
        json_output: bool,
        operation: Callable[[], JsonValue],
        *,
        raw_key: str | None = None,
        redactor: Redactor | None = None,
    ) -> None: ...


class WarningPresenter(Protocol):
    def __call__(
        self,
        command: str,
        json_output: bool,
        operation: Callable[[], tuple[JsonValue, list[str]]],
        *,
        redactor: Redactor | None = None,
    ) -> None: ...


def _result(value: OrganizationPublicationResult) -> tuple[JsonValue, list[str]]:
    return value.model_dump(mode="json", exclude={"warnings"}), list(value.warnings)


def _visible_diff(value: str) -> str:
    # Content is untrusted even after review: do not execute terminal controls.
    return "".join(
        f"\\x{ord(char):02x}"
        if (ord(char) < 32 and char not in "\n\t") or ord(char) == 127
        else char
        for char in value
    )


def _detail_view(data: dict[str, JsonValue], *, json_output: bool) -> JsonValue:
    return data if json_output else {"display": json.dumps(data, ensure_ascii=False, indent=2)}


def register_evolution_commands(
    app: typer.Typer,
    *,
    service_factory: Callable[[Redactor], OrganizationService],
    redactor_factory: Callable[[], Redactor],
    presenter: Presenter,
    warning_presenter: WarningPresenter,
) -> None:
    commands = typer.Typer(
        help="Review, explicitly apply, and roll back versioned organization rules."
    )
    app.add_typer(commands, name="fleet-patch")

    @commands.command("list")
    def list_proposals(
        path: Annotated[Path, typer.Option("--path", help="Registered project repository.")] = Path(
            "."
        ),
        limit: Annotated[int, typer.Option(min=1, max=100, help="Maximum proposals to show.")] = 50,
        json_output: JsonFlag = False,
    ) -> None:
        redactor = redactor_factory()

        def operation() -> JsonValue:
            return [
                {
                    "proposal_id": item.patch.fleet_patch_id,
                    "proposal_sha256": item.proposal_sha256,
                    "base_revision": item.base.revision,
                    "rollback_of": item.patch.rollback_of,
                    "created_at": item.created_at.isoformat(),
                }
                for item in service_factory(redactor).list_proposals(path, limit=limit)
            ]

        presenter("fleet fleet-patch list", json_output, operation, redactor=redactor)

    @commands.command("show")
    def show(proposal_id: Annotated[str, typer.Argument()], json_output: JsonFlag = False) -> None:
        redactor = redactor_factory()

        def operation() -> JsonValue:
            proposal = service_factory(redactor).get_proposal(proposal_id)
            return _detail_view(
                {"proposal_sha256": proposal.proposal_sha256, **proposal.model_dump(mode="json")},
                json_output=json_output,
            )

        presenter(
            "fleet fleet-patch show", json_output, operation, raw_key="display", redactor=redactor
        )

    @commands.command("diff")
    def diff(proposal_id: Annotated[str, typer.Argument()], json_output: JsonFlag = False) -> None:
        redactor = redactor_factory()

        def operation() -> JsonValue:
            proposal = service_factory(redactor).get_proposal(proposal_id)
            return {
                "proposal_id": proposal.patch.fleet_patch_id,
                "proposal_sha256": proposal.proposal_sha256,
                "text_diff": proposal.text_diff
                if json_output
                else _visible_diff(proposal.text_diff),
                "semantic_changes": [
                    item.model_dump(mode="json") for item in proposal.semantic_changes
                ],
            }

        presenter(
            "fleet fleet-patch diff", json_output, operation, raw_key="text_diff", redactor=redactor
        )

    @commands.command("apply")
    def apply(proposal_id: Annotated[str, typer.Argument()], json_output: JsonFlag = False) -> None:
        """Explicitly authorize this exact persisted proposal; never called by CoS."""
        redactor = redactor_factory()
        warning_presenter(
            "fleet fleet-patch apply",
            json_output,
            lambda: _result(service_factory(redactor).apply(proposal_id)),
            redactor=redactor,
        )

    @commands.command("rollback")
    def rollback(
        proposal_id: Annotated[str, typer.Argument()], json_output: JsonFlag = False
    ) -> None:
        """Create and apply a new inverse of the exact current-head proposal."""
        redactor = redactor_factory()
        warning_presenter(
            "fleet fleet-patch rollback",
            json_output,
            lambda: _result(service_factory(redactor).rollback(proposal_id)),
            redactor=redactor,
        )

    @commands.command("operation")
    def operation_show(
        operation_id: Annotated[str, typer.Argument()], json_output: JsonFlag = False
    ) -> None:
        """Inspect an exact durable publication/recovery receipt without changing it."""
        redactor = redactor_factory()
        presenter(
            "fleet fleet-patch operation",
            json_output,
            lambda: _detail_view(
                service_factory(redactor).get_operation(operation_id).model_dump(mode="json"),
                json_output=json_output,
            ),
            raw_key="display",
            redactor=redactor,
        )

    @commands.command("recover")
    def recover(
        operation_id: Annotated[str, typer.Argument()],
        owner_stopped: Annotated[
            bool,
            typer.Option("--owner-stopped", help="Confirm the original publisher has stopped."),
        ] = False,
        json_output: JsonFlag = False,
    ) -> None:
        """Reconcile an exact interrupted operation without exchanging directories again."""
        redactor = redactor_factory()
        warning_presenter(
            "fleet fleet-patch recover",
            json_output,
            lambda: _result(
                service_factory(redactor).recover(operation_id, owner_stopped=owner_stopped)
            ),
            redactor=redactor,
        )
