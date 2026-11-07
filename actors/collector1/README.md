## What does Collector1 do?

**Collector1** collects resumable **public Dhaka Stock Exchange (DSE)** historical data. It ingests staged public end-of-day CSV, XLSX, and ZIP files, and it can download public documents from [Dhaka Stock Exchange](https://www.dsebd.org/) and [Bangladesh Securities and Exchange Commission](https://sec.gov.bd/) hosts. It separates raw receipts, accepted rows, quarantined rows, and failures. It does **not** log into StockNow, bypass challenges, or call private APIs. A metadata-only link is never stored as a verified annual report.

## Why use Collector1?

Use Collector1 when a later run needs a checkpointed, bounded pass over public DSE files:

- Public financial-document discovery, download, and indexing.
- Staged public EOD ingestion with company and period matching.
- SHA-256 dedup that does not overwrite the first canonical bar.
- Idempotent checkpoint queues so a stopped run can resume.
- Per-domain backoff after HTTP 429 and a concurrency ceiling.
- Request, byte, and runtime limits with a hard ceiling.
- Coverage for unknown and explicitly non-trading sessions without calling them proven-missing.
- Field-by-field validation, including legitimately negative NAV.

Apify adds scheduling, a dataset API, and key-value storage for the checkpoint and manifests. This actor does not finish the full DSE history by itself. Scale a run only after a small measured result is useful.

## What data can Collector1 extract?

| Field | Type | Description |
| --- | --- | --- |
| `lane` | text | `raw`, `accepted`, `quarantine`, or `failure` |
| `recordType` | text | EOD bar, company profile, financial document, coverage gap, or failure |
| `symbol` | text | Trading code. A conflicting code is not spliced over the declared one |
| `tradeDate` | text | ISO date parsed from DSE day-month-year formats |
| `close` | number | Close, when the row is a price bar |
| `nav` | number | NAV, which may be negative |
| `documentClaim` | text | `metadata_only`, `unverified_document`, or `verified_annual_report` |
| `verifiedAnnualReport` | boolean | True only after bytes, PDF type, period, and company all match |
| `absenceStatus` | text | `observed`, `unknown`, or `non_trading` |
| `provenMissing` | boolean | Always false |
| `contentSha256` | text | Content hash used for dedup |
| `quarantineReasons` | array | Why a row was held back |

You can download the dataset as JSON, CSV, HTML, or Excel.

## How to collect public DSE data

1. Open the actor input and keep the default limits for the first run.
2. Paste public `eodUrls` or `documentUrls` on `dsebd.org` or `sec.gov.bd`, or add `stagedFiles` whose `sourceUrl` is on that allowlist.
3. Add `symbols` and `sessions` only when you want a coverage manifest.
4. Leave `sample` false for real files. A sample row is labeled and cannot become a verified annual report.
5. Run the actor. Read `RUN_SUMMARY`, `COVERAGE_MANIFEST`, `FAILURE_MANIFEST`, and `CHECKPOINT`.
6. For a later run, pass the previous `CHECKPOINT` or keep `resume` true so completed items are skipped.

The local smoke fixture is synthetic. It is not a DSE publication and must not be merged into market history.

## How much will it cost to run Collector1?

Collector1 uses Apify compute units. The default input allows 20 requests, 120 seconds, and 20 MB. Start the platform run at 512 MB. Do not raise memory, request caps, or the runtime until one small run shows useful new rows. A large history backfill is a separate measured job. This package does not publish a paid store listing and does not change the account plan.

## How to deploy Collector1 later

Deploy with an existing Apify account. Do not put a token in the repo, the commit, or the command line.

1. Install the CLI with `npm install -g apify-cli`.
2. Export `APIFY_TOKEN` in the shell, or run `apify login` in a browser session.
3. From `actors/collector1`, run `apify push`.
4. In the Apify console, set the run memory to 512 MB and keep the default input limits.
5. Start one bounded run. Confirm `RUN_SUMMARY.stoppedReason` and the failure manifest before any larger input.
6. To resume, pass the saved `CHECKPOINT` object in the next input with `resume` true.

Do not run `apify actors publish` from this package. Store publishing is out of scope. Do not point the actor at StockNow or at any host that is not on the allowlist.

## Input

See the input tab for the full field list. `stagedFiles` items are JSON objects. `kind` is `eod`, `zip`, `financial_document`, or `document_metadata`. `expectedPeriod` uses `FY2024`, `Q12024`, or `HY2024`. Dates in CSV files are read as day-month-year when they are not already ISO dates. Limits above the hard ceiling are rejected instead of being silently reduced: 200 requests, 50 MB total, 300 seconds, 15 MB per file, and concurrency 4.

## Output

```json
{
    "lane": "accepted",
    "recordType": "eod_bar",
    "symbol": "GP",
    "tradeDate": "2024-01-15",
    "close": 250.5,
    "nav": -1.25,
    "documentClaim": "not_applicable",
    "verifiedAnnualReport": false,
    "provenMissing": false,
    "sample": false
}
```

A second example is an index row for a link that was not downloaded:

```json
{
    "lane": "accepted",
    "recordType": "financial_document",
    "documentClaim": "metadata_only",
    "verifiedAnnualReport": false,
    "title": "Annual Report 2024"
}
```

`CHECKPOINT` is the resume queue. `COVERAGE_MANIFEST` is the current absence picture. `FAILURE_MANIFEST` lists items that were not promoted.

## Tips

- Keep one in-flight request. The domain limiter lowers concurrency and waits after HTTP 429.
- Pass the same staged file again only with `resume` true. The content hash will not create a second canonical bar.
- Treat `absenceStatus` `unknown` as not yet explained. Do not convert it into a proven missing bar.
- Quarantine a conflicting close. The first accepted close stays in the checkpoint.
- Use `sample: true` for the bundled smoke file only.

## FAQ, disclaimers, and support

Collector1 reads public pages and files the operator supplies. It does not extract private StockNow sessions, credentials, or internal APIs. It blocks local, link-local, and private addresses, re-checks redirects, and refuses zip paths, encrypted archives, and high compression ratios.

Our Actors are ethical and do not extract any private user data, such as email addresses, gender, or location. They only extract what the user has chosen to share publicly. We therefore believe that our Actors, when used for ethical purposes by Apify users, are safe. However, you should be aware that your results could contain personal data. Personal data is protected by the GDPR in the European Union and by other regulations around the world. You should not scrape personal data unless you have a legitimate reason to do so. If you're unsure whether your reason is legitimate, consult your lawyers.

This is not investment advice and it is not a claim that every DSE session or annual report has been collected. Use the Issues tab for actor feedback and the API tab to read the dataset. If a run stops with `max_requests`, `max_bytes`, `max_runtime`, or `backoff`, keep the checkpoint and continue with another bounded run.
