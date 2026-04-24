"""Integration tests for COPY bulk + UPSERT staging against real PostgreSQL."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text

from src.pipelines.loaders.postgres_bulk import PostgresBulkLoader

pytestmark = pytest.mark.asyncio


async def test_copy_records_inserts_rows(db_session):
    """COPY should stream records directly into the staging table."""
    # Use a TEMP table to avoid polluting the partitioned legal_documents
    await db_session.execute(
        text("""
        CREATE TEMP TABLE copy_test (
            id UUID PRIMARY KEY,
            name TEXT NOT NULL,
            amount NUMERIC(10, 2),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    )

    loader = PostgresBulkLoader(
        session=db_session,
        table="copy_test",
        columns=["id", "name", "amount"],
        pipeline="integration_test",
    )

    records = [
        {"id": str(uuid4()), "name": "Alpha", "amount": "100.50"},
        {"id": str(uuid4()), "name": "Beta", "amount": "250.00"},
        {"id": str(uuid4()), "name": "Gamma", "amount": "-15.75"},
    ]
    rows_written = await loader.copy_records(records)
    assert rows_written == 3

    count = (await db_session.execute(text("SELECT count(*) FROM copy_test"))).scalar_one()
    assert count == 3


async def test_upsert_via_staging_updates_on_conflict(db_session):
    """The UPSERT pattern should update existing rows and insert new ones."""
    # Create a real target table with a unique constraint
    await db_session.execute(
        text("""
        CREATE TEMP TABLE upsert_test (
            external_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            risk_score NUMERIC(5, 2),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    )

    # Seed one row
    await db_session.execute(
        text("""
        INSERT INTO upsert_test (external_id, name, risk_score)
        VALUES ('CP-1', 'Original Name', 10.00)
    """)
    )

    loader = PostgresBulkLoader(
        session=db_session,
        table="upsert_test",
        columns=["external_id", "name", "risk_score"],
        pipeline="integration_test",
    )

    records = [
        {"external_id": "CP-1", "name": "Updated Name", "risk_score": "42.50"},  # update
        {"external_id": "CP-2", "name": "New Entity", "risk_score": "5.00"},  # insert
    ]
    rows = await loader.upsert_via_staging(
        records,
        conflict_columns=["external_id"],
        update_columns=["external_id", "name", "risk_score"],
    )
    assert rows == 2

    result = await db_session.execute(
        text("SELECT external_id, name, risk_score FROM upsert_test ORDER BY external_id")
    )
    rows_out = result.all()
    assert rows_out[0][0] == "CP-1"
    assert rows_out[0][1] == "Updated Name"
    assert float(rows_out[0][2]) == 42.50
    assert rows_out[1][0] == "CP-2"


async def test_copy_handles_special_characters(db_session):
    """CSV serialization must escape commas, quotes, newlines safely."""
    await db_session.execute(
        text("""
        CREATE TEMP TABLE special_chars (
            id UUID PRIMARY KEY,
            text_value TEXT
        )
    """)
    )

    loader = PostgresBulkLoader(
        session=db_session,
        table="special_chars",
        columns=["id", "text_value"],
        pipeline="integration_test",
    )

    records = [
        {"id": str(uuid4()), "text_value": 'Value with "quotes" inside'},
        {"id": str(uuid4()), "text_value": "Value, with, commas"},
        {"id": str(uuid4()), "text_value": "Line1\nLine2"},
        {"id": str(uuid4()), "text_value": "UTF-8: ñ á é ü ✓"},
    ]
    rows = await loader.copy_records(records)
    assert rows == 4

    # Verify content round-trip
    result = await db_session.execute(
        text("SELECT text_value FROM special_chars ORDER BY text_value")
    )
    values = [r[0] for r in result.all()]
    assert 'Value with "quotes" inside' in values
    assert any("✓" in v for v in values)


async def test_copy_jsonb_column(db_session):
    """Dicts should be serialized as JSON and round-trip through JSONB."""
    await db_session.execute(
        text("""
        CREATE TEMP TABLE jsonb_test (
            id UUID PRIMARY KEY,
            data JSONB NOT NULL
        )
    """)
    )

    loader = PostgresBulkLoader(
        session=db_session,
        table="jsonb_test",
        columns=["id", "data"],
        pipeline="integration_test",
    )

    records = [
        {"id": str(uuid4()), "data": {"key": "value", "nested": {"a": 1}}},
        {"id": str(uuid4()), "data": {"list": [1, 2, 3], "bool": True}},
    ]
    await loader.copy_records(records)

    result = await db_session.execute(
        text("SELECT data->>'key' FROM jsonb_test WHERE data ? 'key'")
    )
    assert result.scalar_one() == "value"
