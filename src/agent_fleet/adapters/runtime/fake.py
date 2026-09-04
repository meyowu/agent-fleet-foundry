"""Deterministic runtime that exercises the production runtime and tool ports."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import JsonValue

from agent_fleet.domain.models import (
    AgentInvocation,
    AgentInvocationResult,
    AgentRole,
    FakeScenario,
    ImplementationReport,
    RuntimeCapability,
    RuntimeConfiguration,
    RuntimeCredentialCheck,
    RuntimeCredentialStatus,
    RuntimePreflight,
    RuntimeToolCall,
    RuntimeToolOutcome,
    ScopeDecision,
    Verdict,
    VerifierVerdict,
    WorkflowStage,
)
from agent_fleet.domain.offline_canary import FIXED_CANARY, INCORRECT_CANARY
from agent_fleet.ports.runtime import RuntimeInvocationServices

_WORKSPACE_WRITE_TOOL = "workspace_write_file"
_RUN_VERIFICATION_TOOL = "run_verification"
_APPROVAL_PROBE_TOOL = "record_approval_probe"


@dataclass(frozen=True, slots=True)
class _ScriptedAction:
    call_id: str
    tool_name: str
    arguments: dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class _EngineerScript:
    actions: tuple[_ScriptedAction, ...]
    report: ImplementationReport


@dataclass(frozen=True, slots=True)
class _VerifierScript:
    actions: tuple[_ScriptedAction, ...]
    verdict: VerifierVerdict


class FakeRuntimeAdapter:
    """Produces deterministic typed outputs and delegates every action to its catalog."""

    @property
    def capabilities(self) -> frozenset[RuntimeCapability]:
        return frozenset(
            {
                RuntimeCapability.STRUCTURED_OUTPUT,
                RuntimeCapability.TOOL_CALLING,
            }
        )

    def preflight(
        self,
        configuration: RuntimeConfiguration,
        *,
        credential_check: RuntimeCredentialCheck,
    ) -> RuntimePreflight:
        del credential_check
        ready = configuration.runtime_name == "fake"
        return RuntimePreflight(
            runtime_name=configuration.runtime_name,
            ready=ready,
            capabilities=self.capabilities,
            credential_status=RuntimeCredentialStatus.NOT_SELECTED,
            diagnostic=(
                "Fake runtime is ready and requires no provider credential."
                if ready
                else "Runtime configuration does not select the fake adapter."
            ),
        )

    async def invoke(
        self,
        request: AgentInvocation,
        services: RuntimeInvocationServices,
    ) -> AgentInvocationResult:
        if services.configuration.runtime_name != "fake":
            raise ValueError("FakeRuntimeAdapter requires runtime_name='fake'")
        scenario = FakeScenario(str(request.input["fake_scenario"]))
        if request.role == AgentRole.COS:
            if services.tools.definitions:
                raise ValueError("fake CoS invocation requires an empty tool catalog")
            return AgentInvocationResult(output=self._scope_decision(request, scenario))
        if request.role == AgentRole.ENGINEER:
            engineer_script = self._engineer_script(request, scenario)
            await self._execute_actions(engineer_script.actions, services)
            return AgentInvocationResult(output=engineer_script.report)
        if request.role == AgentRole.VERIFIER:
            verifier_script = self._verifier_script(request, scenario)
            await self._execute_actions(verifier_script.actions, services)
            return AgentInvocationResult(output=verifier_script.verdict)
        raise ValueError(f"FakeRuntimeAdapter does not implement role {request.role!r}")

    @staticmethod
    def _scope_decision(request: AgentInvocation, scenario: FakeScenario) -> ScopeDecision:
        goal = request.input["goal"]
        if not isinstance(goal, str):
            raise ValueError("fake goal must be a string")
        direct = scenario is FakeScenario.DIRECT
        single_engineer = scenario is FakeScenario.SINGLE_ENGINEER
        return ScopeDecision(
            normalized_goal=goal,
            workflow="code-change",
            change_kind="read_only" if direct else "code_change",
            fleet_strategy=(
                "direct"
                if direct
                else "single_engineer"
                if single_engineer
                else "engineer_verifier"
            ),
            allowed_paths=[] if direct else ["src/canary_calc/core.py"],
            forbidden_paths=[".git", ".fleet"],
            acceptance_criteria=[
                {
                    "criterion_id": "read-only-response" if direct else "canary-zero-division",
                    "description": (
                        "Return a scoped read-only response without side effects"
                        if direct
                        else "divide(1, 0) raises ValueError with the stable message"
                    ),
                }
            ],
            required_evidence=(
                ["control_plane_plan"]
                if direct
                else ["canonical_patch", "command_evidence"]
                + ([] if single_engineer else ["independent_verifier_verdict"])
            ),
        )

    @staticmethod
    async def _execute_actions(
        actions: tuple[_ScriptedAction, ...],
        services: RuntimeInvocationServices,
    ) -> None:
        for action in actions:
            result = await services.tools.execute(
                RuntimeToolCall(
                    call_id=action.call_id,
                    name=action.tool_name,
                    arguments=action.arguments,
                )
            )
            if result.call_id != action.call_id or result.name != action.tool_name:
                raise RuntimeError("runtime tool result identity does not match its call")
            if result.outcome is not RuntimeToolOutcome.SUCCEEDED:
                raise RuntimeError(
                    f"fake runtime tool {result.name!r} did not succeed: {result.outcome.value}"
                )

    @staticmethod
    def _engineer_script(request: AgentInvocation, scenario: FakeScenario) -> _EngineerScript:
        is_repair = request.stage is WorkflowStage.REPAIRING
        if scenario is FakeScenario.FAIL or (scenario is FakeScenario.REPAIR and not is_repair):
            content = INCORRECT_CANARY
            summary = "Applied a deliberately incomplete scripted candidate."
        else:
            content = FIXED_CANARY
            summary = "Added deterministic zero-division validation."
        actions: list[_ScriptedAction] = []
        if scenario is FakeScenario.APPROVAL:
            actions.append(
                _ScriptedAction(
                    call_id=f"fake_approval_{request.iteration}",
                    tool_name=_APPROVAL_PROBE_TOOL,
                    arguments={
                        "record": "approved-once",
                        "reason": "Exercise durable one-use approval behavior.",
                    },
                )
            )
        actions.extend(
            [
                _ScriptedAction(
                    call_id=f"fake_write_{request.iteration}",
                    tool_name=_WORKSPACE_WRITE_TOOL,
                    arguments={
                        "path": "src/canary_calc/core.py",
                        "content": content,
                        "reason": "Repair the bounded canary implementation.",
                    },
                ),
                _ScriptedAction(
                    call_id=f"fake_engineer_check_{request.iteration}",
                    tool_name=_RUN_VERIFICATION_TOOL,
                    arguments={
                        "reason": "Record deterministic fake command evidence.",
                    },
                ),
            ]
        )
        return _EngineerScript(
            actions=tuple(actions),
            report=ImplementationReport(
                summary=summary,
                intended_changed_paths=["src/canary_calc/core.py"],
                tests_added_or_changed=[],
                criterion_results=["canary-zero-division: scripted candidate produced"],
                evidence_artifact_ids=[],
                unresolved_limitations=["Fake sandbox did not execute project code."],
                verifier_focus=["Validate exact exception type and message independently."],
            ),
        )

    @staticmethod
    def _verifier_script(request: AgentInvocation, scenario: FakeScenario) -> _VerifierScript:
        repair_value = request.input["repair_iterations"]
        if type(repair_value) is not int:
            raise ValueError("fake repair_iterations must be an integer")
        repair_iterations = repair_value
        should_fail = scenario is FakeScenario.FAIL or (
            scenario is FakeScenario.REPAIR and repair_iterations == 0
        )
        if scenario is FakeScenario.INCONCLUSIVE:
            verdict = Verdict.INCONCLUSIVE
        else:
            verdict = Verdict.FAIL if should_fail else Verdict.PASS
        actions: list[_ScriptedAction] = []
        if scenario is FakeScenario.VERIFIER_MUTATION:
            actions.append(
                _ScriptedAction(
                    call_id=f"fake_verifier_mutation_{repair_iterations}",
                    tool_name=_WORKSPACE_WRITE_TOOL,
                    arguments={
                        "path": "verifier-untrusted-note.txt",
                        "content": "This verifier mutation must be denied.\n",
                        "reason": "Adversarial verifier attempts to mutate its workspace.",
                    },
                )
            )
        actions.append(
            _ScriptedAction(
                call_id=f"fake_verifier_check_{repair_iterations}",
                tool_name=_RUN_VERIFICATION_TOOL,
                arguments={
                    "reason": "Record independent deterministic fake verifier evidence.",
                },
            )
        )
        return _VerifierScript(
            actions=tuple(actions),
            verdict=VerifierVerdict(
                verdict=verdict,
                criterion_results=[
                    "canary-zero-division: "
                    + ("failed scripted review" if should_fail else "passed")
                ],
                evidence_artifact_ids=[],
                regressions=["Stable error message is missing."] if should_fail else [],
                required_repairs=["Use the required stable ValueError message."]
                if should_fail
                else [],
                proof_gaps=["No project code was executed because sandbox=fake."],
                rationale=(
                    "Scripted verifier requested repair."
                    if should_fail
                    else (
                        "Scripted verifier could not obtain behavioral proof."
                        if verdict is Verdict.INCONCLUSIVE
                        else "Scripted verifier accepted the canonical candidate patch."
                    )
                ),
            ),
        )
