# Competition and alternatives model

Competition research covers more than SaaS vendors. Each evidence-backed
alternative is classified as one of:

- `DIRECT_SOFTWARE`
- `INDIRECT_SOFTWARE`
- `LEGACY_SOFTWARE`
- `INTERNAL_TOOL`
- `MANUAL_PROCESS`
- `FREELANCER`
- `AGENCY`
- `SERVICE_PROVIDER`
- `DIY_SCRIPT`
- `NO_SOLUTION_FOUND`

`NO_SOLUTION_FOUND` only describes a bounded search. It is not proof that no
solution exists. When a search yields no factual competitor evidence, the normal
competition-pass outcome is `NO_EVIDENCE_FOUND` with a search note.

## Competitor profile

A competitor stores its name, URL, solution type, target customer, market,
pricing, pricing model, features, integrations, DACH availability, and whether it
is DACH-specific. Unknown booleans remain `null`; they are never defaulted to
false.

Every profile requires a factual claim backed by exact evidence. Additional
factual claims can be attached by role: profile, pricing, feature, integration,
availability, or incumbent-fix risk.

## Complaints

Complaints are separate objects with a type, statement, affected segment, and
observed frequency. Each complaint requires one or more factual claims. A claim
used by a competitor or complaint cannot later be downgraded to analysis or
hypothesis.

The frequency field records what was actually observed, such as `single source`
or `three independent reports`; it is not an inferred prevalence estimate.

## Incumbent fix risk

`incumbent_fix_risk` is tri-state: yes, no, or unknown. A yes/no assessment must
include a rationale. It is a counterargument about how easily an incumbent might
close a gap, not a success prediction.

## Completion integrity

An `EVIDENCE_FOUND` competition pass requires at least one structured competitor
or alternative record. A `NO_EVIDENCE_FOUND` pass remains valid without one but
must retain its bounded-search note. Older completed cases are reopened for review
when migrating to this stronger completion contract.
