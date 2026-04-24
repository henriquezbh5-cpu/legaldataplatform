# Load tests

Stress tests for the PostgreSQL query layer. Useful to:

- Establish a baseline throughput for the hottest queries.
- Detect regressions when indexes, partitioning or pg config change.
- Size Aurora Serverless v2 capacity units (ACUs) before going to production.

We use **[Locust](https://docs.locust.io/)** because:

- Python-native — the same language as the rest of the codebase.
- Tasks are plain functions, trivial to write and review.
- Produces p50/p95/p99, RPS and failure rate in a web UI or headless.

## Installation

```bash
pip install locust
```

(`locust` is intentionally **not** in `[dev]` — it is only needed when you're
running load tests, which is an infrequent, explicit activity.)

## Running

### With the web UI

```bash
# From the project root, with Docker Compose up and the pipelines already run
locust -f load_tests/locustfile.py --host postgresql://ldp_admin:ldp_dev_password@localhost:5432/legaldata
```

Open http://localhost:8089 and set your target concurrency + duration.

### Headless (CI-friendly)

```bash
locust -f load_tests/locustfile.py \
       --host postgresql://ldp_admin:ldp_dev_password@localhost:5432/legaldata \
       --users 50 --spawn-rate 5 --run-time 2m --headless \
       --csv=load_tests/results/baseline
```

Output files:

- `baseline_stats.csv` — request counts and percentiles
- `baseline_failures.csv` — any failed requests with reason
- `baseline_exceptions.csv` — Python stack traces

## What the scenarios cover

| Scenario | Query | Exercises |
|---|---|---|
| `count_recent_transactions` | count over 30d window | Partition pruning |
| `top_counterparties` | top-K by revenue (90d) | Covering index |
| `fuzzy_entity_search` | ILIKE on legal_name | pg_trgm + GIN |
| `monthly_revenue_scan` | scan mv_monthly_revenue | Materialized view |
| `point_in_time_counterparty` | SCD2 time-travel query | `dim_counterparty` index |

## Interpreting the results

A healthy baseline on commodity hardware (8 vCPU, 16GB, PostgreSQL tuned):

| Query | p50 target | p95 target | Failure rate |
|---|---|---|---|
| `count_recent_transactions` | < 20 ms | < 50 ms | 0% |
| `top_counterparties` | < 80 ms | < 200 ms | 0% |
| `fuzzy_entity_search` | < 15 ms | < 40 ms | 0% |
| `monthly_revenue_scan` | < 5 ms | < 15 ms | 0% |
| `point_in_time_counterparty` | < 3 ms | < 10 ms | 0% |

If p95 on `top_counterparties` creeps over 500 ms at 50 concurrent users, the covering index is not being used or the partition prune broke. Start the investigation with `EXPLAIN (ANALYZE, BUFFERS)` on the same query.
