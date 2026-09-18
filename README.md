# DACH Problem Intelligence

An evidence-first research system for discovering real workflow problems globally
and investigating their relevance to Germany, Austria, and Switzerland.

This project does **not** generate startup ideas or predict startup success. Its
output is a traceable research case that helps a human decide what to investigate
next.

## Current vertical slice

The initial foundation deliberately focuses on the integrity-critical path:

- provider-neutral `Source` and `SourceItem` ingestion
- stable identifiers and idempotent upserts
- structured problem observations with nullable fields
- exact evidence spans tied to immutable source text
- explicit `GLOBAL` versus `DACH` evidence scope
- fact, analysis, and hypothesis claim types
- database constraints that prevent unsupported factual claims
- validated, manually labelled detection and extraction benchmark cases
- evidence-linked competition and DACH-transfer benchmark contracts
- a provider-neutral connector boundary with a controlled local JSONL adapter
- versioned extraction runs with completed/failed provenance
- deterministic fingerprints with a benchmarked exact-clustering baseline
- transparent research-case candidate ranking without an opportunity score
- gated research cases with workaround, competition, DACH, and counter-evidence passes
- evidence-backed alternatives and competitor complaints, including incumbent-fix risk
- typed, evidence-backed devil's-advocate findings
- first-class research unknowns and explicit no-evidence-found outcomes
- scope-separated Markdown reports focused on validation questions
- a small CLI for initializing and inspecting a local SQLite database
- a provider-independent Reddit discovery/acquisition path with explicit completeness

See [docs/architecture.md](docs/architecture.md) for boundaries and decisions and
[docs/product-principles.md](docs/product-principles.md) for the product rules.
The Reddit provider and measurement policy is documented in
[docs/source-strategy.md](docs/source-strategy.md).

## Quick start

Python 3.11 or newer is recommended. The runtime has no third-party dependencies.

```bash
python -m pip install -e .
problem-intelligence init-db --database local.db
problem-intelligence stats --database local.db
python -m unittest discover -s tests -v
```

For development, install the optional quality tools and run the same gates as CI:

```bash
python -m pip install -e '.[dev]'
ruff check .
pyright
python -m unittest discover -s tests -v
```

To ingest a source item:

```bash
problem-intelligence ingest-item \
  --database local.db \
  --source-type forum \
  --source-name example-community \
  --external-id post-123 \
  --url https://example.test/posts/123 \
  --text "We reconcile every payment manually in a spreadsheet."
```

The command is safe to repeat. Source items are unique within their source by a
normalized external identifier. Re-ingestion also preserves an explicitly assigned
source lifecycle and existing compliance metadata when no replacement value is
provided. Use `set-source-lifecycle` for deliberate classification changes.

For operator-supplied exports, one JSON object per line is accepted. Required
fields are `external_id` and `text`; optional fields are `url`, `title`,
`author_external_id`, `published_at`, `country_code`, `language_code`, and
`metadata`.

```bash
problem-intelligence ingest-jsonl \
  --database local.db \
  --file source-items.jsonl \
  --source-type operator-export \
  --source-name customer-research \
  --commercial-use-status operator-confirmed
```

The complete file is validated before the first write. Unknown keys are rejected
instead of being silently discarded. This adapter performs no network access;
the operator remains responsible for supplying permitted data and recording its
use, retention, and attribution terms.

For multi-publisher competition, DACH, or counter-evidence research, use the
policy-complete capture format documented in
[docs/research-captures.md](docs/research-captures.md):

```bash
problem-intelligence ingest-research-jsonl \
  --database research.db \
  --file data/research/seo_reporting_research_v1.jsonl
```

This format requires explicit quoting, deletion, rate-limit, retention,
attribution, commercial-use, and review metadata for every source.

## Benchmark fixtures

The first labelled fixture lives at
`benchmarks/problem_detection_v1.jsonl`. Each positive case includes its expected
problem type, versioned problem-ontology family, evidence scope, nullable
extraction fields, and exact character spans into the original source text.
Negative cases intentionally carry no extraction labels.

Validate a fixture before using it in an evaluation:

```bash
problem-intelligence validate-benchmark \
  --fixture benchmarks/problem_detection_v1.jsonl
```

Validation rejects duplicate case IDs, unknown extraction fields, invalid enum
values, labels attached to negative examples, missing positive labels, and
evidence excerpts that do not exactly match their source text. Every gold case
also carries structured provenance: source origin, rights status, optional source
URL, label method, reviewer identity, and review date. Synthetic cases must say so
and cannot claim source rights; prediction files do not copy gold provenance.

Predictions use the same labels without the source `text` field and can be scored
deterministically:

```bash
problem-intelligence evaluate-benchmark \
  --fixture benchmarks/problem_detection_v1.jsonl \
  --predictions predictions.jsonl

problem-intelligence evaluate-clustering \
  --fixture benchmarks/clustering_v1.jsonl

problem-intelligence validate-competition-benchmark \
  --fixture benchmarks/competition_v1.jsonl
problem-intelligence evaluate-competition \
  --fixture benchmarks/competition_v1.jsonl \
  --predictions competition-predictions.jsonl

problem-intelligence validate-dach-benchmark \
  --fixture benchmarks/dach_transfer_v1.jsonl
problem-intelligence evaluate-dach-transfer \
  --fixture benchmarks/dach_transfer_v1.jsonl \
  --predictions dach-predictions.jsonl
```

The checked-in fixtures are contract-sized, not statistically representative:
detection currently contains seven cases and clustering contains six, while
competition and DACH transfer each contain one evidence-linked real research case. A perfect
gold-replay result is a harness smoke test, not a production-quality claim. See
[docs/evaluation.md](docs/evaluation.md) for the coverage matrix and expansion
requirements.

The versioned readiness policy makes that limitation machine-readable:

```bash
problem-intelligence evaluation-readiness \
  --manifest benchmarks/readiness_v1.json
```

It evaluates five separate suites—problem detection, structured extraction,
clustering, competition research, and DACH transfer—against explicit coverage and
quality gates. Missing prediction files produce unknown metrics and failed gates;
they are never interpreted as zero or success. Add `--require-ready` in a future
scale-up workflow to return a failing process status until every gate passes. The
checked-in policy requires both manual labels and permissioned, human-reviewed
cases. Synthetic contract fixtures and public cases whose rights still require
review cannot satisfy the permissioned-case gates. It currently and intentionally
reports `ready_for_scale: false`.

## Offline provider bridge

Stored items can be exported as provider-neutral JSONL without coupling the
system to a model vendor:

```bash
problem-intelligence export-items \
  --database local.db \
  --output extraction-input.jsonl
```

Each prediction must echo the exported `source_item_id` and exact `external_id`.
Positive rows additionally contain `problem_type`, `evidence_scope`, `problem`,
`fields`, and one or more exact `evidence` ranges with `start`, `end`, and
`excerpt`. Negative rows contain only identity fields and `is_problem: false`.
Validated predictions are replayed through a versioned pipeline run:

```bash
problem-intelligence extract-predictions \
  --database local.db \
  --file predictions.jsonl \
  --version provider-model-prompt-v1 \
  --model-operation-key extraction:provider-request-123 \
  --model-provider provider-name \
  --model model-name \
  --template-version extraction-v3 \
  --input-tokens 1200 \
  --output-tokens 240 \
  --latency-ms 875
```

Missing predictions, duplicate item IDs, identity mismatches, fabricated excerpts,
unknown fields, and incomplete positive predictions fail the run instead of
silently creating partial evidence. Repeating the same extractor version over the
same exact inputs reuses the completed pipeline run and does not duplicate
observations or evidence.

The model telemetry arguments are optional for human-authored prediction files.
When any telemetry argument is present, provider/model/template identity and the
three measured usage fields become mandatory and are validated before extraction.
The resulting `ModelRun` links directly to the reused or newly created
`PipelineRun`. Measured cost may also be supplied as the complete cost triple used
by `record-model-run`; missing cost remains unknown.

## Research lifecycle

After clustering, inspect which clusters justify additional research:

```bash
problem-intelligence case-candidates \
  --database local.db \
  --sort strongest-evidence \
  --research-ready-only
```

The output exposes the dimensions used for ordering—recurrence, source diversity,
active search, switching intent, quantified impact, payment evidence, workarounds,
and DACH evidence. It does not collapse them into a universal score. A single
observation is marked research-ready only when it has a clear actor and job,
context or a documented workaround, and at least one high-value signal:
quantified impact, payment evidence, active solution search, or switching intent.
Recurrence also qualifies a non-noise cluster. Clusters containing only incidents,
support questions, or user errors are explicitly excluded.

`research_ready` means only that another research pass is justified. The separate
`minimum_problem_evidence_complete` field checks whether one observation already
has the actor, job, context, and exact evidence required by the case-completion
gate. `missing_for_completion` names any remaining fields rather than filling them
with plausible assumptions.

Evidence-backed reviewer corrections use `revise-observation`. Each correction
stores its reason, exact evidence, old and new values, and revision version, then
invalidates stale fingerprints and cluster memberships. Corrections are blocked
after a research case references the cluster.

`cluster-exact` persists the conservative baseline clusters. A research case then
moves through `OPEN`, `INVESTIGATING`, and `REVIEW`. The database refuses the
transition to `COMPLETE` until workaround, competition, DACH-transfer, and
counter-evidence research passes are complete. Each pass records either an
evidence-backed factual claim or an explicit `NO_EVIDENCE_FOUND` outcome with a
note. Completion also requires a clear actor/problem/context backed by an exact
evidence span, at least one documented unknown, and at least one validation
question. Completed cases can be rendered with `report`; global and DACH citations
remain separate and unknowns are shown explicitly. Each scope reports its own
problem-observation count, evidence spans, cited items, source count and names,
recorded countries, and source-publication window. Missing country or publication
metadata is shown as unknown and is never replaced with capture time.

User-facing reports withhold excerpts whose source-use status is not explicitly
approved. `report --include-unapproved-excerpts` exists only for internal review
and marks each such excerpt with a warning.

`report` renders the user-facing structure in German by default. Use
`--language en` for an English research view. Static labels and uncertainty
language are localized; original excerpts, factual claims, and reviewer-authored
research text are retained verbatim rather than machine-translated silently.

Databases upgraded from an earlier schema re-open legacy `COMPLETE` cases as
`REVIEW`, because older completion gates did not require every current research
artifact.

The DACH pass also requires a structured assessment. For example, an assessment
with no local evidence uses zero counts and `NONE_FOUND` rather than treating
global evidence as German evidence:

```bash
problem-intelligence set-dach-assessment \
  --database local.db \
  --case-id 1 \
  --actor-equivalence UNCLEAR \
  --actor-rationale "No DACH actor evidence found in the bounded search." \
  --workflow-equivalence UNKNOWN \
  --workflow-rationale "The local workflow remains unverified." \
  --transfer-type UNKNOWN \
  --transfer-rationale "There is not enough evidence to classify transfer." \
  --local-evidence-state NONE_FOUND \
  --dach-observation-count 0 \
  --dach-unique-author-count 0 \
  --dach-source-count 0
```

Record the stakeholder map separately from the free-text DACH rationale. A known
role requires an evidence-backed factual claim:

```bash
problem-intelligence set-stakeholder \
  --database local.db \
  --case-id 1 \
  --role END_USER \
  --knowledge KNOWN \
  --party "SEO practitioner" \
  --claim-id 42 \
  --note "The cited practitioner describes performing the workflow."

problem-intelligence set-stakeholder \
  --database local.db \
  --case-id 1 \
  --role BUYER \
  --knowledge UNKNOWN \
  --note "No source identifies who controls the purchasing budget."
```

`END_USER`, `BUYER`, `DECISION_MAKER`, `GATEKEEPER`, and `INFLUENCER` remain
distinct. An unknown role cannot carry an inferred party or a decorative claim.

An evidence-found competition pass similarly requires at least one structured
alternative whose profile is tied to a factual claim:

```bash
problem-intelligence add-competitor \
  --database local.db \
  --case-id 1 \
  --name "Existing workflow tool" \
  --solution-type DIRECT_SOFTWARE \
  --profile-claim-id 42 \
  --target-customer "Finance teams" \
  --market "Global" \
  --dach-available UNKNOWN \
  --dach-specific UNKNOWN
```

This lifecycle is available through `Repository` and through the corresponding
CLI commands shown by `problem-intelligence --help`.

## Reddit discovery without the official API

The Reddit path consumes auditable JSONL captures from permitted external search
and page providers; it does not scrape Reddit directly, bypass access controls, or
depend on the official Reddit API. Search and acquisition are separate operations:

```bash
problem-intelligence reddit-discover \
  --database local.db \
  --capture data/reddit/search_results_real_v1.jsonl \
  --query-group manual_work

problem-intelligence reddit-acquire \
  --database local.db \
  --capture data/reddit/acquisition_real_v1.jsonl

problem-intelligence extract-predictions \
  --database local.db \
  --file data/reddit/predictions_real_v1.jsonl \
  --version manual-reviewed-reddit-real-v1

problem-intelligence reddit-report \
  --database local.db \
  --json-output reddit-report.json \
  --markdown-output reddit-report.md
```

`exports/reddit_real_source_report.{json,md}` is the checked-in output of
exactly this sequence against the bundled captures; regenerate it the same way
after any change to the bundled Reddit data so it never silently drifts from
the database it describes.

The checked-in SEO reporting case can be rebuilt after those four commands from
the reviewed heterogeneous research capture. The reference workflow uses stable
external item identities, records every manual interpretation explicitly, and is
safe to replay:

```bash
python scripts/rebuild_seo_reporting_case.py \
  --database local.db \
  --capture data/research/seo_reporting_research_v1.jsonl \
  --output exports/seo_reporting_opportunity_v1.md
```

The script fails on ambiguous or contradictory prior rows instead of silently
choosing one. Its default report remains production-safe: excerpts whose source
rights are not approved are withheld while their provenance and policy status
remain visible. It re-clusters as part of rebuilding the case, so run
`case-candidates` after it, not before, if a candidate export also needs to be
current:

```bash
problem-intelligence case-candidates \
  --database local.db \
  --research-ready-only \
  --include-opened \
  > exports/reddit_real_case_candidates.json
```

Every provider declares capabilities. Discovery records preserve the original URL,
query, provider, canonical Reddit identity, and availability. Acquisition records
separately preserve `FULL`, `PARTIAL`, or `METADATA_ONLY` completeness and failures.
Only full or partial text of at least 40 characters is extraction-eligible. The
bundled real capture is intentionally marked partial: indexed excerpts are not
misrepresented as complete posts or comment threads.

To stage a subreddit registry (including the historical seed or a curated audit), use:

```bash
problem-intelligence sources-import --database local.db --file subreddits.csv
```

The CSV needs a `subreddit`, `name`, or `community` column. All original columns,
including old rankings and scores, are retained under the `legacy-csv` metadata
namespace. Recognized audit fields are also normalized into structured source
registry profiles. Neither legacy scores nor curation recommendations change the
measured lifecycle automatically.

Create a deterministic curation plan from the normalized registry with:

```bash
problem-intelligence sources-plan --database local.db --priority S --priority A --limit 50
```

The plan includes the original scan directive, effective pilot size, and source
policy status. A curation recommendation does not override access policy:
`production_ready` is only true when commercial use has explicitly been approved.

Persist the currently measurable source-performance counters with:

```bash
problem-intelligence source-metrics-refresh --database local.db
```

Snapshots include per-1,000-item yields, cluster contributions, cross-source
confirmations, incident/support counts, duplicate discoveries, and source
discovery/acquisition cost when that provider-cost coverage is complete. Model
cost is retained separately at operation level until exact per-source attribution
is available; batch cost is not divided speculatively. Quantified impact is counted only from structured
impact signals with an explicit value and unit. Counters without a measurement
path, currently promotion, remain `null` rather than becoming zero.

Use those persisted measurements to inspect one allocation dimension at a time:

```bash
problem-intelligence source-performance \
  --database local.db \
  --sort strong-signal-yield \
  --minimum-items 100 \
  --lifecycle EXPLORATION \
  --limit 25
```

Available dimensions cover strong signals, payment evidence, active searches,
cluster contributions, cross-source confirmations, known cost per strong signal,
and newest evidence. The output contains raw counts, per-1,000 yields, lifecycle,
rights readiness, and small-sample warnings. It never combines them into a hidden
source score and never changes lifecycle automatically. Separate lifecycle filters
allow an operator to retain an explicit exploration lane instead of allocating all
future scans only to previously productive sources.

Turn one chosen performance dimension into a bounded, reviewable scan plan while
reserving an explicit exploration budget:

```bash
problem-intelligence source-budget-plan \
  --database local.db \
  --total-items 500 \
  --exploration-items 100 \
  --per-source-cap 50 \
  --minimum-performance-items 100 \
  --performance-sort strong-signal-yield
```

All capacity and sample thresholds are operator inputs. The performance lane uses
only `CORE` or sufficiently measured `EXPLORATION` sources; the exploration lane
uses `CANDIDATE` sources plus exploratory sources below that threshold, ordered by
least prior scanning. Each allocation exposes the source type and access method;
the plan allocates research capacity but does not claim an automated connector is
available. Only sources with approved commercial-use status receive
an allocation. Registry pilot sizes further cap exploratory allocations. Unused
capacity stays visible in its original lane instead of being silently transferred,
and the command neither changes lifecycle nor emits a composite score.

Record exact model telemetry from an external provider adapter with:

```bash
problem-intelligence record-model-run \
  --database local.db \
  --operation-key extraction:batch-2026-09-18-01 \
  --provider provider-name \
  --model model-name \
  --pipeline-stage structured-extraction \
  --template-version extraction-v3 \
  --status COMPLETED \
  --input-tokens 1200 \
  --output-tokens 240 \
  --latency-ms 875 \
  --items-processed 10 \
  --measured-cost 0.0123 \
  --currency USD \
  --cost-measurement-source provider-response
```

The operation key is idempotent and immutable. Cost arguments are optional but
must be supplied as a complete measured triple; absent cost stays unknown rather
than being estimated from token counts.

Inspect measured cost coverage and exact unit costs with:

```bash
problem-intelligence cost-report \
  --database local.db \
  --pipeline-stage structured-extraction
```

The report keeps source discovery/acquisition costs separate from model-operation
currencies. A unit cost is available only when every operation in its selected
scope has measured cost, the currency is uniform, and the denominator is nonzero.
For model outputs, useful observations are the same evidence-backed strong signals
used by candidate admission. Research-case cost is limited to completed cases
linked through exact pipeline-run provenance. `--provider` and `--pipeline-stage`
can narrow the scope without redistributing batch cost.

The report deliberately leaves end-to-end case cost unknown: acquisition, model,
and human research work do not yet share complete case-level attribution. It also
excludes unrecorded human labour and never performs currency conversion.

Audit evidence integrity independently of write-time guards with:

```bash
problem-intelligence evidence-audit \
  --database local.db \
  --fail-on-violation
```

The audit reports the exact unsupported factual-claim rate, invalid or mismatched
evidence relationships, degraded `COMPLETE` research cases, and invalid
`REPORT_READY` opportunities. The failure flag makes the audit suitable for CI or
scheduled quality checks.

Audit source rights-policy completeness independently of the narrower
`commercial_use_status` check used for scan prioritization:

```bash
problem-intelligence source-policy-audit \
  --database local.db \
  --fail-on-violation
```

A source can have an approved commercial-use status and still be missing
retention, attribution, quoting, deletion, or rate-limit documentation; this
audit reports that gap explicitly instead of treating approval alone as
production-ready. `--include-unused` also reports on sources with no items or
discovery activity yet.

## Saved opportunities

Report-ready opportunities can be kept in a local investigation list without
changing their evidence, research state, or claims:

```bash
problem-intelligence save-opportunity \
  --database local.db \
  --opportunity-id 1 \
  --note "Interview affected practitioners before considering a solution."

problem-intelligence saved-opportunities --database local.db
problem-intelligence unsave-opportunity --database local.db --opportunity-id 1
```

Saving the same opportunity again is idempotent and updates only the personal
note. Only `REPORT_READY` opportunities can enter this list; saving does not imply
a recommendation to build.

Search titles and underlying problem, actor, job, and context fields with
composable descriptive filters:

```bash
problem-intelligence search-opportunities \
  --database local.db \
  --query "SEO reporting" \
  --status REPORT_READY \
  --evidence-state SINGLE_SIGNAL \
  --type WORKFLOW_GAP \
  --saved-only
```

Search is Unicode case-insensitive and treats `%` and `_` as literal user input.
Results expose evidence states and types, never a synthetic opportunity score.

## Scope

The codebase establishes trustworthy storage, ingestion, provider-capture,
benchmark, versioned extraction, deterministic clustering, research-case, and
reporting seams. No direct remote connector or production model extractor is
bundled; remote retrieval remains the responsibility of an explicitly permitted
provider, and structured predictions remain reviewable JSONL inputs.
