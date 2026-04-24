"""create partitions and materialized views

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-24 00:01:00

Creates:
- 12 months of partitions for legal_documents and transactions
- Default partitions
- create_monthly_partition helper function
- Materialized views for analytics
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Helper function for monthly partition creation
    op.execute("""
        CREATE OR REPLACE FUNCTION create_monthly_partition(
            parent_table   TEXT,
            partition_date DATE
        )
        RETURNS TEXT
        LANGUAGE plpgsql
        AS $$
        DECLARE
            start_date DATE := date_trunc('month', partition_date)::DATE;
            end_date   DATE := (date_trunc('month', partition_date)
                                + INTERVAL '1 month')::DATE;
            part_name  TEXT := parent_table || '_' ||
                               to_char(start_date, 'YYYY_MM');
        BEGIN
            EXECUTE format(
                'CREATE TABLE IF NOT EXISTS %I PARTITION OF %I
                    FOR VALUES FROM (%L) TO (%L)',
                part_name, parent_table, start_date, end_date
            );
            RETURN part_name;
        END;
        $$;
    """)

    # Create partitions for past 6 months and next 12 months
    op.execute("""
        DO $$
        DECLARE
            m INT;
            d DATE;
        BEGIN
            FOR m IN -6..11 LOOP
                d := (date_trunc('month', CURRENT_DATE)
                      + (m || ' month')::INTERVAL)::DATE;
                PERFORM create_monthly_partition('legal_documents', d);
                PERFORM create_monthly_partition('transactions',    d);
            END LOOP;
        END $$;
    """)

    # Default partitions
    op.execute(
        "CREATE TABLE IF NOT EXISTS legal_documents_default "
        "PARTITION OF legal_documents DEFAULT"
    )
    op.execute(
        "CREATE TABLE IF NOT EXISTS transactions_default "
        "PARTITION OF transactions DEFAULT"
    )

    # Materialized view: monthly revenue per counterparty
    op.execute("""
        CREATE MATERIALIZED VIEW mv_monthly_revenue_per_counterparty AS
        SELECT
            c.external_id                                  AS counterparty_external_id,
            c.name                                         AS counterparty_name,
            c.country_code,
            date_trunc('month', t.transaction_date)::DATE  AS month,
            t.currency,
            COUNT(*)                                       AS transaction_count,
            SUM(t.amount)                                  AS total_amount,
            AVG(t.amount)                                  AS avg_amount
        FROM transactions t
        JOIN counterparties c ON c.id = t.counterparty_id
        WHERE t.transaction_type IN ('INVOICE', 'PAYMENT', 'REFUND')
        GROUP BY c.external_id, c.name, c.country_code,
                 date_trunc('month', t.transaction_date), t.currency
        WITH NO DATA;
    """)
    op.execute(
        "CREATE UNIQUE INDEX ux_mv_revenue_key "
        "ON mv_monthly_revenue_per_counterparty "
        "(counterparty_external_id, month, currency)"
    )

    # Refresh procedure
    op.execute("""
        CREATE OR REPLACE PROCEDURE refresh_analytical_views()
        LANGUAGE plpgsql
        AS $$
        BEGIN
            REFRESH MATERIALIZED VIEW CONCURRENTLY
                mv_monthly_revenue_per_counterparty;
        END;
        $$;
    """)


def downgrade() -> None:
    op.execute("DROP PROCEDURE IF EXISTS refresh_analytical_views()")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_monthly_revenue_per_counterparty")
    op.execute("DROP FUNCTION IF EXISTS create_monthly_partition(TEXT, DATE)")
