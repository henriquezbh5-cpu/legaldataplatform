"""Commercial domain models: contracts, counterparties, transactions."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.models.base import Base, TimestampMixin


class Counterparty(Base, TimestampMixin):
    """Commercial counterparties (clients, vendors, partners)."""

    __tablename__ = "counterparties"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    external_id: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    tax_id: Mapped[str | None] = mapped_column(String(50), index=True)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    risk_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)

    contracts: Mapped[list["Contract"]] = relationship(back_populates="counterparty")
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="counterparty")

    __table_args__ = (
        UniqueConstraint("external_id", name="uq_counterparty_external_id"),
        CheckConstraint("risk_score BETWEEN 0 AND 100", name="ck_counterparty_risk_range"),
        Index("ix_counterparty_country_risk", "country_code", "risk_score"),
    )


class Contract(Base, TimestampMixin):
    """Commercial contracts linked to counterparties and optionally regulations."""

    __tablename__ = "contracts"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    contract_number: Mapped[str] = mapped_column(String(100), nullable=False)
    counterparty_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("counterparties.id"), nullable=False, index=True
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date)
    total_value: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="DRAFT", nullable=False)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)

    counterparty: Mapped[Counterparty] = relationship(back_populates="contracts")
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="contract")

    __table_args__ = (
        UniqueConstraint("contract_number", name="uq_contract_number"),
        CheckConstraint("total_value >= 0", name="ck_contract_value_positive"),
        CheckConstraint(
            "end_date IS NULL OR end_date >= start_date",
            name="ck_contract_date_order",
        ),
        Index("ix_contract_status_dates", "status", "start_date", "end_date"),
        # Partial index: only active contracts — reduces index size dramatically
        Index(
            "ix_contract_active",
            "counterparty_id",
            postgresql_where="status = 'ACTIVE'",
        ),
    )


class Transaction(Base, TimestampMixin):
    """Financial transactions associated with contracts.

    Partitioned by `transaction_date` (RANGE monthly) — high-volume table.
    """

    __tablename__ = "transactions"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    transaction_date: Mapped[date] = mapped_column(Date, primary_key=True, nullable=False)
    contract_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("contracts.id"), nullable=False, index=True
    )
    counterparty_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("counterparties.id"), nullable=False, index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    transaction_type: Mapped[str] = mapped_column(String(30), nullable=False)
    reference: Mapped[str] = mapped_column(String(200), nullable=False)
    source_system: Mapped[str] = mapped_column(String(50), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)

    contract: Mapped[Contract] = relationship(back_populates="transactions")
    counterparty: Mapped[Counterparty] = relationship(back_populates="transactions")

    __table_args__ = (
        UniqueConstraint(
            "source_system",
            "reference",
            "transaction_date",
            name="uq_transaction_source_ref",
        ),
        CheckConstraint("amount <> 0", name="ck_transaction_amount_nonzero"),
        Index("ix_txn_counterparty_date", "counterparty_id", "transaction_date"),
        Index("ix_txn_contract_date", "contract_id", "transaction_date"),
        {"postgresql_partition_by": "RANGE (transaction_date)"},
    )
