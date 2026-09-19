"""Small Brandwatch Reddit connectivity and normalization probe; no raw-text export."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, cast

from .brandwatch import (
    BrandwatchConfig,
    BrandwatchError,
    BrandwatchRedditProvider,
    normalize_brandwatch_reddit_record,
)
from .domain import ContentCompleteness
from .reddit import canonicalize_reddit_url
from .reddit_provider import (
    ProductionReadiness,
    ProviderFailure,
    RedditDataProvider,
    RedditProviderRecord,
)


@dataclass(frozen=True, slots=True)
class PocSource:
    name: str
    query_id: int | None


@dataclass(slots=True)
class PocMetrics:
    status: str = "NOT_RUN"
    recommendation: str = "NOT_ASSESSED_NO_LIVE_DATA"
    readiness: str = ProductionReadiness.CONTRACT_REVIEW_REQUIRED.value
    provider: str = "brandwatch"
    raw_retention: str = "DO_NOT_PERSIST"
    cost: str = "UNKNOWN"
    requests: int = 0
    request_success_rate: float | None = None
    fulltext_requests: int = 0
    mentions_retrieved: int = 0
    items_normalized: int = 0
    items_usable: int = 0
    full: int = 0
    partial: int = 0
    metadata_only: int = 0
    duplicate_records: int = 0
    fulltext_success_rate: float | None = None
    missing_fields: dict[str, int] = field(default_factory=lambda: {})
    sources: dict[str, dict[str, Any]] = field(default_factory=lambda: {})
    comments_seen: int = 0
    failures: dict[str, int] = field(default_factory=lambda: {})
    last_success: str | None = None
    last_failure: str | None = None
    latency_ms: int = 0
    pipeline: str = "NOT_RUN_NO_EXTRACTOR"


def load_manifest(path: Path) -> tuple[PocSource, ...]:
    value: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("manifest must contain sources array")
    root = cast(dict[str, object], value)
    if not isinstance(root.get("sources"), list):
        raise ValueError("manifest must contain sources array")
    sources: list[PocSource] = []
    for raw in cast(list[object], root["sources"]):
        if not isinstance(raw, dict):
            raise ValueError("source entry must be an object")
        row = cast(dict[str, object], raw)
        name, query_id = row.get("name"), row.get("query_id")
        if not isinstance(name, str) or not name.startswith("r/") or not name[2:]:
            raise ValueError("source name must be r/<subreddit>")
        if query_id is not None and (type(query_id) is not int or query_id <= 0):
            raise ValueError("query_id must be a positive integer or null")
        sources.append(PocSource(name, query_id))
    if not sources or len(sources) > 5 or len({s.name.casefold() for s in sources}) != len(sources):
        raise ValueError("PoC needs one to five distinct subreddit sources")
    return tuple(sources)


def run_poc(
    provider: RedditDataProvider,
    sources: Sequence[PocSource],
    *,
    start_date: str,
    end_date: str,
    limit: int = 20,
    per_source_limit: int = 4,
) -> tuple[PocMetrics, tuple[RedditProviderRecord, ...]]:
    if not 10 <= limit <= 20 or not 1 <= per_source_limit <= 20:
        raise ValueError("first PoC must request 10–20 items, max 20 per source")
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except ValueError as exc:
        raise ValueError("PoC dates must be YYYY-MM-DD") from exc
    if start >= end:
        raise ValueError("PoC end date must be after start date")
    if provider.readiness is ProductionReadiness.PRODUCTION_APPROVED:
        raise ValueError("PoC must not mark Brandwatch production-approved")
    metrics = PocMetrics(provider=provider.name)
    unique: dict[str, RedditProviderRecord] = {}
    missing = Counter[str]()
    records: list[RedditProviderRecord] = []
    for source in sources:
        if len(records) >= limit:
            break
        source_metrics: dict[str, Any] = {
            "query_id_configured": source.query_id is not None,
            "mentions": 0,
            "normalized": 0,
            "failure": None,
        }
        metrics.sources[source.name] = source_metrics
        if source.query_id is None:
            source_metrics["failure"] = ProviderFailure.QUERY_CONFIGURATION_ERROR.value
            metrics.failures[ProviderFailure.QUERY_CONFIGURATION_ERROR.value] = (
                metrics.failures.get(ProviderFailure.QUERY_CONFIGURATION_ERROR.value, 0) + 1
            )
            continue
        page = 0
        source_count = 0
        page_size = min(per_source_limit, limit - len(records))
        while source_count < per_source_limit and len(records) < limit and page < 10:
            if int(getattr(provider, "requests", 0)) >= 20:
                source_metrics["failure"] = ProviderFailure.RATE_LIMITED.value
                break
            try:
                discovery = provider.discover(
                    str(source.query_id), start_date, end_date, page_size, page
                )
                if not discovery.records:
                    if page == 0:
                        source_metrics["failure"] = ProviderFailure.NO_RESULTS.value
                    break
            except BrandwatchError as exc:
                source_metrics["failure"] = exc.failure.value
                metrics.failures[exc.failure.value] = metrics.failures.get(exc.failure.value, 0) + 1
                break
            try:
                complete = provider.fetch_fulltext(
                    str(source.query_id), start_date, end_date, page_size, page
                )
                full_records = complete.records
            except BrandwatchError:
                metrics.failures[ProviderFailure.FULLTEXT_UNAVAILABLE.value] = (
                    metrics.failures.get(ProviderFailure.FULLTEXT_UNAVAILABLE.value, 0) + 1
                )
                full_records = ()
            full_by_id = {
                str(row["resourceId"]): row
                for row in full_records if row.get("resourceId") is not None
            }
            for mention in discovery.records:
                metrics.mentions_retrieved += 1
                source_metrics["mentions"] += 1
                fulltext = full_by_id.get(str(mention.get("resourceId")))
                try:
                    normalized = normalize_brandwatch_reddit_record(
                        mention, fulltext,
                        requested_subreddit=source.name,
                        query_id=source.query_id,
                        acquired_at=datetime.now(UTC).isoformat(),
                    )
                except BrandwatchError as exc:
                    metrics.failures[exc.failure.value] = (
                        metrics.failures.get(exc.failure.value, 0) + 1
                    )
                    continue
                identity = (
                    canonicalize_reddit_url(normalized.canonical_url)
                    if normalized.canonical_url else None
                )
                if identity is not None and identity.comment_id:
                    metrics.comments_seen += 1
                dedupe_key = (
                    identity.external_id if identity else
                    f"brandwatch:{normalized.provider_record_id or metrics.mentions_retrieved}"
                )
                if dedupe_key in unique:
                    metrics.duplicate_records += 1
                    continue
                unique[dedupe_key] = normalized
                records.append(normalized)
                source_count += 1
                source_metrics["normalized"] += 1
                missing.update(normalized.missing_fields)
                if normalized.completeness is ContentCompleteness.FULL:
                    metrics.full += 1
                elif normalized.completeness is ContentCompleteness.PARTIAL:
                    metrics.partial += 1
                else:
                    metrics.metadata_only += 1
                if len(records) >= limit or source_count >= per_source_limit:
                    break
            page += 1
            if len(discovery.records) < page_size:
                break
    metrics.items_normalized = len(records)
    metrics.items_usable = sum(
        record.item is not None and len(record.item.raw_text) >= 40
        for record in records
    )
    metrics.missing_fields = dict(sorted(missing.items()))
    metrics.fulltext_success_rate = (
        metrics.full / metrics.items_normalized if metrics.items_normalized else None
    )
    metrics.requests = int(getattr(provider, "requests", 0))
    successful_requests = int(getattr(provider, "successful_requests", 0))
    metrics.request_success_rate = (
        successful_requests / metrics.requests if metrics.requests else None
    )
    metrics.fulltext_requests = int(getattr(provider, "fulltext_requests", 0))
    metrics.last_success = getattr(provider, "last_success", None)
    metrics.last_failure = getattr(provider, "last_failure", None)
    metrics.latency_ms = int(getattr(provider, "latency_ms", 0))
    metrics.status = "CONNECTED" if metrics.mentions_retrieved else "NO_LIVE_RECORDS"
    if metrics.mentions_retrieved:
        metrics.recommendation = (
            "TECHNICALLY_PROMISING_CONTRACT_REVIEW_REQUIRED" if metrics.full
            else "TECHNICALLY_UNSUITABLE"
        )
    return metrics, tuple(records)


def render_report(metrics: PocMetrics) -> str:
    return "\n".join((
        "# Brandwatch Reddit PoC",
        "",
        f"Status: **{metrics.status}**",
        f"Recommendation: **{metrics.recommendation}**",
        f"Production rights: **{metrics.readiness}**",
        "",
        "## Connectivity and coverage",
        "",
        f"Provider requests: {metrics.requests}; mentions retrieved: {metrics.mentions_retrieved}.",
        f"Request success rate: {metrics.request_success_rate}; "
        f"last success: {metrics.last_success}; last failure: {metrics.last_failure}.",
        f"Requested sources and per-source results: {json.dumps(metrics.sources, sort_keys=True)}",
        "Subreddit targeting is checked against each Reddit URL; query configuration "
        "still needs live verification.",
        "",
        "## Completeness and normalization",
        "",
        f"FULL: {metrics.full}; PARTIAL: {metrics.partial}; "
        f"METADATA_ONLY: {metrics.metadata_only}.",
        f"Missing fields: {json.dumps(metrics.missing_fields, sort_keys=True)}",
        f"Normalized: {metrics.items_normalized}; usable (>=40 chars): "
        f"{metrics.items_usable}; duplicates: {metrics.duplicate_records}.",
        f"Fulltext success rate: {metrics.fulltext_success_rate}.",
        f"Comments seen: {metrics.comments_seen}; thread relationship usability "
        "requires live inspection.",
        "Canonical Reddit IDs/URLs are used for cross-provider identity; Brandwatch "
        "record IDs remain provenance only.",
        "",
        "## Pipeline, usage and rights",
        "",
        f"Extraction: {metrics.pipeline}.",
        f"Fulltext requests: {metrics.fulltext_requests}; latency: {metrics.latency_ms} ms; "
        f"monetary cost: {metrics.cost}.",
        f"Failures: {json.dumps(metrics.failures, sort_keys=True)}",
        "Raw text is never persisted in this PoC; metrics reports contain no Reddit text.",
        "Contract review is mandatory before production storage, LLM processing, "
        "embeddings, resale, or customer display.",
        "",
    ))


def write_report(metrics: PocMetrics, output_directory: Path) -> None:
    output_directory.mkdir(parents=True, exist_ok=True)
    (output_directory / "brandwatch_reddit_poc_metrics.json").write_text(
        json.dumps(asdict(metrics), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output_directory / "brandwatch_reddit_poc.md").write_text(
        render_report(metrics), encoding="utf-8"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("docs/providers/brandwatch-poc.json"))
    parser.add_argument("--output", type=Path, default=Path("exports"))
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    args = parser.parse_args(argv)
    sources = load_manifest(args.manifest)
    try:
        config = BrandwatchConfig.from_environment()
    except ValueError:
        metrics = PocMetrics(status="CREDENTIALS_REQUIRED")
        for source in sources:
            metrics.sources[source.name] = {"query_id_configured": source.query_id is not None}
        write_report(metrics, args.output)
        return 2
    provider = BrandwatchRedditProvider(config)
    metrics, _ = run_poc(
        provider, sources, start_date=args.start_date, end_date=args.end_date,
    )
    write_report(metrics, args.output)
    return 0 if metrics.status == "CONNECTED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
