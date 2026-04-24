"""GLEIF ingestion flow — loads Legal Entity Identifiers into counterparties.

Flow:
    1. Pull LEI records from GLEIF's public registry (paginated, rate-limited)
    2. Land raw batches in Bronze (S3 Parquet)
    3. Validate with Pydantic (CounterpartySchema)
    4. Persist rejects to Quarantine
    5. Upsert into counterparties + apply SCD2 on dim_counterparty
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

import polars as pl
from prefect import flow, get_run_logger, task

from src.config import get_settings
from src.database.session import direct_session
from src.observability import bind_pipeline_context, configure_logging, pipeline_duration
from src.pipelines.extractors import GleifConfig, GleifExtractor
from src.pipelines.extractors.base import ExtractBatch
from src.pipelines.loaders import PostgresBulkLoader, S3ParquetLoader
from src.pipelines.transformers import Scd2Handler, normalize_commercial
from src.pipelines.transformers.scd2 import Scd2Config

configure_logging()


@task(retries=3, retry_delay_seconds=30, log_prints=True)
async def extract_gleif(
    country_code: str | None, max_pages: int
) -> list[ExtractBatch]:
    extractor = GleifExtractor(
        GleifConfig(
            country_code=country_code,
            entity_status="ACTIVE",
            max_pages=max_pages,
            source_name="gleif_lei",
        )
    )
    batches: list[ExtractBatch] = []
    async for b in extractor.extract():
        batches.append(b)
    return batches


@task
def persist_bronze(batches: list[ExtractBatch]) -> str:
    if not batches:
        return ""
    settings = get_settings()
    loader = S3ParquetLoader(
        bucket=settings.s3.bronze_bucket,
        dataset="gleif_lei",
        pipeline="gleif_ingestion",
    )
    path = ""
    for b in batches:
        enriched = [
            {**r, "_batch_id": b.batch_id, "_extracted_at": b.extracted_at}
            for r in b.records
        ]
        path = loader.write(enriched, ingestion_date=date.today())
    return path


@task
def normalize_batches(batches: list[ExtractBatch]) -> list[dict[str, Any]]:
    logger = get_run_logger()
    valid: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for b in batches:
        r = normalize_commercial("counterparty", b.records, pipeline="gleif_ingestion")
        valid.extend(r.valid)
        rejected.extend(r.rejected)
    logger.info(f"GLEIF normalization: valid={len(valid)} rejected={len(rejected)}")
    return valid


@task
async def upsert_counterparties(records: list[dict[str, Any]]) -> int:
    if not records:
        return 0
    columns = ["external_id", "name", "tax_id", "country_code", "risk_score", "metadata"]
    async with direct_session() as session:
        loader = PostgresBulkLoader(
            session=session,
            table="counterparties",
            columns=columns,
            pipeline="gleif_ingestion",
        )
        rows = []
        for r in records:
            rows.append({
                "external_id": r["external_id"],
                "name": r["name"],
                "tax_id": r.get("tax_id"),
                "country_code": r["country_code"],
                "risk_score": r.get("risk_score"),
                "metadata": r.get("metadata", {}),
            })
        return await loader.upsert_via_staging(
            rows,
            conflict_columns=["external_id"],
            update_columns=columns,
        )


@task
async def apply_scd2(records: list[dict[str, Any]]) -> dict[str, int]:
    if not records:
        return {"inserted": 0, "expired": 0, "unchanged": 0}
    async with direct_session() as session:
        handler = Scd2Handler(
            session=session,
            config=Scd2Config(
                table="dim_counterparty",
                natural_key="external_id",
                tracked_fields=["name", "tax_id", "country_code", "attributes"],
                insert_fields=["external_id", "name", "tax_id", "country_code", "risk_score", "attributes"],
            ),
        )
        for r in records:
            r["attributes"] = r.pop("metadata", {})
        return await handler.apply(records)


@flow(name="gleif-ingestion")
async def gleif_ingestion_flow(
    country_code: str | None = "US",
    max_pages: int = 5,
) -> dict[str, Any]:
    """Load Legal Entity Identifiers from GLEIF into counterparties.

    Parameters
    ----------
    country_code:
        ISO-3166 alpha-2 to filter by (e.g. "US", "ES", "DE"). None = all countries.
    max_pages:
        Safety cap on pagination; at page_size=200, 5 pages = 1,000 LEIs.
    """
    run_id = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
    bind_pipeline_context(pipeline_name="gleif_ingestion", run_id=run_id)
    logger = get_run_logger()

    with pipeline_duration.labels(pipeline="gleif_ingestion", stage="total").time():
        with pipeline_duration.labels(pipeline="gleif_ingestion", stage="extract").time():
            batches = await extract_gleif(country_code, max_pages)

        if not batches:
            logger.warning("No GLEIF records fetched")
            return {"extracted": 0, "loaded": 0}

        total = sum(b.size for b in batches)
        logger.info(f"Extracted {total} LEI records")

        persist_bronze(batches)
        valid = normalize_batches(batches)

        with pipeline_duration.labels(pipeline="gleif_ingestion", stage="load").time():
            upserted = await upsert_counterparties(valid)
            scd = await apply_scd2(list(valid))

    summary = {"extracted": total, "valid": len(valid), "upserted": upserted, "scd2": scd}
    logger.info(f"GLEIF flow summary: {summary}")
    return summary


if __name__ == "__main__":
    import asyncio
    asyncio.run(gleif_ingestion_flow())
