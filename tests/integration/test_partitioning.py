"""Integration tests for the partitioned tables."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.asyncio


async def test_monthly_partitions_exist_for_transactions(db_session):
    """The 0002 migration should have created partitions around CURRENT_DATE."""
    result = await db_session.execute(
        text("""
        SELECT inhrelid::regclass::text AS partition_name
        FROM pg_inherits
        WHERE inhparent = 'transactions'::regclass
        ORDER BY partition_name
    """)
    )
    partitions = [r[0] for r in result.all()]

    # Expect at least the default and several monthly partitions
    assert any("default" in p for p in partitions)
    assert len([p for p in partitions if "_202" in p]) >= 12


async def test_create_monthly_partition_function_works(db_session):
    """The helper function should create new partitions idempotently."""
    # Pick a date far enough in the future that no partition exists yet
    future_date = date(2030, 6, 15)

    result = await db_session.execute(
        text("SELECT create_monthly_partition('transactions', :d)"), {"d": future_date}
    )
    partition_name = result.scalar_one()

    assert "2030_06" in partition_name

    # Calling again should be idempotent (CREATE IF NOT EXISTS)
    result2 = await db_session.execute(
        text("SELECT create_monthly_partition('transactions', :d)"), {"d": future_date}
    )
    assert result2.scalar_one() == partition_name

    # Cleanup
    await db_session.execute(text(f"DROP TABLE {partition_name}"))


async def test_partition_pruning_plan(db_session):
    """EXPLAIN should show that only the relevant partition is scanned."""
    result = await db_session.execute(
        text("""
        EXPLAIN (FORMAT TEXT)
        SELECT count(*) FROM transactions
        WHERE transaction_date = CURRENT_DATE
    """)
    )
    plan_text = "\n".join(r[0] for r in result.all())

    # The planner should NOT include all monthly partitions — only the one
    # matching CURRENT_DATE. We look for signs of pruning.
    partition_refs = plan_text.count("transactions_")
    assert partition_refs <= 3, f"Expected pruning to limit partitions scanned, got: {plan_text}"


async def test_legal_documents_is_partitioned(db_session):
    """legal_documents must also be RANGE-partitioned."""
    result = await db_session.execute(
        text("""
        SELECT count(*) FROM pg_inherits
        WHERE inhparent = 'legal_documents'::regclass
    """)
    )
    count = result.scalar_one()
    assert count >= 12  # default + at least 12 months


async def test_materialized_view_exists(db_session):
    """mv_monthly_revenue_per_counterparty should be present post-migration."""
    result = await db_session.execute(
        text("""
        SELECT 1 FROM pg_matviews
        WHERE matviewname = 'mv_monthly_revenue_per_counterparty'
    """)
    )
    assert result.scalar() == 1


async def test_refresh_analytical_views_procedure_runs(db_session):
    """The CALL refresh_analytical_views() procedure should execute cleanly."""
    # The procedure uses CONCURRENTLY which requires the MV to have at least
    # one populated snapshot; populate it first with an initial refresh.
    await db_session.execute(text("REFRESH MATERIALIZED VIEW mv_monthly_revenue_per_counterparty"))
    await db_session.commit()

    # Now the CONCURRENTLY refresh inside the procedure should work
    await db_session.execute(text("CALL refresh_analytical_views()"))
