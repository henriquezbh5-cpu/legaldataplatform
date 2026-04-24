"""Normalizers: validate raw records against Pydantic schemas and separate
valid from rejected records.

The "Source of Truth" principle demands that only records passing validation
reach the curated layer. Rejected records go to quarantine with the reason.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError

from src.observability import get_logger, records_quarantined
from src.schemas.commercial import (
    ContractSchema,
    CounterpartySchema,
    TransactionSchema,
)
from src.schemas.legal import (
    LegalDocumentSchema,
    LegalEntitySchema,
    RegulationSchema,
)

logger = get_logger(__name__)


@dataclass
class NormalizationResult:
    """Output of a normalization pass: valid + rejected records."""

    valid: list[dict[str, Any]] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)

    @property
    def valid_count(self) -> int:
        return len(self.valid)

    @property
    def rejected_count(self) -> int:
        return len(self.rejected)

    @property
    def rejection_rate(self) -> float:
        total = self.valid_count + self.rejected_count
        return self.rejected_count / total if total else 0.0


def _apply_schema(
    records: list[dict[str, Any]],
    schema: type[BaseModel],
    pipeline: str,
) -> NormalizationResult:
    result = NormalizationResult()
    for raw in records:
        try:
            obj = schema.model_validate(raw)
            result.valid.append(obj.model_dump(by_alias=True))
        except ValidationError as e:
            rejected = {
                "raw": raw,
                "errors": e.errors(),
                "schema": schema.__name__,
            }
            result.rejected.append(rejected)
            records_quarantined.labels(pipeline=pipeline, rule=schema.__name__).inc()

    if result.rejected_count:
        logger.warning(
            "normalizer.rejections",
            schema=schema.__name__,
            rejected=result.rejected_count,
            valid=result.valid_count,
            rate=round(result.rejection_rate, 4),
        )
    return result


def normalize_legal(kind: str, records: list[dict[str, Any]], pipeline: str) -> NormalizationResult:
    """Normalize legal domain records.

    `kind` is one of: 'document', 'entity', 'regulation'.
    """
    schemas = {
        "document": LegalDocumentSchema,
        "entity": LegalEntitySchema,
        "regulation": RegulationSchema,
    }
    if kind not in schemas:
        raise ValueError(f"Unknown legal kind: {kind}")
    return _apply_schema(records, schemas[kind], pipeline)


def normalize_commercial(
    kind: str, records: list[dict[str, Any]], pipeline: str
) -> NormalizationResult:
    """Normalize commercial records.

    `kind` is one of: 'counterparty', 'contract', 'transaction'.
    """
    schemas = {
        "counterparty": CounterpartySchema,
        "contract": ContractSchema,
        "transaction": TransactionSchema,
    }
    if kind not in schemas:
        raise ValueError(f"Unknown commercial kind: {kind}")
    return _apply_schema(records, schemas[kind], pipeline)
