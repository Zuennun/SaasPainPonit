# 0002: Public subreddit RSS is the current zero-cost production acquisition path

Status: **Superseded by correction below (2026-09-19)**. Direct automated access
to reddit.com RSS is **not** approved for production use: reddit.com's
`robots.txt` disallows automated access, and the original acceptance of this ADR
relied on an unverified verbal confirmation rather than a documented reference.
`RedditRssProvider.readiness` is `POLICY_BLOCKED`. The technical design and
engineering findings below remain accurate and the code is kept (see
"Correction" section at the end); only the production-readiness conclusion is
withdrawn. Official Reddit API access is still not assumed and is not part of
this plan. Paid Reddit data providers (Brandwatch, Sprinklr, or similar) are
still not part of the current roadmap; Brandwatch's implementation remains in the
repository as an optional future provider (see
`docs/decisions/0001-two-reddit-acquisition-shapes.md`) and is not deleted, but
it is not depended on.

## Context

The project has a hard constraint: Reddit data acquisition must cost €0. No paid
provider, no official API. The only remaining free, public source is Reddit's
per-subreddit RSS/Atom feed (`https://www.reddit.com/r/<subreddit>/.rss`).

Reddit's `robots.txt` disallows automated access to all paths for all user agents
(`Disallow: /`), with no exception for `.rss`. On its own this would rule the path
out entirely. The project owner confirmed in-session (2026-09-19) that a specific
arrangement with Reddit exists that permits this access despite that general
disallow; that confirmation is a business/legal representation, not independently
verified by this codebase. See
`docs/providers/reddit-rss-rights-checklist.md` for the exact status and the
unresolved questions to track once a durable written reference exists.

## Decision

`RedditRssProvider` (`src/problem_intelligence/reddit_rss.py`) implements the
existing `RedditDataProvider` protocol (the feed/data-provider acquisition shape
from ADR 0001) rather than `SearchProvider`/`AcquisitionProvider`: one RSS request
returns several full records in one response, closer to Brandwatch's paginated-
mentions shape than to discover-a-URL-then-acquire-it. No existing interface was
redesigned; `ProviderPage.records` was widened from `tuple[dict[str, Any], ...]` to
`tuple[Any, ...]` because it was always meant to be opaque per-provider data (the
docstring already said so) and Brandwatch's dict shape had leaked into the type
itself — this is the one "concrete incompatibility" exception the architecture
freeze allows.

`discover()` and `fetch_fulltext()` share one real HTTP request per subreddit per
poll: RSS delivers full content in a single response, so there is no separate
fulltext step to make. `fetch_fulltext()` reuses the page `discover()` just fetched
rather than issuing best-effort-avoidable second request.

Normalization (`normalize_rss_entry`) reuses the same `canonicalize_reddit_url`
identity and `Repository.ingest_reddit_content` canonical write path as every other
provider — no new ingestion logic was written for RSS. Completeness classification
is evidence-based, not assumed: Reddit's Atom feed wraps real self-text in
`<!-- SC_OFF --><div class="md">...</div><!-- SC_ON -->`; link/image posts carry
only the always-present `submitted by ... [link] [comments]` footer with no
wrapper. That structural marker — not content length — is what separates FULL from
METADATA_ONLY. No PARTIAL case has been observed live; Reddit's feed appears to
deliver either the complete body or none.

`RedditRssHealthProvider` implements the existing `source_health.HealthProvider`
protocol so RSS pollability becomes one more input to the existing, unmodified
`classify_health` logic — no new health-status vocabulary was introduced.

## Operational findings from the live PoC (2026-09-19)

- Reddit's rate limit is a shared, IP-wide budget (`X-Ratelimit-Remaining`,
  `X-Ratelimit-Reset`), not per-subreddit, with an observed ~60-second reset
  window. The task's own conservative 90-second default between requests is
  empirically justified by this, not arbitrary.
- Reddit does not send a standard `Retry-After` header on 429; it sends
  `X-Ratelimit-Reset` (seconds until reset) instead. The provider now falls back to
  that header.
- HTTP/2 responses (observed live) return all header names lowercased. The
  original exact-case lookups (`ETag`, `Last-Modified`, `Retry-After`) would have
  silently failed against a real server; header lookup is now case-insensitive.
- 4 of 5 planned PoC sources succeeded; the fifth was rate-limited across this
  session's repeated attempts and needs a routine retry, not remediation — a 429
  is explicit and distinguishable from `NO_RESULTS`, so it is never misread as a
  bad or inactive source.

See `exports/reddit_rss_poc.md` / `exports/reddit_rss_poc_metrics.json` for the
full PoC report, and `data/reddit/reddit_rss_pilot.db` for the 50 real
`SourceItem`s it produced.

## What RSS is, and is not

RSS is a rolling, forward-looking view of recent activity (Reddit's feed returns
roughly the most recent ~25 posts per subreddit), not a historical archive. The
project's own database becomes the historical dataset by polling repeatedly and
relying on the existing idempotent canonical ingestion to store only genuinely new
items each time. Wave 1's goal under RSS is therefore reframed: validate
continuous acquisition across the curated communities, not force a fixed
historical item count out of a feed that was never designed to provide one.

Only top-level subreddit posts are collected. Comment collection and Reddit's
search RSS endpoint are both explicitly out of scope for this phase (not merely
unimplemented) — comments may be reassessed later; search RSS is unnecessary
because discovery comes entirely from the project's own curated subreddit
registry.

## Consequences

- Downstream research components remain provider-blind: nothing in prefilter,
  extraction, clustering, or evidence logic branches on `provider == "reddit_rss"`.
  Provider-specific logic (parsing Atom XML, the SC_OFF/md heuristic, rate-limit
  header handling) lives entirely inside `reddit_rss.py`, below the canonical
  ingestion boundary.
- A future licensed provider (Brandwatch or otherwise) can still be activated
  later without touching this provider or the research layer, per ADR 0001.
- `reddit_provider_registry.known_provider_rows()` now lists both `brandwatch` and
  `reddit_rss`; neither is marked `PRODUCTION_APPROVED` automatically.

## Correction (2026-09-19)

The decision above was accepted and a live 5-source PoC was run on the strength of
an in-session verbal confirmation that "a specific arrangement with Reddit"
permitted automated RSS access despite `robots.txt`. That was insufficient: no
durable written reference was ever obtained, and technical reachability plus one
plausible-sounding confirmation is not authorization. `RedditRssProvider.readiness`
is now `ProductionReadiness.POLICY_BLOCKED` — a status distinct from
`CONTRACT_REVIEW_REQUIRED` (merely unconfirmed): it means actively prohibited by
the target's own stated policy unless and until explicit, documented permission
exists. `reddit_rss_poc.main()` refuses to run while this status holds, with no
override flag.

What stays true and reusable regardless: the generic engineering work (Atom
parsing, Reddit identity extraction, completeness classification, case-insensitive
HTTP header handling, 429/`Retry-After`/`X-Ratelimit-Reset` handling, and the
canonical-ingestion/idempotency tests) — see `docs/decisions/0001-two-reddit-
acquisition-shapes.md`, which this provider still correctly implements. What is
withdrawn: the conclusion that this is a currently-usable production acquisition
path, and the research data the PoC produced (moved to
`exports/experimental/reddit_rss/` and `data/reddit/experimental/`, explicitly
excluded from the approved research dataset).

The project's zero-cost constraint remains in force; the next candidate under
evaluation is an independent, non-reddit.com archive (Arctic Shift), specifically
because it does not require automated requests to reddit.com at all.
