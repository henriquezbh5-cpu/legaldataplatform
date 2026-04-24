{{ config(
    materialized='table',
    indexes=[
      {'columns': ['counterparty_id', 'month'], 'unique': true},
      {'columns': ['month']},
      {'columns': ['country_code']}
    ]
) }}

-- Monthly revenue per counterparty, with country and origin dimensions for
-- filtering in BI. Replaces mv_monthly_revenue_per_counterparty's role but
-- owned by dbt for lineage, tests and docs. The MV itself remains for
-- workloads that need CONCURRENT refresh without a dbt run.

WITH txns AS (
    SELECT
        counterparty_id,
        date_trunc('month', transaction_date)::date AS month,
        currency,
        transaction_type,
        amount
    FROM {{ ref('stg_transactions') }}
    WHERE transaction_type IN ('INVOICE', 'PAYMENT', 'REFUND')
),
cp AS (
    SELECT counterparty_id, name, country_code, source_origin
    FROM {{ ref('stg_counterparties') }}
)

SELECT
    cp.counterparty_id,
    cp.name                                   AS counterparty_name,
    cp.country_code,
    cp.source_origin,
    txns.month,
    txns.currency,
    count(*)                                  AS transaction_count,
    sum(txns.amount)::numeric(18, 2)          AS total_amount,
    avg(txns.amount)::numeric(18, 2)          AS avg_amount,
    min(txns.amount)::numeric(18, 2)          AS min_amount,
    max(txns.amount)::numeric(18, 2)          AS max_amount,
    sum(txns.amount) FILTER (WHERE txns.transaction_type = 'INVOICE')::numeric(18, 2)
        AS invoiced_amount,
    sum(txns.amount) FILTER (WHERE txns.transaction_type = 'PAYMENT')::numeric(18, 2)
        AS paid_amount,
    sum(txns.amount) FILTER (WHERE txns.transaction_type = 'REFUND')::numeric(18, 2)
        AS refunded_amount
FROM txns
JOIN cp USING (counterparty_id)
GROUP BY
    cp.counterparty_id, cp.name, cp.country_code, cp.source_origin,
    txns.month, txns.currency
