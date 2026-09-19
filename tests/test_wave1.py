from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from problem_intelligence.domain import (
    ContentCompleteness,
    DiscoveryState,
    EvidenceRange,
    EvidenceScope,
    ProblemType,
    SourceAvailability,
)
from problem_intelligence.reddit import SearchResult, canonicalize_reddit_url
from problem_intelligence.repository import Repository
from problem_intelligence.source_health import AccessResult, HealthStatus, run_health_checks
from problem_intelligence.wave1 import (
    AcquisitionCounts,
    WaveSlot,
    cost_per_strong_signal,
    per_thousand,
    select_wave_sources,
)
from problem_intelligence.wave1_report import build_wave1_review, wave1_rows
from tests.test_source_health import capture


class _Provider:
    name = "test"

    def __init__(self, values: dict[str, object]) -> None:
        self.values = values

    def check(self, source: str):  # type: ignore[no-untyped-def]
        return self.values[source]


class WaveOneTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.repository = Repository(Path(self.temporary.name) / "wave.db")
        self.repository.initialize()
        for name in ("r/Accounting", "r/Bookkeeping", "r/HVAC"):
            source_id = self.repository.upsert_source(source_type="reddit", name=name)
            self.repository.connection.execute(
                """INSERT INTO source_registry_profiles
                   (source_id, platform, audience_type, strict_relevance)
                   VALUES (?, 'reddit', 'PRACTITIONER', 'CORE')""",
                (source_id,),
            )
        self.repository.connection.commit()

    def tearDown(self) -> None:
        self.repository.close()
        self.temporary.cleanup()

    def test_restricted_primary_is_replaced_only_by_active_core_backup(self) -> None:
        accounting = self.repository.connection.execute(
            "SELECT id FROM sources WHERE name = 'r/Accounting'"
        ).fetchone()[0]
        bookkeeping = self.repository.connection.execute(
            "SELECT id FROM sources WHERE name = 'r/Bookkeeping'"
        ).fetchone()[0]
        provider = _Provider({
            "r/Accounting": replace(
                capture(), access_result=AccessResult.ACCESS_RESTRICTED,
                reason="Explicit private access result.",
            ),
            "r/Bookkeeping": replace(
                capture("r/Bookkeeping"),
                evidence_urls=("https://www.reddit.com/r/Bookkeeping/comments/abc123/",),
            ),
        })
        run_health_checks(
            self.repository,
            provider,
            ((accounting, "r/Accounting"), (bookkeeping, "r/Bookkeeping")),
        )
        selected = select_wave_sources(
            self.repository, (WaveSlot(1, "office", "r/Accounting", "r/Bookkeeping", 120),)
        )[0]
        self.assertEqual(selected.source, "r/Bookkeeping")
        self.assertEqual(selected.health_status, HealthStatus.ACTIVE)
        self.assertEqual(selected.selection_status, "REPLACED_WITH_ACTIVE_BACKUP")
        self.assertFalse(selected.policy_ready)
        self.assertFalse(selected.acquisition_eligible)
        self.repository.connection.execute(
            """UPDATE sources SET access_method = 'test-provider',
                   commercial_use_status = 'APPROVED', retention_rules = '30 days',
                   attribution_requirements = 'canonical URL', quoting_rules = 'short excerpts',
                   deletion_requirements = 'honor removals', rate_limit_notes = 'documented',
                   rights_reviewed_at = '2026-09-19' WHERE id = ?""",
            (bookkeeping,),
        )
        eligible = select_wave_sources(
            self.repository, (WaveSlot(1, "office", "r/Accounting", "r/Bookkeeping", 120),)
        )[0]
        self.assertTrue(eligible.policy_ready)
        self.assertTrue(eligible.acquisition_eligible)

    def test_unchecked_candidates_are_not_executable_or_poor_yield(self) -> None:
        selected = select_wave_sources(
            self.repository, (WaveSlot(1, "office", "r/Accounting", "r/Bookkeeping", 120),)
        )
        self.assertFalse(selected[0].acquisition_eligible)
        row = wave1_rows(self.repository, selected)[0]
        self.assertEqual(row["usable_items"], 0)
        self.assertIsNone(row["pain_per_1000_usable"])
        self.assertIsNone(row["pain_observations"])
        self.assertEqual(row["research_quality"], "UNMEASURED")

    def test_completeness_deduplication_and_normalization(self) -> None:
        variants = (
            "https://old.reddit.com/r/Accounting/comments/abc123/title/?q=1",
            "https://www.reddit.com/r/accounting/comments/abc123/other/",
            "https://www.reddit.com/r/Accounting/comments/def456/",
        )
        canonical = {canonicalize_reddit_url(url).canonical_url for url in variants}
        self.assertEqual(len(canonical), 2)
        counts = AcquisitionCounts(120, 3, len(canonical), 1, 1, 0, 0)
        self.assertEqual(counts.duplicates_removed, 1)
        self.assertEqual(counts.usable, 1)
        self.assertEqual(counts.acquisition_success_rate, 0.5)
        self.assertEqual(per_thousand(2, 100), 20.0)
        self.assertIsNone(per_thousand(2, 0))
        self.assertEqual(cost_per_strong_signal(3.0, 2), 1.5)
        self.assertIsNone(cost_per_strong_signal(3.0, 0))

    def test_review_package_separates_grounded_weak_and_no_pain(self) -> None:
        source_id = self.repository.connection.execute(
            "SELECT id FROM sources WHERE name = 'r/Accounting'"
        ).fetchone()[0]
        urls = (
            "https://www.reddit.com/r/Accounting/comments/abc123/",
            "https://www.reddit.com/r/Accounting/comments/def456/",
        )
        run_id = self.repository.record_discovery_response(
            source_id=source_id,
            provider="test-search",
            query="office workflow",
            availability=SourceAvailability.RESULTS,
            results=[SearchResult(url) for url in urls],
            capabilities={}, latency_ms=10, cost_usd=0.0, error=None,
            requested_items=2,
        )
        discovery_ids = [
            row[0] for row in self.repository.connection.execute(
                "SELECT id FROM discovery_records WHERE run_id = ? ORDER BY id", (run_id,)
            )
        ]
        texts = (
            "I manually reconcile invoices every week and it takes too long.",
            "I enjoy my accounting team and have no workflow issue to report.",
        )
        item_ids = []
        for index, (discovery_id, url, raw_text) in enumerate(
            zip(discovery_ids, urls, texts, strict=True)
        ):
            item_id = self.repository.upsert_source_item(
                source_id=source_id, external_id=f"reddit:submission:{('abc123', 'def456')[index]}",
                raw_text=raw_text, url=url,
            )
            item_ids.append(item_id)
            self.repository.record_acquisition(
                discovery_id=discovery_id, source_item_id=item_id,
                provider="test-content", state=DiscoveryState.CONTENT_COMPLETE,
                completeness=ContentCompleteness.FULL, latency_ms=20,
                cost_usd=0.0, error=None, metadata={"provider_invocation": True},
            )
        evidence = "manually reconcile invoices"
        start = texts[0].index(evidence)
        self.repository.create_observation_with_evidence(
            source_item_id=item_ids[0], problem_type=ProblemType.WORKFLOW_GAP,
            evidence_scope=EvidenceScope.GLOBAL,
            problem="Invoice reconciliation remains manual.",
            extraction_version="wave-test",
            evidence_ranges=(EvidenceRange(start, start + len(evidence)),),
            fields={"actor": "accountant", "context": "weekly close"},
        )
        prediction_path = Path(self.temporary.name) / "predictions.jsonl"
        prediction_path.write_text(
            json.dumps({
                "source_item_id": item_ids[1], "external_id": "reddit:submission:def456",
                "is_problem": False,
            }) + "\n", encoding="utf-8",
        )
        selected = select_wave_sources(
            self.repository, (WaveSlot(1, "office", "r/Accounting", "r/HVAC", 120),)
        )
        review = build_wave1_review(self.repository, selected, predictions=prediction_path)
        self.assertEqual(wave1_rows(self.repository, selected)[0]["requested_items"], 2)
        self.assertIn("Invoice reconciliation remains manual", review)
        self.assertIn("manually reconcile invoices", review)
        self.assertIn("WEAK", review)
        self.assertIn("NO_PAIN", review)
        self.assertIn(urls[1], review)


if __name__ == "__main__":
    unittest.main()
