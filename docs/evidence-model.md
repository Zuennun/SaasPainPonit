# Evidence model

Evidence is stored before synthesis. A factual statement is only valid when its
support can be traced to exact immutable source text.

## Evidence spans

An evidence span contains a source item, half-open character offsets, copied
excerpt, and evidence scope (`GLOBAL` or `DACH`). Database triggers verify that
the excerpt exactly matches the referenced source text. Once evidence exists,
that source text cannot be changed.

`evidence-audit` rechecks stored relationships independently of the insertion
path. It measures unsupported factual claims, excerpt/source mismatches,
observation-bound claim mismatches, structured-signal evidence mismatches, and
whether completed cases or report-ready opportunities have degraded after their
original transition. `--fail-on-violation` returns a failing process status.

The database also rejects updates that retarget an observation-bound factual
claim to evidence from another observation, and rejects removal of the final
evidence link from a factual claim. A reported unsupported factual-claim rate of
zero is therefore measured as well as protected by write-time invariants.

## Structured signals

Workarounds, impacts, and payment evidence are independent objects rather than
free-text attributes embedded in an AI summary. Every signal references an exact
evidence span belonging to the same observation; cross-observation links are
rejected by database triggers.

### Workarounds

Supported types are:

```text
SPREADSHEET  CSV  EMAIL  WHATSAPP  PAPER  MANUAL_ENTRY
EMPLOYEE  FREELANCER  AGENCY  VIRTUAL_ASSISTANT
INTERNAL_SCRIPT  CUSTOM_SOFTWARE  MULTIPLE_TOOLS  EXISTING_SAAS  OTHER
```

The object also retains an evidence-backed description. Multiple workarounds may
belong to one observation.

### Impact signals

Supported impact types are:

```text
TIME  MONEY  REVENUE  ERRORS  CUSTOMER_LOSS
COMPLIANCE  RISK  STRESS  DELAY  OTHER
```

Qualitative impacts store `quantified = false` and no numeric value or unit.
Quantified impacts require both a source-faithful value and unit. Frequency is
optional and is never inferred.

### Payment evidence

Supported evidence types are:

```text
EXISTING_SOFTWARE_SPEND  EMPLOYEE_LABOR  FREELANCER_SPEND
AGENCY_SPEND  EXPLICIT_BUDGET  PURCHASE_SEARCH  SWITCHING_INTENT
PRICE_COMPLAINT  EXPLICIT_WILLINGNESS_TO_PAY
```

Amount and currency must either both be present or both be absent. A payment
signal without an amount still represents observed behavior, such as explicit
agency use or purchase search; it does not become an estimated willingness to
pay.

## Atomicity and historical fields

New extractor output stores the observation, evidence spans, and all structured
signals in one transaction. Invalid ranges, missing quantified units, partial
amount/currency pairs, or invalid evidence indices reject the entire observation.

The older nullable observation columns remain readable during migration, but the
normalized signal tables are authoritative for measured payment and quantified
impact yields. Historical records are migrated only through explicit reviewed
commands; the system does not guess signal types or numeric values from old text.

## Reviewed corrections

A reviewer may correct a nullable extraction field only through
`revise-observation`. The revision records the old and new JSON values, a reason,
an exact evidence span, and a revision version. Replaying the same revision is
idempotent. Because actor, job, context, and root cause contribute to clustering,
all fingerprints and memberships for the observation are invalidated and must be
recomputed. Corrections are refused once a research case references the cluster;
reviewed case semantics cannot silently change underneath completed research.

## Display rights

Evidence storage and evidence display are separate decisions. User-facing reports
show excerpts only when the source's commercial-use status is explicitly approved.
Otherwise, the report retains the source link and policy status but withholds the
excerpt. Operators can request an internal review rendering explicitly; that view
labels every unapproved excerpt with a warning.
