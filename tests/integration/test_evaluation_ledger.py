"""Registration through a reopened application service has no execution dependency."""

from pathlib import Path

from evaluation_ledger_fixtures import ledger_harness, ledger_manifest, preflight_record

from agent_fleet.application.evaluations import EvaluationLedgerService
from agent_fleet.domain.evaluation_campaign import EvaluationLedgerSnapshot
from agent_fleet.domain.outcomes import OutcomeKind, OutcomeUsage


def test_reopened_service_reports_missing_not_run_and_inconclusive_honestly(tmp_path: Path) -> None:
    h = ledger_harness(tmp_path)
    manifest = ledger_manifest()
    h.service.register(manifest)
    empty = h.service.report(manifest.campaign_id)
    assert empty.first_round.planned == 24
    assert empty.first_round.success_percentage is None
    assert not empty.coverage.cost_complete and not empty.coverage.usage_complete
    results: tuple[OutcomeKind, ...] = ("not_run", "inconclusive")
    for index, result in enumerate(results):
        slot = manifest.slots[index]
        reservation = h.service.reserve(
            manifest.campaign_id, slot.case_id, slot.repetition, f"preflight-{index}"
        )
        record = preflight_record(manifest, reservation, result=result, suffix=index + 1)
        record = record.model_copy(
            update={"usage": (OutcomeUsage(segment_id="preflight", active_milliseconds=12),)}
        )
        h.service.record_preflight_outcome(record)
    # A reserved slot interrupted before observation remains missing, never not_run.
    slot = manifest.slots[2]
    h.service.reserve(manifest.campaign_id, slot.case_id, slot.repetition, "interrupted")
    reopened = ledger_harness(tmp_path, migrate=False)
    report = reopened.service.report(manifest.campaign_id)
    assert report == h.service.report(manifest.campaign_id)
    assert report.first_round.success_percentage == 0
    assert report.first_round.observed == 1
    assert report.coverage.missing_outcomes == 34
    assert report.records_without_cost == 2 and report.kr_status == "not_evaluated"
    assert reopened.service.snapshot(manifest.campaign_id).committed.attempts == 3


def test_report_reads_exactly_one_consistent_snapshot(tmp_path: Path) -> None:
    h = ledger_harness(tmp_path)
    manifest = ledger_manifest()
    h.service.register(manifest)

    class CountingStore:
        calls = 0

        def snapshot(self, campaign_id: str) -> EvaluationLedgerSnapshot:
            self.calls += 1
            return h.store.snapshot(campaign_id)

    store = CountingStore()
    # The read-only report path uses just snapshot, not separate potentially racy list calls.
    service = EvaluationLedgerService(store)  # type: ignore[arg-type]
    service.report(manifest.campaign_id)
    assert store.calls == 1
