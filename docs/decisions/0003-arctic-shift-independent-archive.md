# 0003: Arctic Shift is the current zero-cost acquisition candidate, technically validated

Status: **Accepted (technical), rights REVIEW_REQUIRED**. Supersedes ADR 0002's
production conclusion (Reddit RSS is `POLICY_BLOCKED`, see that ADR's correction
section) as the current zero-cost acquisition candidate. The €0 constraint from
ADR 0002 remains unchanged.

## Context

Direct automated access to reddit.com is `POLICY_BLOCKED`: its `robots.txt`
disallows all automated access, and no documented permission exists (ADR 0002
correction). A replacement zero-cost source was needed that does not require
automated requests to reddit.com at all.

Arctic Shift (`https://arctic-shift.photon-reddit.com`) is an independent,
third-party archive of Reddit content. Its own `robots.txt` (`Disallow:` empty
for `User-agent: *`) explicitly permits automated access -- checked live before
any other work began, learning directly from the RSS correction not to treat
technical reachability as authorization without checking the access policy
first this time.

## Decision

`ArcticShiftRedditProvider` (`src/problem_intelligence/arctic_shift.py`)
implements the same `RedditDataProvider` protocol as `RedditRssProvider` and
`BrandwatchRedditProvider` (the feed/data-provider shape from ADR 0001) --
`discover()`/`fetch_fulltext()` share one real HTTP request per query, since
Arctic Shift returns full post objects (including `selftext`) in one response.
No interface was redesigned.

Normalization (`normalize_arctic_shift_record`) reuses the same
`canonicalize_reddit_url` identity and `Repository.ingest_reddit_content`
canonical write path as every other provider. One real bug was found and fixed
during live verification: for link/image posts, the API's `url` field is the
post's external target (e.g. `i.redd.it`), not a Reddit URL; `permalink`
(reddit.com-relative) is the field that reliably identifies the post regardless
of shape.

Content completeness is evidence-based: `is_self=True` with non-empty
`selftext` is FULL; link/image posts (`is_self=False`, empty `selftext`) are
METADATA_ONLY; and — the case that has no analog in the RSS or Brandwatch
providers — removed/deleted posts (`selftext` of `"[removed]"`/`"[deleted]"`,
often with `removed_by_category` set) are excluded from the default research
run entirely (`item=None`), not force-included as if the absence of text were
editorial. Arctic Shift is an archive, so it can return records for content
that no longer exists in a usable form; this provider does not pretend that
absence is content.

`ArcticShiftHealthProvider` implements the existing `source_health.
HealthProvider` protocol unmodified, exactly as `RedditRssHealthProvider` does.

## Access basis vs. usage rights: two separate questions

This ADR draws a distinction the RSS correction made necessary to name
explicitly: *access being technically permitted* (Arctic Shift's `robots.txt`)
is not the same question as *this project having commercial usage rights* to
the data. The former is confirmed for Arctic Shift; the latter is not.
`ArcticShiftRedditProvider.readiness` stays `CONTRACT_REVIEW_REQUIRED` --
distinct from `RedditRssProvider.readiness = POLICY_BLOCKED`, which is a
stronger, different status (access itself prohibited, not merely commercial
terms unconfirmed). See `docs/providers/arctic-shift-rights-checklist.md`.

## Operational findings from the live PoC (2026-09-19)

- 5 of 5 requested communities returned records (r/Accounting,
  r/restaurantowners, r/PropertyManagement, r/HVAC, r/FreightBrokers), 20
  total records, no failures, no rate limiting encountered.
- Freshness: archival lag (retrieved_on - created_utc) was ~12 seconds for the
  newest post checked; the newest available post per community ranged from
  ~2 minutes to ~2 hours old at retrieval time. Not a stale archive.
- Historical access via `after`/`before` (date strings) works as documented,
  verified with a 1-day window before building anything around it.
- Removal rate varied sharply by community in this small (4-item-per-source)
  sample: 0/4 to 4/4. This is far too small a sample to judge any community,
  and is exactly why the next stage stays small (~50/subreddit, ~250 total
  maximum) rather than jumping to the full Wave 1.

See `exports/arctic_shift_reddit_poc.md` / `exports/arctic_shift_reddit_poc_metrics.json`
for the full report, and `data/reddit/arctic_shift_pilot.db` for the 8 real
FULL `SourceItem`s and 2 evidence-grounded `ProblemObservation`s it produced.

## What did not change

`SearchProvider`/`AcquisitionProvider`, `RedditDataProvider`,
`Repository.ingest_reddit_content`, and the two-acquisition-shape architecture
(ADR 0001) are unchanged. `RedditRssProvider`'s generic engineering (Atom
parsing, completeness heuristics, HTTP header handling) remains in the
repository, unused for live traffic while `POLICY_BLOCKED`. `BrandwatchRedditProvider`
remains available but unused.

## Consequences

- Downstream research components remain provider-blind: nothing branches on
  `provider == "arctic_shift"`.
- `reddit_provider_registry.known_provider_rows()` should list `arctic_shift`
  alongside `brandwatch` and `reddit_rss` for observability.
- The next decision (controlled ~250-item second stage, or resolving usage
  rights, or selecting yet another source) is a business decision, not made by
  this ADR.
