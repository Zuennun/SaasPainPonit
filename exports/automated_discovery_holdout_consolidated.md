# Automated discovery holdout — final consolidated funnel

Status: **INFERENCE_COMPLETED_CONSOLIDATED** (runs 1-5, acquisition cost €0).

- Acquired 250 unseen posts; 130 usable FULL items
- Screened OK: 130/130 (no silent gaps)
- Valid problem observations: 46 (evidence spans: 120)
- Strong signals (multi-source recurring): 0 — all observations remain SINGLE_SIGNAL

## Observation field fill (extraction schema pressure)

Of 46 observations: context 17, actor 14, active_solution_search 11, job_to_be_done 10, current_workaround 7, time_impact 3, financial_impact 1, tools_used 0, switching_intent 0

## Provider usage (model_runs totals)

- `claude_cli`: screening OK 25, extraction OK 1, failed runs 23 (aborted/oversized earlier runs included)
- `codex_cli`: screening OK 93, extraction OK 32, failed runs 726 (aborted/oversized earlier runs included)
- `openai_compatible`: screening OK 74, extraction OK 13, failed runs 220 (aborted/oversized earlier runs included)

## Latest model-produced examples

- Tired of dealing with mid rate agents at this carrier. | actor: None | ctx: at jones motor Co | workaround: None | https://www.reddit.com/r/freightbrokers/comments/1w6pv1x/
- But man the time wasted sending back an "What's your MC#?" email is mind boggling in this day and age. | actor: None | ctx: I have regular freight but it's every other week so I really can't lock in regular carriers and just can't build relationships with anyone when fuel keeps hitting $6/gal every 6 weeks. | workaround: I post all my loads to DAT, email only. | https://www.reddit.com/r/freightbrokers/comments/1w7hq0z/
- Asked For pictures of the load and noticed the company picking up wasn’t the company we booked. | actor: Im a new broker and have been on the owner operator side of things for 10 years. | ctx: This brought me to check a load that was delivered yesterday also booked through email. | workaround: We do cash on deliveryZelle/wire and are only currently using the safer website to check the carriers. | https://www.reddit.com/r/freightbrokers/comments/1w7jull/
- Should I worry that I have a data leak somewhere in my workflow? | actor: Sales advisor | ctx: ginormous expensive software that we use, which emails customers on our behalf | workaround: None | https://www.reddit.com/r/hvac/comments/1w6aoyj/
- leaving doors to walk in coolers wide open | actor: kitchen staff | ctx: I recently started doing more refrigeration stuff | workaround: None | https://www.reddit.com/r/hvac/comments/1w6gjds/

Human precision review is pending via exports/automated_discovery_review.csv.
Semantic recurrence remains a separate clustering gap; thresholds unchanged.
