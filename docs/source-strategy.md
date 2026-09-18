# Source strategy

## Reddit phase-one path

Reddit is a discovery source, not evidence of market size. The phase-one path does
not use Reddit OAuth or the official API and does not make direct network requests.
It replays auditable captures produced by an explicitly permitted external search
or page provider:

```text
controlled subreddit registry
  -> deterministic query generator
  -> SearchProvider
  -> DiscoveryRun + DiscoveryRecord
  -> AcquisitionProvider
  -> AcquisitionRecord
  -> eligible SourceItem
  -> existing extraction pipeline
```

The initial registry contains `r/Accounting`, `r/restaurantowners`,
`r/airbnb_hosts`, `r/SEO`, and `r/smallbusiness`. `r/AppIdeas` is a control source
because it often discusses proposed products or republishes other people's pain
rather than providing first-person operator evidence.

## Provider contract

Providers declare whether they support search, full content, comments, date and
subreddit filters, pagination, and historical search. Search results distinguish
`RESULTS`, `NO_RESULTS`, and `SOURCE_UNAVAILABLE`. Acquisition independently uses
`CONTENT_COMPLETE`, `CONTENT_PARTIAL`, `ACQUISITION_FAILED`, or `POLICY_BLOCKED`.
Content completeness is `FULL`, `PARTIAL`, or `METADATA_ONLY`.

Missing text is never reconstructed. Metadata-only records do not create an
extractable source item. Full or partial text must contain at least 40 characters
before it is eligible for extraction.

## Identity and provenance

Reddit submission and comment IDs are stable identities. Canonicalization removes
host aliases, slugs, fragments, and tracking parameters while preserving the
difference between a submission and a comment. Repeated discovery by another
query or provider creates another provenance record, not another research item.

Every discovery retains its provider, exact query, original and canonical URL,
and timestamp. Every acquisition retains its provider, timestamp, state,
completeness, errors, latency, cost, and capability metadata. The resulting
`SourceItem` also carries platform and latest acquisition metadata; the complete
history remains in discovery and acquisition records.

## Query strategy

The deterministic English-first query groups cover:

- manual work: manual operations, spreadsheets, Excel, copy/paste, import/export,
  and CSV;
- friction: pain, frustration, time waste, and tedious work;
- active search: requests for tools, software, alternatives, and recommendations;
- workflow gaps: integration, synchronization, reconciliation, duplication, and
  data entry.

An optional time-context phrase can be appended when the provider cannot express
a native date filter. Keywords only discover candidates; the existing extraction
pipeline makes the problem/no-problem decision.

## Measurement

Reports expose raw sample sizes alongside per-1,000-item rates. Samples below 100
items are labelled descriptive only. Provider cost or latency remains `unknown`
when it was not returned; missing measurements are never rendered as zero.

The current real capture contains public excerpts and is therefore `PARTIAL`.
The next technical blocker is an approved provider that reproducibly supplies
full posts, clearly scoped comments, latency, and cost without access evasion.

## Source registry imports

`sources-import` accepts a CSV with a `subreddit`, `name`, or `community` column.
All other columns from the historical 647-source registry are stored verbatim in
the `legacy-csv` metadata namespace. Old scores neither change lifecycle nor set
scan priority. Sources remain `CANDIDATE` until current measured evidence supports
a deliberate lifecycle change.

Curated audit columns are additionally normalized into `source_registry_profiles`.
This includes industry, professions, canonical URL, normalized audience type,
activity evidence, curation priority, research role, scan recommendation, pilot
size, and verification date. Compound or legacy audience labels are retained as
segments while the canonical audience type uses the product vocabulary. The
import is idempotent and validates constrained values before its first write.

The original scan directive is retained (`JA`, `JA_LIGHT`, `NUR_SEKUNDAER`, or a
negative verification state); a separate boolean only indicates immediate primary
or light-scan eligibility. This prevents a secondary-only source from being
silently collapsed into an ordinary scan candidate.

`sources-plan` provides a deterministic view of immediate primary and light-scan
candidates, ordered by the audit's curation band and then by industry and name.
It excludes `NUR_SEKUNDAER` and negative verification states. The output reports
commercial-use readiness separately; an imported recommendation never overrides
the policy gate required for production acquisition.

## Persisted performance measurements

`source-metrics-refresh` materializes versioned, idempotent source-performance
snapshots from stored items, observations, clusters, discovery provenance, and
known provider costs. The command calculates pain, strong-signal, active-search,
payment, and cluster-contribution yields per 1,000 scanned items. Cross-source
confirmations are derived from persisted cluster memberships rather than keyword
overlap.

Missing measurement capability is not represented as zero. Promotion remains
unknown until a promo classifier exists. Quantified impact is counted only from
normalized impact signals carrying explicit quantified semantics, value, unit,
and exact evidence. The current source snapshot cost covers discovery and
acquisition operations and remains unknown whenever any such contributing
operation lacks cost data. Exact model costs live in the operation ledger but are
not divided across sources until an adapter supplies auditable per-source
attribution. Samples below 100 items are labelled descriptive only.

Source routing is also materialized per versioned problem-ontology family. These
rows keep `RECONCILIATION`, `INTEGRATION`, `SCHEDULING`, and the other v1 families
separate from observation classifications such as `WORKFLOW_GAP` or
`TEMPORARY_INCIDENT`. Per-family observation, strong-signal, active-search,
payment, and cluster yields can therefore guide future problem-specific scans.

`scan_now`, priority bands, and recommended actions are curation inputs, not
empirical source-performance scores. Importing them never promotes a source out
of `CANDIDATE`, and legacy `prio_score` values remain historical metadata only.

`source-performance` reads only persisted current measurements and sorts by one
named dimension at a time: strong-signal, payment, active-search, cluster, or
cross-source yield; exact known cost per strong signal; or evidence recency. It
exposes no composite score. Minimum sample, lifecycle, policy readiness, and limit
filters are explicit. Tiny samples remain visible with a warning rather than being
silently treated as reliable rankings.

Lifecycle is still a deliberate operator decision. In particular, an exploratory
source is not demoted after one empty pilot. Running the view separately for
`CANDIDATE`/`EXPLORATION` and `CORE` provides an exploration lane while allowing
measured yield to inform later scan allocation.

`source-budget-plan` turns that review into an explicit item budget. The operator
must provide total capacity, reserved exploration capacity, a per-source cap, and
the minimum measured sample. The performance lane ranks `CORE` and eligible
`EXPLORATION` sources by exactly one named dimension. The separate exploration
lane considers `CANDIDATE` sources and under-sampled `EXPLORATION` sources from
least observed to most observed. An `EXPLORATION` source that lacks the selected
metric also stays in this lane; a registry pilot size can only lower its cap.
Both lanes enforce approved source-use policy. Missing metrics do not become zero,
unused lane capacity is reported rather than reassigned, and planning performs no
automatic promotion or demotion. Allocations expose their source type and access
method and are capacity recommendations, not a claim that an automated connector
exists.

## Prohibited paths

Proxy or account rotation, CAPTCHA bypass, rate-limit evasion, fingerprint
spoofing, private endpoints, and access-control circumvention are out of scope.
An acquisition path that requires any of these is recorded unavailable or policy
blocked and abandoned.
