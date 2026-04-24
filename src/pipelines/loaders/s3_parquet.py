"""S3 Parquet loader — writes to the Bronze/Silver/Gold data lake layers.

Parquet is the de-facto analytical columnar format:
- Columnar compression (Snappy/ZSTD) shrinks size 4-10x vs CSV
- Predicate/column pushdown makes scans faster
- Schema embedded in the file (no separate schema registry needed)
- Natively read by Athena, Redshift Spectrum, Glue, Spark

Partitioning by ingestion_date gives time-based pruning downstream.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

import polars as pl
import pyarrow as pa
import pyarrow.parquet as pq
import s3fs

from src.config import get_settings
from src.observability import get_logger, records_loaded

logger = get_logger(__name__)


class S3ParquetLoader:
    """Write records to S3 as Parquet with date partitioning."""

    def __init__(
        self,
        bucket: str,
        dataset: str,
        pipeline: str,
        partition_cols: list[str] | None = None,
        compression: str = "snappy",
    ) -> None:
        self.bucket = bucket
        self.dataset = dataset
        self.pipeline = pipeline
        self.partition_cols = partition_cols or ["ingestion_date"]
        self.compression = compression

    def _filesystem(self) -> s3fs.S3FileSystem:
        settings = get_settings()
        return s3fs.S3FileSystem(
            key=settings.aws.access_key_id,
            secret=settings.aws.secret_access_key,
            client_kwargs=(
                {"endpoint_url": settings.aws.s3_endpoint}
                if settings.aws.s3_endpoint
                else {}
            ),
        )

    def write(
        self,
        records: list[dict[str, Any]],
        ingestion_date: date | None = None,
    ) -> str:
        """Write a batch. Returns the S3 path."""
        if not records:
            return ""

        ingestion_date = ingestion_date or date.today()
        df = pl.DataFrame(records)
        if "ingestion_date" not in df.columns:
            df = df.with_columns(pl.lit(ingestion_date).alias("ingestion_date"))

        arrow_table: pa.Table = df.to_arrow()
        fs = self._filesystem()

        base_path = f"{self.bucket}/{self.dataset}"
        pq.write_to_dataset(
            arrow_table,
            root_path=base_path,
            partition_cols=self.partition_cols,
            filesystem=fs,
            compression=self.compression,
            existing_data_behavior="overwrite_or_ignore",
            basename_template=f"part-{datetime.utcnow():%Y%m%dT%H%M%S%f}-{{i}}.parquet",
        )

        records_loaded.labels(target=self.dataset, pipeline=self.pipeline).inc(len(records))
        logger.info(
            "s3_loader.written",
            dataset=self.dataset,
            rows=len(records),
            compression=self.compression,
        )
        return base_path
