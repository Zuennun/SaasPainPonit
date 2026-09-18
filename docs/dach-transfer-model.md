# DACH transfer model

Global evidence and DACH evidence are different facts. A research case therefore
stores one structured DACH assessment before its `DACH_TRANSFER` pass can be
closed.

## Required classifications

- `actor_equivalence`: `DIRECT`, `SIMILAR`, `DIFFERENT`, or `UNCLEAR`
- `workflow_equivalence`: `DIRECT`, `LOCALIZED`, `MATERIALLY_DIFFERENT`, or
  `UNKNOWN`
- `transfer_type`: `DIRECT_TRANSFER`, `LOCALIZATION_REQUIRED`, `LOCAL_FRICTION`,
  `WEAK_LOCAL_EVIDENCE`, `MATERIAL_DIFFERENCE`, or `UNKNOWN`
- `local_evidence_state`: `NONE_FOUND`, `SINGLE_LOCAL_SIGNAL`,
  `MULTIPLE_LOCAL_SIGNALS`, or `MULTI_SOURCE_LOCAL_SIGNALS`

Actor, workflow, and transfer classifications each require a non-empty rationale.
These are descriptive research states, not scores or success predictions.

## Local evidence counts

The assessment records DACH observation, unique-author, and source counts. The
database keeps them consistent with the evidence state:

- `NONE_FOUND` requires all three counts to be zero.
- `SINGLE_LOCAL_SIGNAL` requires at least one observation, author, and source.
- `MULTIPLE_LOCAL_SIGNALS` requires at least two observations.
- `MULTI_SOURCE_LOCAL_SIGNALS` requires at least two observations and sources.

These counts describe locally scoped evidence only. They are never inferred from
the number of global reports.

## Local market context

The assessment can additionally preserve:

- buyer structure;
- ecosystem dependencies;
- regulatory dependencies;
- switching barriers; and
- localization gaps.

Missing entries remain absent. The report renders an unknown buyer explicitly and
does not turn an empty list into a claim that no dependencies or barriers exist.

## Stakeholder map

End user, buyer, decision maker, gatekeeper, and influencer are stored as separate
case roles. Each role is either `KNOWN` or `UNKNOWN`. A known role requires a
non-empty party label and an evidence-backed factual claim. An unknown role stores
no guessed party and no claim; it requires a note explaining the missing evidence.

The report renders this structured map separately from the DACH assessment's
legacy buyer-structure narrative. This makes “the practitioner has the problem”
visibly different from “the practitioner controls the budget.”

## Completion integrity

Database triggers prevent the DACH pass from becoming satisfied without an
assessment. Completed research cases cannot lose their assessment afterward.
An assessment with `NONE_FOUND` documents that a bounded local search was
performed; it does not claim that no DACH evidence exists.
