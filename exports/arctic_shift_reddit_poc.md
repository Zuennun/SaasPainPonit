# Arctic Shift Reddit PoC (live run, 2026-09-19)

Status: **CONNECTED**. Technical status: **VALIDATED**. Usage rights: **REVIEW_REQUIRED** (public/free API access does not itself prove unrestricted commercial rights -- see `docs/providers/arctic-shift-rights-checklist.md`).

## Connectivity

Arctic Shift's own `robots.txt` (`Disallow:` empty for `User-agent: *`) explicitly permits automated access -- verified live before any request was made, unlike the earlier direct reddit.com RSS path. 5 of 5 requests succeeded (one per subreddit: r/Accounting, r/restaurantowners, r/PropertyManagement, r/HVAC, r/FreightBrokers). No 429s, no credentials required. Total latency 2096 ms across 5 requests.

## RSS structure

N/A for this provider -- Arctic Shift returns `{"data": [<post>, ...]}` JSON via `/api/posts/search`, not a feed format. One real bug found and fixed during verification: for link/image posts, the `url` field is the post's external target (e.g. `i.redd.it`), not a Reddit URL -- `permalink` (reddit.com-relative) is the reliable Reddit identity field for every post shape. Also confirmed live: the `fields` query parameter only accepts a narrower whitelist that excludes `removed_by_category` and `permalink`, so this provider always requests full objects instead of using it.

## Coverage

All 5 requested communities returned records: r/Accounting (4), r/restaurantowners (4), r/PropertyManagement (4), r/HVAC (4), r/FreightBrokers (4) -- 20 total, within the 10-20 target.

## Freshness

Newest available post per community ranged from ~2 minutes to ~2 hours old at retrieval time (r/Accounting: 126s; r/HVAC: 1487s; r/PropertyManagement: 2885s; r/restaurantowners: 4649s; r/FreightBrokers: 7441s). Archival lag (retrieved_on - created_utc) measured separately during manual verification was ~12 seconds for the single newest post checked. Arctic Shift is not a stale or delayed archive for recent content; it is not real-time-guaranteed either -- treat it as near-real-time, consistent with the product's own tolerance for some acquisition delay.

## Historical access

`after`/`before` (date strings, e.g. `2026-09-01`) were verified live before building the provider: a 1-day window returned exactly the posts from that window, correctly excluding others. `limit` was verified up to 100 (the documented maximum). Deep pagination beyond one `after`/`before` window is left to a future orchestrator to drive across multiple calls; this provider's `discover`/`fetch_fulltext` do not claim an opaque `page` number beyond page 0.

## Completeness

Records received: 20. Normalized: 20. **FULL: 8. PARTIAL: 0. METADATA_ONLY: 12** (1 genuine link/image post with no body, 11 removed or deleted -- excluded from the research run, not force-included). Notable finding: removal rates varied sharply by community in this small sample -- r/PropertyManagement had 0/4 removed, r/Accounting 1/4, r/HVAC 3/4, r/FreightBrokers 3/4, r/restaurantowners 4/4 (all 4 of its sampled posts were removed or deleted). This is a 4-item sample per community and must not be read as a verdict on any community's moderation policy or research value -- it is a reason to sample more before drawing conclusions, exactly why this phase stays small.

## Research quality

All 8 real FULL items were read and reviewed (not a cherry-picked subset): 2 were genuine, evidence-groundable professional-operator problems; the other 6 were a homework-help request, a career-change question, workplace interpersonal venting, a landlord-late-fee calculation question, and a promotional/advice post duplicated across two threads by the same account -- none of those six were forced into an extraction to inflate the count.

Extracted (via the same evidence-integrity-checked `JsonlPredictionExtractor` + `run_extraction` pipeline every extractor uses, every excerpt verified byte-for-byte against stored source text): **2 pain observations** (r/Accounting: 1, r/PropertyManagement: 1). 0 strong signals (both are single-source, unquantified). 1 manual workaround signal. 0 quantified impact, 0 payment evidence, 0 active-solution-search signals captured as such, 0 internal/DIY workaround signals. 0 explicit NO_PAIN labels (no predictions file marked a negative this run). 6 items reviewed and not extracted (support question / career question / interpersonal / calculation question / promotional content x2).

**Sample size is 2 observations out of 8 real FULL items and 3 sources with any FULL content -- far too small to judge subreddit quality or extrapolate a rate.**

## Examples

1. **r/Accounting** -- https://www.reddit.com/r/accounting/comments/1wktm98/ -- "Small business handles vendor bill pay manually: invoices arrive via email/Slack, get checked, paid via manual bank ACH, then reconciled by hand each week." Evidence: "Invoices come in through email or Slack, I check them, log into the bank, send the ACH, mark them paid, then make sure the books match later." / "are you handling bill pay through your business bank, using a separate tool, or still doing most of it manually?" Workaround: MULTIPLE_TOOLS.

2. **r/PropertyManagement** -- https://www.reddit.com/r/propertymanagement/comments/1wksk3h/ -- "Property manager receives maintenance requests across many uncoordinated channels (text, email, WhatsApp, calls) that must be manually triaged and logged into their PM system (AppFolio) under the right tenant/unit/work order; a vendor is actively pitching automated intake as the fix, which itself signals the gap is real and being sold against." Evidence: "Let them text, email, WhatsApp, call, send pictures, whatever they already do." / "Apparently his system just catches all of it and gets it into AppFolio under the right tenant/unit/WO."

## Cost

Data acquisition cost: **€0**. No credentials, no paid tier, no proxies. Confirmed: the public search endpoint required no authentication for this entire PoC.

## Rights

**REVIEW_REQUIRED**, explicitly. Arctic Shift's own `robots.txt` permits automated *access*; that is a different question from whether this project has commercial rights to store, process, and derive product value from the content it returns. No written confirmation of commercial usage rights exists yet. See `docs/providers/arctic-shift-rights-checklist.md` for the unresolved questions to track.

## Recommendation

**ARCTIC_SHIFT_READY_FOR_LARGER_PILOT**

Connectivity, historical date-window access, completeness classification (including the removed/deleted exclusion), canonical ingestion, and evidence-grounded extraction all worked correctly against real, live content, at zero cost, under a robots.txt that explicitly permits this access. The controlled second stage (~50 posts x 5 subreddits, ~250 total maximum) is appropriate next -- not the full 25-source Wave 1 -- and should specifically sample more per community given how much the removal rate varied here. Usage rights remain REVIEW_REQUIRED and must be resolved before any production/commercial commitment, independent of this technical result.
