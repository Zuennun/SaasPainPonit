"""Brandwatch Consumer Research adapter for a small, rights-gated Reddit PoC.

Only documented Consumer Research endpoints are used. Query IDs refer to Reddit-only,
subreddit-scoped searches configured and verified in Brandwatch by an operator.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .connectors import SourceItemInput
from .domain import ContentCompleteness
from .reddit import canonicalize_reddit_url
from .reddit_provider import (
    ProductionReadiness,
    ProviderFailure,
    ProviderPage,
    RawRetentionPolicy,
    RedditProviderCapabilities,
    RedditProviderRecord,
)

BRANDWATCH_BASE_URL = "https://api.brandwatch.com"


class BrandwatchError(RuntimeError):
    def __init__(self, failure: ProviderFailure, message: str) -> None:
        super().__init__(message)
        self.failure = failure


@dataclass(frozen=True, slots=True)
class BrandwatchConfig:
    access_token: str
    project_id: int
    timeout_seconds: float = 15.0

    @classmethod
    def from_environment(cls, env: Mapping[str, str] | None = None) -> BrandwatchConfig:
        values = os.environ if env is None else env
        token = values.get("BRANDWATCH_ACCESS_TOKEN", "").strip()
        project = values.get("BRANDWATCH_PROJECT_ID", "").strip()
        if not token:
            raise ValueError("BRANDWATCH_ACCESS_TOKEN is required")
        if not project.isdecimal() or int(project) <= 0:
            raise ValueError("BRANDWATCH_PROJECT_ID must be a positive integer")
        return cls(token, int(project))

    def __post_init__(self) -> None:
        if not self.access_token.strip() or self.project_id <= 0:
            raise ValueError("Brandwatch token and positive project ID are required")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")


Transport = Callable[[str, dict[str, str]], tuple[dict[str, Any], int]]


class BrandwatchRedditProvider:
    name = "brandwatch"
    readiness = ProductionReadiness.CONTRACT_REVIEW_REQUIRED
    capabilities = RedditProviderCapabilities(
        supports_reddit=True,
        supports_subreddit_filter=True,
        supports_date_filter=True,
        supports_pagination=True,
        supports_fulltext=True,
        supports_comments=None,  # documented in UI; API shape must be verified live
        supports_historical_data=True,
        supports_incremental_fetch=True,
    )

    def __init__(
        self, config: BrandwatchConfig, *, transport: Transport | None = None
    ) -> None:
        self.config = config
        self._transport = transport or self._request
        self.requests = 0
        self.successful_requests = 0
        self.fulltext_requests = 0
        self.last_success: str | None = None
        self.last_failure: str | None = None
        self.latency_ms = 0

    def healthcheck(self) -> bool:
        self._call("/projects/summary", {})
        return True

    def discover(
        self, query_id: int, start_date: str, end_date: str, page_size: int, page: int
    ) -> ProviderPage:
        return self._mentions(query_id, start_date, end_date, page_size, page, fulltext=False)

    def fetch_fulltext(
        self, query_id: int, start_date: str, end_date: str, page_size: int, page: int
    ) -> ProviderPage:
        return self._mentions(query_id, start_date, end_date, page_size, page, fulltext=True)

    def _mentions(
        self, query_id: int, start_date: str, end_date: str, page_size: int,
        page: int, *, fulltext: bool,
    ) -> ProviderPage:
        if query_id <= 0 or page < 0 or not 1 <= page_size <= 5000:
            raise ValueError("invalid Brandwatch query ID, page, or pageSize")
        if not start_date or not end_date:
            raise ValueError("Brandwatch startDate and endDate are required")
        suffix = "/fulltext" if fulltext else ""
        path = f"/projects/{self.config.project_id}/data/mentions{suffix}"
        params = {
            "queryId": str(query_id),
            "startDate": start_date,
            "endDate": end_date,
            "pageSize": str(page_size),
            "page": str(page),
        }
        payload, latency = self._call(path, params)
        if fulltext:
            self.fulltext_requests += 1
        raw_records: object = payload.get("results")
        if not isinstance(raw_records, list):
            raise BrandwatchError(ProviderFailure.UNKNOWN_ERROR, "missing results array")
        records: list[dict[str, Any]] = []
        for raw in cast(list[object], raw_records):
            if not isinstance(raw, dict):
                raise BrandwatchError(ProviderFailure.UNKNOWN_ERROR, "non-object mention")
            records.append(cast(dict[str, Any], raw))
        total = payload.get("resultsTotal")
        return ProviderPage(
            tuple(records), int(total) if isinstance(total, int) else None, page, latency
        )

    def _call(self, path: str, params: dict[str, str]) -> tuple[dict[str, Any], int]:
        self.requests += 1
        try:
            payload, latency = self._transport(path, params)
        except BrandwatchError:
            self.last_failure = datetime.now(UTC).isoformat()
            raise
        self.last_success = datetime.now(UTC).isoformat()
        self.successful_requests += 1
        self.latency_ms += latency
        return payload, latency

    def _request(self, path: str, params: dict[str, str]) -> tuple[dict[str, Any], int]:
        url = BRANDWATCH_BASE_URL + path
        if params:
            url += "?" + urlencode(params)
        request = Request(
            url,
            headers={"Authorization": f"Bearer {self.config.access_token}",
                     "Accept": "application/json"},
        )
        started = time.monotonic()
        try:
            with urlopen(request, timeout=self.config.timeout_seconds) as response:
                data: object = json.load(response)
        except HTTPError as exc:
            if exc.code in {401, 403}:
                failure = ProviderFailure.AUTH_FAILURE
            elif exc.code == 429:
                failure = ProviderFailure.RATE_LIMITED
            elif exc.code in {400, 404, 422}:
                failure = ProviderFailure.QUERY_CONFIGURATION_ERROR
            elif exc.code >= 500:
                failure = ProviderFailure.PROVIDER_UNAVAILABLE
            else:
                failure = ProviderFailure.UNKNOWN_ERROR
            raise BrandwatchError(failure, f"Brandwatch HTTP {exc.code}") from exc
        except (URLError, TimeoutError) as exc:
            raise BrandwatchError(
                ProviderFailure.PROVIDER_UNAVAILABLE, "Brandwatch request unavailable"
            ) from exc
        except (ValueError, UnicodeError) as exc:
            raise BrandwatchError(
                ProviderFailure.UNKNOWN_ERROR, "invalid Brandwatch JSON response"
            ) from exc
        if not isinstance(data, dict):
            raise BrandwatchError(ProviderFailure.UNKNOWN_ERROR, "non-object API response")
        return cast(dict[str, Any], data), round((time.monotonic() - started) * 1000)


def normalize_brandwatch_reddit_record(
    mention: Mapping[str, Any],
    fulltext: Mapping[str, Any] | None,
    *,
    requested_subreddit: str,
    query_id: int,
    acquired_at: str,
    raw_retention: RawRetentionPolicy = RawRetentionPolicy.DO_NOT_PERSIST,
) -> RedditProviderRecord:
    """Never infer completeness from a snippet or trust a query's subreddit filter alone."""

    source = "r/" + requested_subreddit.removeprefix("r/")
    raw_url = _string(mention.get("url")) or _string(
        fulltext.get("url") if fulltext else None
    )
    identity = canonicalize_reddit_url(raw_url) if raw_url else None
    if raw_url and (identity is None or identity.subreddit is None or (
        identity.subreddit.casefold() != source.removeprefix("r/").casefold()
    )):
        raise BrandwatchError(
            ProviderFailure.SOURCE_NOT_COVERED,
            f"mention URL does not identify requested {source}",
        )
    provider_record_id = _string(mention.get("resourceId"))
    title = _string((fulltext or mention).get("title")) or _string(mention.get("title"))
    body = _string(fulltext.get("fullText")) if fulltext is not None else None
    snippet = _string(mention.get("snippet"))
    published = _string(mention.get("date"))
    missing = tuple(
        name for name, value in (
            ("title", title), ("body", body),
            ("subreddit", identity.subreddit if identity else None),
            ("url", raw_url), ("timestamp", published),
        ) if not value
    )
    if body and identity is not None:
        completeness = ContentCompleteness.FULL
        text = "\n\n".join(part for part in (title, body) if part)
    elif snippet and identity is not None:
        completeness = ContentCompleteness.PARTIAL
        text = "\n\n".join(part for part in (title, snippet) if part)
    else:
        completeness = ContentCompleteness.METADATA_ONLY
        text = ""
    provenance: dict[str, Any] = {
        "original_platform": "REDDIT",
        "provider": "BRANDWATCH",
        "provider_record_id": provider_record_id,
        "provider_query_id": str(query_id),
        "canonical_source_url": identity.canonical_url if identity else None,
        "acquired_at": acquired_at,
        "content_completeness": completeness.value,
        "reddit_submission_id": identity.submission_id if identity else None,
        "reddit_comment_id": identity.comment_id if identity else None,
        "parent_thread_id": identity.submission_id if identity and identity.comment_id else None,
        "body_complete": completeness is ContentCompleteness.FULL,
        "retrieved_at": acquired_at,
        "raw_retention": raw_retention.value,
    }
    item = (
        SourceItemInput(
            external_id=identity.external_id,
            raw_text=text,
            url=identity.canonical_url,
            title=title,
            author_external_id=_string(mention.get("author")),
            published_at=published,
            language_code=_string(mention.get("language")),
            metadata=provenance,
        ) if text and identity else None
    )
    return RedditProviderRecord(
        source, item, completeness, identity.canonical_url if identity else None, "BRANDWATCH",
        provider_record_id, str(query_id), published, acquired_at, missing, provenance,
    )


def _string(value: object) -> str | None:
    if isinstance(value, (str, int)) and not isinstance(value, bool):
        text = str(value).strip()
        return text or None
    return None
