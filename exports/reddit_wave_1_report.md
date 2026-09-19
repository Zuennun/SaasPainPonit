# Reddit Wave 1 — operational validation

Status: **FIX_AND_RETRY**. This is a preflight report, not a completed 2,500–3,500-item pilot.

## Acquisition

- Planned communities: 25; ACTIVE health: 0; policy-ready: 0; acquisition-eligible: 0.
- Unique URLs captured in the Wave 1 database: 0.
- Provider-attested FULL items: 0. Target: approximately 2,500–3,500.
- No official Reddit API, bypass, proxy rotation, or private endpoint was used.
- Source-policy readiness is an independent gate: `REVIEW_REQUIRED` does not authorize bulk acquisition. A provider's permitted use and retention rules must be documented before execution.
- `target_items` is the planned sample size; actual requested-item counts are reported only when every provider search request records its requested count.

## Completeness and research quality

FULL requires a provider body-complete attestation and retrieval timestamp; a search snippet is not FULL. With no full items, usable-item rates, community yield, extraction precision, and false-negative rates are unknown—not zero.

## Cost

Acquisition cost is shown separately in the metrics CSV when provider records are complete. Model/analysis cost has no exact per-community attribution, so processing cost and cost per strong signal remain unknown—not $0.

## Human review and false positives

No FULL Wave 1 items exist; positive and negative review samples are unavailable.

## Failure and recommendation

Direct ordinary public HTTP retrieval returned 403 for a sampled Reddit post on 2026-09-19. Browser-based viewing confirmed individual public content can sometimes be visible, but this is not a reproducible 100–150-item-per-community acquisition path. The probe is recorded in `data/reddit/health_wave_1_http_probe_2026-09-19.jsonl`. Do not infer poor community relevance from connector failure.

Recommendation: **FIX_AND_RETRY** until a permitted, reproducible public discovery and full-content provider has measured latency, cost, and rights, and human review confirms extraction quality. Do not automatically expand to Wave 2 or the 319-source manifest.
