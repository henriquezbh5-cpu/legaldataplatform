-- =============================================================================
-- Materialized Views for analytical workloads
-- =============================================================================
-- Materialized views pre-compute expensive aggregations and are refreshed
-- CONCURRENTLY (no blocking reads) on a schedule.
-- =============================================================================

-- Monthly revenue per counterparty (joins transactions + dim_counterparty SCD2)
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_monthly_revenue_per_counterparty AS
SELECT
    dc.external_id                     AS counterparty_external_id,
    dc.name                            AS counterparty_name,
    dc.country_code,
    date_trunc('month', t.transaction_date)::DATE AS month,
    t.currency,
    COUNT(*)                           AS transaction_count,
    SUM(t.amount)                      AS total_amount,
    AVG(t.amount)                      AS avg_amount,
    MIN(t.amount)                      AS min_amount,
    MAX(t.amount)                      AS max_amount
FROM transactions t
JOIN dim_counterparty dc
     ON dc.external_id = (
         SELECT external_id FROM counterparties c WHERE c.id = t.counterparty_id
     )
    AND t.transaction_date BETWEEN dc.valid_from AND dc.valid_to
WHERE t.transaction_type IN ('INVOICE', 'PAYMENT', 'REFUND')
GROUP BY
    dc.external_id, dc.name, dc.country_code,
    date_trunc('month', t.transaction_date),
    t.currency
WITH NO DATA;

CREATE UNIQUE INDEX IF NOT EXISTS ux_mv_revenue_key
    ON mv_monthly_revenue_per_counterparty (counterparty_external_id, month, currency);

-- Active regulations with affected entities count
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_active_regulations_by_jurisdiction AS
SELECT
    r.jurisdiction,
    r.category,
    COUNT(DISTINCT r.id)                                AS regulation_count,
    COUNT(DISTINCT ld.entity_id) FILTER (WHERE ld.id IS NOT NULL) AS affected_entities
FROM regulations r
LEFT JOIN legal_documents ld
       ON ld.jurisdiction = r.jurisdiction
      AND ld.metadata @> jsonb_build_object('regulation_code', r.code)
WHERE r.effective_from <= CURRENT_DATE
  AND (r.effective_to IS NULL OR r.effective_to >= CURRENT_DATE)
GROUP BY r.jurisdiction, r.category
WITH NO DATA;

CREATE UNIQUE INDEX IF NOT EXISTS ux_mv_regulations_key
    ON mv_active_regulations_by_jurisdiction (jurisdiction, category);

-- Refresh procedure (to be called from cron or Prefect)
CREATE OR REPLACE PROCEDURE refresh_analytical_views()
LANGUAGE plpgsql
AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY mv_monthly_revenue_per_counterparty;
    REFRESH MATERIALIZED VIEW CONCURRENTLY mv_active_regulations_by_jurisdiction;
END;
$$;
