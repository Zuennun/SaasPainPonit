# Reddit RSS: access basis and rights checklist

Status: **POLICY_BLOCKED** in code (`RedditRssProvider.readiness`). Direct
automated access to reddit.com RSS is withdrawn as a live acquisition path.
Nothing in this codebase may make a live request against reddit.com under this
provider until this status changes.

## CORRECTION (2026-09-19)

A live PoC ran against reddit.com's RSS feeds on the basis of an in-session verbal
confirmation that "a specific arrangement with Reddit" permitted it. On review,
that basis was insufficient: no durable written reference was ever attached, and
Reddit's `robots.txt` remains an unambiguous, unqualified `Disallow: /` for all
user agents on all paths. Technical reachability and one plausible-sounding
confirmation must not be read as authorization. The correct default, absent a
documented reference, is that this path is **policy-blocked**.

The 50 SourceItems and 2 manually-extracted observations that PoC produced were
withdrawn from the approved research dataset; see
`exports/experimental/reddit_rss/README.md` and
`data/reddit/experimental/README.md`. The engineering findings from that run
(Atom feed structure, rate-limit behavior, HTTP header handling) remain valid and
are kept as a technical record.

## Access basis

Reddit's `robots.txt` disallows automated access to all paths for all user agents
(`Disallow: /`), with no `.rss`-specific exception. Per the project's own
constraint ("do not use endpoints Reddit disallows for automated crawling"), that
rules this provider out for live use entirely, absent one specific thing:

A durable, written reference — a contract, a Reddit research-program enrollment
confirmation (referenced in `robots.txt`'s own comments), or equivalent
correspondence — establishing that Reddit has explicitly permitted this project's
automated RSS access despite the general disallow. **No such reference currently
exists in this repository.** Until one is added here, this provider stays
`POLICY_BLOCKED` regardless of any other confirmation, technical success, or
prior PoC result.

This provider still refuses to do several things regardless of that arrangement,
because they were never covered by it and remain generically prohibited:

- `.json` endpoints, the official Reddit API, or OAuth
- Reddit's search RSS endpoint
- comment RSS / comment collection of any kind (deferred, not implemented)
- CAPTCHA bypass, proxy rotation, or account rotation to work around a restriction

## Operational constraints actually enforced in code

- `RedditRssProvider` defaults to a 90-second minimum interval between real HTTP
  requests to the same or different subreddits (`RedditRssConfig.
  min_request_interval_seconds`), configurable but never removed.
- `discover()` followed by `fetch_fulltext()` for the same query makes **one** HTTP
  request, not two — RSS delivers full content in a single response.
- ETag/Last-Modified are sent as `If-None-Match`/`If-Modified-Since` on every poll
  after the first; a `304 Not Modified` is treated as a successful poll with no new
  content, not as a failure.
- `429 Too Many Requests` is mapped to `ProviderFailure.RATE_LIMITED` with
  `Retry-After` parsed when present; `compute_backoff_seconds` provides conservative
  exponential backoff (90s → 180s → 360s → 720s → capped) when it is absent. Neither
  path retries immediately or rotates identity.

## Unresolved questions to track once a written reference exists

1. What is the exact scope of the arrangement — which subreddits, what request
   volume, what retention period for collected content?
2. Does it cover only discovery (title/URL) or also self-text body content?
3. Does it permit storing collected content in our own database indefinitely, or is
   a retention limit implied?
4. Does it permit downstream AI/LLM processing (classification, extraction,
   embeddings) of collected content?
5. Does it permit displaying derived research (not raw Reddit text) to paying SaaS
   customers?
6. What attribution, if any, is required when referencing a Reddit post?

## Current scope

Top-level subreddit posts only (no comments). Discovery comes only from our own
curated subreddit registry — never Reddit's search RSS. RSS is treated as a
forward-looking, rolling-recent source, not a historical archive; our own database
becomes the historical dataset over repeated polling, not Reddit's feed.
