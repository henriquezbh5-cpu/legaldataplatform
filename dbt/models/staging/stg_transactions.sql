-- Staging view over the raw `transactions` table. Normalizes naming, casts
-- types explicitly, and drops ingestion-only columns. Downstream models
-- consume this view instead of `public.transactions` directly so that a
-- source rename or re-partitioning does not ripple through gold models.

WITH src AS (
    SELECT
        id                        AS transaction_id,
        transaction_date,
        contract_id,
        counterparty_id,
        amount::numeric(18, 2)    AS amount,
        upper(currency)           AS currency,
        upper(transaction_type)   AS transaction_type,
        reference,
        source_system,
        ingested_at
    FROM {{ source('public', 'transactions') }}
)

SELECT *
FROM src
WHERE amount <> 0
