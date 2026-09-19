"""Composes existing Brandwatch and canonical-ingestion pieces into a live-pilot
`acquire_source` callable. Adds no new Brandwatch behavior: it only calls
`BrandwatchRedditProvider.discover`/`fetch_fulltext`, `normalize_brandwatch_reddit_record`,
and `ingest_provider_records`, none of which are modified here.

Brandwatch query IDs are provider-specific configuration, kept out of the
provider-independent live pilot manifest by design (see `live_pilot.py`). This module
reads them from a separate small JSON file, keyed by subreddit; a manifest source with
no configured query ID is skipped for this provider, not fabricated.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from .brandwatch import (
    BrandwatchError,
    BrandwatchRedditProvider,
    normalize_brandwatch_reddit_record,
)
from .live_pilot import LiveManifestEntry, SourceRunOutcome, SourceRunStatus
from .reddit import ingest_provider_records
from .reddit_provider import RedditProviderRecord
from .repository import Repository


def load_brandwatch_provider_config(path: Path) -> dict[str, int]:
    """Subreddit (casefolded, no leading `r/`) -> Brandwatch query ID. Missing or
    `null` query IDs are simply absent from the returned mapping."""

    value: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Brandwatch provider config must contain a sources array")
    root = cast(dict[str, object], value)
    sources = root.get("sources")
    if not isinstance(sources, list):
        raise ValueError("Brandwatch provider config must contain a sources array")
    mapping: dict[str, int] = {}
    for raw in cast(list[object], sources):
        if not isinstance(raw, dict):
            raise ValueError("Brandwatch provider config source entry must be an object")
        row = cast(dict[str, object], raw)
        name, query_id = row.get("name"), row.get("query_id")
        if not isinstance(name, str) or not name:
            raise ValueError("Brandwatch provider config source name must be non-empty")
        if query_id is None:
            continue
        if type(query_id) is not int or query_id <= 0:
            raise ValueError("Brandwatch provider config query_id must be a positive integer")
        mapping[name.removeprefix("r/").casefold()] = query_id
    return mapping


def build_brandwatch_acquire_source(
    repository: Repository,
    provider: BrandwatchRedditProvider,
    provider_config: Mapping[str, int],
    *,
    start_date: str,
    end_date: str,
    max_page_size: int = 20,
) -> Callable[[LiveManifestEntry], SourceRunOutcome]:
    """Returns a `live_pilot.run_live_pilot`-compatible `acquire_source` callable."""

    capabilities = asdict(provider.capabilities)

    def acquire(entry: LiveManifestEntry) -> SourceRunOutcome:
        query_id = provider_config.get(entry.subreddit.removeprefix("r/").casefold())
        if query_id is None:
            return SourceRunOutcome(
                SourceRunStatus.SKIPPED,
                error="QUERY_CONFIGURATION_ERROR: no Brandwatch query ID configured",
            )
        source_id = repository.upsert_source(
            source_type="reddit", name=entry.subreddit,
            access_method="licensed-provider:brandwatch",
            commercial_use_status="REVIEW_REQUIRED",
        )
        page_size = max(1, min(entry.pilot_item_target, max_page_size))
        query = str(query_id)
        discovery = provider.discover(query, start_date, end_date, page_size, 0)
        fulltext = provider.fetch_fulltext(query, start_date, end_date, page_size, 0)
        full_by_id = {
            str(row["resourceId"]): row
            for row in fulltext.records if row.get("resourceId") is not None
        }
        acquired_at = datetime.now(UTC).isoformat()
        records: list[RedditProviderRecord] = []
        for mention in discovery.records:
            try:
                records.append(normalize_brandwatch_reddit_record(
                    mention, full_by_id.get(str(mention.get("resourceId"))),
                    requested_subreddit=entry.subreddit, query_id=query_id,
                    acquired_at=acquired_at,
                ))
            except BrandwatchError:
                continue  # one malformed/mismatched mention must not fail the whole source
        acquisition_ids = ingest_provider_records(
            repository, source_id=source_id, provider="brandwatch", query=query,
            records=tuple(records), capabilities=capabilities,
        )
        return SourceRunOutcome(SourceRunStatus.COMPLETE, acquisition_ids=acquisition_ids)

    return acquire
