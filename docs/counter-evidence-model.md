# Counter-evidence model

Every reportable research case includes a separate devil's-advocate pass. Positive
evidence never substitutes for this pass.

## Types

Counter-evidence is stored using the product vocabulary:

- temporary problem;
- feature already exists or has been announced;
- free or satisfactory workaround;
- low frequency or impact;
- very small segment;
- no payment signal;
- high switching cost;
- incumbent fix risk;
- regulatory, distribution, or dependency barrier;
- weak DACH transfer;
- contradicting users; or
- other.

The persisted enum names are defined by `CounterEvidenceType` in the domain model.

## Evidence rule

Every counter-evidence item links to a factual claim, which in turn requires exact
source evidence. Claims used here cannot later be downgraded to analysis or
hypothesis.

An evidence-found counter pass cannot close without at least one typed item. If a
bounded search finds nothing, the pass instead records `NO_EVIDENCE_FOUND` and a
required note. The report phrases this as “no additional counter-evidence found,”
never as “there are no risks.”

## Interpretation

Counter-evidence is not a negative opportunity score. It preserves facts that may
weaken, narrow, or invalidate a case so a reader can judge them alongside the
supporting evidence and unknowns.
