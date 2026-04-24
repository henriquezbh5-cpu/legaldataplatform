"""Pydantic schemas for the commercial domain."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

ISOCurrency = Annotated[str, StringConstraints(min_length=3, max_length=3, to_upper=True)]
CountryCode = Annotated[str, StringConstraints(min_length=2, max_length=2, to_upper=True)]


class CounterpartySchema(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    external_id: Annotated[str, Field(min_length=1, max_length=100)]
    name: Annotated[str, Field(min_length=1, max_length=500)]
    tax_id: str | None = None
    country_code: CountryCode
    risk_score: Decimal | None = None
    metadata_: dict = Field(default_factory=dict, alias="metadata")

    @field_validator("risk_score")
    @classmethod
    def _range(cls, v: Decimal | None) -> Decimal | None:
        if v is not None and not (0 <= v <= 100):
            raise ValueError("risk_score must be between 0 and 100")
        return v


class ContractSchema(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    contract_number: Annotated[str, Field(min_length=1, max_length=100)]
    counterparty_external_id: Annotated[str, Field(min_length=1, max_length=100)]
    start_date: date
    end_date: date | None = None
    total_value: Decimal = Field(ge=0)
    currency: ISOCurrency
    status: str = "DRAFT"
    metadata_: dict = Field(default_factory=dict, alias="metadata")

    @field_validator("status")
    @classmethod
    def _valid_status(cls, v: str) -> str:
        allowed = {"DRAFT", "ACTIVE", "SUSPENDED", "TERMINATED", "EXPIRED"}
        up = v.upper()
        if up not in allowed:
            raise ValueError(f"status must be in {allowed}")
        return up


class TransactionSchema(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    transaction_date: date
    contract_number: Annotated[str, Field(min_length=1, max_length=100)]
    counterparty_external_id: Annotated[str, Field(min_length=1, max_length=100)]
    amount: Decimal
    currency: ISOCurrency
    transaction_type: Annotated[str, Field(min_length=1, max_length=30)]
    reference: Annotated[str, Field(min_length=1, max_length=200)]
    source_system: Annotated[str, Field(min_length=1, max_length=50)]
    ingested_at: datetime = Field(default_factory=datetime.utcnow)
    metadata_: dict = Field(default_factory=dict, alias="metadata")

    @field_validator("amount")
    @classmethod
    def _nonzero(cls, v: Decimal) -> Decimal:
        if v == 0:
            raise ValueError("amount cannot be zero")
        return v

    @field_validator("transaction_type")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper()
