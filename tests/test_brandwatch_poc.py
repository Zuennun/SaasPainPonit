"""Brandwatch adapter tests require no credentials and contain only synthetic text."""

from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request

import pytest

import problem_intelligence.brandwatch as brandwatch_module
from problem_intelligence.brandwatch import (
    BrandwatchConfig,
    BrandwatchError,
    BrandwatchRedditProvider,
    Transport,
    normalize_brandwatch_reddit_record,
)
from problem_intelligence.brandwatch_poc import (
    PocMetrics,
    PocSource,
    load_manifest,
    render_report,
    run_poc,
)
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
from problem_intelligence.reddit import SearchResult, canonicalize_reddit_url
from problem_intelligence.reddit_provider import ProductionReadiness, ProviderFailure
from problem_intelligence.repository import Repository


def mention(
    record_id: int, *, subreddit: str = "Accounting", path: str | None = None
) -> dict[str, Any]:
    url = path or f"https://www.reddit.com/r/{subreddit}/comments/ab{record_id}/test/"
    return {
        "resourceId": record_id,
        "queryId": 10,
        "url": url,
        "title": f"Synthetic title {record_id}",
        "snippet": "Short preview only...",
        "author": "mock_author",
        "date": "2026-09-18T12:00:00.000+0000",
        "language": "en",
    }


def full(mention_record: dict[str, Any]) -> dict[str, Any]:
    return {**mention_record, "fullText": "A synthetic complete body about duplicate entry."}


def test_config_validates_token_and_project_without_leaking_secret() -> None:
    with pytest.raises(ValueError, match="BRANDWATCH_ACCESS_TOKEN"):
        BrandwatchConfig.from_environment({"BRANDWATCH_PROJECT_ID": "1"})
    with pytest.raises(ValueError, match="positive integer"):
        BrandwatchConfig.from_environment({
            "BRANDWATCH_ACCESS_TOKEN": "secret", "BRANDWATCH_PROJECT_ID": "x"
        })
    config = BrandwatchConfig.from_environment({
        "BRANDWATCH_ACCESS_TOKEN": "secret", "BRANDWATCH_PROJECT_ID": "42"
    })
    assert config.project_id == 42


def test_client_uses_documented_paths_filters_and_pages() -> None:
    calls: list[tuple[str, dict[str, str]]] = []

    def transport(path: str, params: dict[str, str]) -> tuple[dict[str, Any], int]:
        calls.append((path, params))
        return {"results": [mention(1)], "resultsTotal": 7}, 12

    provider = BrandwatchRedditProvider(BrandwatchConfig("token", 42), transport=transport)
    page = provider.discover("10", "2026-09-01", "2026-09-19", 4, 2)
    provider.fetch_fulltext("10", "2026-09-01", "2026-09-19", 4, 2)
    assert page.page == 2 and page.total == 7
    assert calls[0] == (
        "/projects/42/data/mentions",
        {"queryId": "10", "startDate": "2026-09-01", "endDate": "2026-09-19",
         "pageSize": "4", "page": "2"},
    )
    assert calls[1][0] == "/projects/42/data/mentions/fulltext"
    assert provider.requests == 2 and provider.fulltext_requests == 1
    assert provider.latency_ms == 24


def test_live_transport_uses_bearer_header_and_maps_http_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[Request] = []

    def succeed(request: Request, timeout: float) -> BytesIO:
        seen.append(request)
        assert timeout == 15.0
        return BytesIO(b'{"results": [], "resultsTotal": 0}')

    monkeypatch.setattr(brandwatch_module, "urlopen", succeed)
    provider = BrandwatchRedditProvider(BrandwatchConfig("secret-token", 42))
    assert provider.discover("10", "2026-09-01", "2026-09-19", 1, 0).records == ()
    assert seen[0].get_header("Authorization") == "Bearer secret-token"
    assert "secret-token" not in seen[0].full_url

    def unauthorized(request: Request, timeout: float) -> BytesIO:
        raise HTTPError(request.full_url, 401, "unauthorized", {}, None)

    monkeypatch.setattr(brandwatch_module, "urlopen", unauthorized)
    with pytest.raises(BrandwatchError) as error:
        provider.discover("10", "2026-09-01", "2026-09-19", 1, 0)
    assert error.value.failure is ProviderFailure.AUTH_FAILURE


def test_normalization_full_partial_metadata_and_provenance() -> None:
    row = mention(1)
    complete = normalize_brandwatch_reddit_record(
        row, full(row), requested_subreddit="r/Accounting", query_id=10,
        acquired_at="2026-09-19T10:00:00+00:00",
    )
    assert complete.completeness is ContentCompleteness.FULL
    assert complete.item is not None
    assert complete.item.external_id == "reddit:submission:ab1"
    assert "duplicate entry" in complete.item.raw_text
    assert complete.item.metadata["provider_record_id"] == "1"
    assert complete.item.metadata["body_complete"] is True
    assert complete.provenance["raw_retention"] == "DO_NOT_PERSIST"
    partial = normalize_brandwatch_reddit_record(
        row, None, requested_subreddit="Accounting", query_id=10,
        acquired_at="2026-09-19T10:00:00+00:00",
    )
    assert partial.completeness is ContentCompleteness.PARTIAL
    assert partial.item is not None and "Short preview" in partial.item.raw_text
    assert "body" in partial.missing_fields
    empty = {**row, "snippet": None}
    metadata = normalize_brandwatch_reddit_record(
        empty, None, requested_subreddit="Accounting", query_id=10,
        acquired_at="2026-09-19T10:00:00+00:00",
    )
    assert metadata.completeness is ContentCompleteness.METADATA_ONLY
    assert metadata.item is None


def test_comments_canonicalization_and_cross_provider_identity() -> None:
    row = mention(
        2, path="https://old.reddit.com/r/Accounting/comments/abc/test/def/?utm_source=mock"
    )
    record = normalize_brandwatch_reddit_record(
        row, full(row), requested_subreddit="Accounting", query_id=10,
        acquired_at="2026-09-19T10:00:00+00:00",
    )
    assert record.item is not None
    assert record.item.external_id == "reddit:comment:abc:def"
    assert record.provenance["parent_thread_id"] == "abc"
    alternate = canonicalize_reddit_url(
        "https://www.reddit.com/r/accounting/comments/ABC/_/DEF/"
    )
    assert alternate is not None and alternate.external_id == record.item.external_id


def test_rejects_wrong_subreddit_even_with_query_match() -> None:
    with pytest.raises(BrandwatchError) as error:
        normalize_brandwatch_reddit_record(
            mention(1, subreddit="HVAC"), None,
            requested_subreddit="Accounting", query_id=10,
            acquired_at="2026-09-19T10:00:00+00:00",
        )
    assert error.value.failure is ProviderFailure.SOURCE_NOT_COVERED


def test_missing_url_remains_countable_metadata_only() -> None:
    record = normalize_brandwatch_reddit_record(
        {**mention(1), "url": None}, {**full(mention(1)), "url": None},
        requested_subreddit="Accounting", query_id=10,
        acquired_at="2026-09-19T10:00:00+00:00",
    )
    assert record.completeness is ContentCompleteness.METADATA_ONLY
    assert record.item is None
    assert "url" in record.missing_fields


def test_fulltext_failure_keeps_partial_discoveries() -> None:
    def transport(path: str, params: dict[str, str]) -> tuple[dict[str, Any], int]:
        if path.endswith("/fulltext"):
            raise BrandwatchError(ProviderFailure.PROVIDER_UNAVAILABLE, "unavailable")
        return {"results": [mention(1)], "resultsTotal": 1}, 5

    provider = BrandwatchRedditProvider(BrandwatchConfig("token", 42), transport=transport)
    metrics, records = run_poc(
        provider, (PocSource("r/Accounting", 10),),
        start_date="2026-09-01", end_date="2026-09-19", limit=10,
    )
    assert len(records) == 1 and metrics.partial == 1
    assert metrics.failures == {"FULLTEXT_UNAVAILABLE": 1}


def test_poc_pagination_dedupe_and_content_metrics() -> None:
    def transport(path: str, params: dict[str, str]) -> tuple[dict[str, Any], int]:
        page = int(params["page"])
        rows = (
            [mention(1), mention(2), mention(2), mention(3)] if page == 0
            else [mention(4)] if page == 1 else []
        )
        if path.endswith("/fulltext"):
            rows = [full(row) for row in rows]
        return {"results": rows, "resultsTotal": 4}, 5

    provider = BrandwatchRedditProvider(BrandwatchConfig("token", 42), transport=transport)
    metrics, records = run_poc(
        provider, (PocSource("r/Accounting", 10),),
        start_date="2026-09-01", end_date="2026-09-19", limit=10,
        per_source_limit=4,
    )
    assert metrics.mentions_retrieved == 5
    assert metrics.items_normalized == 4
    assert metrics.duplicate_records == 1
    assert metrics.full == 4 and metrics.partial == 0
    assert metrics.fulltext_requests == 2 and len(records) == 4
    assert "A synthetic complete body" not in render_report(metrics)
    assert metrics.readiness == "CONTRACT_REVIEW_REQUIRED"


def test_provider_failure_mapping_and_readiness() -> None:
    provider = BrandwatchRedditProvider(BrandwatchConfig("token", 42))
    assert provider.readiness is ProductionReadiness.CONTRACT_REVIEW_REQUIRED
    def fail_for(
        code: int, expected: ProviderFailure
    ) -> Transport:
        def fail(path: str, params: dict[str, str]) -> tuple[dict[str, Any], int]:
            raise BrandwatchError(expected, f"Brandwatch HTTP {code}")
        return fail

    for code, expected in (
        (401, ProviderFailure.AUTH_FAILURE), (429, ProviderFailure.RATE_LIMITED),
        (500, ProviderFailure.PROVIDER_UNAVAILABLE),
        (400, ProviderFailure.QUERY_CONFIGURATION_ERROR),
    ):
        mocked = BrandwatchRedditProvider(
            BrandwatchConfig("token", 42), transport=fail_for(code, expected)
        )
        with pytest.raises(BrandwatchError) as error:
            mocked.discover("10", "2026-09-01", "2026-09-19", 1, 0)
        assert error.value.failure is expected
        assert mocked.last_failure is not None


def test_manifest_rejects_duplicate_source(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"sources": [
        {"name": "r/Accounting", "query_id": 1},
        {"name": "r/accounting", "query_id": 2},
    ]}), encoding="utf-8")
    with pytest.raises(ValueError, match="distinct"):
        load_manifest(path)


def test_missing_credentials_report_contains_no_raw_text() -> None:
    metrics = PocMetrics(status="CREDENTIALS_REQUIRED")
    report = render_report(metrics)
    assert "CREDENTIALS_REQUIRED" in report
    assert "CONTRACT_REVIEW_REQUIRED" in report
    assert "SESSION_ONLY" not in report or "session-only" in report


def test_normalized_item_enters_existing_evidence_pipeline_and_cross_provider_dedup() -> None:
    row = mention(99)
    normalized = normalize_brandwatch_reddit_record(
        row, full(row), requested_subreddit="Accounting", query_id=10,
        acquired_at="2026-09-19T10:00:00+00:00",
    )
    assert normalized.item is not None
    item = normalized.item
    repository = Repository()
    repository.initialize()
    try:
        source_id = repository.upsert_source(
            source_type="reddit", name="r/Accounting",
            access_method="licensed-provider", commercial_use_status="REVIEW_REQUIRED",
        )
        source_item_id = repository.upsert_source_item(
            source_id=source_id, external_id=item.external_id,
            raw_text=item.raw_text, url=item.url, title=item.title,
            metadata=item.metadata,
        )
        same_id = repository.upsert_source_item(
            source_id=source_id, external_id=item.external_id,
            raw_text=item.raw_text,
            url="https://www.reddit.com/r/accounting/comments/AB99/",
            title=item.title,
        )
        assert source_item_id == same_id
        for provider in ("brandwatch", "another_licensed_provider"):
            run_id = repository.record_discovery_response(
                source_id=source_id, provider=provider, query="test",
                availability=SourceAvailability.RESULTS,
                results=(SearchResult(item.url or ""),), capabilities={},
                latency_ms=1, cost_usd=None, error=None,
            )
            discovery = repository.connection.execute(
                "SELECT id FROM discovery_records WHERE run_id = ?", (run_id,)
            ).fetchone()
            assert discovery is not None
            repository.record_acquisition(
                discovery_id=int(discovery["id"]), source_item_id=source_item_id,
                provider=provider, state=DiscoveryState.CONTENT_COMPLETE,
                completeness=ContentCompleteness.FULL, latency_ms=1,
                cost_usd=None, error=None,
                metadata={"provider_record_id": provider},
            )

        class SyntheticExtractor:
            version = "synthetic-brandwatch-test"

            def extract(self, source_item: SourceItemRecord) -> tuple[ObservationDraft, ...]:
                phrase = "duplicate entry"
                start = source_item.raw_text.index(phrase)
                return (ObservationDraft(
                    problem_type=ProblemType.WORKFLOW_GAP,
                    problem_family=ProblemFamily.MANUAL_DATA_ENTRY,
                    evidence_scope=EvidenceScope.GLOBAL,
                    problem="Repeated duplicate data entry",
                    evidence_ranges=(EvidenceRange(start, start + len(phrase)),),
                ),)

        result = run_extraction(
            repository, SyntheticExtractor(), source_item_ids=(source_item_id,)
        )
        assert result.processed_items == 1 and result.created_observations == 1
        linked = repository.connection.execute(
            """SELECT es.excerpt, si.url, COUNT(DISTINCT ar.provider) AS providers
               FROM evidence_spans es
               JOIN source_items si ON si.id = es.source_item_id
               JOIN acquisition_records ar ON ar.source_item_id = si.id
               GROUP BY es.id"""
        ).fetchone()
        assert linked is not None
        assert linked["excerpt"] == "duplicate entry"
        assert "reddit.com" in linked["url"]
        assert linked["providers"] == 2
    finally:
        repository.close()
