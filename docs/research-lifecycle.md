# Research case lifecycle

A cluster becomes a `ResearchCase` before it can become a reportable opportunity.
Completion means that required research was performed; it does not mean that the
market or product will succeed.

## State transitions

```text
OPEN -> INVESTIGATING -> REVIEW -> COMPLETE
  \          \            \
   +----------+------------+-> REJECTED
```

The database rejects skipped or reversed transitions.

## Minimum problem evidence

Before completion, at least one clustered observation must contain:

- an actor or actor role;
- a job to be done;
- explicit context;
- a non-empty problem statement; and
- an exact evidence span belonging to that observation.

This prevents a collection of detached claims from substituting for a clearly
described problem.

## Mandatory research passes

Every new case starts with four pending passes:

1. `WORKAROUND_RESEARCH`
2. `COMPETITION`
3. `DACH_TRANSFER`
4. `COUNTER_EVIDENCE`

The `DACH_TRANSFER` pass cannot be closed until a structured DACH assessment has
been stored. A generic note is not a substitute for the assessment; see
[DACH transfer model](dach-transfer-model.md).

An evidence-found `COMPETITION` pass likewise requires a structured solution or
alternative record. Competitor profiles and complaints retain their own factual
claim links; see [competition model](competition-model.md).

An evidence-found `COUNTER_EVIDENCE` pass requires at least one typed, factual
counter-evidence item. A completed bounded search with no result uses
`NO_EVIDENCE_FOUND`; see [counter-evidence model](counter-evidence-model.md).

Each pass ends in one of two explicit outcomes:

### `EVIDENCE_FOUND`

The pass links to a factual claim. The normal claim invariant applies: the claim
must have exact supporting evidence and cannot later be downgraded to analysis or
hypothesis while it satisfies the pass.

### `NO_EVIDENCE_FOUND`

No factual claim is manufactured. The pass stores a required note describing the
bounded search result. This means only that no evidence was found in that research
pass; it never means that evidence or risk does not exist.

## Unknowns and validation

At least one unknown and one concrete validation question are required before
completion. Unknowns are displayed separately in the report. They are not encoded
as negative evidence and are not silently converted into assumptions.

Global and DACH evidence summaries are computed independently from the exact
spans used by the cluster and completed research passes. They expose observation,
span, cited-item, and source counts; source names; recorded country codes; and the
publication-date window. Ingestion timestamps never substitute for missing source
publication dates.

The report shell is German by default, with an explicit English option. Source
quotes and reviewer-authored claims are not silently translated because that
would obscure which wording is original evidence and which wording is analysis.

The completion invariant is enforced by database triggers, so direct SQL cannot
bypass missing context, passes, unknowns, or validation questions.
