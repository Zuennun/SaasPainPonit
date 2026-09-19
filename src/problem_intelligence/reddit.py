"""Provider-independent Reddit discovery and acquisition.

The module deliberately contains no Reddit client and no access-evasion logic. Providers
return provenance-bearing captures; the service normalizes identity and persists states.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol, cast
from urllib.parse import unquote, urlsplit

from .domain import ContentCompleteness, DiscoveryState, SourceAvailability
from .repository import Repository

DEFAULT_SUBREDDITS = (
    "Accounting",
    "restaurantowners",
    "airbnb_hosts",
    "SEO",
    "smallbusiness",
    "AppIdeas",  # negative/control community: idea discussion rather than operator-only pain
)

QUERY_GROUPS: dict[str, tuple[str, ...]] = {
    "manual_work": (
        "manual",
        "manually",
        "spreadsheet",
        "excel",
        "copy",
        "paste",
        "export",
        "import",
        "csv",
    ),
    "workflow_friction": (
        "annoying",
        "pain",
        "problem",
        "frustrating",
        "takes hours",
        "waste time",
        "tedious",
    ),
    "active_search": (
        "looking for",
        "is there a tool",
        "any software",
        "alternative",
        "recommend",
        "how do you handle",
    ),
    "integration_gap": (
        "integration",
        "sync",
        "connect",
        "workflow",
        "reconcile",
        "duplicate",
        "data entry",
    ),
}


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    supports_search: bool
    supports_full_content: bool
    supports_comments: bool
    supports_date_filter: bool
    supports_subreddit_filter: bool
    supports_pagination: bool
    supports_historical_search: bool


@dataclass(frozen=True, slots=True)
class SearchResult:
    url: str
    title: str | None = None
    snippet: str | None = None


@dataclass(frozen=True, slots=True)
class SearchResponse:
    availability: SourceAvailability
    results: tuple[SearchResult, ...] = ()
    latency_ms: int | None = None
    cost_usd: float | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class AcquisitionResponse:
    state: DiscoveryState
    completeness: ContentCompleteness | None
    text: str | None = None
    title: str | None = None
    author_external_id: str | None = None
    published_at: str | None = None
    latency_ms: int | None = None
    cost_usd: float | None = None
    error: str | None = None
    metadata: dict[str, Any] | None = None


class SearchProvider(Protocol):
    name: str
    capabilities: ProviderCapabilities

    def search(self, query: str) -> SearchResponse: ...


class AcquisitionProvider(Protocol):
    name: str
    capabilities: ProviderCapabilities

    def acquire(self, canonical_url: str) -> AcquisitionResponse: ...


@dataclass(frozen=True, slots=True)
class RedditIdentity:
    canonical_url: str
    submission_id: str
    comment_id: str | None
    subreddit: str | None

    @property
    def external_id(self) -> str:
        if self.comment_id:
            return f"reddit:comment:{self.submission_id}:{self.comment_id}"
        return f"reddit:submission:{self.submission_id}"


def canonicalize_reddit_url(url: str) -> RedditIdentity | None:
    """Return stable Reddit identity for common post/comment/share URL variants."""

    parsed = urlsplit(url.strip())
    host = parsed.hostname.lower() if parsed.hostname else ""
    if host.startswith("www."):
        host = host[4:]
    allowed_hosts = {"reddit.com", "old.reddit.com", "new.reddit.com", "np.reddit.com", "redd.it"}
    if host not in allowed_hosts and not host.endswith(".reddit.com"):
        return None
    parts = [unquote(part) for part in parsed.path.split("/") if part]
    if host == "redd.it":
        if not parts:
            return None
        submission_id = parts[0].lower()
        return RedditIdentity(
            f"https://www.reddit.com/comments/{submission_id}/",
            submission_id,
            None,
            None,
        )

    # Locale-prefixed links occasionally appear as /en/r/... .
    if len(parts) >= 2 and parts[0].lower() in {"en", "de", "fr", "es", "it"}:
        parts = parts[1:]
    lower = [part.lower() for part in parts]
    try:
        comments_index = lower.index("comments")
    except ValueError:
        return None
    if comments_index + 1 >= len(parts):
        return None
    submission_id = parts[comments_index + 1].lower()
    subreddit: str | None = None
    if comments_index >= 2 and lower[comments_index - 2] == "r":
        subreddit = parts[comments_index - 1]
    # /comments/id/slug/comment_id; the slug itself is never identity. A URL that
    # drops the slug entirely (/comments/<submission_id>/<comment_id>) is
    # indistinguishable from a slug-only submission URL by position alone, so it
    # is conservatively treated as a submission rather than guessing.
    comment_id = parts[comments_index + 3].lower() if len(parts) > comments_index + 3 else None
    prefix = f"/r/{subreddit.lower()}" if subreddit else ""
    if comment_id:
        canonical = (
            f"https://www.reddit.com{prefix}/comments/{submission_id}/_/{comment_id}/"
        )
    else:
        canonical = f"https://www.reddit.com{prefix}/comments/{submission_id}/"
    return RedditIdentity(canonical, submission_id, comment_id, subreddit)


def build_reddit_query(
    subreddit: str, group: str, *, time_context: str | None = None
) -> str:
    terms = QUERY_GROUPS.get(group)
    if terms is None:
        raise ValueError(f"unknown query group: {group}")
    return build_reddit_query_for_vocabulary(
        subreddit, terms, time_context=time_context
    )


def build_reddit_query_for_vocabulary(
    subreddit: str,
    problem_vocabulary: Sequence[str],
    *,
    time_context: str | None = None,
) -> str:
    """Build a deterministic provider query from caller-supplied problem language."""

    normalized_terms = tuple(dict.fromkeys(" ".join(term.split()) for term in problem_vocabulary))
    if not normalized_terms or any(not term for term in normalized_terms):
        raise ValueError("problem vocabulary must contain non-blank terms")
    quoted = " OR ".join(f'"{term}"' for term in normalized_terms)
    query = f"site:reddit.com/r/{subreddit} ({quoted})"
    if time_context is not None:
        normalized_context = " ".join(time_context.split())
        if not normalized_context:
            raise ValueError("time context must not be blank")
        query += f' "{normalized_context}"'
    return query


def build_reddit_queries(
    subreddit: str, *, time_context: str | None = None
) -> tuple[tuple[str, str], ...]:
    return tuple(
        (group, build_reddit_query(subreddit, group, time_context=time_context))
        for group in QUERY_GROUPS
    )


class JsonlSearchProvider:
    """Replay an auditable JSONL export from any permitted search provider."""

    def __init__(self, path: Path) -> None:
        rows = _jsonl_rows(path)
        self._responses = {str(row["query"]): row for row in rows}
        provider_names = {str(row["provider"]) for row in rows}
        if len(provider_names) != 1:
            raise ValueError("search capture must contain exactly one provider")
        self.name = next(iter(provider_names))
        self.capabilities = _capabilities(rows[0]["capabilities"])

    def search(self, query: str) -> SearchResponse:
        row = self._responses.get(query)
        if row is None:
            return SearchResponse(
                SourceAvailability.SOURCE_UNAVAILABLE,
                error="query absent from provider capture",
            )
        results = tuple(
            SearchResult(str(item["url"]), item.get("title"), item.get("snippet"))
            for item in row.get("results", [])
        )
        return SearchResponse(
            SourceAvailability(str(row["availability"])),
            results,
            _optional_int(row.get("latency_ms")),
            _optional_float(row.get("cost_usd")),
            _optional_str(row.get("error")),
        )


class JsonlAcquisitionProvider:
    """Replay provenance-preserving content captures keyed by canonical Reddit URL."""

    def __init__(self, path: Path) -> None:
        rows = _jsonl_rows(path)
        self._responses: dict[str, dict[str, Any]] = {}
        provider_names = {str(row["provider"]) for row in rows}
        if len(provider_names) != 1:
            raise ValueError("acquisition capture must contain exactly one provider")
        self.name = next(iter(provider_names))
        self.capabilities = _capabilities(rows[0]["capabilities"])
        for row in rows:
            identity = canonicalize_reddit_url(str(row["url"]))
            if identity is None:
                raise ValueError(f"not a Reddit content URL: {row['url']}")
            self._responses[identity.canonical_url] = row

    def acquire(self, canonical_url: str) -> AcquisitionResponse:
        row = self._responses.get(canonical_url)
        if row is None:
            return AcquisitionResponse(
                DiscoveryState.ACQUISITION_FAILED,
                None,
                error="URL absent from provider capture",
            )
        completeness_raw = row.get("completeness")
        return AcquisitionResponse(
            state=DiscoveryState(str(row["state"])),
            completeness=(
                ContentCompleteness(str(completeness_raw))
                if completeness_raw is not None
                else None
            ),
            text=_optional_str(row.get("text")),
            title=_optional_str(row.get("title")),
            author_external_id=_optional_str(row.get("author_external_id")),
            published_at=_optional_str(row.get("published_at")),
            latency_ms=_optional_int(row.get("latency_ms")),
            cost_usd=_optional_float(row.get("cost_usd")),
            error=_optional_str(row.get("error")),
            metadata=dict(row.get("metadata", {})),
        )


def discover_subreddits(
    repository: Repository,
    provider: SearchProvider,
    *,
    subreddits: tuple[str, ...] = DEFAULT_SUBREDDITS,
    query_groups: tuple[str, ...] = tuple(QUERY_GROUPS),
    time_context: str | None = None,
) -> tuple[str, ...]:
    run_ids: list[str] = []
    for subreddit in subreddits:
        source_id = repository.upsert_source(
            source_type="reddit",
            name=f"r/{subreddit}",
            access_method=f"external-search:{provider.name}",
            commercial_use_status="REVIEW_REQUIRED",
            attribution_requirements="retain canonical Reddit URL and provider provenance",
        )
        for group in query_groups:
            query = build_reddit_query(subreddit, group, time_context=time_context)
            response = provider.search(query)
            run_ids.append(
                repository.record_discovery_response(
                    source_id=source_id,
                    provider=provider.name,
                    query=query,
                    availability=response.availability,
                    results=response.results,
                    capabilities=asdict(provider.capabilities),
                    latency_ms=response.latency_ms,
                    cost_usd=response.cost_usd,
                    error=response.error,
                )
            )
    return tuple(run_ids)


def acquire_discoveries(
    repository: Repository, provider: AcquisitionProvider
) -> tuple[int, ...]:
    acquisition_ids: list[int] = []
    responses: dict[str, AcquisitionResponse] = {}
    source_item_ids: dict[str, int | None] = {}
    for row in repository.pending_discoveries(provider.name):
        canonical_url = str(row["canonical_url"])
        reused = canonical_url in responses
        if reused:
            response = responses[canonical_url]
        else:
            response = provider.acquire(canonical_url)
            responses[canonical_url] = response
        acquisition_metadata = {
            **(response.metadata or {}),
            "provider_capabilities": asdict(provider.capabilities),
            "provider_invocation": not reused,
            "reused_acquisition_url": canonical_url if reused else None,
        }
        source_item_id: int | None = source_item_ids.get(canonical_url)
        identity = canonicalize_reddit_url(str(row["canonical_url"]))
        assert identity is not None
        if response.state in {DiscoveryState.CONTENT_PARTIAL, DiscoveryState.CONTENT_COMPLETE}:
            if response.completeness is None:
                raise ValueError("successful acquisition requires completeness")
            if response.state is DiscoveryState.CONTENT_COMPLETE and (
                response.completeness is not ContentCompleteness.FULL
            ):
                raise ValueError("CONTENT_COMPLETE requires FULL completeness")
            if response.completeness is not ContentCompleteness.METADATA_ONLY and not reused:
                if not response.text:
                    raise ValueError("text acquisition requires non-empty text")
                source_item_id = repository.upsert_source_item(
                    source_id=int(row["source_id"]),
                    external_id=identity.external_id,
                    raw_text=response.text,
                    url=identity.canonical_url,
                    title=response.title or row["title"],
                    author_external_id=response.author_external_id,
                    published_at=response.published_at,
                    language_code="en",
                    metadata={
                        **acquisition_metadata,
                        "platform": "reddit",
                        "content_completeness": response.completeness.value,
                        "acquisition_provider": provider.name,
                        "discovery_provider": row["provider"],
                        "discovery_run_id": row["run_id"],
                    },
                )
        elif response.completeness is not None:
            raise ValueError("failed or blocked acquisition cannot claim completeness")
        if not reused:
            source_item_ids[canonical_url] = source_item_id
        acquisition_ids.append(
            repository.record_acquisition(
                discovery_id=int(row["id"]),
                source_item_id=source_item_id,
                provider=provider.name,
                state=response.state,
                completeness=response.completeness,
                latency_ms=None if reused else response.latency_ms,
                cost_usd=0.0 if reused else response.cost_usd,
                error=response.error,
                metadata=acquisition_metadata,
            )
        )
    return tuple(acquisition_ids)


def _jsonl_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value: object = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number}: expected JSON object")
        object_row = cast(dict[object, object], value)
        rows.append({str(key): item for key, item in object_row.items()})
    if not rows:
        raise ValueError(f"{path}: capture is empty")
    return rows


def _capabilities(value: object) -> ProviderCapabilities:
    if not isinstance(value, dict):
        raise ValueError("capabilities must be an object")
    object_value = cast(dict[object, object], value)
    return ProviderCapabilities(**{str(key): bool(item) for key, item in object_value.items()})


def _optional_str(value: object) -> str | None:
    return None if value is None else str(value)


def _optional_int(value: object) -> int | None:
    return None if value is None else int(str(value))


def _optional_float(value: object) -> float | None:
    return None if value is None else float(str(value))
