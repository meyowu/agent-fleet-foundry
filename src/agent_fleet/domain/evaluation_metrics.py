"""Pure deterministic accounting over a fixed preregistered task denominator."""

from __future__ import annotations

from collections import Counter
from typing import Annotated, Literal

from pydantic import Field, model_validator

from agent_fleet.domain.evaluation import (
    CampaignId,
    CaseId,
    EvaluationManifest,
    EvaluationModel,
    RepositoryId,
)
from agent_fleet.domain.models import Sha256
from agent_fleet.domain.outcomes import Currency, OutcomeArtifactRef, OutcomeKind, OutcomeRecord

AggregateCount = Annotated[int, Field(strict=True, ge=0, le=256 * 64 * (2**63 - 1))]


class OutcomeCount(EvaluationModel):
    result: OutcomeKind | Literal["missing"]
    count: int = Field(strict=True, ge=0, le=256)


class EvaluationCounts(EvaluationModel):
    planned: int = Field(strict=True, ge=0, le=256)
    observed: int = Field(strict=True, ge=0, le=256)
    successful: int = Field(strict=True, ge=0, le=256)
    success_percentage: float | None = Field(default=None, ge=0, le=100)
    outcomes: tuple[OutcomeCount, ...] = Field(max_length=11)

    @model_validator(mode="after")
    def coherent(self) -> EvaluationCounts:
        bins = {item.result: item.count for item in self.outcomes}
        if len(bins) != len(self.outcomes) or sum(bins.values()) != self.planned:
            raise ValueError("evaluation counts need unique complete outcome bins")
        observed = self.planned - bins.get("missing", 0) - bins.get("not_run", 0)
        successful = bins.get("verified_success", 0)
        if self.observed != observed or self.successful != successful:
            raise ValueError("evaluation observed/success counts differ from outcome bins")
        rate = round(100.0 * successful / self.planned, 6) if observed else None
        if self.success_percentage != rate:
            raise ValueError("evaluation percentage must use the frozen planned denominator")
        return self


class RepositoryEvaluation(EvaluationModel):
    repository_id: RepositoryId
    first_round: EvaluationCounts


class SlotEvaluation(EvaluationModel):
    case_id: CaseId
    repetition: int = Field(strict=True, ge=0, le=2)
    group: Literal["first_round", "repeat", "auxiliary"]
    result: OutcomeKind | Literal["missing"]

    @model_validator(mode="after")
    def coherent(self) -> SlotEvaluation:
        if (self.group == "repeat") != (self.repetition > 0):
            raise ValueError("only repeat observations can use a nonzero repetition")
        return self


class ReportedUsage(EvaluationModel):
    model_requests_lower_bound: AggregateCount
    tool_calls_lower_bound: AggregateCount
    input_tokens_lower_bound: AggregateCount
    output_tokens_lower_bound: AggregateCount
    active_milliseconds_lower_bound: AggregateCount
    unknown_requests: AggregateCount
    unreported_segments: AggregateCount
    records_without_usage: int = Field(strict=True, ge=0, le=256)


class ReportedCost(EvaluationModel):
    currency: Currency
    microunits_lower_bound: AggregateCount
    reported_records: int = Field(strict=True, ge=1, le=256)


class EvaluationCoverage(EvaluationModel):
    planned_slots: int = Field(strict=True, ge=1, le=256)
    recorded_outcomes: int = Field(strict=True, ge=0, le=256)
    missing_outcomes: int = Field(strict=True, ge=0, le=256)
    usage_complete: bool
    cost_complete: bool

    @model_validator(mode="after")
    def coherent(self) -> EvaluationCoverage:
        if self.recorded_outcomes + self.missing_outcomes != self.planned_slots:
            raise ValueError("evaluation coverage counts must retain every planned slot")
        if self.missing_outcomes and (self.usage_complete or self.cost_complete):
            raise ValueError("missing outcomes cannot have complete usage or cost coverage")
        return self


class EvaluationReport(EvaluationModel):
    """Structural summary; consumers must recompute against manifest and outcomes."""

    schema_version: int = Field(default=1, strict=True, ge=1, le=1)
    campaign_id: CampaignId
    manifest_sha256: Sha256
    first_round: EvaluationCounts
    development: EvaluationCounts
    sealed_holdout: EvaluationCounts
    repositories: tuple[RepositoryEvaluation, ...] = Field(max_length=16)
    repeats: EvaluationCounts
    auxiliary: EvaluationCounts
    slots: tuple[SlotEvaluation, ...] = Field(min_length=1, max_length=256)
    coverage: EvaluationCoverage
    usage: ReportedUsage
    costs: tuple[ReportedCost, ...] = Field(max_length=256)
    records_without_cost: int = Field(strict=True, ge=0, le=256)
    assurance: Literal["structural_only"] = "structural_only"
    kr_status: Literal["not_evaluated"] = "not_evaluated"

    @model_validator(mode="after")
    def coherent(self) -> EvaluationReport:
        if len({(slot.case_id, slot.repetition) for slot in self.slots}) != len(self.slots):
            raise ValueError("report slots must be unique")
        slots = {(slot.case_id, slot.repetition): slot for slot in self.slots}
        for slot in self.slots:
            if slot.repetition and any(
                (slot.case_id, previous) not in slots for previous in range(slot.repetition)
            ):
                raise ValueError("report repeats must retain their earlier planned slots")
            if slot.repetition and slots[(slot.case_id, 0)].group != "first_round":
                raise ValueError("auxiliary observations cannot be repeated cohort tasks")
        if len({repo.repository_id for repo in self.repositories}) != len(self.repositories):
            raise ValueError("report repository identities must be unique")
        if len({cost.currency for cost in self.costs}) != len(self.costs):
            raise ValueError("report cost currencies must be unique")
        for group, counts in (
            ("first_round", self.first_round),
            ("repeat", self.repeats),
            ("auxiliary", self.auxiliary),
        ):
            if counts != _counts(tuple(slot.result for slot in self.slots if slot.group == group)):
                raise ValueError("report group counts must match its exact slot observations")
        for groups in (
            (self.development, self.sealed_holdout),
            tuple(repo.first_round for repo in self.repositories),
        ):
            combined = tuple(
                item.result
                for group in groups
                for item in group.outcomes
                for _ in range(item.count)
            )
            if _counts(combined) != self.first_round:
                raise ValueError("report cohort/repository counts must reconcile first rounds")
        missing = sum(slot.result == "missing" for slot in self.slots)
        if (
            self.coverage.planned_slots != len(self.slots)
            or self.coverage.missing_outcomes != missing
        ):
            raise ValueError("report coverage must match every slot")
        if (
            sum(cost.reported_records for cost in self.costs) + self.records_without_cost
            != self.coverage.recorded_outcomes
        ):
            raise ValueError("report cost coverage must retain every recorded outcome")
        if self.coverage.cost_complete and self.records_without_cost:
            raise ValueError("unreported costs cannot be complete")
        if self.coverage.usage_complete and (
            self.usage.records_without_usage
            or self.usage.unreported_segments
            or self.usage.unknown_requests
        ):
            raise ValueError("unreported usage cannot be complete")
        if self.usage.records_without_usage > self.coverage.recorded_outcomes:
            raise ValueError("usage coverage cannot exceed recorded outcomes")
        return self


def _counts(results: tuple[OutcomeKind | Literal["missing"], ...]) -> EvaluationCounts:
    counts = Counter(results)
    observed = len(results) - counts["missing"] - counts["not_run"]
    successful = counts["verified_success"]
    return EvaluationCounts(
        planned=len(results),
        observed=observed,
        successful=successful,
        success_percentage=round(100.0 * successful / len(results), 6) if observed else None,
        outcomes=tuple(
            OutcomeCount(result=result, count=count) for result, count in sorted(counts.items())
        ),
    )


def evaluate_records(
    manifest: EvaluationManifest, records: tuple[OutcomeRecord, ...]
) -> EvaluationReport:
    """Check structural linkage only; no reads, dispatch, evidence repair or KR verdict."""
    if not isinstance(records, tuple) or len(records) > 256:
        raise ValueError("evaluation records must be a bounded immutable tuple")
    # Revalidate raw instances before serialization: an integer-field serializer
    # can turn an invalid copied True into 1 and hide its original strict type.
    manifest = EvaluationManifest.model_validate(manifest)
    records = tuple(OutcomeRecord.model_validate(record) for record in records)
    cases = {case.case_id: case for case in manifest.cases}
    repos = {repo.repository_id: repo for repo in manifest.repositories}
    slots = {(slot.case_id, slot.repetition) for slot in manifest.slots}
    indexed: dict[tuple[str, int], OutcomeRecord] = {}
    outcomes: set[str] = set()
    attempts: set[str] = set()
    runs: set[str] = set()
    tasks: set[str] = set()
    artifacts: dict[str, OutcomeArtifactRef] = {}
    for record in records:
        slot = (record.case_id, record.repetition)
        if record.campaign_id != manifest.campaign_id or record.manifest_sha256 != manifest.sha256:
            raise ValueError("outcome does not belong to the frozen campaign manifest")
        if record.recorded_at < manifest.frozen_at:
            raise ValueError("outcome cannot predate the frozen manifest")
        if slot not in slots:
            raise ValueError("outcome does not belong to a preregistered attempt slot")
        case = cases[record.case_id]
        if (record.configuration_sha256, record.oracle_sha256, record.scoring_sha256) != (
            case.configuration_sha256,
            case.oracle_sha256,
            case.scoring_sha256,
        ):
            raise ValueError("outcome configuration or oracle/scoring contract differs")
        if slot in indexed or record.outcome_id in outcomes or record.attempt_id in attempts:
            raise ValueError("duplicate outcome, attempt or case repetition")
        if record.root_run_id is not None:
            if record.root_run_id in runs:
                raise ValueError("a root Run cannot count as more than one attempt")
            runs.add(record.root_run_id)
        if record.task_id is not None:
            if record.task_id in tasks:
                raise ValueError("a Task cannot count as more than one attempt")
            tasks.add(record.task_id)
        for ref in record.artifacts:
            if ref.artifact_id in artifacts and artifacts[ref.artifact_id] != ref:
                raise ValueError("an artifact identity cannot change its run, category or hash")
            # Exact shared preflight diagnostic references may recur. Run-bound
            # evidence cannot be shared across distinct root Run attempts.
            artifacts[ref.artifact_id] = ref
        categories = {ref.category for ref in record.artifacts}
        if case.task_kind == "read_only" and (
            record.apply_status != "not_applicable"
            or {"patch", "apply", "post_apply"}.intersection(categories)
        ):
            raise ValueError("read-only outcomes cannot fabricate patch application")
        if record.external_result == "verified_success":
            if not set(case.required_evidence).issubset(categories):
                raise ValueError("success lacks the frozen required evidence categories")
            if case.task_kind == "code_change" and record.apply_status != "applied":
                raise ValueError("code-change success requires explicit application evidence")
        indexed[slot] = record
        outcomes.add(record.outcome_id)
        attempts.add(record.attempt_id)
    observations: list[SlotEvaluation] = []
    for case_id, repetition in sorted(slots):
        case = cases[case_id]
        observed_record = indexed.get((case_id, repetition))
        group: Literal["first_round", "repeat", "auxiliary"] = (
            "auxiliary" if case.auxiliary_purpose else "repeat" if repetition else "first_round"
        )
        observations.append(
            SlotEvaluation(
                case_id=case_id,
                repetition=repetition,
                group=group,
                result=observed_record.external_result if observed_record else "missing",
            )
        )
    first = tuple(item for item in observations if item.group == "first_round")
    usage_fields = (
        "model_requests",
        "tool_calls",
        "input_tokens",
        "output_tokens",
        "active_milliseconds",
    )
    segments = tuple(segment for record in records for segment in record.usage)
    amounts = {
        name: sum(getattr(segment, name) or 0 for segment in segments) for name in usage_fields
    }
    costs: dict[str, int] = {}
    currency_records: Counter[str] = Counter()
    for record in records:
        if record.currency is not None and record.reported_cost_microunits is not None:
            costs[record.currency] = costs.get(record.currency, 0) + record.reported_cost_microunits
            currency_records[record.currency] += 1
    return EvaluationReport(
        campaign_id=manifest.campaign_id,
        manifest_sha256=manifest.sha256,
        first_round=_counts(tuple(item.result for item in first)),
        development=_counts(
            tuple(
                item.result
                for item in first
                if repos[cases[item.case_id].repository_id].cohort == "development"
            )
        ),
        sealed_holdout=_counts(
            tuple(
                item.result
                for item in first
                if repos[cases[item.case_id].repository_id].cohort == "sealed_holdout"
            )
        ),
        repositories=tuple(
            RepositoryEvaluation(
                repository_id=repo_id,
                first_round=_counts(
                    tuple(
                        item.result
                        for item in first
                        if cases[item.case_id].repository_id == repo_id
                    )
                ),
            )
            for repo_id in sorted(repos)
        ),
        repeats=_counts(tuple(item.result for item in observations if item.group == "repeat")),
        auxiliary=_counts(tuple(item.result for item in observations if item.group == "auxiliary")),
        slots=tuple(observations),
        coverage=EvaluationCoverage(
            planned_slots=len(slots),
            recorded_outcomes=len(records),
            missing_outcomes=len(slots) - len(records),
            usage_complete=len(records) == len(slots)
            and all(
                record.usage
                and all(
                    segment.unknown_requests == 0
                    and all(getattr(segment, name) is not None for name in usage_fields)
                    for segment in record.usage
                )
                for record in records
            ),
            cost_complete=len(records) == len(slots)
            and all(record.reported_cost_microunits is not None for record in records),
        ),
        usage=ReportedUsage(
            model_requests_lower_bound=amounts["model_requests"],
            tool_calls_lower_bound=amounts["tool_calls"],
            input_tokens_lower_bound=amounts["input_tokens"],
            output_tokens_lower_bound=amounts["output_tokens"],
            active_milliseconds_lower_bound=amounts["active_milliseconds"],
            unknown_requests=sum(segment.unknown_requests for segment in segments),
            unreported_segments=sum(
                any(getattr(segment, name) is None for name in usage_fields) for segment in segments
            ),
            records_without_usage=sum(not record.usage for record in records),
        ),
        costs=tuple(
            ReportedCost(
                currency=currency,
                microunits_lower_bound=amount,
                reported_records=currency_records[currency],
            )
            for currency, amount in sorted(costs.items())
        ),
        records_without_cost=sum(record.reported_cost_microunits is None for record in records),
    )
