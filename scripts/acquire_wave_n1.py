"""Wave N+1 acquisition: 20 communities x 250 posts via Arctic Shift (EUR0, resumable).

Writes data/reddit/wave_n1.db. Never touches the holdout DB.
Re-running is safe: duplicate external_ids are skipped by the repository layer.
"""
from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path("/home/zunnun/projects/SaasPainPonit")
sys.path.insert(0, str(ROOT / "src"))

from problem_intelligence.arctic_shift import (  # noqa: E402
    ArcticShiftConfig,
    ArcticShiftRedditProvider,
)
from problem_intelligence.arctic_shift_poc import run_poc  # noqa: E402
from problem_intelligence.live_pilot import read_live_manifest_csv  # noqa: E402
from problem_intelligence.repository import Repository  # noqa: E402

MANIFEST = ROOT / "docs/providers/wave-n1-manifest.csv"
DB = ROOT / "data/reddit/wave_n1.db"
PROGRESS = ROOT / "exports/wave_n1_progress.json"
START, END = "2026-06-01", "2026-08-14"  # before holdout window 2026-08-15..09-05


def main() -> int:
    sources = read_live_manifest_csv(MANIFEST)
    print(f"manifest sources: {len(sources)}")
    import os
    ua = os.environ.get("ARCTIC_SHIFT_USER_AGENT", "")
    provider = ArcticShiftRedditProvider(
        ArcticShiftConfig(user_agent=ua, min_request_interval_seconds=3.0))
    repository = Repository(DB)
    repository.initialize()
    metrics, _ = run_poc(
        repository, provider, sources, per_source_limit=100,
        start_date=START, end_date=END,
    )
    full_ids = repository.full_reddit_source_item_ids()
    payload = {
        "acquired_at": datetime.now(UTC).isoformat(),
        "window": {"after": START, "before": END},
        "status": metrics.status,
        "records_received": metrics.records_received,
        "sources": {k: v["records_returned"] for k, v in metrics.sources.items()},
        "source_failures": {k: v["failure"] for k, v in metrics.sources.items()
                            if v["failure"]},
        "full_usable_items": len(full_ids),
        "screened_items": 0,
        "observations": 0,
        "next_step": "screen+extract with codex_cli (see wave-n1 goal task)",
    }
    PROGRESS.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print("status:", metrics.status, "| received:", metrics.records_received,
          "| FULL usable:", len(full_ids))
    if metrics.failures:
        print("failure codes:", metrics.failures)
    repository.close()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
