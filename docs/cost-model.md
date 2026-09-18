# Measured cost model

The system records cost only when a provider or operator supplies a measured
amount. Token counts are telemetry, not a licence to invent a price. Missing cost
remains unknown.

## Separate scopes

`cost-report` exposes two ledgers:

- Source acquisition covers discovery runs and acquisition attempts. These legacy
  adapter fields are explicitly denominated in USD.
- Model operations use exact `cost_events` and preserve their recorded ISO
  currency. Currency totals are never converted or combined.

Each scope reports operation counts, measured-cost coverage, missing-cost counts,
and known totals. A known partial total is not described as the total cost.

## Unit-cost gates

A unit metric is `AVAILABLE` only when:

1. at least one operation exists;
2. every selected operation has a measured cost;
3. all selected model costs use one currency; and
4. the relevant denominator is nonzero.

Source cost per item divides fully covered discovery and acquisition cost by the
distinct acquired source items in the same provider scope.

Model cost per processed item uses the exact `items_processed` telemetry. Cost per
useful observation uses the shared strong-signal predicate and requires every
selected model run to reference a pipeline run. Cost per linked complete research
case follows those pipeline outputs through cluster membership into `COMPLETE`
cases. Failed operations remain in cost totals because failed work may still incur
real cost.

Multiple model operations may contribute to one pipeline run. Their costs are all
retained while linked observations and cases are deduplicated. This represents
aggregate operational cost without speculatively splitting a batch among sources
or cases.

## Deliberate unknowns

The report does not calculate an end-to-end cost per research case. Source
discovery, acquisition, model execution, and manual competition/DACH research do
not yet have complete shared case attribution, and human labour is not measured.
Presenting their partial sum as total unit economics would understate cost.

Filters select exact stored provider or pipeline-stage values. They do not rewrite
history, estimate missing events, convert currencies, or allocate costs across
unlinked outputs.
