# Automated discovery holdout — final consolidated funnel

Status: **INFERENCE_COMPLETED_CONSOLIDATED** (runs 1-5, acquisition cost €0).

- Acquired 250 unseen posts; 130 usable FULL items
- Screened OK: 130/130 (no silent gaps)
- Valid problem observations: 34 (evidence spans: 71)
- Strong signals (multi-source recurring): 0 — all observations remain SINGLE_SIGNAL

## Provider usage (model_runs totals)

- `claude_cli`: screening OK 23, extraction OK 1, failed runs 20 (aborted/oversized earlier runs included)
- `codex_cli`: screening OK 78, extraction OK 24, failed runs 674 (aborted/oversized earlier runs included)
- `openai_compatible`: screening OK 74, extraction OK 9, failed runs 196 (aborted/oversized earlier runs included)

## Latest model-produced examples

- Broker prospecting outreach the shipper receives is generic, low-value, and indistinguishable from spam. | actor: A shipper (and former broker) who receives inbound broker prospecting. | ctx: None | workaround: None | https://www.reddit.com/r/freightbrokers/comments/1w4vw5u/
- Difficulty delivering upsetting news about extremely high renewal offers. | actor: None | ctx: None | workaround: None | https://www.reddit.com/r/propertymanagement/comments/1w5owsv/
- A newly started property manager feels overwhelmed and wants help managing it. | actor: New property manager. | ctx: Has worked in the industry for a little over two years. | workaround: None | https://www.reddit.com/r/propertymanagement/comments/1w5ssz4/
- The manager consistently moves residents into apartments with roaches. | actor: APM at a multifamily property. | ctx: None | workaround: None | https://www.reddit.com/r/propertymanagement/comments/1w6836y/
- Available affordable software lacks asset inventory tracking functionality. | actor: None | ctx: Has 33 units and inherited almost no asset inventory documentation. | workaround: Uses Excel for asset inventory tracking. | https://www.reddit.com/r/propertymanagement/comments/1w695ln/

Human precision review is pending via exports/automated_discovery_review.csv.
Semantic recurrence remains a separate clustering gap; thresholds unchanged.
