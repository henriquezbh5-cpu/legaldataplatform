# Talking points — decision rationale

This document supports technical interviews on this project. Each section is a decision with:

- **Choice** — what I picked
- **Alternatives evaluated** — what I discarded
- **Trade-off accepted** — what I'm paying for that choice
- **When I would revisit** — conditions that would flip the decision

The format reads out loud in 30–60 seconds per decision; long enough to show reasoning, short enough not to stall a conversation.

---

## 1. Medallion architecture (Bronze / Silver / Gold / Quarantine)

**Choice.** I separated raw ingested data (Bronze, immutable on S3), cleaned/validated data (Silver, on S3 and PostgreSQL) and business-aggregated data (Gold, on PostgreSQL materialized views). Rejected records go to a Quarantine bucket with their Pydantic errors attached.

**Alternatives evaluated.**
- Single schema in PostgreSQL, no raw layer. Rejected because re-running a normalization fix would require re-hitting external APIs, some of which are rate-limited or paid.
- Delta Lake / Iceberg on S3. Rejected for scope — the team would have to learn Spark or use Trino just to read Silver. PostgreSQL + Parquet on S3 is simpler and sufficient for the data volumes.

**Trade-off accepted.** Bronze storage cost (S3 is ~$0.023/GB/month, lifecycle moves data to Glacier at 90d).

**When I would revisit.** If we ever ingest > 10TB of raw daily, Iceberg becomes attractive because of ACID + time travel at that scale. For < 1TB daily, Medallion on S3 is the cheaper, simpler path.

---

## 2. Prefect 2 over Airflow

**Choice.** Prefect 2 for orchestration.

**Alternatives evaluated.**
- Airflow. Battle-tested, larger provider ecosystem. But the DX friction is real: DAG files, context parameter limitations, the historical scheduler-executor separation.
- Dagster. Strong asset-centric model, good for data-product thinking. Smaller community, steeper onboarding.
- Mage. Modern but less mature for production observability.

**Trade-off accepted.** Prefect's ecosystem of provider packages is thinner than Airflow's. When I need an obscure connector, I write it.

**When I would revisit.** If we grow beyond ~200 DAGs with heterogeneous teams owning subsets of them, Airflow's RBAC and provider ecosystem become more valuable than Prefect's DX gains.

---

## 3. Polars alongside Pandas (not instead of)

**Choice.** Polars for large-batch processing (>100K rows), Pandas for compatibility with third-party libraries (GE, some plotting).

**Alternatives evaluated.**
- Pandas-only. Works but is 10–30× slower on the batch sizes I care about, and eats memory with uncontrolled copies.
- Polars-only. Most of my code uses it, but libraries like Great Expectations still expect Pandas.
- DuckDB. Excellent for ad-hoc SQL on Parquet, but the team's code is Python-first.

**Trade-off accepted.** Two DataFrame APIs to know. Worth it: Polars' lazy scanning + expression pushdown is a real performance multiplier.

**When I would revisit.** When Polars integration with GE stabilizes (they're working on it), I'd drop Pandas entirely.

---

## 4. PostgreSQL as the operational source of truth

**Choice.** PostgreSQL 16 is the single authoritative store for current state. S3 holds history and reprocessable inputs.

**Alternatives evaluated.**
- Redshift / BigQuery / Snowflake as SoT. Good for analytics but ACID transactions on individual records, foreign keys and CHECK constraints are second-class. For contracts and transactions that need integrity, PostgreSQL wins.
- MySQL. Rejected for lack of partial indexes, weaker JSON support, and weaker query planner on JOINs.
- Managed NoSQL (DynamoDB, Cosmos). Rejected because our joins are deeply relational.

**Trade-off accepted.** Operational cost of tuning Postgres (VACUUM, bloat, partition maintenance) vs. the zero-maintenance promise of managed warehouses.

**When I would revisit.** If Gold-layer analytics outgrows what a single Aurora writer can serve, I'd export Silver/Gold to Redshift Spectrum for BI while keeping PostgreSQL as the OLTP SoT.

---

## 5. RANGE partitioning by month on transactions and legal_documents

**Choice.** Native PostgreSQL RANGE partitioning per month on the two highest-volume tables.

**Alternatives evaluated.**
- No partitioning. Fails above ~100M rows: VACUUM locks the table for minutes, DELETEs for retention flood the WAL, and the planner can't prune.
- HASH partitioning by ID. Cheap to maintain, but time-range queries have to scan all partitions — defeats the main benefit.
- Citus / logical sharding. Overkill until multi-node genuinely needed.

**Trade-off accepted.** Primary keys become composite `(id, date)` — every FK from transactions to contracts has to include the date if we want partition-local joins. That friction is real but manageable.

**When I would revisit.** If queries are overwhelmingly by a non-temporal key, HASH might make sense. So far, every analytical query has a date range filter.

---

## 6. Three lines of DQ defense, not one

**Choice.** Pydantic for structure, YAML rule engine for business rules, Great Expectations for statistical / post-load checks.

**Alternatives evaluated.**
- Great Expectations only. Too heavy for per-record ingestion; not ergonomic for "string length 1–500" type checks.
- Pydantic only. Doesn't cover cross-row constraints (uniqueness at batch level) or statistical drift.
- Soda / dbt tests. Great for SQL-world checks, less good for in-pipeline Python.

**Trade-off accepted.** Three systems to understand. The boundary is clear though: Pydantic runs per record at ingest; YAML rules run per batch post-normalize; GE runs scheduled post-load.

**When I would revisit.** If the YAML rule engine grew to > 50 rule types, I'd fold it into GE's custom expectations framework instead.

---

## 7. COPY bulk + temp-staging UPSERT, not row-by-row INSERTs

**Choice.** For writes, stream records via COPY into a TEMP staging table, then `INSERT ... ON CONFLICT DO UPDATE` from staging into target.

**Alternatives evaluated.**
- Row-by-row INSERTs via ORM. ~1K rows/s on commodity hardware — 100× slower.
- INSERT ... VALUES with multi-row batches. Better than row-by-row, but still an order of magnitude below COPY.
- Bulk UPDATE via temp table only (no ON CONFLICT). Fine when there are no unique conflicts, but I need idempotency on re-runs.

**Trade-off accepted.** COPY requires knowing the exact column order and serialization format. The code is slightly more fragile than an ORM call, but pays for itself in throughput.

**When I would revisit.** If loads shrink to < 1000 rows per run, ORM-level UPSERT becomes simpler and the performance difference is irrelevant.

---

## 8. PgBouncer in transaction mode (not session mode)

**Choice.** PgBouncer in transaction mode with `statement_cache_size=0` on asyncpg.

**Alternatives evaluated.**
- No pooler. Each app connection opens a dedicated backend — ~10MB RAM each. With 500 concurrent clients, that's 5GB just in idle connections.
- pgcat (newer, Rust). Promising, but less battle-tested for our scale.
- Session pooling. Keeps session-local state (LISTEN/NOTIFY, prepared statements), but caps concurrency at the pool size.

**Trade-off accepted.** Transaction mode forbids session-level state. Prepared statements, LISTEN/NOTIFY and `SET LOCAL` spanning transactions don't work. I handle prepared statements at the driver level (caching off) and use a direct engine for anything needing session state.

**When I would revisit.** If I ever need heavy use of `LISTEN/NOTIFY` for real-time notifications — then session mode for that subsystem while keeping transaction mode for the bulk workload.

---

## 9. SCD Type 2 on counterparty, Type 1 on jurisdiction

**Choice.** Counterparties use SCD2 (full history with `valid_from`/`valid_to`/`is_current`). Jurisdictions use SCD1 (overwrite on change).

**Alternatives evaluated.**
- Event-sourcing for both. True history via a log of changes, reconstructed on demand. Overkill for a small number of dimensions.
- SCD2 everywhere. Expensive: every slowly-changing reference table carries 10×+ overhead for history that's rarely queried.
- SCD1 everywhere. Works until the first auditor asks "what did we believe about this entity on date X?"

**Trade-off accepted.** Cognitive complexity: developers have to remember which tables have SCD2 and query with `WHERE valid_from <= date AND date < valid_to`. I mitigated this with a `dim_counterparty` model distinct from the operational `counterparties` table — the name signals the difference.

**When I would revisit.** If compliance requirements tighten to "full audit trail on everything", I'd build a generic change-capture layer (e.g., Debezium) rather than hand-coded SCD2 per table.

---

## 10. Terraform over CDK or CloudFormation

**Choice.** Terraform for all AWS infrastructure.

**Alternatives evaluated.**
- AWS CDK. Great DX if you're AWS-only and Python/TypeScript native. Locked into CloudFormation under the hood.
- Raw CloudFormation. Verbose, AWS-only, slow to iterate.
- Pulumi. Like CDK but multi-cloud. Smaller community than Terraform.

**Trade-off accepted.** Terraform's state management requires discipline (S3 + DynamoDB backend, never commit `terraform.tfstate`). Worth it for the provider ecosystem.

**When I would revisit.** If we committed to AWS-only and had a strong Python or TypeScript team, CDK's programmatic model is more natural for complex conditional infra.

---

## 11. Why Lambda doesn't run the pipeline itself

**Choice.** Lambda handles S3 events and puts a message on SQS. The pipeline runs in a Prefect worker (ECS Fargate in prod, local process in dev).

**Alternatives evaluated.**
- Run the pipeline inside Lambda. Hits the 15-minute timeout for larger batches, 10 GB memory limit, and the deployment package size limit (~250 MB unzipped) which Pandas + Polars easily blows past.
- Fargate direct, no Lambda. Works, but then S3 events need a different entry point; Lambda is the natural glue.

**Trade-off accepted.** Two-hop architecture (S3 → Lambda → SQS → worker) is a small operational complexity cost for a lot of flexibility.

**When I would revisit.** If pipelines become small and stateless (< 15 min, < 10 GB), Lambda-native execution removes the Fargate footprint.

---

## 12. Rate-limited SEC EDGAR extractor, not scraping the HTML site

**Choice.** Use SEC's official JSON API at `data.sec.gov`, respecting their 10 req/s limit via an asyncio semaphore + sleep.

**Alternatives evaluated.**
- Scraping the HTML filings pages. Fragile (markup changes), slower, and disrespectful to a free public service.
- Using a paid aggregator (Intrinio, Polygon). Higher quality for financial fundamentals but adds cost and lock-in for data the SEC gives away.
- Bulk download of the daily index files. Appropriate for historical backfills; overkill for "recent filings" use cases.

**Trade-off accepted.** SEC's API has more restrictions than a paid service: I have to identify via User-Agent with an email, cannot parallelize beyond ~10 rps, and depend on their uptime.

**When I would revisit.** For bulk historical backfill (e.g., 20 years of filings), I'd use the daily index files instead of the submissions endpoint.

---

## Common follow-up questions & answers

### "How did you test this in production?"

**Honest answer.** This project is not currently in production. The architecture and code are designed per production patterns I've used in prior work, but for this repository the validation is: unit tests with moto-mocked AWS, integration tests against a real Dockerized PostgreSQL, benchmark runs captured in `docs/evidence/benchmarks.md`, and real data ingestion from SEC EDGAR.

### "What would you change first if you ran it in production?"

1. Add Grafana dashboards tied to Prometheus alerts (PagerDuty / OpsGenie routing).
2. Turn on PITR backups on Aurora, validate restore procedure monthly.
3. Add CI gate that fails on mypy strict errors and pytest coverage < 85%.
4. Introduce Debezium + Kafka for change-data-capture from upstream systems, replacing the pull-based watermark extractor for low-latency sources.

### "What's the biggest risk in this design?"

Partition management. If the cron that creates next month's partitions fails silently, inserts will land in the `default` partition and eventually degrade. I would mitigate by (a) using `pg_partman` for automated management, and (b) a monitoring query that alerts if the default partition grows past N rows.

### "What would you push back on if the team asked for it?"

Requests to put compute at the database layer (stored procedures, triggers doing business logic). PostgreSQL is an excellent store and planner; it's a poor application runtime. I keep logic in Python where it's testable and observable, and reserve the database for what it's best at.
