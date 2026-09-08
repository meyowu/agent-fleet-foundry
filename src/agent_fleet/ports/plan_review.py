from __future__ import annotations

from typing import Protocol

from agent_fleet.domain.models import Run
from agent_fleet.domain.plan_review import PlanReviewCheckpoint


class PlanReviewStore(Protocol):
    def create(self, run: Run, checkpoint: PlanReviewCheckpoint) -> PlanReviewCheckpoint: ...

    def get(self, run: Run) -> PlanReviewCheckpoint: ...

    def approve(self, run: Run, *, expected_sha256: str, actor: str) -> PlanReviewCheckpoint: ...

    def consume(self, run: Run, *, expected_sha256: str) -> Run: ...
