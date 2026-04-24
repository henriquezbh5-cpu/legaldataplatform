# Arquitectura

## Diagrama de componentes

```
┌──────────────────────────────────────────────────────────────────────────┐
│                              SOURCES                                     │
│  REST APIs · CSV/SFTP · External DBs · Web scraping · Event streams      │
└──────────────────────────────┬───────────────────────────────────────────┘
                               │
          ┌────────────────────┼────────────────────┐
          ▼                    ▼                    ▼
   ┌────────────┐       ┌────────────┐      ┌────────────┐
   │  REST      │       │  CSV/SFTP  │      │  DB        │
   │ extractor  │       │ extractor  │      │ extractor  │
   └─────┬──────┘       └─────┬──────┘      └─────┬──────┘
         │                    │                   │
         └──────────┬─────────┴─────────┬─────────┘
                    ▼                   ▼
             ┌──────────────────────────────┐
             │  BRONZE LAYER (S3 Parquet)   │
             │  Raw, immutable, lineage-tagged│
             └──────────────┬───────────────┘
                            │
                            ▼
             ┌──────────────────────────────┐
             │  NORMALIZE (Pydantic)        │
             │  + DQ rules (YAML engine)    │
             │  + Great Expectations        │
             └──────────────┬───────────────┘
                            │
                  ┌─────────┼──────────┐
                  ▼         ▼          ▼
            Quarantine  Silver    Silver (S3)
             (S3)       (tables)
                            │
                            ▼
                  ┌──────────────────┐
                  │  POSTGRESQL 16   │
                  │  SoT Operativo   │
                  │  · Particionado  │
                  │  · SCD2 dims     │
                  │  · MViews        │
                  │  · PgBouncer pool│
                  └──────────┬───────┘
                             │
                             ▼
                  ┌──────────────────┐
                  │  GOLD LAYER      │
                  │  MViews refresh  │
                  │  + S3 export     │
                  └──────────┬───────┘
                             │
                  ┌──────────┴───────────┐
                  ▼                      ▼
           BI / Dashboards        ML / Analytics
```

## Componentes clave

| Componente | Ubicación | Responsabilidad |
|---|---|---|
| Extractors | `src/pipelines/extractors/` | Lectura de fuentes externas |
| Transformers | `src/pipelines/transformers/` | Normalización, SCD2, enrichment |
| Loaders | `src/pipelines/loaders/` | Escritura bulk a Postgres y S3 |
| Schemas | `src/schemas/` | Contratos Pydantic compartidos |
| Rule engine | `src/data_quality/validators/` | DQ gates declarativos |
| Orchestration | `src/pipelines/orchestration/` | Flows Prefect |
| DB | `src/database/` | ORM, migrations, optimization |
| AWS | `src/aws/` | S3, Lambda, Glue integrations |
| Observability | `src/observability/` | Logs + metrics + tracing |
| IaC | `infra/terraform/` | AWS resources |

## Flujo de control

1. **Trigger**: cron de Prefect, webhook, o S3 event vía Lambda.
2. **Ejecución**: worker Prefect ejecuta el flow, invocando tasks con retry/backoff.
3. **Persistence**: cada stage persiste artefactos (Bronze, quarantine, Silver) antes del siguiente.
4. **Observabilidad**: structlog emite JSON → CloudWatch / Grafana; Prometheus scrapea métricas.
5. **Alerting**: Grafana alerting sobre tasas de rechazo, duración p95, DLQ count.

## Patrones aplicados

- **Medallion Architecture** (Databricks) — Bronze/Silver/Gold.
- **Watermark-based incremental extraction** — no re-procesa lo ya hecho.
- **Dead Letter Queue** — mensajes fallidos no bloquean el pipeline.
- **Idempotent upserts** — re-ejecutar un flow no duplica datos.
- **Staging-table UPSERT** — alta velocidad de carga a Postgres.
- **Slowly Changing Dimensions Type 2** — histórico queryable por fecha.
- **Lineage tagging** — batch_id acompaña al dato hasta el destino.
- **Partition pruning** — queries sobre rangos de fechas saltan particiones irrelevantes.

## Escalabilidad

| Capa | Mecanismo | Límite práctico |
|---|---|---|
| Extract | `async` + chunks | Red de origen (rate limits) |
| Bronze | S3 | Ilimitado |
| Transform | Polars en un proceso | ~100M rows; por encima → Glue Spark |
| Load | COPY + particiones | 500K-1M rows/s por conexión |
| Query | Indexes + MViews | p95 <100ms en 100M+ rows si el modelo se respeta |

## Seguridad

- Credenciales en Secrets Manager, **nunca en .env en prod**.
- SSE-KMS en todos los buckets + Aurora encryption at rest.
- IAM roles scoped per-function (principio de menor privilegio).
- Postgres roles separados: `ldp_readonly`, `ldp_etl`, `ldp_admin`.
- VPC privada para Aurora; Lambdas opcionales en VPC.
- Audit trail: `created_at`, `updated_at`, `ingested_at` en todas las tablas.
