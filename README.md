# LegalDataPlatform

[![CI](https://github.com/henriquezbh5-cpu/legaldataplatform/actions/workflows/ci.yml/badge.svg)](https://github.com/henriquezbh5-cpu/legaldataplatform/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue.svg)](https://www.python.org)
[![PostgreSQL](https://img.shields.io/badge/postgresql-16-336791.svg)](https://www.postgresql.org/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

ETL/ELT platform for legal and commercial data. Python 3.11+, PostgreSQL 16, AWS (S3, Lambda, Glue), Docker.

## Requirements addressed

- **Scalable ETL/ELT pipelines in Python and AWS** for ingestion of legal and commercial sources.
- **PostgreSQL optimization** for relational workloads: partitioning, indexes, materialized views, connection pooling.
- **Data quality and normalization** enforcing a single source of truth: Pydantic validation, declarative rule engine, Great Expectations, SCD2.

## Stack

| Layer | Choice | Why |
|---|---|---|
| Runtime | Python 3.11 async | Standard for data engineering; async/await for extractors |
| Orchestration | Prefect 2 | Python-native flows, retries, observability |
| DataFrames | Polars + Pandas | Polars for large batches (Rust-backed), Pandas for compatibility |
| Validation | Pydantic v2 | Rust-backed core, ~1M models/s |
| DQ | Great Expectations + custom YAML engine | Statistical + business rules split |
| RDBMS | PostgreSQL 16 | Partitioning, JSONB, pg_trgm, pg_stat_statements |
| ORM | SQLAlchemy 2.0 + asyncpg | Async, type-annotated, robust pool |
| Migrations | Alembic | Version-controlled schema |
| Pool | PgBouncer | Transaction pooling, 20:1 client:backend ratio |
| Lake | AWS S3 (MinIO locally) | Medallion Bronze / Silver / Gold / Quarantine |
| Serverless | AWS Lambda | S3 events → SQS → pipeline trigger |
| Big data | AWS Glue PySpark | For batches > 100M rows |
| Messaging | AWS SQS + DLQ | Decoupling + poison-message isolation |
| IaC | Terraform | All AWS resources codified |
| Observability | structlog + Prometheus + Grafana | RED + data-specific metrics |

## Project layout

```
src/
├── config.py
├── schemas/            Pydantic contracts
├── database/           SQLAlchemy models, Alembic migrations, optimization scripts
├── pipelines/
│   ├── extractors/     REST (generic + SEC EDGAR), CSV, PostgreSQL, S3
│   ├── transformers/   Normalizers, SCD2, enrichers
│   ├── loaders/        Postgres bulk COPY, S3 Parquet
│   └── orchestration/  Prefect flows
├── data_quality/       YAML rules + Great Expectations integration
├── aws/                S3 client, Lambda handlers, Glue jobs
└── observability/      Logs, metrics
.github/workflows/      CI (lint + tests + security + Docker build)
infra/
├── terraform/          S3, SQS, Lambda, Glue, Aurora Serverless
├── docker/             Prometheus config
└── sql/init/           DB extensions + roles
tests/unit + integration
docs/
├── ARCHITECTURE.md
├── PIPELINES.md
├── POSTGRESQL_OPTIMIZATION.md
├── DATA_QUALITY.md
├── AWS_DEPLOYMENT.md
├── WALKTHROUGH.md      Full technical write-up with ADRs
├── TALKING_POINTS.md   Decision rationale for interviews
└── evidence/           Real runtime screenshots and benchmarks
```

## Quickstart

Prerequisites: Python 3.11+, Docker Desktop, Git.

```bash
# 1. Env config
cp .env.example .env

# 2. Python venv + deps
python -m venv .venv
source .venv/bin/activate           # or .venv\Scripts\activate on Windows
pip install -e ".[dev]"

# 3. Docker stack (Postgres + PgBouncer + MinIO + Prefect + Prometheus + Grafana)
docker compose up -d

# 4. Schema + seed
alembic upgrade head
python scripts/seed_data.py

# 5. Run pipelines
make pipeline            # legal documents (CSV source)
make sec-edgar           # real SEC EDGAR filings
make gleif               # real GLEIF Legal Entity Identifiers
make commercial          # contracts + transactions from CSV

# 6. Tests + benchmarks
make test                # unit + integration (needs Postgres up)
make test-unit           # unit only, no DB required
make benchmark           # query p50/p95/p99
make evidence            # capture env + benchmarks into docs/evidence/
```

UIs exposed on `localhost`: Prefect 4200 · MinIO 9001 · Prometheus 9090 · Grafana 3000.

## Real source integrations

Two production APIs are integrated with real rate limiting and identification:

### SEC EDGAR ([`src/pipelines/extractors/sec_edgar.py`](src/pipelines/extractors/sec_edgar.py))

Live corporate filings from `data.sec.gov`: 10-K, 10-Q, 8-K, DEF 14A, S-1, etc. Normalized into `legal_documents`. Rate-limited to 8 req/s (under SEC's 10 req/s cap), identified via User-Agent per their fair-use policy.

### GLEIF ([`src/pipelines/extractors/gleif.py`](src/pipelines/extractors/gleif.py))

Legal Entity Identifiers from `api.gleif.org` — the globally mandated ID for any legal entity in financial transactions (MiFID II, Dodd-Frank, EMIR). Normalized into `counterparties` with SCD2 history tracked in `dim_counterparty`. JSON:API pagination handled end-to-end.

## CI/CD

GitHub Actions runs on every push and pull request:

- **lint** — ruff check, ruff format, mypy
- **unit-tests** — pytest on Python 3.11 and 3.12 in parallel
- **integration-tests** — pytest against real PostgreSQL 16 service container
- **security** — pip-audit (CVE scan), bandit (static security analysis)
- **docker-build** — builds the multi-stage production image

## Documentation

- [docs/WALKTHROUGH.md](docs/WALKTHROUGH.md) — full technical write-up, ADRs, trade-offs
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — components and patterns
- [docs/PIPELINES.md](docs/PIPELINES.md) — extractors, transformers, loaders
- [docs/POSTGRESQL_OPTIMIZATION.md](docs/POSTGRESQL_OPTIMIZATION.md) — partitioning, indexes, MViews, tuning
- [docs/DATA_QUALITY.md](docs/DATA_QUALITY.md) — the three lines of defense
- [docs/AWS_DEPLOYMENT.md](docs/AWS_DEPLOYMENT.md) — Terraform, costs, DR runbooks
- [docs/TALKING_POINTS.md](docs/TALKING_POINTS.md) — architectural decisions Q&A
- [docs/evidence/](docs/evidence/) — real runtime captures and benchmark numbers

## Author

Humberto Henriquez — Senior Data Engineer / Solutions Architect
