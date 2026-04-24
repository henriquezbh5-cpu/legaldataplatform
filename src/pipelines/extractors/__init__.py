"""Extractor modules — one per source type.

All extractors implement the `Extractor` protocol and yield `ExtractBatch`
records with source metadata for lineage tracking.
"""
from src.pipelines.extractors.base import ExtractBatch, Extractor
from src.pipelines.extractors.csv_extractor import CSVExtractor
from src.pipelines.extractors.db_extractor import PostgresExtractor
from src.pipelines.extractors.rest_api import RestAPIExtractor
from src.pipelines.extractors.s3_extractor import S3ParquetExtractor

__all__ = [
    "CSVExtractor",
    "ExtractBatch",
    "Extractor",
    "PostgresExtractor",
    "RestAPIExtractor",
    "S3ParquetExtractor",
]
