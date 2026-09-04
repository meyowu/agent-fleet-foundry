"""Deterministic scripted runtime used through the production runtime port."""

from __future__ import annotations

from pathlib import Path

from agent_fleet.adapters.repository.git import FIXED_CANARY, INCORRECT_CANARY
from agent_fleet.domain.models import (
    AgentInvocation,
    AgentInvocationResult,
    AgentRole,
    CanonicalResource,
    EngineerScript,
    FakeScenario,
    ImplementationReport,
    ScriptedAction,
    Verdict,
    VerifierScript,
    VerifierVerdict,
    WorkflowStage,
)


class FakeRuntimeAdapter:
    """Produces typed scripts; it never performs Engineer side effects itself."""

    @property
    def capabilities(self) -> frozenset[str]:
        return frozenset({"structured_output", "tool_calling"})

    async def invoke(self, request: AgentInvocation) -> AgentInvocationResult:
        scenario = FakeScenario(str(request.input["fake_scenario"]))
        if request.role is AgentRole.COS:
            output = {
                "normalized_goal": request.input["goal"],
                "workflow": "code-change",
                "allowed_paths": ["src/canary_calc/core.py"],
                "forbidden_paths": [".git", ".fleet"],
                "acceptance_criteria": [
                    {
                        "criterion_id": "canary-zero-division",
                        "description": "divide(1, 0) raises ValueError with the stable message",
                    }
                ],
                "required_evidence": ["canonical patch", "independent fake verifier verdict"],
            }
            return AgentInvocationResult(output=output)
        if request.role is AgentRole.ENGINEER:
            engineer_script = self._engineer_script(request, scenario)
            return AgentInvocationResult(output=engineer_script.model_dump(mode="json"))
        verifier_script = self._verifier_script(request, scenario)
        if verifier_script.simulate_workspace_mutation:
            workspace = Path(str(request.input["verification_workspace_path"]))
            (workspace / "verifier-untrusted-note.txt").write_text(
                "This verifier mutation must be discarded.\n", encoding="utf-8"
            )
        return AgentInvocationResult(output=verifier_script.model_dump(mode="json"))

    @staticmethod
    def _engineer_script(request: AgentInvocation, scenario: FakeScenario) -> EngineerScript:
        is_repair = request.stage is WorkflowStage.REPAIRING
        if scenario is FakeScenario.FAIL or (scenario is FakeScenario.REPAIR and not is_repair):
            content = INCORRECT_CANARY
            summary = "Applied a deliberately incomplete scripted candidate."
        else:
            content = FIXED_CANARY
            summary = "Added deterministic zero-division validation."
        actions: list[ScriptedAction] = []
        if scenario is FakeScenario.APPROVAL:
            actions.append(
                ScriptedAction(
                    action="fixture.record_side_effect",
                    resource=CanonicalResource(
                        kind="fake_side_effect", identifier="fixture://approval-proof"
                    ),
                    parameters={"record": "approved-once"},
                    reason="Exercise durable one-use approval behavior.",
                    side_effect=True,
                    idempotency_key=f"{request.run_id}:approval-proof",
                )
            )
        actions.extend(
            [
                ScriptedAction(
                    action="workspace.write_file",
                    resource=CanonicalResource(
                        kind="workspace_path", identifier="src/canary_calc/core.py"
                    ),
                    parameters={"content": content},
                    reason="Repair the bounded canary implementation.",
                    side_effect=True,
                    idempotency_key=f"{request.run_id}:write:{request.iteration}",
                ),
                ScriptedAction(
                    action="command.run",
                    resource=CanonicalResource(
                        kind="fake_command", identifier="verification://offline-canary"
                    ),
                    parameters={
                        "executable": "python",
                        "argv": ["-m", "pytest", "-q"],
                        "cwd": ".",
                    },
                    reason="Record deterministic fake command evidence.",
                    side_effect=False,
                    idempotency_key=f"{request.run_id}:engineer-check:{request.iteration}",
                ),
            ]
        )
        return EngineerScript(
            actions=actions,
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
    def _verifier_script(request: AgentInvocation, scenario: FakeScenario) -> VerifierScript:
        repair_value = request.input["repair_iterations"]
        if not isinstance(repair_value, int):
            raise ValueError("fake repair_iterations must be an integer")
        repair_iterations = repair_value
        should_fail = scenario is FakeScenario.FAIL or (
            scenario is FakeScenario.REPAIR and repair_iterations == 0
        )
        if scenario is FakeScenario.INCONCLUSIVE:
            verdict = Verdict.INCONCLUSIVE
        else:
            verdict = Verdict.FAIL if should_fail else Verdict.PASS
        return VerifierScript(
            actions=[
                ScriptedAction(
                    action="command.run",
                    resource=CanonicalResource(
                        kind="fake_command", identifier="verification://offline-canary"
                    ),
                    parameters={
                        "executable": "python",
                        "argv": ["-m", "pytest", "-q"],
                        "cwd": ".",
                    },
                    reason="Record independent deterministic fake verifier evidence.",
                    side_effect=False,
                    idempotency_key=f"{request.run_id}:verifier-check:{repair_iterations}",
                )
            ],
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
            simulate_workspace_mutation=scenario is FakeScenario.VERIFIER_MUTATION,
        )
