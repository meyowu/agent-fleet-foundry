"""Project-bound, bounded conversations over the existing owned workflow."""

from __future__ import annotations

import asyncio
import secrets
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal, cast

from pydantic import Field, JsonValue, ValidationError

from agent_fleet.application.approvals import ApprovalService
from agent_fleet.application.artifacts import ArtifactService
from agent_fleet.application.bootstrap import BootstrapService
from agent_fleet.application.conversation_results import bounded_summary
from agent_fleet.application.inspection import InspectionService
from agent_fleet.application.model_profiles import ModelProfileService
from agent_fleet.application.permission_policy import PermissionPolicyService
from agent_fleet.application.resources import CancellationService
from agent_fleet.application.session_review import SessionReviewService
from agent_fleet.application.workflow import WorkflowEngine
from agent_fleet.domain.conversation import (
    Conversation,
    ConversationContext,
    ConversationContextEntry,
    ConversationSubmission,
    ConversationTurn,
    ConversationTurnStatus,
)
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.ids import IdPrefix
from agent_fleet.domain.models import (
    AgentRole,
    ApprovalChoice,
    ApprovalStatus,
    FakeScenario,
    FrozenStrictModel,
    Project,
    Run,
    RunStatus,
    WorkflowStage,
    jsonable,
)
from agent_fleet.domain.security import Redactor, sha256_bytes
from agent_fleet.domain.session_review import SessionSelection
from agent_fleet.domain.trust import TrustMode
from agent_fleet.ports.conversation import ConversationStore
from agent_fleet.ports.id_generator import IdGenerator
from agent_fleet.ports.repository import RepositoryPort
from agent_fleet.ports.secret_store import SecretStatus, SecretStore, SecretStoreError
from agent_fleet.ports.state_store import StateStore

ConversationView = dict[str, JsonValue]
ConversationProgressPage = dict[str, JsonValue]


@dataclass(frozen=True)
class ChatExecutionOptions:
    runtime_name: str | None = None
    sandbox_name: str | None = None
    provider_model: str | None = None
    credential_ref: str | None = None
    fake_scenario: FakeScenario | None = None
    allow_unsafe_local: bool = False
    review_plan: bool = False


class SessionBootstrapOptions(FrozenStrictModel):
    runtime_name: Literal["fake", "pydantic-ai"] = "fake"
    provider_model: str | None = Field(default=None, max_length=256)
    credential_ref: str | None = Field(default=None, max_length=256)
    docker_image: str = Field(min_length=1, max_length=512)
    trust_mode: TrustMode = TrustMode.SAFE
    allowed_paths: tuple[str, ...] = Field(default=(".",), min_length=1, max_length=32)


@dataclass(frozen=True)
class _BootstrapReview:
    code: str
    root: Path
    options: SessionBootstrapOptions
    proposal_sha256: str
    trust_revision: int
    issued_at: datetime
    expires_at: datetime


class ConversationService:
    def __init__(
        self,
        store: ConversationStore,
        state: StateStore,
        repository: RepositoryPort,
        workflow: WorkflowEngine,
        inspection: InspectionService,
        artifacts: ArtifactService,
        approvals: ApprovalService,
        permissions: PermissionPolicyService,
        cancellation: CancellationService,
        ids: IdGenerator,
        redactor: Redactor,
        secrets: SecretStore,
        reviews: SessionReviewService,
        bootstrap: BootstrapService,
        model_profiles: ModelProfileService | None = None,
    ) -> None:
        self.store = store
        self.state = state
        self.repository = repository
        self.workflow = workflow
        self.inspection = inspection
        self.artifact_service = artifacts
        self.approvals = approvals
        self.permission_service = permissions
        self.cancellation = cancellation
        self.ids = ids
        self.redactor = redactor
        self.secrets = secrets
        self.reviews = reviews
        self.bootstrap = bootstrap
        self.model_profiles = model_profiles
        self._bootstrap_review: _BootstrapReview | None = None
        self._selected: dict[str, str] = {}
        self._executions: dict[str, asyncio.Task[Run]] = {}
        self._cancellations: dict[str, asyncio.Task[None]] = {}

    def select(
        self,
        project_path: Path,
        *,
        conversation_id: str | None = None,
        create_new: bool = False,
    ) -> ConversationView:
        if conversation_id is not None and create_new:
            raise _invalid("Choose an existing conversation or create a new one, not both.")
        info = self.repository.inspect(project_path)
        project = self.state.get_project_by_root(info.root)
        if project is None:
            raise FleetError(
                ErrorCode.PROJECT_NOT_INITIALIZED,
                "Chat requires a registered project.",
                "Review and initialize the repository before starting chat.",
            )
        if info.identity_hash != project.identity_hash:
            raise _invalid("The repository no longer matches its registered identity.")
        self._register_redaction(project)
        if conversation_id is not None:
            conversation = self.store.get(project.project_id, conversation_id)
        elif create_new:
            conversation = self.store.create(project.project_id, project.identity_hash)
        else:
            previous = self.store.latest(project.project_id, project.identity_hash)
            conversation = (
                previous
                if previous is not None
                else self.store.create(project.project_id, project.identity_hash)
            )
        if conversation.repository_identity != project.identity_hash:
            raise _invalid("The conversation does not belong to this repository identity.")
        # Changing the foreground selection requires another review even when
        # later returning to the same conversation (selection ABA).
        self.reviews.invalidate_selection()
        self._selected[conversation.conversation_id] = project.project_id
        return self.status(conversation.conversation_id)

    def _conversation(self, conversation_id: str) -> Conversation:
        project_id = self._selected.get(conversation_id)
        if project_id is None:
            raise _invalid("Select this conversation against its registered project first.")
        project = self.state.get_project(project_id)
        self._register_redaction(project)
        conversation = self.store.get(project_id, conversation_id)
        if conversation.repository_identity != project.identity_hash:
            raise _invalid("The selected conversation repository binding is invalid.")
        return conversation

    def _register_redaction(self, project: Project) -> None:
        # Read only the previously reviewed exact reference; do not discover
        # ambient provider keys or make a provider/model request for inspection.
        if self.model_profiles is not None and self.model_profiles.prepare_project(project):
            return
        self._register_credential(project.credential_ref)

    def _register_credential(self, reference: str | None) -> None:
        if reference is None:
            return
        inspection = self.secrets.inspect(reference)
        if inspection.status is SecretStatus.MISSING:
            return
        failed = inspection.status is SecretStatus.INVALID
        if not failed:
            try:
                self.secrets.resolve(reference)
            except SecretStoreError:
                failed = True
        if failed:
            raise FleetError(
                ErrorCode.CREDENTIAL_INVALID,
                "The registered credential cannot safely establish conversation redaction.",
                "Restore its valid configured value before inspecting sensitive local history.",
            ) from None

    def _turn(self, conversation: Conversation) -> ConversationTurn | None:
        turn: ConversationTurn | None
        if conversation.active_turn_id is not None:
            turn = self.store.get_turn(conversation.project_id, conversation.active_turn_id)
        else:
            turns = self.store.list_turns(
                conversation.project_id, conversation.conversation_id, limit=1
            )
            turn = turns[0] if turns else None
        if turn is not None:
            self._register_run_redaction(turn.binding.run_id)
            # Read persisted summaries again after registering pinned keys.
            turn = self.store.get_turn(conversation.project_id, turn.binding.turn_id)
        return turn

    def _register_run_redaction(self, run_id: str) -> None:
        run = self.state.get_run(run_id)
        if self.model_profiles is not None and run.model_bindings_sha256 is not None:
            self.model_profiles.inspect_bindings(
                self.state.get_project(run.project_id),
                root_run_id=run.run_id,
                expected_sha256=run.model_bindings_sha256,
            )
        else:
            self._register_credential(run.credential_ref)

    def preview_initialization(
        self, project_path: Path, *, options: SessionBootstrapOptions
    ) -> ConversationView:
        """Prepare exactly one foreground public bootstrap, never a fake registration."""
        self._bootstrap_review = None
        info = self.repository.inspect(project_path)
        if self.state.get_project_by_root(info.root) is not None:
            raise _invalid(
                "This repository is already registered; initialization is not an update path."
            )
        policy = self.permission_service.review_initialization(
            Path(info.root), mode=options.trust_mode, allowed_paths=options.allowed_paths
        )
        preview = self.bootstrap.projects.preview(
            Path(info.root),
            runtime_name=options.runtime_name,
            provider_model=options.provider_model,
            credential_ref=options.credential_ref,
            sandbox_name="docker",
            docker_image=options.docker_image,
        )
        proposal_hash = preview.get("proposal_sha256")
        revision = policy.get("policy_revision")
        if not isinstance(proposal_hash, str) or type(revision) is not int:
            raise _invalid("Public bootstrap returned an invalid review identity.")
        code = secrets.token_hex(8)
        issued_at = self.artifact_service.clock.now()
        expires_at = issued_at + timedelta(minutes=5)
        result = cast(
            ConversationView,
            jsonable(
                {
                    **preview,
                    "proposed_user_policy": policy,
                    "confirmation_code": code,
                    "expires_at": expires_at.isoformat(),
                    "instruction": (
                        f"Enter initialize {code} to run the disposable Docker canary and publish "
                        "only after its patch, verification and cleanup evidence pass."
                    ),
                }
            ),
        )
        self._reject_secret(result)
        self._bootstrap_review = _BootstrapReview(
            code, Path(info.root), options, proposal_hash, revision, issued_at, expires_at
        )
        return result

    async def initialize(self, *, code: str) -> ConversationView:
        reviewed, self._bootstrap_review = self._bootstrap_review, None
        if (
            reviewed is None
            or reviewed.code != code
            or not reviewed.issued_at <= self.artifact_service.clock.now() < reviewed.expires_at
        ):
            raise _invalid("Initialization review is missing, expired or no longer matches.")
        options = reviewed.options
        result = await self.bootstrap.initialize(
            reviewed.root,
            runtime_name=options.runtime_name,
            provider_model=options.provider_model,
            credential_ref=options.credential_ref,
            sandbox_name="docker",
            docker_image=options.docker_image,
            expected_proposal_hash=reviewed.proposal_sha256,
            trust_mode=options.trust_mode,
            allowed_paths=options.allowed_paths,
            expected_trust_revision=reviewed.trust_revision,
        )
        view = cast(ConversationView, jsonable(result))
        self._reject_secret(view)
        return view

    def status(self, conversation_id: str) -> ConversationView:
        conversation = self._conversation(conversation_id)
        return self._view(conversation, self._turn(conversation))

    def _view(self, conversation: Conversation, turn: ConversationTurn | None) -> ConversationView:
        conversation_id = conversation.conversation_id
        if turn is not None:
            self._register_run_redaction(turn.binding.run_id)
        run_data = self.inspection.status(turn.binding.run_id) if turn is not None else None
        warnings: list[str] = []
        if run_data is not None:
            if run_data["sandbox"] == "local-unsafe":
                warnings.append("LOCAL-UNSAFE: host execution is not isolated or verified.")
            elif run_data["sandbox"] == "fake":
                warnings.append("FakeSandbox simulates commands and cannot prove completion.")
            if run_data["status"] == "ready_for_review":
                warnings.append(
                    "Candidate patch is not applied; use /diff and /apply to review it."
                )
            elif run_data["status"] == "paused_for_plan":
                warnings.append(
                    "Paused before execution. Use /plan to inspect, /plan approve and /confirm "
                    "to approve only, then /resume to continue the exact frozen plan."
                )
        retained_owner = bool(
            turn is not None
            and turn.active_claim_id is not None
            and conversation_id not in self._executions
        )
        recovery_required = retained_owner or bool(
            turn is not None and turn.status is ConversationTurnStatus.RECOVERY_REQUIRED
        )
        if recovery_required:
            warnings.append(
                "Execution ownership is unresolved. Inspect the run and use explicit "
                "owner-stopped recovery; chat will not replay it."
            )
        data: ConversationView = {
            "conversation_id": conversation.conversation_id,
            "project_id": conversation.project_id,
            "revision": conversation.revision,
            "active_turn_id": conversation.active_turn_id,
            "turn_id": turn.binding.turn_id if turn is not None else None,
            "run_id": turn.binding.run_id if turn is not None else None,
            "turn_status": turn.status.value if turn is not None else None,
            "run": jsonable(run_data),
            "user_summary": turn.user_summary.text if turn is not None else None,
            "result_summary": (
                turn.result_summary.text
                if turn is not None and turn.result_summary is not None
                else None
            ),
            "summary_truncated": bool(
                turn is not None
                and (
                    turn.user_summary.truncated
                    or (turn.result_summary is not None and turn.result_summary.truncated)
                )
            ),
            "context_omitted_turns": (
                turn.context.through_sequence - len(turn.context.entries) if turn is not None else 0
            ),
            "recovery_required": recovery_required,
            "warnings": cast(JsonValue, warnings),
        }
        self._reject_secret(data)
        return data

    async def submit(
        self,
        conversation_id: str,
        *,
        message: str,
        submission_id: str | None,
        options: ChatExecutionOptions,
    ) -> ConversationView:
        conversation = self._conversation(conversation_id)
        encoded: bytes | None = None
        if isinstance(message, str):
            with suppress(UnicodeError):
                encoded = message.encode("utf-8")
        if encoded is None or not message.strip() or len(encoded) > 16_384:
            raise _invalid("A chat goal must be nonempty and at most 16384 UTF-8 bytes.")
        if message.lstrip().startswith("/"):
            raise _invalid("Slash commands are local controls, not submitted model goals.")
        if conversation_id in self._executions:
            raise _busy()
        key = submission_id or self.ids.new(IdPrefix.CORRELATION)
        prior = self.store.get_submission(conversation.project_id, conversation_id, key)
        if conversation.active_turn_id is not None and prior is None:
            raise _busy()
        context = prior.context if prior is not None else self._context(conversation)
        redacted, _ = self.redactor.redact_text(message)
        submission: ConversationSubmission | None = None
        with suppress(ValidationError):
            submission = ConversationSubmission(
                conversation_id=conversation_id,
                project_id=conversation.project_id,
                repository_identity=conversation.repository_identity,
                submission_key=key,
                expected_revision=conversation.revision,
                context=context,
                user_summary=bounded_summary(redacted, limit=2048),
            )
        if submission is None:
            raise _invalid("The conversation submission is malformed or exceeds its bounds.")
        if prior is not None:
            historical = self.state.get_run(prior.binding.run_id)
            if (
                sha256_bytes(redacted.encode("utf-8")) != prior.binding.user_goal_sha256
                or submission.user_summary != prior.user_summary
                or options.review_plan != historical.plan_review_required
                or any(
                    requested is not None and requested != recorded
                    for requested, recorded in (
                        (options.runtime_name, historical.runtime_name),
                        (options.provider_model, historical.provider_model),
                        (options.credential_ref, historical.credential_ref),
                        (options.sandbox_name, historical.sandbox_name),
                        (options.fake_scenario, historical.fake_scenario),
                    )
                )
            ):
                raise _invalid("The submission key belongs to a different original request.")
            # get_submission validated the immutable turn/Run/audit binding. This
            # is historical inspection, never registration, execution, or resume.
            # It must not require a live credential or the current organization generation.
            return self._view(conversation, prior)
        project = self.state.get_project(conversation.project_id)
        execution = asyncio.create_task(
            self.workflow.start(
                project_path=Path(project.canonical_root),
                goal=message,
                runtime_name=options.runtime_name,
                sandbox_name=options.sandbox_name,
                provider_model=options.provider_model,
                credential_ref=options.credential_ref,
                fake_scenario=options.fake_scenario,
                allow_unsafe_local=options.allow_unsafe_local,
                conversation_submission=submission,
                review_plan=options.review_plan,
            )
        )
        result = await self._await_execution(conversation_id, execution)
        binding = self.store.binding_for_run(result.run_id)
        if binding is None or binding.conversation_id != conversation_id:
            raise _invalid("The submitted result lost its authoritative conversation binding.")
        return self._view(
            self._conversation(conversation_id),
            self.store.get_turn(binding.project_id, binding.turn_id),
        )

    def _context(self, conversation: Conversation) -> ConversationContext:
        turns = self.store.list_turns(
            conversation.project_id, conversation.conversation_id, limit=8
        )
        entries: list[ConversationContextEntry] = []
        for turn in sorted(turns, key=lambda item: item.binding.sequence, reverse=True):
            self._register_run_redaction(turn.binding.run_id)
            if turn.status in {
                ConversationTurnStatus.RUNNING,
                ConversationTurnStatus.WAITING,
                ConversationTurnStatus.RECOVERY_REQUIRED,
            }:
                raise _busy()
            for ref in turn.artifact_refs:
                self.artifact_service.read_bounded_text(ref.artifact_id)
            # This read validates current evidence claims. Historical status is a
            # delivery snapshot, not a claim that the old patch was applied.
            self.inspection.status(turn.binding.run_id)
            entry = ConversationContextEntry(
                turn_id=turn.binding.turn_id,
                sequence=turn.binding.sequence,
                run_id=turn.binding.run_id,
                run_status=turn.observed_run_status,
                user_summary=turn.user_summary,
                result_summary=turn.result_summary,
                artifact_refs=turn.artifact_refs,
            )
            candidate: ConversationContext | None = None
            with suppress(ValidationError):
                candidate = ConversationContext(
                    conversation_id=conversation.conversation_id,
                    project_id=conversation.project_id,
                    through_sequence=conversation.next_turn_sequence - 1,
                    entries=tuple(sorted([*entries, entry], key=lambda item: item.sequence)),
                )
            if candidate is None:
                break
            entries.append(entry)
        result = ConversationContext(
            conversation_id=conversation.conversation_id,
            project_id=conversation.project_id,
            through_sequence=conversation.next_turn_sequence - 1,
            entries=tuple(sorted(entries, key=lambda item: item.sequence)),
        )
        self._reject_secret(result.model_dump(mode="json"))
        return result

    async def resume(
        self, conversation_id: str, *, allow_unsafe_local: bool = False
    ) -> ConversationView:
        conversation = self._conversation(conversation_id)
        turn = self._turn(conversation)
        if turn is None:
            raise _invalid("This conversation has no run to resume.")
        if conversation_id in self._executions:
            raise _busy()
        run = self.state.get_run(turn.binding.run_id)
        if run.sandbox_name == "local-unsafe" and not allow_unsafe_local:
            raise FleetError(
                ErrorCode.UNSAFE_LOCAL_CONFIRMATION_REQUIRED,
                "Resuming this chat would execute directly on the host.",
                "Select --allow-unsafe-local explicitly; chat will not imply confirmation.",
            )
        execution = asyncio.create_task(self.workflow.resume(run.run_id))
        await self._await_execution(conversation_id, execution)
        return self.status(conversation_id)

    async def _await_execution(self, conversation_id: str, execution: asyncio.Task[Run]) -> Run:
        self._executions[conversation_id] = execution
        try:
            return await asyncio.shield(execution)
        except asyncio.CancelledError:
            execution.cancel()
            await _await_stopped(execution)
            raise
        finally:
            if execution.done() and self._executions.get(conversation_id) is execution:
                self._executions.pop(conversation_id, None)

    async def cancel(self, conversation_id: str) -> ConversationView:
        conversation = self._conversation(conversation_id)
        cleanup = self._cancellations.get(conversation_id)
        if cleanup is None:
            # Bind the user's cancellation before scheduling or awaiting work.
            # Another process can submit a newer turn as soon as this owner's
            # cleanup settles; it must never become this operation's target.
            turn = self._turn(conversation)
            cleanup = asyncio.create_task(
                self._cancel(
                    turn.binding.run_id if turn is not None else None,
                    self._executions.get(conversation_id),
                )
            )
            self._cancellations[conversation_id] = cleanup
        cancellation: asyncio.CancelledError | None = None
        try:
            while not cleanup.done():
                try:
                    await asyncio.wait({cleanup})
                except asyncio.CancelledError as error:
                    cancellation = cancellation or error
            cleanup.result()
        finally:
            if cleanup.done() and self._cancellations.get(conversation_id) is cleanup:
                self._cancellations.pop(conversation_id, None)
        if cancellation is not None:
            raise cancellation
        return self.status(conversation_id)

    async def _cancel(self, run_id: str | None, execution: asyncio.Task[Run] | None) -> None:
        if execution is not None and not execution.done():
            execution.cancel()
            await _await_stopped(execution)
        if run_id is not None:
            await self.cancellation.cancel(run_id)

    def artifacts(self, conversation_id: str) -> dict[str, JsonValue]:
        turn = self._turn(self._conversation(conversation_id))
        return {
            "conversation_id": conversation_id,
            "run_id": turn.binding.run_id if turn is not None else None,
            "artifacts": (
                jsonable(self.inspection.artifacts_for_run(turn.binding.run_id))
                if turn is not None
                else []
            ),
        }

    def _review_selection(self, conversation_id: str) -> SessionSelection:
        conversation = self._conversation(conversation_id)
        turn = self._turn(conversation)
        return SessionSelection(
            project_id=conversation.project_id,
            conversation_id=conversation_id,
            conversation_revision=conversation.revision,
            run_id=turn.binding.run_id if turn is not None else None,
        )

    def review(
        self, conversation_id: str, *, action: str, arguments: tuple[str, ...] = ()
    ) -> dict[str, JsonValue]:
        """Human control entry only; no model text is parsed as a review command."""
        selection = self._review_selection(conversation_id)
        if action == "plan" and not arguments:
            view = self.reviews.plan(selection)
        elif action == "plan" and arguments == ("approve",):
            view = self.reviews.plan(selection, prepare=True)
        elif action in {"diff", "apply"} and not arguments:
            view = self.reviews.diff(selection, prepare=action == "apply")
        elif action == "fleet-patch" and 1 <= len(arguments) <= 2:
            view = self.reviews.fleet_patch(
                selection,
                action=arguments[0],
                proposal_id=arguments[1] if len(arguments) == 2 else None,
            )
        elif action == "confirm" and len(arguments) == 1:
            view = self.reviews.confirm(
                selection,
                arguments[0],
                current_selection=lambda: self._review_selection(conversation_id),
                approve_request=lambda request_id, choice: self.approve(
                    conversation_id, request_id, choice=choice
                ),
            )
        elif action == "dismiss" and not arguments:
            view = self.reviews.dismiss(selection)
        else:
            raise _invalid("Invalid session review command; use /help for its exact syntax.")
        self._reject_secret(view)
        return view

    def permissions(
        self, conversation_id: str, *, identifier: str | None = None
    ) -> dict[str, JsonValue]:
        conversation = self._conversation(conversation_id)
        project = self.state.get_project(conversation.project_id)
        if identifier is not None:
            self._require_request(conversation_id, identifier)
            return cast(dict[str, JsonValue], jsonable(self.permission_service.explain(identifier)))
        return cast(
            dict[str, JsonValue],
            jsonable(self.permission_service.list_rules(Path(project.canonical_root))),
        )

    def _require_request(self, conversation_id: str, request_id: str) -> None:
        conversation = self._conversation(conversation_id)
        turn = self._turn(conversation)
        if turn is None:
            raise _invalid("This conversation has no approval request.")
        request = self.state.get_approval(request_id)
        run = self.state.get_run(turn.binding.run_id)
        allowed = {run.run_id}
        allowed.update(item.child_run_id for item in self.workflow.graphs.descendants(run.run_id))
        if request.run_id not in allowed:
            raise FleetError(
                ErrorCode.APPROVAL_INVALID,
                "The request is not owned by this conversation's selected run.",
                "Inspect the exact current parent or child request before approving it.",
            )

    def approve(
        self,
        conversation_id: str,
        request_id: str | None = None,
        *,
        choice: ApprovalChoice | None = None,
    ) -> dict[str, JsonValue]:
        if request_id is None:
            selection = self._review_selection(conversation_id)
            run_ids = [] if selection.run_id is None else [selection.run_id]
            if selection.run_id is not None:
                run_ids.extend(
                    item.child_run_id for item in self.workflow.graphs.descendants(selection.run_id)
                )
            requests = [
                self.state.get_approval(run.pending_approval_id)
                for run_id in run_ids
                if (run := self.state.get_run(run_id)).pending_approval_id is not None
            ]
            pending = [request for request in requests if request.status is ApprovalStatus.PENDING]
            if len(pending) != 1:
                return {
                    "selection_required": len(pending) > 1,
                    "pending_requests": [request.model_dump(mode="json") for request in pending],
                    "notice": (
                        "No sole pending request was selected. "
                        "Use an exact ID when several are waiting."
                    ),
                }
            request_id = pending[0].request_id
            self._require_request(conversation_id, request_id)
            if choice is None:
                return {
                    **self.permissions(conversation_id, identifier=request_id),
                    "instruction": (
                        "Choose /approve --once, --run, or --always --scope project; "
                        "then confirm the exact review code."
                    ),
                }
            view = self.reviews.prepare_approval(selection, request_id, choice)
            self._reject_secret(view)
            return view
        self._require_request(conversation_id, request_id)
        if choice is None:
            return self.permissions(conversation_id, identifier=request_id)
        return self.approvals.approve(request_id, choice=choice).model_dump(mode="json")

    def deny(
        self, conversation_id: str, request_id: str, *, reason: str | None = None
    ) -> dict[str, JsonValue]:
        self._require_request(conversation_id, request_id)
        self.approvals.deny(request_id, reason)
        return {"request_id": request_id, "denied": True}

    def progress(
        self, conversation_id: str, *, cursor: str | None = None, limit: int = 50
    ) -> ConversationProgressPage:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise _invalid("Progress page size must be between 1 and 100.")
        turn = self._turn(self._conversation(conversation_id))
        if turn is None:
            if cursor is not None:
                raise _invalid("A progress cursor cannot refer to an empty conversation.")
            return {"cursor": None, "events": [], "has_more": False}
        run_id = turn.binding.run_id
        after = 0
        if cursor is not None:
            cursor_bytes: bytes | None = None
            with suppress(UnicodeError):
                cursor_bytes = cursor.encode("utf-8")
            if cursor_bytes is None or len(cursor_bytes) > 1024:
                raise _invalid("The progress cursor exceeds its bound.")
            parts = cursor.split(":")
            if len(parts) != 3 or parts[0] != conversation_id or not parts[2].isascii():
                raise _invalid("The progress cursor does not belong to this conversation.")
            if not parts[2].isdigit() or len(parts[2]) > 12:
                raise _invalid("The progress cursor sequence is invalid.")
            if parts[1] == run_id:
                after = int(parts[2])
            else:
                old_binding = self.store.binding_for_run(parts[1])
                if old_binding is None or old_binding.conversation_id != conversation_id:
                    raise _invalid("The progress cursor refers to another conversation.")
        events = self.state.list_events_after(run_id, after_sequence=after, limit=limit)
        result: list[JsonValue] = []
        pending: list[str] = []
        for owned_id in (
            run_id,
            *(child.child_run_id for child in self.workflow.graphs.descendants(run_id)),
        ):
            owned = self.state.get_run(owned_id)
            if (
                owned.status is RunStatus.PAUSED_FOR_APPROVAL
                and owned.pending_approval_id is not None
            ):
                request = self.state.get_approval(owned.pending_approval_id)
                if request.status is ApprovalStatus.PENDING:
                    pending.append(request.request_id)
        allowed = {
            "stage": {item.value for item in WorkflowStage},
            "status": {item.value for item in RunStatus},
            "role": {item.value for item in AgentRole},
        }
        for event in events:
            parts = [event.event_type.replace(".", " ")[:160]]
            for key, values in allowed.items():
                value = event.payload.get(key)
                if isinstance(value, str) and value in values:
                    parts.append(f"{key}={value}")
            item: dict[str, JsonValue] = {
                "event_id": event.event_id,
                "run_id": run_id,
                "sequence": event.sequence,
                "event_type": event.event_type,
                "summary": " ".join(parts),
            }
            if pending:
                item["request_ids"] = cast(JsonValue, pending)
            result.append(item)
        page: ConversationProgressPage = {
            "cursor": f"{conversation_id}:{run_id}:{events[-1].sequence if events else after}",
            "events": result,
            "has_more": len(events) == limit,
        }
        self._reject_secret(page)
        return page

    def _reject_secret(self, value: JsonValue) -> None:
        if self.redactor.contains_secret_data(value):
            raise FleetError(
                ErrorCode.COMMAND_DENIED,
                "Registered secret material cannot enter conversation records or output.",
                "Remove the sensitive content before retrying.",
            )


async def _await_stopped(execution: asyncio.Task[Run]) -> None:
    while not execution.done():
        try:
            await asyncio.wait({execution})
        except asyncio.CancelledError:
            continue
    if not execution.cancelled():
        # Cleanup/domain errors must stay observable, not become false success.
        execution.result()


def _invalid(message: str) -> FleetError:
    return FleetError(ErrorCode.CONFIG_INVALID, message, "Inspect the selected chat and retry.")


def _busy() -> FleetError:
    return FleetError(
        ErrorCode.RECOVERY_REQUIRED,
        "This conversation already has an active or waiting turn.",
        "Inspect, approve/resume, cancel, or explicitly recover its exact run first.",
    )
