"""Staging tables: landing zone for raw ingested data.

Staging tables are unlogged (UNLOGGED) for faster writes since data is
transient — if lost, we re-ingest from the Bronze S3 layer. Production DDL
sets UNLOGGED via migration.
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.database.models.base import Base


class StagingLegalDocument(Base):
    """Raw legal documents from extractors, before normalization."""

    __tablename__ = "stg_legal_document"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    batch_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_system: Mapped[str] = mapped_column(String(50), nullable=False)
    source_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    raw_text: Mapped[str | None] = mapped_column(Text)
    extracted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    processed: Mapped[bool] = mapped_column(default=False, nullable=False)

    __table_args__ = (Index("ix_stg_legal_batch_processed", "batch_id", "processed"),)


class StagingTransaction(Base):
    """Raw transactions from extractors."""

    __tablename__ = "stg_transaction"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    batch_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_system: Mapped[str] = mapped_column(String(50), nullable=False)
    source_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    extracted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    processed: Mapped[bool] = mapped_column(default=False, nullable=False)

    __table_args__ = (Index("ix_stg_txn_batch_processed", "batch_id", "processed"),)
