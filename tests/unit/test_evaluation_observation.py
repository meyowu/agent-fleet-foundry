from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_fleet.domain.evaluation_observation import EvaluationObservation


def test_observation_is_immutable_repeatable_and_nonauthorizing() -> None:
    observation = EvaluationObservation(
        campaign_id="campaign_" + "a" * 32,
        attempt_id="attempt_" + "b" * 32,
        state="reserved",
    )
    assert (
        observation.sha256
        == EvaluationObservation.model_validate_json(observation.model_dump_json()).sha256
    )
    assert not observation.execution_authorized
    assert observation.physical_cleanup == "not_checked"
    with pytest.raises(ValidationError):
        observation.state = "failed"  # type: ignore[misc]


@pytest.mark.parametrize(
    "update",
    [
        {"terminal_result": "verified_success"},
        {"terminal_result": "functional_failure"},
        {"terminal_result": "provider_failure"},
        {"state": "corrupt"},
        {"execution_authorized": True},
        {"execution_authorized": 0},
        {"task_id": "task_" + "c" * 32},
        {"verified_artifact_count": True},
        {"raw_error": "not allowed"},
    ],
)
def test_invalid_or_untrusted_observations_reject(update: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        EvaluationObservation.model_validate(
            {
                "campaign_id": "campaign_" + "a" * 32,
                "attempt_id": "attempt_" + "b" * 32,
                "state": "reserved",
                **update,
            }
        )
