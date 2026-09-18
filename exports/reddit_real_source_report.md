# Reddit source experiment

This report separates discovery from content acquisition. Partial captures are not reported as complete threads, and metadata-only or failed captures are not eligible for extraction.

## Summary

- Search requests: 6
- Provider results: 7
- Reddit URLs discovered: 7
- Unique canonical URLs: 6
- Duplicate discoveries removed: 1
- Acquired content records: 6
- Extraction-eligible items: 6
- Structured observations: 5
- Known processing cost (USD): 0.0000
- Requests/attempts with unknown cost: 12

## Per-community metrics

| Community | Requests | Availability | Discovered | Unique | Duplicates | Acquired | Full | Partial | Metadata | Failed | After prefilter | Observations | Active | Quantified | Payment | Strong | Cost | Errors |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| r/Accounting | 1 | RESULTS:1 | 2 | 1 | 1 | 1 | 0 | 1 | 0 | 0 | 1 | 1 | 0 | 0 | 0 | 0 | unknown (2 records) | 0 |
| r/restaurantowners | 1 | RESULTS:1 | 1 | 1 | 0 | 1 | 0 | 1 | 0 | 0 | 1 | 1 | 0 | 0 | 0 | 0 | unknown (2 records) | 0 |
| r/airbnb_hosts | 1 | RESULTS:1 | 1 | 1 | 0 | 1 | 0 | 1 | 0 | 0 | 1 | 1 | 1 | 0 | 0 | 0 | unknown (2 records) | 0 |
| r/SEO | 1 | RESULTS:1 | 1 | 1 | 0 | 1 | 0 | 1 | 0 | 0 | 1 | 1 | 1 | 0 | 0 | 1 | unknown (2 records) | 0 |
| r/smallbusiness | 1 | RESULTS:1 | 1 | 1 | 0 | 1 | 0 | 1 | 0 | 0 | 1 | 1 | 0 | 1 | 0 | 1 | unknown (2 records) | 0 |
| r/AppIdeas | 1 | RESULTS:1 | 1 | 1 | 0 | 1 | 0 | 1 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | unknown (2 records) | 0 |

Strong single signals require a clear actor and job, context or a documented workaround, and quantified impact, payment evidence, active solution search, or switching intent. They are leads, not validated opportunities.

### Normalized source performance

| Community | Sample items | Observations/1k | Strong/1k | Active/1k | Payment/1k | Processing cost/1k USD | Sample warning |
|---|---:|---:|---:|---:|---:|---:|---|
| r/Accounting | 1 | 1000.0 | 0.0 | 0.0 | 0.0 | unknown | tiny sample; rates are descriptive only |
| r/restaurantowners | 1 | 1000.0 | 0.0 | 0.0 | 0.0 | unknown | tiny sample; rates are descriptive only |
| r/airbnb_hosts | 1 | 1000.0 | 0.0 | 1000.0 | 0.0 | unknown | tiny sample; rates are descriptive only |
| r/SEO | 1 | 1000.0 | 1000.0 | 1000.0 | 0.0 | unknown | tiny sample; rates are descriptive only |
| r/smallbusiness | 1 | 1000.0 | 1000.0 | 0.0 | 0.0 | unknown | tiny sample; rates are descriptive only |
| r/AppIdeas | 1 | 0.0 | 0.0 | 0.0 | 0.0 | unknown | tiny sample; rates are descriptive only |

## Provider performance

| Provider | Role | Requests | Results | Reddit URLs | Unique URLs | Success | Full | Partial | Failure | Latency | Cost | Capabilities |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|
| openai-web-search | search | 6 | 7 | 7 | 6 | n/a | n/a | n/a | n/a | unknown | unknown | supports_historical_search, supports_search, supports_subreddit_filter |
| openai-web-page | acquisition | 6 | 0 | 0 | 6 | 100.0% | 0.0% | 100.0% | 0.0% | unknown | unknown | supports_comments, supports_historical_search |

## Observed examples

### r/airbnb_hosts: A host cannot export booking dates, prices, and earnings into Excel.

> I can't figure out how to export my bookings data such as dates, prices, and earnings into Excel.

Source: https://www.reddit.com/r/airbnb_hosts/comments/1qtpnfo/

### r/SEO: Recurring SEO reporting still requires manual data entry.

> I feel many things I do manually could be automated. I hate reporting and it involves so much manual data entry.

Source: https://www.reddit.com/r/seo/comments/hp9l64/

### r/smallbusiness: Disconnected business applications require repeated manual data transfer.

> I spend half my week moving data from one app to another because nothing actually talks to each other.

Source: https://www.reddit.com/r/smallbusiness/comments/1ry01nd/

### r/Accounting: Accounting figures are manually copied into several tracking spreadsheets.

> There were three other accounting tracking spreadsheets that those numbers got manually posted to.

Source: https://www.reddit.com/r/accounting/comments/153xylq/

### r/restaurantowners: Restaurant scheduling apps lose practical value when staff adoption is incomplete.

> Personally I've found spreadsheets to work most reliably. Apps have promise, but getting perfect adoption is difficult.

Source: https://www.reddit.com/r/restaurantowners/comments/17r6dbm/

## Errors and unavailable inputs

None recorded.

## What worked

- External search captures produced canonical Reddit identities.
- Duplicate URL variants converged on one research item.
- Eligible English excerpts passed through the existing extraction pipeline.
- The control community produced no structured problem observation.

## What failed or remains limited

- All 6 acquired items are partial captures; no thread is claimed complete.
- Provider cost was not supplied for 12 requests/attempts, so cost-per-1,000 is unknown.
- Acquisition failures or policy blocks: 0.
- Every community sample is below 100 items; normalized rates are descriptive only.

## Next technical blocker

Identify and approve a permitted provider that can return reproducible full post content (and clearly scoped comments) with measured latency and cost.
