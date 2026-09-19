"""Wave 1 acquisition-first report; undefined yield is never rendered as zero yield."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from .reddit_reporting import build_reddit_report
from .repository import Repository
from .wave1 import WaveSelection, cost_per_strong_signal, per_thousand

FIELDS: tuple[str, ...] = (
    "source", "category", "target_items", "health_status", "acquisition_eligible",
    "search_requests", "requested_items", "discovered_urls", "unique_urls",
    "duplicates_removed", "full_items", "partial_items", "metadata_only_items",
    "failed_acquisitions", "acquisition_success_rate", "usable_items",
    "items_after_prefilter", "pain_observations", "strong_signals",
    "active_solution_searches", "quantified_impacts", "payment_signals",
    "manual_workaround_signals", "diy_internal_tool_signals", "processing_cost_usd",
    "unknown_cost_records", "latency_ms", "pain_per_1000_usable",
    "strong_per_1000_usable", "active_per_1000_usable",
    "payment_per_1000_usable", "cost_per_strong_signal_usd",
    "research_quality", "sample_size_usable",
)


def wave1_rows(
    repository: Repository, selections: tuple[WaveSelection, ...]
) -> tuple[dict[str, Any], ...]:
    by_source = {
        str(row["community"]).casefold(): row
        for row in build_reddit_report(repository).data["communities"]
    }
    rows: list[dict[str, Any]] = []
    for selected in selections:
        result = by_source.get(selected.source.casefold(), {})
        unique = int(result.get("unique_urls", 0))
        full = int(result.get("full", 0))
        requests = int(result.get("search_requests", 0))
        unknown_cost = int(result.get("unknown_cost_records", 0))
        known_cost = float(result.get("known_processing_cost_usd", 0))
        cost = known_cost if requests and not unknown_cost else None
        strong = int(result.get("strong_single_signals", 0))
        observations = int(result.get("observations", 0))
        active = int(result.get("active_solution_searches", 0))
        payment = int(result.get("payment_signals", 0))
        rows.append({
            "source": selected.source,
            "category": selected.category,
            "target_items": selected.target_items,
            "health_status": selected.health_status,
            "acquisition_eligible": selected.acquisition_eligible,
            "search_requests": requests,
            "requested_items": 0 if requests == 0 else selected.target_items,
            "discovered_urls": int(result.get("discovered", 0)),
            "unique_urls": unique,
            "duplicates_removed": int(result.get("duplicates_removed", 0)),
            "full_items": full,
            "partial_items": int(result.get("partial", 0)),
            "metadata_only_items": int(result.get("metadata_only", 0)),
            "failed_acquisitions": int(result.get("failed_or_blocked", 0)),
            "acquisition_success_rate": full / unique if unique else None,
            "usable_items": full,
            "items_after_prefilter": (
                min(full, int(result.get("eligible_items", 0))) if full else None
            ),
            "pain_observations": observations if full else None,
            "strong_signals": strong if full else None,
            "active_solution_searches": active if full else None,
            "quantified_impacts": int(result.get("quantified_impacts", 0)) if full else None,
            "payment_signals": payment if full else None,
            "manual_workaround_signals": None,
            "diy_internal_tool_signals": None,
            "processing_cost_usd": cost,
            "unknown_cost_records": unknown_cost,
            "latency_ms": None,
            "pain_per_1000_usable": per_thousand(observations, full),
            "strong_per_1000_usable": per_thousand(strong, full),
            "active_per_1000_usable": per_thousand(active, full),
            "payment_per_1000_usable": per_thousand(payment, full),
            "cost_per_strong_signal_usd": cost_per_strong_signal(cost, strong),
            "research_quality": "UNMEASURED" if full == 0 else "DESCRIPTIVE_ONLY",
            "sample_size_usable": full,
        })
    return tuple(rows)


def write_wave1_metrics(path: Path, rows: tuple[dict[str, Any], ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def write_wave1_report(path: Path, rows: tuple[dict[str, Any], ...]) -> None:
    full = sum(int(row["full_items"]) for row in rows)
    unique = sum(int(row["unique_urls"]) for row in rows)
    active = sum(bool(row["acquisition_eligible"]) for row in rows)
    preflight = full == 0
    lines = [
        "# Reddit Wave 1 — operational validation",
        "",
        (
            "Status: **FIX_AND_RETRY**. This is a preflight report, not a completed "
            "2,500–3,500-item pilot."
            if preflight else
            "Status: **IN_PROGRESS**. Captured items still require completeness, yield, "
            "evidence-grounding, and cost review before any scale recommendation."
        ),
        "",
        "## Acquisition",
        "",
        f"- Planned communities: {len(rows)}; health-confirmed and acquisition-eligible: {active}.",
        f"- Unique URLs captured in the Wave 1 database: {unique}.",
        f"- Verified FULL items: {full}. Target: approximately 2,500–3,500.",
        "- No official Reddit API, bypass, proxy rotation, or private endpoint was used.",
        "",
        "## Completeness and research quality",
        "",
        (
            "FULL means verified complete public post content; a search snippet is not FULL. "
            "With no full items, usable-item rates, community yield, extraction precision, "
            "and false-negative rates are unknown—not zero."
            if preflight else
            "FULL content counts alone do not establish extraction precision or evidence "
            "quality; review both positive and rejected samples before assessing yield."
        ),
        "",
        "## Cost",
        "",
        "Unknown provider or model cost is not represented as $0; consult the metrics CSV "
        "for per-source known and unknown cost records.",
        "",
        "## Human review and false positives",
        "",
        "A complete human-review package needs top observations plus NO_PAIN and "
        "WEAK/REJECTED samples. It has not been completed for this run.",
        "",
        "## Failure and recommendation",
        "",
        (
            "Direct ordinary public HTTP retrieval returned 403 for a sampled Reddit post "
            "on 2026-09-19. Browser-based viewing confirmed individual public content can "
            "sometimes be visible, but this is not a reproducible 100–150-item-per-community "
            "acquisition path. The probe is recorded in "
            "`data/reddit/health_wave_1_http_probe_2026-09-19.jsonl`. Do not infer poor "
            "community relevance from connector failure."
            if preflight else
            "Do not infer poor community relevance from connector failures or incomplete "
            "content. Assess acquisition and research quality separately."
        ),
        "",
        "Recommendation: **FIX_AND_RETRY** until a permitted, reproducible public "
        "discovery and full-content provider has measured latency, cost, and rights, and "
        "human review confirms extraction quality. Do not automatically expand to Wave 2 "
        "or the 319-source manifest.",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
