"""Containment is not acceptance of the unqualified atomic terminal-write contract."""

from typing import cast

import pytest

from agent_fleet.adapters.persistence.evaluation_evidence import SqliteEvaluationEvidence
from agent_fleet.application.evaluation_outcomes import EvaluationOutcomeService
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.evaluation_observation import EvaluationObservation
from agent_fleet.domain.outcomes import OutcomeRecord


class NoAccess:
    def __getattribute__(self, name: str) -> object:
        raise AssertionError("Containment must precede every access")


@pytest.mark.parametrize("entry", ["service", "adapter"])
def test_terminal_recording_rejects_before_any_dependency_or_input_access(entry: str) -> None:
    # Deliberately no constructor/state: rejection must not inspect inputs, stores or clocks.
    value = NoAccess()
    with pytest.raises(FleetError) as caught:
        if entry == "service":
            service = EvaluationOutcomeService.__new__(EvaluationOutcomeService)
            service.record_final_outcome(cast(str, value), cast(str, value), cast(str, value))
        else:
            adapter = SqliteEvaluationEvidence.__new__(SqliteEvaluationEvidence)
            adapter.record_terminal(cast(EvaluationObservation, value), cast(OutcomeRecord, value))
    assert caught.value.code is ErrorCode.STATE_UNAVAILABLE
    assert caught.value.details == {
        "feature": "evaluation_terminal_recording",
        "reason": "write_boundary_unqualified",
    }
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert "No result, refund or replay" in caught.value.remediation
