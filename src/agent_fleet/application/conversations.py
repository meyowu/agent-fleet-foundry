"""Project-bound, bounded conversations over the existing owned workflow."""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import Callable
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
from agent_fleet.application.readiness import ReadinessService
from agent_fleet.application.resources import CancellationService
from agent_fleet.application.session_recovery import SessionRecoveryService, recovery_review_error
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
    ApprovalRequest,
    ApprovalStatus,
    FakeScenario,
    FrozenStrictModel,
    Project,
    Run,
    RunStatus,
    WorkflowStage,
    jsonable,
)
from agent_fleet.domain.role_templates import ResolvedRoleTemplate
from agent_fleet.domain.security import Redactor, canonical_json_hash, sha256_bytes
from agent_fleet.domain.session_review import ModelSelectionReview, SessionSelection
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
    runtime_name: Literal["fake", "pydantic-ai", "openai-agents"] = "fake"
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
        readiness: ReadinessService | None = None,
        recovery: SessionRecoveryService | None = None,
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
        self.readiness_service = readiness
        self.session_recovery = recovery
        self._bootstrap_review: _BootstrapReview | None = None
        self._selected: dict[str, str] = {}
        self._executions: dict[str, asyncio.Task[Run]] = {}
        self._cancellations: dict[str, asyncio.Task[None]] = {}
        self._inspection: dict[str, str] = {}
        self._selection_generation: dict[str, int] = {}
        self._task_choices: dict[str, dict[int, str]] = {}
        self._cancellation_targets: dict[str, str | None] = {}

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
        self._selected[conversation.conversation_id] = project.project_id
        self._change_inspection(conversation.conversation_id, None)
        return self.status(conversation.conversation_id)

    def _change_inspection(self, conversation_id: str, turn_id: str | None) -> None:
        self.reviews.invalidate_selection()
        self._selection_generation[conversation_id] = (
            self._selection_generation.get(conversation_id, 0) + 1
        )
        self._task_choices.pop(conversation_id, None)
        if turn_id is None:
            self._inspection.pop(conversation_id, None)
        else:
            self._inspection[conversation_id] = turn_id

    def _history_turn(self, conversation: Conversation, turn_id: str) -> ConversationTurn:
        turn = self.store.get_turn(conversation.project_id, turn_id)
        binding = self.store.binding_for_run(turn.binding.run_id)
        run = self.state.get_run(turn.binding.run_id)
        if (
            binding != turn.binding
            or turn.binding.conversation_id != conversation.conversation_id
            or turn.binding.project_id != conversation.project_id
            or turn.binding.repository_identity != conversation.repository_identity
            or run.project_id != conversation.project_id
            or run.parent_run_id is not None
        ):
            raise _invalid("The displayed task is not a root task in this conversation.")
        self._register_run_redaction(run.run_id)
        reloaded = self.store.get_turn(conversation.project_id, turn_id)
        if reloaded.binding != turn.binding:
            raise _invalid("The displayed task binding changed during inspection.")
        return reloaded

    def _inspected_turn(self, conversation: Conversation) -> ConversationTurn | None:
        selected = self._inspection.get(conversation.conversation_id)
        return (
            self._history_turn(conversation, selected)
            if selected is not None
            else self._turn(conversation)
        )

    def _require_current(self, conversation_id: str) -> None:
        if self.session_recovery is not None and self.session_recovery.active(conversation_id):
            raise _busy()
        conversation = self._conversation(conversation_id)
        current = self._turn(conversation)
        selected = self._inspection.get(conversation_id)
        if selected is not None and (current is None or selected != current.binding.turn_id):
            raise _invalid("Historical inspection cannot mutate a task. Use /tasks current first.")

    def tasks(
        self,
        conversation_id: str,
        *,
        before_sequence: int | None = None,
        select_sequence: int | None = None,
        current: bool = False,
    ) -> ConversationView:
        conversation = self._conversation(conversation_id)
        if (
            type(current) is not bool
            or sum((before_sequence is not None, select_sequence is not None, current)) > 1
        ):
            raise _invalid(
                "Use /tasks [before-sequence], /tasks select <sequence>, or /tasks current."
            )
        for number in (before_sequence, select_sequence):
            if number is not None and (type(number) is not int or not 1 <= number <= 1000):
                raise _invalid("Task sequences must be integers from 1 through 1000.")
        if current:
            self._change_inspection(conversation_id, None)
            return self.status(conversation_id)
        if select_sequence is not None:
            turn_id = self._task_choices.get(conversation_id, {}).get(select_sequence)
            if turn_id is None:
                raise _invalid("List /tasks and select a sequence from that displayed page.")
            turn = self._history_turn(conversation, turn_id)
            if turn.binding.sequence != select_sequence:
                raise _invalid("The displayed task sequence no longer matches its binding.")
            self._change_inspection(conversation_id, turn_id)
            return self.status(conversation_id)
        turns = self.store.list_turns(
            conversation.project_id,
            conversation_id,
            before_sequence=before_sequence,
            limit=21,
        )
        choices: dict[int, str] = {}
        summaries: list[JsonValue] = []
        for item in turns[:20]:
            turn = self._history_turn(conversation, item.binding.turn_id)
            choices[turn.binding.sequence] = turn.binding.turn_id
            summaries.append(
                {
                    "sequence": turn.binding.sequence,
                    "status": turn.status.value,
                    "user_summary": turn.user_summary.text,
                    "result_summary": turn.result_summary.text if turn.result_summary else None,
                    "summary_truncated": turn.user_summary.truncated
                    or bool(turn.result_summary and turn.result_summary.truncated),
                    "active": conversation.active_turn_id == turn.binding.turn_id,
                    "inspected": self._inspection.get(conversation_id) == turn.binding.turn_id,
                }
            )
        self._task_choices[conversation_id] = choices
        view: ConversationView = {
            "conversation_id": conversation_id,
            "tasks": summaries,
            "has_more": len(turns) > 20,
            "next_before_sequence": turns[19].binding.sequence if len(turns) > 20 else None,
            "notice": "Select a displayed sequence with /tasks select <sequence>; "
            "/tasks current returns to the current task.",
        }
        self._reject_secret(view)
        return view

    def _role_configuration(self, project: Project) -> tuple[str, dict[str, ResolvedRoleTemplate]]:
        spec, snapshot = self.workflow.config.load_snapshot(
            Path(project.canonical_root) / ".fleet/fleet.yaml"
        )
        return self.workflow.config.snapshot_hash(snapshot), self.workflow.config.role_templates(
            spec, snapshot
        )

    def roles(self, conversation_id: str) -> ConversationView:
        conversation = self._conversation(conversation_id)
        digest, templates = self._role_configuration(
            self.state.get_project(conversation.project_id)
        )
        view: ConversationView = {
            "conversation_id": conversation_id,
            "config_snapshot_sha256": digest,
            "roles": [
                {
                    "role_id": role,
                    "execution_kind": template.execution_kind.value,
                    "requested_tool_ceiling": list(template.allowed_tools),
                    "requested_step_ceiling": template.max_steps,
                    "requested_path_ceiling": list(template.allowed_paths)
                    if template.allowed_paths is not None
                    else None,
                    "model_preference": template.model_profile,
                    "template_sha256": canonical_json_hash(template.model_dump(mode="json")),
                }
                for role, template in sorted(templates.items())
            ],
            "notice": "Repository role requests are ceilings, not permission grants. "
            "Prompt bodies are not displayed.",
        }
        self._reject_secret(view)
        return view

    def readiness(self, conversation_id: str) -> ConversationView:
        conversation = self._conversation(conversation_id)
        if self.readiness_service is None:
            raise _invalid("The static readiness service is unavailable.")
        project = self.state.get_project(conversation.project_id)
        report = self.readiness_service.inspect(Path(project.canonical_root))
        view = report.model_dump(mode="json")
        self._reject_secret(view)
        return view

    def models(
        self,
        conversation_id: str,
        *,
        profile: str | None = None,
        role: str | None = None,
        default: bool = False,
    ) -> ConversationView:
        conversation = self._conversation(conversation_id)
        service = self.model_profiles
        if service is None:
            raise _invalid("The model profile service is unavailable.")
        if type(default) is not bool:
            raise _invalid("The model default selection flag must be a boolean.")
        project = self.state.get_project(conversation.project_id)
        if profile is not None:
            self._require_current(conversation_id)
            if (role is None) != default:
                raise _invalid("Use /models use <alias> --default or --role <configured-role>.")
            digest, templates = self._role_configuration(project)
            if role is not None and role not in templates:
                raise _invalid("The requested model role is not configured in this project.")
            shown = service.show(profile)
            if shown.get("enabled") is not True:
                raise _invalid("A disabled model profile cannot be selected.")
            selection = self._review_selection(conversation_id)
            expected = ModelSelectionReview(
                selection=selection,
                profile_name=profile,
                profile_revision=cast(int, shown["revision"]),
                configuration_sha256=cast(str, shown["configuration_sha256"]),
                role_id=role,
                expected_selection_revision=cast(int, service.selection(project)["revision"]),
                config_snapshot_sha256=digest,
            )
            view = self.reviews.prepare_model_selection(selection, expected, shown)
        else:
            if role is not None or default:
                raise _invalid("Choose a model profile before a target role/default.")
            turn = self._inspected_turn(conversation)
            pinned: JsonValue = None
            if turn is not None:
                run = self.state.get_run(turn.binding.run_id)
                if run.model_bindings_sha256 is not None:
                    pinned = jsonable(
                        service.inspect_bindings(
                            project,
                            root_run_id=run.run_id,
                            expected_sha256=run.model_bindings_sha256,
                        ).safe_projection()
                    )
                else:
                    pinned = {
                        "run_id": run.run_id,
                        "mode": "legacy",
                        "runtime": run.runtime_name,
                        "provider_model": run.provider_model,
                    }
            view = {
                "conversation_id": conversation_id,
                "catalog": jsonable(service.list()),
                "future_task_selection": jsonable(service.selection(project)),
                "inspected_run_id": turn.binding.run_id if turn is not None else None,
                "inspected_run_binding": pinned,
                "notice": "Catalog and future-task selection are separate from immutable "
                "historical Run bindings. No provider connectivity was tested.",
            }
        self._reject_secret(view)
        return view

    def _memory_selection(self, expected: SessionSelection) -> SessionSelection:
        if (
            self._selected.get(expected.conversation_id) != expected.project_id
            or self._selection_generation.get(expected.conversation_id, 0)
            != expected.inspection_revision
        ):
            raise _invalid("The foreground session inspection changed; prepare a new review.")
        return expected

    def _select_model(
        self, expected: ModelSelectionReview, validate: Callable[[], None]
    ) -> ConversationView:
        service = self.model_profiles
        if service is None:
            raise _invalid("The model profile service is unavailable.")
        project = self.state.get_project(expected.selection.project_id)

        def check() -> None:
            validate()  # RAM generation/expiry only: no nested SQLite transaction.
            digest, templates = self._role_configuration(project)
            if digest != expected.config_snapshot_sha256 or (
                expected.role_id is not None and expected.role_id not in templates
            ):
                raise _invalid("The reviewed project role configuration changed.")

        check()
        result = service.bind(
            project,
            expected_revision=expected.expected_selection_revision,
            profile=expected.profile_name,
            role=expected.role_id,
            default=expected.role_id is None,
            expected_review=expected,
            validate_review=check,
        )
        return {
            "future_task_selection": jsonable(result),
            "notice": "Model selection saved for future tasks only; no provider was contacted.",
        }

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
        return self._view(conversation, self._inspected_turn(conversation))

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
                "owner-stopped /recover review; chat will not replay it."
            )
        data: ConversationView = {
            "conversation_id": conversation.conversation_id,
            "project_id": conversation.project_id,
            "revision": conversation.revision,
            "active_turn_id": conversation.active_turn_id,
            "active_run_id": (
                self.store.get_turn(
                    conversation.project_id, conversation.active_turn_id
                ).binding.run_id
                if conversation.active_turn_id is not None
                else None
            ),
            "inspected_run_id": turn.binding.run_id if turn is not None else None,
            "inspection_mode": "selected" if conversation_id in self._inspection else "current",
            "inspection_revision": self._selection_generation.get(conversation_id, 0),
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
        if conversation_id in self._executions or (
            self.session_recovery is not None and self.session_recovery.active(conversation_id)
        ):
            raise _busy()
        key = submission_id or self.ids.new(IdPrefix.CORRELATION)
        prior = self.store.get_submission(conversation.project_id, conversation_id, key)
        if conversation.active_turn_id is not None and prior is None:
            raise _busy()
        if conversation_id in self._inspection:
            self._change_inspection(conversation_id, None)
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
        self._require_current(conversation_id)
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
        if self.session_recovery is not None and self.session_recovery.active(conversation_id):
            raise _busy()
        conversation = self._conversation(conversation_id)
        cleanup = self._cancellations.get(conversation_id)
        if cleanup is None:
            # Bind the user's cancellation before scheduling or awaiting work.
            # Another process can submit a newer turn as soon as this owner's
            # cleanup settles; it must never become this operation's target.
            turn = self._turn(conversation) if conversation.active_turn_id is not None else None
            self._cancellation_targets[conversation_id] = (
                turn.binding.run_id if turn is not None else None
            )
            cleanup = asyncio.create_task(
                self._cancel(
                    turn.binding.run_id if turn is not None else None,
                    self._executions.get(conversation_id),
                )
            )
            self._cancellations[conversation_id] = cleanup
        target_run_id = self._cancellation_targets.get(conversation_id)
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
                self._cancellation_targets.pop(conversation_id, None)
        if cancellation is not None:
            raise cancellation
        view = self.status(conversation_id)
        view["cancelled_run_id"] = target_run_id
        return view

    async def _cancel(self, run_id: str | None, execution: asyncio.Task[Run] | None) -> None:
        if execution is not None and not execution.done():
            execution.cancel()
            await _await_stopped(execution)
        if run_id is not None:
            await self.cancellation.cancel(run_id)

    async def recover(
        self,
        conversation_id: str,
        *,
        code: str | None = None,
        confirm_owner_stopped: bool = False,
    ) -> ConversationView:
        self._require_current(conversation_id)
        if self.session_recovery is None:
            raise recovery_review_error()

        def locally_busy() -> bool:
            return conversation_id in self._executions or conversation_id in self._cancellations

        if locally_busy():
            raise _busy()
        selection = self._review_selection(conversation_id)
        if code is None and not confirm_owner_stopped:
            view = self.session_recovery.prepare(selection)
        elif code is not None and confirm_owner_stopped is True:
            view = await self.session_recovery.confirm(
                selection,
                code,
                owner_stopped=confirm_owner_stopped,
                current_selection=lambda: self._review_selection(conversation_id),
                locally_busy=locally_busy,
            )
        else:
            raise recovery_review_error()
        self._reject_secret(view)
        return view

    def artifacts(self, conversation_id: str) -> dict[str, JsonValue]:
        turn = self._inspected_turn(self._conversation(conversation_id))
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
        turn = self._inspected_turn(conversation)
        return SessionSelection(
            project_id=conversation.project_id,
            conversation_id=conversation_id,
            conversation_revision=conversation.revision,
            run_id=turn.binding.run_id if turn is not None else None,
            inspection_revision=self._selection_generation.get(conversation_id, 0),
        )

    def review(
        self, conversation_id: str, *, action: str, arguments: tuple[str, ...] = ()
    ) -> dict[str, JsonValue]:
        """Human control entry only; no model text is parsed as a review command."""
        if (
            action == "apply"
            or (action == "plan" and arguments == ("approve",))
            or (action == "fleet-patch" and arguments and arguments[0] in {"apply", "rollback"})
        ):
            self._require_current(conversation_id)
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
                select_model=self._select_model,
                current_model_selection=lambda: self._memory_selection(selection),
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
        self._require_current(conversation_id)
        if request_id is None:
            selection = self._review_selection(conversation_id)
            pending = self._pending_requests(conversation_id)
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

    def _pending_requests(self, conversation_id: str) -> list[ApprovalRequest]:
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
        return [request for request in requests if request.status is ApprovalStatus.PENDING]

    def deny(
        self, conversation_id: str, request_id: str | None = None, *, reason: str | None = None
    ) -> dict[str, JsonValue]:
        self._require_current(conversation_id)
        if request_id is None:
            pending = self._pending_requests(conversation_id)
            if len(pending) != 1:
                view: dict[str, JsonValue] = {
                    "selection_required": len(pending) > 1,
                    "pending_requests": [request.model_dump(mode="json") for request in pending],
                    "notice": "No sole pending request was selected; no denial was performed.",
                }
                self._reject_secret(view)
                return view
            request_id = pending[0].request_id
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
