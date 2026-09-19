# Experimental data — not approved production research evidence

`reddit_rss_pilot_predictions.jsonl` contains 2 manually-extracted, evidence-
verified observations from the 2026-09-19 Reddit RSS PoC. They demonstrate the
extraction pipeline works correctly (every evidence excerpt is checked byte-for-
byte against real source text by `JsonlPredictionExtractor`), but they are
**not approved benchmark or research evidence**: the underlying content was
acquired through a provider (`RedditRssProvider`) that is `POLICY_BLOCKED`
because reddit.com's `robots.txt` disallows automated access. See
`exports/experimental/reddit_rss/README.md` and
`docs/decisions/0002-reddit-rss-free-acquisition.md`.
