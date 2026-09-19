"""POLICY_BLOCKED: kept as a technical record and reusable script, not a runnable
production path. `main()` refuses to run while `RedditRssProvider.readiness` is not
`PRODUCTION_APPROVED` -- see reddit_rss.py's module docstring and
docs/providers/reddit-rss-rights-checklist.md. The 2026-09-19 PoC run this script
produced is documented in exports/reddit_rss_poc.md as a technical experiment; its
output was withdrawn from the approved research dataset, not treated as production
evidence.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .domain import ContentCompleteness
from .live_pilot import LiveManifestEntry, read_live_manifest_csv
from .reddit import ingest_provider_records
from .reddit_provider import ProductionReadiness, ProviderFailure, RedditProviderRecord
from .reddit_rss import RedditRssConfig, RedditRssError, RedditRssProvider, normalize_rss_entry
from .repository import Repository

CAPABILITIES: dict[str, Any] = {
    "supports_reddit": True,
    "supports_subreddit_filter": True,
    "supports_date_filter": False,
    "supports_pagination": False,
    "supports_fulltext": True,
    "supports_comments": False,
    "supports_historical_data": False,
    "supports_incremental_fetch": True,
}


@dataclass(slots=True)
class RssPocMetrics:
    status: str = "NOT_RUN"
    requests: int = 0
    successful_feeds: int = 0
    failed_feeds: int = 0
    entries_returned: int = 0
    unique_submissions: int = 0
    full: int = 0
    partial: int = 0
    metadata_only: int = 0
    duplicates: int = 0
    new_source_items: int = 0
    existing_source_items: int = 0
    rate_limited_responses: int = 0
    latency_ms: int = 0
    failures: dict[str, int] = field(default_factory=lambda: {})
    sources: dict[str, dict[str, Any]] = field(default_factory=lambda: {})


def run_poc(
    repository: Repository,
    provider: RedditRssProvider,
    sources: tuple[LiveManifestEntry, ...],
    *,
    page_size: int = 25,
) -> tuple[RssPocMetrics, tuple[int, ...]]:
    if not sources:
        raise ValueError("PoC requires at least one source")
    metrics = RssPocMetrics()
    unique_urls: set[str] = set()
    acquisition_ids: list[int] = []
    for entry in sources:
        subreddit = entry.subreddit.removeprefix("r/")
        source_metrics: dict[str, Any] = {
            "entries": 0, "full": 0, "partial": 0, "metadata_only": 0, "failure": None,
        }
        metrics.sources[entry.subreddit] = source_metrics
        try:
            discovery = provider.discover(subreddit, "", "", page_size, 0)
            fulltext = provider.fetch_fulltext(subreddit, "", "", page_size, 0)
        except RedditRssError as exc:
            source_metrics["failure"] = exc.failure.value
            metrics.failures[exc.failure.value] = metrics.failures.get(exc.failure.value, 0) + 1
            metrics.failed_feeds += 1
            if exc.failure is ProviderFailure.RATE_LIMITED:
                metrics.rate_limited_responses += 1
            continue
        metrics.successful_feeds += 1
        del discovery  # fetch_fulltext already covers the same (cached) response
        source_id = repository.upsert_source(
            source_type="reddit", name=entry.subreddit,
            access_method="public-rss:reddit_rss", commercial_use_status="REVIEW_REQUIRED",
        )
        existing_before = {
            str(row["external_id"]) for row in repository.connection.execute(
                """SELECT external_id FROM source_items WHERE source_id = ?""",
                (source_id,),
            ).fetchall()
        }
        records: list[RedditProviderRecord] = []
        for rss_entry in fulltext.records:
            metrics.entries_returned += 1
            source_metrics["entries"] += 1
            try:
                record = normalize_rss_entry(
                    rss_entry, requested_subreddit=subreddit,
                    acquired_at=datetime.now(UTC).isoformat(),
                )
            except RedditRssError as exc:
                metrics.failures[exc.failure.value] = (
                    metrics.failures.get(exc.failure.value, 0) + 1
                )
                continue
            if record.canonical_url is not None and record.canonical_url in unique_urls:
                metrics.duplicates += 1
                continue
            if record.canonical_url is not None:
                unique_urls.add(record.canonical_url)
            records.append(record)
            if record.completeness is ContentCompleteness.FULL:
                metrics.full += 1
                source_metrics["full"] += 1
            elif record.completeness is ContentCompleteness.PARTIAL:
                metrics.partial += 1
                source_metrics["partial"] += 1
            else:
                metrics.metadata_only += 1
                source_metrics["metadata_only"] += 1
        ids = ingest_provider_records(
            repository, source_id=source_id, provider="reddit_rss", query=subreddit,
            records=tuple(records), capabilities=CAPABILITIES,
        )
        acquisition_ids.extend(ids)
        acquired_ids = {
            record.item.external_id for record in records if record.item is not None
        }
        metrics.new_source_items += len(acquired_ids - existing_before)
        metrics.existing_source_items += len(acquired_ids & existing_before)
    metrics.unique_submissions = len(unique_urls)
    metrics.requests = provider.requests
    metrics.latency_ms = provider.latency_ms
    metrics.status = "CONNECTED" if metrics.successful_feeds else "ALL_FEEDS_FAILED"
    return metrics, tuple(acquisition_ids)


def render_report(metrics: RssPocMetrics) -> str:
    return "\n".join((
        "# Reddit RSS PoC",
        "",
        f"Status: **{metrics.status}**",
        "",
        "## Connectivity",
        "",
        f"RSS requests: {metrics.requests}; successful feeds: {metrics.successful_feeds}; "
        f"failed feeds: {metrics.failed_feeds}.",
        f"Latency: {metrics.latency_ms} ms; rate-limited (429) responses: "
        f"{metrics.rate_limited_responses}.",
        f"Per-source detail: {json.dumps(metrics.sources, sort_keys=True)}",
        "",
        "## Completeness",
        "",
        f"Entries returned: {metrics.entries_returned}; unique Reddit submissions: "
        f"{metrics.unique_submissions}; duplicates within this run: {metrics.duplicates}.",
        f"FULL: {metrics.full}; PARTIAL: {metrics.partial}; "
        f"METADATA_ONLY: {metrics.metadata_only}.",
        "FULL requires the Atom feed's self-text body (SC_OFF/md wrapper); link and "
        "image posts with no self-text are METADATA_ONLY, never upgraded or "
        "reconstructed.",
        "",
        "## Ingestion",
        "",
        f"New SourceItems created: {metrics.new_source_items}; SourceItems already "
        f"on file (idempotent re-ingestion): {metrics.existing_source_items}.",
        f"Failures by type: {json.dumps(metrics.failures, sort_keys=True)}",
        "",
        "## Cost",
        "",
        "Reddit data acquisition cost: **€0** (public RSS, no paid provider, no "
        "official API). AI/model processing cost, if any, is tracked separately.",
        "",
    ))


def write_report(metrics: RssPocMetrics, output_directory: Path) -> None:
    output_directory.mkdir(parents=True, exist_ok=True)
    (output_directory / "reddit_rss_poc_metrics.json").write_text(
        json.dumps(asdict(metrics), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output_directory / "reddit_rss_poc.md").write_text(render_report(metrics), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("exports"))
    parser.add_argument("--user-agent", required=True)
    parser.add_argument("--min-request-interval-seconds", type=float, default=90.0)
    parser.add_argument("--page-size", type=int, default=25)
    args = parser.parse_args(argv)

    if RedditRssProvider.readiness is not ProductionReadiness.PRODUCTION_APPROVED:
        print(
            "LIVE RSS RUN = BLOCKED: RedditRssProvider.readiness is "
            f"{RedditRssProvider.readiness.value}, not PRODUCTION_APPROVED. "
            "reddit.com's robots.txt disallows automated access; see "
            "docs/providers/reddit-rss-rights-checklist.md. This refusal has no "
            "--force override; it can only be lifted by changing readiness once "
            "explicit, documented permission exists."
        )
        return 2

    sources = read_live_manifest_csv(args.manifest)
    config = RedditRssConfig(
        user_agent=args.user_agent,
        min_request_interval_seconds=args.min_request_interval_seconds,
    )
    provider = RedditRssProvider(config)
    repository = Repository(args.database)
    repository.initialize()
    try:
        metrics, _ = run_poc(repository, provider, sources, page_size=args.page_size)
    finally:
        repository.close()
    write_report(metrics, args.output)
    return 0 if metrics.status == "CONNECTED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
