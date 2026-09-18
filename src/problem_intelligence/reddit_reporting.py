"""Operational JSON/Markdown reporting for Reddit source experiments."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .repository import Repository
from .signal_policy import strong_individual_signal_sql


@dataclass(frozen=True, slots=True)
class RedditReport:
    data: dict[str, Any]

    def to_json(self) -> str:
        return json.dumps(self.data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"

    def to_markdown(self) -> str:
        summary = self.data["summary"]
        lines = [
            "# Reddit source experiment",
            "",
            "This report separates discovery from content acquisition. Partial captures are not "
            "reported as complete threads, and metadata-only or failed captures are not eligible "
            "for extraction.",
            "",
            "## Summary",
            "",
            f"- Search requests: {summary['search_requests']}",
            f"- Provider results: {summary['provider_results']}",
            f"- Reddit URLs discovered: {summary['reddit_urls_discovered']}",
            f"- Unique canonical URLs: {summary['unique_canonical_urls']}",
            f"- Duplicate discoveries removed: {summary['duplicate_discoveries_removed']}",
            f"- Acquired content records: {summary['acquired_records']}",
            f"- Extraction-eligible items: {summary['extraction_eligible_items']}",
            f"- Structured observations: {summary['observations']}",
            f"- Known processing cost (USD): {summary['known_cost_usd']:.4f}",
            f"- Requests/attempts with unknown cost: {summary['unknown_cost_records']}",
            "",
            "## Per-community metrics",
            "",
            "| Community | Requests | Availability | Discovered | Unique | Duplicates | Acquired | "
            "Full | Partial | Metadata | Failed | After prefilter | Observations | Active | "
            "Quantified | Payment | Strong | Cost | Errors |",
            "|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for row in self.data["communities"]:
            availability = ", ".join(
                f"{key}:{value}" for key, value in row["availability"].items() if value
            )
            lines.append(
                f"| {row['community']} | {row['search_requests']} | {availability or 'none'} | "
                f"{row['discovered']} | {row['unique_urls']} | {row['duplicates_removed']} | "
                f"{row['items_acquired']} | {row['full']} | "
                f"{row['partial']} | {row['metadata_only']} | {row['failed_or_blocked']} | "
                f"{row['eligible_items']} | "
                f"{row['observations']} | {row['active_solution_searches']} | "
                f"{row['quantified_impacts']} | {row['payment_signals']} | "
                f"{row['strong_single_signals']} | {_cost_label(row)} | "
                f"{row['error_count']} |"
            )
        lines.extend(
            [
                "",
                "Strong single signals require a clear actor and job, context or a documented "
                "workaround, and quantified impact, payment evidence, active solution search, "
                "or switching intent. They are leads, not validated opportunities.",
                "",
                "### Normalized source performance",
                "",
                "| Community | Sample items | Observations/1k | Strong/1k | Active/1k | "
                "Payment/1k | Processing cost/1k USD | Sample warning |",
                "|---|---:|---:|---:|---:|---:|---:|---|",
            ]
        )
        for row in self.data["communities"]:
            normalized_cost = row["processing_cost_per_1000_items_usd"]
            cost_text = "unknown" if normalized_cost is None else f"{normalized_cost:.4f}"
            lines.append(
                f"| {row['community']} | {row['sample_size_items']} | "
                f"{row['observations_per_1000_items']:.1f} | "
                f"{row['strong_signals_per_1000_items']:.1f} | "
                f"{row['active_searches_per_1000_items']:.1f} | "
                f"{row['payment_signals_per_1000_items']:.1f} | {cost_text} | "
                f"{row['sample_warning'] or 'none'} |"
            )
        lines.extend(
            [
                "",
                "## Provider performance",
                "",
                "| Provider | Role | Requests | Results | Reddit URLs | Unique URLs | Success | "
                "Full | Partial | Failure | Latency | Cost | Capabilities |",
                "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|",
            ]
        )
        for row in self.data["providers"]:
            caps = ", ".join(key for key, enabled in row["capabilities"].items() if enabled)
            lines.append(
                f"| {row['provider']} | {row['role']} | {row['requests']} | "
                f"{row['results_returned']} | {row['reddit_urls_discovered']} | "
                f"{row['unique_urls']} | {_rate(row['success_rate'])} | "
                f"{_rate(row['full_content_rate'])} | {_rate(row['partial_content_rate'])} | "
                f"{_rate(row['failure_rate'])} | {_metric_label(row, 'latency_ms')} | "
                f"{_metric_label(row, 'known_cost_usd', decimals=4)} | "
                f"{caps or 'none recorded'} |"
            )
        lines.extend(["", "## Observed examples", ""])
        samples = self.data["samples"]
        if not samples:
            lines.append("No structured observations were produced.")
        for sample in samples:
            lines.extend(
                [
                    f"### {sample['community']}: {sample['problem']}",
                    "",
                    f"> {sample['excerpt']}",
                    "",
                    f"Source: {sample['url']}",
                    "",
                ]
            )
        lines.extend(["## Errors and unavailable inputs", ""])
        errors = self.data["errors"]
        if not errors:
            lines.append("None recorded.")
        else:
            lines.extend(f"- {item}" for item in errors)
        assessment = self.data["assessment"]
        lines.extend(
            [
                "",
                "## What worked",
                "",
                *[f"- {item}" for item in assessment["worked"]],
                "",
                "## What failed or remains limited",
                "",
                *[f"- {item}" for item in assessment["limitations"]],
                "",
                "## Next technical blocker",
                "",
                assessment["next_technical_blocker"],
            ]
        )
        return "\n".join(lines).rstrip() + "\n"


def build_reddit_report(repository: Repository) -> RedditReport:
    connection = repository.connection
    community_rows = connection.execute(
        """SELECT id, name FROM sources AS s
           WHERE source_type = 'reddit'
             AND EXISTS (
                 SELECT 1 FROM discovery_runs AS dr WHERE dr.source_id = s.id
             )
           ORDER BY id"""
    ).fetchall()
    communities: list[dict[str, Any]] = []
    for source in community_rows:
        source_id = int(source["id"])
        availability_rows = connection.execute(
            """SELECT availability, COUNT(*) AS count FROM discovery_runs
               WHERE source_id = ? GROUP BY availability""",
            (source_id,),
        ).fetchall()
        availability = {"RESULTS": 0, "NO_RESULTS": 0, "SOURCE_UNAVAILABLE": 0}
        for row in availability_rows:
            availability[str(row["availability"])] = int(row["count"])
        strong_signal = strong_individual_signal_sql("po")
        completed_run = "(po.pipeline_run_id IS NULL OR pr.status = 'COMPLETED')"
        metrics = connection.execute(
            f"""SELECT
                 (SELECT COUNT(*) FROM discovery_runs WHERE source_id = ?) AS requests,
                 (SELECT COALESCE(SUM(reddit_urls_discovered), 0) FROM discovery_runs
                    WHERE source_id = ?) AS discovered,
                 (SELECT COUNT(DISTINCT canonical_url) FROM discovery_records
                    WHERE source_id = ?) AS unique_urls,
                 (SELECT COUNT(DISTINCT d.canonical_url) FROM acquisition_records AS a
                    JOIN discovery_records AS d ON d.id = a.discovery_id
                    WHERE d.source_id = ? AND a.completeness = 'FULL') AS full_count,
                 (SELECT COUNT(DISTINCT d.canonical_url) FROM acquisition_records AS a
                    JOIN discovery_records AS d ON d.id = a.discovery_id
                    WHERE d.source_id = ? AND a.completeness = 'PARTIAL') AS partial_count,
                 (SELECT COUNT(*) FROM acquisition_records AS a
                    JOIN discovery_records AS d ON d.id = a.discovery_id
                    WHERE d.source_id = ?
                      AND a.state IN ('ACQUISITION_FAILED','POLICY_BLOCKED')) AS failed_count,
                 (SELECT COUNT(DISTINCT a.source_item_id) FROM acquisition_records AS a
                    JOIN discovery_records AS d ON d.id = a.discovery_id
                    JOIN source_items AS si ON si.id = a.source_item_id
                    WHERE d.source_id = ? AND a.completeness IN ('FULL','PARTIAL')
                      AND length(si.raw_text) >= 40) AS eligible,
                 (SELECT COUNT(*) FROM problem_observations AS po
                    JOIN source_items AS si ON si.id = po.source_item_id
                    LEFT JOIN pipeline_runs AS pr ON pr.id = po.pipeline_run_id
                    WHERE si.source_id = ? AND {completed_run}) AS observations,
                 (SELECT COUNT(*) FROM problem_observations AS po
                    JOIN source_items AS si ON si.id = po.source_item_id
                    LEFT JOIN pipeline_runs AS pr ON pr.id = po.pipeline_run_id
                    WHERE si.source_id = ? AND po.active_solution_search = 1
                      AND {completed_run}) AS active_searches,
                 (SELECT COUNT(*) FROM impact_signals AS impact
                    JOIN problem_observations AS po ON po.id = impact.observation_id
                    JOIN source_items AS si ON si.id = po.source_item_id
                    LEFT JOIN pipeline_runs AS pr ON pr.id = po.pipeline_run_id
                    WHERE si.source_id = ? AND impact.quantified = 1
                      AND {completed_run}) AS quantified_impacts,
                 (SELECT COUNT(*) FROM payment_signals AS payment
                    JOIN problem_observations AS po ON po.id = payment.observation_id
                    JOIN source_items AS si ON si.id = po.source_item_id
                    LEFT JOIN pipeline_runs AS pr ON pr.id = po.pipeline_run_id
                    WHERE si.source_id = ? AND {completed_run}) AS payment_signals,
                 (SELECT COUNT(*) FROM problem_observations AS po
                    JOIN source_items AS si ON si.id = po.source_item_id
                    LEFT JOIN pipeline_runs AS pr ON pr.id = po.pipeline_run_id
                    WHERE si.source_id = ? AND {strong_signal}
                      AND {completed_run}) AS strong_count""",
            (source_id,) * 12,
        ).fetchone()
        assert metrics is not None
        unique_urls = int(metrics["unique_urls"])
        observations = int(metrics["observations"])
        operations = connection.execute(
            """SELECT
                 (SELECT COUNT(DISTINCT a.source_item_id) FROM acquisition_records AS a
                    JOIN discovery_records AS d ON d.id = a.discovery_id
                    WHERE d.source_id = ? AND a.source_item_id IS NOT NULL) AS acquired,
                 (SELECT COUNT(DISTINCT d.canonical_url) FROM acquisition_records AS a
                    JOIN discovery_records AS d ON d.id = a.discovery_id
                    WHERE d.source_id = ? AND a.completeness = 'METADATA_ONLY') AS metadata_only,
                 (SELECT COALESCE(SUM(cost_usd), 0) FROM discovery_runs
                    WHERE source_id = ?) +
                 (SELECT COALESCE(SUM(a.cost_usd), 0) FROM acquisition_records AS a
                    JOIN discovery_records AS d ON d.id = a.discovery_id
                    WHERE d.source_id = ?) AS known_cost,
                 (SELECT COUNT(*) FROM discovery_runs
                    WHERE source_id = ? AND cost_usd IS NULL) +
                 (SELECT COUNT(*) FROM acquisition_records AS a
                    JOIN discovery_records AS d ON d.id = a.discovery_id
                    WHERE d.source_id = ? AND a.cost_usd IS NULL) AS unknown_cost,
                 (SELECT COUNT(*) FROM discovery_runs
                    WHERE source_id = ? AND (
                      availability = 'SOURCE_UNAVAILABLE' OR error IS NOT NULL)) +
                 (SELECT COUNT(*) FROM acquisition_records AS a
                    JOIN discovery_records AS d ON d.id = a.discovery_id
                    WHERE d.source_id = ? AND (
                      a.state IN ('ACQUISITION_FAILED','POLICY_BLOCKED')
                      OR a.error IS NOT NULL)) AS error_count""",
            (source_id,) * 8,
        ).fetchone()
        assert operations is not None
        strong = int(metrics["strong_count"])
        active = int(metrics["active_searches"])
        payment = int(metrics["payment_signals"])
        known_cost = float(operations["known_cost"])
        unknown_cost = int(operations["unknown_cost"])

        communities.append(
            {
                "community": str(source["name"]),
                "search_requests": int(metrics["requests"]),
                "availability": availability,
                "discovered": int(metrics["discovered"]),
                "unique_urls": unique_urls,
                "duplicates_removed": int(metrics["discovered"]) - unique_urls,
                "items_acquired": int(operations["acquired"]),
                "full": int(metrics["full_count"]),
                "partial": int(metrics["partial_count"]),
                "metadata_only": int(operations["metadata_only"]),
                "failed_or_blocked": int(metrics["failed_count"]),
                "eligible_items": int(metrics["eligible"]),
                "observations": observations,
                "active_solution_searches": active,
                "quantified_impacts": int(metrics["quantified_impacts"]),
                "payment_signals": payment,
                "strong_single_signals": strong,
                "known_processing_cost_usd": known_cost,
                "unknown_cost_records": unknown_cost,
                "error_count": int(operations["error_count"]),
                "sample_size_items": unique_urls,
                "sample_warning": (
                    "tiny sample; rates are descriptive only" if unique_urls < 100 else None
                ),
                "observations_per_1000_items": _per_thousand(observations, unique_urls),
                "strong_signals_per_1000_items": _per_thousand(strong, unique_urls),
                "active_searches_per_1000_items": _per_thousand(active, unique_urls),
                "payment_signals_per_1000_items": _per_thousand(payment, unique_urls),
                "processing_cost_per_1000_items_usd": (
                    None if unknown_cost else _per_thousand(known_cost, unique_urls)
                ),
            }
        )

    providers = _provider_rows(repository)
    totals = connection.execute(
        """SELECT
             COALESCE(SUM(search_requests), 0) AS requests,
             COALESCE(SUM(results_returned), 0) AS results,
             COALESCE(SUM(reddit_urls_discovered), 0) AS reddit_urls,
             COALESCE(SUM(cost_usd), 0) AS discovery_cost,
             COALESCE(SUM(cost_usd IS NULL), 0) AS unknown_cost
           FROM discovery_runs"""
    ).fetchone()
    acquisition = connection.execute(
        """SELECT COUNT(*) AS count, COALESCE(SUM(cost_usd), 0) AS cost,
                  COALESCE(SUM(cost_usd IS NULL), 0) AS unknown_cost
           FROM acquisition_records"""
    ).fetchone()
    assert totals is not None and acquisition is not None
    unique_urls = int(
        connection.execute(
            "SELECT COUNT(DISTINCT canonical_url) FROM discovery_records"
        ).fetchone()[0]
    )
    summary = {
        "search_requests": int(totals["requests"]),
        "provider_results": int(totals["results"]),
        "reddit_urls_discovered": int(totals["reddit_urls"]),
        "unique_canonical_urls": unique_urls,
        "duplicate_discoveries_removed": int(totals["reddit_urls"]) - unique_urls,
        "acquired_records": int(acquisition["count"]),
        "extraction_eligible_items": len(repository.extraction_eligible_source_item_ids()),
        "observations": int(
            connection.execute(
                """SELECT COUNT(*) FROM problem_observations AS po
                   JOIN source_items AS si ON si.id = po.source_item_id
                   JOIN sources AS s ON s.id = si.source_id
                   WHERE s.source_type = 'reddit'"""
            ).fetchone()[0]
        ),
        "known_cost_usd": float(totals["discovery_cost"]) + float(acquisition["cost"]),
        "unknown_cost_records": int(totals["unknown_cost"])
        + int(acquisition["unknown_cost"]),
    }
    samples = [dict(row) for row in connection.execute(
        """SELECT s.name AS community, po.problem, es.excerpt, si.url
           FROM problem_observations AS po
           JOIN source_items AS si ON si.id = po.source_item_id
           JOIN sources AS s ON s.id = si.source_id
           JOIN evidence_spans AS es ON es.observation_id = po.id
           WHERE s.source_type = 'reddit'
           ORDER BY (po.time_impact IS NOT NULL OR po.financial_impact IS NOT NULL
                     OR po.active_solution_search = 1) DESC, po.id
           LIMIT 10"""
    ).fetchall()]
    errors = [
        f"search {row['provider']} / {row['query']}: {row['error'] or row['availability']}"
        for row in connection.execute(
            """SELECT provider, query, availability, error FROM discovery_runs
               WHERE availability = 'SOURCE_UNAVAILABLE' OR error IS NOT NULL ORDER BY id"""
        ).fetchall()
    ]
    errors.extend(
        f"acquisition {row['provider']} / {row['canonical_url']}: {row['error'] or row['state']}"
        for row in connection.execute(
            """SELECT a.provider, d.canonical_url, a.state, a.error
               FROM acquisition_records AS a
               JOIN discovery_records AS d ON d.id = a.discovery_id
               WHERE a.state IN ('ACQUISITION_FAILED','POLICY_BLOCKED') ORDER BY a.id"""
        ).fetchall()
    )
    full_items = sum(int(row["full"]) for row in communities)
    partial_items = sum(int(row["partial"]) for row in communities)
    failed_attempts = sum(int(row["failed_or_blocked"]) for row in communities)
    limitations = [
        f"All {partial_items} acquired items are partial captures; no thread is claimed complete."
        if partial_items and not full_items
        else f"Full items: {full_items}; partial items: {partial_items}.",
        (
            f"Provider cost was not supplied for {summary['unknown_cost_records']} "
            "requests/attempts, so cost-per-1,000 is unknown."
            if summary["unknown_cost_records"]
            else "All provider requests supplied cost measurements."
        ),
        f"Acquisition failures or policy blocks: {failed_attempts}.",
        "Every community sample is below 100 items; normalized rates are descriptive only.",
    ]
    blocker = (
        "Identify and approve a permitted provider that can return reproducible full post "
        "content (and clearly scoped comments) with measured latency and cost."
        if not full_items
        else "Increase the labelled sample while preserving provider terms and completeness."
    )
    return RedditReport(
        {
            "methodology": {
                "content_truth": "FULL, PARTIAL, and METADATA_ONLY are distinct",
                "eligibility": "FULL or PARTIAL and at least 40 characters",
                "strong_single_signal_definition": (
                    "clear actor and job; context or workaround; plus quantified impact, "
                    "payment evidence, active search, or switching intent"
                ),
                "normalization_denominator": "unique canonical Reddit URLs",
            },
            "summary": summary,
            "communities": communities,
            "providers": providers,
            "samples": samples,
            "errors": errors,
            "assessment": {
                "worked": [
                    "External search captures produced canonical Reddit identities.",
                    "Duplicate URL variants converged on one research item.",
                    "Eligible English excerpts passed through the existing extraction pipeline.",
                    "The control community produced no structured problem observation.",
                ],
                "limitations": limitations,
                "next_technical_blocker": blocker,
            },
        }
    )


def _provider_rows(repository: Repository) -> list[dict[str, Any]]:
    connection = repository.connection
    rows: list[dict[str, Any]] = []
    for row in connection.execute(
        """SELECT provider, COUNT(*) AS requests,
                  COALESCE(SUM(results_returned), 0) AS results,
                  COALESCE(SUM(reddit_urls_discovered), 0) AS reddit_urls,
                  COALESCE(SUM(latency_ms), 0) AS latency,
                  COUNT(latency_ms) AS known_latency,
                  COALESCE(SUM(cost_usd), 0) AS cost,
                  COUNT(cost_usd) AS known_cost,
                  MIN(provider_capabilities_json) AS capabilities
           FROM discovery_runs GROUP BY provider ORDER BY provider"""
    ).fetchall():
        rows.append(
            {
                "provider": str(row["provider"]),
                "role": "search",
                "requests": int(row["requests"]),
                "results_returned": int(row["results"]),
                "reddit_urls_discovered": int(row["reddit_urls"]),
                "unique_urls": int(
                    connection.execute(
                        """SELECT COUNT(DISTINCT canonical_url) FROM discovery_records
                           WHERE provider = ?""",
                        (row["provider"],),
                    ).fetchone()[0]
                ),
                "success_rate": None,
                "full_content_rate": None,
                "partial_content_rate": None,
                "failure_rate": None,
                "latency_ms": (
                    int(row["latency"]) if int(row["known_latency"]) else None
                ),
                "unknown_latency_records": int(row["requests"])
                - int(row["known_latency"]),
                "known_cost_usd": float(row["cost"]),
                "unknown_cost_records": int(row["requests"]) - int(row["known_cost"]),
                "capabilities": json.loads(str(row["capabilities"])),
            }
        )
    for row in connection.execute(
        """SELECT provider, COUNT(*) AS attempts,
                  COALESCE(SUM(state IN ('CONTENT_PARTIAL','CONTENT_COMPLETE')), 0) AS successes,
                  COALESCE(SUM(completeness = 'FULL'), 0) AS full_count,
                  COALESCE(SUM(completeness = 'PARTIAL'), 0) AS partial_count,
                  COALESCE(SUM(state IN ('ACQUISITION_FAILED','POLICY_BLOCKED')), 0)
                    AS failure_count,
                  COALESCE(SUM(latency_ms), 0) AS latency,
                  COUNT(latency_ms) AS known_latency,
                  COALESCE(SUM(cost_usd), 0) AS cost,
                  COUNT(cost_usd) AS known_cost,
                  MIN(metadata_json) AS metadata
           FROM acquisition_records GROUP BY provider ORDER BY provider"""
    ).fetchall():
        attempts = int(row["attempts"])
        rows.append(
            {
                "provider": str(row["provider"]),
                "role": "acquisition",
                "requests": attempts,
                "results_returned": 0,
                "reddit_urls_discovered": 0,
                "unique_urls": int(
                    connection.execute(
                        """SELECT COUNT(DISTINCT d.canonical_url)
                           FROM acquisition_records AS a
                           JOIN discovery_records AS d ON d.id = a.discovery_id
                           WHERE a.provider = ?""",
                        (row["provider"],),
                    ).fetchone()[0]
                ),
                "success_rate": int(row["successes"]) / attempts if attempts else None,
                "full_content_rate": int(row["full_count"]) / attempts if attempts else None,
                "partial_content_rate": (
                    int(row["partial_count"]) / attempts if attempts else None
                ),
                "failure_rate": int(row["failure_count"]) / attempts if attempts else None,
                "latency_ms": (
                    int(row["latency"]) if int(row["known_latency"]) else None
                ),
                "unknown_latency_records": attempts - int(row["known_latency"]),
                "known_cost_usd": float(row["cost"]),
                "unknown_cost_records": attempts - int(row["known_cost"]),
                "capabilities": json.loads(str(row["metadata"])).get(
                    "provider_capabilities", {}
                ),
            }
        )
    return rows


def _rate(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{float(value) * 100:.1f}%"


def _metric_label(row: dict[str, Any], key: str, *, decimals: int = 0) -> str:
    value = row[key]
    unknown_key = "unknown_latency_records" if key == "latency_ms" else "unknown_cost_records"
    unknown = int(row[unknown_key])
    if value is None or (key == "known_cost_usd" and unknown == int(row["requests"])):
        return "unknown"
    label = f"{float(value):.{decimals}f}"
    return f"{label} ({unknown} unknown)" if unknown else label


def _cost_label(row: dict[str, Any]) -> str:
    unknown = int(row["unknown_cost_records"])
    if unknown:
        return f"unknown ({unknown} records)"
    return f"${float(row['known_processing_cost_usd']):.4f}"


def _per_thousand(value: int | float, denominator: int) -> float:
    return float(value) * 1000.0 / denominator if denominator else 0.0
