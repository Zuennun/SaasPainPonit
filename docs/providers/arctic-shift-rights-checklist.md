# Arctic Shift: access basis and usage-rights checklist

Status in code (`ArcticShiftRedditProvider.readiness`): **CONTRACT_REVIEW_REQUIRED**.
`technical_status = VALIDATED` (live PoC succeeded, `exports/arctic_shift_reddit_poc.md`).
`usage_rights = REVIEW_REQUIRED`. Technical validation does not change the rights
status; only explicit confirmation can.

## Access basis (confirmed)

`arctic-shift.photon-reddit.com/robots.txt` is:

```
User-agent: *
Disallow:
```

An empty `Disallow` for `User-agent: *` explicitly permits automated access to
all paths. This was checked live *before* building the provider, and is a
materially different situation from direct reddit.com access (`Disallow: /`,
`docs/providers/reddit-rss-rights-checklist.md`). Arctic Shift is a third-party
archive independent of reddit.com; requests go only to
`arctic-shift.photon-reddit.com`, never to reddit.com as a fallback.

Public, unauthenticated access being *technically permitted* is not the same
question as this project having *commercial usage rights* to the data it
returns. The former is confirmed; the latter is not.

## Unresolved usage-rights questions

1. Does Arctic Shift's own terms of use (if any exist beyond `robots.txt`)
   permit commercial use of retrieved content, or only research/personal use?
2. May retrieved post text (title, `selftext`, author) be stored in our own
   database, and for how long?
3. May retrieved content be sent to third-party LLM providers for
   classification, extraction, embeddings, or clustering?
4. After retrieval, do we inherit any obligation to honor subsequent Reddit-side
   deletions or removals (Arctic Shift is an archive; a post later removed on
   Reddit may remain in Arctic Shift's data)?
5. May derived research (`ProblemObservation`s, clusters, aggregate metrics) be
   displayed to paying SaaS customers, independent of the raw text?
6. What attribution, if any, does Arctic Shift or Reddit require when
   referencing content sourced through this archive?
7. Are there any rate, volume, or scope limits stated anywhere (documentation,
   a project page, direct correspondence with the maintainer) beyond what the
   API itself enforces via HTTP 429?
8. Does the same "public content policy" Reddit references in its own
   `robots.txt` (the research/`reddit4researchers` program) apply to a
   commercial SaaS product built on data sourced through a third-party archive,
   or only to direct academic research?

None of these are answered by this codebase. Do not treat technical success as
an answer to any of them.

## Operational constraints actually enforced in code

- `ArcticShiftRedditProvider` defaults to a 3-second minimum interval between
  real HTTP requests (`ArcticShiftConfig.min_request_interval_seconds`),
  configurable. Arctic Shift states it offers no uptime/performance guarantee;
  this project does not optimize for throughput against it and uses
  concurrency of 1 in the PoC runner.
- `discover()` followed by `fetch_fulltext()` for the same query/date-window
  makes **one** HTTP request, not two.
- `429 Too Many Requests` maps to `ProviderFailure.RATE_LIMITED`, with
  `Retry-After` (falling back to `X-Ratelimit-Reset`) parsed when present.
- Removed/deleted content (`selftext` of `"[removed]"`/`"[deleted]"`, or
  `removed_by_category` set) is excluded from the default research run: no
  `SourceItem` is created for it, though the raw record's provenance is
  visible in the PoC's own metrics (`removed_or_deleted_excluded`).
- This provider never requests reddit.com, old.reddit.com, or Reddit RSS/JSON
  as a fallback for content Arctic Shift lacks or has only partially.

## Current scope

Top-level subreddit posts only (no comments). Discovery comes only from our own
curated subreddit registry, using Arctic Shift's documented `/api/posts/search`
endpoint (`subreddit`, `after`, `before`, `limit`) -- no undocumented endpoints
or parameters.
