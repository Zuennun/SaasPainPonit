# Research captures

Competition, DACH-transfer, and counter-evidence research often uses several
different publishers in one bounded pass. `ingest-research-jsonl` accepts this
heterogeneous evidence without erasing the policy attached to each source.

Every JSONL row contains a `source` and an `item`. Unlike the simpler operator
export connector, all source-policy fields are mandatory:

- access method;
- commercial-use status;
- retention rules;
- attribution requirements;
- quoting rules;
- deletion requirements;
- rate-limit notes; and
- rights-review date.

Unknown rights are written explicitly, for example
`UNKNOWN_REQUIRES_REVIEW`. This permits internal research while preventing the
capture from being mistaken for production-display approval. A complete file is
validated before the first database write, and replay is idempotent by normalized
source and external item identity.

```bash
problem-intelligence ingest-research-jsonl \
  --database research.db \
  --file data/research/seo_reporting_research_v1.jsonl
```

The included SEO reporting capture intentionally distinguishes official
documentation from vendor marketing. Vendor statements carry a bias warning in
item metadata and must not be represented as independent customer testimony.
Reports withhold those excerpts by default while their commercial display status
is `UNKNOWN_REQUIRES_REVIEW`.
