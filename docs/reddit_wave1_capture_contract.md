# Wave 1 capture contract

The pilot database must contain only Wave 1 captures. The 25-source candidate list is
`data/reddit/wave_1_candidates.csv`; regenerate the executable manifest after health
checks. `ACTIVE` health and a complete, approved source-policy record are separate
prerequisites. Neither a search snippet nor an HTTP 403 establishes subreddit health.

No official Reddit API, access-control workaround, or unlicensed bulk archive is a
fallback. Before importing a real capture, document the provider's permission for this
use, retention/deletion terms, attribution, quoting limits, rate limits, and rights
review in the source-policy fields. A reviewer must confirm that a `FULL` capture is
truly the complete public post body, not just the indexed text.

Discovery captures use the existing `reddit-discover --capture` JSONL interface.
Every result needs a canonicalizable Reddit URL with an explicit subreddit matching
the selected source. URL variants and cross-query discoveries are deduplicated before
acquisition-provider calls. Record non-negative `requested_items` for each search
request when the provider exposes it; otherwise leave it null. The report never
substitutes the target sample size for measured requests.

Acquisition captures use `reddit-acquire --capture`. A `FULL` row requires:

```json
{"provider":"licensed-provider","capabilities":{"supports_search":false,"supports_full_content":true,"supports_comments":false,"supports_date_filter":false,"supports_subreddit_filter":true,"supports_pagination":true,"supports_historical_search":false},"url":"https://www.reddit.com/r/Accounting/comments/example1/","state":"CONTENT_COMPLETE","completeness":"FULL","text":"Complete public post body supplied by the provider","metadata":{"body_complete":true,"retrieved_at":"2026-09-19T12:00:00Z"}}
```

The timestamp must be ISO 8601 with a timezone. `body_complete` is an auditable
provider assertion, not independent proof. `PARTIAL` and `METADATA_ONLY` remain
distinct; `--reddit-full-only` on `export-items` and `extract-predictions` prevents
them from entering the Wave 1 extraction batch. Preserve actual provider latency and
cost where available; unknown values must stay unknown.

To generate the review section, pass the same validated prediction JSONL to
`reddit-wave1-report --predictions`. Positive observations are taken from stored
evidence spans; `NO_PAIN` examples come only from explicit negative prediction
labels. Weak observations are sampled separately. Explicit rejection decisions are
not yet persisted, so `REJECTED` remains unmeasured rather than inferred.
