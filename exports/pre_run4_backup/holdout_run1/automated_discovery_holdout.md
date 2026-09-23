# Automated discovery holdout

Status: **INFERENCE_COMPLETED**. Arctic Shift acquisition cost: **€0**.

## Funnel and model usage

Acquired 250; usable 130; screening calls 388; POTENTIAL_PAIN 0; NO_PAIN 1; extraction calls 0; valid observations 0; strong signals 0.
Inference failures 129; evidence-validation failures 0; failure types {"MODEL_UNAVAILABLE": 129}.
Tokens reported: input 0, output 0; calls without usage 388; API inference cost USD: UNKNOWN; local direct API charge EUR: UNKNOWN; infrastructure cost: UNKNOWN; runtime 1436.82 seconds.
Baseline IDs excluded: 250; overlap encountered: 0.

## Unedited model-produced examples

No validated positive observations.

## Failure and review visibility

Provisional recommendation: AUTOMATED_DISCOVERY_NOT_READY (human precision labels are still pending).

Model/evidence validation failures:
- MODEL_UNAVAILABLE: https://www.reddit.com/r/accounting/comments/1w7kugh/
- MODEL_UNAVAILABLE: https://www.reddit.com/r/accounting/comments/1w7ktnq/
- MODEL_UNAVAILABLE: https://www.reddit.com/r/accounting/comments/1w7kbfi/
- MODEL_UNAVAILABLE: https://www.reddit.com/r/accounting/comments/1w7k1lq/
- MODEL_UNAVAILABLE: https://www.reddit.com/r/accounting/comments/1w7jwto/

Lower-strength positive candidates (not confirmed false positives):
- None identified by evidence-strength flag.

Keyword-flagged NO_PAIN candidates (not confirmed misses):
- None identified by this diagnostic flag.
The review CSV contains model positives and a deterministic sample of NO_PAIN items; all human columns are blank.
Likely false positives, suspicious negatives, and semantically misaligned claims require human review; none are labeled without that review.
Failed model/validation calls remain separate from NO_PAIN in metrics.
Semantic recurrence remains a separate clustering gap; thresholds are unchanged.
