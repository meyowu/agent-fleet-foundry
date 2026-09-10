"""Bounded session inspection and one-use, exact human review capabilities."""

from __future__ import annotations

import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Literal, cast

from pydantic import JsonValue, ValidationError

from agent_fleet.application.artifacts import ArtifactService
from agent_fleet.application.evolution import OrganizationService
from agent_fleet.application.inspection import InspectionService
from agent_fleet.application.patches import PatchService
from agent_fleet.application.plan_review import PlanReviewService
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.evolution import FleetPatchProposalRecord
from agent_fleet.domain.fleet_plan import FleetPlan, validate_fleet_plan
from agent_fleet.domain.models import (
    ApprovalChoice,
    ApprovalStatus,
    ArtifactKind,
    Run,
    RunStatus,
    TaskSpec,
    jsonable,
)
from agent_fleet.domain.security import canonical_json_hash
from agent_fleet.domain.session_review import (
    ApprovalReview,
    BaselineSessionBinding,
    BaselineSessionReview,
    ModelSelectionReview,
    OrganizationReview,
    PatchReview,
    PlanReview,
    SessionSelection,
)
from agent_fleet.ports.clock import Clock
from agent_fleet.ports.state_store import StateStore

type View = dict[str, JsonValue]
_REVIEW_LIFETIME = timedelta(minutes=5)
_MAX_TICKETS = 32
_MAX_ISSUED_CODES = 4096


@dataclass(frozen=True)
class _Ticket:
    selection: SessionSelection | BaselineSessionBinding
    expected: (
        PatchReview
        | OrganizationReview
        | ApprovalReview
        | PlanReview
        | ModelSelectionReview
        | BaselineSessionReview
    )
    issued_at: datetime
    expires_at: datetime


class SessionReviewService:
    """Not a runtime tool. Tickets are held only by the selected foreground UI.

    Tickets are consumed even if validation/application fails, are invalid after
    restart and never enter conversation summaries or model context. The guarded
    services revalidate the exact expected identities before executing effects.
    """

    def __init__(
        self,
        state: StateStore,
        artifacts: ArtifactService,
        inspection: InspectionService,
        patches: PatchService,
        organization: OrganizationService,
        clock: Clock,
        *,
        plan_reviews: PlanReviewService | None = None,
        code_factory: Callable[[], str] = lambda: secrets.token_hex(8),
    ) -> None:
        self.state = state
        self.artifacts = artifacts
        self.inspection = inspection
        self.patches = patches
        self.organization = organization
        self.clock = clock
        self.plan_reviews = plan_reviews
        self.code_factory = code_factory
        self._tickets: dict[str, _Ticket] = {}
        self._issued_codes: set[str] = set()
        self._baseline_codes: set[str] = set()
        self._lock = Lock()

    def _run(self, selection: SessionSelection) -> Run:
        if selection.run_id is None:
            raise _invalid("This conversation has no current run to review.")
        run = self.state.get_run(selection.run_id)
        if run.project_id != selection.project_id or run.parent_run_id is not None:
            raise _invalid("This review is not bound to the selected project and root run.")
        return run

    def _artifact(
        self, run: Run, identifier: str | None, digest: str | None, kind: ArtifactKind
    ) -> str:
        if identifier is None or digest is None:
            raise _invalid("The current run has no complete task/plan artifact yet.")
        metadata = self.state.get_artifact(identifier)
        if (
            metadata.project_id != run.project_id
            or metadata.run_id != run.run_id
            or metadata.task_id != run.task_id
            or metadata.kind is not kind
            or metadata.sha256 != digest
        ):
            raise _integrity()
        return self.artifacts.read_bounded_text(identifier, max_bytes=2_097_152)

    def plan(self, selection: SessionSelection, *, prepare: bool = False) -> View:
        run = self._run(selection)
        view = {**selection.model_dump(mode="json"), **self.run_plan(run.run_id)}
        if prepare:
            if not run.plan_review_required or self.plan_reviews is None:
                raise _invalid(
                    "This run has no pre-execution plan gate; inspection is not approval."
                )
            checkpoint = self.plan_reviews.inspect(run)
            if run.status is not RunStatus.PAUSED_FOR_PLAN or checkpoint.status != "pending":
                raise _invalid("Only the exact pending pre-execution plan can be approved.")
            view.update(
                self._issue(
                    selection,
                    PlanReview(run_id=run.run_id, checkpoint_sha256=checkpoint.checkpoint_sha256),
                )
            )
        return view

    def run_plan(self, run_id: str) -> View:
        """The same bounded evidence view for session and one-shot inspection."""
        run = self.state.get_run(run_id)
        if run.parent_run_id is not None:
            raise _invalid("Review the root plan, not an internal child.")
        self.organization.register_run_secrets(run)
        try:
            task = TaskSpec.model_validate_json(
                self._artifact(
                    run, run.task_spec_artifact_id, run.task_spec_hash, ArtifactKind.TASK_SPEC
                )
            )
            plan = FleetPlan.model_validate_json(
                self._artifact(
                    run, run.fleet_plan_artifact_id, run.fleet_plan_hash, ArtifactKind.FLEET_PLAN
                )
            )
        except ValidationError:
            raise _integrity() from None
        if (
            task.run_id != run.run_id
            or task.task_id != run.task_id
            or task.base_revision != run.base_revision
            or task.config_snapshot_hash != run.config_snapshot_hash
        ):
            raise _integrity()
        validate_fleet_plan(plan, task)
        view: View = {
            "run_id": run.run_id,
            "project_id": run.project_id,
            "mode": "inspection_only",
            "notice": (
                "This shows the recorded task and plan; it is not a pre-execution approval gate."
            ),
            "task_sha256": run.task_spec_hash,
            "plan_sha256": run.fleet_plan_hash,
            "task": task.model_dump(mode="json"),
            "plan": plan.model_dump(mode="json"),
        }
        if run.plan_review_required:
            if self.plan_reviews is None:
                raise _invalid("The required durable plan review service is unavailable.")
            checkpoint = self.plan_reviews.inspect(run)
            view.update(
                {
                    "mode": "pre_execution_gate",
                    "checkpoint": jsonable(checkpoint.safe_projection()),
                    "notice": (
                        "This task paused before workspace or execution-agent dispatch. "
                        "/plan approve prepares an exact decision; confirmation approves only. "
                        "/resume consumes the approved plan once and continues without replanning."
                    ),
                }
            )
        return view

    def diff(self, selection: SessionSelection, *, prepare: bool = False) -> View:
        run = self._run(selection)
        if prepare and run.status is not RunStatus.READY_FOR_REVIEW:
            raise _invalid("Only a READY_FOR_REVIEW candidate can be prepared for application.")
        expected, patch = self.patches.review(run.run_id)
        view: View = {
            **selection.model_dump(mode="json"),
            "action": "patch_apply" if prepare else "patch_review",
            "base_revision": run.base_revision,
            "target_status_fingerprint": run.target_status_fingerprint,
            "patch_artifact_id": run.patch_artifact_id,
            "patch_sha256": run.patch_sha256,
            "config_snapshot_sha256": run.config_snapshot_hash,
            "organization_revision": expected.organization.revision,
            "patch": patch,
            "evidence": jsonable(self.inspection.status(run.run_id)),
        }
        if prepare:
            view.update(self._issue(selection, expected))
        return view

    def fleet_patch(
        self,
        selection: SessionSelection,
        *,
        action: str,
        proposal_id: str | None = None,
    ) -> View:
        if action not in {"list", "show", "diff", "apply", "rollback"} or (
            action == "list" and proposal_id is not None
        ):
            raise _invalid("Use /fleet-patch list|show|diff|apply|rollback [proposal-id].")
        project = self.state.get_project(selection.project_id)
        if action == "list" or proposal_id is None:
            proposals = self.organization.list_proposals(Path(project.canonical_root), limit=51)
            choices: list[JsonValue] = [
                {
                    "proposal_id": item.patch.fleet_patch_id,
                    "source_run_id": item.source_run_id,
                    "proposal_sha256": item.proposal_sha256,
                    "base_revision": item.base.revision,
                    "rollback_of": item.patch.rollback_of,
                }
                for item in proposals[:50]
            ]
            if action == "list":
                return {"proposals": choices, "has_more": len(proposals) > 50}
            current = [item for item in proposals if item.source_run_id == selection.run_id]
            candidates = current if current else proposals
            if len(candidates) != 1 or len(proposals) > 50:
                return {
                    "selection_required": True,
                    "notice": "Choose an exact proposal ID; no proposal was selected or applied.",
                    "proposals": choices,
                    "has_more": len(proposals) > 50,
                }
            proposal_id = candidates[0].patch.fleet_patch_id
        proposal = self.organization.get_proposal(proposal_id)
        if proposal.base.project_id != selection.project_id:
            raise _invalid("The proposal belongs to another project.")
        view = self._proposal_view(proposal, action)
        if action in {"apply", "rollback"}:
            expected, reviewed = self.organization.review(
                proposal_id, action=cast(Literal["apply", "rollback"], action)
            )
            view = self._proposal_view(reviewed, action)
            view["organization_revision"] = expected.organization.revision
            view.update(self._issue(selection, expected))
        return view

    @staticmethod
    def _proposal_view(proposal: FleetPatchProposalRecord, action: str) -> View:
        return {
            "action": action,
            "proposal_id": proposal.patch.fleet_patch_id,
            "proposal_sha256": proposal.proposal_sha256,
            "base_revision": proposal.base.revision,
            "before_tree_sha256": proposal.before_tree_sha256,
            "after_tree_sha256": proposal.after_tree_sha256,
            "rationale": proposal.patch.rationale,
            "text_diff": proposal.text_diff,
            "semantic_changes": [
                item.model_dump(mode="json") for item in proposal.semantic_changes
            ],
            "notice": (
                "Rollback restores this proposal's before tree through a new inverse operation; "
                "the displayed diff is the original change being reversed."
                if action == "rollback"
                else "Organization changes require explicit confirmation and affect future tasks."
            ),
        }

    def _issue(
        self,
        selection: SessionSelection | BaselineSessionBinding,
        expected: PatchReview
        | OrganizationReview
        | ApprovalReview
        | PlanReview
        | ModelSelectionReview
        | BaselineSessionReview,
    ) -> View:
        now = self.clock.now()
        with self._lock:
            self._tickets = {
                code: ticket
                for code, ticket in self._tickets.items()
                if ticket.issued_at <= now < ticket.expires_at
                and ticket.selection.conversation_id != selection.conversation_id
            }
            if len(self._tickets) >= _MAX_TICKETS:
                raise _invalid("Too many pending reviews; dismiss one before preparing another.")
            if len(self._issued_codes) >= _MAX_ISSUED_CODES:
                raise _invalid(
                    "This process reached its review limit; reopen the session to review again."
                )
            code = self.code_factory()
            if (
                code in self._issued_codes
                or len(code) != 16
                or any(c not in "0123456789abcdef" for c in code)
            ):
                raise _invalid("A unique bounded review code could not be created.")
            expires_at = now + _REVIEW_LIFETIME
            if isinstance(expected, BaselineSessionReview):
                expires_at = min(expires_at, expected.expires_at)
                if expires_at <= now:
                    raise _invalid("The original baseline review has expired.")
                self._baseline_codes.add(code)
            self._tickets[code] = _Ticket(selection, expected, now, expires_at)
            self._issued_codes.add(code)
        return {
            "confirmation_required": True,
            "confirmation_code": code,
            "expires_at": expires_at.isoformat(),
            "instruction": (
                f"Review this exact change, then enter /confirm {code}; /dismiss cancels it."
            ),
        }

    def confirmation_family(self, code: str) -> Literal["baseline", "ordinary", "unknown"]:
        """Classify consumed codes too, so they never fall through into history."""
        with self._lock:
            if code in self._baseline_codes:
                return "baseline"
            return "ordinary" if code in self._issued_codes else "unknown"

    def prepare_baseline(self, expected: BaselineSessionReview) -> View:
        return self._issue(expected.binding, expected)

    def confirm_baseline(
        self,
        code: str,
        *,
        authorize: Callable[[BaselineSessionReview, Callable[[], None]], View],
        validate_selection: Callable[[BaselineSessionBinding], None],
    ) -> View:
        with self._lock:
            ticket = self._tickets.pop(code, None)
        if ticket is None or not isinstance(ticket.expected, BaselineSessionReview):
            raise _invalid("The exact baseline review is unknown, consumed or dismissed.")
        expected = ticket.expected

        def validate() -> None:
            now = self.clock.now()
            if not ticket.issued_at <= now < ticket.expires_at:
                raise _invalid("The original baseline review has expired.")
            validate_selection(expected.binding)

        validate()
        return authorize(expected, validate)

    def confirm(
        self,
        selection: SessionSelection,
        code: str,
        *,
        current_selection: Callable[[], SessionSelection],
        approve_request: Callable[[str, ApprovalChoice], View] | None = None,
        select_model: Callable[[ModelSelectionReview, Callable[[], None]], View] | None = None,
        current_model_selection: Callable[[], SessionSelection] | None = None,
    ) -> View:
        with self._lock:
            ticket = self._tickets.pop(code, None)
        now = self.clock.now()
        if (
            ticket is None
            or ticket.selection != selection
            or not ticket.issued_at <= now < ticket.expires_at
        ):
            raise _invalid(
                "Review code is unknown, expired, consumed or belongs to another selection."
            )
        expected = ticket.expected

        if isinstance(expected, BaselineSessionReview):
            raise _invalid("Baseline reviews require the separate baseline controller.")

        if isinstance(expected, ModelSelectionReview):
            if select_model is None or current_model_selection is None:
                raise _invalid("The exact model selection service is unavailable.")

            def validate_model_selection() -> None:
                checked_at = self.clock.now()
                if (
                    current_model_selection() != ticket.selection
                    or not ticket.issued_at <= checked_at < ticket.expires_at
                ):
                    raise _invalid(
                        "The reviewed session changed or expired before model selection."
                    )

            return select_model(expected, validate_model_selection)

        def validate_selection() -> None:
            # Invoked under the same publication guard used by new Run
            # admission. Check selection again without retargeting the action.
            checked_at = self.clock.now()
            if (
                current_selection() != ticket.selection
                or not ticket.issued_at <= checked_at < ticket.expires_at
            ):
                raise _invalid("The reviewed session changed or expired before application.")

        if isinstance(expected, PlanReview):
            if self.plan_reviews is None:
                raise _invalid("The required durable plan review service is unavailable.")
            checkpoint = self.plan_reviews.approve(
                self.state.get_run(expected.run_id),
                expected_sha256=expected.checkpoint_sha256,
                validate_review=validate_selection,
            )
            return {
                "run_id": expected.run_id,
                "checkpoint": jsonable(checkpoint.safe_projection()),
                "notice": "Plan approved only. Enter /resume to execute this frozen plan once.",
            }
        if isinstance(expected, ApprovalReview):
            validate_selection()
            request = self.state.get_approval(expected.request_id)
            if (
                approve_request is None
                or request.status is not ApprovalStatus.PENDING
                or canonical_json_hash(request.model_dump(mode="json")) != expected.request_sha256
            ):
                raise _invalid("The exact reviewed approval request changed or was resolved.")
            # ApprovalService revalidates the immutable intent/current ceilings;
            # StateStore atomically resolves the original request, never latest.
            return approve_request(expected.request_id, expected.choice)
        if isinstance(expected, PatchReview):
            run, result = self.patches.apply(
                expected.run_id, expected_review=expected, validate_review=validate_selection
            )
            return {
                "run_id": run.run_id,
                "status": run.status.value,
                "application": result.model_dump(mode="json"),
            }
        operation = (
            self.organization.apply if expected.action == "apply" else self.organization.rollback
        )
        return operation(
            expected.proposal_id, expected_review=expected, validate_review=validate_selection
        ).model_dump(mode="json")

    def prepare_model_selection(
        self,
        selection: SessionSelection,
        expected: ModelSelectionReview,
        profile: dict[str, object],
    ) -> View:
        if expected.selection != selection:
            raise _invalid("The model review belongs to a different session selection.")
        return {
            **selection.model_dump(mode="json"),
            "action": "model_selection",
            "target_role": expected.role_id,
            "target_default": expected.role_id is None,
            "expected_selection_revision": expected.expected_selection_revision,
            "profile": jsonable(profile),
            "config_snapshot_sha256": expected.config_snapshot_sha256,
            "notice": "Future tasks only; historical Run model bindings remain immutable. "
            "No provider was contacted.",
            **self._issue(selection, expected),
        }

    def prepare_approval(
        self, selection: SessionSelection, request_id: str, choice: ApprovalChoice
    ) -> View:
        request = self.state.get_approval(request_id)
        request_run = self.state.get_run(request.run_id)
        if (
            request.status is not ApprovalStatus.PENDING
            or selection.run_id is None
            or request_run.project_id != selection.project_id
            or (
                request.run_id != selection.run_id and request_run.parent_run_id != selection.run_id
            )
            or request.expires_at <= self.clock.now()
            or choice is ApprovalChoice.DENY
            or choice not in request.available_choices
        ):
            raise _invalid("The selected request or approval duration is no longer available.")
        expected = ApprovalReview(
            request_id=request_id,
            request_sha256=canonical_json_hash(request.model_dump(mode="json")),
            choice=choice,
        )
        return {
            **selection.model_dump(mode="json"),
            "action": "approve",
            "request": request.model_dump(mode="json"),
            "choice": choice.value,
            "notice": (
                "Confirm only this exact permission scope. Approval never resumes automatically."
            ),
            **self._issue(selection, expected),
        }

    def dismiss(self, selection: SessionSelection | BaselineSessionBinding) -> View:
        with self._lock:
            codes = [
                code
                for code, ticket in self._tickets.items()
                if ticket.selection.conversation_id == selection.conversation_id
                and ticket.selection.project_id == selection.project_id
            ]
            for code in codes:
                del self._tickets[code]
        return {"dismissed": bool(codes), "conversation_id": selection.conversation_id}

    def invalidate_selection(self) -> None:
        """A newly selected foreground session requires fresh review, without I/O."""
        with self._lock:
            self._tickets.clear()


def _invalid(message: str) -> FleetError:
    return FleetError(
        ErrorCode.APPROVAL_INVALID,
        message,
        "Inspect the current session and prepare a new exact review; nothing was authorized.",
    )


def _integrity() -> FleetError:
    return FleetError(
        ErrorCode.ARTIFACT_INTEGRITY_FAILED,
        "The task or plan fails its exact recorded identity/hash binding.",
        "Inspect original artifacts; unvalidated plan content was not displayed.",
    )
