"""S3 Parquet extractor — reads from the Bronze data lake layer."""
from __future__ import annotations

from collections.abc import AsyncIterator

import pyarrow.parquet as pq
import s3fs

from src.config import get_settings
from src.observability import get_logger, records_extracted
from src.pipelines.extractors.base import ExtractBatch, Extractor

logger = get_logger(__name__)


class S3ParquetExtractor(Extractor):
    """Reads Parquet files from S3 (or MinIO) in row-group chunks.

    Row groups are the Parquet unit of columnar storage. Reading in row-group
    chunks keeps memory bounded and allows for predicate/column pushdown.
    """

    def __init__(
        self,
        bucket: str,
        key: str,
        source_name: str,
        columns: list[str] | None = None,
        batch_size: int = 10_000,
        source_system: str = "s3_parquet",
    ) -> None:
        self.bucket = bucket
        self.key = key
        self.source_name = source_name
        self.columns = columns
        self.batch_size = batch_size
        self.source_system = source_system

    async def extract(self) -> AsyncIterator[ExtractBatch]:
        settings = get_settings()
        fs = s3fs.S3FileSystem(
            key=settings.aws.access_key_id,
            secret=settings.aws.secret_access_key,
            client_kwargs={"endpoint_url": settings.aws.s3_endpoint} if settings.aws.s3_endpoint else {},
        )

        path = f"{self.bucket}/{self.key}"
        logger.info("s3_extractor.start", path=path)

        with fs.open(path, "rb") as f:
            parquet_file = pq.ParquetFile(f)

            for batch in parquet_file.iter_batches(
                batch_size=self.batch_size, columns=self.columns
            ):
                records = batch.to_pylist()
                extract_batch = ExtractBatch.new(
                    source_system=self.source_system,
                    source_name=self.source_name,
                    records=records,
                    attributes={"s3_path": path},
                )
                records_extracted.labels(
                    source=self.source_system, pipeline=self.source_name
                ).inc(extract_batch.size)
                yield extract_batch
