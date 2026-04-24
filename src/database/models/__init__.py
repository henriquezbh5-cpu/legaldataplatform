"""SQLAlchemy ORM models.

Organized by domain:
    - base:       Declarative base + mixins
    - legal:      Legal documents, regulations, case law
    - commercial: Contracts, transactions, counterparties
    - dim:        Dimension tables (SCD2)
    - staging:    Landing tables for raw ingestion
"""

from src.database.models.base import Base, TimestampMixin
from src.database.models.commercial import Contract, Counterparty, Transaction
from src.database.models.dim import DimCounterparty, DimJurisdiction
from src.database.models.legal import LegalDocument, LegalEntity, Regulation
from src.database.models.staging import StagingLegalDocument, StagingTransaction

__all__ = [
    "Base",
    "Contract",
    "Counterparty",
    "DimCounterparty",
    "DimJurisdiction",
    "LegalDocument",
    "LegalEntity",
    "Regulation",
    "StagingLegalDocument",
    "StagingTransaction",
    "TimestampMixin",
    "Transaction",
]
