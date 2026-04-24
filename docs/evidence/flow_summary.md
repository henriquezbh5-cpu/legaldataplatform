# Flow run summaries

> **Pending real capture.** Append the output of each pipeline run here. Format below.

## legal-ingestion-flow

```
Date:
Host:
Duration:
Rows extracted:
Rows valid:
Rows rejected (quarantine):
Rows loaded:
Throughput peak (rows/s):
```

## sec-edgar-ingestion

```
Date:
Host:
Duration:
Companies queried:
Filings extracted:
Filings valid:
Filings rejected:
Filings loaded:
Form types observed: (10-K, 10-Q, 8-K, ...)
```

## commercial-ingestion-flow

```
Date:
Host:
Duration:
Counterparties upserted:
SCD2 inserts / expirations / unchanged:
Transactions loaded:
```

## How to capture

After running each flow, copy the output line with `Flow summary: {...}` from the Prefect log and paste it into this file along with the date and host. The Prefect UI run detail page is also worth a screenshot into `screenshots/`.
