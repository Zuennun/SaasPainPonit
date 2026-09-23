"""Wave N+1 screening (resumable via inference cache; provider from env).

Screens every FULL item in data/reddit/wave_n1.db. Extraction for
POTENTIAL_PAIN items runs automatically within the same pipeline; the
provider precedence (codex first) is enforced by the caller's env choice,
this script only executes. Progress is persisted to exports/wave_n1_progress.json.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

ROOT = Path("/home/zunnun/projects/SaasPainPonit")
sys.path.insert(0, str(ROOT / "src"))

from problem_intelligence.automated_discovery import (  # noqa: E402
    AutomatedDiscovery,
    InferenceConfig,
)
from problem_intelligence.discovery_model import provider_from_environment  # noqa: E402
from problem_intelligence.repository import Repository  # noqa: E402

DB = ROOT / "data/reddit/wave_n1.db"
PROGRESS = ROOT / "exports/wave_n1_progress.json"
BASELINE = ROOT / "data/reddit/arctic_shift_250_pilot.db"


def main() -> int:
    repository = Repository(DB)
    repository.initialize()
    # exclude baseline + holdout Reddit identities by external_id
    from problem_intelligence.automated_holdout import load_baseline_reddit_ids
    excluded: set[str] = set(load_baseline_reddit_ids(BASELINE))
    holdout_db = ROOT / "data/reddit/automated_holdout.db"
    if holdout_db.is_file():
        import sqlite3
        hc = sqlite3.connect(holdout_db)
        excluded |= {str(r[0]) for r in hc.execute(
            "SELECT external_id FROM source_items")}
        hc.close()
    all_full = repository.full_reddit_source_item_ids()
    rows = repository.connection.execute(
        f"SELECT id, external_id FROM source_items WHERE id IN "
        f"({','.join('?' for _ in all_full)}) ORDER BY id", all_full).fetchall()
    ids = tuple(int(r["id"]) for r in rows
                if str(r["external_id"]).casefold() not in excluded)
    print(f"unseen FULL items to process: {len(ids)}")
    if not ids:
        return 0
    provider = provider_from_environment(os.environ)
    config = InferenceConfig(
        temperature=0.0, timeout_seconds=120.0, max_retries=2,
        input_usd_per_million=None, output_usd_per_million=None,
    )
    discovery = AutomatedDiscovery(repository, provider, config)
    # circuit breaker: process in batches, stop early on provider-limit bursts
    BATCH = 25
    agg_processed = agg_pain = agg_fail = 0
    agg_failures: dict[str, int] = {}
    for start in range(0, len(ids), BATCH):
        batch = ids[start:start + BATCH]
        metrics = discovery.run(batch)
        agg_processed += metrics.processed_items
        agg_pain += metrics.potential_pain
        agg_fail += metrics.inference_failures
        for k, v in metrics.failures.items():
            agg_failures[k] = agg_failures.get(k, 0) + v
        unavailable = metrics.failures.get("MODEL_UNAVAILABLE", 0)
        if unavailable >= 3:
            print(f"circuit open at item {start}: {unavailable} MODEL_UNAVAILABLE "
                  f"in batch of {len(batch)} — provider window exhausted")
            break
    payload: dict[str, object] = {}
    if PROGRESS.is_file():
        try:
            loaded = json.loads(PROGRESS.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                payload = {str(k): v for k, v in
                           cast("dict[str, object]", loaded).items()}
        except (OSError, ValueError):
            payload = {}
    total_obs = repository.connection.execute(
        "SELECT COUNT(*) FROM problem_observations").fetchone()[0]
    payload.update({
        "last_run_at": datetime.now(UTC).isoformat(),
        "last_provider": provider.name,
        "processed_items": agg_processed,
        "screened_ok_cumulative": repository.connection.execute(
            """SELECT COUNT(DISTINCT source_item_id) FROM structured_inference_attempts
               WHERE stage='SCREENING' AND failure_code IS NULL""").fetchone()[0],
        "potential_pain": agg_pain,
        "valid_observations": total_obs,
        "failures": agg_failures,
        "inference_failures": agg_fail,
    })
    PROGRESS.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print("processed:", agg_processed, "| potential_pain:", agg_pain,
          "| obs total:", total_obs,
          "| failures:", agg_failures, "| provider:", provider.name)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
