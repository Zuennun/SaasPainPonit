# Architecture

## Shape

The first version is a modular monolith backed by SQLite. Domain types contain no
provider or database details. `Repository` owns persistence and transaction rules;
future connectors and model providers will sit behind protocols at the application
boundary.

```text
SearchProvider -> DiscoveryRun -> DiscoveryRecord -> AcquisitionRecord
                                               |              |
                                               +----------> SourceItem
                                                              |
Source connector ---------------------------------------------+
                                                              v
                                                 ProblemObservation -> EvidenceSpan
                           |                       |
                           v                       v
                  Fingerprint -> Cluster -> ResearchCase -> Report
                                             |       |
                                             + Claim +
```

Later stages extend this path with fingerprints, clusters, research cases,
competition research, DACH assessments, counter-evidence, and opportunity reports.
They should not bypass the evidence model.

## Decisions

### Modular monolith first

A new research product benefits from transactions and direct inspectability more
than distributed infrastructure. SQLite keeps local development reproducible. The
repository boundary permits a later database change without leaking SQL into the
domain.

### Immutable evidence coordinates

An evidence span stores offsets and a copied excerpt, and the repository verifies
that the excerpt exactly matches the source item's raw text. Updating the text of
an item that already has evidence is rejected, preserving auditability.

### Facts require evidence

Database triggers reject factual claims without evidence. Analysis and hypotheses
may be stored without evidence but remain visibly typed. This is enforced in the
database as well as the application layer.

Workaround, impact, and payment signals follow the same rule. Each normalized
signal links to an exact evidence span belonging to its observation. Extracted
observations, spans, and signals are committed atomically; malformed signal
bundles cannot leave partial structured output behind.

### Locality is evidence metadata

`GLOBAL` and `DACH` are explicit evidence scopes. Country is retained separately;
a global observation is never promoted to DACH merely because its language is
German or because the problem appears transferable.

### Idempotent ingestion

Sources have a stable normalized key. Items are unique by `(source_id,
normalized_external_id)`. Re-ingestion updates metadata while retaining identity;
source text becomes immutable after evidence references it.

### Explicit acquisition boundary

Connectors expose a `SourceDescriptor` and an iterator of provider-neutral source
items. The first adapter only reads an operator-supplied local JSONL file and does
not imply permission to collect from any remote source. Source access, commercial
use, retention, and attribution terms are persisted with the source.

Reddit adds a second provider-neutral boundary for external search captures.
`SearchProvider` declares capabilities and returns `RESULTS`, `NO_RESULTS`, or
`SOURCE_UNAVAILABLE`; a zero-result query is therefore never inferred from a
provider failure. Reddit submission/comment identity is derived from canonical
URLs, independent of hostname variants, slugs, query parameters, and fragments.

Discovery does not imply possession of content. A separate `AcquisitionProvider`
records `CONTENT_COMPLETE`, `CONTENT_PARTIAL`, `ACQUISITION_FAILED`, or
`POLICY_BLOCKED`, together with `FULL`, `PARTIAL`, or `METADATA_ONLY`
completeness. Multiple provider/query records retain provenance while canonical
identity deduplicates the downstream source item. The bundled adapters replay
JSONL captures and never perform access-evasion or direct network collection.

### Versioned extraction provenance

Extractors return structured `ObservationDraft` values with exact character
ranges. Every execution creates a pipeline run with a version, input/output
counts, and a terminal completed or failed state. An observation and all of its
evidence spans are committed atomically and linked to that run. Completed runs are
indexed by extractor version and a deterministic signature of every selected
input; exact reruns reuse the prior result rather than duplicating evidence.

Provider calls may run outside the application. `export-items` creates a stable
JSONL handoff and `JsonlPredictionExtractor` validates returned identities,
structured fields, and exact excerpts before storing anything. This keeps model
credentials and SDK choices outside the evidence core while preserving complete
run provenance.

### Exact model usage and cost telemetry

`ModelRun` is provider-neutral and records the provider, model, pipeline stage,
prompt/template version, token counts, latency, and processed item count for one
AI operation. A caller-supplied operation key makes capture idempotent; replaying
that key with different telemetry is rejected rather than overwriting history.

`CostEvent` is optional and stores only a measured decimal amount, three-letter
currency, and the measurement source (for example a provider response or invoice).
All three values must be present together. Missing cost remains null; the system
does not infer or estimate a price from token counts. A model run can optionally
reference the broader `PipelineRun` that consumed its output.

The offline prediction-import command accepts this telemetry as an optional
all-or-nothing group. It validates identity, non-negative usage, and measured cost
before extraction, then links the recorded model operation to the exact completed
or reused extraction pipeline run. Human-reviewed files can omit model telemetry
instead of inventing provider usage.

### Conservative clustering baseline

The baseline fingerprint normalizes and hashes the specified problem identity:
actor, job to be done, problem, context, and optional root cause. Workarounds,
tools, observation classification, and evidence scope are deliberately excluded;
they may vary while the underlying problem remains the same.
Evidence scope is excluded so the same problem can accumulate global and DACH
evidence. Exact fingerprints favour precision over recall; semantic clustering
must remain versioned and beat the labelled pairwise benchmark before replacing
the baseline.

Problem ontology is versioned independently. `problem_family` describes the
workflow domain (for example `RECONCILIATION`), while `problem_type` describes the
kind of report (for example `WORKFLOW_GAP`). Source performance is materialized by
ontology family to support problem-specific source routing.

### Completion is a database invariant

Research cases follow explicit state transitions. Workaround, competition, DACH
transfer, and counter-evidence research passes must each finish with either an
evidence-backed factual claim or an explicit bounded `NO_EVIDENCE_FOUND` outcome.
The DACH pass additionally requires a structured assessment that keeps actor and
workflow equivalence, local evidence state, and transfer classification separate
from global evidence.
An evidence-found competition pass requires a structured alternative profile.
Profiles and complaints each retain factual claim links so a list of vendor names
cannot masquerade as researched competition.
At least one unknown and one validation question are mandatory. The clustered
problem itself must have a clear actor, job, context, and exact observation
evidence. Database triggers enforce these rules even when writes bypass the
repository. Reports are only rendered from completed cases, separate global and
DACH evidence, and explicitly avoid making a build recommendation.

### Saved opportunities are user state

A report-ready opportunity can be bookmarked with an optional local note. This
does not add evidence, alter claims, change research status, or imply a build
recommendation. The single-user MVP stores one saved record per opportunity;
re-saving updates the note while retaining the original saved timestamp.

## Next increments

1. Expand the human-labelled detection and clustering fixtures with more real,
   permissioned source examples.
2. Select and benchmark a production extractor behind `ProblemExtractor`.
3. Approve remote source terms before implementing any network connector.
4. Add a versioned semantic clusterer only if it improves the pairwise benchmark.
5. Add dedicated competition and DACH research providers without weakening the
   existing structured assessment, factual-claim, and completion gates.
