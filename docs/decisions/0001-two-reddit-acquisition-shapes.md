# 0001: Two Reddit acquisition shapes, one canonical ingestion boundary

Status: **Accepted**. This is an intentional architecture, not temporary duplication.

## Context

Reddit content can be legitimately acquired in two structurally different ways:

- **URL-discovery acquisition**: a query returns candidate URLs; a separate step
  fetches each one individually. This is the natural shape for search engines,
  targeted verification, and fallback discovery.
- **Feed/data-provider acquisition**: a licensed provider (Brandwatch today) returns
  paginated "mentions" for a standing query, each already carrying most metadata, with
  fulltext sometimes requiring a second retrieval call. This is the natural shape for
  licensed bulk/historical feeds.

The codebase has one abstraction per shape:

```text
SearchProvider + AcquisitionProvider      (reddit.py)
    query -> discovered URL -> acquire(url) -> one page/item

RedditDataProvider                        (reddit_provider.py)
    query -> paginated mentions -> optional fulltext -> RedditProviderRecord
```

`SearchProvider.search(query)` has no concept of pagination or a second fulltext
call; forcing it to model Brandwatch's paginated-mentions-plus-fulltext shape would
make every search adapter carry unused machinery. `RedditDataProvider.discover`
returns a page of raw provider records, not a single discovered URL; forcing it to
pretend every record starts from one discovered link would make Brandwatch page
through mentions one fabricated "discovery" at a time for no benefit. Each
abstraction stays honest about the acquisition pattern it represents.

## Decision

Both acquisition shapes converge on one canonical ingestion boundary instead of a
shared top-level interface:

```text
SearchProvider + AcquisitionProvider  ---\
                                          +--> Repository.ingest_reddit_content --> SourceItem
RedditDataProvider (RedditProviderRecord) --/
```

Concretely:

- `acquire_discoveries` (search-driven path, `reddit.py`) and `ingest_provider_records`
  (feed-driven path, `reddit.py`) are the two adapters. Each turns its own acquisition
  shape into calls against the same `Repository` methods: `record_discovery_response`,
  `Repository.ingest_reddit_content`, and `record_acquisition`.
- `Repository.ingest_reddit_content` is the single canonical write path for Reddit
  content, used by both adapters. It owns:
  - idempotent re-ingestion keyed by `(source_id, normalized_external_id)`
  - completeness precedence (`FULL` > `PARTIAL` > `METADATA_ONLY`): content is never
    downgraded by a later, less-complete acquisition
  - conflict handling: two `FULL` payloads for the same identity that disagree are
    flagged in `metadata.content_conflicts` and the original is kept, never merged or
    silently overwritten
  - the `FULL`-completeness attestation check (`body_complete` + a timezone-aware
    `retrieved_at`), previously duplicated inline in `acquire_discoveries`
  - the evidence-integrity guard inherited from `upsert_source_item`: text cannot
    change once an evidence span points into it
- `discovery_records` / `acquisition_records` (already in `schema.sql`) is the shared
  provenance ledger for both shapes. A `SourceItem` acquired via both a search
  provider and a feed provider keeps one row per provider in `acquisition_records`,
  never a duplicate `SourceItem`.
- Reddit identity (`canonicalize_reddit_url`, `RedditIdentity.external_id`) is the
  single dedup key for both shapes; a submission and its own comment always produce
  different identities and are never collapsed into one `SourceItem`.

## What did not change

`SearchProvider`, `AcquisitionProvider`, and `RedditDataProvider` keep their existing
shapes and names — they already represent their acquisition pattern accurately.
`Repository.upsert_source_item` (the plain, non-Reddit-specific connector path used by
`ingestion.py` for JSONL/manual imports) is unchanged; `ingest_reddit_content` wraps
it rather than replacing it, so generic non-Reddit connector ingestion is unaffected.

## Consequences

- Downstream components (prefilter, pain classification, extraction, clustering,
  source metrics) only ever see `SourceItem`/`Repository` state. They have no reason
  to branch on which provider acquired a given item, and none of the code in this
  repository does.
- A future licensed Reddit provider only needs to implement `RedditDataProvider` (and
  pass `tests/reddit_provider_conformance.py`) to reuse `ingest_provider_records`
  as-is; no research-layer change is needed.
- A future URL-discovery source only needs `SearchProvider`/`AcquisitionProvider`; it
  reuses `acquire_discoveries` as-is.
- See `tests/test_reddit_canonical_ingestion.py` for the cross-path regression
  coverage: same submission via both paths, submission-vs-comment identity, comment
  dedup across paths, `METADATA_ONLY -> FULL` enrichment, `FULL` never downgraded by a
  later `PARTIAL`, conflicting `FULL` payloads, repeated same-provider re-ingestion,
  and observation idempotency (including the enrichment-after-evidence rejection
  case).
