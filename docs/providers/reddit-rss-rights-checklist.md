# Reddit RSS: access basis and rights checklist

Status: **CONTRACT_REVIEW_REQUIRED** in code (`RedditRssProvider.readiness`). This
provider is not marked `PRODUCTION_APPROVED` by this codebase, even though a live
PoC has run successfully — that determination stays a human, documented decision.

## Access basis

Reddit's `robots.txt` disallows automated access to all paths for all user agents
(`Disallow: /`), with no `.rss`-specific exception. On its own, that would rule out
this provider entirely, per the project's own constraint: "do not use endpoints
Reddit disallows for automated crawling."

The project owner confirmed in-session (2026-09-19) that a specific arrangement
with Reddit exists that permits this access despite the general `robots.txt`
disallow. That confirmation is a business/legal representation by the project
owner; it is **not independently verified by this codebase** and no durable written
reference (contract, program enrollment confirmation, correspondence) is attached
here yet. Replace this note with that reference as soon as it exists — until then,
anyone reviewing this code should treat the access basis as *asserted, not
documented*.

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
