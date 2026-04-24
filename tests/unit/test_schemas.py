"""Tests for Pydantic validation."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.schemas.commercial import (
    ContractSchema,
    CounterpartySchema,
    TransactionSchema,
)
from src.schemas.legal import LegalDocumentSchema, LegalEntitySchema


class TestLegalDocumentSchema:
    def test_normalizes_document_type_to_upper(self):
        doc = LegalDocumentSchema(
            document_date=date(2025, 1, 1),
            source_system="courts",
            source_id="1",
            source_hash="a" * 64,
            document_type="judgment",
            title="test",
            jurisdiction="US-NY",
        )
        assert doc.document_type == "JUDGMENT"

    def test_deduplicates_and_lowercases_tags(self):
        doc = LegalDocumentSchema(
            document_date=date(2025, 1, 1),
            source_system="courts",
            source_id="1",
            source_hash="a" * 64,
            document_type="NOTICE",
            title="t",
            jurisdiction="US-NY",
            tags=["Foo", "foo", " BAR ", "bar"],
        )
        assert doc.tags == ["foo", "bar"]

    def test_rejects_short_hash(self):
        with pytest.raises(ValidationError):
            LegalDocumentSchema(
                document_date=date(2025, 1, 1),
                source_system="x",
                source_id="1",
                source_hash="short",
                document_type="NOTICE",
                title="t",
                jurisdiction="US-NY",
            )


class TestLegalEntitySchema:
    def test_normalizes_legal_name(self):
        e = LegalEntitySchema(
            tax_id="12345",
            legal_name="  acme  corp  ",
            entity_type="LLC",
            jurisdiction="US-NY",
        )
        assert e.legal_name == "ACME CORP"

    def test_rejects_unknown_status(self):
        with pytest.raises(ValidationError):
            LegalEntitySchema(
                tax_id="12345",
                legal_name="acme",
                entity_type="LLC",
                jurisdiction="US",
                status="FROZEN",
            )


class TestTransactionSchema:
    def test_rejects_zero_amount(self):
        with pytest.raises(ValidationError):
            TransactionSchema(
                transaction_date=date(2025, 1, 1),
                contract_number="CT-1",
                counterparty_external_id="CP-1",
                amount=Decimal("0"),
                currency="USD",
                transaction_type="INVOICE",
                reference="R-1",
                source_system="erp",
            )

    def test_uppers_currency(self):
        t = TransactionSchema(
            transaction_date=date(2025, 1, 1),
            contract_number="CT-1",
            counterparty_external_id="CP-1",
            amount=Decimal("100"),
            currency="usd",
            transaction_type="invoice",
            reference="R-1",
            source_system="erp",
        )
        assert t.currency == "USD"
        assert t.transaction_type == "INVOICE"


class TestContractSchema:
    def test_rejects_negative_value(self):
        with pytest.raises(ValidationError):
            ContractSchema(
                contract_number="CT-1",
                counterparty_external_id="CP-1",
                start_date=date(2025, 1, 1),
                total_value=Decimal("-1"),
                currency="USD",
            )


class TestCounterpartySchema:
    def test_rejects_risk_out_of_range(self):
        with pytest.raises(ValidationError):
            CounterpartySchema(
                external_id="CP-1",
                name="x",
                country_code="US",
                risk_score=Decimal("150"),
            )
