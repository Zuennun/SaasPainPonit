"""Both Reddit acquisition shapes must converge on one canonical domain layer.

`acquire_discoveries` (URL-discovery: SearchProvider + AcquisitionProvider) and
`ingest_provider_records` (feed/data-provider: RedditDataProvider, e.g. Brandwatch) are
intentionally different acquisition strategies, but both write through
`Repository.ingest_reddit_content`. These tests prove the two paths never diverge in
what lands in the domain: no duplicate SourceItems, provenance preserved per provider,
completeness only ever upgrades, and conflicting FULL payloads are flagged rather than
merged or silently overwritten.
"""

from __future__ import annotations

import unittest
from collections.abc import Sequence
from typing import Any

from problem_intelligence.connectors import SourceItemInput
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
from problem_intelligence.reddit import (
    AcquisitionResponse,
    ProviderCapabilities,
    SearchResponse,
    SearchResult,
    acquire_discoveries,
    canonicalize_reddit_url,
    discover_subreddits,
    ingest_provider_records,
)
from problem_intelligence.reddit_provider import RedditProviderRecord
from problem_intelligence.repository import IntegrityError, Repository

CAPABILITIES = {
    "supports_search": True,
    "supports_full_content": True,
    "supports_comments": False,
    "supports_date_filter": False,
    "supports_subreddit_filter": True,
    "supports_pagination": False,
    "supports_historical_search": True,
}


def _feed_record(
    url: str,
    *,
    completeness: ContentCompleteness,
    text: str = "",
    provider: str = "FEEDPROVIDER",
    acquired_at: str = "2026-09-19T10:00:00+00:00",
) -> RedditProviderRecord:
    identity = canonicalize_reddit_url(url)
    assert identity is not None
    provenance = {
        "original_platform": "REDDIT",
        "provider": provider,
        "body_complete": completeness is ContentCompleteness.FULL,
        "retrieved_at": acquired_at,
        "acquired_at": acquired_at,
        "content_completeness": completeness.value,
    }
    item = (
        SourceItemInput(
            external_id=identity.external_id, raw_text=text, url=identity.canonical_url,
            title="Feed title", metadata=provenance,
        )
        if completeness is not ContentCompleteness.METADATA_ONLY
        else None
    )
    return RedditProviderRecord(
        source=f"r/{identity.subreddit}", item=item, completeness=completeness,
        canonical_url=identity.canonical_url, provider=provider, provider_record_id="1",
        provider_query_id="q1", published_at=acquired_at, acquired_at=acquired_at,
        missing_fields=(), provenance=provenance,
    )


class CrossPathIngestionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = Repository()
        self.repository.initialize()
        self.source_id = self.repository.upsert_source(
            source_type="reddit", name="r/Accounting",
        )

    def tearDown(self) -> None:
        self.repository.close()

    def _search_acquire(
        self, url: str, *, completeness: ContentCompleteness, text: str, provider: str,
    ) -> None:
        discover_subreddits(
            self.repository, _StubSearch(url, provider), subreddits=("Accounting",),
            query_groups=("manual_work",),
        )
        state = (
            "CONTENT_COMPLETE" if completeness is ContentCompleteness.FULL else "CONTENT_PARTIAL"
        )
        metadata = (
            {"body_complete": True, "retrieved_at": "2026-09-19T10:00:00+00:00"}
            if completeness is ContentCompleteness.FULL else None
        )
        acquire_discoveries(self.repository, _StubAcquisition(
            url, provider, state, completeness.value, text, metadata,
        ))

    def test_same_submission_through_both_paths_is_one_source_item_two_acquisitions(
        self,
    ) -> None:
        url = "https://www.reddit.com/r/Accounting/comments/xy1/thread/"
        self._search_acquire(
            url, completeness=ContentCompleteness.PARTIAL,
            text="A short preview from search discovery.", provider="search-provider",
        )
        ingest_provider_records(
            self.repository, source_id=self.source_id, provider="brandwatch", query="q1",
            records=(_feed_record(
                url, completeness=ContentCompleteness.FULL,
                text="A full synthetic body about duplicate invoice entry.",
            ),),
            capabilities={"supports_reddit": True},
        )
        self.assertEqual(self.repository.stats()["source_items"], 1)
        self.assertEqual(self.repository.stats()["acquisition_records"], 2)
        providers = {
            row["provider"]
            for row in self.repository.connection.execute(
                "SELECT provider FROM acquisition_records"
            ).fetchall()
        }
        self.assertEqual(providers, {"search-provider", "brandwatch"})
        row = self.repository.connection.execute(
            "SELECT raw_text FROM source_items"
        ).fetchone()
        self.assertIn("duplicate invoice entry", row["raw_text"])

    def test_submission_and_comment_never_collapse_but_each_dedupes_across_paths(
        self,
    ) -> None:
        submission_url = "https://www.reddit.com/r/Accounting/comments/xy2/thread/"
        comment_url = "https://www.reddit.com/r/Accounting/comments/xy2/thread/cm1/"
        self._search_acquire(
            submission_url, completeness=ContentCompleteness.PARTIAL,
            text="Submission preview text here.", provider="search-provider",
        )
        ingest_provider_records(
            self.repository, source_id=self.source_id, provider="brandwatch", query="q1",
            records=(_feed_record(
                submission_url, completeness=ContentCompleteness.FULL,
                text="Submission full text about manual reconciliation.",
            ),),
            capabilities={"supports_reddit": True},
        )
        ingest_provider_records(
            self.repository, source_id=self.source_id, provider="brandwatch", query="q1",
            records=(_feed_record(
                comment_url, completeness=ContentCompleteness.FULL,
                text="Comment full text with a different workaround.",
            ),),
            capabilities={"supports_reddit": True},
        )
        self._search_acquire(
            comment_url, completeness=ContentCompleteness.PARTIAL,
            text="Comment preview text.", provider="search-provider",
        )
        self.assertEqual(self.repository.stats()["source_items"], 2)
        external_ids = {
            row["external_id"]
            for row in self.repository.connection.execute(
                "SELECT external_id FROM source_items"
            ).fetchall()
        }
        self.assertEqual(external_ids, {"reddit:submission:xy2", "reddit:comment:xy2:cm1"})

    def test_full_content_is_never_downgraded_by_a_later_partial_acquisition(self) -> None:
        url = "https://www.reddit.com/r/Accounting/comments/xy3/thread/"
        ingest_provider_records(
            self.repository, source_id=self.source_id, provider="brandwatch", query="q1",
            records=(_feed_record(
                url, completeness=ContentCompleteness.FULL,
                text="The richer FULL text acquired first.",
            ),),
            capabilities={"supports_reddit": True},
        )
        self._search_acquire(
            url, completeness=ContentCompleteness.PARTIAL,
            text="A worse partial snippet acquired second.", provider="search-provider",
        )
        row = self.repository.connection.execute(
            "SELECT raw_text FROM source_items"
        ).fetchone()
        self.assertEqual(row["raw_text"], "The richer FULL text acquired first.")
        self.assertEqual(self.repository.stats()["source_items"], 1)
        providers = {
            record["provider"]
            for record in self.repository.connection.execute(
                "SELECT provider FROM acquisition_records"
            ).fetchall()
        }
        self.assertEqual(providers, {"brandwatch", "search-provider"})

    def test_metadata_only_upgrades_to_full_when_no_evidence_recorded_yet(self) -> None:
        url = "https://www.reddit.com/r/Accounting/comments/xy4/thread/"
        ingest_provider_records(
            self.repository, source_id=self.source_id, provider="brandwatch", query="q1",
            records=(_feed_record(url, completeness=ContentCompleteness.METADATA_ONLY),),
            capabilities={"supports_reddit": True},
        )
        self.assertEqual(self.repository.stats()["source_items"], 0)
        ingest_provider_records(
            self.repository, source_id=self.source_id, provider="second-provider", query="q1",
            records=(_feed_record(
                url, completeness=ContentCompleteness.FULL,
                text="Later acquisition supplies the full body.", provider="second-provider",
            ),),
            capabilities={"supports_reddit": True},
        )
        self.assertEqual(self.repository.stats()["source_items"], 1)
        row = self.repository.connection.execute(
            "SELECT raw_text FROM source_items"
        ).fetchone()
        self.assertEqual(row["raw_text"], "Later acquisition supplies the full body.")

    def test_conflicting_full_payloads_are_flagged_and_original_is_retained(self) -> None:
        url = "https://www.reddit.com/r/Accounting/comments/xy5/thread/"
        ingest_provider_records(
            self.repository, source_id=self.source_id, provider="brandwatch", query="q1",
            records=(_feed_record(
                url, completeness=ContentCompleteness.FULL,
                text="Original FULL text from Brandwatch.",
            ),),
            capabilities={"supports_reddit": True},
        )
        ingest_provider_records(
            self.repository, source_id=self.source_id, provider="other-feed", query="q1",
            records=(_feed_record(
                url, completeness=ContentCompleteness.FULL,
                text="A conflicting FULL text from another provider.", provider="other-feed",
            ),),
            capabilities={"supports_reddit": True},
        )
        self.assertEqual(self.repository.stats()["source_items"], 1)
        row = self.repository.connection.execute(
            "SELECT raw_text, metadata_json FROM source_items"
        ).fetchone()
        self.assertEqual(row["raw_text"], "Original FULL text from Brandwatch.")
        self.assertIn('"content_conflicts"', row["metadata_json"])
        self.assertIn("other-feed", row["metadata_json"])

    def test_repeated_same_provider_ingestion_is_idempotent(self) -> None:
        url = "https://www.reddit.com/r/Accounting/comments/xy6/thread/"
        record = _feed_record(
            url, completeness=ContentCompleteness.FULL, text="Stable content, ingested twice.",
        )
        first = ingest_provider_records(
            self.repository, source_id=self.source_id, provider="brandwatch", query="q1",
            records=(record,), capabilities={"supports_reddit": True},
        )
        second = ingest_provider_records(
            self.repository, source_id=self.source_id, provider="brandwatch", query="q1",
            records=(record,), capabilities={"supports_reddit": True},
        )
        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 1)
        self.assertEqual(self.repository.stats()["source_items"], 1)
        row = self.repository.connection.execute(
            "SELECT raw_text FROM source_items"
        ).fetchone()
        self.assertEqual(row["raw_text"], "Stable content, ingested twice.")

    def test_observations_stay_idempotent_and_enrichment_after_evidence_is_rejected(
        self,
    ) -> None:
        url = "https://www.reddit.com/r/Accounting/comments/xy7/thread/"
        ingest_provider_records(
            self.repository, source_id=self.source_id, provider="brandwatch", query="q1",
            records=(_feed_record(
                url, completeness=ContentCompleteness.PARTIAL,
                text="We manually re-key every duplicate invoice line by hand.",
            ),),
            capabilities={"supports_reddit": True},
        )
        item_id = int(
            self.repository.connection.execute("SELECT id FROM source_items").fetchone()["id"]
        )

        class StubExtractor:
            version = "cross-path-test-v1"

            def extract(self, item: SourceItemRecord) -> Sequence[ObservationDraft]:
                phrase = "duplicate invoice"
                start = item.raw_text.index(phrase)
                return (ObservationDraft(
                    problem_type=ProblemType.WORKFLOW_GAP,
                    problem_family=ProblemFamily.MANUAL_DATA_ENTRY,
                    evidence_scope=EvidenceScope.GLOBAL,
                    problem="Repeated duplicate invoice entry",
                    evidence_ranges=(EvidenceRange(start, start + len(phrase)),),
                ),)

        extractor = StubExtractor()
        first_run = run_extraction(self.repository, extractor, source_item_ids=(item_id,))
        self.assertEqual(first_run.created_observations, 1)

        # Re-ingesting identical PARTIAL content from the same provider is a no-op and
        # re-running the same extractor version returns the cached result: no duplicates.
        ingest_provider_records(
            self.repository, source_id=self.source_id, provider="brandwatch", query="q1",
            records=(_feed_record(
                url, completeness=ContentCompleteness.PARTIAL,
                text="We manually re-key every duplicate invoice line by hand.",
            ),),
            capabilities={"supports_reddit": True},
        )
        second_run = run_extraction(self.repository, extractor, source_item_ids=(item_id,))
        self.assertEqual(second_run.pipeline_run_id, first_run.pipeline_run_id)
        observation_count = self.repository.connection.execute(
            "SELECT COUNT(*) AS n FROM problem_observations WHERE source_item_id = ?", (item_id,)
        ).fetchone()["n"]
        self.assertEqual(observation_count, 1)

        # A later FULL acquisition with *different* text must not silently rewrite text
        # that evidence already points into.
        with self.assertRaises(IntegrityError):
            ingest_provider_records(
                self.repository, source_id=self.source_id, provider="other-feed", query="q1",
                records=(_feed_record(
                    url, completeness=ContentCompleteness.FULL,
                    text="A materially different FULL rewrite of the same thread.",
                    provider="other-feed",
                ),),
                capabilities={"supports_reddit": True},
            )
        unchanged = self.repository.connection.execute(
            "SELECT raw_text FROM source_items WHERE id = ?", (item_id,)
        ).fetchone()
        self.assertEqual(
            unchanged["raw_text"], "We manually re-key every duplicate invoice line by hand.",
        )
        observation_count_after = self.repository.connection.execute(
            "SELECT COUNT(*) AS n FROM problem_observations WHERE source_item_id = ?", (item_id,)
        ).fetchone()["n"]
        self.assertEqual(observation_count_after, 1)


def _capabilities() -> ProviderCapabilities:
    return ProviderCapabilities(**CAPABILITIES)


class _StubSearch:
    """Minimal SearchProvider returning one fixed Reddit URL, for cross-path tests."""

    def __init__(self, url: str, name: str) -> None:
        self._url = url
        self.name = name
        self.capabilities = _capabilities()

    def search(self, query: str) -> SearchResponse:
        return SearchResponse(SourceAvailability.RESULTS, (SearchResult(self._url),))


class _StubAcquisition:
    """Minimal AcquisitionProvider returning fixed content, for cross-path tests."""

    def __init__(
        self, url: str, name: str, state: str, completeness: str, text: str,
        metadata: dict[str, Any] | None,
    ) -> None:
        self._url = url
        self.name = name
        self.capabilities = _capabilities()
        self._state = state
        self._completeness = completeness
        self._text = text
        self._metadata = metadata

    def acquire(self, canonical_url: str) -> AcquisitionResponse:
        identity = canonicalize_reddit_url(self._url)
        assert identity is not None
        if canonical_url != identity.canonical_url:
            return AcquisitionResponse(DiscoveryState.ACQUISITION_FAILED, None, error="not found")
        return AcquisitionResponse(
            state=DiscoveryState(self._state),
            completeness=ContentCompleteness(self._completeness),
            text=self._text,
            metadata=self._metadata,
        )
