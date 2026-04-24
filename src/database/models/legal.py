"""Legal domain models.

Legal documents cover regulations, court decisions, and legal entities
(companies, individuals involved in cases). All documents are versioned
via source_hash to allow idempotent re-ingestion.
"""

from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import Date, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.models.base import Base, TimestampMixin


class LegalEntity(Base, TimestampMixin):
    """Companies or individuals referenced in legal documents."""

    __tablename__ = "legal_entities"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tax_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    legal_name: Mapped[str] = mapped_column(String(500), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    jurisdiction: Mapped[str] = mapped_column(String(100), nullable=False)
    registration_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE", nullable=False)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)

    documents: Mapped[list["LegalDocument"]] = relationship(back_populates="entity")

    __table_args__ = (
        UniqueConstraint("tax_id", "jurisdiction", name="uq_entity_tax_jurisdiction"),
        Index(
            "ix_entity_legal_name_gin",
            "legal_name",
            postgresql_using="gin",
            postgresql_ops={"legal_name": "gin_trgm_ops"},
        ),
    )


class LegalDocument(Base, TimestampMixin):
    """Legal documents (judgments, regulations, contracts registered publicly).

    Partitioned by `document_date` (RANGE) for performance at scale.
    """

    __tablename__ = "legal_documents"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    document_date: Mapped[date] = mapped_column(Date, primary_key=True, nullable=False)
    source_system: Mapped[str] = mapped_column(String(50), nullable=False)
    source_id: Mapped[str] = mapped_column(String(200), nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    document_type: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(1000), nullable=False)
    content: Mapped[str | None] = mapped_column(Text)
    jurisdiction: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("legal_entities.id"), index=True
    )
    tags: Mapped[list[str]] = mapped_column(JSONB, default=list)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    entity: Mapped[LegalEntity | None] = relationship(back_populates="documents")

    __table_args__ = (
        UniqueConstraint(
            "source_system",
            "source_id",
            "document_date",
            name="uq_legal_doc_source",
        ),
        Index("ix_legal_doc_date_type", "document_date", "document_type"),
        Index("ix_legal_doc_hash", "source_hash"),
        # Full-text search index on title (using GIN trigram for partial match)
        Index(
            "ix_legal_doc_title_gin",
            "title",
            postgresql_using="gin",
            postgresql_ops={"title": "gin_trgm_ops"},
        ),
        # PARTITION BY RANGE (document_date) applied via migration
        {"postgresql_partition_by": "RANGE (document_date)"},
    )


class Regulation(Base, TimestampMixin):
    """Normative regulations with effective-date ranges."""

    __tablename__ = "regulations"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    jurisdiction: Mapped[str] = mapped_column(String(100), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    content: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)

    __table_args__ = (
        UniqueConstraint("code", "jurisdiction", name="uq_regulation_code_jurisdiction"),
        Index("ix_regulation_effective_range", "effective_from", "effective_to"),
    )
