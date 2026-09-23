"""Generate the wave N+1 report: funnel, recurrence, cross-holdout family overlap."""
from __future__ import annotations

import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path("/home/zunnun/projects/SaasPainPonit")
sys.path.insert(0, str(ROOT / "src"))

from problem_intelligence.clustering import cluster_exact  # noqa: E402
from problem_intelligence.repository import Repository  # noqa: E402
from problem_intelligence.signal_policy import (  # noqa: E402
    is_strong_individual_signal,
)

WAVE_DB = ROOT / "data/reddit/wave_n1.db"
HOLDOUT_DB = ROOT / "data/reddit/automated_holdout.db"


def main() -> int:
    repo = Repository(WAVE_DB)
    repo.initialize()
    res = cluster_exact(repo)
    c = repo.connection
    screened = c.execute("""SELECT COUNT(DISTINCT source_item_id)
        FROM structured_inference_attempts
        WHERE stage='SCREENING' AND failure_code IS NULL""").fetchone()[0]
    total_full = len(repo.full_reddit_source_item_ids())
    obs = c.execute("""SELECT o.problem_family, o.problem, si.url,
        o.actor, o.job_to_be_done, o.context, o.current_workaround,
        o.time_impact, o.financial_impact, o.active_solution_search,
        o.switching_intent, o.problem_type
        FROM problem_observations o
        JOIN source_items si ON si.id = o.source_item_id ORDER BY o.id""").fetchall()
    recurring = c.execute("""SELECT cluster_id, COUNT(*) n FROM cluster_members
        GROUP BY cluster_id HAVING n > 1""").fetchall()
    # cross-check vs holdout families (semantic, family-level, conservative)
    hc = sqlite3.connect(HOLDOUT_DB)
    holdout_fams = {r[0] for r in hc.execute(
        "SELECT DISTINCT problem_family FROM problem_observations")}
    hc.close()
    strong = 0
    for o in obs:
        strong += int(is_strong_individual_signal(
            allowed_problem_type=o["problem_type"] not in
            ("TEMPORARY_INCIDENT", "SUPPORT_QUESTION", "USER_ERROR"),
            has_actor=bool(o["actor"]), has_job=bool(o["job_to_be_done"]),
            has_context=bool(o["context"]), has_workaround=bool(o["current_workaround"]),
            has_quantified_impact=bool(o["time_impact"] or o["financial_impact"]),
            has_payment=False, active_search=bool(o["active_solution_search"]),
            switching_intent=bool(o["switching_intent"])))
    fam_counts: dict[str, int] = {}
    for o in obs:
        fam_counts[o["problem_family"]] = fam_counts.get(o["problem_family"], 0) + 1
    repeats = {k: v for k, v in fam_counts.items() if v >= 2}
    lines = [
        "# Welle N+1 — Report",
        "",
        f"Stand: {screened}/{total_full} gescreent (wave_n1.db, €0-Arctic-Shift).",
        "",
        "## Trichter",
        "",
        f"- FULL-Items: {total_full} | gescreent OK: {screened}"
        f" | Observations: {len(obs)} | strong signals: {strong}",
        f"- Exact-Cluster: {res.cluster_count} für {res.observation_count}"
        f" Observations; Duplikat-Cluster (harte Rekurrenz): {len(recurring)}",
        "",
        "## Family-Repetition innerhalb der Welle (>=2 Observations)",
        "",
    ]
    if repeats:
        for fam, n in sorted(repeats.items(), key=lambda kv: -kv[1]):
            cross = " + HOLDOUT" if fam in holdout_fams else ""
            lines.append(f"- {fam}: {n}×{cross}")
    else:
        lines.append("- (noch keine)")
    lines += ["", "## Observations (alle)", ""]
    for o in obs:
        m = re.search(r"/r/(\w+)", o["url"] or "")
        lines.append(
            f"- [{m.group(1) if m else '?'}/{o['problem_family']}] {o['problem'][:130]}")
    (ROOT / "exports/wave_n1_report.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"screened {screened}/{total_full} | obs {len(obs)} | strong {strong}"
          f" | dup-clusters {len(recurring)} | family-repeats {repeats}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
