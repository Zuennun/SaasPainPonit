"""Reusable, provider-independent conformance suite for RedditDataProvider adapters.

Any adapter behind the generic Reddit acquisition contract in
`problem_intelligence.reddit_provider` should pass `run_conformance_suite` against a
`ConformanceHarness` implementation. The suite only asserts behavior visible through the
generic contract (`RedditDataProvider`, `RedditProviderRecord`, `ProviderFailure`); each
adapter's own raw mention shape and transport wiring stay hidden inside its harness.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

from problem_intelligence.domain import ContentCompleteness
from problem_intelligence.reddit_provider import (
    ProviderFailure,
    RedditDataProvider,
    RedditProviderRecord,
)
from problem_intelligence.repository import Repository

ACQUIRED_AT = "2026-09-19T10:00:00+00:00"


class ConformanceHarness(Protocol):
    """Implemented once per provider adapter; hides the adapter's raw wire format."""

    provider_name: str

    def build_provider(
        self,
        *,
        discover_pages: Sequence[Sequence[Any]],
        fulltext_pages: Sequence[Sequence[Any]] | None = None,
        discover_failure: ProviderFailure | None = None,
        fulltext_failure: ProviderFailure | None = None,
    ) -> RedditDataProvider:
        """A provider whose discover()/fetch_fulltext() page through *_pages in call
        order (page N of discover_pages/fulltext_pages per requested `page`), or raise
        an error exposing `.failure` as discover_failure/fulltext_failure on any call."""
        ...

    def build_mention(self, record_id: int, *, subreddit: str) -> Any: ...

    def with_fulltext(self, mention: Any, text: str) -> Any: ...

    def alternate_representation(self, mention: Any) -> Any:
        """The same Reddit item as `mention`, expressed through a different URL variant."""
        ...

    def valid_query(self) -> str: ...

    def normalize(
        self,
        mention: Any,
        fulltext: Any | None,
        *,
        requested_subreddit: str,
        query: str,
        acquired_at: str,
    ) -> RedditProviderRecord: ...


def run_conformance_suite(harness: ConformanceHarness) -> None:
    _check_full_partial_metadata_only(harness)
    _check_provenance_preserved(harness)
    _check_canonical_identity_and_duplicates(harness)
    _check_pagination(harness)
    _check_empty_results(harness)
    _check_provider_failure_mapping(harness)
    _check_fulltext_failure_handling(harness)
    _check_idempotent_reingestion(harness)
    _check_cross_provider_dedup_readiness(harness)


def _check_full_partial_metadata_only(harness: ConformanceHarness) -> None:
    subreddit = "Accounting"
    mention = harness.build_mention(1, subreddit=subreddit)
    full_record = harness.normalize(
        mention, harness.with_fulltext(mention, "A full synthetic body."),
        requested_subreddit=subreddit, query=harness.valid_query(), acquired_at=ACQUIRED_AT,
    )
    assert full_record.completeness is ContentCompleteness.FULL
    assert full_record.item is not None and full_record.item.raw_text

    partial_or_metadata = harness.normalize(
        mention, None,
        requested_subreddit=subreddit, query=harness.valid_query(), acquired_at=ACQUIRED_AT,
    )
    assert partial_or_metadata.completeness in (
        ContentCompleteness.PARTIAL, ContentCompleteness.METADATA_ONLY,
    )
    assert partial_or_metadata.completeness is not ContentCompleteness.FULL


def _check_provenance_preserved(harness: ConformanceHarness) -> None:
    subreddit = "Accounting"
    mention = harness.build_mention(2, subreddit=subreddit)
    record = harness.normalize(
        mention, harness.with_fulltext(mention, "Provenance body."),
        requested_subreddit=subreddit, query=harness.valid_query(), acquired_at=ACQUIRED_AT,
    )
    assert record.provider.upper() == harness.provider_name.upper()
    assert record.acquired_at == ACQUIRED_AT
    assert record.item is not None
    assert record.item.metadata.get("original_platform") == "REDDIT"
    assert record.item.metadata.get("acquired_at") == ACQUIRED_AT
    assert record.item.metadata.get("content_completeness") == ContentCompleteness.FULL.value


def _check_canonical_identity_and_duplicates(harness: ConformanceHarness) -> None:
    subreddit = "Accounting"
    mention = harness.build_mention(3, subreddit=subreddit)
    alternate = harness.alternate_representation(mention)
    first = harness.normalize(
        mention, harness.with_fulltext(mention, "Same item, one URL shape."),
        requested_subreddit=subreddit, query=harness.valid_query(), acquired_at=ACQUIRED_AT,
    )
    second = harness.normalize(
        alternate, harness.with_fulltext(alternate, "Same item, another URL shape."),
        requested_subreddit=subreddit, query=harness.valid_query(), acquired_at=ACQUIRED_AT,
    )
    assert first.item is not None and second.item is not None
    assert first.item.external_id == second.item.external_id
    assert first.canonical_url == second.canonical_url


def _check_pagination(harness: ConformanceHarness) -> None:
    subreddit = "Accounting"
    page0 = [
        harness.build_mention(10, subreddit=subreddit),
        harness.build_mention(11, subreddit=subreddit),
    ]
    page1 = [harness.build_mention(12, subreddit=subreddit)]
    provider = harness.build_provider(discover_pages=[page0, page1])
    first = provider.discover(harness.valid_query(), "2026-09-01", "2026-09-19", 2, 0)
    second = provider.discover(harness.valid_query(), "2026-09-01", "2026-09-19", 2, 1)
    assert len(first.records) == 2 and first.page == 0
    assert len(second.records) == 1 and second.page == 1


def _check_empty_results(harness: ConformanceHarness) -> None:
    provider = harness.build_provider(discover_pages=[[]])
    page = provider.discover(harness.valid_query(), "2026-09-01", "2026-09-19", 5, 0)
    assert page.records == ()


def _check_provider_failure_mapping(harness: ConformanceHarness) -> None:
    for failure in (
        ProviderFailure.AUTH_FAILURE, ProviderFailure.RATE_LIMITED,
        ProviderFailure.PROVIDER_UNAVAILABLE, ProviderFailure.QUERY_CONFIGURATION_ERROR,
    ):
        provider = harness.build_provider(discover_pages=[], discover_failure=failure)
        try:
            provider.discover(harness.valid_query(), "2026-09-01", "2026-09-19", 5, 0)
        except Exception as exc:  # noqa: BLE001 - deliberately duck-typed across adapters
            assert getattr(exc, "failure", None) is failure
        else:
            raise AssertionError(f"expected {failure} to raise")


def _check_fulltext_failure_handling(harness: ConformanceHarness) -> None:
    subreddit = "Accounting"
    mention = harness.build_mention(20, subreddit=subreddit)
    provider = harness.build_provider(
        discover_pages=[[mention]], fulltext_failure=ProviderFailure.FULLTEXT_UNAVAILABLE,
    )
    discovery = provider.discover(harness.valid_query(), "2026-09-01", "2026-09-19", 5, 0)
    assert len(discovery.records) == 1
    try:
        provider.fetch_fulltext(harness.valid_query(), "2026-09-01", "2026-09-19", 5, 0)
    except Exception as exc:  # noqa: BLE001
        assert getattr(exc, "failure", None) is ProviderFailure.FULLTEXT_UNAVAILABLE
    else:
        raise AssertionError("expected fetch_fulltext failure to raise")


def _check_idempotent_reingestion(harness: ConformanceHarness) -> None:
    subreddit = "Accounting"
    mention = harness.build_mention(30, subreddit=subreddit)
    record = harness.normalize(
        mention, harness.with_fulltext(mention, "Idempotent ingestion body."),
        requested_subreddit=subreddit, query=harness.valid_query(), acquired_at=ACQUIRED_AT,
    )
    assert record.item is not None
    item = record.item
    repository = Repository()
    repository.initialize()
    try:
        source_id = repository.upsert_source(
            source_type="reddit", name=f"r/{subreddit}",
            access_method="licensed-provider", commercial_use_status="REVIEW_REQUIRED",
        )
        first_id = repository.upsert_source_item(
            source_id=source_id, external_id=item.external_id, raw_text=item.raw_text,
            url=item.url, title=item.title, metadata=item.metadata,
        )
        second_id = repository.upsert_source_item(
            source_id=source_id, external_id=item.external_id, raw_text=item.raw_text,
            url=item.url, title=item.title, metadata=item.metadata,
        )
        assert first_id == second_id
    finally:
        repository.close()


def _check_cross_provider_dedup_readiness(harness: ConformanceHarness) -> None:
    subreddit = "Accounting"
    mention = harness.build_mention(40, subreddit=subreddit)
    record = harness.normalize(
        mention, harness.with_fulltext(mention, "Cross-provider dedup body."),
        requested_subreddit=subreddit, query=harness.valid_query(), acquired_at=ACQUIRED_AT,
    )
    assert record.item is not None
    external_id = record.item.external_id
    assert external_id.startswith("reddit:submission:") or external_id.startswith("reddit:comment:")
