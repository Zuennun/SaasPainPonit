"""Cron helper: wave progress + stale RUNNING pipeline_runs (read-only report)."""
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path("/home/zunnun/projects/SaasPainPonit")
con = sqlite3.connect(ROOT / "data/reddit/wave_n1.db")
con.row_factory = sqlite3.Row

out = {}
out["obs"] = con.execute(
    "SELECT COUNT(*) FROM problem_observations").fetchone()[0]
out["screened_ok"] = con.execute(
    """SELECT COUNT(DISTINCT source_item_id) FROM structured_inference_attempts
       WHERE stage='SCREENING' AND failure_code IS NULL""").fetchone()[0]
out["runs"] = {r["s"]: r["c"] for r in con.execute(
    "SELECT status s, COUNT(*) c FROM model_runs GROUP BY status")}
stale = con.execute(
    "SELECT * FROM pipeline_runs WHERE status='RUNNING'").fetchall()
out["stale_running"] = [dict(r) for r in stale]
pg = ROOT / "exports/wave_n1_progress.json"
if pg.is_file():
    out["progress"] = json.loads(pg.read_text())
print(json.dumps(out, indent=1, default=str))

if "--fail-stale" in sys.argv and stale:
    import subprocess
    alive = subprocess.run(["pgrep", "-f", "scripts/[s]creen_wave_n1"],
                           capture_output=True, text=True).stdout.strip()
    if alive:
        print("SKIP fail-stale: screen_wave_n1 worker alive:", alive.replace("\n", ","))
        sys.exit(0)
    sys.path.insert(0, str(ROOT / "src"))
    from problem_intelligence.repository import Repository
    repo = Repository(ROOT / "data/reddit/wave_n1.db")
    for r in stale:
        try:
            repo.fail_pipeline_run(r["id"], output_count=0,
                                   error="wave relay cron: worker process dead, marked FAILED")
            print("FAILED", r["id"])
        except Exception as e:  # noqa: BLE001
            print("fail_err", r["id"], repr(e))
