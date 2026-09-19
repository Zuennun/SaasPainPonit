"""Arctic Shift provider: fixture-based, no live network access required.

Live connectivity was verified manually during development (see
arctic_shift.py's module docstring and exports/arctic_shift_reddit_poc.md); these
automated tests replay a real captured response plus synthetic edge cases through a
mock transport. No test here makes a real HTTP request.
"""

from __future__ import annotations

import json
import unittest
from collections.abc import Mapping
from pathlib import Path

from problem_intelligence.arctic_shift import (
    ArcticShiftConfig,
    ArcticShiftError,
    ArcticShiftHealthProvider,
    ArcticShiftHttpResponse,
    ArcticShiftRedditProvider,
    is_removed_or_deleted,
    normalize_arctic_shift_record,
)
from problem_intelligence.domain import ContentCompleteness
from problem_intelligence.reddit import canonicalize_reddit_url, ingest_provider_records
from problem_intelligence.reddit_provider import ProviderFailure
from problem_intelligence.repository import Repository
from problem_intelligence.source_health import AccessResult, HealthStatus, classify_health

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "arctic_shift"
REAL_RESPONSE_BODY = (FIXTURE_DIR / "accounting_sample_2026-09-19.json").read_bytes()

EMPTY_RESPONSE = json.dumps({"data": []}).encode("utf-8")


def _post(
    *, id_: str = "abc123", subreddit: str = "Accounting", title: str = "Manual invoices",
    selftext: str = "We manually reconcile duplicate invoices every week.",
    is_self: bool = True, author: str = "tester", created_utc: float = 1789842297,
    removed_by_category: object = None, url: str | None = None,
) -> dict[str, object]:
    return {
        "id": id_, "name": f"t3_{id_}", "subreddit": subreddit, "title": title,
        "selftext": selftext, "is_self": is_self, "author": author,
        "created_utc": created_utc, "retrieved_on": created_utc + 10,
        "permalink": f"/r/{subreddit}/comments/{id_}/{title.lower().replace(' ', '_')}/",
        "url": url or f"https://www.reddit.com/r/{subreddit}/comments/{id_}/",
        "score": 1, "num_comments": 0, "removed_by_category": removed_by_category,
    }


def _response(records: list[dict[str, object]], *, status: int = 200) -> ArcticShiftHttpResponse:
    return ArcticShiftHttpResponse(status, {}, json.dumps({"data": records}).encode("utf-8"))


class _StubTransport:
    def __init__(self, responses: list[ArcticShiftHttpResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, dict[str, str]]] = []

    def __call__(self, path: str, headers: Mapping[str, str]) -> ArcticShiftHttpResponse:
        self.calls.append((path, dict(headers)))
        if len(self._responses) > 1:
            return self._responses.pop(0)
        return self._responses[0]


def _config(**overrides: object) -> ArcticShiftConfig:
    defaults: dict[str, object] = {
        "user_agent": "test-agent/0.1 (contact: test)",
        "min_request_interval_seconds": 0.0,
    }
    defaults.update(overrides)
    return ArcticShiftConfig(**defaults)  # type: ignore[arg-type]


class ResponseParsingTests(unittest.TestCase):
    def test_parses_real_captured_response(self) -> None:
        payload = json.loads(REAL_RESPONSE_BODY)
        records = payload["data"]
        self.assertEqual(len(records), 10)
        first = records[0]
        self.assertIn("id", first)
        self.assertIn("permalink", first)
        self.assertIn("selftext", first)
        self.assertIn("created_utc", first)
        self.assertIn("is_self", first)
        self.assertIn("removed_by_category", first)

    def test_empty_response_is_zero_records(self) -> None:
        transport = _StubTransport([ArcticShiftHttpResponse(200, {}, EMPTY_RESPONSE)])
        provider = ArcticShiftRedditProvider(_config(), transport=transport)
        page = provider.discover("Accounting", "", "", 25, 0)
        self.assertEqual(page.records, ())

    def test_malformed_json_raises_invalid_feed(self) -> None:
        transport = _StubTransport([ArcticShiftHttpResponse(200, {}, b"not json")])
        provider = ArcticShiftRedditProvider(_config(), transport=transport)
        with self.assertRaises(ArcticShiftError) as ctx:
            provider.discover("Accounting", "", "", 25, 0)
        self.assertIs(ctx.exception.failure, ProviderFailure.INVALID_FEED)

    def test_non_array_data_raises_invalid_feed(self) -> None:
        body = json.dumps({"data": "not-an-array"}).encode("utf-8")
        transport = _StubTransport([ArcticShiftHttpResponse(200, {}, body)])
        provider = ArcticShiftRedditProvider(_config(), transport=transport)
        with self.assertRaises(ArcticShiftError) as ctx:
            provider.discover("Accounting", "", "", 25, 0)
        self.assertIs(ctx.exception.failure, ProviderFailure.INVALID_FEED)


class NormalizationTests(unittest.TestCase):
    def test_self_post_with_text_is_full(self) -> None:
        record = normalize_arctic_shift_record(
            _post(), requested_subreddit="Accounting", acquired_at="2026-09-19T12:00:00+00:00",
        )
        self.assertIs(record.completeness, ContentCompleteness.FULL)
        assert record.item is not None
        self.assertEqual(record.item.external_id, "reddit:submission:abc123")
        self.assertIn("duplicate invoices", record.item.raw_text)
        self.assertEqual(record.provider, "ARCTIC_SHIFT")

    def test_link_post_missing_selftext_is_metadata_only(self) -> None:
        raw = _post(
            id_="link1", is_self=False, selftext="", url="https://i.redd.it/x.jpg",
        )
        record = normalize_arctic_shift_record(
            raw, requested_subreddit="Accounting", acquired_at="2026-09-19T12:00:00+00:00",
        )
        self.assertIs(record.completeness, ContentCompleteness.METADATA_ONLY)
        self.assertIsNone(record.item)
        self.assertIn("body", record.missing_fields)

    def test_url_field_pointing_off_reddit_does_not_break_identity(self) -> None:
        """Regression: for link posts `url` is the external target, not a Reddit
        URL. `permalink` is used instead -- discovered live against real data."""

        raw = _post(id_="link2", is_self=False, selftext="", url="https://i.redd.it/y.jpg")
        record = normalize_arctic_shift_record(
            raw, requested_subreddit="Accounting", acquired_at="2026-09-19T12:00:00+00:00",
        )
        self.assertEqual(record.canonical_url, "https://www.reddit.com/r/accounting/comments/link2/")

    def test_removed_post_is_excluded_not_upgraded(self) -> None:
        raw = _post(id_="rm1", selftext="[removed]", removed_by_category="moderator")
        record = normalize_arctic_shift_record(
            raw, requested_subreddit="Accounting", acquired_at="2026-09-19T12:00:00+00:00",
        )
        self.assertIs(record.completeness, ContentCompleteness.METADATA_ONLY)
        self.assertIsNone(record.item)
        self.assertTrue(record.provenance["removed_or_deleted"])

    def test_deleted_post_marker_is_recognized(self) -> None:
        raw = _post(id_="del1", selftext="[deleted]", removed_by_category=None)
        self.assertTrue(is_removed_or_deleted(raw))

    def test_wrong_subreddit_is_rejected(self) -> None:
        raw = _post(subreddit="HVAC")
        with self.assertRaises(ArcticShiftError) as ctx:
            normalize_arctic_shift_record(
                raw, requested_subreddit="Accounting", acquired_at="2026-09-19T12:00:00+00:00",
            )
        self.assertIs(ctx.exception.failure, ProviderFailure.SOURCE_NOT_COVERED)

    def test_canonical_identity_matches_url_variants(self) -> None:
        record = normalize_arctic_shift_record(
            _post(), requested_subreddit="Accounting", acquired_at="2026-09-19T12:00:00+00:00",
        )
        alternate = canonicalize_reddit_url(
            "https://old.reddit.com/r/accounting/comments/ABC123/manual_invoices/?utm=x"
        )
        assert record.item is not None and alternate is not None
        self.assertEqual(record.item.external_id, alternate.external_id)


class ProviderProtocolTests(unittest.TestCase):
    def test_discover_and_fetch_fulltext_share_one_request(self) -> None:
        transport = _StubTransport([_response([_post()])])
        provider = ArcticShiftRedditProvider(_config(), transport=transport)
        discovery = provider.discover("Accounting", "", "", 25, 0)
        fulltext = provider.fetch_fulltext("Accounting", "", "", 25, 0)
        self.assertEqual(discovery.records, fulltext.records)
        self.assertEqual(len(transport.calls), 1)

    def test_page_beyond_zero_returns_empty_no_request(self) -> None:
        transport = _StubTransport([_response([])])
        provider = ArcticShiftRedditProvider(_config(), transport=transport)
        page = provider.discover("Accounting", "", "", 25, 1)
        self.assertEqual(page.records, ())
        self.assertEqual(transport.calls, [])

    def test_date_filters_are_sent_as_after_before(self) -> None:
        transport = _StubTransport([_response([])])
        provider = ArcticShiftRedditProvider(_config(), transport=transport)
        provider.discover("Accounting", "2026-09-01", "2026-09-02", 10, 0)
        path = transport.calls[0][0]
        self.assertIn("after=2026-09-01", path)
        self.assertIn("before=2026-09-02", path)
        self.assertIn("subreddit=Accounting", path)

    def test_no_date_filters_omits_after_before(self) -> None:
        transport = _StubTransport([_response([])])
        provider = ArcticShiftRedditProvider(_config(), transport=transport)
        provider.discover("Accounting", "", "", 10, 0)
        path = transport.calls[0][0]
        self.assertNotIn("after=", path)
        self.assertNotIn("before=", path)

    def test_pagination_across_date_windows(self) -> None:
        transport = _StubTransport([_response([_post(id_="a")]), _response([_post(id_="b")])])
        provider = ArcticShiftRedditProvider(_config(), transport=transport)
        first = provider.discover("Accounting", "2026-09-01", "2026-09-02", 25, 0)
        second = provider.discover("Accounting", "2026-09-02", "2026-09-03", 25, 0)
        self.assertEqual(len(first.records), 1)
        self.assertEqual(len(second.records), 1)
        self.assertNotEqual(first.records, second.records)

    def test_400_raises_query_configuration_error(self) -> None:
        body = json.dumps({"error": "'subreddit' must be 2-30 characters long"}).encode()
        transport = _StubTransport([ArcticShiftHttpResponse(400, {}, body)])
        provider = ArcticShiftRedditProvider(_config(), transport=transport)
        with self.assertRaises(ArcticShiftError) as ctx:
            provider.discover("X", "", "", 25, 0)
        self.assertIs(ctx.exception.failure, ProviderFailure.QUERY_CONFIGURATION_ERROR)

    def test_429_raises_rate_limited_and_parses_retry_after(self) -> None:
        transport = _StubTransport([ArcticShiftHttpResponse(429, {"Retry-After": "31"}, b"")])
        provider = ArcticShiftRedditProvider(_config(), transport=transport)
        with self.assertRaises(ArcticShiftError) as ctx:
            provider.discover("Accounting", "", "", 25, 0)
        self.assertIs(ctx.exception.failure, ProviderFailure.RATE_LIMITED)
        self.assertEqual(ctx.exception.retry_after_seconds, 31.0)

    def test_server_error_raises_provider_unavailable(self) -> None:
        transport = _StubTransport([ArcticShiftHttpResponse(503, {}, b"")])
        provider = ArcticShiftRedditProvider(_config(), transport=transport)
        with self.assertRaises(ArcticShiftError) as ctx:
            provider.discover("Accounting", "", "", 25, 0)
        self.assertIs(ctx.exception.failure, ProviderFailure.PROVIDER_UNAVAILABLE)

    def test_healthcheck_polls_reference_subreddit(self) -> None:
        transport = _StubTransport([_response([])])
        provider = ArcticShiftRedditProvider(_config(), transport=transport)
        self.assertTrue(provider.healthcheck())
        self.assertIn("subreddit=announcements", transport.calls[0][0])

    def test_min_interval_sleeps_before_second_real_request(self) -> None:
        sleeps: list[float] = []
        transport = _StubTransport([_response([]), _response([])])
        provider = ArcticShiftRedditProvider(
            _config(min_request_interval_seconds=3.0), transport=transport, sleep=sleeps.append,
        )
        provider.discover("Accounting", "", "", 25, 0)
        provider.discover("HVAC", "", "", 25, 0)
        self.assertEqual(len(sleeps), 1)
        self.assertGreater(sleeps[0], 0)
        self.assertLessEqual(sleeps[0], 3.0)


class HealthMappingTests(unittest.TestCase):
    def test_active_content_maps_to_active_status(self) -> None:
        transport = _StubTransport([_response([_post()])])
        provider = ArcticShiftRedditProvider(_config(), transport=transport)
        health = ArcticShiftHealthProvider(provider)
        capture = health.check("r/Accounting")
        self.assertIs(capture.access_result, AccessResult.PUBLIC_CONTENT)
        self.assertIs(classify_health(capture).status, HealthStatus.ACTIVE)

    def test_only_removed_records_do_not_count_as_usable(self) -> None:
        transport = _StubTransport(
            [_response([_post(id_="rm1", selftext="[removed]", removed_by_category="moderator")])]
        )
        provider = ArcticShiftRedditProvider(_config(), transport=transport)
        health = ArcticShiftHealthProvider(provider)
        capture = health.check("r/Accounting")
        self.assertIs(capture.access_result, AccessResult.PUBLIC_NO_RECENT)

    def test_provider_failure_does_not_claim_no_results(self) -> None:
        transport = _StubTransport([ArcticShiftHttpResponse(503, {}, b"")])
        provider = ArcticShiftRedditProvider(_config(), transport=transport)
        health = ArcticShiftHealthProvider(provider)
        capture = health.check("r/Accounting")
        self.assertIs(capture.access_result, AccessResult.PROVIDER_FAILED)
        self.assertIs(classify_health(capture).status, HealthStatus.UNKNOWN)


class CanonicalIngestionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = Repository()
        self.repository.initialize()
        self.source_id = self.repository.upsert_source(source_type="reddit", name="r/Accounting")

    def tearDown(self) -> None:
        self.repository.close()

    def test_repeated_ingestion_is_idempotent(self) -> None:
        record = normalize_arctic_shift_record(
            _post(), requested_subreddit="Accounting", acquired_at="2026-09-19T12:00:00+00:00",
        )
        for _ in range(10):
            ingest_provider_records(
                self.repository, source_id=self.source_id, provider="arctic_shift",
                query="Accounting", records=(record,), capabilities={"supports_reddit": True},
            )
        self.assertEqual(self.repository.stats()["source_items"], 1)

    def test_removed_records_never_create_source_items(self) -> None:
        raw = _post(id_="rm2", selftext="[removed]", removed_by_category="moderator")
        record = normalize_arctic_shift_record(
            raw, requested_subreddit="Accounting", acquired_at="2026-09-19T12:00:00+00:00",
        )
        ingest_provider_records(
            self.repository, source_id=self.source_id, provider="arctic_shift",
            query="Accounting", records=(record,), capabilities={"supports_reddit": True},
        )
        self.assertEqual(self.repository.stats()["source_items"], 0)

    def test_cross_provider_dedup_and_completeness_never_downgraded(self) -> None:
        full_record = normalize_arctic_shift_record(
            _post(id_="xp1"), requested_subreddit="Accounting",
            acquired_at="2026-09-19T12:00:00+00:00",
        )
        ingest_provider_records(
            self.repository, source_id=self.source_id, provider="arctic_shift",
            query="Accounting", records=(full_record,), capabilities={"supports_reddit": True},
        )
        outcome = self.repository.ingest_reddit_content(
            source_id=self.source_id, external_id="reddit:submission:xp1",
            provider="other_provider", completeness=ContentCompleteness.PARTIAL,
            raw_text="A shorter snippet of the same post.",
            url="https://www.reddit.com/r/accounting/comments/xp1/",
        )
        self.assertEqual(self.repository.stats()["source_items"], 1)
        row = self.repository.connection.execute(
            "SELECT raw_text FROM source_items WHERE id = ?", (outcome.source_item_id,)
        ).fetchone()
        self.assertIn("duplicate invoices", row["raw_text"])

    def test_metadata_only_upgrades_to_full_when_richer_provider_arrives(self) -> None:
        link_record = normalize_arctic_shift_record(
            _post(id_="up1", is_self=False, selftext="", url="https://i.redd.it/z.jpg"),
            requested_subreddit="Accounting", acquired_at="2026-09-19T12:00:00+00:00",
        )
        ingest_provider_records(
            self.repository, source_id=self.source_id, provider="arctic_shift",
            query="Accounting", records=(link_record,), capabilities={"supports_reddit": True},
        )
        # METADATA_ONLY with no item creates an acquisition record but no SourceItem.
        self.assertEqual(self.repository.stats()["source_items"], 0)
        outcome = self.repository.ingest_reddit_content(
            source_id=self.source_id, external_id="reddit:submission:up1",
            provider="other_provider", completeness=ContentCompleteness.FULL,
            raw_text="Later, a full-content provider supplies the real body.",
            url="https://www.reddit.com/r/accounting/comments/up1/",
            metadata={"body_complete": True, "retrieved_at": "2026-09-19T12:00:00+00:00"},
        )
        self.assertTrue(outcome.content_updated)
        self.assertEqual(self.repository.stats()["source_items"], 1)


class FixtureIsolationTests(unittest.TestCase):
    def test_repository_default_is_in_memory_not_a_real_pilot_database(self) -> None:
        repository = Repository()
        try:
            repository.initialize()
            repository.upsert_source(source_type="reddit", name="r/TestIsolation")
            self.assertEqual(repository.stats()["sources"], 1)
        finally:
            repository.close()
        other = Repository()
        try:
            other.initialize()
            self.assertEqual(other.stats()["sources"], 0)
        finally:
            other.close()


if __name__ == "__main__":
    unittest.main()
