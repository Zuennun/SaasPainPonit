# Evaluation strategy and current coverage

Evaluation gates are deterministic, but current fixture size is intentionally
small. A perfect score obtained by replaying gold labels as predictions only
proves that the loader and metric implementation agree with the fixture. It does
not prove production research quality.

## Current benchmark coverage

| Area | Fixture | Labelled | Permissioned + reviewed | Current purpose | Production gap |
|---|---|---:|---:|---|---|
| Problem detection and extraction | `problem_detection_v1.jsonl` | 7 | 1 | Schema, span, null, and metric validation | Expand to hundreds of permissioned positive and negative items |
| Exact clustering | `clustering_v1.jsonl` | 6 | 0 | Pairwise metric and conservative baseline validation | Add permissioned paraphrases, near misses, multilingual cases, and larger clusters |
| Competition research | `competition_v1.jsonl` | 1 | 0 | Existing-solution precision/recall contract | Resolve mixed source rights and add reviewed cases across problem families |
| DACH transfer | `dach_transfer_v1.jsonl` | 1 | 0 | Separate actor, workflow, transfer, and local-evidence metrics | Resolve source rights and add direct, localized, materially different, and no-evidence examples |

Every gold record requires structured benchmark provenance. `SYNTHETIC`,
`PUBLIC_SOURCE`, and `FIRST_PARTY` origins are distinct from `APPROVED`,
`REVIEW_REQUIRED`, and `NOT_APPLICABLE` rights. Label method separately records
`HUMAN`, `HUMAN_REVIEWED`, or `UNREVIEWED`; reviewed labels require a reviewer and
ISO review date. Synthetic records require `NOT_APPLICABLE` rights and cannot carry
a source URL. Public records require a URL and an explicit rights decision.

The competition and DACH gold records additionally require at least one research
URL. Prediction files omit evidence URLs and provenance; metrics compare model
results, not whether a model reproduced gold governance metadata. The current
competition and DACH fixtures are human-labelled but intentionally remain
`REVIEW_REQUIRED`, so they do not count as permissioned benchmark coverage.

## Scale-readiness policy

`benchmarks/readiness_v1.json` records provisional minimum coverage and quality
thresholds separately from the implementation. `evaluation-readiness` validates
the policy, loads every fixture through its strict loader, calculates label
diversity and pair coverage, and evaluates supplied prediction files. It never
generates predictions and does not treat absent predictions as a passing result.

The five policy suites remain separate even where detection and extraction share
a fixture. This prevents strong detection from hiding poor field or evidence-span
extraction. DACH equivalence dimensions likewise remain separate. Clustering is
the only suite whose current deterministic baseline can be evaluated without an
external prediction file.

Every suite policy must include both `manually_labeled_cases` and
`permissioned_human_reviewed_cases` coverage gates. This prevents synthetic volume,
unreviewed generated labels, or unresolved source rights from satisfying the
scale-readiness sample requirement.

Run the report without enforcement while the benchmark assets are being built:

```bash
problem-intelligence evaluation-readiness \
  --manifest benchmarks/readiness_v1.json
```

Use `--require-ready` only at a scale-up boundary. It returns status 1 when any
coverage or metric gate fails. The current checked-in result is deliberately not
ready: this is a guard against scaling weakly evaluated ingestion, not a quality
claim. The thresholds themselves are an explicit provisional product policy and
should be revised through review rather than silently changed in code.

## Metrics

Problem evaluation reports detection precision/recall/F1, strict type/family/scope
accuracy, exact structured-field accuracy, and evidence-span precision/recall/F1.
Clustering uses pairwise precision, recall, and F1.

Competition evaluation treats normalized solution name plus solution type as the
solution identity. It reports micro precision, recall, F1, exact case accuracy,
and URL accuracy separately so a harmless URL spelling difference does not become
a false missing competitor.

DACH evaluation reports actor equivalence, workflow equivalence, transfer type,
and local-evidence-state accuracy separately, plus exact all-fields accuracy. This
prevents one broad “Germany score” from hiding the dimension that failed.

## Required interpretation

- Do not publish a production quality claim from the current fixture sizes.
- Do not tune a model against the same cases used for final evaluation.
- Preserve difficult negatives, weak evidence, and `UNKNOWN` outcomes.
- Review every new gold label and its source rights before inclusion.
- Record the evaluated provider, model, template version, usage, and measured cost
  through the model-run ledger.
