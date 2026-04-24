# dbt models — Gold layer

This folder contains the **SQL transformation layer** built on top of the Python-ingested Silver tables. dbt is responsible for:

1. Defining and testing the Gold-layer aggregates consumed by BI and APIs.
2. Auto-generating a lineage graph between sources, staging and gold.
3. Running assertions (uniqueness, not_null, custom expressions) on every refresh.

Python owns ingestion + normalization + SCD2 (where behavior is imperative). dbt owns transformation + aggregation + test assertions (where the work is declarative SQL).

## Layout

```
dbt/
├── dbt_project.yml          Project config
├── profiles.yml             Target connections (dev / ci / prod)
├── packages.yml             External package dependencies (dbt_utils)
├── models/
│   ├── staging/             Thin views over source tables
│   │   ├── sources.yml      Source definitions + freshness tests
│   │   ├── stg_transactions.sql
│   │   ├── stg_counterparties.sql
│   │   └── stg_legal_documents.sql
│   └── gold/                Business-ready aggregates (tables)
│       ├── schema.yml       Model contracts + tests
│       ├── gold_monthly_revenue_by_counterparty.sql
│       ├── gold_counterparty_risk_distribution.sql
│       └── gold_legal_documents_by_jurisdiction.sql
└── tests/                   Custom data tests (beyond schema.yml)
```

## Running dbt

```bash
# 1. Install the dbt extras
pip install -e ".[dbt]"

# 2. Export connection profiles location
export DBT_PROFILES_DIR=$(pwd)/dbt

# 3. Install package deps
cd dbt && dbt deps

# 4. Run models
dbt run                    # build all models in the default target
dbt test                   # run all tests
dbt docs generate          # generate lineage + model docs
dbt docs serve             # browse at http://localhost:8080
```

## Integration with Prefect

The Prefect flow can trigger `dbt run` after Silver loads by shelling out:

```python
from prefect_dbt.cli import DbtCoreOperation

@task
def refresh_gold_with_dbt():
    DbtCoreOperation(
        commands=["dbt run", "dbt test"],
        project_dir="dbt",
        profiles_dir="dbt",
    ).run()
```

This keeps the transformation layer in SQL while letting Prefect orchestrate retries, alerting and observability.

## Why this co-exists with the PostgreSQL materialized view

The `mv_monthly_revenue_per_counterparty` materialized view in the Python migration is used for ultra-low-latency `REFRESH MATERIALIZED VIEW CONCURRENTLY` operations (sub-second). It's kept as the real-time serving layer. dbt's `gold_monthly_revenue_by_counterparty` is the dbt-owned sister table with tests and lineage, suitable for BI and scheduled batch refresh.

Both models exist intentionally: MV for transactional workloads where concurrent refresh matters, dbt table for analytical workloads where documentation + tests + lineage matter more.
