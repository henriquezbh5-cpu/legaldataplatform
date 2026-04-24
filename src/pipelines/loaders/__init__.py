"""Loaders: write normalized data into target systems."""

from src.pipelines.loaders.postgres_bulk import PostgresBulkLoader
from src.pipelines.loaders.s3_parquet import S3ParquetLoader

__all__ = ["PostgresBulkLoader", "S3ParquetLoader"]
