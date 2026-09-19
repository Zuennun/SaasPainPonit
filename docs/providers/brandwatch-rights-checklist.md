# Brandwatch Consumer Research: Reddit rights and PoC checklist

Status: **CONTRACT_REVIEW_REQUIRED**. No production approval is implied by technical access.

Before a live PoC, configure five Reddit-only Consumer Research queries, one per
subreddit in `brandwatch-poc.json`. Put their numeric IDs in that file. Use a
short-lived `BRANDWATCH_ACCESS_TOKEN` and `BRANDWATCH_PROJECT_ID` from the
environment. Do not commit credentials, API responses, or raw Reddit text.

Ask Brandwatch/Cision to answer these questions **in writing for our exact use case**:

1. Does the Consumer Research API's `/data/mentions/fulltext` return complete
   Reddit submission bodies and comments, or only previews? Which fields signal
   truncation? Can we inspect 10–20 examples from the selected subreddits?
2. May we store titles, bodies, comments, author identifiers, canonical URLs,
   and provider records in our own database? What retention period applies?
   Can raw text instead be held only in memory for a PoC?
3. May we send this content to third-party LLMs for classification, extraction,
   embeddings, and clustering? Which processors, regions, and safeguards apply?
4. After source content expires or is deleted, may we retain ProblemObservations,
   ProblemClusters, embeddings, claims, aggregate metrics, and derived insights?
5. May a separate paid SaaS display derived problem/market intelligence to its
   customers? Is resale or sublicensing of derived data allowed?
6. What may be displayed: short quotes, titles, usernames, links, full text?
   Are there quote-length, attribution, or linking requirements?
7. How are Reddit/Brandwatch deletions or corrections notified? What must we
   delete, update, or suppress, and by when?
8. What limits apply to mentions, fulltext calls, historical queries, exports,
   API calls, and concurrent access? What metered usage or monetary charges apply?
9. Does the licence expressly allow a **separate commercial SaaS** that analyzes
   licensed Reddit data and exposes derived problem intelligence to paying users?
10. Are all five requested communities available, and can each be filtered
    reliably? Are submission/comment IDs and parent/thread IDs exposed?

Technical basis, not a rights grant:

- Reddit confirms its [Cision data partnership](https://redditinc.com/news/building-on-our-partnership-with-cision).
- Brandwatch documents [Reddit coverage, subreddit filtering, exports, and API
  availability](https://social-media-management-help.brandwatch.com/en/articles/16414214-overview-of-changes-to-brandwatch-s-reddit-coverage-august-2026).
- Brandwatch documents [Bearer-token authentication](https://developers.brandwatch.com/docs/authenticate)
  and a separate [fulltext endpoint](https://developers.brandwatch.com/docs/retrieving-mentions).
- [Data restrictions](https://developers.brandwatch.com/docs/data-restrictions)
  can vary by content source and contract. Verify actual account output.

Run only the first stage (maximum 20 records):

```bash
python -m problem_intelligence.brandwatch_poc \
  --start-date 2026-09-01 --end-date 2026-09-19
```

The runner keeps raw text in memory and writes metrics only to `exports/`.
`FULL` means a non-empty `fullText` field returned by the fulltext endpoint;
sample inspection must still confirm that the field is truly untruncated.
No extractor is run automatically: an approved local extraction mechanism must
be explicitly supplied before testing evidence spans on real content.

Second stage (50–100 per community, 250–500 total) is intentionally not wired
to this command. Authorize and implement it only after the first stage shows
usable content, stable identity, and a documented rights position.
