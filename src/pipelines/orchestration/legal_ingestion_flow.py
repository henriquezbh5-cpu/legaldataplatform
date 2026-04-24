"""End-to-end legal data ingestion flow.

Medallion architecture:
    Bronze (raw)  → Silver (normalized, quality-gated) → Gold (business-ready)

Stages:
    1. Extract from sources → land in Bronze S3 (Parquet)
    2. Normalize Bronze → Silver (Pydantic + DQ rules)
    3. Load Silver → PostgreSQL (COPY + UPSERT)
    4. Build Gold aggregates (refresh materialized views)
"""
from __future__ import annotations

import hashlib
from datetime import date, datetime
from pathlib import Path
from typing import Any

import polars as pl
from prefect import flow, get_run_logger, task
from sqlalchemy import text

from src.config import get_settings
from src.data_quality import run_rules
from src.data_quality.validators.rule_engine import assert_no_errors, load_rules_yaml
from src.database.session import direct_session
from src.observability import (
    bind_pipeline_context,
    configure_logging,
    pipeline_duration,
)
from src.pipelines.extractors import CSVExtractor
from src.pipelines.extractors.base import ExtractBatch
from src.pipelines.loaders import PostgresBulkLoader, S3ParquetLoader
from src.pipelines.transformers import normalize_legal

configure_logging()


# -----------------------------------------------------------------------------
# Tasks
# -----------------------------------------------------------------------------

@task(retries=3, retry_delay_seconds=30, log_prints=True)
async def extract_from_csv(
    file_path: str, source_name: str, chunk_size: int = 5000
) -> list[ExtractBatch]:
    """Run a CSV extractor and collect all batches."""
    extractor = CSVExtractor(
        file_path=file_path,
        source_name=source_name,
        chunk_size=chunk_size,
        source_system="legal_csv",
    )
    batches: list[ExtractBatch] = []
    async for batch in extractor.extract():
        batches.append(batch)
    return batches


@task(log_prints=True)
def persist_to_bronze(batches: list[ExtractBatch], dataset: str, pipeline: str) -> str:
    """Write raw batches to the Bronze S3 layer."""
    settings = get_settings()
    loader = S3ParquetLoader(
        bucket=settings.s3.bronze_bucket,
        dataset=dataset,
        pipeline=pipeline,
    )
    total = 0
    path = ""
    for batch in batches:
        # Enrich each record with extraction metadata before write
        enriched = [
            {**rec, "_batch_id": batch.batch_id, "_extracted_at": batch.extracted_at}
            for rec in batch.records
        ]
        path = loader.write(enriched, ingestion_date=date.today())
        total += len(enriched)

    logger = get_run_logger()
    logger.info(f"Bronze write complete: {total} rows to {path}")
    return path


@task(log_prints=True)
def normalize_and_validate(
    batches: list[ExtractBatch],
    kind: str,
    pipeline: str,
    rules_path: str | Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Normalize raw records and apply declarative DQ rules."""
    logger = get_run_logger()
    all_valid: list[dict[str, Any]] = []
    all_rejected: list[dict[str, Any]] = []

    for batch in batches:
        # Map CSV columns → schema fields; this is where source-specific
        # glue code lives. For legal docs we assume the CSV uses these names.
        mapped = [_map_legal_doc_csv(r) for r in batch.records]
        result = normalize_legal(kind, mapped, pipeline)
        all_valid.extend(result.valid)
        all_rejected.extend(result.rejected)

    logger.info(
        f"Normalization: {len(all_valid)} valid, {len(all_rejected)} rejected "
        f"({len(all_rejected) / max(len(all_valid) + len(all_rejected), 1):.2%})"
    )

    # Apply DQ rules on the valid subset
    if all_valid:
        df = pl.DataFrame(all_valid)
        rules = load_rules_yaml(rules_path)
        results = run_rules(df, rules, suite=pipeline)
        assert_no_errors(results)

    return all_valid, all_rejected


@task(log_prints=True)
async def load_legal_documents(records: list[dict[str, Any]], pipeline: str) -> int:
    """Bulk-load normalized legal documents into PostgreSQL."""
    if not records:
        return 0

    # Hydrate required DB-side fields
    now = datetime.utcnow()
    for r in records:
        r.setdefault("ingested_at", now)
        r.setdefault("tags", [])
        r.setdefault("metadata", {})

    columns = [
        "document_date", "source_system", "source_id", "source_hash",
        "document_type", "title", "content", "jurisdiction", "tags",
        "metadata", "ingested_at",
    ]
    # Strip any keys not in columns
    filtered = [{k: r.get(k) for k in columns} for r in records]

    async with direct_session() as session:
        loader = PostgresBulkLoader(
            session=session,
            table="legal_documents",
            columns=columns,
            pipeline=pipeline,
        )
        count = await loader.upsert_via_staging(
            filtered,
            conflict_columns=["source_system", "source_id", "document_date"],
            update_columns=columns,
        )
    return count


@task(log_prints=True)
async def persist_quarantine(
    rejected: list[dict[str, Any]], pipeline: str
) -> str | None:
    """Persist rejected records to the Quarantine bucket for triage."""
    if not rejected:
        return None
    settings = get_settings()
    loader = S3ParquetLoader(
        bucket=settings.s3.quarantine_bucket,
        dataset=pipeline,
        pipeline=pipeline,
    )
    flat = [
        {
            "raw": r["raw"],
            "schema": r["schema"],
            "errors": r["errors"],
            "rejected_at": datetime.utcnow(),
        }
        for r in rejected
    ]
    return loader.write(flat)


@task
async def refresh_gold() -> None:
    """Refresh materialized views that serve the Gold analytical layer."""
    async with direct_session() as session:
        await session.execute(text("CALL refresh_analytical_views()"))


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def _map_legal_doc_csv(row: dict[str, Any]) -> dict[str, Any]:
    """Map source CSV columns to LegalDocumentSchema field names."""
    src_id = row.get("doc_id") or row.get("source_id") or ""
    doc_date = row.get("date") or row.get("document_date")
    source_system = row.get("source_system", "legal_csv")

    canonical = f"{source_system}|{src_id}|{doc_date}".encode()
    source_hash = hashlib.sha256(canonical).hexdigest()

    return {
        "document_date": doc_date,
        "source_system": source_system,
        "source_id": str(src_id),
        "source_hash": source_hash,
        "document_type": row.get("type") or row.get("document_type") or "NOTICE",
        "title": row.get("title", ""),
        "content": row.get("content") or row.get("body"),
        "jurisdiction": row.get("jurisdiction", "UNKNOWN"),
        "tags": row.get("tags", []) or [],
        "metadata": {
            "original_source_row": row,
        },
    }


# -----------------------------------------------------------------------------
# Flow
# -----------------------------------------------------------------------------

@flow(name="legal-ingestion-flow")
async def legal_ingestion_flow(
    file_path: str = "data/samples/legal_documents.csv",
    rules_path: str = "src/data_quality/rules/legal_documents.yaml",
) -> dict[str, Any]:
    """Top-level flow. Returns summary counters."""
    run_id = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
    bind_pipeline_context(pipeline_name="legal_ingestion", run_id=run_id)
    logger = get_run_logger()

    with pipeline_duration.labels(pipeline="legal_ingestion", stage="total").time():
        with pipeline_duration.labels(pipeline="legal_ingestion", stage="extract").time():
            batches = await extract_from_csv(file_path, source_name="legal_documents")

        if not batches:
            logger.warning("No records extracted")
            return {"extracted": 0, "loaded": 0}

        with pipeline_duration.labels(pipeline="legal_ingestion", stage="bronze").time():
            await persist_to_bronze(batches, dataset="legal_documents", pipeline="legal_ingestion")

        with pipeline_duration.labels(pipeline="legal_ingestion", stage="normalize").time():
            valid, rejected = normalize_and_validate(
                batches, kind="document", pipeline="legal_ingestion", rules_path=rules_path,
            )

        if rejected:
            await persist_quarantine(rejected, pipeline="legal_ingestion")

        with pipeline_duration.labels(pipeline="legal_ingestion", stage="load").time():
            loaded = await load_legal_documents(valid, pipeline="legal_ingestion")

        with pipeline_duration.labels(pipeline="legal_ingestion", stage="gold").time():
            await refresh_gold()

    summary = {
        "extracted": sum(b.size for b in batches),
        "valid": len(valid),
        "rejected": len(rejected),
        "loaded": loaded,
    }
    logger.info(f"Flow summary: {summary}")
    return summary


if __name__ == "__main__":
    import asyncio
    asyncio.run(legal_ingestion_flow())
