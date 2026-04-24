# Evidence — runtime captures and benchmark measurements

This folder holds **real artifacts** produced by running the platform on a specific machine. Anyone can reproduce these by running the stack locally and following the capture checklist below.

## What goes here

| File | Purpose |
|---|---|
| `env.md` | Hardware and software environment of the capture (CPU, RAM, Docker version) |
| `benchmarks.md` | Output of `make benchmark` with p50/p95/p99 measured on this host |
| `flow_summary.md` | End-to-end run summary of `make pipeline` + `sec_edgar_ingestion_flow` |
| `screenshots/prefect_flow_completed.png` | Prefect UI showing a successful flow run with timeline |
| `screenshots/grafana_dashboard.png` | Grafana showing metrics emitted during the run |
| `screenshots/minio_bronze_partition.png` | MinIO console showing Parquet partitions under `bronze/` |
| `screenshots/psql_partitions.png` | `\d+ transactions` showing the monthly partitions |
| `screenshots/pg_stat_statements.png` | Top slow queries ordered by `mean_exec_time` |
| `screenshots/sec_edgar_filings.png` | Real SEC EDGAR filings in `legal_documents` table |

## Capture checklist (run when reproducing)

Prerequisites: Docker running, Python venv active, `pip install -e ".[dev]"` done.

### 1. Environment snapshot

```bash
python scripts/capture_env.py > docs/evidence/env.md
```

### 2. Run the pipelines

```bash
alembic upgrade head
python scripts/seed_data.py
make pipeline
export SEC_USER_AGENT="LegalDataPlatform/0.1 (your-email@example.com)"
python -m src.pipelines.orchestration.sec_edgar_flow
```

### 3. Capture real benchmarks

```bash
python scripts/capture_benchmarks.py > docs/evidence/benchmarks.md
```

### 4. Take the screenshots

Open each URL and save the screenshot into `docs/evidence/screenshots/` with the filename listed above:

- http://localhost:4200 → open the latest `legal-ingestion-flow` run
- http://localhost:3000 → Grafana dashboard with `ldp_*` metrics
- http://localhost:9001 → MinIO console, bronze bucket
- `psql -h localhost -U ldp_admin -d legaldata` →
  - `\d+ transactions` (show partitions)
  - `SELECT * FROM pg_stat_statements ORDER BY mean_exec_time DESC LIMIT 10;`
  - `SELECT source_system, document_type, count(*) FROM legal_documents GROUP BY 1,2;`

### 5. Commit

```bash
git add docs/evidence/
git commit -m "Capture real runtime evidence on $(uname -n) $(date +%Y-%m-%d)"
```

## Why this folder exists

Code in a repo is a claim. Screenshots plus benchmark numbers with a timestamp and machine identifier are proof that the claim holds on at least one real machine. For anyone evaluating this project, this folder is the fastest way to verify that the system actually runs.
