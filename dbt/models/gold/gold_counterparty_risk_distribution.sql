{{ config(
    materialized='table',
    indexes=[
      {'columns': ['country_code', 'risk_tier']},
      {'columns': ['risk_tier']}
    ]
) }}

-- Distribution of counterparties by country and risk tier. Feeds executive
-- dashboards that show geographic + risk exposure at a glance.

WITH cp AS (
    SELECT
        counterparty_id,
        name,
        country_code,
        source_origin,
        risk_score,
        CASE
            WHEN risk_score IS NULL          THEN 'UNKNOWN'
            WHEN risk_score <  25            THEN 'LOW'
            WHEN risk_score <  50            THEN 'MODERATE'
            WHEN risk_score <  75            THEN 'HIGH'
            ELSE                                  'CRITICAL'
        END AS risk_tier
    FROM {{ ref('stg_counterparties') }}
)

SELECT
    country_code,
    source_origin,
    risk_tier,
    count(*)                              AS counterparty_count,
    round(avg(risk_score)::numeric, 2)    AS avg_risk_score,
    min(risk_score)                       AS min_risk_score,
    max(risk_score)                       AS max_risk_score
FROM cp
GROUP BY country_code, source_origin, risk_tier
