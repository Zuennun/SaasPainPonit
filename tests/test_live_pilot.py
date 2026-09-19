"""Provider-neutral live pilot orchestration: manifest selection, dry-run,
resumable/failure-safe execution, and reuse of the existing acquisition/research
quality separation for reporting."""

from __future__ import annotations

import json
import tempfile
import unittest
from collections.abc import Sequence
from pathlib import Path

from problem_intelligence.domain import (
    ContentCompleteness,
    DiscoveryState,
    EvidenceRange,
    EvidenceScope,
    ProblemFamily,
    ProblemType,
    SourceAvailability,
    SourceItemRecord,
)
from problem_intelligence.extraction import ObservationDraft, run_extraction
from problem_intelligence.live_pilot import (
    MANIFEST_FIELDS,
    REVIEW_FIELDS,
    LiveManifestEntry,
    LivePilotRunResult,
    SourceRunOutcome,
    SourceRunStatus,
    build_dry_run_report,
    build_review_export_rows,
    live_pilot_wave_selections,
    read_live_manifest_csv,
    run_live_pilot,
    select_live_pilot_manifest,
    write_live_manifest_csv,
    write_review_export_csv,
)
from problem_intelligence.pilot_planner import PilotPlan, PilotPlanEntry
from problem_intelligence.reddit import SearchResult
from problem_intelligence.reddit_provider_registry import LiveRunGateResult
from problem_intelligence.repository import Repository
from problem_intelligence.wave1_report import wave1_rows


def _entry(
    source_id: int, name: str, category: str, *, relevance: str = "CORE",
    ready: bool = True, conflict: str | None = None,
) -> PilotPlanEntry:
    return PilotPlanEntry(
        ordering=source_id, source_id=source_id, source_name=name, category=category,
        target_group="testers", relevance_status=relevance, activity_status="ACTIVE",
        access_status="NOT_FLAGGED", recommended_action="SCAN_PILOT_NOW", ready=ready,
        pilot_size=50, reason="synthetic test entry", conflict=conflict,
    )


class ManifestSelectionTests(unittest.TestCase):
    def test_selects_only_ready_core_conflict_free_and_round_robins_categories(self) -> None:
        entries = (
            _entry(1, "r/A1", "Accounting"), _entry(2, "r/A2", "Accounting"),
            _entry(3, "r/H1", "HVAC"),
            _entry(4, "r/P1", "PILOT_ONLY", relevance="PILOT"),
            _entry(5, "r/Blocked", "Legal", ready=False),
            _entry(6, "r/Conflict", "Legal", conflict="sizing conflict"),
        )
        plan = PilotPlan(entries=entries)
        selected = select_live_pilot_manifest(plan, max_sources=3, item_target=100)
        subreddits = [entry.subreddit for entry in selected]
        self.assertEqual(len(subreddits), 3)
        self.assertIn("r/A1", subreddits)
        self.assertIn("r/H1", subreddits)
        self.assertNotIn("r/P1", subreddits)  # PILOT, not CORE
        self.assertNotIn("r/Blocked", subreddits)  # not ready
        self.assertNotIn("r/Conflict", subreddits)  # sizing conflict
        self.assertTrue(all(entry.pilot_item_target == 100 for entry in selected))

    def test_selection_is_deterministic(self) -> None:
        entries = tuple(
            _entry(i, f"r/S{i}", f"Category{i % 4}") for i in range(1, 13)
        )
        plan = PilotPlan(entries=entries)
        first = select_live_pilot_manifest(plan, max_sources=6)
        second = select_live_pilot_manifest(plan, max_sources=6)
        self.assertEqual(first, second)

    def test_rejects_non_positive_arguments(self) -> None:
        plan = PilotPlan(entries=(_entry(1, "r/A", "Accounting"),))
        with self.assertRaises(ValueError):
            select_live_pilot_manifest(plan, max_sources=0)
        with self.assertRaises(ValueError):
            select_live_pilot_manifest(plan, item_target=0)


class ManifestCsvTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "manifest.csv"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_round_trip_and_provider_independence(self) -> None:
        entries = (
            LiveManifestEntry("r/Accounting", "Finance", "Accountants", 100, "CORE", "ACTIVE",
                               "NOT_FLAGGED"),
            LiveManifestEntry("r/HVAC", "Trades", None, 100, "CORE", "ACTIVE", "NOT_FLAGGED"),
        )
        write_live_manifest_csv(self.path, entries)
        loaded = read_live_manifest_csv(self.path)
        self.assertEqual(loaded, entries)
        header = self.path.read_text(encoding="utf-8").splitlines()[0]
        self.assertNotIn("query_id", header.lower())
        self.assertNotIn("provider", header.lower())
        self.assertEqual(MANIFEST_FIELDS, tuple(header.split(",")))

    def test_rejects_duplicate_subreddits(self) -> None:
        entries = (
            LiveManifestEntry("r/Accounting", "Finance", None, 100, "CORE", "ACTIVE",
                               "NOT_FLAGGED"),
            LiveManifestEntry("r/accounting", "Finance", None, 100, "CORE", "ACTIVE",
                               "NOT_FLAGGED"),
        )
        write_live_manifest_csv(self.path, entries)
        with self.assertRaises(ValueError):
            read_live_manifest_csv(self.path)

    def test_rejects_empty_manifest(self) -> None:
        write_live_manifest_csv(self.path, ())
        with self.assertRaises(ValueError):
            read_live_manifest_csv(self.path)


class DryRunTests(unittest.TestCase):
    def test_dry_run_makes_no_calls_and_reports_estimate_and_blockers(self) -> None:
        manifest = (
            LiveManifestEntry("r/A", "Cat", None, 100, "CORE", "ACTIVE", "NOT_FLAGGED"),
            LiveManifestEntry("r/B", "Cat", None, 45, "CORE", "ACTIVE", "NOT_FLAGGED"),
        )
        gate = LiveRunGateResult(allowed=False, reasons=("credentials missing",))
        report = build_dry_run_report(
            provider="brandwatch", manifest=manifest, max_sources=25,
            max_items_per_source=100, gate=gate, capabilities={"supports_reddit": True},
            page_size=20,
        )
        self.assertEqual(report.selected_source_count, 2)
        self.assertEqual(report.total_requested_items, 145)
        # 100 items / 20 page_size = 5 pages, x2 (discover+fulltext) = 10
        # 45 items / 20 page_size = 3 pages (ceil), x2 = 6
        self.assertEqual(report.estimated_acquisition_operations, 16)
        payload = report.to_dict()
        self.assertFalse(payload["allowed"])
        self.assertEqual(payload["blocked_reasons"], ["credentials missing"])
        self.assertFalse(payload["made_external_requests"])

    def test_dry_run_respects_max_sources_and_max_items_caps(self) -> None:
        manifest = tuple(
            LiveManifestEntry(f"r/S{i}", "Cat", None, 200, "CORE", "ACTIVE", "NOT_FLAGGED")
            for i in range(5)
        )
        gate = LiveRunGateResult(allowed=True, reasons=())
        report = build_dry_run_report(
            provider="brandwatch", manifest=manifest, max_sources=2,
            max_items_per_source=50, gate=gate, capabilities={},
        )
        self.assertEqual(report.selected_source_count, 2)
        self.assertTrue(all(source.pilot_item_target == 50 for source in report.sources))


class ResumableExecutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.state_path = Path(self.temporary.name) / "state.json"
        self.manifest = (
            LiveManifestEntry("r/A", "Cat", None, 10, "CORE", "ACTIVE", "NOT_FLAGGED"),
            LiveManifestEntry("r/B", "Cat", None, 10, "CORE", "ACTIVE", "NOT_FLAGGED"),
            LiveManifestEntry("r/C", "Cat", None, 10, "CORE", "ACTIVE", "NOT_FLAGGED"),
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_blocked_gate_never_calls_acquire_source(self) -> None:
        calls: list[str] = []

        def acquire(entry: LiveManifestEntry) -> SourceRunOutcome:
            calls.append(entry.subreddit)
            return SourceRunOutcome(SourceRunStatus.COMPLETE)

        gate = LiveRunGateResult(allowed=False, reasons=("blocked",))
        with self.assertRaises(ValueError):
            run_live_pilot(
                provider="brandwatch", sources=self.manifest, gate=gate,
                acquire_source=acquire, state_path=self.state_path,
            )
        self.assertEqual(calls, [])

    def test_one_failed_source_does_not_abort_or_discard_completed_results(self) -> None:
        def acquire(entry: LiveManifestEntry) -> SourceRunOutcome:
            if entry.subreddit == "r/B":
                raise RuntimeError("provider unavailable")
            return SourceRunOutcome(SourceRunStatus.COMPLETE, acquisition_ids=(1,))

        gate = LiveRunGateResult(allowed=True, reasons=())
        result = run_live_pilot(
            provider="brandwatch", sources=self.manifest, gate=gate,
            acquire_source=acquire, state_path=self.state_path,
        )
        self.assertEqual(set(result.completed), {"r/A", "r/C"})
        self.assertEqual(result.failed, ("r/B",))
        self.assertEqual(result.outcomes["r/B"].error, "provider unavailable")

    def test_resume_skips_completed_sources_and_retries_failed_ones(self) -> None:
        calls: list[str] = []

        def failing_acquire(entry: LiveManifestEntry) -> SourceRunOutcome:
            calls.append(entry.subreddit)
            if entry.subreddit == "r/B":
                raise RuntimeError("transient failure")
            return SourceRunOutcome(SourceRunStatus.COMPLETE)

        gate = LiveRunGateResult(allowed=True, reasons=())
        first = run_live_pilot(
            provider="brandwatch", sources=self.manifest, gate=gate,
            acquire_source=failing_acquire, state_path=self.state_path,
        )
        self.assertEqual(set(first.completed), {"r/A", "r/C"})
        self.assertEqual(first.failed, ("r/B",))
        self.assertEqual(calls, ["r/A", "r/B", "r/C"])

        calls.clear()

        def succeeding_acquire(entry: LiveManifestEntry) -> SourceRunOutcome:
            calls.append(entry.subreddit)
            return SourceRunOutcome(SourceRunStatus.COMPLETE)

        second = run_live_pilot(
            provider="brandwatch", sources=self.manifest, gate=gate,
            acquire_source=succeeding_acquire, state_path=self.state_path,
        )
        # r/A and r/C were already COMPLETE and must not be re-acquired.
        self.assertEqual(calls, ["r/B"])
        self.assertEqual(set(second.completed), {"r/A", "r/B", "r/C"})
        self.assertEqual(second.outcomes["r/A"].status, SourceRunStatus.SKIPPED)
        self.assertEqual(second.outcomes["r/C"].status, SourceRunStatus.SKIPPED)

    def test_state_file_persists_status_per_source(self) -> None:
        def acquire(entry: LiveManifestEntry) -> SourceRunOutcome:
            return SourceRunOutcome(SourceRunStatus.COMPLETE)

        gate = LiveRunGateResult(allowed=True, reasons=())
        run_live_pilot(
            provider="brandwatch", sources=self.manifest, gate=gate,
            acquire_source=acquire, state_path=self.state_path,
        )
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertEqual(state, {"r/A": "COMPLETE", "r/B": "COMPLETE", "r/C": "COMPLETE"})


class ReportingReuseTests(unittest.TestCase):
    """Acquisition and research quality stay separated by reusing wave1_report as-is."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.repository = Repository(Path(self.temporary.name) / "pilot.db")
        self.repository.initialize()

    def tearDown(self) -> None:
        self.repository.close()
        self.temporary.cleanup()

    def test_live_pilot_selections_feed_wave1_rows_with_both_layers_present(self) -> None:
        manifest = (
            LiveManifestEntry("r/Accounting", "Finance", None, 10, "CORE", "ACTIVE",
                               "NOT_FLAGGED"),
        )
        selections = live_pilot_wave_selections(manifest)
        self.assertEqual(selections[0].source, "r/Accounting")
        self.assertEqual(selections[0].selection_status, "LIVE_PILOT_MANIFEST")
        rows = wave1_rows(self.repository, selections)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        # Acquisition-quality fields present.
        for field in ("full_items", "partial_items", "metadata_only_items", "duplicates_removed"):
            self.assertIn(field, row)
        # Research-quality fields present, and gated (None, not 0) when nothing is FULL.
        for field in ("pain_observations", "strong_signals", "payment_signals"):
            self.assertIn(field, row)
            self.assertIsNone(row[field])
        self.assertEqual(row["research_quality"], "UNMEASURED")

    def test_acquisition_eligible_reflects_run_outcome(self) -> None:
        manifest = (
            LiveManifestEntry("r/A", "Cat", None, 10, "CORE", "ACTIVE", "NOT_FLAGGED"),
            LiveManifestEntry("r/B", "Cat", None, 10, "CORE", "ACTIVE", "NOT_FLAGGED"),
        )
        result = LivePilotRunResult(provider="brandwatch", outcomes={
            "r/A": SourceRunOutcome(SourceRunStatus.COMPLETE),
            "r/B": SourceRunOutcome(SourceRunStatus.FAILED, error="boom"),
        })
        selections = live_pilot_wave_selections(manifest, result)
        by_source = {s.source: s for s in selections}
        self.assertTrue(by_source["r/A"].acquisition_eligible)
        self.assertFalse(by_source["r/B"].acquisition_eligible)


class ReviewExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.repository = Repository(Path(self.temporary.name) / "review.db")
        self.repository.initialize()
        self.source_id = self.repository.upsert_source(source_type="reddit", name="r/Accounting")

    def tearDown(self) -> None:
        self.repository.close()
        self.temporary.cleanup()

    def _ingest_full_item(
        self, external_id: str, text: str, *, title: str | None = None,
    ) -> int:
        return self.repository.upsert_source_item(
            source_id=self.source_id, external_id=external_id, raw_text=text, title=title,
            url=f"https://www.reddit.com/r/Accounting/comments/{external_id}/",
        )

    def test_review_rows_have_blank_human_columns_and_real_evidence(self) -> None:
        item_id = self._ingest_full_item(
            "ab1", "We manually reconcile duplicate invoices weekly.",
            title="Manual invoice pain",
        )
        run_id = self.repository.record_discovery_response(
            source_id=self.source_id, provider="brandwatch", query="q1",
            availability=SourceAvailability.RESULTS,
            results=(SearchResult("https://www.reddit.com/r/Accounting/comments/ab1/"),),
            capabilities={}, latency_ms=1, cost_usd=None, error=None,
        )
        discovery = self.repository.connection.execute(
            "SELECT id FROM discovery_records WHERE run_id = ?", (run_id,)
        ).fetchone()
        self.repository.record_acquisition(
            discovery_id=int(discovery["id"]), source_item_id=item_id, provider="brandwatch",
            state=DiscoveryState.CONTENT_COMPLETE,
            completeness=ContentCompleteness.FULL, latency_ms=1, cost_usd=None, error=None,
            metadata={},
        )

        class Extractor:
            version = "review-export-test-v1"

            def extract(self, item: SourceItemRecord) -> Sequence[ObservationDraft]:
                phrase = "duplicate invoices"
                start = item.raw_text.index(phrase)
                return (ObservationDraft(
                    problem_type=ProblemType.WORKFLOW_GAP,
                    problem_family=ProblemFamily.MANUAL_DATA_ENTRY,
                    evidence_scope=EvidenceScope.GLOBAL,
                    problem="Manual duplicate invoice reconciliation",
                    evidence_ranges=(EvidenceRange(start, start + len(phrase)),),
                ),)

        run_extraction(self.repository, Extractor(), source_item_ids=(item_id,))
        selections = live_pilot_wave_selections((
            LiveManifestEntry("r/Accounting", "Finance", None, 10, "CORE", "ACTIVE",
                               "NOT_FLAGGED"),
        ))
        rows = build_review_export_rows(self.repository, selections)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["subreddit"], "r/Accounting")
        self.assertEqual(row["title"], "Manual invoice pain")
        self.assertIn("duplicate invoices", row["source_context"])
        self.assertIn("duplicate invoices", row["evidence_text"])
        self.assertEqual(row["source_completeness"], "FULL")
        self.assertEqual(row["provider"], "brandwatch")
        self.assertIn("active_solution_search", row)
        for field in (
            "human_pain_label", "human_strength_label", "human_cluster_notes",
            "human_extraction_notes", "reviewer_notes",
        ):
            self.assertEqual(row[field], "")

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "review.csv"
            write_review_export_csv(path, rows)
            header = path.read_text(encoding="utf-8").splitlines()[0]
            self.assertEqual(REVIEW_FIELDS, tuple(header.split(",")))

    def test_source_context_is_bounded_not_the_full_raw_text(self) -> None:
        from problem_intelligence.live_pilot import CONTEXT_EXCERPT_CHARS

        long_text = "We manually reconcile duplicate invoices weekly. " + ("padding " * 200)
        item_id = self._ingest_full_item("ab2", long_text, title="Long post")
        self.repository.create_observation_with_evidence(
            source_item_id=item_id, problem_type=ProblemType.WORKFLOW_GAP,
            evidence_scope=EvidenceScope.GLOBAL, problem="Manual invoice reconciliation",
            extraction_version="test-v1",
            evidence_ranges=(EvidenceRange(0, len("We manually reconcile duplicate invoices")),),
        )
        run_id = self.repository.record_discovery_response(
            source_id=self.source_id, provider="brandwatch", query="q1",
            availability=SourceAvailability.RESULTS,
            results=(SearchResult("https://www.reddit.com/r/Accounting/comments/ab2/"),),
            capabilities={}, latency_ms=1, cost_usd=None, error=None,
        )
        discovery = self.repository.connection.execute(
            "SELECT id FROM discovery_records WHERE run_id = ?", (run_id,)
        ).fetchone()
        self.repository.record_acquisition(
            discovery_id=int(discovery["id"]), source_item_id=item_id, provider="brandwatch",
            state=DiscoveryState.CONTENT_COMPLETE, completeness=ContentCompleteness.FULL,
            latency_ms=1, cost_usd=None, error=None, metadata={},
        )
        selections = live_pilot_wave_selections((
            LiveManifestEntry("r/Accounting", "Finance", None, 10, "CORE", "ACTIVE",
                               "NOT_FLAGGED"),
        ))
        rows = build_review_export_rows(self.repository, selections)
        self.assertEqual(len(rows), 1)
        self.assertLess(len(rows[0]["source_context"]), len(long_text))
        self.assertLessEqual(len(rows[0]["source_context"]), CONTEXT_EXCERPT_CHARS + 1)

    def test_no_observations_yields_empty_review(self) -> None:
        selections = live_pilot_wave_selections((
            LiveManifestEntry("r/Accounting", "Finance", None, 10, "CORE", "ACTIVE",
                               "NOT_FLAGGED"),
        ))
        rows = build_review_export_rows(self.repository, selections)
        self.assertEqual(rows, ())


if __name__ == "__main__":
    unittest.main()
