"""Database-to-database extractor with watermark tracking (incremental loads).

Watermark-based extraction ensures idempotency: we only fetch rows newer
than the last successful run. The watermark is stored in a dedicated table.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.observability import get_logger, records_extracted
from src.pipelines.extractors.base import ExtractBatch, Extractor

logger = get_logger(__name__)


class PostgresExtractor(Extractor):
    """Incremental Postgres extractor using a watermark column.

    Usage:
        extractor = PostgresExtractor(
            session=session,
            query="SELECT id, name, updated_at FROM source_table "
                  "WHERE updated_at > :watermark ORDER BY updated_at",
            watermark_column="updated_at",
            last_watermark=datetime(2024, 1, 1),
            source_name="source_table",
            batch_size=5000,
        )
        async for batch in extractor.extract(): ...
    """

    def __init__(
        self,
        session: AsyncSession,
        query: str,
        watermark_column: str,
        last_watermark: Any,
        source_name: str,
        batch_size: int = 5000,
        source_system: str = "postgres",
    ) -> None:
        self.session = session
        self.query = query
        self.watermark_column = watermark_column
        self.last_watermark = last_watermark
        self.source_name = source_name
        self.batch_size = batch_size
        self.source_system = source_system

    async def extract(self) -> AsyncIterator[ExtractBatch]:
        logger.info(
            "pg_extractor.start",
            source=self.source_name,
            watermark=str(self.last_watermark),
        )

        result = await self.session.execute(
            text(self.query),
            {"watermark": self.last_watermark},
        )

        buffer: list[dict[str, Any]] = []
        max_watermark = self.last_watermark

        async for row in result:
            record = dict(row._mapping)
            wm = record.get(self.watermark_column)
            if wm and (max_watermark is None or wm > max_watermark):
                max_watermark = wm
            buffer.append(record)

            if len(buffer) >= self.batch_size:
                batch = ExtractBatch.new(
                    source_system=self.source_system,
                    source_name=self.source_name,
                    records=buffer,
                    attributes={"watermark_column": self.watermark_column},
                )
                records_extracted.labels(source=self.source_system, pipeline=self.source_name).inc(
                    batch.size
                )
                yield batch
                buffer = []

        if buffer:
            batch = ExtractBatch.new(
                source_system=self.source_system,
                source_name=self.source_name,
                records=buffer,
                attributes={
                    "watermark_column": self.watermark_column,
                    "new_watermark": str(max_watermark),
                },
            )
            records_extracted.labels(source=self.source_system, pipeline=self.source_name).inc(
                batch.size
            )
            yield batch

        logger.info(
            "pg_extractor.done",
            source=self.source_name,
            new_watermark=str(max_watermark),
        )


async def get_watermark(session: AsyncSession, pipeline_name: str, default: datetime) -> datetime:
    """Fetch last watermark for a given pipeline."""
    await session.execute(
        text("""
        CREATE TABLE IF NOT EXISTS pipeline_watermarks (
            pipeline_name TEXT PRIMARY KEY,
            watermark TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    )
    row = (
        await session.execute(
            text("SELECT watermark FROM pipeline_watermarks WHERE pipeline_name = :n"),
            {"n": pipeline_name},
        )
    ).first()
    return row[0] if row else default


async def set_watermark(session: AsyncSession, pipeline_name: str, watermark: datetime) -> None:
    """Upsert watermark for a pipeline."""
    await session.execute(
        text("""
        INSERT INTO pipeline_watermarks (pipeline_name, watermark)
        VALUES (:n, :wm)
        ON CONFLICT (pipeline_name)
        DO UPDATE SET watermark = EXCLUDED.watermark, updated_at = now()
    """),
        {"n": pipeline_name, "wm": watermark},
    )
