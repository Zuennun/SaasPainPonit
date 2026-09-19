"""Reddit RSS provider: fixture-based, no live network access required.

Live connectivity was verified manually once during development (see
reddit_rss.py's module docstring and exports/reddit_rss_poc.md); these automated
tests replay a real captured feed plus synthetic edge cases through a mock
transport. No test here makes a real HTTP request.
"""

from __future__ import annotations

import unittest
from collections.abc import Mapping
from pathlib import Path

from problem_intelligence.domain import ContentCompleteness
from problem_intelligence.reddit import canonicalize_reddit_url, ingest_provider_records
from problem_intelligence.reddit_provider import ProviderFailure
from problem_intelligence.reddit_rss import (
    RedditRssConfig,
    RedditRssError,
    RedditRssHealthProvider,
    RedditRssProvider,
    RssHttpResponse,
    compute_backoff_seconds,
    normalize_rss_entry,
    parse_atom_entries,
)
from problem_intelligence.repository import Repository
from problem_intelligence.source_health import AccessResult, HealthStatus, classify_health

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "reddit_rss"
REAL_FEED = (FIXTURE_DIR / "accounting_sample_2026-09-19.xml").read_bytes()

EMPTY_FEED = (
    b'<?xml version="1.0" encoding="UTF-8"?>'
    b'<feed xmlns="http://www.w3.org/2005/Atom"><title>Empty</title></feed>'
)

ONE_SELF_TEXT_ENTRY = (
    b'<?xml version="1.0" encoding="UTF-8"?>'
    b'<feed xmlns="http://www.w3.org/2005/Atom">'
    b'<entry><author><name>/u/tester</name></author>'
    b'<content type="html">&lt;!-- SC_OFF --&gt;&lt;div class=&quot;md&quot;&gt;'
    b'&lt;p&gt;We manually reconcile duplicate invoices every week.&lt;/p&gt;'
    b'&lt;/div&gt;&lt;!-- SC_ON --&gt; submitted by &lt;a&gt;/u/tester&lt;/a&gt;'
    b'</content>'
    b'<id>t3_abc123</id>'
    b'<link href="https://www.reddit.com/r/Accounting/comments/abc123/manual_invoices/" />'
    b'<published>2026-09-19T10:00:00+00:00</published>'
    b'<title>Manual invoice reconciliation</title></entry></feed>'
)

ONE_LINK_POST_ENTRY = (
    b'<?xml version="1.0" encoding="UTF-8"?>'
    b'<feed xmlns="http://www.w3.org/2005/Atom">'
    b'<entry><author><name>/u/tester2</name></author>'
    b'<content type="html">'
    b'&amp;#32;submitted by&amp;#32;&lt;a&gt;/u/tester2&lt;/a&gt;'
    b'&lt;span&gt;&lt;a&gt;[link]&lt;/a&gt;&lt;/span&gt;'
    b'&lt;span&gt;&lt;a&gt;[comments]&lt;/a&gt;&lt;/span&gt;'
    b'</content>'
    b'<id>t3_def456</id>'
    b'<link href="https://www.reddit.com/r/Accounting/comments/def456/a_link_post/" />'
    b'<published>2026-09-19T11:00:00+00:00</published>'
    b'<title>Check out this article</title></entry></feed>'
)

MALFORMED_XML = b"<feed><entry><title>unclosed"


class _StubTransport:
    """Queued (or default-repeated) canned responses, for one path at a time."""

    def __init__(self, responses: list[RssHttpResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, dict[str, str]]] = []

    def __call__(self, path: str, headers: Mapping[str, str]) -> RssHttpResponse:
        self.calls.append((path, dict(headers)))
        if len(self._responses) > 1:
            return self._responses.pop(0)
        return self._responses[0]


def _config(**overrides: object) -> RedditRssConfig:
    defaults: dict[str, object] = {
        "user_agent": "test-agent/0.1 (contact: test)",
        "min_request_interval_seconds": 0.0,
    }
    defaults.update(overrides)
    return RedditRssConfig(**defaults)  # type: ignore[arg-type]


class AtomParsingTests(unittest.TestCase):
    def test_parses_real_captured_feed(self) -> None:
        entries = parse_atom_entries(REAL_FEED)
        self.assertEqual(len(entries), 25)
        first = entries[0]
        self.assertEqual(first.entry_id, "t3_1tx1k5k")
        self.assertTrue(first.link and "1tx1k5k" in first.link)
        self.assertTrue(first.title)
        self.assertTrue(first.author)
        self.assertTrue(first.published_at)
        self.assertTrue(first.body and len(first.body) > 100)
        self.assertNotIn("SC_OFF", first.body or "")
        self.assertNotIn("<", first.body or "")

    def test_link_post_has_no_body_in_real_feed(self) -> None:
        entries = parse_atom_entries(REAL_FEED)
        link_post = next(e for e in entries if e.entry_id == "t3_1wjzxxe" or (
            e.title and e.title.startswith("Hey whether you like being an accountant")
        ))
        self.assertIsNone(link_post.body)

    def test_parses_self_text_entry(self) -> None:
        entries = parse_atom_entries(ONE_SELF_TEXT_ENTRY)
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry.author, "tester")
        self.assertEqual(entry.body, "We manually reconcile duplicate invoices every week.")

    def test_parses_link_post_entry_with_no_body(self) -> None:
        entries = parse_atom_entries(ONE_LINK_POST_ENTRY)
        self.assertEqual(len(entries), 1)
        self.assertIsNone(entries[0].body)

    def test_empty_feed_returns_no_entries(self) -> None:
        self.assertEqual(parse_atom_entries(EMPTY_FEED), ())

    def test_malformed_xml_raises_invalid_feed(self) -> None:
        with self.assertRaises(RedditRssError) as ctx:
            parse_atom_entries(MALFORMED_XML)
        self.assertIs(ctx.exception.failure, ProviderFailure.INVALID_FEED)


class NormalizationTests(unittest.TestCase):
    def test_self_text_entry_is_full(self) -> None:
        entry = parse_atom_entries(ONE_SELF_TEXT_ENTRY)[0]
        record = normalize_rss_entry(
            entry, requested_subreddit="Accounting", acquired_at="2026-09-19T12:00:00+00:00",
        )
        self.assertIs(record.completeness, ContentCompleteness.FULL)
        assert record.item is not None
        self.assertEqual(record.item.external_id, "reddit:submission:abc123")
        self.assertIn("duplicate invoices", record.item.raw_text)
        self.assertEqual(record.provider, "REDDIT_RSS")
        self.assertTrue(record.provenance["body_complete"])

    def test_link_post_is_metadata_only_never_fabricated(self) -> None:
        entry = parse_atom_entries(ONE_LINK_POST_ENTRY)[0]
        record = normalize_rss_entry(
            entry, requested_subreddit="Accounting", acquired_at="2026-09-19T12:00:00+00:00",
        )
        self.assertIs(record.completeness, ContentCompleteness.METADATA_ONLY)
        self.assertIsNone(record.item)
        self.assertIn("body", record.missing_fields)

    def test_wrong_subreddit_is_rejected(self) -> None:
        entry = parse_atom_entries(ONE_SELF_TEXT_ENTRY)[0]
        with self.assertRaises(RedditRssError) as ctx:
            normalize_rss_entry(
                entry, requested_subreddit="HVAC", acquired_at="2026-09-19T12:00:00+00:00",
            )
        self.assertIs(ctx.exception.failure, ProviderFailure.SOURCE_NOT_COVERED)

    def test_canonical_identity_matches_url_variants(self) -> None:
        entry = parse_atom_entries(ONE_SELF_TEXT_ENTRY)[0]
        record = normalize_rss_entry(
            entry, requested_subreddit="Accounting", acquired_at="2026-09-19T12:00:00+00:00",
        )
        alternate = canonicalize_reddit_url(
            "https://old.reddit.com/r/accounting/comments/ABC123/manual_invoices/?utm=x"
        )
        assert record.item is not None and alternate is not None
        self.assertEqual(record.item.external_id, alternate.external_id)


class BackoffTests(unittest.TestCase):
    def test_backoff_sequence_matches_documented_example(self) -> None:
        self.assertEqual(compute_backoff_seconds(0), 90.0)
        self.assertEqual(compute_backoff_seconds(1), 180.0)
        self.assertEqual(compute_backoff_seconds(2), 360.0)
        self.assertEqual(compute_backoff_seconds(3), 720.0)

    def test_backoff_is_capped(self) -> None:
        self.assertEqual(compute_backoff_seconds(10, maximum=1800.0), 1800.0)

    def test_backoff_rejects_negative_attempt(self) -> None:
        with self.assertRaises(ValueError):
            compute_backoff_seconds(-1)


class ProviderProtocolTests(unittest.TestCase):
    def test_discover_and_fetch_fulltext_share_one_request(self) -> None:
        transport = _StubTransport([
            RssHttpResponse(200, {"ETag": '"v1"'}, ONE_SELF_TEXT_ENTRY),
        ])
        provider = RedditRssProvider(_config(), transport=transport)
        discovery = provider.discover("Accounting", "", "", 25, 0)
        fulltext = provider.fetch_fulltext("Accounting", "", "", 25, 0)
        self.assertEqual(len(discovery.records), 1)
        self.assertEqual(discovery.records, fulltext.records)
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(provider.requests, 1)

    def test_page_beyond_zero_returns_empty_no_request(self) -> None:
        transport = _StubTransport([RssHttpResponse(200, {}, EMPTY_FEED)])
        provider = RedditRssProvider(_config(), transport=transport)
        page = provider.discover("Accounting", "", "", 25, 1)
        self.assertEqual(page.records, ())
        self.assertEqual(transport.calls, [])

    def test_empty_feed_is_a_successful_zero_result_page(self) -> None:
        transport = _StubTransport([RssHttpResponse(200, {}, EMPTY_FEED)])
        provider = RedditRssProvider(_config(), transport=transport)
        page = provider.discover("Accounting", "", "", 25, 0)
        self.assertEqual(page.records, ())
        self.assertEqual(provider.successful_requests, 1)

    def test_etag_and_last_modified_are_sent_on_next_request(self) -> None:
        transport = _StubTransport([
            RssHttpResponse(200, {"ETag": '"v1"', "Last-Modified": "Sat, 19 Sep 2026 10:00:00 GMT"},
                             ONE_SELF_TEXT_ENTRY),
            RssHttpResponse(304, {}, b""),
        ])
        provider = RedditRssProvider(_config(), transport=transport)
        provider.discover("Accounting", "", "", 25, 0)
        provider.discover("Accounting", "", "", 25, 0)  # discover() always re-fetches
        second_call_headers = transport.calls[1][1]
        self.assertEqual(second_call_headers.get("If-None-Match"), '"v1"')
        self.assertEqual(
            second_call_headers.get("If-Modified-Since"), "Sat, 19 Sep 2026 10:00:00 GMT"
        )

    def test_304_is_a_successful_poll_with_cached_content_not_a_failure(self) -> None:
        transport = _StubTransport([
            RssHttpResponse(200, {"ETag": '"v1"'}, ONE_SELF_TEXT_ENTRY),
            RssHttpResponse(304, {}, b""),
        ])
        provider = RedditRssProvider(_config(), transport=transport)
        first = provider.discover("Accounting", "", "", 25, 0)
        second = provider.discover("Accounting", "", "", 25, 0)  # always re-fetches
        self.assertEqual(first.records, second.records)
        self.assertEqual(provider.not_modified_responses, 1)
        self.assertEqual(provider.successful_requests, 2)

    def test_429_raises_rate_limited_and_parses_retry_after(self) -> None:
        transport = _StubTransport([RssHttpResponse(429, {"Retry-After": "120"}, b"")])
        provider = RedditRssProvider(_config(), transport=transport)
        with self.assertRaises(RedditRssError) as ctx:
            provider.discover("Accounting", "", "", 25, 0)
        self.assertIs(ctx.exception.failure, ProviderFailure.RATE_LIMITED)
        self.assertEqual(ctx.exception.retry_after_seconds, 120.0)
        self.assertEqual(provider.rate_limited_responses, 1)

    def test_429_falls_back_to_x_ratelimit_reset_header(self) -> None:
        transport = _StubTransport([RssHttpResponse(429, {"x-ratelimit-reset": "46"}, b"")])
        provider = RedditRssProvider(_config(), transport=transport)
        with self.assertRaises(RedditRssError) as ctx:
            provider.discover("Accounting", "", "", 25, 0)
        self.assertEqual(ctx.exception.retry_after_seconds, 46.0)

    def test_header_lookup_is_case_insensitive_like_http2_lowercased_headers(self) -> None:
        transport = _StubTransport([
            RssHttpResponse(200, {"etag": '"lowercase"'}, ONE_SELF_TEXT_ENTRY),
            RssHttpResponse(304, {}, b""),
        ])
        provider = RedditRssProvider(_config(), transport=transport)
        provider.discover("Accounting", "", "", 25, 0)
        provider.discover("Accounting", "", "", 25, 0)
        second_call_headers = transport.calls[1][1]
        self.assertEqual(second_call_headers.get("If-None-Match"), '"lowercase"')

    def test_403_raises_access_restricted(self) -> None:
        transport = _StubTransport([RssHttpResponse(403, {}, b"")])
        provider = RedditRssProvider(_config(), transport=transport)
        with self.assertRaises(RedditRssError) as ctx:
            provider.discover("Accounting", "", "", 25, 0)
        self.assertIs(ctx.exception.failure, ProviderFailure.ACCESS_RESTRICTED)

    def test_404_raises_source_not_covered(self) -> None:
        transport = _StubTransport([RssHttpResponse(404, {}, b"")])
        provider = RedditRssProvider(_config(), transport=transport)
        with self.assertRaises(RedditRssError) as ctx:
            provider.discover("Accounting", "", "", 25, 0)
        self.assertIs(ctx.exception.failure, ProviderFailure.SOURCE_NOT_COVERED)

    def test_server_error_raises_provider_unavailable(self) -> None:
        transport = _StubTransport([RssHttpResponse(503, {}, b"")])
        provider = RedditRssProvider(_config(), transport=transport)
        with self.assertRaises(RedditRssError) as ctx:
            provider.discover("Accounting", "", "", 25, 0)
        self.assertIs(ctx.exception.failure, ProviderFailure.PROVIDER_UNAVAILABLE)

    def test_healthcheck_polls_configured_reference_subreddit(self) -> None:
        transport = _StubTransport([RssHttpResponse(200, {}, EMPTY_FEED)])
        provider = RedditRssProvider(
            _config(healthcheck_subreddit="announcements"), transport=transport,
        )
        self.assertTrue(provider.healthcheck())
        self.assertEqual(transport.calls[0][0], "/r/announcements/.rss")

    def test_min_interval_sleeps_before_second_real_request(self) -> None:
        sleeps: list[float] = []
        transport = _StubTransport([
            RssHttpResponse(200, {}, EMPTY_FEED), RssHttpResponse(200, {}, EMPTY_FEED),
        ])
        provider = RedditRssProvider(
            _config(min_request_interval_seconds=90.0), transport=transport,
            sleep=sleeps.append,
        )
        provider.discover("Accounting", "", "", 25, 0)
        provider.discover("HVAC", "", "", 25, 0)
        self.assertEqual(len(sleeps), 1)
        self.assertGreater(sleeps[0], 0)
        self.assertLessEqual(sleeps[0], 90.0)


class HealthMappingTests(unittest.TestCase):
    def test_active_content_maps_to_active_status(self) -> None:
        transport = _StubTransport([RssHttpResponse(200, {}, ONE_SELF_TEXT_ENTRY)])
        provider = RedditRssProvider(_config(), transport=transport)
        health = RedditRssHealthProvider(provider)
        capture = health.check("r/Accounting")
        self.assertIs(capture.access_result, AccessResult.PUBLIC_CONTENT)
        decision = classify_health(capture)
        self.assertIs(decision.status, HealthStatus.ACTIVE)

    def test_access_restricted_failure_maps_through(self) -> None:
        transport = _StubTransport([RssHttpResponse(403, {}, b"")])
        provider = RedditRssProvider(_config(), transport=transport)
        health = RedditRssHealthProvider(provider)
        capture = health.check("r/Accounting")
        self.assertIs(capture.access_result, AccessResult.ACCESS_RESTRICTED)
        self.assertIs(classify_health(capture).status, HealthStatus.ACCESS_RESTRICTED)

    def test_source_not_found_maps_through(self) -> None:
        transport = _StubTransport([RssHttpResponse(404, {}, b"")])
        provider = RedditRssProvider(_config(), transport=transport)
        health = RedditRssHealthProvider(provider)
        capture = health.check("r/Accounting")
        self.assertIs(capture.access_result, AccessResult.SOURCE_NOT_FOUND)
        self.assertIs(classify_health(capture).status, HealthStatus.SOURCE_UNAVAILABLE)

    def test_provider_failure_does_not_claim_no_results(self) -> None:
        transport = _StubTransport([RssHttpResponse(503, {}, b"")])
        provider = RedditRssProvider(_config(), transport=transport)
        health = RedditRssHealthProvider(provider)
        capture = health.check("r/Accounting")
        self.assertIs(capture.access_result, AccessResult.PROVIDER_FAILED)
        # A technical failure is UNKNOWN, never silently treated as inactivity.
        self.assertIs(classify_health(capture).status, HealthStatus.UNKNOWN)


class CanonicalIngestionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = Repository()
        self.repository.initialize()
        self.source_id = self.repository.upsert_source(source_type="reddit", name="r/Accounting")

    def tearDown(self) -> None:
        self.repository.close()

    def test_repeated_polling_is_idempotent_no_duplicate_source_items(self) -> None:
        entry = parse_atom_entries(ONE_SELF_TEXT_ENTRY)[0]
        record = normalize_rss_entry(
            entry, requested_subreddit="Accounting", acquired_at="2026-09-19T12:00:00+00:00",
        )
        for _ in range(20):
            ingest_provider_records(
                self.repository, source_id=self.source_id, provider="reddit_rss",
                query="Accounting", records=(record,), capabilities={"supports_reddit": True},
            )
        self.assertEqual(self.repository.stats()["source_items"], 1)

    def test_duplicate_entries_within_one_poll_do_not_create_two_items(self) -> None:
        entry = parse_atom_entries(ONE_SELF_TEXT_ENTRY)[0]
        record = normalize_rss_entry(
            entry, requested_subreddit="Accounting", acquired_at="2026-09-19T12:00:00+00:00",
        )
        ingest_provider_records(
            self.repository, source_id=self.source_id, provider="reddit_rss",
            query="Accounting", records=(record, record), capabilities={"supports_reddit": True},
        )
        self.assertEqual(self.repository.stats()["source_items"], 1)

    def test_cross_provider_dedup_with_another_provider_for_same_identity(self) -> None:
        entry = parse_atom_entries(ONE_SELF_TEXT_ENTRY)[0]
        rss_record = normalize_rss_entry(
            entry, requested_subreddit="Accounting", acquired_at="2026-09-19T12:00:00+00:00",
        )
        ingest_provider_records(
            self.repository, source_id=self.source_id, provider="reddit_rss",
            query="Accounting", records=(rss_record,), capabilities={"supports_reddit": True},
        )
        outcome = self.repository.ingest_reddit_content(
            source_id=self.source_id, external_id="reddit:submission:abc123",
            provider="other_provider", completeness=ContentCompleteness.PARTIAL,
            raw_text="A shorter snippet of the same post.",
            url="https://www.reddit.com/r/accounting/comments/abc123/",
        )
        self.assertEqual(self.repository.stats()["source_items"], 1)
        # Richer RSS content is never downgraded by a later, less-complete acquisition.
        row = self.repository.connection.execute(
            "SELECT raw_text FROM source_items WHERE id = ?", (outcome.source_item_id,)
        ).fetchone()
        self.assertIn("duplicate invoices", row["raw_text"])

    def test_evidence_safe_enrichment_rejects_conflicting_rewrite_after_evidence(self) -> None:
        from problem_intelligence.domain import EvidenceRange, EvidenceScope, ProblemType
        from problem_intelligence.repository import IntegrityError

        entry = parse_atom_entries(ONE_SELF_TEXT_ENTRY)[0]
        record = normalize_rss_entry(
            entry, requested_subreddit="Accounting", acquired_at="2026-09-19T12:00:00+00:00",
        )
        ids = ingest_provider_records(
            self.repository, source_id=self.source_id, provider="reddit_rss",
            query="Accounting", records=(record,), capabilities={"supports_reddit": True},
        )
        self.assertEqual(len(ids), 1)
        item = self.repository.connection.execute(
            "SELECT id, raw_text FROM source_items"
        ).fetchone()
        phrase = "manually reconcile"
        start = item["raw_text"].index(phrase)
        self.repository.create_observation_with_evidence(
            source_item_id=int(item["id"]), problem_type=ProblemType.WORKFLOW_GAP,
            evidence_scope=EvidenceScope.GLOBAL, problem="Manual invoice reconciliation",
            extraction_version="test-v1",
            evidence_ranges=(EvidenceRange(start, start + len(phrase)),),
        )
        with self.assertRaises(IntegrityError):
            self.repository.upsert_source_item(
                source_id=self.source_id, external_id="reddit:submission:abc123",
                raw_text="A completely different rewritten body.",
                url="https://www.reddit.com/r/accounting/comments/abc123/",
            )
        unchanged = self.repository.connection.execute(
            "SELECT raw_text FROM source_items WHERE id = ?", (item["id"],)
        ).fetchone()
        self.assertEqual(unchanged["raw_text"], item["raw_text"])


class FixtureIsolationTests(unittest.TestCase):
    def test_repository_default_is_in_memory_not_a_real_pilot_database(self) -> None:
        repository = Repository()
        try:
            repository.initialize()
            repository.upsert_source(source_type="reddit", name="r/TestIsolation")
            self.assertEqual(repository.stats()["sources"], 1)
        finally:
            repository.close()
        # A second in-memory repository never sees the first's data: no shared file.
        other = Repository()
        try:
            other.initialize()
            self.assertEqual(other.stats()["sources"], 0)
        finally:
            other.close()


if __name__ == "__main__":
    unittest.main()
