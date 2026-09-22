# Automated discovery holdout

Status: **INFERENCE_COMPLETED**. Arctic Shift acquisition cost: **€0**.

## Funnel and model usage

Acquired 250; usable 130; screening calls 206; POTENTIAL_PAIN 24; NO_PAIN 54; extraction calls 21; valid observations 24; strong signals 0.
Inference failures 52; evidence-validation failures 0; failure types {"MODEL_UNAVAILABLE": 52}.
Tokens reported: input 0, output 0; calls without usage 227; API inference cost USD: UNKNOWN; local direct API charge EUR: UNKNOWN; infrastructure cost: UNKNOWN; runtime 1877.03 seconds.
Baseline IDs excluded: 250; overlap encountered: 0.

## Unedited model-produced examples

- Problem: The author is uncertain about the accuracy of importing PDF data using PQ.; actor: None; workflow/context: None / The PDF contains DATE, MEMO, and AMOUNT columns and is 20 pages long.; workaround: None; impact: None; signal: SINGLE_SIGNAL; source: https://www.reddit.com/r/accounting/comments/1w7ktnq/; evidence: I want import using PQ, how accurate is it. | The pdf has DATE | MEMO | AMOUNT. Very simple but It's 20 pages long.
- Problem: Uncertainty about why shipping costs for a non-inventory item are coded in AP to the freight-in expense GL.; actor: None; workflow/context: None / None; workaround: None; impact: None; signal: SINGLE_SIGNAL; source: https://www.reddit.com/r/accounting/comments/1w7ibj6/; evidence: Can someone explain why the cost of shipping for a non inventory item would be coded in AP to the freight in Expense GL?
- Problem: The company has messed up books.; actor: None; workflow/context: None / Joining a new accounting team.; workaround: None; impact: None; signal: SINGLE_SIGNAL; source: https://www.reddit.com/r/accounting/comments/1w7ghek/; evidence: the company has messed up books | Joining a new accounting team
- Problem: Received conflicting accounting advice from multiple accountants.; actor: None; workflow/context: None / None; workaround: None; impact: None; signal: SINGLE_SIGNAL; source: https://www.reddit.com/r/accounting/comments/1w7erp5/; evidence: I have spoken with a few accountants and gotten different answers | if someone can clarify for me
- Problem: Uncertainty about which financial controls to establish before taking owner draws from a new e-commerce business.; actor: Solo founder; workflow/context: None / Launching a solo, bootstrapped e-commerce business and seeking financial controls before revenue begins.; workaround: None; impact: None; signal: SINGLE_SIGNAL; source: https://www.reddit.com/r/accounting/comments/1w7d4tw/; evidence: What financial controls should a solo founder establish before taking owner draws from a new e-commerce business? | solo founder

## Failure and review visibility

Provisional recommendation: AUTOMATED_DISCOVERY_NEEDS_TUNING (human precision labels are still pending).

Model/evidence validation failures:
- MODEL_UNAVAILABLE: https://www.reddit.com/r/propertymanagement/comments/1w5culy/
- MODEL_UNAVAILABLE: https://www.reddit.com/r/propertymanagement/comments/1w57f7s/
- MODEL_UNAVAILABLE: https://www.reddit.com/r/propertymanagement/comments/1w56nh6/
- MODEL_UNAVAILABLE: https://www.reddit.com/r/propertymanagement/comments/1w53c9n/
- MODEL_UNAVAILABLE: https://www.reddit.com/r/propertymanagement/comments/1w50roc/

Lower-strength positive candidates (not confirmed false positives):
- None identified by evidence-strength flag.

Keyword-flagged NO_PAIN candidates (not confirmed misses):
- None identified by this diagnostic flag.
The review CSV contains model positives and a deterministic sample of NO_PAIN items; all human columns are blank.
Likely false positives, suspicious negatives, and semantically misaligned claims require human review; none are labeled without that review.
Failed model/validation calls remain separate from NO_PAIN in metrics.
Semantic recurrence remains a separate clustering gap; thresholds are unchanged.
