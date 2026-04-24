# Resumen para entrevista / portfolio

## Qué es LegalDataPlatform

Una plataforma de datos full-stack que demuestra capacidades de Senior Data Engineer / Arquitecto de Soluciones: ingesta ETL/ELT escalable en Python y AWS, optimización de PostgreSQL a nivel de producción y un framework de calidad de datos tratado como código.

## Los tres requisitos del rol, mapeados

### 1. Pipelines ETL/ELT escalables en Python y AWS

| Requisito | Entregable |
|---|---|
| Python moderno | 3.11, async/await, type hints, Pydantic v2, Polars |
| Orquestación | Prefect 2 flows con retries, schedules, deployments |
| AWS | S3 (data lake Medallion), Lambda (S3→SQS→Prefect), Glue (PySpark), SQS+DLQ, KMS, Secrets Manager |
| Escalabilidad | Streaming extractors, chunk processing, partitioning, COPY bulk (150K+ rows/s) |
| Observabilidad | structlog JSON + Prometheus metrics + CloudWatch |
| IaC | Terraform para todos los recursos AWS |

### 2. Optimización PostgreSQL

| Requisito | Entregable |
|---|---|
| Schema design | Modelos relacionales normalizados con constraints (FK, CHECK, UNIQUE) |
| Particionado | RANGE mensual en transactions y legal_documents |
| Indexación | BTree compuesto, BRIN, partial, covering, GIN/pg_trgm, GIN/JSONB |
| Materialized views | Pre-agregados con CONCURRENTLY refresh |
| Query tuning | pg_stat_statements, EXPLAIN ANALYZE helpers, benchmark suite |
| Connection pooling | PgBouncer transaction mode con asyncpg compatible |
| Configuración | Tuning de shared_buffers, work_mem, autovacuum |
| Mantenimiento | VACUUM ANALYZE programado, bloat detection |

### 3. Calidad y normalización — Fuente de verdad

| Requisito | Entregable |
|---|---|
| Validación estructural | Pydantic v2 schemas por entidad |
| Reglas de negocio | Rule engine YAML (not_null, unique, regex, range, in_set, row_count) |
| Expectations estadísticas | Great Expectations integration |
| Histórico | SCD Type 2 sobre dimensiones críticas (counterparty) |
| Idempotencia | Hashes determinísticos, unique constraints, UPSERT via staging |
| Quarantine | Registros rechazados con motivo → S3, triage semanal |
| Lineage | batch_id viaja con el dato, metadata en cada tabla |
| Observabilidad | Métricas de calidad (pass/fail rate) en Prometheus |

## Talking points

### "¿Por qué Medallion y no un solo schema operativo?"

Porque separa la historia del estado. Postgres es la fuente operativa, pero si el negocio cambia reglas de normalización o si descubrimos un bug, podemos re-derivar Silver/Gold desde Bronze sin volver a golpear las APIs. Bronze es el "event log" inmutable; todo lo demás es una proyección.

### "¿Por qué no usar dbt?"

dbt es excelente para Gold (transformaciones SQL). Aquí el foco es el **corazón del ETL** (extracción + normalización), que dbt no cubre. En el roadmap encaja perfectamente: Silver ya normalizado en PG, dbt corre los modelos Gold con tests.

### "¿Cuándo pasar de Python a Spark?"

El cutoff práctico en un proceso Python + Polars es ~50M-100M rows por batch en hardware commodity. Arriba de eso, o con joins masivos, migrar a Glue PySpark. El job `legal_doc_normalize.py` es la plantilla.

### "¿Por qué SCD2 sobre counterparties?"

Compliance. Si regulador pregunta "¿cuál era el risk_score de ACME Corp. el 2024-06-01?", SCD2 responde en un query. Sin SCD2 tendríamos que reconstruir de logs de cambios.

### "¿Cómo manejas schema evolution?"

- Cambios compatibles (columna nueva con default) → Alembic migration, sin breaking.
- Cambios incompatibles (rename, drop, type change) → migración en dos fases: (1) agregar columna nueva, backfill, pipelines escriben ambas; (2) migrar lectores, remover vieja.
- Validación: Pydantic schemas versionados, rechazos a quarantine.

### "¿Cómo pruebas el pipeline completo?"

Tests unitarios para schemas/validators/rule engine. Integration tests con moto (S3) y Testcontainers-Postgres (DB real en Docker). End-to-end: seed_data + docker-compose + make pipeline + asserts sobre el estado de la DB.

### "¿Cómo detectas data drift?"

Great Expectations con expectations estadísticas (distributions, means, quantiles). Checkpoint diario que compara contra baseline. Alerta Prometheus si la tasa de rechazo cambia significativamente.

### "¿Y si la fuente cambia sin avisar?"

Pydantic falla la validación → registro a quarantine → alerta por threshold de rejection rate. El pipeline no corrompe Silver; el ingeniero triajea y actualiza el schema o el extractor.

## Números memorables

- **COPY bulk**: 150K+ rows/s vs ~1K rows/s en INSERTs.
- **Partición mensual** reduce p95 de queries de 800ms a <50ms.
- **BRIN** usa 0.03% del espacio de un BTree para columnas time-series.
- **Materialized views** con CONCURRENTLY refresh → lecturas no bloqueadas.
- **PgBouncer transaction mode** → ratio 20:1 de conexiones cliente/backend.
- **Pydantic v2** valida ~1M models/s.
- **Polars** es 10-30× más rápido que Pandas en cargas grandes.

## Estructura del repo (referencia visual)

```
LegalDataPlatform/
├── README.md
├── docker-compose.yml
├── pyproject.toml
├── Makefile
├── alembic.ini
├── src/
│   ├── config.py
│   ├── observability/
│   ├── schemas/
│   ├── database/
│   │   ├── models/
│   │   ├── migrations/
│   │   ├── optimization/
│   │   └── session.py
│   ├── pipelines/
│   │   ├── extractors/      (REST, CSV, DB, S3)
│   │   ├── transformers/    (normalizers, SCD2, enrichers)
│   │   ├── loaders/         (Postgres bulk, S3 Parquet)
│   │   └── orchestration/   (Prefect flows + deployments)
│   ├── data_quality/
│   │   ├── validators/      (rule engine)
│   │   ├── rules/           (YAML suites)
│   │   └── ge_integration.py
│   └── aws/
│       ├── s3/
│       ├── lambda_handlers/ (S3→SQS, SQS→Prefect)
│       └── glue_jobs/       (PySpark)
├── infra/
│   ├── terraform/           (S3, SQS, Lambda, Glue, RDS)
│   ├── docker/              (Prometheus config)
│   └── sql/init/            (extensions, roles)
├── tests/
│   ├── unit/
│   ├── integration/
│   └── conftest.py
├── scripts/
│   ├── seed_data.py
│   └── benchmarks/
└── docs/
    ├── WALKTHROUGH.md        ← paso a paso completo
    ├── ARCHITECTURE.md
    ├── PIPELINES.md
    ├── POSTGRESQL_OPTIMIZATION.md
    ├── DATA_QUALITY.md
    ├── AWS_DEPLOYMENT.md
    └── INTERVIEW_SUMMARY.md  ← este archivo
```

## Cómo demostrarlo en vivo

```bash
# 1. Un comando, sube todo
docker compose up -d

# 2. Prepara datos
pip install -e ".[dev]" && alembic upgrade head && python scripts/seed_data.py

# 3. Corre el pipeline
make pipeline

# 4. Muestra la UI de Prefect
open http://localhost:4200

# 5. Corre benchmarks
make benchmark

# 6. Abre docs
open docs/WALKTHROUGH.md
```

Todo el stack corre local (MinIO emula S3) → la demo no depende de credenciales AWS.
