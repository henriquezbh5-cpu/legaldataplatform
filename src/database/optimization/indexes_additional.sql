-- =============================================================================
-- Additional indexes beyond what ORM models declare
-- =============================================================================
-- These support common query patterns identified during profiling.
-- Every index costs write-amplification, so each is justified below.
-- =============================================================================

-- (1) BRIN index on transactions.transaction_date
--     BRIN uses ~10KB per million rows vs ~30MB for BTREE.
--     Suitable when data is naturally clustered (time-ordered inserts).
CREATE INDEX IF NOT EXISTS ix_txn_date_brin
    ON transactions USING BRIN (transaction_date)
    WITH (pages_per_range = 32);

-- (2) Covering index for "sum by counterparty last 90 days" queries
CREATE INDEX IF NOT EXISTS ix_txn_counterparty_recent
    ON transactions (counterparty_id, transaction_date DESC)
    INCLUDE (amount, currency)
    WHERE transaction_date >= CURRENT_DATE - INTERVAL '90 days';

-- (3) Expression index for case-insensitive entity search
CREATE INDEX IF NOT EXISTS ix_entity_legal_name_lower
    ON legal_entities (lower(legal_name));

-- (4) JSONB path index for tag filtering on legal_documents
CREATE INDEX IF NOT EXISTS ix_legal_doc_tags_gin
    ON legal_documents USING GIN (tags);

CREATE INDEX IF NOT EXISTS ix_legal_doc_metadata_gin
    ON legal_documents USING GIN (metadata jsonb_path_ops);

-- (5) Partial index on open contracts (common filter)
CREATE INDEX IF NOT EXISTS ix_contract_open
    ON contracts (end_date, counterparty_id)
    WHERE status IN ('ACTIVE', 'PENDING');
