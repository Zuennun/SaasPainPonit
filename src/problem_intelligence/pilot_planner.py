"""Deterministic pilot-scan planning over the curated source registry.

The curated `strict_relevance` audit answers "where should we start scanning".
Empirical `source_metrics` snapshots later answer "was that source actually
useful". This module only reads the curated layer; it never reads or writes
measured performance, so running it can never overwrite observed yield.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from typing import Any

from .repository import Repository

#: Relevance states eligible for the primary discovery pilot. SECONDARY, DROP,
#: and RECHECK_ACCESS are deliberately excluded until their curated state changes.
PILOT_RELEVANCE_STATES: tuple[str, ...] = ("CORE", "PILOT")

#: Curated recommendations that mean "usable/active now", not merely relevant.
READY_RECOMMENDED_ACTIONS = frozenset({"SCAN_PILOT_NOW", "SCAN_SMALL_PILOT"})

#: Access-verification recommendation surfaced as its own access dimension.
ACCESS_RECHECK_ACTIONS = frozenset({"VERIFY_ACCESS"})

#: Conservative fallback sample sizes, used only when the registry supplies
#: neither strict_pilot_posts nor pilot_posts for an otherwise-ready source.
DEFAULT_PILOT_SIZE = {"CORE": 50, "PILOT": 25}

_RELEVANCE_RANK = {state: index for index, state in enumerate(PILOT_RELEVANCE_STATES)}


@dataclass(frozen=True, slots=True)
class PilotPlanEntry:
    ordering: int
    source_id: int
    source_name: str
    category: str | None
    target_group: str | None
    relevance_status: str
    activity_status: str | None
    access_status: str
    recommended_action: str | None
    ready: bool
    pilot_size: int
    reason: str | None
    conflict: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ordering": self.ordering,
            "source_id": self.source_id,
            "source": self.source_name,
            "category": self.category,
            "target_group": self.target_group,
            "relevance_status": self.relevance_status,
            "activity_status": self.activity_status,
            "access_status": self.access_status,
            "recommended_action": self.recommended_action,
            "ready": self.ready,
            "pilot_size": self.pilot_size,
            "reason": self.reason,
            "conflict": self.conflict,
        }


@dataclass(frozen=True, slots=True)
class PilotPlan:
    entries: tuple[PilotPlanEntry, ...]

    @property
    def manifest(self) -> tuple[PilotPlanEntry, ...]:
        """The concrete first-scan-wave subset: ready now, no sizing conflict."""

        return tuple(
            entry for entry in self.entries if entry.ready and entry.conflict is None
        )

    @property
    def conflicts(self) -> tuple[PilotPlanEntry, ...]:
        return tuple(entry for entry in self.entries if entry.conflict is not None)

    def counts_by_relevance(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for entry in self.entries:
            counts[entry.relevance_status] = counts.get(entry.relevance_status, 0) + 1
        return counts

    def to_dict(self) -> dict[str, Any]:
        manifest = self.manifest
        return {
            "entry_count": len(self.entries),
            "manifest_count": len(manifest),
            "manifest_pilot_items": sum(entry.pilot_size for entry in manifest),
            "conflict_count": len(self.conflicts),
            "counts_by_relevance": self.counts_by_relevance(),
            "entries": [entry.to_dict() for entry in self.entries],
            "manifest": [entry.to_dict() for entry in manifest],
            "conflicts": [entry.to_dict() for entry in self.conflicts],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"

    def to_csv(self) -> str:
        buffer = io.StringIO()
        fieldnames = [
            "ordering",
            "source_id",
            "source",
            "category",
            "target_group",
            "relevance_status",
            "activity_status",
            "access_status",
            "recommended_action",
            "ready",
            "pilot_size",
            "reason",
            "conflict",
        ]
        writer = csv.DictWriter(buffer, fieldnames=fieldnames)
        writer.writeheader()
        for entry in self.entries:
            writer.writerow(entry.to_dict())
        return buffer.getvalue()

    def to_markdown(self) -> str:
        manifest = self.manifest
        lines = [
            "# Reddit source pilot plan",
            "",
            "Curated relevance from the strict source-registry audit, not measured "
            "performance. SECONDARY, DROP, and RECHECK_ACCESS sources are excluded "
            "until their curated state changes.",
            "",
            "## Summary",
            "",
            f"- Plan entries (CORE + PILOT): {len(self.entries)}",
            f"- First-wave manifest entries: {len(manifest)}",
            f"- First-wave manifest pilot items: {sum(e.pilot_size for e in manifest)}",
            f"- Sizing conflicts excluded from the manifest: {len(self.conflicts)}",
        ]
        for relevance, count in sorted(self.counts_by_relevance().items()):
            lines.append(f"- {relevance}: {count}")
        lines += [
            "",
            "## Plan",
            "",
            "| # | Source | Category | Relevance | Activity | Access | Ready | "
            "Pilot size | Reason |",
            "|---:|---|---|---|---|---|---|---:|---|",
        ]
        for entry in self.entries:
            reason = (entry.reason or "").replace("|", "/")
            lines.append(
                f"| {entry.ordering} | {entry.source_name} | {entry.category or ''} | "
                f"{entry.relevance_status} | {entry.activity_status or ''} | "
                f"{entry.access_status} | {'yes' if entry.ready else 'no'} | "
                f"{entry.pilot_size} | {reason} |"
            )
        return "\n".join(lines) + "\n"


def _access_status(recommended_action: str | None, relevance_status: str) -> str:
    if recommended_action in ACCESS_RECHECK_ACTIONS or relevance_status == "RECHECK_ACCESS":
        return "RECHECK_REQUIRED"
    return "NOT_FLAGGED"


def _pilot_size(
    *, relevance_status: str, strict_pilot_posts: int | None, pilot_posts: int | None
) -> tuple[int, bool]:
    """Return (size, used_default). Explicit zero is authoritative, never a fallback."""

    if strict_pilot_posts is not None:
        return strict_pilot_posts, False
    if pilot_posts is not None:
        return pilot_posts, False
    return DEFAULT_PILOT_SIZE.get(relevance_status, 0), True


def build_pilot_plan(repository: Repository) -> PilotPlan:
    """Build the deterministic CORE/PILOT scan plan from curated registry rows.

    Reads only `source_registry_profiles` (curated seed data). Never reads or
    writes `source_metrics` (observed performance), so plan generation cannot
    promote, demote, or otherwise mutate empirical source state.
    """

    placeholders = ", ".join("?" for _ in PILOT_RELEVANCE_STATES)
    rows = repository.connection.execute(
        f"""SELECT s.id AS source_id, s.name AS source_name,
                   p.primary_industry, p.professions_json, p.strict_relevance,
                   p.activity_status, p.recommended_action, p.strict_reason,
                   p.rationale, p.notes, p.pilot_posts, p.strict_pilot_posts
            FROM source_registry_profiles AS p
            JOIN sources AS s ON s.id = p.source_id
            WHERE p.strict_relevance IN ({placeholders})
              AND s.lifecycle <> 'EXCLUDED'""",
        PILOT_RELEVANCE_STATES,
    ).fetchall()

    staged: list[tuple[int, int, str, str, PilotPlanEntry]] = []
    for row in rows:
        relevance_status = str(row["strict_relevance"])
        recommended_action = row["recommended_action"]
        ready = recommended_action in READY_RECOMMENDED_ACTIONS
        strict_pilot_posts = (
            int(row["strict_pilot_posts"]) if row["strict_pilot_posts"] is not None else None
        )
        pilot_posts = int(row["pilot_posts"]) if row["pilot_posts"] is not None else None
        pilot_size, used_default = _pilot_size(
            relevance_status=relevance_status,
            strict_pilot_posts=strict_pilot_posts,
            pilot_posts=pilot_posts,
        )
        conflict = None
        if ready and pilot_size == 0 and not used_default:
            conflict = (
                "recommended_action signals the source is ready to scan, but the "
                "registry supplies an explicit pilot size of zero"
            )
        professions = tuple(json.loads(row["professions_json"] or "[]"))
        target_group = ", ".join(professions) or None
        reason = row["strict_reason"] or row["rationale"] or row["notes"]
        readiness_rank = 0 if ready else 1
        industry_key = (row["primary_industry"] or "").casefold()
        name_key = str(row["source_name"]).casefold()
        entry = PilotPlanEntry(
            ordering=0,
            source_id=int(row["source_id"]),
            source_name=str(row["source_name"]),
            category=row["primary_industry"],
            target_group=target_group,
            relevance_status=relevance_status,
            activity_status=row["activity_status"],
            access_status=_access_status(recommended_action, relevance_status),
            recommended_action=recommended_action,
            ready=ready,
            pilot_size=pilot_size,
            reason=reason,
            conflict=conflict,
        )
        sort_key = (
            _RELEVANCE_RANK[relevance_status],
            readiness_rank,
        )
        staged.append((sort_key[0], sort_key[1], industry_key, name_key, entry))

    staged.sort(key=lambda item: (item[0], item[1], item[2], item[3], item[4].source_id))
    ordered_entries = tuple(
        _with_ordering(entry, index)
        for index, (*_rest, entry) in enumerate(staged, start=1)
    )
    return PilotPlan(entries=ordered_entries)


def _with_ordering(entry: PilotPlanEntry, ordering: int) -> PilotPlanEntry:
    return PilotPlanEntry(
        ordering=ordering,
        source_id=entry.source_id,
        source_name=entry.source_name,
        category=entry.category,
        target_group=entry.target_group,
        relevance_status=entry.relevance_status,
        activity_status=entry.activity_status,
        access_status=entry.access_status,
        recommended_action=entry.recommended_action,
        ready=entry.ready,
        pilot_size=entry.pilot_size,
        reason=entry.reason,
        conflict=entry.conflict,
    )
