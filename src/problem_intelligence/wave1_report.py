"""Wave 1 acquisition-first report; undefined yield is never rendered as zero yield."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from .prediction_extractor import JsonlPredictionExtractor
from .reddit_reporting import build_reddit_report
from .repository import Repository
from .signal_policy import strong_individual_signal_sql
from .wave1 import WaveSelection, per_thousand

FIELDS: tuple[str, ...] = (
    "source", "category", "target_items", "health_status", "policy_ready",
    "acquisition_eligible",
    "search_requests", "requested_items", "discovered_urls", "unique_urls",
    "duplicates_removed", "full_items", "partial_items", "metadata_only_items",
    "failed_acquisitions", "acquisition_success_rate", "usable_items",
    "items_after_prefilter", "pain_observations", "strong_signals",
    "active_solution_searches", "quantified_impacts", "payment_signals",
    "manual_workaround_signals", "diy_internal_tool_signals", "acquisition_cost_usd",
    "processing_cost_usd", "unknown_cost_records", "latency_ms", "pain_per_1000_usable",
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
        source = repository.connection.execute(
            "SELECT id FROM sources WHERE source_type = 'reddit' AND lower(name) = lower(?)",
            (selected.source,),
        ).fetchone()
        source_id = int(source["id"]) if source is not None else -1
        requested = repository.connection.execute(
            """SELECT COUNT(*) AS run_count, COUNT(requested_items) AS measured_count,
                      COALESCE(SUM(requested_items), 0) AS item_count
               FROM discovery_runs WHERE source_id = ?""",
            (source_id,),
        ).fetchone()
        assert requested is not None
        detail = repository.connection.execute(
            """SELECT
                 (SELECT COUNT(DISTINCT a.source_item_id) FROM acquisition_records a
                  JOIN discovery_records d ON d.id = a.discovery_id
                  JOIN source_items si ON si.id = a.source_item_id
                  WHERE d.source_id = ? AND a.completeness = 'FULL'
                    AND length(si.raw_text) >= 40) AS after_prefilter,
                 (SELECT COUNT(DISTINCT po.id) FROM problem_observations po
                  JOIN source_items si ON si.id = po.source_item_id
                  JOIN workarounds w ON w.observation_id = po.id
                  WHERE si.source_id = ? AND w.workaround_type IN
                    ('SPREADSHEET','CSV','EMAIL','WHATSAPP','PAPER','MANUAL_ENTRY'))
                    AS manual_workarounds,
                 (SELECT COUNT(DISTINCT po.id) FROM problem_observations po
                  JOIN source_items si ON si.id = po.source_item_id
                  JOIN workarounds w ON w.observation_id = po.id
                  WHERE si.source_id = ? AND w.workaround_type IN
                    ('INTERNAL_SCRIPT','CUSTOM_SOFTWARE')) AS diy_tools,
                 (SELECT SUM(a.latency_ms) FROM acquisition_records a
                  JOIN discovery_records d ON d.id = a.discovery_id
                  WHERE d.source_id = ? AND json_extract(a.metadata_json,
                    '$.provider_invocation') = 1) AS acquisition_latency
               """,
            (source_id,) * 4,
        ).fetchone()
        assert detail is not None
        unique = int(result.get("unique_urls", 0))
        full = int(result.get("full", 0))
        requests = int(result.get("search_requests", 0))
        unknown_cost = int(result.get("unknown_cost_records", 0))
        known_cost = float(result.get("known_processing_cost_usd", 0))
        acquisition_cost = known_cost if requests and not unknown_cost else None
        strong = int(result.get("strong_single_signals", 0))
        observations = int(result.get("observations", 0))
        active = int(result.get("active_solution_searches", 0))
        payment = int(result.get("payment_signals", 0))
        rows.append({
            "source": selected.source,
            "category": selected.category,
            "target_items": selected.target_items,
            "health_status": selected.health_status,
            "policy_ready": selected.policy_ready,
            "acquisition_eligible": selected.acquisition_eligible,
            "search_requests": requests,
            "requested_items": (
                int(requested["item_count"])
                if requested["run_count"] == requested["measured_count"]
                else None
            ),
            "discovered_urls": int(result.get("discovered", 0)),
            "unique_urls": unique,
            "duplicates_removed": int(result.get("duplicates_removed", 0)),
            "full_items": full,
            "partial_items": int(result.get("partial", 0)),
            "metadata_only_items": int(result.get("metadata_only", 0)),
            "failed_acquisitions": int(result.get("failed_or_blocked", 0)),
            "acquisition_success_rate": full / unique if unique else None,
            "usable_items": full,
            "items_after_prefilter": int(detail["after_prefilter"]) if full else None,
            "pain_observations": observations if full else None,
            "strong_signals": strong if full else None,
            "active_solution_searches": active if full else None,
            "quantified_impacts": int(result.get("quantified_impacts", 0)) if full else None,
            "payment_signals": payment if full else None,
            "manual_workaround_signals": int(detail["manual_workarounds"]) if full else None,
            "diy_internal_tool_signals": int(detail["diy_tools"]) if full else None,
            "acquisition_cost_usd": acquisition_cost,
            # Model costs cannot be allocated to a community without an exact
            # source-item or single-community run relationship.
            "processing_cost_usd": None,
            "unknown_cost_records": unknown_cost,
            "latency_ms": detail["acquisition_latency"],
            "pain_per_1000_usable": per_thousand(observations, full),
            "strong_per_1000_usable": per_thousand(strong, full),
            "active_per_1000_usable": per_thousand(active, full),
            "payment_per_1000_usable": per_thousand(payment, full),
            "cost_per_strong_signal_usd": None,
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


def _short(value: object, limit: int = 200) -> str:
    normalized = " ".join(str(value or "").split())
    return normalized[:limit] + ("…" if len(normalized) > limit else "")


def build_wave1_review(
    repository: Repository,
    selections: tuple[WaveSelection, ...],
    *,
    predictions: Path | None = None,
) -> str:
    """Top grounded observations and distinct weak/NO_PAIN review strata."""

    full_ids = set(repository.full_reddit_source_item_ids())
    if not full_ids:
        return "No FULL Wave 1 items exist; positive and negative review samples are unavailable."
    negative_ids: set[int] = set()
    if predictions is not None:
        extractor = JsonlPredictionExtractor(predictions, version="wave1-review-v1")
        for item_id, external_id, is_problem in extractor.classification_rows():
            if item_id not in full_ids:
                raise ValueError(f"prediction item {item_id} is not a FULL Reddit capture")
            item = repository.connection.execute(
                "SELECT external_id FROM source_items WHERE id = ?", (item_id,)
            ).fetchone()
            if item is None or item["external_id"] != external_id:
                raise ValueError(f"prediction identity mismatch for item {item_id}")
            if not is_problem:
                negative_ids.add(item_id)
    strong = strong_individual_signal_sql("po")
    lines: list[str] = []
    for selected in selections:
        lines.extend([f"### {selected.source}", ""])
        positives = repository.connection.execute(
            f"""SELECT po.problem, po.actor, po.actor_role, po.context,
                       po.current_workaround, po.time_impact, po.financial_impact,
                       si.url,
                       (SELECT es.excerpt FROM evidence_spans es
                        WHERE es.observation_id = po.id ORDER BY es.id LIMIT 1)
                        AS evidence_excerpt,
                       (SELECT p.payment_type || ': ' || es.excerpt
                        FROM payment_signals p
                        JOIN evidence_spans es ON es.id = p.evidence_span_id
                        WHERE p.observation_id = po.id ORDER BY p.id LIMIT 1)
                        AS payment_evidence,
                       {strong} AS is_strong
                FROM problem_observations po
                JOIN source_items si ON si.id = po.source_item_id
                JOIN sources s ON s.id = si.source_id
                WHERE lower(s.name) = lower(?) AND po.source_item_id IN
                    (SELECT a.source_item_id FROM acquisition_records a
                     WHERE a.completeness = 'FULL')
                ORDER BY is_strong DESC, po.id LIMIT 5""",
            (selected.source,),
        ).fetchall()
        if not positives:
            lines.append("No grounded observations available for review.")
        for row in positives:
            impact_text = _short(row["time_impact"] or row["financial_impact"])
            lines.extend([
                f"- **{'STRONG' if row['is_strong'] else 'WEAK'}:** {_short(row['problem'])}",
                f"  - Actor: {_short(row['actor'] or row['actor_role']) or 'not captured'}; "
                f"workflow/context: {_short(row['context']) or 'not captured'}.",
                f"  - Workaround: {_short(row['current_workaround']) or 'not captured'}; "
                f"impact: {impact_text or 'not captured'}; "
                f"payment evidence: {_short(row['payment_evidence']) or 'not captured'}.",
                f"  - Source: {row['url'] or 'URL missing'}; "
                f"evidence span: {_short(row['evidence_excerpt']) or 'MISSING'}.",
            ])
        lines.extend(["", "Weak / rejected review sample:"])
        weak = repository.connection.execute(
            f"""SELECT po.problem, si.url FROM problem_observations po
                JOIN source_items si ON si.id = po.source_item_id
                JOIN sources s ON s.id = si.source_id
                WHERE lower(s.name) = lower(?) AND COALESCE({strong}, 0) = 0
                  AND po.source_item_id IN
                    (SELECT a.source_item_id FROM acquisition_records a
                     WHERE a.completeness = 'FULL')
                ORDER BY po.id LIMIT 3""",
            (selected.source,),
        ).fetchall()
        if weak:
            lines.extend(
                f"- WEAK: {_short(row['problem'])} — {row['url'] or 'URL missing'}"
                for row in weak
            )
        else:
            lines.append("- No weak observations in the top-five sample.")
        lines.append("- REJECTED: no explicit rejection decisions are persisted; unmeasured.")
        lines.append("NO_PAIN review sample:")
        if predictions is None:
            lines.append("- Prediction capture not supplied; NO_PAIN unmeasured.")
        else:
            negative_rows = repository.connection.execute(
                """SELECT si.id, si.url, si.raw_text FROM source_items si
                   JOIN sources s ON s.id = si.source_id
                   WHERE lower(s.name) = lower(?) ORDER BY si.id""",
                (selected.source,),
            ).fetchall()
            matches = [row for row in negative_rows if int(row["id"]) in negative_ids][:3]
            if not matches:
                lines.append("- No labeled NO_PAIN items for this community.")
            for row in matches:
                lines.append(
                    f"- NO_PAIN: {_short(row['raw_text'])} — {row['url'] or 'URL missing'}"
                )
        lines.append("")
    return "\n".join(lines).rstrip()


def write_wave1_report(
    path: Path,
    rows: tuple[dict[str, Any], ...],
    *,
    review: str | None = None,
) -> None:
    full = sum(int(row["full_items"]) for row in rows)
    unique = sum(int(row["unique_urls"]) for row in rows)
    active = sum(bool(row["acquisition_eligible"]) for row in rows)
    health_active = sum(row["health_status"] == "ACTIVE" for row in rows)
    policy_ready = sum(bool(row["policy_ready"]) for row in rows)
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
        f"- Planned communities: {len(rows)}; ACTIVE health: {health_active}; "
        f"policy-ready: {policy_ready}; acquisition-eligible: {active}.",
        f"- Unique URLs captured in the Wave 1 database: {unique}.",
        f"- Provider-attested FULL items: {full}. Target: approximately 2,500–3,500.",
        "- No official Reddit API, bypass, proxy rotation, or private endpoint was used.",
        "- Source-policy readiness is an independent gate: `REVIEW_REQUIRED` does not "
        "authorize bulk acquisition. A provider's permitted use and retention rules "
        "must be documented before execution.",
        "- `target_items` is the planned sample size; actual requested-item counts are "
        "reported only when every provider search request records its requested count.",
        "",
        "## Completeness and research quality",
        "",
        (
            "FULL requires a provider body-complete attestation and retrieval timestamp; "
            "a search snippet is not FULL. "
            "With no full items, usable-item rates, community yield, extraction precision, "
            "and false-negative rates are unknown—not zero."
            if preflight else
            "FULL content counts alone do not establish extraction precision or evidence "
            "quality; review both positive and rejected samples before assessing yield."
        ),
        "",
        "## Cost",
        "",
        "Acquisition cost is shown separately in the metrics CSV when provider records "
        "are complete. Model/analysis cost has no exact per-community attribution, so "
        "processing cost and cost per strong signal remain unknown—not $0.",
        "",
        "## Human review and false positives",
        "",
        review or "A complete human-review package needs top observations plus NO_PAIN and "
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
