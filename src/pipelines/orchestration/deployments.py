"""Prefect deployment definitions — maps flows to schedules and work pools.

Run: `python -m src.pipelines.orchestration.deployments` to register.
"""

from __future__ import annotations

from prefect import serve

from src.pipelines.orchestration.commercial_ingestion_flow import commercial_ingestion_flow
from src.pipelines.orchestration.legal_ingestion_flow import legal_ingestion_flow


def main() -> None:
    legal_dep = legal_ingestion_flow.to_deployment(
        name="legal-ingestion-daily",
        cron="0 2 * * *",  # 02:00 UTC daily
        parameters={
            "file_path": "data/samples/legal_documents.csv",
            "rules_path": "src/data_quality/rules/legal_documents.yaml",
        },
        tags=["legal", "ingestion", "production"],
    )
    commercial_dep = commercial_ingestion_flow.to_deployment(
        name="commercial-ingestion-hourly",
        cron="15 * * * *",  # 15 min past every hour
        parameters={
            "counterparties_csv": "data/samples/counterparties.csv",
            "transactions_csv": "data/samples/transactions.csv",
        },
        tags=["commercial", "ingestion", "production"],
    )
    serve(legal_dep, commercial_dep)


if __name__ == "__main__":
    main()
