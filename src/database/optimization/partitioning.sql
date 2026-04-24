-- =============================================================================
-- Partitioning Strategy
-- =============================================================================
-- legal_documents and transactions are partitioned by RANGE (date) monthly.
-- Rationale:
--   - Pruning: planner skips irrelevant partitions automatically
--   - Maintenance: VACUUM / REINDEX per partition, not full table
--   - Retention: DROP PARTITION is O(1) vs DELETE which is expensive
--   - Parallel scans: PostgreSQL can scan partitions in parallel
-- =============================================================================

-- Helper function to create a monthly partition
CREATE OR REPLACE FUNCTION create_monthly_partition(
    parent_table   TEXT,
    partition_date DATE
)
RETURNS TEXT
LANGUAGE plpgsql
AS $$
DECLARE
    start_date DATE := date_trunc('month', partition_date)::DATE;
    end_date   DATE := (date_trunc('month', partition_date) + INTERVAL '1 month')::DATE;
    part_name  TEXT := parent_table || '_' || to_char(start_date, 'YYYY_MM');
    sql_stmt   TEXT;
BEGIN
    sql_stmt := format(
        'CREATE TABLE IF NOT EXISTS %I PARTITION OF %I
            FOR VALUES FROM (%L) TO (%L)',
        part_name, parent_table, start_date, end_date
    );
    EXECUTE sql_stmt;
    RETURN part_name;
END;
$$;

-- Pre-create partitions for the next 12 months for both partitioned tables
DO $$
DECLARE
    m INT;
    d DATE;
BEGIN
    FOR m IN 0..11 LOOP
        d := (date_trunc('month', CURRENT_DATE) + (m || ' month')::INTERVAL)::DATE;
        PERFORM create_monthly_partition('legal_documents', d);
        PERFORM create_monthly_partition('transactions',    d);
    END LOOP;
END $$;

-- Default partition catches rows outside expected ranges (flagged for review)
CREATE TABLE IF NOT EXISTS legal_documents_default PARTITION OF legal_documents DEFAULT;
CREATE TABLE IF NOT EXISTS transactions_default    PARTITION OF transactions    DEFAULT;
