"""Free, zero-cost Reddit acquisition via public subreddit RSS (Atom) feeds.

Feed structure (Atom, not RSS 2.0, despite the `.rss` path) was verified against a
live public request during development:
`<entry><id>t3_xxxxx</id><link href="canonical permalink"/><title>`, `<published>`,
`<author><name>/u/x</name>`, and `<content type="html">` holding the rendered
self-text wrapped in `<!-- SC_OFF --><div class="md">...</div><!-- SC_ON -->`,
followed by an always-present `submitted by ... [link] [comments]` footer. Link and
image posts carry *only* that footer -- no `SC_OFF`/`md` wrapper -- which is the
actual signal this module uses to tell FULL self-text posts apart from
METADATA_ONLY link posts; it is not inferred from content length.

Reddit's robots.txt disallows automated access to all paths for all user agents
(`Disallow: /`). This provider is used only under an explicit arrangement with
Reddit confirmed by the project owner; see
docs/providers/reddit-rss-rights-checklist.md. It never uses `.json` endpoints, the
official API, OAuth, search RSS, or comment RSS, and never rotates proxies or
identities to work around a restriction.
"""

from __future__ import annotations

import html
import re
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.error import HTTPError, URLError
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

BASE_URL = "https://www.reddit.com"
ATOM_NS = "{http://www.w3.org/2005/Atom}"
DEFAULT_MIN_REQUEST_INTERVAL_SECONDS = 90.0


class RedditRssError(RuntimeError):
    def __init__(
        self, failure: ProviderFailure, message: str, *, retry_after_seconds: float | None = None
    ) -> None:
        super().__init__(message)
        self.failure = failure
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True, slots=True)
class RedditRssConfig:
    user_agent: str
    min_request_interval_seconds: float = DEFAULT_MIN_REQUEST_INTERVAL_SECONDS
    timeout_seconds: float = 15.0
    healthcheck_subreddit: str = "announcements"

    def __post_init__(self) -> None:
        if not self.user_agent.strip():
            raise ValueError("a descriptive User-Agent is required")
        if self.min_request_interval_seconds < 0:
            raise ValueError("min_request_interval_seconds must not be negative")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if not self.healthcheck_subreddit.strip():
            raise ValueError("healthcheck_subreddit must not be empty")


@dataclass(frozen=True, slots=True)
class RssHttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


@dataclass(frozen=True, slots=True)
class RssEntry:
    """One parsed Atom entry; `body` is None for link/image posts (no self-text)."""

    entry_id: str | None
    link: str | None
    title: str | None
    author: str | None
    published_at: str | None
    body: str | None


Transport = Callable[[str, Mapping[str, str]], RssHttpResponse]

_MD_WRAPPER_RE = re.compile(r"<!--\s*SC_OFF\s*-->(.*?)<!--\s*SC_ON\s*-->", re.S)
_TAG_RE = re.compile(r"<[^>]+>")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _header(response: RssHttpResponse, name: str) -> str | None:
    """Case-insensitive header lookup: HTTP/2 responses (observed live) return all
    header names lowercased, while HTTP/1.1 typically preserves server casing."""

    target = name.casefold()
    for key, value in response.headers.items():
        if key.casefold() == target:
            return value
    return None


def _text(elem: ET.Element | None) -> str | None:
    if elem is None or elem.text is None:
        return None
    stripped = elem.text.strip()
    return stripped or None


def _extract_self_text(content_html: str) -> str | None:
    """Only the rendered self-text between the SC_OFF/SC_ON markers, never the
    trailing 'submitted by ... [link] [comments]' footer that every entry carries."""

    match = _MD_WRAPPER_RE.search(content_html)
    if match is None:
        return None
    without_tags = _TAG_RE.sub(" ", match.group(1))
    text = html.unescape(without_tags)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def parse_atom_entries(body: bytes) -> tuple[RssEntry, ...]:
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise RedditRssError(ProviderFailure.INVALID_FEED, "malformed Atom XML") from exc
    entries: list[RssEntry] = []
    for elem in root.findall(f"{ATOM_NS}entry"):
        link_elem = elem.find(f"{ATOM_NS}link")
        link = link_elem.get("href") if link_elem is not None else None
        author = _text(elem.find(f"{ATOM_NS}author/{ATOM_NS}name"))
        if author is not None:
            author = author.removeprefix("/u/")
        content_elem = elem.find(f"{ATOM_NS}content")
        content_raw = content_elem.text if content_elem is not None else None
        body_text = _extract_self_text(content_raw) if content_raw else None
        entries.append(RssEntry(
            entry_id=_text(elem.find(f"{ATOM_NS}id")),
            link=link,
            title=_text(elem.find(f"{ATOM_NS}title")),
            author=author,
            published_at=(
                _text(elem.find(f"{ATOM_NS}published"))
                or _text(elem.find(f"{ATOM_NS}updated"))
            ),
            body=body_text,
        ))
    return tuple(entries)


def compute_backoff_seconds(
    attempt: int, *, base: float = DEFAULT_MIN_REQUEST_INTERVAL_SECONDS, maximum: float = 1800.0
) -> float:
    """90 -> 180 -> 360 -> 720 -> ... capped at `maximum`. A starting operational
    default, not a claimed official Reddit rate limit."""

    if attempt < 0:
        raise ValueError("attempt must not be negative")
    return min(base * (2**attempt), maximum)


class RedditRssProvider:
    name = "reddit_rss"
    readiness = ProductionReadiness.CONTRACT_REVIEW_REQUIRED
    capabilities = RedditProviderCapabilities(
        supports_reddit=True,
        supports_subreddit_filter=True,
        supports_date_filter=False,
        supports_pagination=False,
        supports_fulltext=True,
        supports_comments=False,
        supports_historical_data=False,
        supports_incremental_fetch=True,
    )

    def __init__(
        self,
        config: RedditRssConfig,
        *,
        transport: Transport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config
        self._transport = transport or self._request
        self._sleep = sleep
        self.requests = 0
        self.successful_requests = 0
        self.not_modified_responses = 0
        self.rate_limited_responses = 0
        self.last_success: str | None = None
        self.last_failure: str | None = None
        self.latency_ms = 0
        self._last_request_at: float | None = None
        self._conditional_cache: dict[str, tuple[str | None, str | None]] = {}
        self._last_entries: dict[str, tuple[RssEntry, ...]] = {}
        self._page_cache: dict[tuple[str, int], ProviderPage] = {}

    def healthcheck(self) -> bool:
        self._fetch_feed(self.config.healthcheck_subreddit, page_size=1)
        return True

    def discover(
        self, query: str, start_date: str, end_date: str, page_size: int, page: int
    ) -> ProviderPage:
        if not 1 <= page_size <= 100:
            raise ValueError("page_size must be between 1 and 100")
        if page < 0:
            raise ValueError("page must not be negative")
        if page > 0:
            # RSS has no true pagination: only the most recent window is available.
            return ProviderPage((), 0, page, 0)
        result = self._fetch_feed(query, page_size)
        self._page_cache[(query.casefold(), page_size)] = result
        return result

    def fetch_fulltext(
        self, query: str, start_date: str, end_date: str, page_size: int, page: int
    ) -> ProviderPage:
        if page > 0:
            return ProviderPage((), 0, page, 0)
        cached = self._page_cache.get((query.casefold(), page_size))
        if cached is not None:
            return cached
        # RSS delivers full content in the same response as discovery; fulltext is
        # only fetched again here if called without a preceding matching discover().
        return self._fetch_feed(query, page_size)

    def _fetch_feed(self, subreddit: str, page_size: int) -> ProviderPage:
        key = subreddit.casefold()
        self._respect_min_interval()
        headers: dict[str, str] = {
            "User-Agent": self.config.user_agent, "Accept": "application/atom+xml",
        }
        etag, last_modified = self._conditional_cache.get(key, (None, None))
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified
        started = time.monotonic()
        self.requests += 1
        response = self._transport(f"/r/{subreddit}/.rss", headers)
        self._last_request_at = time.monotonic()
        latency = round((time.monotonic() - started) * 1000)
        self.latency_ms += latency
        return self._handle_response(key, response, page_size, latency)

    def _handle_response(
        self, key: str, response: RssHttpResponse, page_size: int, latency: int
    ) -> ProviderPage:
        if response.status == 304:
            self.not_modified_responses += 1
            self.successful_requests += 1
            self.last_success = _now_iso()
            cached = self._last_entries.get(key, ())
            return ProviderPage(cached[:page_size], len(cached), 0, latency)
        if response.status == 429:
            self.rate_limited_responses += 1
            self.last_failure = _now_iso()
            # Reddit signals its own rate limit via X-Ratelimit-Reset (seconds until
            # reset), observed live; a standard Retry-After is used first if present.
            retry_after = _parse_retry_after(
                _header(response, "retry-after") or _header(response, "x-ratelimit-reset")
            )
            raise RedditRssError(
                ProviderFailure.RATE_LIMITED, "rate limited (429)",
                retry_after_seconds=retry_after,
            )
        if response.status == 403:
            self.last_failure = _now_iso()
            raise RedditRssError(ProviderFailure.ACCESS_RESTRICTED, "access restricted (403)")
        if response.status == 404:
            self.last_failure = _now_iso()
            raise RedditRssError(
                ProviderFailure.SOURCE_NOT_COVERED, "subreddit not found or private (404)"
            )
        if response.status >= 500:
            self.last_failure = _now_iso()
            raise RedditRssError(
                ProviderFailure.PROVIDER_UNAVAILABLE, f"server error ({response.status})"
            )
        if response.status != 200:
            self.last_failure = _now_iso()
            raise RedditRssError(
                ProviderFailure.UNKNOWN_ERROR, f"unexpected status ({response.status})"
            )
        entries = parse_atom_entries(response.body)
        self._last_entries[key] = entries
        new_etag = _header(response, "etag")
        new_last_modified = _header(response, "last-modified")
        if new_etag or new_last_modified:
            self._conditional_cache[key] = (new_etag, new_last_modified)
        self.successful_requests += 1
        self.last_success = _now_iso()
        return ProviderPage(entries[:page_size], len(entries), 0, latency)

    def _respect_min_interval(self) -> None:
        if self._last_request_at is None:
            return
        elapsed = time.monotonic() - self._last_request_at
        remaining = self.config.min_request_interval_seconds - elapsed
        if remaining > 0:
            self._sleep(remaining)

    def _request(self, path: str, headers: Mapping[str, str]) -> RssHttpResponse:
        request = Request(BASE_URL + path, headers=dict(headers))
        try:
            with urlopen(request, timeout=self.config.timeout_seconds) as response:
                return RssHttpResponse(
                    response.status, dict(response.headers), response.read()
                )
        except HTTPError as exc:
            body = exc.read()
            return RssHttpResponse(exc.code, dict(exc.headers), body)
        except (URLError, TimeoutError) as exc:
            raise RedditRssError(
                ProviderFailure.PROVIDER_UNAVAILABLE, f"network failure: {exc}"
            ) from exc


def _parse_retry_after(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def normalize_rss_entry(
    entry: RssEntry,
    *,
    requested_subreddit: str,
    acquired_at: str,
    raw_retention: RawRetentionPolicy = RawRetentionPolicy.DO_NOT_PERSIST,
) -> RedditProviderRecord:
    """Never infer a body from title/footer text; a link post with no self-text is
    METADATA_ONLY, not reconstructed or upgraded by an LLM."""

    source = "r/" + requested_subreddit.removeprefix("r/")
    identity = canonicalize_reddit_url(entry.link) if entry.link else None
    if entry.link and (identity is None or identity.subreddit is None or (
        identity.subreddit.casefold() != source.removeprefix("r/").casefold()
    )):
        raise RedditRssError(
            ProviderFailure.SOURCE_NOT_COVERED,
            f"entry URL does not identify requested {source}",
        )
    missing = tuple(
        name for name, value in (
            ("title", entry.title), ("body", entry.body),
            ("subreddit", identity.subreddit if identity else None),
            ("url", entry.link), ("timestamp", entry.published_at),
        ) if not value
    )
    if entry.body and identity is not None:
        completeness = ContentCompleteness.FULL
        text = "\n\n".join(part for part in (entry.title, entry.body) if part)
    else:
        completeness = ContentCompleteness.METADATA_ONLY
        text = ""
    provenance: dict[str, Any] = {
        "original_platform": "REDDIT",
        "provider": "REDDIT_RSS",
        "provider_record_id": entry.entry_id,
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
    }
    item = (
        SourceItemInput(
            external_id=identity.external_id,
            raw_text=text,
            url=identity.canonical_url,
            title=entry.title,
            author_external_id=entry.author,
            published_at=entry.published_at,
            metadata=provenance,
        ) if text and identity else None
    )
    return RedditProviderRecord(
        source, item, completeness, identity.canonical_url if identity else None,
        "REDDIT_RSS", entry.entry_id, None, entry.published_at, acquired_at, missing, provenance,
    )


class RedditRssHealthProvider:
    """Adapts RedditRssProvider into source_health.HealthProvider. One RSS poll is
    the health check; classify_health (unmodified) decides ACTIVE/INACTIVE_OR_LOW_
    ACTIVITY/ACCESS_RESTRICTED/SOURCE_UNAVAILABLE/UNKNOWN from the capture -- this
    class never assigns a HealthStatus itself, only reports what was observed."""

    name = "reddit_rss"

    def __init__(self, provider: RedditRssProvider) -> None:
        self._provider = provider

    def check(self, source: str) -> HealthCapture:
        subreddit = source.removeprefix("r/")
        checked_at = _now_iso()
        started = time.monotonic()
        try:
            page = self._provider.discover(subreddit, "", "", 25, 0)
        except RedditRssError as exc:
            return self._failure_capture(source, checked_at, started, exc)
        latency = round((time.monotonic() - started) * 1000)
        entries = [
            entry for entry in page.records
            if isinstance(entry, RssEntry) and entry.link and entry.published_at
        ]
        if not entries:
            return HealthCapture(
                source=source, provider=self.name, checked_at=checked_at,
                access_result=AccessResult.PUBLIC_NO_RECENT, http_status=200,
                latest_visible_item_at=None, visible_item_count=0,
                sample_window_start=checked_at, sample_window_end=checked_at,
                coverage_complete=True, reason="feed reachable, zero entries",
                evidence_urls=(), latency_ms=latency, cost_usd=0.0,
            )
        published = sorted(str(entry.published_at) for entry in entries)
        evidence = tuple(str(entry.link) for entry in entries[:5])
        return HealthCapture(
            source=source, provider=self.name, checked_at=checked_at,
            access_result=AccessResult.PUBLIC_CONTENT, http_status=200,
            latest_visible_item_at=published[-1], visible_item_count=len(entries),
            sample_window_start=published[0], sample_window_end=checked_at,
            coverage_complete=len(entries) < 25,
            reason="RSS feed poll returned recent entries", evidence_urls=evidence,
            latency_ms=latency, cost_usd=0.0,
        )

    def _failure_capture(
        self, source: str, checked_at: str, started: float, exc: RedditRssError
    ) -> HealthCapture:
        latency = round((time.monotonic() - started) * 1000)
        if exc.failure is ProviderFailure.ACCESS_RESTRICTED:
            access_result, http_status = AccessResult.ACCESS_RESTRICTED, 403
        elif exc.failure is ProviderFailure.SOURCE_NOT_COVERED:
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
