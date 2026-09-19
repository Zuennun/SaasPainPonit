# Reddit RSS PoC (live run, 2026-09-19)

**TECHNICAL EXPERIMENT — NOT AN APPROVED DATA ACQUISITION PATH.**
Reddit's `robots.txt` disallows automated access to all paths for all user agents
(`Disallow: /`), with no exception observed for `.rss`. This PoC's live requests
were made before that was correctly weighed against the project's own stated
constraint ("do not use endpoints Reddit disallows for automated crawling"). The
findings below are kept as a technical record — they are real and were not
fabricated — but the 50 SourceItems and 2 observations this PoC produced are
**excluded from the approved production research dataset** and must not count
toward source performance, opportunity counts, benchmark labels, or Wave 1
metrics. No further automated requests were or will be made against reddit.com
under this provider; see `docs/providers/reddit-rss-rights-checklist.md` and
`RedditRssProvider.readiness = POLICY_BLOCKED`.

Status: **CONNECTED** (4 of 5 planned sources; r/HVAC pending a retry after Reddit's rate limit) — technical result only, not a production status.

## Connectivity

4 of 5 RSS feeds worked: r/Accounting, r/FreightBrokers, r/PropertyManagement, r/restaurantowners. r/HVAC returned 429 on every attempt made during this session (3 attempts across ~10 minutes) and was not force-retried further; Reddit's own rate-limit headers (`x-ratelimit-remaining`, `x-ratelimit-reset`) showed a shared, IP-wide budget with an approximately 60-second reset window, not a per-subreddit limit. This empirically validates the task's own 90-second conservative default -- the first PoC attempt used a 5-second interval deliberately for a one-time manual test and immediately hit 429s on 3 of 5 sources; the retry at 90 seconds succeeded for 2 of the 3 remaining sources.

9 real HTTP requests were made in total across this session (including diagnostic checks); 4 returned usable feeds, 5 returned 429.

## RSS structure

The `.rss` path returns Atom (not RSS 2.0). Verified live fields: `<id>` (Reddit fullname, e.g. `t3_1tx1k5k`), `<link href>` (canonical permalink), `<title>`, `<author><name>` (`/u/username`), `<published>`, and `<content type="html">`. Self-text posts wrap their real body in `<!-- SC_OFF --><div class="md">...</div><!-- SC_ON -->`; link/image posts carry only the always-present `submitted by ... [link] [comments]` footer with no wrapper -- this, not content length, is what the parser uses to tell FULL apart from METADATA_ONLY.

## Completeness

60 entries returned across 4 successful feeds, 60 unique Reddit submissions, 0 duplicates. **FULL: 50. PARTIAL: 0. METADATA_ONLY: 10.** No PARTIAL case was observed in live data -- Reddit's Atom feed appears to deliver either the complete self-text or none at all (link/image posts), never a truncated preview, so this provider currently has no evidence-based PARTIAL path.

## Deduplication

No duplicates were created. All 50 FULL items produced distinct canonical Reddit identities and were ingested as 50 new SourceItems (0 pre-existing) through the same `Repository.ingest_reddit_content` path every other provider uses -- repeated/overlapping polling is protected by the same idempotency guarantee proven for Brandwatch in `tests/test_reddit_canonical_ingestion.py`, and by RSS-specific regression tests added this session (`tests/test_reddit_rss.py`).

## Rate limiting

Yes: 5 of 9 requests returned 429 during this session, all correctly mapped to `ProviderFailure.RATE_LIMITED` (never misread as `NO_RESULTS`). Reddit does not send a standard `Retry-After` header; it sends `X-Ratelimit-Reset` (seconds until reset) instead, which the provider now parses as a fallback -- this was discovered live and fixed during this session, along with a related bug: HTTP/2 responses return all header names lowercased, so the original exact-case header lookups (`ETag`, `Last-Modified`, `Retry-After`) would have silently failed; header lookup is now case-insensitive.

## Research quality

50 real FULL SourceItems are now stored (`data/reddit/reddit_rss_pilot.db`). A full automated extraction pass across all 50 was not run this session (no external LLM call is wired into this environment); instead, 2 of the clearest real examples were manually reviewed and extracted through the exact same evidence-integrity-checked pipeline every other extractor uses (`JsonlPredictionExtractor` + `run_extraction`), with every evidence excerpt verified byte-for-byte against the stored source text before submission -- the pipeline would have rejected any excerpt that didn't match exactly.

Extracted: **2 pain observations**, both from r/restaurantowners (0 from the other 3 sources -- not reviewed yet, not confirmed absent). 0 strong signals (the strong-signal rule requires more than a single-source, unquantified signal). 0 active solution searches captured as such. 0 quantified impact. 0 payment evidence. 1 manual workaround signal (spreadsheet/manual tracking in place of a POS system). 0 internal/DIY workaround signals.

**Sample size is 2 observations out of 50 real items and 4 sources -- this is far too small to judge subreddit quality or extrapolate a rate. It demonstrates the pipeline works end-to-end on real data, nothing more.**

## Examples

1. **r/restaurantowners** -- https://www.reddit.com/r/restaurantowners/comments/1whqwvl/ -- "New cafe owner has no reliable way to track daily sales without buying a POS system." Evidence: "I don't wanna get a POS right away, so for those of you who already run cafes/restaurants, how do you manage this?" / "Do you use Excel, Google Sheets, some other tool or just keep it manual?" Workaround: SPREADSHEET (considering Excel/Google Sheets or fully manual tracking).

2. **r/restaurantowners** -- https://www.reddit.com/r/restaurantowners/comments/1wi2evm/ -- "Restaurant using DoorDash for delivery gets refund requests for misdelivered orders denied by DoorDash's 100m-radius policy, with no effective recourse, and reports this happens repeatedly." Evidence: 'went to ask for a refund, and DD said "Refund Amount: $0.00 Refund Explanation: Never Delivered refunds cannot be processed for orders where the Dasher delivered the order within 100m of the customer address."' / "It happens ALL THE TIME - wrong apartment, wrong house, and in this case, wrong business." Impact: REVENUE, qualitative, recurring.

## Cost

Reddit data acquisition cost: **€0**. No paid provider, no official API, no proxies.

## Recommendation

**RSS_TECHNICALLY_VALIDATED_POLICY_BLOCKED**

Connectivity, completeness classification, canonical ingestion, and evidence-grounded extraction all worked correctly against real, live content, and the engineering findings (Atom structure, FULL/METADATA_ONLY signal, IP-wide rate limiting, `X-Ratelimit-Reset`, lowercased HTTP/2 headers) are real and reusable. None of that changes the access-policy finding: reddit.com's `robots.txt` disallows automated access, so this path is **not** approved for Wave 1 or any further live use regardless of technical success. The originally-stated recommendation, `RSS_READY_FOR_WAVE_1`, is withdrawn.
