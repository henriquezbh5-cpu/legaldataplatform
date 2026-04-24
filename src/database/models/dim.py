"""Dimension tables using Slowly Changing Dimension Type 2 (SCD2).

SCD2 preserves historical state by maintaining multiple versions of a row
with valid_from / valid_to / is_current flags. This allows point-in-time
queries: "what was this counterparty's risk score as of 2024-06-01?"
"""
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import Boolean, Date, DateTime, Index, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.database.models.base import Base


class DimCounterparty(Base):
    """SCD2 dimension for counterparties.

    Natural key: external_id. Surrogate key: id.
    Each change generates a new row with updated valid_from and marks the
    previous version valid_to = (change_date - 1 day), is_current = false.
    """

    __tablename__ = "dim_counterparty"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    external_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    tax_id: Mapped[str | None] = mapped_column(String(50))
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    risk_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    attributes: Mapped[dict] = mapped_column(JSONB, default=dict)

    # SCD2 fields
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date] = mapped_column(Date, nullable=False, default=date(9999, 12, 31))
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    row_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    loaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "external_id", "valid_from",
            name="uq_dim_counterparty_version",
        ),
        Index(
            "ix_dim_counterparty_current",
            "external_id",
            postgresql_where="is_current = true",
        ),
        Index(
            "ix_dim_counterparty_valid_range",
            "external_id", "valid_from", "valid_to",
        ),
    )


class DimJurisdiction(Base):
    """Lookup dimension for jurisdictions — SCD Type 1 (overwrite)."""

    __tablename__ = "dim_jurisdiction"

    code: Mapped[str] = mapped_column(String(10), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    legal_system: Mapped[str] = mapped_column(String(50), nullable=False)
    attributes: Mapped[dict] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
