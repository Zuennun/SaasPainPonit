"""Arctic Shift: independent Reddit archive, zero-cost, robots.txt-permitted.

https://arctic-shift.photon-reddit.com's `robots.txt` is `Disallow:` (empty) for
`User-agent: *` -- automated access is explicitly permitted. Verified live
2026-09-19, unlike direct reddit.com access (see reddit_rss.py, POLICY_BLOCKED).
This provider only ever requests Arctic Shift; it never falls back to reddit.com,
old.reddit.com, or Reddit RSS/JSON for content Arctic Shift lacks.

Only the documented `/api/posts/search` endpoint is used (`subreddit`, `after`,
`before`, `limit`, `sort`). Comments are out of scope for this phase.

Verified live response shape: `{"data": [<post>, ...]}`, each `<post>` the
standard Reddit post JSON object. Confirmed present: `id`, `name` (t3_ fullname),
`subreddit`, `title`, `selftext`, `author`, `created_utc`, `retrieved_on`, `url`,
`score`, `num_comments`, `is_self`, `removed_by_category`. The `fields` query
parameter only accepts a narrower whitelist that excludes `removed_by_category`
and `permalink`, so this module always requests full objects rather than using it.

Link/image posts (`is_self=False`) have empty `selftext` -- METADATA_ONLY, never
upgraded or reconstructed. Removed/deleted posts have `selftext` of `"[removed]"`
(moderator) or `"[deleted]"` (user), often with `removed_by_category` set -- these
are excluded from the default research run (no SourceItem is created for them),
not force-included as if the text were genuinely absent for editorial reasons.

Freshness observed live: archival lag (retrieved_on - created_utc) was ~12 seconds
for the newest available post at verification time -- Arctic Shift is not a
stale or delayed archive for recent content.
"""

from __future__ import annotations

import json
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
from .source_health import AccessResult, HealthCapture

BASE_URL = "https://arctic-shift.photon-reddit.com"
DEFAULT_MIN_REQUEST_INTERVAL_SECONDS = 3.0


class ArcticShiftError(RuntimeError):
    def __init__(
        self, failure: ProviderFailure, message: str, *, retry_after_seconds: float | None = None
    ) -> None:
        super().__init__(message)
        self.failure = failure
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True, slots=True)
class ArcticShiftConfig:
    user_agent: str
    min_request_interval_seconds: float = DEFAULT_MIN_REQUEST_INTERVAL_SECONDS
    timeout_seconds: float = 20.0

    def __post_init__(self) -> None:
        if not self.user_agent.strip():
            raise ValueError("a descriptive User-Agent is required")
        if self.min_request_interval_seconds < 0:
            raise ValueError("min_request_interval_seconds must not be negative")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")


@dataclass(frozen=True, slots=True)
class ArcticShiftHttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


Transport = Callable[[str, Mapping[str, str]], ArcticShiftHttpResponse]

REMOVED_MARKERS = frozenset({"[removed]", "[deleted]"})


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _header(response: ArcticShiftHttpResponse, name: str) -> str | None:
    target = name.casefold()
    for key, value in response.headers.items():
        if key.casefold() == target:
            return value
    return None


def _string(value: object) -> str | None:
    if isinstance(value, (str, int, float)) and not isinstance(value, bool):
        text = str(value).strip()
        return text or None
    return None


def _parse_retry_after(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def is_removed_or_deleted(raw: Mapping[str, Any]) -> bool:
    selftext = raw.get("selftext")
    if isinstance(selftext, str) and selftext in REMOVED_MARKERS:
        return True
    category = raw.get("removed_by_category")
    return category is not None and category is not False


class ArcticShiftRedditProvider:
    name = "arctic_shift"
    readiness = ProductionReadiness.CONTRACT_REVIEW_REQUIRED
    capabilities = RedditProviderCapabilities(
        supports_reddit=True,
        supports_subreddit_filter=True,
        supports_date_filter=True,
        supports_pagination=True,
        supports_fulltext=True,
        supports_comments=False,
        supports_historical_data=True,
        supports_incremental_fetch=True,
    )

    def __init__(
        self,
        config: ArcticShiftConfig,
        *,
        transport: Transport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config
        self._transport = transport or self._request
        self._sleep = sleep
        self.requests = 0
        self.successful_requests = 0
        self.rate_limited_responses = 0
        self.last_success: str | None = None
        self.last_failure: str | None = None
        self.latency_ms = 0
        self._last_request_at: float | None = None
        self._page_cache: dict[tuple[str, str, str, int], ProviderPage] = {}

    def healthcheck(self) -> bool:
        self._fetch("announcements", "", "", 1)
        return True

    def discover(
        self, query: str, start_date: str, end_date: str, page_size: int, page: int
    ) -> ProviderPage:
        if not 1 <= page_size <= 100:
            raise ValueError("page_size must be between 1 and 100")
        if page < 0:
            raise ValueError("page must not be negative")
        if page > 0:
            # Deep pagination is date-window traversal (after/before), which the
            # orchestrator drives across calls, not an opaque page number here.
            return ProviderPage((), 0, page, 0)
        result = self._fetch(query, start_date, end_date, page_size)
        self._page_cache[(query.casefold(), start_date, end_date, page_size)] = result
        return result

    def fetch_fulltext(
        self, query: str, start_date: str, end_date: str, page_size: int, page: int
    ) -> ProviderPage:
        if page > 0:
            return ProviderPage((), 0, page, 0)
        cached = self._page_cache.get((query.casefold(), start_date, end_date, page_size))
        if cached is not None:
            return cached
        # Arctic Shift delivers full post objects (including selftext) in the same
        # response as discovery; fetched again only if called without a prior
        # matching discover().
        return self._fetch(query, start_date, end_date, page_size)

    def _fetch(self, subreddit: str, start_date: str, end_date: str, limit: int) -> ProviderPage:
        self._respect_min_interval()
        params: dict[str, str] = {"subreddit": subreddit, "limit": str(limit)}
        if start_date:
            params["after"] = start_date
        if end_date:
            params["before"] = end_date
        headers = {"User-Agent": self.config.user_agent, "Accept": "application/json"}
        started = time.monotonic()
        self.requests += 1
        response = self._transport(f"/api/posts/search?{urlencode(params)}", headers)
        self._last_request_at = time.monotonic()
        latency = round((time.monotonic() - started) * 1000)
        self.latency_ms += latency
        return self._handle_response(response, latency)

    def _handle_response(
        self, response: ArcticShiftHttpResponse, latency: int
    ) -> ProviderPage:
        if response.status == 429:
            self.rate_limited_responses += 1
            self.last_failure = _now_iso()
            retry_after = _parse_retry_after(
                _header(response, "retry-after") or _header(response, "x-ratelimit-reset")
            )
            raise ArcticShiftError(
                ProviderFailure.RATE_LIMITED, "rate limited (429)",
                retry_after_seconds=retry_after,
            )
        if response.status == 400:
            self.last_failure = _now_iso()
            raise ArcticShiftError(
                ProviderFailure.QUERY_CONFIGURATION_ERROR, self._error_message(response)
            )
        if response.status >= 500:
            self.last_failure = _now_iso()
            raise ArcticShiftError(
                ProviderFailure.PROVIDER_UNAVAILABLE, f"server error ({response.status})"
            )
        if response.status != 200:
            self.last_failure = _now_iso()
            raise ArcticShiftError(
                ProviderFailure.UNKNOWN_ERROR, f"unexpected status ({response.status})"
            )
        try:
            payload: object = json.loads(response.body)
        except ValueError as exc:
            raise ArcticShiftError(ProviderFailure.INVALID_FEED, "malformed JSON body") from exc
        if not isinstance(payload, dict):
            raise ArcticShiftError(ProviderFailure.INVALID_FEED, "response is not an object")
        root = cast(dict[str, object], payload)
        raw_records = root.get("data")
        if not isinstance(raw_records, list):
            raise ArcticShiftError(ProviderFailure.INVALID_FEED, "missing data array")
        records: list[dict[str, Any]] = []
        for raw in cast(list[object], raw_records):
            if not isinstance(raw, dict):
                raise ArcticShiftError(ProviderFailure.INVALID_FEED, "non-object post record")
            records.append(cast(dict[str, Any], raw))
        self.successful_requests += 1
        self.last_success = _now_iso()
        return ProviderPage(tuple(records), len(records), 0, latency)

    def _error_message(self, response: ArcticShiftHttpResponse) -> str:
        try:
            payload: object = json.loads(response.body)
        except ValueError:
            return "invalid request (400)"
        if isinstance(payload, dict):
            error = cast(dict[str, object], payload).get("error")
            if isinstance(error, str):
                return error
        return "invalid request (400)"

    def _respect_min_interval(self) -> None:
        if self._last_request_at is None:
            return
        elapsed = time.monotonic() - self._last_request_at
        remaining = self.config.min_request_interval_seconds - elapsed
        if remaining > 0:
            self._sleep(remaining)

    def _request(self, path: str, headers: Mapping[str, str]) -> ArcticShiftHttpResponse:
        request = Request(BASE_URL + path, headers=dict(headers))
        try:
            with urlopen(request, timeout=self.config.timeout_seconds) as response:
                return ArcticShiftHttpResponse(
                    response.status, dict(response.headers), response.read()
                )
        except HTTPError as exc:
            body = exc.read()
            return ArcticShiftHttpResponse(exc.code, dict(exc.headers), body)
        except (URLError, TimeoutError) as exc:
            raise ArcticShiftError(
                ProviderFailure.PROVIDER_UNAVAILABLE, f"network failure: {exc}"
            ) from exc


def normalize_arctic_shift_record(
    raw: Mapping[str, Any],
    *,
    requested_subreddit: str,
    acquired_at: str,
    raw_retention: RawRetentionPolicy = RawRetentionPolicy.DO_NOT_PERSIST,
) -> RedditProviderRecord:
    """Never reconstructs missing or removed text. A removed/deleted post is
    excluded from the research run (item=None) even though Arctic Shift still
    returns a record for it, so its provenance stays visible without polluting
    extraction with placeholder text like "[removed]"."""

    source = "r/" + requested_subreddit.removeprefix("r/")
    # `url` is the post's link target -- the external URL for link/image posts, not
    # a Reddit URL at all. `permalink` (a reddit.com-relative path) is the reliable
    # Reddit identity field for every post shape; discovered live via a link post
    # whose `url` pointed at i.redd.it.
    permalink = _string(raw.get("permalink"))
    reddit_url = f"https://www.reddit.com{permalink}" if permalink else _string(raw.get("url"))
    identity = canonicalize_reddit_url(reddit_url) if reddit_url else None
    if reddit_url and (identity is None or identity.subreddit is None or (
        identity.subreddit.casefold() != source.removeprefix("r/").casefold()
    )):
        raise ArcticShiftError(
            ProviderFailure.SOURCE_NOT_COVERED,
            f"record URL does not identify requested {source}",
        )
    removed = is_removed_or_deleted(raw)
    is_self = bool(raw.get("is_self"))
    selftext = _string(raw.get("selftext")) if not removed else None
    title = _string(raw.get("title"))
    author = _string(raw.get("author"))
    created_utc = raw.get("created_utc")
    published = (
        datetime.fromtimestamp(float(created_utc), tz=UTC).isoformat()
        if isinstance(created_utc, (int, float)) and not isinstance(created_utc, bool)
        else None
    )
    missing = tuple(
        name for name, value in (
            ("title", title), ("body", selftext),
            ("subreddit", identity.subreddit if identity else None),
            ("url", reddit_url), ("timestamp", published),
        ) if not value
    )
    if removed:
        completeness = ContentCompleteness.METADATA_ONLY
        text = ""
    elif is_self and selftext:
        completeness = ContentCompleteness.FULL
        text = "\n\n".join(part for part in (title, selftext) if part)
    else:
        completeness = ContentCompleteness.METADATA_ONLY
        text = ""
    provenance: dict[str, Any] = {
        "original_platform": "REDDIT",
        "provider": "ARCTIC_SHIFT",
        "provider_record_id": _string(raw.get("name")) or _string(raw.get("id")),
        "provider_query_id": None,
        "canonical_source_url": identity.canonical_url if identity else None,
        "acquired_at": acquired_at,
        "content_completeness": completeness.value,
        "reddit_submission_id": identity.submission_id if identity else None,
        "reddit_comment_id": None,
        "parent_thread_id": None,
        "body_complete": completeness is ContentCompleteness.FULL,
        "retrieved_at": acquired_at,
        "raw_retention": raw_retention.value,
        "removed_or_deleted": removed,
        "is_self": is_self,
        "archive_retrieved_on": _string(raw.get("retrieved_on")),
    }
    item = (
        SourceItemInput(
            external_id=identity.external_id,
            raw_text=text,
            url=identity.canonical_url,
            title=title,
            author_external_id=author,
            published_at=published,
            metadata=provenance,
        ) if text and identity else None
    )
    return RedditProviderRecord(
        source, item, completeness, identity.canonical_url if identity else None,
        "ARCTIC_SHIFT", provenance["provider_record_id"], None, published, acquired_at,
        missing, provenance,
    )


class ArcticShiftHealthProvider:
    """Adapts ArcticShiftRedditProvider into source_health.HealthProvider. One
    search request is the health check; classify_health (unmodified) decides
    ACTIVE/INACTIVE_OR_LOW_ACTIVITY/ACCESS_RESTRICTED/SOURCE_UNAVAILABLE/UNKNOWN
    from the capture -- this class never assigns a HealthStatus itself."""

    name = "arctic_shift"

    def __init__(self, provider: ArcticShiftRedditProvider) -> None:
        self._provider = provider

    def check(self, source: str) -> HealthCapture:
        subreddit = source.removeprefix("r/")
        checked_at = _now_iso()
        started = time.monotonic()
        try:
            page = self._provider.discover(subreddit, "", "", 25, 0)
        except ArcticShiftError as exc:
            return self._failure_capture(source, checked_at, started, exc)
        latency = round((time.monotonic() - started) * 1000)
        usable: list[dict[str, Any]] = []
        for raw in page.records:
            if not isinstance(raw, dict):
                continue
            typed = cast(dict[str, Any], raw)
            has_identity = typed.get("permalink") and typed.get("created_utc")
            if has_identity and not is_removed_or_deleted(typed):
                usable.append(typed)
        if not usable:
            return HealthCapture(
                source=source, provider=self.name, checked_at=checked_at,
                access_result=AccessResult.PUBLIC_NO_RECENT, http_status=200,
                latest_visible_item_at=None, visible_item_count=0,
                sample_window_start=checked_at, sample_window_end=checked_at,
                coverage_complete=True, reason="archive reachable, zero usable records",
                evidence_urls=(), latency_ms=latency, cost_usd=0.0,
            )
        timestamps = sorted(
            datetime.fromtimestamp(float(raw["created_utc"]), tz=UTC).isoformat()
            for raw in usable
        )
        evidence = tuple(
            f"https://www.reddit.com{raw['permalink']}" for raw in usable[:5]
        )
        return HealthCapture(
            source=source, provider=self.name, checked_at=checked_at,
            access_result=AccessResult.PUBLIC_CONTENT, http_status=200,
            latest_visible_item_at=timestamps[-1], visible_item_count=len(usable),
            sample_window_start=timestamps[0], sample_window_end=checked_at,
            coverage_complete=len(usable) < 25,
            reason="Arctic Shift search returned recent records", evidence_urls=evidence,
            latency_ms=latency, cost_usd=0.0,
        )

    def _failure_capture(
        self, source: str, checked_at: str, started: float, exc: ArcticShiftError
    ) -> HealthCapture:
        latency = round((time.monotonic() - started) * 1000)
        if exc.failure is ProviderFailure.SOURCE_NOT_COVERED:
            access_result, http_status = AccessResult.SOURCE_NOT_FOUND, 404
        else:
            access_result, http_status = AccessResult.PROVIDER_FAILED, None
        return HealthCapture(
            source=source, provider=self.name, checked_at=checked_at,
            access_result=access_result, http_status=http_status,
            latest_visible_item_at=None, visible_item_count=0,
            sample_window_start=None, sample_window_end=None,
            coverage_complete=False, reason=str(exc), evidence_urls=(),
            latency_ms=latency, cost_usd=0.0,
        )
