# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- LICENSE (MIT), CONTRIBUTING.md, CHANGELOG.md, CODE_OF_CONDUCT.md, CODEOWNERS, SECURITY.md and GitHub issue/PR templates for open-source project governance.
- Pre-configured Grafana datasource and dashboard for pipeline metrics (auto-provisioned on `docker compose up`).
- Jupyter notebook `notebooks/pipeline_analysis.ipynb` demonstrating SCD2 point-in-time queries, cross-source aggregation and partition-aware analytics.
- Status badges in README (CI, Python version, ruff, license).
- **mkdocs documentation site** with Material theme, Mermaid diagrams, auto-published to GitHub Pages on `docs/**` changes.
- **dbt Gold-layer models** (`dbt/`) owning the SQL transformation contract separately from Python: 3 staging views and 3 gold tables with schema tests (unique keys, accepted values, not-null, expression_is_true) using `dbt_utils`, plus a dedicated `dbt-validate` job in CI that parses + compiles against the real PostgreSQL.
- **pytest-benchmark** suite covering the four hot paths (Pydantic, row_hash, DQ rule engine, CSV encoding). Informational in CI; flags regressions > 10× in PR logs.
- **Load tests with Locust** (`load_tests/`): 5 representative query scenarios with documented p50/p95 budgets per workload.

### Changed
- `mypy` configuration refined: removed blanket `strict=true`. Now enforces `check_untyped_defs`, `disallow_incomplete_defs`, `warn_redundant_casts`. Strict checking (`disallow_untyped_defs`) applied per-module to `src.schemas.*` and `src.observability.*` where full typing is already achieved.
- CI: `docker-build` now depends on `lint` + `unit-tests` (gated). `codecov-action` v4 → v5. `docker/build-push-action` v5 → v6.
- CI: Unit test runners disable benchmarks during correctness tests and run them separately as an informational step.

## [0.1.0] - 2026-04-24

Initial project release.

### Added

**Pipelines (ETL/ELT in Python + AWS)**
- Async extractors for REST APIs, CSV, PostgreSQL (watermark-based incremental), S3 Parquet.
- **SEC EDGAR extractor** — real corporate filings from `data.sec.gov`, rate-limited to 8 req/s, User-Agent identification per SEC policy, form-to-document-type taxonomy, SHA-256 deterministic hashing.
- **GLEIF extractor** — real Legal Entity Identifiers from `api.gleif.org`, JSON:API pagination, country and status filters.
- Transformers: Pydantic normalizers, SCD Type 2 handler with point-in-time query support, risk-tier enricher.
- Loaders: PostgreSQL bulk COPY with UPSERT-via-staging pattern, S3 Parquet writer with date partitioning.
- Prefect 2 orchestration: four flows (legal CSV, SEC EDGAR, GLEIF, commercial) with retries, schedules and observability.
- AWS Lambda handlers for S3 → SQS → Prefect event-driven triggering.
- AWS Glue PySpark job for batches exceeding single-process limits.

**PostgreSQL optimization**
- Native RANGE partitioning by month on `transactions` and `legal_documents`.
- Multi-pattern indexing: BTree composite, BRIN for time series, GIN + pg_trgm for fuzzy search, partial indexes on status, covering indexes with INCLUDE columns, GIN with jsonb_path_ops.
- Materialized views with `REFRESH MATERIALIZED VIEW CONCURRENTLY` refresh procedure.
- PgBouncer transaction pooling with asyncpg compatibility (statement_cache disabled).
- Query helpers: EXPLAIN ANALYZE wrapper, pg_stat_statements aggregation, bloat estimation.
- Alembic migrations: initial schema, partitioning + materialized views, pipeline_watermarks with auto-touch trigger.

**Data quality (three lines of defense)**
- Pydantic v2 schemas for all domain entities with strict validation and normalization.
- Custom YAML rule engine: `not_null`, `unique`, `regex`, `in_set`, `range`, `row_count_range`, with error/warning severity levels.
- Great Expectations integration for statistical expectations and data docs.
- Quarantine pattern: rejected records land in S3 with their validation errors attached.

**Infrastructure**
- Terraform modules for S3 (Bronze/Silver/Gold/Quarantine with KMS + lifecycle), SQS + DLQ, Lambda handlers, Glue catalog and PySpark jobs, Aurora PostgreSQL Serverless v2.
- Multi-stage Dockerfile (~280 MB runtime) with non-root user and tini init.
- Docker Compose stack: Postgres 16, PgBouncer, MinIO, Prefect, Prometheus, Grafana.

**CI/CD**
- GitHub Actions pipeline with six jobs: ruff lint, ruff format check, mypy, unit tests (Python 3.11 and 3.12), integration tests against real PostgreSQL 16 service container, pip-audit + bandit security scan, Docker build verification.
- Pre-commit hooks: ruff, mypy, bandit, gitleaks, YAML/JSON validation.

**Documentation**
- Full technical walkthrough with 6 ADRs (`docs/WALKTHROUGH.md`).
- Specialized docs for architecture, pipelines, PostgreSQL optimization, data quality and AWS deployment.
- Decision rationale document for interviews (`docs/TALKING_POINTS.md`).
- Evidence-capture scaffolding (`docs/evidence/` + `scripts/capture_*.py`).

[Unreleased]: https://github.com/henriquezbh5-cpu/legaldataplatform/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/henriquezbh5-cpu/legaldataplatform/releases/tag/v0.1.0
