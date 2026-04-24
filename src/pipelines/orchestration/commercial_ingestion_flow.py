"""Commercial data ingestion flow: counterparties + contracts + transactions.

Highlights SCD2 on counterparties and bulk transactional loading.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import polars as pl
from prefect import flow, get_run_logger, task
from sqlalchemy import text

from src.data_quality import run_rules
from src.data_quality.validators.rule_engine import assert_no_errors, load_rules_yaml
from src.database.session import direct_session
from src.observability import bind_pipeline_context, configure_logging, pipeline_duration
from src.pipelines.extractors import CSVExtractor
from src.pipelines.extractors.base import ExtractBatch
from src.pipelines.loaders import PostgresBulkLoader
from src.pipelines.transformers import Scd2Handler, normalize_commercial
from src.pipelines.transformers.scd2 import Scd2Config

configure_logging()


@task(retries=3, retry_delay_seconds=20)
async def extract_commercial_csv(path: str, name: str) -> list[ExtractBatch]:
    extractor = CSVExtractor(
        path, source_name=name, chunk_size=5000, source_system="commercial_csv"
    )
    batches: list[ExtractBatch] = []
    async for b in extractor.extract():
        batches.append(b)
    return batches


@task
def normalize_commercial_batch(
    batches: list[ExtractBatch], kind: str, pipeline: str, rules_path: str | Path | None
) -> list[dict[str, Any]]:
    logger = get_run_logger()
    valid_all: list[dict[str, Any]] = []
    rejected_all: list[dict[str, Any]] = []
    for b in batches:
        r = normalize_commercial(kind, b.records, pipeline)
        valid_all.extend(r.valid)
        rejected_all.extend(r.rejected)

    logger.info(f"{kind}: valid={len(valid_all)}, rejected={len(rejected_all)}")

    if valid_all and rules_path:
        df = pl.DataFrame(valid_all)
        rules = load_rules_yaml(rules_path)
        results = run_rules(df, rules, suite=f"{pipeline}_{kind}")
        assert_no_errors(results)

    return valid_all


@task
async def upsert_counterparties_scd2(records: list[dict[str, Any]]) -> dict[str, int]:
    if not records:
        return {"inserted": 0, "expired": 0, "unchanged": 0}
    async with direct_session() as session:
        handler = Scd2Handler(
            session=session,
            config=Scd2Config(
                table="dim_counterparty",
                natural_key="external_id",
                tracked_fields=["name", "tax_id", "country_code", "risk_score", "attributes"],
                insert_fields=[
                    "external_id",
                    "name",
                    "tax_id",
                    "country_code",
                    "risk_score",
                    "attributes",
                ],
            ),
        )
        # Map schema "metadata" alias to "attributes" expected by SCD2 config
        for r in records:
            r["attributes"] = r.pop("metadata", {})
        return await handler.apply(records)


@task
async def bulk_upsert_counterparties(records: list[dict[str, Any]]) -> int:
    if not records:
        return 0
    columns = ["external_id", "name", "tax_id", "country_code", "risk_score", "metadata"]
    async with direct_session() as session:
        loader = PostgresBulkLoader(
            session=session,
            table="counterparties",
            columns=columns,
            pipeline="commercial_ingestion",
        )
        filtered = [
            {k: r.get("metadata" if k == "metadata" else k) for k in columns} for r in records
        ]
        return await loader.upsert_via_staging(
            filtered,
            conflict_columns=["external_id"],
            update_columns=columns,
        )


@task
async def bulk_load_transactions(records: list[dict[str, Any]]) -> int:
    if not records:
        return 0
    now = datetime.utcnow()
    # Resolve counterparty_id and contract_id via lookups
    async with direct_session() as session:
        cp_map = dict(
            (await session.execute(text("SELECT external_id, id FROM counterparties"))).all()
        )
        contract_map = dict(
            (await session.execute(text("SELECT contract_number, id FROM contracts"))).all()
        )

    rows = []
    skipped = 0
    for r in records:
        cp_id = cp_map.get(r["counterparty_external_id"])
        contract_id = contract_map.get(r["contract_number"])
        if not cp_id or not contract_id:
            skipped += 1
            continue
        rows.append(
            {
                "transaction_date": r["transaction_date"],
                "contract_id": contract_id,
                "counterparty_id": cp_id,
                "amount": r["amount"],
                "currency": r["currency"],
                "transaction_type": r["transaction_type"],
                "reference": r["reference"],
                "source_system": r["source_system"],
                "ingested_at": now,
                "metadata": r.get("metadata", {}),
            }
        )

    logger = get_run_logger()
    if skipped:
        logger.warning(f"Skipped {skipped} transactions with missing FK references")

    columns = [
        "transaction_date",
        "contract_id",
        "counterparty_id",
        "amount",
        "currency",
        "transaction_type",
        "reference",
        "source_system",
        "ingested_at",
        "metadata",
    ]
    async with direct_session() as session:
        loader = PostgresBulkLoader(
            session=session,
            table="transactions",
            columns=columns,
            pipeline="commercial_ingestion",
        )
        return await loader.upsert_via_staging(
            rows,
            conflict_columns=["source_system", "reference", "transaction_date"],
            update_columns=columns,
        )


@flow(name="commercial-ingestion-flow")
async def commercial_ingestion_flow(
    counterparties_csv: str = "data/samples/counterparties.csv",
    transactions_csv: str = "data/samples/transactions.csv",
) -> dict[str, Any]:
    run_id = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
    bind_pipeline_context(pipeline_name="commercial_ingestion", run_id=run_id)
    logger = get_run_logger()

    with pipeline_duration.labels(pipeline="commercial_ingestion", stage="total").time():
        cp_batches = await extract_commercial_csv(counterparties_csv, "counterparties")
        txn_batches = await extract_commercial_csv(transactions_csv, "transactions")

        cp_valid = normalize_commercial_batch(
            cp_batches,
            "counterparty",
            "commercial_ingestion",
            None,
        )
        txn_valid = normalize_commercial_batch(
            txn_batches,
            "transaction",
            "commercial_ingestion",
            "src/data_quality/rules/transactions.yaml",
        )

        cp_upserted = await bulk_upsert_counterparties(cp_valid)
        scd = await upsert_counterparties_scd2(list(cp_valid))  # SCD2 also
        txn_loaded = await bulk_load_transactions(txn_valid)

    summary = {
        "counterparties_upserted": cp_upserted,
        "scd2": scd,
        "transactions_loaded": txn_loaded,
    }
    logger.info(f"Commercial summary: {summary}")
    return summary


if __name__ == "__main__":
    import asyncio

    asyncio.run(commercial_ingestion_flow())
