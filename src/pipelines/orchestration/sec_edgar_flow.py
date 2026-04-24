"""End-to-end pipeline for the SEC EDGAR source.

Flow:
    1. Pull recent filings from SEC's public API (rate-limited, identified)
    2. Land raw batches in Bronze (S3 Parquet)
    3. Validate with Pydantic + YAML DQ rules
    4. Persist rejects to Quarantine
    5. Upsert into legal_documents via COPY staging

Usage:
    export SEC_USER_AGENT="LegalDataPlatform/0.1 (yourname@example.com)"
    python -m src.pipelines.orchestration.sec_edgar_flow
"""
from __future__ import annotations

import os
from datetime import date, datetime
from typing import Any

import polars as pl
from prefect import flow, get_run_logger, task

from src.config import get_settings
from src.data_quality import run_rules
from src.data_quality.validators.rule_engine import assert_no_errors, load_rules_yaml
from src.database.session import direct_session
from src.observability import bind_pipeline_context, configure_logging, pipeline_duration
from src.pipelines.extractors import SecEdgarConfig, SecEdgarExtractor
from src.pipelines.extractors.base import ExtractBatch
from src.pipelines.loaders import PostgresBulkLoader, S3ParquetLoader
from src.pipelines.transformers import normalize_legal

configure_logging()


@task(retries=3, retry_delay_seconds=60, log_prints=True)
async def extract_sec_filings(
    user_agent: str,
    max_companies: int,
    form_types: list[str] | None,
    since_date: date | None,
) -> list[ExtractBatch]:
    extractor = SecEdgarExtractor(
        SecEdgarConfig(
            user_agent=user_agent,
            max_companies=max_companies,
            form_types=form_types,
            since_date=since_date,
            batch_size=100,
            source_name="sec_edgar_filings",
        )
    )
    batches: list[ExtractBatch] = []
    async for batch in extractor.extract():
        batches.append(batch)
    return batches


@task(log_prints=True)
def persist_bronze(batches: list[ExtractBatch]) -> str:
    if not batches:
        return ""
    settings = get_settings()
    loader = S3ParquetLoader(
        bucket=settings.s3.bronze_bucket,
        dataset="sec_edgar_filings",
        pipeline="sec_edgar_ingestion",
    )
    path = ""
    for batch in batches:
        enriched = [
            {**r, "_batch_id": batch.batch_id, "_extracted_at": batch.extracted_at}
            for r in batch.records
        ]
        path = loader.write(enriched, ingestion_date=date.today())
    return path


@task(log_prints=True)
def normalize_and_validate(
    batches: list[ExtractBatch],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    logger = get_run_logger()
    valid_all: list[dict[str, Any]] = []
    rejected_all: list[dict[str, Any]] = []

    for batch in batches:
        result = normalize_legal("document", batch.records, pipeline="sec_edgar_ingestion")
        valid_all.extend(result.valid)
        rejected_all.extend(result.rejected)

    logger.info(
        f"Normalization: valid={len(valid_all)} rejected={len(rejected_all)} "
        f"rate={len(rejected_all) / max(len(valid_all) + len(rejected_all), 1):.4f}"
    )

    if valid_all:
        df = pl.DataFrame(valid_all)
        rules = load_rules_yaml("src/data_quality/rules/legal_documents.yaml")
        results = run_rules(df, rules, suite="sec_edgar_ingestion")
        assert_no_errors(results)

    return valid_all, rejected_all


@task(log_prints=True)
async def load_filings(records: list[dict[str, Any]]) -> int:
    if not records:
        return 0

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
    filtered = [{k: r.get(k) for k in columns} for r in records]

    async with direct_session() as session:
        loader = PostgresBulkLoader(
            session=session,
            table="legal_documents",
            columns=columns,
            pipeline="sec_edgar_ingestion",
        )
        return await loader.upsert_via_staging(
            filtered,
            conflict_columns=["source_system", "source_id", "document_date"],
            update_columns=columns,
        )


@task
async def persist_quarantine(rejected: list[dict[str, Any]]) -> str:
    if not rejected:
        return ""
    settings = get_settings()
    loader = S3ParquetLoader(
        bucket=settings.s3.quarantine_bucket,
        dataset="sec_edgar_ingestion",
        pipeline="sec_edgar_ingestion",
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


@flow(name="sec-edgar-ingestion")
async def sec_edgar_ingestion_flow(
    user_agent: str | None = None,
    max_companies: int = 50,
    form_types: list[str] | None = None,
    since_days: int = 90,
) -> dict[str, Any]:
    """Top-level flow for SEC EDGAR ingestion.

    Parameters
    ----------
    user_agent:
        SEC requires identification. If None, reads SEC_USER_AGENT env var.
    max_companies:
        Number of tickers to process (default: 50).
    form_types:
        Filter to specific filing types (e.g. ["10-K", "10-Q", "8-K"]).
    since_days:
        Only filings within the last N days.
    """
    from datetime import timedelta

    run_id = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
    bind_pipeline_context(pipeline_name="sec_edgar_ingestion", run_id=run_id)
    logger = get_run_logger()

    ua = user_agent or os.environ.get("SEC_USER_AGENT")
    if not ua:
        raise RuntimeError(
            "SEC_USER_AGENT env var required. Set it to a string with your email: "
            '"LegalDataPlatform/0.1 (yourname@example.com)"'
        )

    since_date = date.today() - timedelta(days=since_days)

    with pipeline_duration.labels(pipeline="sec_edgar_ingestion", stage="total").time():

        with pipeline_duration.labels(pipeline="sec_edgar_ingestion", stage="extract").time():
            batches = await extract_sec_filings(ua, max_companies, form_types, since_date)

        if not batches:
            logger.warning("No filings fetched")
            return {"extracted": 0, "loaded": 0}

        total_extracted = sum(b.size for b in batches)
        logger.info(f"Extracted {total_extracted} filings from {max_companies} companies")

        with pipeline_duration.labels(pipeline="sec_edgar_ingestion", stage="bronze").time():
            persist_bronze(batches)

        with pipeline_duration.labels(pipeline="sec_edgar_ingestion", stage="normalize").time():
            valid, rejected = normalize_and_validate(batches)

        if rejected:
            await persist_quarantine(rejected)

        with pipeline_duration.labels(pipeline="sec_edgar_ingestion", stage="load").time():
            loaded = await load_filings(valid)

    summary = {
        "extracted": total_extracted,
        "valid": len(valid),
        "rejected": len(rejected),
        "loaded": loaded,
    }
    logger.info(f"SEC EDGAR flow summary: {summary}")
    return summary


if __name__ == "__main__":
    import asyncio
    asyncio.run(sec_edgar_ingestion_flow())
