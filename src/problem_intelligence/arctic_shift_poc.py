"""Small, real Arctic Shift connectivity/completeness/freshness probe.

Arctic Shift's own robots.txt explicitly permits automated access
(`Disallow:` empty for `User-agent: *`), verified live 2026-09-19 -- unlike
direct reddit.com access. Requests go only to arctic-shift.photon-reddit.com;
this script never falls back to reddit.com for content Arctic Shift lacks.

Persists its results: this PoC's technical validation and usage-rights status
are tracked separately (see docs/providers/arctic-shift-rights-checklist.md).
Acquired content becomes real research data through the same canonical
ingestion boundary every other provider uses, gated the same way (rights
review required before broader production use).
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .arctic_shift import (
    ArcticShiftConfig,
    ArcticShiftError,
    ArcticShiftRedditProvider,
    is_removed_or_deleted,
    normalize_arctic_shift_record,
    removal_state,
)
from .domain import ContentCompleteness
from .live_pilot import LiveManifestEntry, read_live_manifest_csv
from .reddit import ingest_provider_records
from .reddit_provider import RedditProviderRecord
from .repository import Repository

CAPABILITIES: dict[str, Any] = {
    "supports_reddit": True,
    "supports_subreddit_filter": True,
    "supports_date_filter": True,
    "supports_pagination": True,
    "supports_fulltext": True,
    "supports_comments": False,
    "supports_historical_data": True,
    "supports_incremental_fetch": True,
}


@dataclass(slots=True)
class ArcticShiftPocMetrics:
    status: str = "NOT_RUN"
    technical_status: str = "UNVALIDATED"
    usage_rights: str = "REVIEW_REQUIRED"
    requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    records_received: int = 0
    records_normalized: int = 0
    full: int = 0
    partial: int = 0
    metadata_only: int = 0
    removed_or_deleted_excluded: int = 0
    removed_excluded: int = 0
    deleted_excluded: int = 0
    usable_records: int = 0
    new_source_items: int = 0
    existing_source_items: int = 0
    latency_ms: int = 0
    failures: dict[str, int] = field(default_factory=lambda: {})
    sources: dict[str, dict[str, Any]] = field(default_factory=lambda: {})
    freshness: dict[str, dict[str, Any]] = field(default_factory=lambda: {})


def run_poc(
    repository: Repository,
    provider: ArcticShiftRedditProvider,
    sources: tuple[LiveManifestEntry, ...],
    *,
    per_source_limit: int,
    start_date: str = "",
    end_date: str = "",
) -> tuple[ArcticShiftPocMetrics, tuple[int, ...]]:
    if not sources:
        raise ValueError("PoC requires at least one source")
    metrics = ArcticShiftPocMetrics()
    acquisition_ids: list[int] = []
    poc_started_at = datetime.now(UTC)
    for entry in sources:
        subreddit = entry.subreddit.removeprefix("r/")
        source_metrics: dict[str, Any] = {
            "records_returned": 0, "full": 0, "partial": 0, "metadata_only": 0,
            "removed_or_deleted_excluded": 0, "removed_excluded": 0, "deleted_excluded": 0,
            "failure": None,
            "requested_time_window": {"after": start_date or None, "before": end_date or None},
            "records_requested": per_source_limit,
        }
        metrics.sources[entry.subreddit] = source_metrics
        try:
            discovery = provider.discover(subreddit, start_date, end_date, per_source_limit, 0)
            fulltext = provider.fetch_fulltext(
                subreddit, start_date, end_date, per_source_limit, 0
            )
        except ArcticShiftError as exc:
            source_metrics["failure"] = exc.failure.value
            metrics.failures[exc.failure.value] = metrics.failures.get(exc.failure.value, 0) + 1
            metrics.failed_requests += 1
            continue
        del discovery
        source_id = repository.upsert_source(
            source_type="reddit", name=entry.subreddit,
            access_method="archive:arctic_shift", commercial_use_status="REVIEW_REQUIRED",
        )
        existing_before = {
            str(row["external_id"]) for row in repository.connection.execute(
                "SELECT external_id FROM source_items WHERE source_id = ?", (source_id,),
            ).fetchall()
        }
        records: list[RedditProviderRecord] = []
        newest: str | None = None
        oldest: str | None = None
        for raw in fulltext.records:
            metrics.records_received += 1
            source_metrics["records_returned"] += 1
            if is_removed_or_deleted(raw):
                metrics.removed_or_deleted_excluded += 1
                source_metrics["removed_or_deleted_excluded"] += 1
                state = removal_state(raw)
                if state == "REMOVED":
                    metrics.removed_excluded += 1
                    source_metrics["removed_excluded"] += 1
                elif state == "DELETED":
                    metrics.deleted_excluded += 1
                    source_metrics["deleted_excluded"] += 1
            created_utc = raw.get("created_utc")
            if isinstance(created_utc, (int, float)) and not isinstance(created_utc, bool):
                published = datetime.fromtimestamp(float(created_utc), tz=UTC).isoformat()
                if newest is None or published > newest:
                    newest = published
                if oldest is None or published < oldest:
                    oldest = published
            try:
                record = normalize_arctic_shift_record(
                    raw, requested_subreddit=subreddit,
                    acquired_at=datetime.now(UTC).isoformat(),
                )
            except ArcticShiftError as exc:
                metrics.failures[exc.failure.value] = (
                    metrics.failures.get(exc.failure.value, 0) + 1
                )
                continue
            metrics.records_normalized += 1
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
        if newest is not None:
            age_seconds = (poc_started_at - datetime.fromisoformat(newest)).total_seconds()
            metrics.freshness[entry.subreddit] = {
                "newest_available_post": newest, "oldest_in_sample": oldest,
                "poc_retrieval_timestamp": poc_started_at.isoformat(),
                "age_of_newest_post_seconds": age_seconds,
            }
        ids = ingest_provider_records(
            repository, source_id=source_id, provider="arctic_shift", query=subreddit,
            records=tuple(records), capabilities=CAPABILITIES,
        )
        acquisition_ids.extend(ids)
        acquired_ids = {
            record.item.external_id for record in records if record.item is not None
        }
        metrics.new_source_items += len(acquired_ids - existing_before)
        metrics.existing_source_items += len(acquired_ids & existing_before)
    metrics.usable_records = metrics.full
    metrics.requests = provider.requests
    metrics.successful_requests = provider.successful_requests
    metrics.latency_ms = provider.latency_ms
    metrics.status = "CONNECTED" if metrics.successful_requests else "ALL_REQUESTS_FAILED"
    metrics.technical_status = "VALIDATED" if metrics.successful_requests else "UNVALIDATED"
    return metrics, tuple(acquisition_ids)


def render_report(metrics: ArcticShiftPocMetrics) -> str:
    return "\n".join((
        "# Arctic Shift Reddit PoC",
        "",
        f"Status: **{metrics.status}**. Technical status: "
        f"**{metrics.technical_status}**. Usage rights: **{metrics.usage_rights}**.",
        "",
        "## Connectivity",
        "",
        f"Requests: {metrics.requests}; successful: {metrics.successful_requests}; "
        f"failed: {metrics.failed_requests}. Latency: {metrics.latency_ms} ms.",
        f"Per-source detail: {json.dumps(metrics.sources, sort_keys=True)}",
        "",
        "## Freshness",
        "",
        f"{json.dumps(metrics.freshness, sort_keys=True)}",
        "",
        "## Completeness",
        "",
        f"Records received: {metrics.records_received}; normalized: "
        f"{metrics.records_normalized}.",
        f"FULL: {metrics.full}; PARTIAL: {metrics.partial}; "
        f"METADATA_ONLY: {metrics.metadata_only}.",
        f"Removed/deleted records excluded from the research run: "
        f"{metrics.removed_or_deleted_excluded} (REMOVED: {metrics.removed_excluded}; "
        f"DELETED: {metrics.deleted_excluded}).",
        "",
        "## Ingestion",
        "",
        f"New SourceItems: {metrics.new_source_items}; already on file: "
        f"{metrics.existing_source_items}.",
        f"Failures by type: {json.dumps(metrics.failures, sort_keys=True)}",
        "",
        "## Cost",
        "",
        "Data acquisition cost: **€0**. No credentials required.",
        "",
    ))


def write_report(metrics: ArcticShiftPocMetrics, output_directory: Path) -> None:
    output_directory.mkdir(parents=True, exist_ok=True)
    (output_directory / "arctic_shift_reddit_poc_metrics.json").write_text(
        json.dumps(asdict(metrics), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output_directory / "arctic_shift_reddit_poc.md").write_text(
        render_report(metrics), encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("exports"))
    parser.add_argument("--user-agent", required=True)
    parser.add_argument("--min-request-interval-seconds", type=float, default=3.0)
    parser.add_argument("--per-source-limit", type=int, default=4)
    parser.add_argument("--start-date", default="", help="after (YYYY-MM-DD), empty = unbounded")
    parser.add_argument("--end-date", default="", help="before (YYYY-MM-DD), empty = unbounded")
    args = parser.parse_args(argv)

    sources = read_live_manifest_csv(args.manifest)
    config = ArcticShiftConfig(
        user_agent=args.user_agent,
        min_request_interval_seconds=args.min_request_interval_seconds,
    )
    provider = ArcticShiftRedditProvider(config)
    repository = Repository(args.database)
    repository.initialize()
    try:
        metrics, _ = run_poc(
            repository, provider, sources, per_source_limit=args.per_source_limit,
            start_date=args.start_date, end_date=args.end_date,
        )
    finally:
        repository.close()
    write_report(metrics, args.output)
    return 0 if metrics.status == "CONNECTED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
