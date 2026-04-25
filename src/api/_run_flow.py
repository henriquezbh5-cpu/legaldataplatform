"""CLI entrypoint used by the API to run the legal flow against a custom CSV.

Usage:
    python -m src.api._run_flow /path/to/uploaded.csv
"""

from __future__ import annotations

import asyncio
import sys

from src.pipelines.orchestration.legal_ingestion_flow import legal_ingestion_flow


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python -m src.api._run_flow <csv_path>", file=sys.stderr)
        return 2

    csv_path = sys.argv[1]

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    asyncio.run(
        legal_ingestion_flow(
            file_path=csv_path,
            rules_path="src/data_quality/rules/legal_documents.yaml",
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
