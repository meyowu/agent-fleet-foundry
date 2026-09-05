"""Validated adaptive fleet-plan contracts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator, model_validator

from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import (
    BoundedSummary,
    CriterionId,
    EvidenceRequirementId,
    FleetPlanId,
    RoleId,
    RunId,
    StrictModel,
    TaskId,
    TaskSpec,
    _require_utc,
)
from agent_fleet.domain.paths import path_is_within

NodeId = Annotated[
    str, StringConstraints(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_-]*$")
]
PlanScopePath = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=4096,
        pattern=r"^[^/\\\x00][^\\\x00]*$",
    ),
]
_INDEPENDENT_VERIFICATION_REQUIREMENT = "independent_verifier_verdict"
_DIRECT_EVIDENCE_REQUIREMENTS = {"control_plane_plan"}


class FleetStrategy(StrEnum):
    DIRECT = "direct"
    SINGLE_ENGINEER = "single_engineer"
    ENGINEER_VERIFIER = "engineer_verifier"
    PARALLEL_ENGINEERS = "parallel_engineers"
    RESEARCH_ARCHITECT_ENGINEER_VERIFIER = "research_architect_engineer_verifier"


class FleetPlanNode(StrictModel):
    node_id: NodeId
    role_id: RoleId
    goal: BoundedSummary | None = None
    criterion_ids: list[CriterionId] = Field(default_factory=list, max_length=128)
    depends_on: list[NodeId] = Field(default_factory=list, max_length=16)
    scope: list[PlanScopePath] = Field(default_factory=list, max_length=128)
    can_write: bool = False
    requires_workspace: bool = False
    independent_verifier: bool = False
    max_steps: int = Field(default=10, ge=1, le=100)

    @field_validator("scope")
    @classmethod
    def validate_scope(cls, values: list[str]) -> list[str]:
        folded_paths: list[tuple[str, ...]] = []
        for value in values:
            path = PurePosixPath(value)
            if (
                not value
                or value.startswith("/")
                or "\\" in value
                or ".." in path.parts
                or path.as_posix() != value
            ):
                raise ValueError(f"invalid repository-relative plan scope: {value!r}")
            folded_paths.append(_fold_path(path))
        if len(folded_paths) != len(set(folded_paths)):
            raise ValueError("fleet plan scope entries must be case-insensitively unique")
        return values

    @field_validator("depends_on")
    @classmethod
    def validate_dependencies(cls, values: list[NodeId]) -> list[NodeId]:
        if len(values) != len(set(values)):
            raise ValueError("fleet plan dependencies must be unique")
        return values

    @field_validator("criterion_ids")
    @classmethod
    def validate_criteria(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("fleet plan criterion IDs must be unique")
        return values


class FleetPlan(StrictModel):
    api_version: Literal["agentfleet.dev/v1alpha1"] = "agentfleet.dev/v1alpha1"
    kind: Literal["FleetPlan"] = "FleetPlan"
    plan_id: FleetPlanId
    run_id: RunId
    task_id: TaskId
    strategy: FleetStrategy
    nodes: list[FleetPlanNode] = Field(max_length=16)
    max_parallel_agents: int = Field(default=1, ge=1, le=8)
    required_evidence: list[EvidenceRequirementId] = Field(min_length=1, max_length=32)
    rationale: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4096)
    ]
    created_at: datetime

    _created_utc = field_validator("created_at")(_require_utc)

    @field_validator("required_evidence")
    @classmethod
    def validate_evidence_requirements(
        cls, values: list[EvidenceRequirementId]
    ) -> list[EvidenceRequirementId]:
        if len(values) != len(set(values)):
            raise ValueError("FleetPlan evidence requirements must be unique")
        return values

    @model_validator(mode="after")
    def validate_graph_shape(self) -> FleetPlan:
        node_ids = [node.node_id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("fleet plan node IDs must be unique")
        known = set(node_ids)
        for node in self.nodes:
            missing = set(node.depends_on) - known
            if missing:
                raise ValueError(
                    f"fleet plan node {node.node_id!r} has missing dependencies: {sorted(missing)}"
                )
            if node.node_id in node.depends_on:
                raise ValueError(f"fleet plan node {node.node_id!r} depends on itself")
        _reject_cycles(self.nodes)
        return self


def validate_fleet_plan(
    plan: FleetPlan,
    task: TaskSpec,
    *,
    known_roles: set[str] | None = None,
) -> None:
    """Apply deterministic limits to a runtime-proposed topology."""

    if plan.run_id != task.run_id or plan.task_id != task.task_id:
        raise _invalid("FleetPlan identity does not match its TaskSpec.")
    if set(task.required_evidence) != set(plan.required_evidence):
        raise _invalid("FleetPlan evidence requirements must exactly match its TaskSpec.")
    if known_roles is not None:
        missing_roles = {node.role_id for node in plan.nodes} - known_roles
        if missing_roles:
            raise _invalid(f"FleetPlan references undeclared roles: {sorted(missing_roles)}.")
    task_criteria = {criterion.criterion_id for criterion in task.acceptance_criteria}
    if any(set(node.criterion_ids) - task_criteria for node in plan.nodes):
        raise _invalid("FleetPlan nodes must not introduce acceptance criterion IDs.")
    writers = [node for node in plan.nodes if node.can_write]
    verifiers = [node for node in plan.nodes if node.independent_verifier]
    requires_independent_verification = (
        _INDEPENDENT_VERIFICATION_REQUIREMENT in task.required_evidence
    )
    if requires_independent_verification and not verifiers:
        raise _invalid(
            "The TaskSpec requires independent verification but the FleetPlan has no "
            "independent verifier."
        )
    if plan.strategy is FleetStrategy.DIRECT:
        if task.change_kind != "read_only" or plan.nodes:
            raise _invalid("Direct plans are limited to read-only tasks and have no specialists.")
        if set(plan.required_evidence) != _DIRECT_EVIDENCE_REQUIREMENTS:
            raise _invalid("A direct plan requires exactly control_plane_plan evidence.")
        return
    if task.change_kind != "code_change":
        raise _invalid("Specialist FleetPlans are limited to code-change tasks.")
    if task.change_kind == "code_change" and not writers:
        raise _invalid("A code-change plan requires at least one writer.")
    for writer in writers:
        if not writer.requires_workspace or not writer.scope:
            raise _invalid("Every writer requires a workspace and a non-empty path scope.")
        if any(
            not path_is_within(path, task.allowed_paths, forbidden=task.forbidden_paths)
            for path in writer.scope
        ):
            raise _invalid(
                f"Writer {writer.node_id!r} requests paths outside the TaskSpec allow-list."
            )
    for verifier in verifiers:
        if verifier.can_write or not verifier.requires_workspace or not verifier.scope:
            raise _invalid(
                "Every independent Verifier must be read-only and requires a workspace "
                "with a non-empty path scope."
            )
        if any(
            not path_is_within(path, task.allowed_paths, forbidden=task.forbidden_paths)
            for path in verifier.scope
        ):
            raise _invalid(
                f"Verifier {verifier.node_id!r} requests paths outside the TaskSpec allow-list."
            )
    if plan.strategy is FleetStrategy.SINGLE_ENGINEER and (
        len(writers) != 1 or writers[0].role_id != "engineer" or verifiers or len(plan.nodes) != 1
    ):
        raise _invalid(
            "A single-engineer plan must contain exactly one Engineer writer and no verifier."
        )
    if plan.strategy is FleetStrategy.ENGINEER_VERIFIER:
        if not requires_independent_verification:
            raise _invalid(
                "An engineer-verifier plan requires independent_verifier_verdict evidence."
            )
        if len(writers) != 1 or len(verifiers) != 1 or len(plan.nodes) != 2:
            raise _invalid("An engineer-verifier plan requires one writer and one verifier.")
        writer = writers[0]
        verifier = verifiers[0]
        if (
            writer.role_id != "engineer"
            or verifier.role_id != "verifier"
            or writer.node_id not in verifier.depends_on
        ):
            raise _invalid(
                "The engineer-verifier roles must be Engineer and Verifier; the independent "
                "Verifier must be read-only and depend on the writer."
            )
    if plan.strategy is FleetStrategy.PARALLEL_ENGINEERS:
        if len(writers) < 2 or plan.max_parallel_agents < 2:
            raise _invalid(
                "A parallel-engineers plan requires at least two writers and parallel capacity."
            )
        if any(writer.role_id != "engineer" for writer in writers) or any(
            node.role_id not in {"engineer", "verifier"} for node in plan.nodes
        ):
            raise _invalid(
                "A parallel-engineers plan may contain only Engineer writers and Verifiers."
            )
        if len(verifiers) > 1 or len(plan.nodes) != len(writers) + len(verifiers):
            raise _invalid(
                "A parallel-engineers plan permits only its Engineer writers and at most "
                "one independent Verifier."
            )
        if any(writer.depends_on for writer in writers):
            raise _invalid("Parallel Engineer writers must not depend on one another.")
        for verifier in verifiers:
            if not {item.node_id for item in writers}.issubset(verifier.depends_on):
                raise _invalid(
                    "A parallel-plan verifier must be read-only and depend on every writer."
                )
        # Legacy persisted plans omit these optional fields. New operational plans
        # populate every writer, so partial or foreign mappings cannot be accepted.
        if any(node.criterion_ids for node in plan.nodes) and (
            any(not writer.criterion_ids or writer.goal is None for writer in writers)
            or {item for writer in writers for item in writer.criterion_ids} != task_criteria
        ):
            raise _invalid("Parallel writer assignments must cover exactly the task criteria.")
    if plan.strategy is FleetStrategy.RESEARCH_ARCHITECT_ENGINEER_VERIFIER:
        if not requires_independent_verification:
            raise _invalid("The specialist plan requires independent_verifier_verdict evidence.")
        by_role = {node.role_id: node for node in plan.nodes}
        expected = {"researcher", "architect", "engineer", "verifier"}
        if set(by_role) != expected or len(plan.nodes) != len(expected):
            raise _invalid(
                "The specialist plan requires researcher, architect, engineer, and verifier."
            )
        if (
            len(verifiers) != 1
            or verifiers[0].node_id != by_role["verifier"].node_id
            or by_role["researcher"].depends_on
            or by_role["researcher"].can_write
            or by_role["researcher"].independent_verifier
            or by_role["architect"].depends_on != [by_role["researcher"].node_id]
            or by_role["architect"].can_write
            or by_role["architect"].independent_verifier
            or by_role["engineer"].depends_on != [by_role["architect"].node_id]
            or not by_role["engineer"].can_write
            or by_role["engineer"].independent_verifier
            or by_role["verifier"].depends_on != [by_role["engineer"].node_id]
            or by_role["verifier"].can_write
            or not by_role["verifier"].independent_verifier
        ):
            raise _invalid("The specialist plan dependency and authority chain is invalid.")
        for role in ("researcher", "architect"):
            specialist = by_role[role]
            if not specialist.requires_workspace or specialist.scope != task.allowed_paths:
                raise _invalid(
                    "Read-only specialists require a workspace with the full task scope."
                )
    for index, left in enumerate(writers):
        for right in writers[index + 1 :]:
            if _scopes_overlap(left.scope, right.scope):
                raise _invalid(f"Writer scopes overlap: {left.node_id!r} and {right.node_id!r}.")


def _reject_cycles(nodes: list[FleetPlanNode]) -> None:
    dependencies = {node.node_id: set(node.depends_on) for node in nodes}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in visiting:
            raise ValueError("fleet plan dependency graph contains a cycle")
        if node_id in visited:
            return
        visiting.add(node_id)
        for dependency in dependencies[node_id]:
            visit(dependency)
        visiting.remove(node_id)
        visited.add(node_id)

    for node_id in dependencies:
        visit(node_id)


def _scopes_overlap(left: list[str], right: list[str]) -> bool:
    for left_value in left:
        left_parts = _fold_path(PurePosixPath(left_value))
        for right_value in right:
            right_parts = _fold_path(PurePosixPath(right_value))
            if (
                left_parts == right_parts
                or left_parts[: len(right_parts)] == right_parts
                or right_parts[: len(left_parts)] == left_parts
            ):
                return True
    return False


def _fold_path(path: PurePosixPath) -> tuple[str, ...]:
    return tuple(part.casefold() for part in path.parts)


def _invalid(message: str) -> FleetError:
    return FleetError(
        ErrorCode.CONFIG_INVALID,
        message,
        "Use a bounded acyclic FleetPlan whose roles, scopes, and assurance claims match the task.",
    )
