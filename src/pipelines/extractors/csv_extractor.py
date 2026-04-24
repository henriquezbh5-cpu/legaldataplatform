"""CSV extractor that streams rows in chunks using Polars.

Polars reads CSV 10-30x faster than Pandas for large files and uses less
memory. For CSVs too large to fit in RAM, we use `scan_csv` + streaming.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import polars as pl

from src.observability import get_logger, records_extracted
from src.pipelines.extractors.base import ExtractBatch, Extractor

logger = get_logger(__name__)


class CSVExtractor(Extractor):
    """Stream a CSV file in configurable chunks."""

    def __init__(
        self,
        file_path: str | Path,
        source_name: str,
        chunk_size: int = 10_000,
        source_system: str = "csv",
        separator: str = ",",
        encoding: str = "utf8",
    ) -> None:
        self.file_path = Path(file_path)
        self.source_name = source_name
        self.chunk_size = chunk_size
        self.source_system = source_system
        self.separator = separator
        self.encoding = encoding

    async def extract(self) -> AsyncIterator[ExtractBatch]:
        if not self.file_path.exists():
            raise FileNotFoundError(f"CSV not found: {self.file_path}")

        logger.info("csv_extractor.start", path=str(self.file_path))

        # Lazy scan: builds a query plan; execution is pushed down
        lazy = pl.scan_csv(
            self.file_path,
            separator=self.separator,
            encoding=self.encoding,
            infer_schema_length=1000,
            ignore_errors=False,
        )

        total = 0
        offset = 0
        while True:
            chunk = lazy.slice(offset, self.chunk_size).collect()
            if chunk.is_empty():
                break

            records = chunk.to_dicts()
            batch = ExtractBatch.new(
                source_system=self.source_system,
                source_name=self.source_name,
                records=records,
                attributes={"file": str(self.file_path), "chunk_offset": offset},
            )
            records_extracted.labels(
                source=self.source_system, pipeline=self.source_name
            ).inc(batch.size)

            logger.info(
                "csv_extractor.batch",
                batch_id=batch.batch_id,
                size=batch.size,
                offset=offset,
            )
            yield batch

            total += len(records)
            offset += self.chunk_size
            if len(records) < self.chunk_size:
                break

        logger.info("csv_extractor.done", total=total)
