# Reddit live pilot readiness

Status: **EXECUTION_BLOCKED**. No real pilot has been executed to produce this report.

## Manifest

- Sources selected: 25 (target: 20-25 CORE sources spread across curated categories).
- Requested items per source: 100. Total requested items: 2500.
- Manifest is provider-independent: it stores no Brandwatch query IDs or other provider-specific configuration (`exports/reddit_wave1_live_manifest.csv`).

## Providers

```
Provider    Technical  Credentials  Rights                    Production
brandwatch  READY      MISSING      CONTRACT_REVIEW_REQUIRED  BLOCKED   
```

Selected provider for this readiness check: **brandwatch**.

## Blockers to a real run

- provider credentials are not available in the environment
- provider configuration (e.g. query IDs) is missing or invalid
- rights status is CONTRACT_REVIEW_REQUIRED, not PRODUCTION_APPROVED

## Acquisition architecture status

Frozen; considered structurally complete (`docs/decisions/0001-two-reddit-acquisition-shapes.md`). Both the URL-discovery and feed/data-provider acquisition paths converge on `Repository.ingest_reddit_content`. This readiness phase does not change them.

## Evaluation readiness

No evaluation-suite manifest is configured yet (`problem_intelligence.cli evaluation-readiness` requires one). Evaluation readiness for this pilot's own output is therefore unmeasured, not passing.

## Manual-review export

`exports/reddit_wave1_review.csv` exists with the full review schema (problem statement, actor, workaround, impact, payment signal, evidence text, completeness, provider, and blank `human_*`/`reviewer_notes` columns for manual labeling) but currently has zero rows: no real FULL Reddit content has been acquired yet, and this export never fabricates one to fill the file.

## Command that will execute the pilot once unblocked

```bash
python -m problem_intelligence.cli reddit-live-pilot \
  --provider brandwatch --database <path-to-a-real-database-file> \
  --manifest exports/reddit_wave1_live_manifest.csv \
  --max-sources 25 --max-items-per-source 100 \
  --state exports/reddit_live_pilot_state.json
```

This phase does not claim a real run occurred; every count above comes from the curated registry and dry-run estimation only, never a live provider call.
