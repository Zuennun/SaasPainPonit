# Reddit RSS experiment — not approved production data

Everything in this directory came from a live technical PoC run on 2026-09-19
against reddit.com's public RSS feeds. Reddit's `robots.txt` disallows automated
access to all paths for all user agents; that was correctly weighed against this
project's own zero-cost RSS plan only after the PoC had already run.

**Nothing in this directory counts as approved research evidence.** It must not
contribute to source performance, opportunity counts, benchmark labels, source
ranking, Wave 1 metrics, or any production report. It is kept only because the
underlying engineering findings (Atom feed structure, FULL/METADATA_ONLY
classification behavior, rate-limit and HTTP header handling) are real, useful,
and worth preserving as a technical record.

`RedditRssProvider.readiness` is `POLICY_BLOCKED`. See
`docs/providers/reddit-rss-rights-checklist.md` for the current access status and
`docs/decisions/0002-reddit-rss-free-acquisition.md` for the correction.

- `reddit_rss_poc.md` — the PoC report, banner-marked as a technical experiment.
- `reddit_rss_poc_metrics.json` — raw metrics, with `_excluded_from_production_dataset: true`.
- `reddit_rss_research_quality.csv` — acquisition/research-quality breakdown from the same run.
