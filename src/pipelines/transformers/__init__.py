"""Transformers: apply normalization, deduplication, SCD2, and enrichment.

Separation of concerns:
- Normalizers: rules that shape raw records into canonical form
- SCD handlers: detect changes and emit versioned rows
- Enrichers: add computed fields (hashes, geo codes, risk tiers)
"""

from src.pipelines.transformers.enrichers import compute_row_hash, enrich_commercial
from src.pipelines.transformers.normalizers import (
    NormalizationResult,
    normalize_commercial,
    normalize_legal,
)
from src.pipelines.transformers.scd2 import Scd2Handler

__all__ = [
    "NormalizationResult",
    "Scd2Handler",
    "compute_row_hash",
    "enrich_commercial",
    "normalize_commercial",
    "normalize_legal",
]
