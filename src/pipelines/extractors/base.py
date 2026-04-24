"""Extractor contract and shared primitives."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4


@dataclass
class ExtractBatch:
    """A batch of extracted records plus lineage metadata.

    Lineage metadata is essential for debugging and reproducibility — every
    record can be traced back to its source, extraction time, and batch.
    """

    batch_id: str
    source_system: str
    source_name: str
    extracted_at: datetime
    records: list[dict[str, Any]]
    schema_version: str = "v1"
    checksum: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def new(
        cls,
        source_system: str,
        source_name: str,
        records: list[dict[str, Any]],
        **kwargs: Any,
    ) -> ExtractBatch:
        return cls(
            batch_id=str(uuid4()),
            source_system=source_system,
            source_name=source_name,
            extracted_at=datetime.utcnow(),
            records=records,
            **kwargs,
        )

    @property
    def size(self) -> int:
        return len(self.records)


class Extractor(ABC):
    """Base class for all extractors.

    Extractors yield batches asynchronously so that memory stays bounded
    even with large sources (streaming semantics).
    """

    source_system: str = "unknown"

    @abstractmethod
    async def extract(self) -> AsyncIterator[ExtractBatch]:
        """Yield batches of records."""
        yield  # type: ignore[misc]  # abstract
