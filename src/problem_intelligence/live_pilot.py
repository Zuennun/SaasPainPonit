"""Provider-neutral live pilot orchestration.

The Reddit acquisition architecture is frozen (docs/decisions/0001-two-reddit-
acquisition-shapes.md). This module only orchestrates: it selects which curated CORE
sources to run, gates real execution on provider readiness, and drives a per-source
acquisition callable through resumable, idempotent state. It never branches on which
provider is selected for research-layer behavior — provider-specific logic (how to
call Brandwatch's API, how to normalize its records) lives in the caller-supplied
`acquire_source` callable, not here.
"""

from __future__ import annotations

import csv
import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from itertools import cycle
from pathlib import Path
from typing import Any, cast

from .pilot_planner import PilotPlan, PilotPlanEntry
from .prediction_extractor import JsonlPredictionExtractor
from .reddit_provider_registry import LiveRunGateResult
from .repository import Repository
from .signal_policy import strong_individual_signal_sql
from .wave1 import WaveSelection


@dataclass(frozen=True, slots=True)
class LiveManifestEntry:
    subreddit: str
    category: str | None
    target_group: str | None
    pilot_item_target: int
    selection_reason: str
    activity_state: str | None
    access_state: str


MANIFEST_FIELDS: tuple[str, ...] = (
    "subreddit", "category", "target_group", "pilot_item_target",
    "selection_reason", "activity_state", "access_state",
)


def select_live_pilot_manifest(
    plan: PilotPlan, *, max_sources: int = 25, item_target: int = 100,
) -> tuple[LiveManifestEntry, ...]:
    """Deterministically select up to `max_sources` CORE, ready, conflict-free
    sources from the curated pilot plan, round-robined across curated categories so
    the pilot is not one category deep. Never invents a source not in the registry."""

    if max_sources <= 0:
        raise ValueError("max_sources must be positive")
    if item_target <= 0:
        raise ValueError("item_target must be positive")
    core_ready = [entry for entry in plan.manifest if entry.relevance_status == "CORE"]
    by_category: dict[str, list[PilotPlanEntry]] = {}
    for entry in core_ready:
        by_category.setdefault(entry.category or "Uncategorized", []).append(entry)
    selected: list[PilotPlanEntry] = []
    category_order = sorted(by_category)
    if category_order:
        for category in cycle(category_order):
            if len(selected) >= max_sources:
                break
            bucket = by_category[category]
            if bucket:
                selected.append(bucket.pop(0))
            if not any(by_category.values()):
                break
    return tuple(
        LiveManifestEntry(
            subreddit=entry.source_name,
            category=entry.category,
            target_group=entry.target_group,
            pilot_item_target=item_target,
            selection_reason=(
                entry.reason or "CORE and ready per the curated source-registry audit"
            ),
            activity_state=entry.activity_status,
            access_state=entry.access_status,
        )
        for entry in selected
    )


def write_live_manifest_csv(path: Path, entries: tuple[LiveManifestEntry, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        for entry in entries:
            writer.writerow({
                "subreddit": entry.subreddit,
                "category": entry.category or "",
                "target_group": entry.target_group or "",
                "pilot_item_target": entry.pilot_item_target,
                "selection_reason": entry.selection_reason,
                "activity_state": entry.activity_state or "",
                "access_state": entry.access_state,
            })


def read_live_manifest_csv(path: Path) -> tuple[LiveManifestEntry, ...]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != list(MANIFEST_FIELDS):
            raise ValueError("live pilot manifest CSV has unexpected columns")
        entries = tuple(
            LiveManifestEntry(
                subreddit=row["subreddit"],
                category=row["category"] or None,
                target_group=row["target_group"] or None,
                pilot_item_target=int(row["pilot_item_target"]),
                selection_reason=row["selection_reason"],
                activity_state=row["activity_state"] or None,
                access_state=row["access_state"],
            )
            for row in reader
        )
    if not entries:
        raise ValueError("live pilot manifest must not be empty")
    if len({entry.subreddit.casefold() for entry in entries}) != len(entries):
        raise ValueError("live pilot manifest has duplicate subreddits")
    return entries


class SourceRunStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


@dataclass(frozen=True, slots=True)
class SourceRunOutcome:
    status: SourceRunStatus
    acquisition_ids: tuple[int, ...] = ()
    error: str | None = None


@dataclass(frozen=True, slots=True)
class DryRunSourcePlan:
    subreddit: str
    pilot_item_target: int
    estimated_acquisition_operations: int


@dataclass(frozen=True, slots=True)
class DryRunReport:
    provider: str
    manifest_source_count: int
    selected_source_count: int
    total_requested_items: int
    provider_readiness: LiveRunGateResult
    capabilities: dict[str, Any]
    sources: tuple[DryRunSourcePlan, ...]

    @property
    def estimated_acquisition_operations(self) -> int:
        return sum(source.estimated_acquisition_operations for source in self.sources)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "manifest_source_count": self.manifest_source_count,
            "selected_source_count": self.selected_source_count,
            "total_requested_items": self.total_requested_items,
            "allowed": self.provider_readiness.allowed,
            "blocked_reasons": list(self.provider_readiness.reasons),
            "capabilities": self.capabilities,
            "estimated_acquisition_operations": self.estimated_acquisition_operations,
            "sources": [
                {
                    "subreddit": source.subreddit,
                    "pilot_item_target": source.pilot_item_target,
                    "estimated_acquisition_operations": source.estimated_acquisition_operations,
                }
                for source in self.sources
            ],
            "made_external_requests": False,
        }


def build_dry_run_report(
    *,
    provider: str,
    manifest: tuple[LiveManifestEntry, ...],
    max_sources: int,
    max_items_per_source: int,
    gate: LiveRunGateResult,
    capabilities: dict[str, Any],
    page_size: int = 20,
) -> DryRunReport:
    """Pure computation over already-loaded manifest/gate data: makes zero provider
    calls. `estimated_acquisition_operations` is an explicit upper-bound estimate
    (discover + fulltext pages per source at `page_size`), never a real count."""

    if page_size <= 0:
        raise ValueError("page_size must be positive")
    selected = manifest[:max_sources]
    sources = tuple(
        DryRunSourcePlan(
            subreddit=entry.subreddit,
            pilot_item_target=min(entry.pilot_item_target, max_items_per_source),
            estimated_acquisition_operations=2 * math.ceil(
                min(entry.pilot_item_target, max_items_per_source) / page_size
            ),
        )
        for entry in selected
    )
    return DryRunReport(
        provider=provider,
        manifest_source_count=len(manifest),
        selected_source_count=len(selected),
        total_requested_items=sum(source.pilot_item_target for source in sources),
        provider_readiness=gate,
        capabilities=capabilities,
        sources=sources,
    )


def load_run_state(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    value: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("run state file must contain an object")
    typed_value = cast(dict[object, object], value)
    return {str(key): str(item) for key, item in typed_value.items()}


def write_run_state(path: Path, state: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


@dataclass(frozen=True, slots=True)
class LivePilotRunResult:
    provider: str
    outcomes: dict[str, SourceRunOutcome]

    @property
    def completed(self) -> tuple[str, ...]:
        return tuple(
            source for source, outcome in self.outcomes.items()
            if outcome.status in (SourceRunStatus.COMPLETE, SourceRunStatus.SKIPPED)
        )

    @property
    def failed(self) -> tuple[str, ...]:
        return tuple(
            source for source, outcome in self.outcomes.items()
            if outcome.status is SourceRunStatus.FAILED
        )


def run_live_pilot(
    *,
    provider: str,
    sources: tuple[LiveManifestEntry, ...],
    gate: LiveRunGateResult,
    acquire_source: Callable[[LiveManifestEntry], SourceRunOutcome],
    state_path: Path,
) -> LivePilotRunResult:
    """Resumable, failure-safe execution. A source already COMPLETE in `state_path`
    is skipped, not re-acquired. A single source raising does not abort the run or
    discard outcomes already recorded for earlier sources; it is recorded FAILED and
    the run continues. Re-running is safe because acquire_source is expected to write
    through the existing idempotent canonical ingestion path."""

    if not gate.allowed:
        raise ValueError("live run blocked: " + "; ".join(gate.reasons))
    state = load_run_state(state_path)
    outcomes: dict[str, SourceRunOutcome] = {}
    for entry in sources:
        if state.get(entry.subreddit) == SourceRunStatus.COMPLETE.value:
            outcomes[entry.subreddit] = SourceRunOutcome(SourceRunStatus.SKIPPED)
            continue
        state[entry.subreddit] = SourceRunStatus.RUNNING.value
        write_run_state(state_path, state)
        try:
            outcome = acquire_source(entry)
        except Exception as exc:  # noqa: BLE001 - one source's failure must not abort the run
            outcome = SourceRunOutcome(SourceRunStatus.FAILED, error=str(exc))
        outcomes[entry.subreddit] = outcome
        state[entry.subreddit] = outcome.status.value
        write_run_state(state_path, state)
    return LivePilotRunResult(provider=provider, outcomes=outcomes)


def live_pilot_wave_selections(
    manifest: tuple[LiveManifestEntry, ...], run_result: LivePilotRunResult | None = None,
) -> tuple[WaveSelection, ...]:
    """Adapt the provider-independent manifest into `WaveSelection` rows so the
    existing, already acquisition/research-quality-separated `wave1_report` module
    can be reused unchanged for live pilot reporting."""

    selections: list[WaveSelection] = []
    for index, entry in enumerate(manifest, start=1):
        outcome = run_result.outcomes.get(entry.subreddit) if run_result else None
        acquisition_eligible = outcome is not None and outcome.status in (
            SourceRunStatus.COMPLETE, SourceRunStatus.SKIPPED,
        )
        selections.append(WaveSelection(
            slot=index,
            category=entry.category or "",
            source=entry.subreddit,
            primary=entry.subreddit,
            backup=entry.subreddit,
            target_items=entry.pilot_item_target,
            health_status=entry.activity_state or "UNKNOWN",
            policy_ready=entry.access_state == "NOT_FLAGGED",
            selection_status="LIVE_PILOT_MANIFEST",
            acquisition_eligible=acquisition_eligible,
        ))
    return tuple(selections)


REVIEW_FIELDS: tuple[str, ...] = (
    "subreddit", "canonical_url", "classification", "problem_statement", "actor",
    "job_context", "workaround", "impact", "payment_signal", "evidence_text",
    "source_completeness", "provider",
    "human_pain_label", "human_strength_label", "human_cluster_notes",
    "human_extraction_notes", "reviewer_notes",
)


def build_review_export_rows(
    repository: Repository,
    selections: tuple[WaveSelection, ...],
    *,
    predictions: Path | None = None,
    limit_per_source: int = 5,
) -> tuple[dict[str, Any], ...]:
    """Every row traces to a stored SourceItem and, for positive/weak rows, an
    evidence span. Human-review columns are always blank: this export seeds manual
    labeling, it never invents a label or a finding."""

    full_ids = set(repository.full_reddit_source_item_ids())
    negative_ids: set[int] = set()
    if predictions is not None and full_ids:
        extractor = JsonlPredictionExtractor(predictions, version="live-pilot-review-v1")
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
    rows: list[dict[str, Any]] = []
    for selected in selections:
        observation_rows = repository.connection.execute(
            f"""SELECT po.problem, po.actor, po.actor_role, po.context,
                       po.current_workaround, po.time_impact, po.financial_impact, si.url,
                       (SELECT es.excerpt FROM evidence_spans es
                        WHERE es.observation_id = po.id ORDER BY es.id LIMIT 1)
                        AS evidence_excerpt,
                       (SELECT p.payment_type || ': ' || es.excerpt FROM payment_signals p
                        JOIN evidence_spans es ON es.id = p.evidence_span_id
                        WHERE p.observation_id = po.id ORDER BY p.id LIMIT 1) AS payment_evidence,
                       (SELECT GROUP_CONCAT(DISTINCT a.provider) FROM acquisition_records a
                        WHERE a.source_item_id = po.source_item_id AND a.completeness = 'FULL')
                        AS providers,
                       {strong} AS is_strong
                FROM problem_observations po
                JOIN source_items si ON si.id = po.source_item_id
                JOIN sources s ON s.id = si.source_id
                WHERE lower(s.name) = lower(?) AND po.source_item_id IN
                    (SELECT a.source_item_id FROM acquisition_records a
                     WHERE a.completeness = 'FULL')
                ORDER BY is_strong DESC, po.id LIMIT ?""",
            (selected.source, limit_per_source),
        ).fetchall()
        for row in observation_rows:
            rows.append(_review_row(
                subreddit=selected.source, canonical_url=row["url"],
                classification="STRONG_POSITIVE" if row["is_strong"] else "WEAK_POSITIVE",
                problem_statement=row["problem"], actor=row["actor"] or row["actor_role"],
                job_context=row["context"], workaround=row["current_workaround"],
                impact=row["time_impact"] or row["financial_impact"],
                payment_signal=row["payment_evidence"], evidence_text=row["evidence_excerpt"],
                provider=row["providers"],
            ))
        if predictions is not None:
            negative_rows = repository.connection.execute(
                """SELECT si.id, si.url, si.raw_text,
                          (SELECT GROUP_CONCAT(DISTINCT a.provider) FROM acquisition_records a
                           WHERE a.source_item_id = si.id AND a.completeness = 'FULL')
                           AS providers
                   FROM source_items si JOIN sources s ON s.id = si.source_id
                   WHERE lower(s.name) = lower(?) ORDER BY si.id""",
                (selected.source,),
            ).fetchall()
            matches = [r for r in negative_rows if int(r["id"]) in negative_ids]
            for row in matches[:limit_per_source]:
                rows.append(_review_row(
                    subreddit=selected.source, canonical_url=row["url"],
                    classification="NO_PAIN", problem_statement=None, actor=None,
                    job_context=None, workaround=None, impact=None, payment_signal=None,
                    evidence_text=row["raw_text"], provider=row["providers"],
                ))
    return tuple(rows)


def _review_row(
    *, subreddit: str, canonical_url: str | None, classification: str,
    problem_statement: str | None, actor: str | None, job_context: str | None,
    workaround: str | None, impact: str | None, payment_signal: str | None,
    evidence_text: str | None, provider: str | None,
) -> dict[str, Any]:
    return {
        "subreddit": subreddit,
        "canonical_url": canonical_url,
        "classification": classification,
        "problem_statement": problem_statement,
        "actor": actor,
        "job_context": job_context,
        "workaround": workaround,
        "impact": impact,
        "payment_signal": payment_signal,
        "evidence_text": evidence_text,
        "source_completeness": "FULL",
        "provider": provider,
        "human_pain_label": "",
        "human_strength_label": "",
        "human_cluster_notes": "",
        "human_extraction_notes": "",
        "reviewer_notes": "",
    }


def write_review_export_csv(path: Path, rows: tuple[dict[str, Any], ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def build_readiness_report(
    *,
    manifest: tuple[LiveManifestEntry, ...],
    provider: str,
    gate: LiveRunGateResult,
    provider_status_table: str,
    dry_run: DryRunReport,
) -> str:
    per_source_target = dry_run.sources[0].pilot_item_target if dry_run.sources else 0
    lines = [
        "# Reddit live pilot readiness",
        "",
        f"Status: **{'READY_TO_RUN' if gate.allowed else 'EXECUTION_BLOCKED'}**. "
        "No real pilot has been executed to produce this report.",
        "",
        "## Manifest",
        "",
        f"- Sources selected: {len(manifest)} (target: 20-25 CORE sources spread "
        "across curated categories).",
        f"- Requested items per source: {per_source_target}. "
        f"Total requested items: {sum(entry.pilot_item_target for entry in manifest)}.",
        "- Manifest is provider-independent: it stores no Brandwatch query IDs or "
        "other provider-specific configuration "
        "(`exports/reddit_wave1_live_manifest.csv`).",
        "",
        "## Providers",
        "",
        "```",
        provider_status_table,
        "```",
        "",
        f"Selected provider for this readiness check: **{provider}**.",
        "",
        "## Blockers to a real run",
        "",
    ]
    lines.extend(
        ["- None. All readiness conditions are satisfied."] if gate.allowed
        else [f"- {reason}" for reason in gate.reasons]
    )
    lines += [
        "",
        "## Acquisition architecture status",
        "",
        "Frozen; considered structurally complete "
        "(`docs/decisions/0001-two-reddit-acquisition-shapes.md`). Both the "
        "URL-discovery and feed/data-provider acquisition paths converge on "
        "`Repository.ingest_reddit_content`. This readiness phase does not change them.",
        "",
        "## Evaluation readiness",
        "",
        "No evaluation-suite manifest is configured yet "
        "(`problem_intelligence.cli evaluation-readiness` requires one). Evaluation "
        "readiness for this pilot's own output is therefore unmeasured, not passing.",
        "",
        "## Manual-review export",
        "",
        "`exports/reddit_wave1_review.csv` exists with the full review schema (problem "
        "statement, actor, workaround, impact, payment signal, evidence text, "
        "completeness, provider, and blank `human_*`/`reviewer_notes` columns for "
        "manual labeling) but currently has zero rows: no real FULL Reddit content has "
        "been acquired yet, and this export never fabricates one to fill the file.",
        "",
        "## Command that will execute the pilot once unblocked",
        "",
        "```bash",
        "python -m problem_intelligence.cli reddit-live-pilot \\",
        f"  --provider {provider} --database <path-to-a-real-database-file> \\",
        "  --manifest exports/reddit_wave1_live_manifest.csv \\",
        f"  --max-sources {len(manifest)} --max-items-per-source {per_source_target} \\",
        "  --state exports/reddit_live_pilot_state.json",
        "```",
        "",
        "This phase does not claim a real run occurred; every count above comes from "
        "the curated registry and dry-run estimation only, never a live provider call.",
        "",
    ]
    return "\n".join(lines)
