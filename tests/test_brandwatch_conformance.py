"""Proves the Brandwatch adapter satisfies the generic Reddit provider contract.

Future licensed Reddit providers should implement a harness of this shape and call
`run_conformance_suite` the same way, so the pipeline can trust any conforming
provider without provider-specific research-layer code.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from reddit_provider_conformance import run_conformance_suite

from problem_intelligence.brandwatch import (
    BrandwatchConfig,
    BrandwatchError,
    BrandwatchRedditProvider,
    normalize_brandwatch_reddit_record,
)
from problem_intelligence.reddit_provider import (
    ProviderFailure,
    RedditDataProvider,
    RedditProviderRecord,
)


def _mention(record_id: int, *, subreddit: str, url: str | None = None) -> dict[str, Any]:
    return {
        "resourceId": record_id,
        "queryId": 10,
        "url": url or f"https://www.reddit.com/r/{subreddit}/comments/ab{record_id}/test/",
        "title": f"Synthetic title {record_id}",
        "snippet": "Short preview only...",
        "author": "mock_author",
        "date": "2026-09-18T12:00:00.000+0000",
        "language": "en",
    }


class BrandwatchConformanceHarness:
    provider_name = "brandwatch"

    def build_mention(self, record_id: int, *, subreddit: str) -> Any:
        return _mention(record_id, subreddit=subreddit)

    def with_fulltext(self, mention: Any, text: str) -> Any:
        return {**mention, "fullText": text}

    def alternate_representation(self, mention: Any) -> Any:
        subreddit = mention["url"].split("/r/")[1].split("/")[0]
        return {
            **mention,
            "url": (
                f"https://old.reddit.com/r/{subreddit}/comments/"
                f"ab{mention['resourceId']}/test/?utm_source=synthetic"
            ),
        }

    def valid_query(self) -> str:
        return "10"

    def normalize(
        self,
        mention: Any,
        fulltext: Any | None,
        *,
        requested_subreddit: str,
        query: str,
        acquired_at: str,
    ) -> RedditProviderRecord:
        return normalize_brandwatch_reddit_record(
            mention, fulltext, requested_subreddit=requested_subreddit,
            query_id=int(query), acquired_at=acquired_at,
        )

    def build_provider(
        self,
        *,
        discover_pages: Sequence[Sequence[Any]],
        fulltext_pages: Sequence[Sequence[Any]] | None = None,
        discover_failure: ProviderFailure | None = None,
        fulltext_failure: ProviderFailure | None = None,
    ) -> RedditDataProvider:
        def transport(path: str, params: dict[str, str]) -> tuple[dict[str, Any], int]:
            page = int(params["page"])
            if path.endswith("/fulltext"):
                if fulltext_failure is not None:
                    raise BrandwatchError(fulltext_failure, "synthetic fulltext failure")
                pages = fulltext_pages if fulltext_pages is not None else discover_pages
                rows = list(pages[page]) if page < len(pages) else []
                return (
                    {"results": [self.with_fulltext(m, "synthetic full text") for m in rows],
                     "resultsTotal": len(rows)},
                    1,
                )
            if discover_failure is not None:
                raise BrandwatchError(discover_failure, "synthetic discover failure")
            rows = list(discover_pages[page]) if page < len(discover_pages) else []
            return {"results": rows, "resultsTotal": len(rows)}, 1

        return BrandwatchRedditProvider(BrandwatchConfig("token", 42), transport=transport)


def test_brandwatch_provider_passes_generic_conformance_suite() -> None:
    run_conformance_suite(BrandwatchConformanceHarness())
