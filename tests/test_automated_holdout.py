"""Holdout identity exclusion and pending-report tests, without live calls."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from problem_intelligence.arctic_shift_poc import ArcticShiftPocMetrics
from problem_intelligence.automated_discovery import DiscoveryMetrics, ItemOutcome
from problem_intelligence.automated_holdout import (
    REVIEW_FIELDS,
    HoldoutResult,
    load_baseline_reddit_ids,
    main,
    select_unseen_full_items,
    valid_research_user_agent,
    write_holdout_outputs,
)
from problem_intelligence.domain import (
    ContentCompleteness,
    DiscoveryState,
    EvidenceRange,
    EvidenceScope,
    ProblemFamily,
    ProblemType,
    SourceAvailability,
)
from problem_intelligence.reddit import SearchResult
from problem_intelligence.repository import Repository


def add_full(repository: Repository, post_id: str) -> int:
    source_id = repository.upsert_source(source_type="reddit", name="r/Accounting")
    url = f"https://www.reddit.com/r/Accounting/comments/{post_id}/"
    item_id = repository.upsert_source_item(
        source_id=source_id, external_id=f"reddit:submission:{post_id}",
        raw_text="A synthetic operational problem in invoice processing.", url=url,
    )
    run_id = repository.record_discovery_response(
        source_id=source_id, provider="arctic_shift", query="Accounting",
        availability=SourceAvailability.RESULTS, results=(SearchResult(url),),
        capabilities={}, latency_ms=1, cost_usd=None, error=None,
    )
    row = repository.connection.execute(
        "SELECT id FROM discovery_records WHERE run_id = ?", (run_id,)
    ).fetchone()
    assert row is not None
    repository.record_acquisition(
        discovery_id=int(row["id"]), source_item_id=item_id,
        provider="arctic_shift", state=DiscoveryState.CONTENT_COMPLETE,
        completeness=ContentCompleteness.FULL, latency_ms=1,
        cost_usd=None, error=None, metadata={},
    )
    return item_id


def test_holdout_excludes_every_baseline_reddit_identity(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.db"
    baseline = Repository(baseline_path)
    baseline.initialize()
    add_full(baseline, "old123")
    baseline.close()
    baseline_ids = load_baseline_reddit_ids(baseline_path)
    assert "reddit:submission:old123" in baseline_ids

    holdout = Repository()
    holdout.initialize()
    try:
        old = add_full(holdout, "old123")
        fresh = add_full(holdout, "new456")
        selected, overlap = select_unseen_full_items(holdout, baseline_ids)
        assert old not in selected
        assert selected == (fresh,)
        assert overlap == 1
        acquisition = holdout.connection.execute(
            "SELECT id FROM acquisition_records WHERE source_item_id = ?", (fresh,)
        ).fetchone()
        assert acquisition is not None
        current_only, current_overlap = select_unseen_full_items(
            holdout, baseline_ids, acquisition_ids=(int(acquisition["id"]),),
        )
        assert current_only == (fresh,) and current_overlap == 0
    finally:
        holdout.close()


def test_pending_outputs_do_not_invent_holdout_results(tmp_path: Path) -> None:
    write_holdout_outputs(
        None, None, tmp_path, status="NOT_RUN_CONFIGURATION_REQUIRED",
        blocker="model credential unavailable",
    )
    metrics = json.loads((tmp_path / "automated_discovery_holdout_metrics.json").read_text())
    assert metrics["real_holdout_run"] is False
    assert metrics["records_acquired"] is None
    assert metrics["cost_usd"] == "UNKNOWN"
    report = (tmp_path / "automated_discovery_holdout.md").read_text()
    assert "No unseen holdout inference has run" in report
    with (tmp_path / "automated_discovery_review.csv").open(newline="") as handle:
        rows = list(csv.reader(handle))
    assert rows == [list(REVIEW_FIELDS)]


def test_live_report_uses_only_stored_observations_and_blank_human_labels(
    tmp_path: Path,
) -> None:
    repository = Repository()
    repository.initialize()
    try:
        item_id = add_full(repository, "new789")
        text = repository.source_items((item_id,))[0].raw_text
        observation_id, _ = repository.create_observation_with_evidence(
            source_item_id=item_id, problem_type=ProblemType.WORKFLOW_GAP,
            problem_family=ProblemFamily.MANUAL_DATA_ENTRY,
            evidence_scope=EvidenceScope.GLOBAL,
            problem="Synthetic invoice-processing problem",
            extraction_version="automated-test",
            evidence_ranges=(EvidenceRange(0, len(text)),),
        )
        acquisition = ArcticShiftPocMetrics(records_received=1)
        inference = DiscoveryMetrics(
            processed_items=1, valid_observations=1,
            outcomes=[ItemOutcome(item_id, "OBSERVATION", observation_id)],
        )
        result = HoldoutResult(acquisition, inference, 250, 0, 0.5)
        write_holdout_outputs(
            repository, result, tmp_path, status="INFERENCE_COMPLETED",
        )
        report = (tmp_path / "automated_discovery_holdout.md").read_text()
        assert "Synthetic invoice-processing problem" in report
        assert "SINGLE_SIGNAL" in report
        assert "AUTOMATED_DISCOVERY_NEEDS_TUNING" in report
        with (tmp_path / "automated_discovery_review.csv").open(newline="") as handle:
            rows = list(csv.DictReader(handle))
        assert len(rows) == 1
        assert rows[0]["problem_statement"] == "Synthetic invoice-processing problem"
        assert rows[0]["human_problem_label"] == ""
    finally:
        repository.close()


def test_local_holdout_gate_does_not_require_openai_key(
    tmp_path: Path, monkeypatch: object,
) -> None:
    from pytest import MonkeyPatch

    patch = monkeypatch
    assert isinstance(patch, MonkeyPatch)
    patch.setenv("DISCOVERY_LLM_PROVIDER", "openai_compatible")
    patch.setenv("DISCOVERY_BASE_URL", "http://127.0.0.1:8000/v1")
    patch.setenv("DISCOVERY_MODEL", "local")
    patch.setenv("DISCOVERY_LOCAL_INFERENCE", "true")
    patch.delenv("OPENAI_API_KEY", raising=False)
    patch.setenv("ARCTIC_SHIFT_USER_AGENT", "GlobalProblemIntelligence/0.1 (research prototype)")
    calls: list[str] = []

    def fail_after_check(*_args: object, **_kwargs: object) -> None:
        calls.append("checked")
        raise RuntimeError("synthetic check stubbed before acquisition")

    patch.setattr("problem_intelligence.automated_holdout.check_model", fail_after_check)
    status = main(["--output", str(tmp_path)])
    assert status == 1 and calls == ["checked"]
    report = (tmp_path / "automated_discovery_holdout.md").read_text()
    assert "synthetic check stubbed" in report
    assert "OPENAI_API_KEY" not in report
    assert valid_research_user_agent("GlobalProblemIntelligence/0.1 (research prototype)")
    assert not valid_research_user_agent("Mozilla/5.0 (fake browser)")
