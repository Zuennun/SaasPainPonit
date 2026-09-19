"""Narrow, provider-independent Reddit acquisition contract for feed/data-provider
style providers (paginated mentions plus optional fulltext), licensed or free."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

from .connectors import SourceItemInput
from .domain import ContentCompleteness


class ProviderFailure(StrEnum):
    NO_RESULTS = "NO_RESULTS"
    AUTH_FAILURE = "AUTH_FAILURE"
    RATE_LIMITED = "RATE_LIMITED"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    QUERY_CONFIGURATION_ERROR = "QUERY_CONFIGURATION_ERROR"
    FULLTEXT_UNAVAILABLE = "FULLTEXT_UNAVAILABLE"
    SOURCE_NOT_COVERED = "SOURCE_NOT_COVERED"
    ACCESS_RESTRICTED = "ACCESS_RESTRICTED"
    INVALID_FEED = "INVALID_FEED"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


class ProductionReadiness(StrEnum):
    TECHNICALLY_VALIDATED = "TECHNICALLY_VALIDATED"
    CONTRACT_REVIEW_REQUIRED = "CONTRACT_REVIEW_REQUIRED"
    PRODUCTION_APPROVED = "PRODUCTION_APPROVED"
    PRODUCTION_BLOCKED = "PRODUCTION_BLOCKED"
    #: Distinct from CONTRACT_REVIEW_REQUIRED: not merely unconfirmed, but actively
    #: prohibited by the target's own stated access policy (e.g. robots.txt) unless
    #: and until explicit documented permission is obtained. Technical validation can
    #: never change this status on its own.
    POLICY_BLOCKED = "POLICY_BLOCKED"


class RawRetentionPolicy(StrEnum):
    DO_NOT_PERSIST = "DO_NOT_PERSIST"
    DAYS_7 = "DAYS_7"
    DAYS_30 = "DAYS_30"
    INDEFINITE = "INDEFINITE"


@dataclass(frozen=True, slots=True)
class RedditProviderCapabilities:
    supports_reddit: bool
    supports_subreddit_filter: bool
    supports_date_filter: bool
    supports_pagination: bool
    supports_fulltext: bool
    supports_comments: bool | None
    supports_historical_data: bool
    supports_incremental_fetch: bool


@dataclass(frozen=True, slots=True)
class RedditProviderRecord:
    """Normalized record; opaque provider IDs remain provenance, not identity."""

    source: str
    item: SourceItemInput | None
    completeness: ContentCompleteness
    canonical_url: str | None
    provider: str
    provider_record_id: str | None
    provider_query_id: str | None
    published_at: str | None
    acquired_at: str
    missing_fields: tuple[str, ...] = ()
    provenance: dict[str, Any] = field(default_factory=lambda: {})


@dataclass(frozen=True, slots=True)
class ProviderPage:
    """`records` is opaque: each provider's own raw shape (a dict for Brandwatch's
    JSON mentions, an RssEntry for RedditRssProvider, ...). Only that provider's own
    normalize function is expected to understand it."""

    records: tuple[Any, ...]
    total: int | None
    page: int
    latency_ms: int


class RedditDataProvider(Protocol):
    name: str
    capabilities: RedditProviderCapabilities
    readiness: ProductionReadiness

    def healthcheck(self) -> bool: ...

    def discover(
        self, query: str, start_date: str, end_date: str, page_size: int, page: int
    ) -> ProviderPage: ...

    def fetch_fulltext(
        self, query: str, start_date: str, end_date: str, page_size: int, page: int
    ) -> ProviderPage: ...
