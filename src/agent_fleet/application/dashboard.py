"""Read-only dashboard projections over the same persisted control-plane evidence."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, cast

from pydantic import JsonValue

from agent_fleet.application.artifacts import ArtifactService
from agent_fleet.application.evolution import OrganizationService
from agent_fleet.application.inspection import InspectionService
from agent_fleet.application.plan_review import PlanReviewService
from agent_fleet.domain.dashboard import MAX_DASHBOARD_RESPONSE, DashboardCursors
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import ArtifactKind, Project, Run
from agent_fleet.domain.security import Redactor, canonical_json_hash
from agent_fleet.ports.clock import Clock
from agent_fleet.ports.conversation import ConversationStore
from agent_fleet.ports.dashboard import DashboardReader
from agent_fleet.ports.repository import RepositoryPort
from agent_fleet.ports.state_store import StateStore

_PRIVATE_KEYS = {
    "credential_ref",
    "credential",
    "secret_ref",
    "api_key",
    "authorization",
    "claim",
    "claim_id",
    "active_claim_id",
    "driver_claim",
    "permission_grant",
    "instructions",
    "prompt",
    "conversation_context",
    "context",
}
_REFERENCE = re.compile(r"\b(?:env|keyring):[A-Za-z0-9_./:-]+")
_VISIBLE_ARTIFACTS = {
    ArtifactKind.PATCH,
    ArtifactKind.EVIDENCE_BUNDLE,
    ArtifactKind.VERIFIER_VERDICT,
    ArtifactKind.IMPLEMENTATION_REPORT,
    ArtifactKind.COS_RESPONSE,
    ArtifactKind.RUN_SUMMARY,
    ArtifactKind.FLEET_PATCH_DIFF,
}


class DashboardService:
    def __init__(
        self,
        *,
        state: StateStore,
        reader: DashboardReader,
        inspection: InspectionService,
        conversations: ConversationStore,
        organization: OrganizationService,
        artifacts: ArtifactService,
        repository: RepositoryPort,
        clock: Clock,
        redactor: Redactor,
        plan_reviews: PlanReviewService | None = None,
    ) -> None:
        self.state = state
        self.reader = reader
        self.inspection = inspection
        self.conversations = conversations
        self.organization = organization
        self.artifacts = artifacts
        self.repository = repository
        self.clock = clock
        self.redactor = redactor
        self.plan_reviews = plan_reviews

    def open_project(self, path: Path) -> Project:
        info = self.repository.inspect(path)
        project = self.state.get_project_by_root(info.root)
        if project is None or project.identity_hash != info.identity_hash:
            raise FleetError(
                ErrorCode.PROJECT_NOT_INITIALIZED,
                "The dashboard requires this exact registered repository.",
                "Initialize the project in the terminal; viewing does not initialize it.",
            )
        self.organization.register_project_secrets(project)
        return project

    def _project(self, project: Project) -> Project:
        current = self.state.get_project(project.project_id)
        if (current.identity_hash, current.canonical_root) != (
            project.identity_hash,
            project.canonical_root,
        ):
            raise FleetError(
                ErrorCode.RECOVERY_REQUIRED,
                "The observed repository identity changed.",
                "Stop the dashboard and select the intended project again.",
            )
        self.organization.register_project_secrets(current)
        return current

    def _clean(self, value: object) -> JsonValue:
        cleaned, _ = self.redactor.redact_data(value)

        def visit(item: object, depth: int = 0) -> JsonValue:
            if depth > 20:
                return "[bounded nested content]"
            if isinstance(item, dict):
                return {
                    str(key): visit(child, depth + 1)
                    for key, child in item.items()
                    if str(key).casefold() not in _PRIVATE_KEYS
                    and not str(key)
                    .casefold()
                    .endswith(("_credential_ref", "_api_key", "_claim_id"))
                }
            if isinstance(item, (list, tuple)):
                return [visit(child, depth + 1) for child in item]
            if isinstance(item, str):
                text = _REFERENCE.sub("[credential reference omitted]", item)
                return "".join(
                    f"\\u{ord(char):04x}"
                    if (ord(char) < 32 and char not in "\n\t")
                    or 0x7F <= ord(char) <= 0x9F
                    or 0x202A <= ord(char) <= 0x202E
                    or 0x2066 <= ord(char) <= 0x2069
                    else char
                    for char in text
                )
            if item is None or isinstance(item, (int, float, bool)):
                return item
            raise FleetError(
                ErrorCode.STATE_UNAVAILABLE,
                "Dashboard projection is not JSON data.",
                "Inspect the source record without changing the task.",
            )

        result = visit(cleaned)
        if len(json.dumps(result, ensure_ascii=False).encode()) > MAX_DASHBOARD_RESPONSE:
            raise FleetError(
                ErrorCode.STATE_UNAVAILABLE,
                "The dashboard response exceeds its bound.",
                "Inspect individual artifacts in the terminal.",
            )
        return result

    @staticmethod
    def _run_view(run: Run) -> dict[str, JsonValue]:
        return {
            "run_id": run.run_id,
            "parent_run_id": run.parent_run_id,
            "node_id": run.parent_node_id,
            "goal": run.goal[:4096],
            "status": run.status.value,
            "stage": run.stage.value if run.stage else None,
            "runtime": run.runtime_name,
            "provider_model": run.provider_model,
            "created_at": run.created_at.isoformat(),
            "updated_at": run.updated_at.isoformat(),
            "strategy": run.fleet_strategy,
            "verified_complete": run.verified_complete,
            "assurance": run.assurance_verdict.value if run.assurance_verdict else None,
            "review_plan": run.plan_review_required,
        }

    def catalog(self, project: Project, *, before: int | None = None) -> dict[str, JsonValue]:
        project = self._project(project)
        catalog = self.reader.catalog(project.project_id, before=before)
        for run in catalog.runs:
            self.organization.register_run_secrets(run)
        conversations: list[JsonValue] = []
        for conversation_id in catalog.conversation_ids:
            conversation = self.conversations.get(project.project_id, conversation_id)
            status: str | None = None
            run_id: str | None = None
            if conversation.active_turn_id is not None:
                turn = self.conversations.get_turn(project.project_id, conversation.active_turn_id)
                status, run_id = turn.status.value, turn.binding.run_id
            conversations.append(
                {
                    "conversation_id": conversation_id,
                    "status": status or "idle",
                    "run_id": run_id,
                    "revision": conversation.revision,
                    "updated_at": conversation.updated_at.isoformat(),
                }
            )
        return cast(
            dict[str, JsonValue],
            self._clean(
                {
                    "project": {
                        "project_id": project.project_id,
                        "name": Path(project.canonical_root).name,
                    },
                    "runs": [self._run_view(run) for run in catalog.runs],
                    "conversations": conversations,
                    "before": catalog.before,
                }
            ),
        )

    def frame(
        self, project: Project, root_run_id: str, *, cursors: DashboardCursors | None = None
    ) -> dict[str, JsonValue]:
        project = self._project(project)
        source = self.reader.frame(project.project_id, root_run_id, cursors=cursors)
        for run in source.runs:
            self.organization.register_run_secrets(run)
        status = self.inspection.status(root_run_id)
        model_view = cast(dict[str, object] | None, status.get("model_bindings"))
        models = cast(
            dict[str, dict[str, object]], model_view.get("roles", {}) if model_view else {}
        )
        agents: list[JsonValue] = []
        for agent in source.agents:
            owner = next(run for run in source.runs if run.run_id == agent.run_id)
            model = models.get(agent.role, {})
            configuration = cast(dict[str, object], model.get("configuration", {}))
            agents.append(
                {
                    "agent_id": agent.agent_instance_id,
                    "run_id": agent.run_id,
                    "role": agent.role,
                    "execution_kind": agent.effective_kind.value,
                    "status": agent.status.value,
                    "iteration": agent.iteration,
                    "started_at": agent.created_at.isoformat(),
                    "completed_at": agent.completed_at.isoformat() if agent.completed_at else None,
                    "runtime": cast(
                        JsonValue, configuration.get("runtime_name", owner.runtime_name)
                    ),
                    "provider_model": cast(
                        JsonValue, configuration.get("provider_model", owner.provider_model)
                    ),
                    "profile": cast(JsonValue, model.get("profile_name")),
                }
            )
        approvals: list[JsonValue] = []
        for run in source.runs:
            if run.pending_approval_id is None:
                continue
            request = self.state.get_approval(run.pending_approval_id)
            if request.run_id != run.run_id:
                raise FleetError(
                    ErrorCode.RECOVERY_REQUIRED,
                    "Approval identity is inconsistent.",
                    "Inspect this task in the terminal.",
                )
            approvals.append(
                {
                    "request_id": request.request_id,
                    "run_id": run.run_id,
                    "role": request.principal_role,
                    "action": request.action,
                    "resource": request.resource.model_dump(mode="json"),
                    "reason": request.reason[:4096],
                    "status": request.status.value,
                }
            )
        artifact_refs = [
            {"artifact_id": str(status[field]), "kind": kind}
            for field, kind in (
                ("patch_artifact_id", "patch"),
                ("evidence_bundle_artifact_id", "evidence_bundle"),
                ("verifier_verdict_artifact_id", "verifier_verdict"),
            )
            if status.get(field) is not None
        ]
        graph = cast(dict[str, Any] | None, status.get("graph"))
        graph_nodes = (
            []
            if graph is None
            else [
                {
                    "node_id": node["node"]["node_id"],
                    "role": node["node"]["role_id"],
                    "depends_on": node["node"]["depends_on"],
                    "scope": node["node"]["scope"],
                    "status": node["status"],
                    "run_id": node["binding"]["child_run_id"],
                }
                for node in graph["nodes"]
            ]
        )
        projection = cast(
            dict[str, JsonValue],
            self._clean(
                {
                    "root_run_id": root_run_id,
                    "runs": [self._run_view(run) for run in source.runs],
                    "agents": agents,
                    "events": [event.model_dump(mode="json") for event in source.events],
                    "cursors": source.cursors,
                    "high_watermarks": source.high_watermarks,
                    "resync": source.resync,
                    "earlier_events": source.earlier_events,
                    "truncated_agents": source.truncated_agents,
                    "more_events": any(
                        source.cursors[key] < value for key, value in source.high_watermarks.items()
                    ),
                    "approvals": approvals,
                    "evidence": status["evidence"],
                    "budget": status["runtime_budget"],
                    "models": model_view,
                    "graph_nodes": graph_nodes,
                    "artifacts": artifact_refs,
                    "sandbox": status["sandbox"],
                    "security_level": status["security_level"],
                    "plan_review": (
                        self.plan_reviews.inspect(source.runs[0]).safe_projection()
                        if source.runs[0].plan_review_required
                        and source.runs[0].fleet_plan_artifact_id is not None
                        and self.plan_reviews is not None
                        else {"status": "not_reached"}
                        if source.runs[0].plan_review_required
                        else None
                    ),
                }
            ),
        )
        projection["revision"] = canonical_json_hash(projection)
        projection["observed_at"] = self.clock.now().isoformat()
        return projection

    def artifact(
        self, project: Project, root_run_id: str, artifact_id: str
    ) -> dict[str, JsonValue]:
        project = self._project(project)
        source = self.reader.frame(project.project_id, root_run_id)
        for run in source.runs:
            self.organization.register_run_secrets(run)
        metadata = self.state.get_artifact(artifact_id)
        if (
            metadata.project_id != project.project_id
            or metadata.run_id not in {run.run_id for run in source.runs}
            or metadata.kind not in _VISIBLE_ARTIFACTS
        ):
            raise FleetError(
                ErrorCode.COMMAND_DENIED,
                "This artifact is outside the observed task.",
                "Select a published patch, verdict or evidence artifact for this task.",
            )
        content = self.artifacts.read_bounded_text(artifact_id, max_bytes=524_288)
        return cast(
            dict[str, JsonValue],
            self._clean(
                {
                    "artifact_id": artifact_id,
                    "kind": metadata.kind.value,
                    "sha256": metadata.sha256,
                    "content": content,
                }
            ),
        )
