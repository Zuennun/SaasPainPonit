# Arctic Shift 250-Post Research Pilot (2026-09-19)

**Baseline evaluation. Run once, not tuned, not rerun after review.**

Status: real, live acquisition (250/250 records, 5/5 requests succeeded) + full-population
manual extraction review (114/114 usable items reviewed, no cherry-picking) + the
existing, unmodified automated pipeline (evidence validation, signal policy, exact
clustering).

## 1. Sampling method (reproducible)

Provider: Arctic Shift only. No automated requests to reddit.com were made.

- Requested time window: `after=2026-09-05`, `before=2026-09-20` (a fixed 15-day
  window ending at pilot start), applied identically to all 5 subreddits.
- Requested per subreddit: 50 (250 total maximum, not exceeded).
- Returned per subreddit: exactly 50/50 for all five -- the window was generous
  enough that no subreddit ran short.
- Actual oldest/newest returned item per subreddit (real timestamps, not
  estimated):

| Subreddit | Oldest in sample | Newest available | Age of newest at retrieval |
|---|---|---|---|
| r/Accounting | 2026-09-19T02:58:33Z | 2026-09-19T18:43:14Z | ~4 min |
| r/restaurantowners | 2026-09-15T23:56:35Z | 2026-09-19T18:46:57Z | ~27 sec |
| r/PropertyManagement | 2026-09-16T15:30:53Z | 2026-09-19T17:45:19Z | ~62 min |
| r/HVAC | 2026-09-17T17:17:41Z | 2026-09-19T18:08:37Z | ~39 min |
| r/FreightBrokers | 2026-09-16T16:22:52Z | 2026-09-19T16:29:23Z | ~2.3 hr |

Command used: `python -m problem_intelligence.arctic_shift_poc --manifest
docs/providers/arctic-shift-poc-manifest.csv --database
data/reddit/arctic_shift_250_pilot.db --per-source-limit 50 --start-date
2026-09-05 --end-date 2026-09-20 --min-request-interval-seconds 3`. Re-running
this exact command against Arctic Shift later will return a different (larger,
newer) window unless the same `after`/`before` are kept -- the window, not the
result set, is what is reproducible; Arctic Shift's own data can change (new
removals, newly-indexed posts) between runs.

## 2. Acquisition vs. usable content (separated)

| Metric | Count |
|---|---|
| Records retrieved | 250 |
| FULL | 114 |
| METADATA_ONLY | 136 |
| — of which REMOVED (moderator/admin) | 88 |
| — of which DELETED (by author) | 1 |
| — of which genuine bodyless link/image posts | 47 |
| Usable (entered the research pipeline) | 114 |

FULL rate varied sharply by community and must not be read as a verdict on
community quality -- it is dominated by moderation/removal activity, which
Arctic Shift exposes but does not explain:

| Subreddit | Returned | FULL | Removed | Deleted | Genuine link/image |
|---|---:|---:|---:|---:|---:|
| r/Accounting | 50 | 41 | 3 | 0 | 6 |
| r/restaurantowners | 50 | 10 | 35 | 1 | 4 |
| r/PropertyManagement | 50 | 37 | 9 | 0 | 4 |
| r/HVAC | 50 | 9 | 25 | 0 | 16 |
| r/FreightBrokers | 50 | 17 | 16 | 0 | 17 |

r/restaurantowners lost 72% of its sample to removal/deletion -- likely a heavily
moderated or spam-targeted community at the timestamps sampled. This is a
provider/community observation, not a pipeline defect.

## 3. Extraction method

Every one of the 114 usable (FULL) items was read and given an explicit
`is_problem` judgment -- not a cherry-picked subset. This codebase has no
automated prefilter or pain-detection classifier: `ProblemExtractor` (the only
extraction interface) is always backed by externally-supplied structured
predictions (`JsonlPredictionExtractor`), validated byte-for-byte against stored
source text before anything is accepted. For this baseline, the calling agent
supplied those predictions directly (acting as the required external classifier,
since no other is wired into this environment) -- for all 114 items, not just the
ones that looked promising. 10 were judged `is_problem: true`; 104 were judged
`is_problem: false` and carry no extraction output. All 114 were submitted in one
batch (`extract-predictions --version arctic-shift-250-pilot-manual-review-v1`)
and validated/ingested by the unmodified pipeline: `processed_items: 114,
created_observations: 10`. No thresholds, prompts, or signal-policy rules were
changed to shape this result.

## 4. Full funnel by subreddit

| Subreddit | Retrieved | FULL | Usable | After prefilter | ProblemObservations | Strong | Active search | Manual workaround | DIY/internal | Quantified impact | Payment evidence | NO_PAIN/rejected |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| r/Accounting | 50 | 41 | 41 | 41 | 2 | 1 | 2 | 0 | 0 | 1 | 0 | 39 |
| r/restaurantowners | 50 | 10 | 10 | 10 | 3 | 2 | 2 | 2 | 0 | 0 | 0 | 7 |
| r/PropertyManagement | 50 | 37 | 37 | 37 | 3 | 0 | 1 | 0 | 0 | 0 | 0 | 34 |
| r/HVAC | 50 | 9 | 9 | 9 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 9 |
| r/FreightBrokers | 50 | 17 | 17 | 17 | 2 | 0 | 1 | 0 | 0 | 0 | 0 | 15 |
| **Total** | **250** | **114** | **114** | **114** | **10** | **3** | **6** | **2** | **0** | **1** | **0** | **104** |

"After prefilter" equals FULL here because the only prefilter this codebase
implements is `length(raw_text) >= 40`, which every FULL item cleared by
construction (self-text posts are materially longer than 40 characters in this
sample).

**Rates per 100 usable items** (sample sizes shown -- do not extrapolate past
them):

| Subreddit | n (usable) | Pain obs / 100 | Strong / 100 | Active search / 100 | Payment / 100 |
|---|---:|---:|---:|---:|---:|
| r/Accounting | 41 | 4.9 | 2.4 | 4.9 | 0 |
| r/restaurantowners | 10 | 30.0 | 20.0 | 20.0 | 0 |
| r/PropertyManagement | 37 | 8.1 | 0 | 2.7 | 0 |
| r/HVAC | 9 | 0 | 0 | 0 | 0 |
| r/FreightBrokers | 17 | 11.8 | 0 | 5.9 | 0 |

n=9 and n=10 are far too small for these per-100 rates to mean anything on their
own; they are shown only because they were asked for, not as a ranking.

## 5. Source yield vs. extraction quality (kept separate)

**Source yield** (does the community contain useful material, independent of our
system): r/restaurantowners and r/Accounting produced the clearest, most concrete
operational-software problems in this sample. r/HVAC produced zero -- its FULL
content this pilot was career questions, workplace friction, and hands-on trade
talk (motor repair, bib clothing, boiler brands), not office/software workflow
discussion. r/FreightBrokers and r/PropertyManagement produced real but thinner
material, diluted by industry-gossip and legal/interpersonal-dispute posts.

**Extraction quality** (does our system correctly identify and structure what is
there): every accepted observation's evidence was verified to match source text
exactly (the system enforces this and would reject a mismatch); no fabricated
field was possible by construction. Two posts describing genuine vendor pitches
were correctly evidence-grounded while flagging the vendor-claim span as weaker
evidence than the practitioner's own framing (see #12). The signal-policy
"strong" rule correctly demoted several real problems to "weak" specifically
because this extraction pass did not populate a `context` field or a formal
workaround row for them (see #23 -- an extraction completeness gap in this run,
not a system defect).

## 6. Promotional contamination

Explicitly identified and **excluded from the 10 accepted observations**:

- **r/Accounting**: a bookkeeper pitching an app they are personally building
  ("I've started building a very simple app around this problem... Before I
  spend too much time building it, I'd love some brutally honest feedback"),
  and a post publishing a company blog's AP-recovery workflow with a link to
  `duvo.ai` -- content-marketing framed as a question, not a first-person
  unsolved problem.
- **r/PropertyManagement**: a real-estate portfolio tool builder explicitly
  disclosing "I'm involved in building AcreTerminal at DesiAcres... asking
  partly for product research."
- **r/Accounting**: a post testing a named AI tool ("Jev" by "Typesafe")
  against AR/collections tasks, ironically titled "(No Self Promotion)."

One accepted observation (#3, PropertyManagement maintenance-request triage)
retains a vendor's own product claim as a secondary evidence span, explicitly
labeled in its `problem` text as weaker evidence than the practitioner's own
framing in the primary span -- included, not excluded, because the primary
evidence is the practitioner's own words, with the vendor claim kept only as
market-validation context per the instruction not to discard useful provenance.

## 7. Evidence strength

This codebase's domain model does not have a `FIRST_PERSON`/`VENDOR_CLAIM`/
`THIRD_PARTY_DESCRIPTION` enum (checked before building anything new -- none
exists, and none was added, per instruction not to grow the ontology
speculatively). The operative distinction was applied qualitatively instead:
promotional/vendor-framed posts were excluded outright (Section 6); the one
observation that legitimately mixes a practitioner's own words with a nearby
vendor claim documents that distinction in its `problem` field rather than
inventing new structure. `active_solution_search` (an existing boolean field)
was used wherever a post was explicitly comparing named tools, which is the
closest existing structure to "this practitioner is actively shopping."

## 8. Clustering

`cluster-exact` (the existing, unmodified deterministic exact-fingerprint
algorithm) was run over all 10 observations: **10 clusters, all
single-observation, 0 multi-source clusters**. This is expected at n=10, not a
clustering defect -- exact-fingerprint matching requires near-identical
normalized actor/context/job/problem/root-cause text, which 10 independently
worded real posts will essentially never share. Per the existing principle, none
of the 3 strong single signals need cluster membership to remain visible; they
are visible in the funnel table above regardless. No cross-source recurrence
(e.g. "manual invoice/bill processing" appearing in both Accounting and
restaurantowners as *related but differently worded* problems) was mechanically
detected, because exact-fingerprint clustering cannot detect semantic
similarity -- this is a known, inherent limit of the existing algorithm, not
something this pilot changed or attempted to fix.

## 9. LLM / model usage

| Stage | Calls | Notes |
|---|---:|---|
| Prefilter | 0 | No model-backed prefilter exists; only a SQL length check. |
| Classification | 0 | No separate classification step exists in this codebase. |
| Extraction | 1 pipeline run (114 items) | Predictions supplied by the calling agent directly, not a separately-metered API call. |
| Embedding | 0 | Not used anywhere in this pipeline. |
| Clustering | 0 model calls | `cluster-exact` is deterministic SQL/hashing. |

Tokens: 0 input, 0 output (honestly recorded as 0, not estimated, because no
separately-metered API call was made for this extraction pass -- see Section 3).
**This does not mean extraction is free or automatic.** It means this baseline's
extraction step was performed by the same agent producing this report, which is
not a repeatable, unattended process at a larger scale. Cost per usable item /
per observation / per strong signal: **UNKNOWN** (`cost_reporting.py`'s existing
`build_cost_efficiency_report` correctly reports this as `UNKNOWN`, not $0 --
`missing_cost_operation_count: 255`, `missing_cost_run_count: 1`). Reddit
acquisition cost: confirmed **€0**.

## 10. Processing efficiency

- Total acquisition runtime: ~2.9 seconds of latency across 5 requests (plus
  politeness spacing, not counted as "processing").
- Total extraction/review time: not separately instrumented (performed inline
  by the calling agent in this session).
- Total LLM calls: 0 separately-metered calls; 1 `model_runs` row recorded for
  provenance with `provider=manual, model=human-reviewer` and 0 tokens.
- Items/minute, cost per usable item, cost per observation, cost per strong
  signal: **not meaningfully calculable** from this run, because the extraction
  step had no per-item wall-clock or token instrumentation. This is an honest
  gap to note for the next phase, not a number to estimate.

## 11. Arctic Shift provider quality (kept separate from research quality)

| Metric | Value |
|---|---|
| Requests | 5 |
| Failures | 0 |
| Total latency | 2878 ms |
| Records received | 250 |
| Removed/deleted rate | 35.6% (89/250) |
| FULL rate | 45.6% (114/250) |
| METADATA_ONLY (non-removed) rate | 18.8% (47/250) |
| Archive lag (retrieved_on - created_utc), newest post sampled | ~12 sec (measured during the earlier 20-item PoC) |

No 429s, no auth required, zero cost -- consistent with the earlier 20-item PoC.

## 12. The 10 accepted problems

1. **r/Accounting** -- small business handles vendor bill pay manually
   (email/Slack invoices → manual bank ACH → manual reconciliation, weekly).
   Actor: small business finance owner. Workaround: MULTIPLE_TOOLS.
   **STRONG.** 1 observation, 1 subreddit.
   https://www.reddit.com/r/accounting/comments/1wktm98/

2. **r/Accounting** -- affiliate-network payout operator hits a $5k/day cap on
   every centralized crypto processor tried, cannot find a compliant
   high-volume decentralized alternative. Quantified impact: $5,000/day/person
   cap. **WEAK** (missing context/workaround field in this extraction pass,
   despite having quantified impact). 1 observation, 1 subreddit.
   https://www.reddit.com/r/accounting/comments/1wkjt48/

3. **r/PropertyManagement** -- maintenance requests arrive across uncoordinated
   channels (text/email/WhatsApp/calls), manually triaged into AppFolio;
   evidence includes a vendor's own pitch, explicitly flagged as weaker
   evidence than the practitioner's own framing. **WEAK.** 1 observation, 1
   subreddit. https://www.reddit.com/r/propertymanagement/comments/1wksk3h/

4. **r/PropertyManagement** -- 50-unit PM company outgrowing informal tracking
   of owner onboardings/lease renewals/vacancies; actively comparing LeadSimple
   and Notion, neither fits. Actor: 50-unit PM company owner. **WEAK** (missing
   context/workaround field). 1 observation, 1 subreddit.
   https://www.reddit.com/r/propertymanagement/comments/1wjvizq/

5. **r/PropertyManagement** -- six-property, two-state operation ran unit walks
   three different ways (paper, an Excel sheet only one manager understood,
   unarchived group-chat photos) before centralizing. Workaround:
   MULTIPLE_TOOLS. **WEAK** (no active-search/quantified/payment signal in this
   extraction). 1 observation, 1 subreddit.
   https://www.reddit.com/r/propertymanagement/comments/1wiul95/

6. **r/FreightBrokers** -- broker relays unverified carrier-portal container
   status to customers, causing failed pickups ~twice a month; no clear
   industry norm for whether to wait for triple confirmation. **WEAK.** 1
   observation, 1 subreddit. https://www.reddit.com/r/freightbrokers/comments/1wi8ybe/

7. **r/FreightBrokers** -- small brokerage (<200 loads/month) dissatisfied with
   its TMS (Rose Rocket), actively comparing Sunnybrook/ascend/Tai, no fit yet.
   Thin signal (one short post, no detail on the actual complaint). **WEAK.** 1
   observation, 1 subreddit. https://www.reddit.com/r/freightbrokers/comments/1wi4k2m/

8. **r/restaurantowners** -- 14-location, ~300-employee chain schedules staff
   in per-GM spreadsheets; unbudgeted overtime slips through every pay period,
   managers spend hours rebuilding schedules after call-outs; owner quantifying
   the loss before buying software. Workaround: SPREADSHEET. **STRONG.** 1
   observation, 1 subreddit. https://www.reddit.com/r/restaurantowners/comments/1wku4e7/

9. **r/restaurantowners** -- DoorDash denies refunds for misdelivered orders
   under a 100m-radius policy, "happens ALL THE TIME," no effective recourse.
   **WEAK** (unquantified, though recurring). 1 observation, 1 subreddit.
   https://www.reddit.com/r/restaurantowners/comments/1wi2evm/

10. **r/restaurantowners** -- new cafe owner has no reliable way to track daily
    sales without buying a POS system; comparing Excel/Sheets/fully manual.
    Workaround: SPREADSHEET. **STRONG.** 1 observation, 1 subreddit.
    https://www.reddit.com/r/restaurantowners/comments/1whqwvl/

No problem appears in more than one subreddit or more than one observation in
this sample -- cross-source recurrence was not observed at n=250/n=114, not
because the mechanism to show it (Section 8) doesn't exist.

## 13. Failures, false positives, and ambiguous cases

- **Likely false negatives (useful-looking posts the review rejected)**: r/Accounting
  #66 (a lease-clause contradiction / CAM-reconciliation research post) and
  r/FreightBrokers #98 (a detention-pay research question) both read as
  possible market/product research by someone building a tool, similar to the
  confirmed promotional cases in Section 6, but without an explicit disclosure
  like AcreTerminal's -- excluded on the conservative side rather than
  extracted on ambiguous evidence. A future pass with more signal (author
  history, cross-posting pattern) might resolve these either way.
- **Ambiguous extractions kept in**: #3 and #4 above mix practitioner testimony
  with market-validation context; kept, with the mixture explicitly noted in
  the `problem` text rather than silently blended.
- **Promotional contamination**: 4 confirmed cases, detailed in Section 6, all
  excluded.
- **Completeness problems**: r/PropertyManagement contained two exact-duplicate
  postings of the same "eight questions" advice essay under different
  submission IDs (`1wksk2f` and `1wksiq3`, not part of this run's 37 FULL
  items' overlap but observed in the earlier 20-item PoC) and two duplicate
  "privacy issues in a few units" posts in this run (ids 64/65) -- each became
  its own canonical SourceItem correctly (different Reddit identities), but a
  human reviewer would recognize them as the same author's repeated content,
  which the system does not currently detect or flag.
- **Clustering mistakes**: none observed (10/10 correctly left as singletons;
  no incorrect merge or split was possible to observe at this sample size).

## 14. Rights status (unchanged)

`ArcticShiftRedditProvider.readiness = CONTRACT_REVIEW_REQUIRED`
(`ProductionReadiness` enum value). Technically validated; commercial usage
rights remain under review. This pilot does not change that status. See
`docs/providers/arctic-shift-rights-checklist.md`.

## 15. Most important question

**Would a founder looking for real operational problems learn something
genuinely useful from this dataset?**

Partially, and unevenly. Three of the ten problems are concrete, specific, and
immediately actionable as SaaS wedges: manual AP/bill-pay workflow (Accounting),
multi-location staff scheduling with quantifiable overtime leakage
(restaurantowners), and no-POS sales tracking for a new cafe
(restaurantowners) -- a founder reading these three would learn something real
and could start a conversation with each poster today. The other seven are
genuine but thinner or less immediately buildable (a data-trust gap in freight
dispatch, a DoorDash policy complaint with no software angle, active-search
signals with almost no detail). Two whole communities in this sample
(r/HVAC entirely, and much of r/FreightBrokers/r/PropertyManagement) did not
surface software-workflow pain at the volume sampled -- either because the
material isn't there in this window, or because it's diluted by career talk,
legal disputes, and promotional posts that a human reviewer had to filter out
by hand. A founder would learn real things from this dataset, but would also
need to read past a lot of noise to get there, and the noise-filtering step
(promotional detection, career/interpersonal-post rejection) is not yet
automated.

## 16. Recommendation

**`DISCOVERY_PIPELINE_NEEDS_TUNING`**

Not based on the count of extracted problems (10 is a real, non-trivial
result at this sample size). Based on the full criteria set:

- **Acquisition quality**: excellent. 5/5 requests succeeded, deterministic and
  reproducible, zero cost, zero failures.
- **Usable-content rate**: honest and reasonable (45.6%), but highly uneven by
  source (18%-82%), driven by moderation/removal rates the pipeline correctly
  surfaces but cannot control.
- **Extraction precision**: high, by construction (every evidence span is
  exact-matched; nothing was force-extracted to inflate the count; 4
  promotional posts were caught and excluded).
- **Evidence grounding**: strong -- 100% of accepted evidence is verbatim
  source text.
- **Problem usefulness**: real but uneven; 3 of 10 are strong, immediately
  actionable signals; several others are thin.
- **Clustering quality**: mechanically correct at this sample size; its
  inherent inability to detect semantic (not exact-text) recurrence is a real,
  pre-existing limitation this pilot surfaced but did not create.
- **Operational reliability**: the acquisition, ingestion, evidence-validation,
  signal-policy, and clustering stages are all reliable and required no
  changes. The extraction stage is the actual gap: it has zero automation in
  this codebase and was performed by the calling agent reading all 114 items
  by hand. That is not repeatable at 25-source scale (potentially 1,000+
  usable items) without either a real, metered LLM extraction integration or
  an explicit plan to keep doing this manually at a much larger volume.

The tuning needed before a 25-source pilot is specifically: (a) wire a real,
metered LLM extraction call into `ProblemExtractor` so this stage stops
depending on the calling agent's direct reading, and (b) add a lightweight,
explicit promotional/vendor-content signal so it doesn't have to be caught by
manual review every time. Neither requires changing thresholds, prompts on an
existing model, or clustering/signal-policy logic -- both are new capability,
not tuning of what exists. Per instructions, this baseline was not rerun after
identifying these gaps.
