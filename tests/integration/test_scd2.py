"""Integration tests for the SCD Type 2 handler against real PostgreSQL."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import text

from src.pipelines.transformers.scd2 import Scd2Config, Scd2Handler

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def scd2_handler(db_session):
    # Clean any prior test data in dim_counterparty
    await db_session.execute(text("TRUNCATE dim_counterparty"))
    return Scd2Handler(
        session=db_session,
        config=Scd2Config(
            table="dim_counterparty",
            natural_key="external_id",
            tracked_fields=["name", "country_code", "risk_score"],
            insert_fields=[
                "external_id",
                "name",
                "tax_id",
                "country_code",
                "risk_score",
                "attributes",
            ],
        ),
    )


async def _count_versions(db_session, external_id: str) -> int:
    result = await db_session.execute(
        text("SELECT count(*) FROM dim_counterparty WHERE external_id = :eid"), {"eid": external_id}
    )
    return result.scalar_one()


async def _current_version(db_session, external_id: str) -> dict | None:
    result = await db_session.execute(
        text("""
        SELECT external_id, name, country_code, risk_score, valid_from, valid_to, is_current
        FROM dim_counterparty
        WHERE external_id = :eid AND is_current = true
    """),
        {"eid": external_id},
    )
    row = result.first()
    return dict(row._mapping) if row else None


async def test_new_entity_is_inserted_as_current(db_session, scd2_handler):
    record = {
        "external_id": "CP-NEW-1",
        "name": "Alpha Corp",
        "tax_id": "TAX-001",
        "country_code": "US",
        "risk_score": Decimal("25.00"),
        "attributes": {"source": "test"},
    }
    result = await scd2_handler.apply([record], effective_date=date(2025, 1, 1))

    assert result == {"inserted": 1, "expired": 0, "unchanged": 0}
    assert await _count_versions(db_session, "CP-NEW-1") == 1
    current = await _current_version(db_session, "CP-NEW-1")
    assert current["is_current"] is True
    assert current["valid_from"] == date(2025, 1, 1)


async def test_unchanged_record_does_not_create_new_version(db_session, scd2_handler):
    record = {
        "external_id": "CP-NEW-2",
        "name": "Beta Corp",
        "tax_id": "TAX-002",
        "country_code": "DE",
        "risk_score": Decimal("50.00"),
        "attributes": {},
    }
    await scd2_handler.apply([record], effective_date=date(2025, 1, 1))

    # Re-apply the same record
    result = await scd2_handler.apply([record], effective_date=date(2025, 6, 1))
    assert result == {"inserted": 0, "expired": 0, "unchanged": 1}
    assert await _count_versions(db_session, "CP-NEW-2") == 1


async def test_changed_record_expires_old_and_inserts_new(db_session, scd2_handler):
    # Version 1
    v1 = {
        "external_id": "CP-NEW-3",
        "name": "Gamma Ltd",
        "tax_id": "TAX-003",
        "country_code": "UK",
        "risk_score": Decimal("30.00"),
        "attributes": {},
    }
    await scd2_handler.apply([v1], effective_date=date(2025, 1, 1))

    # Version 2 — risk_score changed
    v2 = {**v1, "risk_score": Decimal("75.00")}
    result = await scd2_handler.apply([v2], effective_date=date(2025, 6, 15))
    assert result == {"inserted": 1, "expired": 1, "unchanged": 0}

    assert await _count_versions(db_session, "CP-NEW-3") == 2

    # The old row should be expired (is_current=false, valid_to = day before)
    old = await db_session.execute(
        text("""
        SELECT is_current, valid_to FROM dim_counterparty
        WHERE external_id = 'CP-NEW-3' AND risk_score = 30.00
    """)
    )
    old_row = old.first()
    assert old_row[0] is False
    assert old_row[1] == date(2025, 6, 14)  # day before effective_date

    # The new row should be current
    current = await _current_version(db_session, "CP-NEW-3")
    assert current["is_current"] is True
    assert float(current["risk_score"]) == 75.00
    assert current["valid_from"] == date(2025, 6, 15)


async def test_point_in_time_query_returns_version_at_date(db_session, scd2_handler):
    """Prove that SCD2 enables point-in-time queries."""
    v1 = {
        "external_id": "CP-PIT",
        "name": "Delta Inc",
        "tax_id": "TAX-PIT",
        "country_code": "FR",
        "risk_score": Decimal("10.00"),
        "attributes": {},
    }
    await scd2_handler.apply([v1], effective_date=date(2025, 1, 1))
    await scd2_handler.apply(
        [{**v1, "risk_score": Decimal("40.00")}],
        effective_date=date(2025, 6, 1),
    )
    await scd2_handler.apply(
        [{**v1, "risk_score": Decimal("90.00")}],
        effective_date=date(2025, 11, 1),
    )

    # "What was the risk score on 2025-03-15?" → should be 10
    result = await db_session.execute(
        text("""
        SELECT risk_score FROM dim_counterparty
        WHERE external_id = 'CP-PIT'
          AND :query_date BETWEEN valid_from AND valid_to
    """),
        {"query_date": date(2025, 3, 15)},
    )
    assert float(result.scalar_one()) == 10.00

    # "On 2025-07-20?" → 40
    result = await db_session.execute(
        text("""
        SELECT risk_score FROM dim_counterparty
        WHERE external_id = 'CP-PIT'
          AND :query_date BETWEEN valid_from AND valid_to
    """),
        {"query_date": date(2025, 7, 20)},
    )
    assert float(result.scalar_one()) == 40.00

    # "Today (current)?" → 90
    current = await _current_version(db_session, "CP-PIT")
    assert float(current["risk_score"]) == 90.00
