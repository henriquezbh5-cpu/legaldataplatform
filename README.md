# LegalDataPlatform

**Plataforma de datos escalable para ingesta, normalización y análisis de información legal y comercial.**

Construido con Python 3.11+, AWS, PostgreSQL 16, Docker y patrones modernos de Data Engineering (ETL/ELT, Medallion Architecture, Data Quality-as-Code).

---

## Tabla de contenidos

- [Visión general](#visión-general)
- [Arquitectura](#arquitectura)
- [Stack tecnológico](#stack-tecnológico)
- [Estructura del proyecto](#estructura-del-proyecto)
- [Quickstart](#quickstart)
- [Documentación detallada](#documentación-detallada)
- [Roadmap](#roadmap)

---

## Visión general

LegalDataPlatform resuelve tres desafíos centrales del rol de Senior Data Engineer / Arquitecto de Soluciones:

| Desafío | Implementación |
|---|---|
| **Pipelines ETL/ELT escalables en Python y AWS** | Orquestación con Prefect, extractores modulares (API, CSV, Parquet, DB-to-DB), transformadores con Pandas + Polars, loaders con `COPY` bulk. Integración con S3 (data lake), Lambda (eventos), Glue Catalog (metadata). |
| **Optimización PostgreSQL** | Esquemas particionados por rango, índices compuestos y parciales, vistas materializadas, query tuning con `EXPLAIN ANALYZE`, `pg_stat_statements`, connection pooling con PgBouncer. |
| **Calidad y normalización ("Fuente de verdad")** | Validación con Pydantic + Great Expectations, reglas declarativas en YAML, Slowly Changing Dimensions Type 2, expectation suites versionadas, data quality dashboards. |

## Arquitectura

```
                        ┌──────────────────────────────────────┐
                        │         DATA SOURCES                 │
                        │  APIs legales · CSVs · DB externas   │
                        │  Web scraping · Event streams        │
                        └────────────────┬─────────────────────┘
                                         │
                                         ▼
                        ┌──────────────────────────────────────┐
                        │       EXTRACTORS (Python)            │
                        │  REST · JDBC · File · Event          │
                        │  Retry · Circuit breaker · Idempotent│
                        └────────────────┬─────────────────────┘
                                         │
                                         ▼
                        ┌──────────────────────────────────────┐
                        │    RAW LAYER (S3 Bronze)             │
                        │  Parquet + Snappy · Partition: date  │
                        └────────────────┬─────────────────────┘
                                         │
                                         ▼
                        ┌──────────────────────────────────────┐
                        │   TRANSFORMATION (Pandas/Polars)     │
                        │  Normalize · Dedupe · SCD2 · Enrich  │
                        │  Data Quality Gates (GE)             │
                        └────────────────┬─────────────────────┘
                                         │
                                         ▼
                        ┌──────────────────────────────────────┐
                        │   CURATED LAYER (S3 Silver/Gold)     │
                        │  Clean · Joined · Business-ready     │
                        └────────────────┬─────────────────────┘
                                         │
                                         ▼
                        ┌──────────────────────────────────────┐
                        │   POSTGRESQL (Source of Truth)       │
                        │  Partitioned · Indexed · MViews      │
                        │  OLTP + Analytical models            │
                        └────────────────┬─────────────────────┘
                                         │
                                         ▼
                        ┌──────────────────────────────────────┐
                        │   CONSUMERS                          │
                        │  BI · APIs · ML · Reporting          │
                        └──────────────────────────────────────┘
```

## Stack tecnológico

| Capa | Herramienta | Por qué |
|---|---|---|
| Lenguaje | **Python 3.11** | Estándar de la industria para data engineering; rich ecosystem. |
| Orquestación | **Prefect 2** | DAGs dinámicos en Python puro; retries, observability, mejor DX que Airflow para equipos pequeños. |
| Procesamiento | **Pandas + Polars** | Pandas para compatibilidad y Polars (Rust-backed) para datasets 10-100x más rápidos. |
| Validación | **Pydantic v2** | Type-safe models, 5-50x más rápido que v1, runtime validation. |
| Data Quality | **Great Expectations** | Expectation suites versionables, documentation auto-generada, gates en pipelines. |
| DB Relacional | **PostgreSQL 16** | Particionado nativo, JSONB, full-text search, MVCC maduro. |
| ORM / Query | **SQLAlchemy 2.0 + asyncpg** | Async-first, type-annotated, connection pool robusto. |
| Migraciones | **Alembic** | Version control para schema. |
| Pool | **PgBouncer** | Reduce sobrecarga de conexiones en cargas concurrentes. |
| Data Lake | **AWS S3** | Durabilidad 11-nines, barato, integra con todo. |
| Compute serverless | **AWS Lambda** | Event-driven, escala a cero, pay-per-invocation. |
| Catálogo | **AWS Glue Data Catalog** | Metadata central, schema discovery, integra con Athena/Redshift. |
| Mensajería | **AWS SQS / EventBridge** | Desacoplamiento, retry nativo, DLQ. |
| IaC | **Terraform** | Multi-cloud, state management, modulable. |
| Container | **Docker + Docker Compose** | Parity dev/prod, one-command setup. |
| Logs | **structlog** | Logs estructurados JSON, correlación por trace-id. |
| Métricas | **Prometheus + Grafana** | Observability estándar. |

## Estructura del proyecto

```
LegalDataPlatform/
├── src/
│   ├── pipelines/
│   │   ├── extractors/       # Fuentes de datos
│   │   ├── transformers/     # Lógica de negocio y normalización
│   │   ├── loaders/          # Escritura a targets
│   │   └── orchestration/    # Flujos Prefect
│   ├── data_quality/
│   │   ├── validators/       # Pydantic models
│   │   ├── rules/            # GE expectation suites
│   │   └── reports/          # Dashboards HTML
│   ├── database/
│   │   ├── migrations/       # Alembic
│   │   ├── models/           # SQLAlchemy ORM
│   │   ├── optimization/     # Indexes, partitions, MViews
│   │   └── seeds/            # Datos iniciales
│   ├── aws/
│   │   ├── s3/               # Data lake handlers
│   │   ├── lambda_handlers/  # Event processors
│   │   └── glue_jobs/        # PySpark jobs
│   ├── schemas/              # Contratos compartidos
│   ├── observability/        # Logs, métricas, tracing
│   └── utils/
├── infra/
│   ├── terraform/            # IaC AWS
│   ├── docker/               # Dockerfiles
│   └── sql/                  # DDL scripts
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
├── scripts/
│   ├── seed_data.py
│   └── benchmarks/
├── docs/
│   ├── ARCHITECTURE.md
│   ├── PIPELINES.md
│   ├── POSTGRESQL_OPTIMIZATION.md
│   ├── DATA_QUALITY.md
│   ├── AWS_DEPLOYMENT.md
│   └── WALKTHROUGH.md        # Paso a paso completo
├── config/
│   └── pipelines.yaml
├── docker-compose.yml
├── pyproject.toml
├── Makefile
└── README.md
```

## Quickstart

**Setup automatizado (recomendado)** — un comando hace todo:

```bash
# macOS / Linux / WSL / Git Bash
bash scripts/setup.sh

# Windows PowerShell
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
```

Esto verifica prerequisitos, crea `.env`, instala dependencias, levanta Docker,
aplica migraciones y genera datos de ejemplo.

**Setup manual** (si prefieres controlar cada paso):

```bash
# 1. Copiar variables de entorno
cp .env.example .env        # o "copy .env.example .env" en Windows cmd

# 2. Virtualenv Python
python -m venv .venv
source .venv/bin/activate   # o ".venv\Scripts\activate" en Windows

# 3. Dependencias
pip install -e ".[dev]"

# 4. Levantar stack local (PostgreSQL + PgBouncer + Prefect + MinIO + Grafana)
docker compose up -d

# 5. Aplicar migraciones
alembic upgrade head

# 6. Cargar datos de ejemplo
python scripts/seed_data.py

# 7. Ejecutar pipeline
make pipeline
# o: python -m src.pipelines.orchestration.legal_ingestion_flow
```

### UIs disponibles

- Prefect: http://localhost:4200
- MinIO: http://localhost:9001 (`minioadmin` / `minioadmin123`)
- Prometheus: http://localhost:9090
- Grafana: http://localhost:3000 (`admin` / `admin`)

Para detalles por sistema operativo, troubleshooting y puertos ver **[SETUP.md](SETUP.md)**.

## Documentación detallada

- [**Walkthrough completo paso a paso**](docs/WALKTHROUGH.md) — Qué se implementó y por qué.
- [Arquitectura](docs/ARCHITECTURE.md)
- [Pipelines ETL/ELT](docs/PIPELINES.md)
- [Optimización PostgreSQL](docs/POSTGRESQL_OPTIMIZATION.md)
- [Data Quality](docs/DATA_QUALITY.md)
- [Despliegue AWS](docs/AWS_DEPLOYMENT.md)

## Roadmap

- [x] H0 — Fundación: estructura, Docker Compose local, DB schema, extractor base
- [x] H1 — Core: pipeline ETL completo, data quality gates, optimización PostgreSQL
- [x] H2 — AWS: integración S3/Lambda/Glue, Terraform, observability
- [ ] H3 — Avanzado: ML features, Redshift, streaming CDC con Debezium

---

**Autor**: Humberto Henriquez — Senior Data Engineer / Solutions Architect
