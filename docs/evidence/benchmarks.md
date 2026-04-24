# Benchmark capture

> **Pending real measurement.** Run `python scripts/capture_benchmarks.py > docs/evidence/benchmarks.md` after executing `make pipeline` and `sec_edgar_ingestion_flow` to populate this file with real numbers.

The capture script will measure:

## Table sizes

- Live row count, total size, index size, bloat % and last VACUUM timestamp for the four main tables: `legal_documents`, `legal_entities`, `counterparties`, `transactions`.

## Query performance

Five representative queries, each run 20 times after a warm-up, reporting p50 / p95 / p99:

| Query | What it exercises |
|---|---|
| `count_transactions_last_30d` | Partition pruning — planner should scan only the current-month partition |
| `top_counterparties_by_revenue` | Covering index `ix_txn_counterparty_recent` with INCLUDE columns |
| `fuzzy_search_entity_name` | Trigram GIN index via `pg_trgm` |
| `mv_monthly_revenue_scan` | Materialized view — pre-aggregated, sub-ms target |
| `sec_edgar_filings_by_type` | Aggregation over real SEC EDGAR data |

Each row includes the EXPLAIN ANALYZE plan execution time and shared-buffer cache hit ratio, for comparison with the wall-clock statistics.
