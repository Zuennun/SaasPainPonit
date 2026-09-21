"""Fresh five-source Arctic Shift holdout and autonomous extraction runner."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sqlite3
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .arctic_shift import ArcticShiftConfig, ArcticShiftRedditProvider
from .arctic_shift_poc import ArcticShiftPocMetrics, run_poc
from .automated_discovery import AutomatedDiscovery, DiscoveryMetrics, InferenceConfig
from .discovery_model import check_model, provider_from_environment
from .live_pilot import read_live_manifest_csv
from .llm_provider import LLMProvider
from .repository import Repository
from .signal_policy import strong_individual_signal_sql

EXPECTED_SOURCES = frozenset({
    "r/accounting", "r/restaurantowners", "r/propertymanagement", "r/hvac",
    "r/freightbrokers",
})
USER_AGENT_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9._-]*/[0-9][A-Za-z0-9._-]* \(.+\)$")


def valid_research_user_agent(value: str) -> bool:
    return bool(USER_AGENT_PATTERN.fullmatch(value.strip())) and not any(
        word in value.casefold() for word in ("mozilla", "chrome", "reddit/", "bot rotation")
    )
REVIEW_FIELDS = (
    "source_item_id", "model_status", "source_url", "source_text",
    "problem_statement", "actor", "workflow_context", "workaround",
    "impact", "evidence_excerpts", "human_problem_label",
    "human_actor_correct", "human_problem_faithful",
    "human_workaround_supported", "human_impact_supported",
    "human_evidence_correct", "human_notes",
)


@dataclass(frozen=True, slots=True)
class HoldoutResult:
    acquisition: ArcticShiftPocMetrics
    inference: DiscoveryMetrics
    baseline_excluded_ids: int
    overlap_found: int
    runtime_seconds: float


def load_baseline_reddit_ids(path: Path) -> set[str]:
    if not path.is_file():
        raise FileNotFoundError(f"baseline database not found: {path}")
    uri = f"file:{quote(str(path.resolve()))}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        rows = connection.execute(
            "SELECT DISTINCT submission_id, comment_id FROM discovery_records"
        ).fetchall()
        identities = {
            (f"reddit:comment:{str(submission).lower()}:{str(comment).lower()}"
             if comment is not None else f"reddit:submission:{str(submission).lower()}")
            for submission, comment in rows
        }
        source_items = connection.execute(
            "SELECT external_id FROM source_items WHERE external_id LIKE 'reddit:%'"
        ).fetchall()
        identities.update(str(row[0]).casefold() for row in source_items)
        if not identities:
            raise ValueError("baseline has no Reddit identities")
        return identities
    finally:
        connection.close()


def select_unseen_full_items(
    repository: Repository, excluded_ids: set[str], *, max_items: int = 250,
    acquisition_ids: tuple[int, ...] | None = None,
) -> tuple[tuple[int, ...], int]:
    if max_items <= 0 or max_items > 250:
        raise ValueError("holdout cap must be 1–250")
    full_ids = repository.full_reddit_source_item_ids()
    if acquisition_ids is not None:
        if not acquisition_ids:
            return (), 0
        acquisition_placeholders = ",".join("?" for _ in acquisition_ids)
        current_rows = repository.connection.execute(
            f"""SELECT DISTINCT source_item_id FROM acquisition_records
                WHERE id IN ({acquisition_placeholders})
                  AND completeness = 'FULL' AND source_item_id IS NOT NULL""",
            acquisition_ids,
        ).fetchall()
        current_ids = {int(row["source_item_id"]) for row in current_rows}
        full_ids = tuple(item_id for item_id in full_ids if item_id in current_ids)
    if not full_ids:
        return (), 0
    placeholders = ",".join("?" for _ in full_ids)
    rows = repository.connection.execute(
        f"""SELECT id, external_id FROM source_items
            WHERE id IN ({placeholders}) ORDER BY id""", full_ids,
    ).fetchall()
    overlap = sum(str(row["external_id"]).casefold() in excluded_ids for row in rows)
    selected = tuple(
        int(row["id"]) for row in rows
        if str(row["external_id"]).casefold() not in excluded_ids
    )
    return selected[:max_items], overlap


def run_holdout(
    *, repository: Repository, baseline_ids: set[str],
    arctic_provider: ArcticShiftRedditProvider,
    model_provider: LLMProvider,
    config: InferenceConfig,
    manifest: Path,
    start_date: str,
    end_date: str,
) -> HoldoutResult:
    entries = read_live_manifest_csv(manifest)
    if len(entries) != 5 or {entry.subreddit.casefold() for entry in entries} != set(
        EXPECTED_SOURCES
    ):
        raise ValueError("holdout must use exactly the five baseline communities")
    if start_date >= end_date:
        raise ValueError("holdout date window is invalid")
    started = time.monotonic()
    acquisition, acquisition_ids = run_poc(
        repository, arctic_provider, entries, per_source_limit=50,
        start_date=start_date, end_date=end_date,
    )
    selected, overlap = select_unseen_full_items(
        repository, baseline_ids, acquisition_ids=acquisition_ids,
    )
    if not selected:
        raise ValueError("holdout acquisition produced no unseen FULL SourceItems")
    inference = AutomatedDiscovery(repository, model_provider, config).run(selected)
    return HoldoutResult(
        acquisition, inference, len(baseline_ids), overlap,
        time.monotonic() - started,
    )


def _review_rows(repository: Repository, metrics: DiscoveryMetrics) -> list[dict[str, Any]]:
    positives = [outcome for outcome in metrics.outcomes if outcome.status == "OBSERVATION"]
    negatives = [outcome for outcome in metrics.outcomes if outcome.status == "NO_PAIN"]
    external_ids = {
        int(row["id"]): str(row["external_id"])
        for row in repository.connection.execute(
            "SELECT id, external_id FROM source_items"
        ).fetchall()
    }
    negatives.sort(key=lambda row: hashlib.sha256(
        external_ids.get(row.source_item_id, str(row.source_item_id)).encode()
    ).hexdigest())
    selected = positives[:30] + negatives[:25]
    rows: list[dict[str, Any]] = []
    for outcome in selected:
        item = repository.connection.execute(
            "SELECT url, raw_text FROM source_items WHERE id = ?", (outcome.source_item_id,)
        ).fetchone()
        if item is None:
            continue
        observation = None
        evidence: list[str] = []
        if outcome.observation_id is not None:
            observation = repository.connection.execute(
                "SELECT * FROM problem_observations WHERE id = ?",
                (outcome.observation_id,),
            ).fetchone()
            evidence = [
                str(row["excerpt"]) for row in repository.connection.execute(
                    "SELECT excerpt FROM evidence_spans WHERE observation_id = ? ORDER BY id",
                    (outcome.observation_id,),
                ).fetchall()
            ]
        workaround = observation["current_workaround"] if observation else ""
        impact = observation["time_impact"] if observation else ""
        if outcome.observation_id is not None:
            workaround_signal = repository.connection.execute(
                "SELECT description FROM workarounds WHERE observation_id = ? "
                "ORDER BY id LIMIT 1", (outcome.observation_id,),
            ).fetchone()
            impact_signal = repository.connection.execute(
                "SELECT impact_type, value, unit, frequency FROM impact_signals "
                "WHERE observation_id = ? ORDER BY id LIMIT 1", (outcome.observation_id,),
            ).fetchone()
            if not workaround and workaround_signal is not None:
                workaround = workaround_signal["description"]
            if not impact and impact_signal is not None:
                impact = " ".join(str(value) for value in (
                    impact_signal["value"], impact_signal["unit"],
                    impact_signal["frequency"],
                ) if value is not None)
        rows.append({
            "source_item_id": outcome.source_item_id,
            "model_status": outcome.status,
            "source_url": item["url"],
            "source_text": item["raw_text"],
            "problem_statement": observation["problem"] if observation else "",
            "actor": observation["actor"] if observation else "",
            "workflow_context": observation["context"] if observation else "",
            "workaround": workaround,
            "impact": impact,
            "evidence_excerpts": json.dumps(evidence, ensure_ascii=False),
            "human_problem_label": "", "human_actor_correct": "",
            "human_problem_faithful": "", "human_workaround_supported": "",
            "human_impact_supported": "", "human_evidence_correct": "", "human_notes": "",
        })
    return rows


def write_holdout_outputs(
    repository: Repository | None,
    result: HoldoutResult | None,
    output_directory: Path,
    *, status: str,
    blocker: str | None = None,
) -> None:
    output_directory.mkdir(parents=True, exist_ok=True)
    metrics_path = output_directory / "automated_discovery_holdout_metrics.json"
    report_path = output_directory / "automated_discovery_holdout.md"
    review_path = output_directory / "automated_discovery_review.csv"
    if result is None:
        payload: dict[str, Any] = {
            "status": status, "blocker": blocker, "real_holdout_run": False,
            "records_acquired": None, "usable_records": None,
            "screening_calls": None, "potential_pain": None, "no_pain": None,
            "extraction_calls": None, "valid_observations": None,
            "inference_failures": None, "evidence_validation_failures": None,
            "strong_signals": None, "input_tokens": None, "output_tokens": None,
            "cost_usd": "UNKNOWN", "runtime_seconds": None,
            "api_inference_cost_eur": "UNKNOWN",
            "infrastructure_cost": "UNKNOWN",
        }
        report = (
            "# Automated discovery holdout\n\n"
            f"Status: **{status}**. No unseen holdout inference has run.\n\n"
            f"Blocker: {blocker or 'unknown'}.\n\n"
            "No examples or quality recommendation are asserted without real model calls.\n"
            "Semantic recurrence remains a separate clustering gap; thresholds are unchanged.\n"
        )
        review_rows: list[dict[str, Any]] = []
    else:
        assert repository is not None
        inference = result.inference
        acquisition = result.acquisition
        payload = {
            "status": status, "real_holdout_run": True,
            "records_acquired": acquisition.records_received,
            "usable_records": inference.processed_items,
            "baseline_excluded_ids": result.baseline_excluded_ids,
            "overlap_found": result.overlap_found,
            "screening_calls": inference.screening_calls,
            "potential_pain": inference.potential_pain,
            "no_pain": inference.no_pain,
            "extraction_calls": inference.extraction_calls,
            "valid_observations": inference.valid_observations,
            "inference_failures": inference.inference_failures,
            "evidence_validation_failures": inference.evidence_validation_failures,
            "strong_signals": inference.strong_signals,
            "input_tokens": (inference.input_tokens if not inference.unreported_usage_calls
                             else None),
            "output_tokens": (inference.output_tokens if not inference.unreported_usage_calls
                              else None),
            "reported_input_tokens": inference.input_tokens,
            "reported_output_tokens": inference.output_tokens,
            "unreported_usage_calls": inference.unreported_usage_calls,
            "model_usage": {
                "provider": repository.connection.execute(
                    "SELECT provider FROM model_runs WHERE pipeline_run_id = ? LIMIT 1",
                    (inference.run_id,),
                ).fetchone()[0] if inference.screening_calls else None,
                "endpoint_class": repository.connection.execute(
                    """SELECT sia.endpoint_class FROM structured_inference_attempts sia
                       JOIN model_runs mr ON mr.id = sia.model_run_id
                       WHERE mr.pipeline_run_id = ? LIMIT 1""",
                    (inference.run_id,),
                ).fetchone()[0] if inference.screening_calls else None,
                "model": repository.connection.execute(
                    "SELECT model FROM model_runs WHERE pipeline_run_id = ? LIMIT 1",
                    (inference.run_id,),
                ).fetchone()[0] if inference.screening_calls else None,
                "calls": inference.screening_calls + inference.extraction_calls,
                "retries": inference.retries,
            },
            "cost_usd": (str(inference.known_cost_usd) if inference.known_cost_usd is not None
                         else "UNKNOWN"),
            "api_inference_cost_usd": (
                str(inference.known_cost_usd) if inference.known_cost_usd is not None
                else "UNKNOWN"
            ),
            "infrastructure_cost_usd": "UNKNOWN",
            "api_inference_cost_eur": (
                "0" if repository.connection.execute(
                    """SELECT 1 FROM cost_events ce
                       JOIN model_runs mr ON mr.id = ce.model_run_id
                       WHERE mr.pipeline_run_id = ?
                         AND ce.measurement_source = 'local-api-charge'
                       LIMIT 1""", (inference.run_id,),
                ).fetchone() is not None else "UNKNOWN"
            ),
            "infrastructure_cost": "UNKNOWN",
            "runtime_seconds": result.runtime_seconds,
            "failures": inference.failures,
            "recommendation": (
                "AUTOMATED_DISCOVERY_NEEDS_TUNING" if inference.valid_observations
                else "AUTOMATED_DISCOVERY_NOT_READY"
            ),
        }
        review_rows = _review_rows(repository, inference)
        examples: list[str] = []
        failure_examples: list[str] = []
        suspicious_negatives: list[str] = []
        lower_evidence_positives: list[str] = []
        for outcome in inference.outcomes:
            if outcome.observation_id is None or len(examples) >= 5:
                continue
            row = repository.connection.execute(
                """SELECT o.problem, o.actor, o.job_to_be_done, o.context,
                          o.current_workaround, o.time_impact, si.url
                   FROM problem_observations o
                   JOIN source_items si ON si.id = o.source_item_id
                   WHERE o.id = ?""", (outcome.observation_id,),
            ).fetchone()
            if row is None:
                continue
            evidence = repository.connection.execute(
                "SELECT excerpt FROM evidence_spans WHERE observation_id = ? ORDER BY id LIMIT 2",
                (outcome.observation_id,),
            ).fetchall()
            workaround_signal = repository.connection.execute(
                "SELECT description FROM workarounds WHERE observation_id = ? "
                "ORDER BY id LIMIT 1", (outcome.observation_id,),
            ).fetchone()
            impact_signal = repository.connection.execute(
                "SELECT impact_type, value, unit, frequency FROM impact_signals "
                "WHERE observation_id = ? ORDER BY id LIMIT 1", (outcome.observation_id,),
            ).fetchone()
            workaround = row["current_workaround"] or (
                workaround_signal["description"] if workaround_signal else None
            )
            impact = row["time_impact"] or (
                " ".join(str(value) for value in (
                    impact_signal["value"], impact_signal["unit"],
                    impact_signal["frequency"],
                ) if value is not None) if impact_signal else None
            )
            strong = repository.connection.execute(
                f"""SELECT {strong_individual_signal_sql('o')} AS strong
                    FROM problem_observations o WHERE o.id = ?""",
                (outcome.observation_id,),
            ).fetchone()
            signal = "STRONG_SINGLE_SIGNAL" if strong and strong["strong"] else "SINGLE_SIGNAL"
            examples.append(
                f"- Problem: {row['problem']}; actor: {row['actor']}; "
                f"workflow/context: {row['job_to_be_done']} / {row['context']}; "
                f"workaround: {workaround}; impact: {impact}; "
                f"signal: {signal}; source: {row['url']}; evidence: "
                + " | ".join(str(item["excerpt"]) for item in evidence)
            )
        for outcome in inference.outcomes:
            if outcome.status == "MODEL_FAILURE" and len(failure_examples) < 5:
                source = repository.connection.execute(
                    "SELECT url FROM source_items WHERE id = ?", (outcome.source_item_id,)
                ).fetchone()
                failure_examples.append(
                    f"- {outcome.failure.value if outcome.failure else 'UNKNOWN_ERROR'}: "
                    f"{source['url'] if source else 'unknown URL'}"
                )
            if outcome.status == "NO_PAIN" and len(suspicious_negatives) < 5:
                source = repository.connection.execute(
                    "SELECT url, raw_text FROM source_items WHERE id = ?",
                    (outcome.source_item_id,),
                ).fetchone()
                if source is not None and any(
                    term in str(source["raw_text"]).casefold()
                    for term in ("manually", "spreadsheet", "waste time", "duplicate entry")
                ):
                    suspicious_negatives.append(f"- keyword-flagged for review: {source['url']}")
            if outcome.observation_id is not None and len(lower_evidence_positives) < 5:
                cache = repository.connection.execute(
                    """SELECT result_json FROM structured_inference_cache
                       WHERE observation_id = ? ORDER BY created_at DESC LIMIT 1""",
                    (outcome.observation_id,),
                ).fetchone()
                if cache is not None:
                    result_json = json.loads(str(cache["result_json"]))
                    claims = result_json.get("claims", [])
                    if any(
                        claim.get("field") == "problem_statement"
                        and claim.get("strength") == "THIRD_PARTY_DESCRIPTION"
                        for claim in claims
                    ):
                        source = repository.connection.execute(
                            "SELECT url FROM source_items WHERE id = ?",
                            (outcome.source_item_id,),
                        ).fetchone()
                        lower_evidence_positives.append(
                            f"- third-party problem description; review carefully: "
                            f"{source['url'] if source else 'unknown URL'}"
                        )
        report = "\n".join((
            "# Automated discovery holdout", "",
            f"Status: **{status}**. Arctic Shift acquisition cost: **€0**.",
            "", "## Funnel and model usage", "",
            f"Acquired {acquisition.records_received}; usable {inference.processed_items}; "
            f"screening calls {inference.screening_calls}; POTENTIAL_PAIN "
            f"{inference.potential_pain}; NO_PAIN {inference.no_pain}; extraction calls "
            f"{inference.extraction_calls}; valid observations "
            f"{inference.valid_observations}; strong signals {inference.strong_signals}.",
            f"Inference failures {inference.inference_failures}; evidence-validation "
            f"failures {inference.evidence_validation_failures}; "
            f"failure types {json.dumps(inference.failures, sort_keys=True)}.",
            f"Tokens reported: input {inference.input_tokens}, output "
            f"{inference.output_tokens}; calls without usage "
            f"{inference.unreported_usage_calls}; "
            f"API inference cost USD: {payload['api_inference_cost_usd']}; "
            f"local direct API charge EUR: {payload['api_inference_cost_eur']}; "
            "infrastructure cost: UNKNOWN; "
            f"runtime {result.runtime_seconds:.2f} seconds.",
            f"Baseline IDs excluded: {result.baseline_excluded_ids}; "
            f"overlap encountered: {result.overlap_found}.",
            "", "## Unedited model-produced examples", "",
            *(examples or ["No validated positive observations."]),
            "", "## Failure and review visibility", "",
            f"Provisional recommendation: {payload['recommendation']} "
            "(human precision labels are still pending).",
            "", "Model/evidence validation failures:",
            *(failure_examples or ["- None recorded."]),
            "", "Lower-strength positive candidates (not confirmed false positives):",
            *(lower_evidence_positives or ["- None identified by evidence-strength flag."]),
            "", "Keyword-flagged NO_PAIN candidates (not confirmed misses):",
            *(suspicious_negatives or ["- None identified by this diagnostic flag."]),
            "The review CSV contains model positives and a deterministic sample of "
            "NO_PAIN items; all human columns are blank.",
            "Likely false positives, suspicious negatives, and semantically misaligned "
            "claims require human review; none are labeled without that review.",
            "Failed model/validation calls remain separate from NO_PAIN in metrics.",
            "Semantic recurrence remains a separate clustering gap; thresholds are unchanged.",
            "",
        ))
    metrics_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    report_path.write_text(report, encoding="utf-8")
    with review_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_FIELDS)
        writer.writeheader()
        for row in review_rows:
            writer.writerow({key: row.get(key, "") for key in REVIEW_FIELDS})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path,
                        default=Path("data/reddit/automated_holdout.db"))
    parser.add_argument("--baseline-database", type=Path,
                        default=Path("data/reddit/arctic_shift_250_pilot.db"))
    parser.add_argument("--manifest", type=Path,
                        default=Path("docs/providers/arctic-shift-poc-manifest.csv"))
    parser.add_argument("--output", type=Path, default=Path("exports"))
    parser.add_argument("--start-date", default="2026-08-15")
    parser.add_argument("--end-date", default="2026-09-05")
    parser.add_argument("--user-agent", default=os.environ.get("ARCTIC_SHIFT_USER_AGENT", ""))
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-screen-tokens", type=int, default=300)
    parser.add_argument("--max-extract-tokens", type=int, default=1800)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--input-usd-per-million", type=Decimal)
    parser.add_argument("--output-usd-per-million", type=Decimal)
    parser.add_argument("--llm-rights-confirmed", action="store_true")
    args = parser.parse_args(argv)
    missing: list[str] = []
    provider_type = os.environ.get("DISCOVERY_LLM_PROVIDER", "openai")
    if provider_type not in {"openai", "openai_compatible", "codex_cli"}:
        missing.append("DISCOVERY_LLM_PROVIDER=openai|openai_compatible|codex_cli")
    if provider_type != "codex_cli" and not os.environ.get("DISCOVERY_MODEL"):
        missing.append("DISCOVERY_MODEL")
    if provider_type == "openai" and not os.environ.get("OPENAI_API_KEY"):
        missing.append("OPENAI_API_KEY")
    if provider_type == "openai_compatible" and not os.environ.get("DISCOVERY_BASE_URL"):
        missing.append("DISCOVERY_BASE_URL")
    if not valid_research_user_agent(args.user_agent):
        missing.append("truthful ARCTIC_SHIFT_USER_AGENT or --user-agent")
    if missing:
        write_holdout_outputs(
            None, None, args.output, status="NOT_RUN_CONFIGURATION_REQUIRED",
            blocker=", ".join(missing),
        )
        return 2
    try:
        llm = provider_from_environment()
        if not getattr(llm, "local_inference", False) and not args.llm_rights_confirmed:
            write_holdout_outputs(
                None, None, args.output, status="NOT_RUN_CONFIGURATION_REQUIRED",
                blocker="explicit rights confirmation for non-loopback LLM processing",
            )
            return 2
        check_model(llm, timeout_seconds=args.timeout_seconds)
        baseline_ids = load_baseline_reddit_ids(args.baseline_database)
        config = InferenceConfig(
            temperature=args.temperature,
            max_output_tokens_screen=args.max_screen_tokens,
            max_output_tokens_extract=args.max_extract_tokens,
            timeout_seconds=args.timeout_seconds, max_retries=args.max_retries,
            input_usd_per_million=args.input_usd_per_million,
            output_usd_per_million=args.output_usd_per_million,
        )
        arctic = ArcticShiftRedditProvider(ArcticShiftConfig(user_agent=args.user_agent))
        repository = Repository(args.database)
        try:
            repository.initialize()
            result = run_holdout(
                repository=repository, baseline_ids=baseline_ids,
                arctic_provider=arctic, model_provider=llm, config=config,
                manifest=args.manifest, start_date=args.start_date, end_date=args.end_date,
            )
            write_holdout_outputs(repository, result, args.output, status="INFERENCE_COMPLETED")
            return 0
        finally:
            repository.close()
    except Exception as exc:
        write_holdout_outputs(
            None, None, args.output, status="HOLDOUT_FAILED",
            blocker=f"{type(exc).__name__}: {exc}",
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
