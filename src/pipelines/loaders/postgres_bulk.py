"""PostgreSQL bulk loader using the COPY protocol.

COPY is 10-100x faster than row-by-row INSERTs because it bypasses per-row
transaction overhead. For UPSERTs we use the staging-table pattern:

    1. TRUNCATE a staging table
    2. COPY new data into staging
    3. Run an INSERT ... ON CONFLICT ... DO UPDATE from staging → target

This keeps the write path fast and atomic.
"""
from __future__ import annotations

import csv
import io
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.observability import get_logger, records_loaded

logger = get_logger(__name__)


class PostgresBulkLoader:
    """Bulk loader using COPY FROM STDIN via asyncpg raw connection."""

    def __init__(
        self,
        session: AsyncSession,
        table: str,
        columns: list[str],
        pipeline: str,
    ) -> None:
        self.session = session
        self.table = table
        self.columns = columns
        self.pipeline = pipeline

    async def copy_records(self, records: list[dict[str, Any]]) -> int:
        """Stream records via COPY. Returns number of rows written."""
        if not records:
            return 0

        raw_conn = await (await self.session.connection()).get_raw_connection()
        driver_conn = raw_conn.driver_connection  # asyncpg.Connection

        buffer = self._encode_csv(records)
        await driver_conn.copy_to_table(
            self.table,
            source=io.BytesIO(buffer.encode("utf-8")),
            columns=self.columns,
            format="csv",
            header=False,
        )

        records_loaded.labels(target=self.table, pipeline=self.pipeline).inc(len(records))
        logger.info("pg_loader.copied", table=self.table, rows=len(records))
        return len(records)

    async def upsert_via_staging(
        self,
        records: list[dict[str, Any]],
        conflict_columns: list[str],
        update_columns: list[str],
        staging_suffix: str = "_stg",
    ) -> int:
        """UPSERT pattern: COPY into staging then INSERT ... ON CONFLICT."""
        if not records:
            return 0

        staging = f"{self.table}{staging_suffix}"

        await self.session.execute(text(f"""
            CREATE TEMP TABLE IF NOT EXISTS {staging}
                (LIKE {self.table} INCLUDING DEFAULTS)
                ON COMMIT DROP
        """))
        await self.session.execute(text(f"TRUNCATE {staging}"))

        # COPY into staging
        raw_conn = await (await self.session.connection()).get_raw_connection()
        driver_conn = raw_conn.driver_connection
        buffer = self._encode_csv(records)
        await driver_conn.copy_to_table(
            staging,
            source=io.BytesIO(buffer.encode("utf-8")),
            columns=self.columns,
            format="csv",
            header=False,
        )

        conflict_cols = ", ".join(conflict_columns)
        set_clause = ", ".join(
            f"{c} = EXCLUDED.{c}" for c in update_columns if c not in conflict_columns
        )
        col_list = ", ".join(self.columns)

        sql = f"""
            INSERT INTO {self.table} ({col_list})
            SELECT {col_list} FROM {staging}
            ON CONFLICT ({conflict_cols})
            DO UPDATE SET {set_clause}, updated_at = now()
        """
        await self.session.execute(text(sql))

        records_loaded.labels(target=self.table, pipeline=self.pipeline).inc(len(records))
        logger.info(
            "pg_loader.upserted",
            table=self.table,
            rows=len(records),
            conflict=conflict_cols,
        )
        return len(records)

    def _encode_csv(self, records: list[dict[str, Any]]) -> str:
        """Render records as CSV in the column order expected by COPY."""
        buf = io.StringIO()
        writer = csv.writer(buf, quoting=csv.QUOTE_MINIMAL)
        for rec in records:
            row = [self._serialize(rec.get(c)) for c in self.columns]
            writer.writerow(row)
        return buf.getvalue()

    @staticmethod
    def _serialize(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, (dict, list)):
            import json
            return json.dumps(value, default=str)
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)
