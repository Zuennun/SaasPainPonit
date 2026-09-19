# Reddit RSS Wave 1 expansion plan (prepared, not executed)

Per `exports/reddit_rss_poc.md`: recommendation is **RSS_READY_FOR_WAVE_1**. This
document prepares the 25-source expansion; it does not run it.

## Manifest

Reuse the existing, already-generated, provider-independent manifest:
`exports/reddit_wave1_live_manifest.csv` (25 CORE, ready, curated sources spread
across 25 distinct categories — see `docs/decisions/0002-reddit-rss-free-acquisition.md`
and the prior live-pilot readiness work). No new source selection is needed; it
contains no Brandwatch query IDs or other provider-specific configuration, so it
works unchanged for RSS.

## What changes from the 5-source PoC

- **Item target per source**: the manifest currently lists `pilot_item_target = 100`
  (set for a hypothetical bulk-capable provider). RSS returns at most ~25 most-recent
  posts per subreddit per poll — Wave 1 under RSS should not try to force 100 items
  out of a single poll. Reframe the per-source target to "whatever the current feed
  returns" (typically 10-25), consistent with `docs/decisions/0002-...`'s point that
  RSS is forward-looking, not historical: repeated scheduled polling accumulates the
  historical dataset over time, a single pass does not need to.
- **Request budget**: 25 sources × 1 request per source per pass (discover and
  fetch_fulltext share one request) = 25 real requests. At the empirically-validated
  90-second minimum interval, one full pass takes at least ~37.5 minutes serial,
  single-threaded, never parallelized across sources.
- **Rate-limit headroom**: the 5-source PoC showed Reddit's budget is shared across
  the whole session (IP-wide), not per-subreddit. 25 sequential requests at 90s
  spacing should comfortably stay under it, but the run must still tolerate
  individual 429s (via `RedditRssError`/`ProviderFailure.RATE_LIMITED` and
  `compute_backoff_seconds`) without aborting the whole pass — exactly the
  resumable, failure-safe design already built in `live_pilot.run_live_pilot`
  (per-source PENDING/RUNNING/COMPLETE/FAILED/SKIPPED state, persisted to disk,
  safe to resume).

## How it would run

Extend the existing `reddit-live-pilot` CLI command (`src/problem_intelligence/
cli.py`, built in a prior session for the provider-neutral live pilot runner) with
a `reddit_rss` adapter analogous to `brandwatch_live_adapter.py`: compose
`RedditRssProvider.discover`/`fetch_fulltext`, `normalize_rss_entry`, and the
already-generic `ingest_provider_records` into a `live_pilot`-compatible
`acquire_source` callable — the same pattern already proven for Brandwatch, no new
canonical-ingestion code. `reddit_rss_poc.py`'s simpler, standalone runner (used
for the 5-source PoC) demonstrates the same composition at smaller scale and could
be extended directly instead, if a lighter-weight path is preferred over wiring a
second provider into `reddit-live-pilot`.

## Explicitly not done here

- No code changes were made to execute this.
- No 25-source live run has occurred.
- No expansion beyond 25 (50 / 100 / 255 CORE-ready) is planned or prepared yet —
  per the task, that only follows observing requests/day, new items/day, problem
  signal yield, and rate-limit behavior from the 25-source run once it happens.
