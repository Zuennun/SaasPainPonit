from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from problem_intelligence.reddit import canonicalize_reddit_url
from problem_intelligence.repository import Repository
from problem_intelligence.source_health import AccessResult, HealthStatus, run_health_checks
from problem_intelligence.wave1 import (
    AcquisitionCounts,
    WaveSlot,
    cost_per_strong_signal,
    per_thousand,
    select_wave_sources,
)
from problem_intelligence.wave1_report import wave1_rows
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
        self.assertTrue(selected.acquisition_eligible)

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


if __name__ == "__main__":
    unittest.main()
